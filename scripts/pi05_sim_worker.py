"""ネットワークなしの推論側。実験用ファイルIPCのみでBridgeへ返す。"""

import base64
import argparse
import io
import json
import time
from pathlib import Path

import torch
from PIL import Image
from vla_server.pi05_piper_task import Pi05PiperTask, MODEL_ID, MODEL_REVISION, SCHEMA

parser = argparse.ArgumentParser()
parser.add_argument("--exchange", type=Path, default=Path("/exchange"))
args = parser.parse_args()
root = args.exchange
torch.set_num_threads(4)
policy = Pi05PiperTask(
    Path("/models/pi05-piper-task"),
    Path("/workspace/checkpoints/pi05_base/paligemma_tokenizer.model"),
)
(root / "ready.json").write_text(
    json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION, "schema": SCHEMA, "stats_sha256": policy.stats_sha256})
)
seen = None
deadline = time.monotonic() + 900
while time.monotonic() < deadline and not (root / "shutdown").exists():
    try:
        obs = json.loads((root / "observation.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        time.sleep(0.05)
        continue
    if obs["request_id"] == seen:
        time.sleep(0.05)
        continue
    seen = obs["request_id"]
    if time.time_ns() - obs["sent_wall_ns"] > 5_000_000_000:
        continue
    ee_image = Image.open(io.BytesIO(base64.b64decode(obs["ee_image_png"])))
    external_image = Image.open(io.BytesIO(base64.b64decode(obs["external_image_png"])))
    before = time.monotonic()
    targets, raw_actions = policy.infer(ee_image, external_image, obs["positions"], seed=7)
    reply = {k: obs[k] for k in ("request_id", "stamp_ns", "epoch")}
    reply.update(
        schema=SCHEMA,
        targets=targets,
        inference_s=time.monotonic() - before,
        action_mode="absolute_joint_positions",
        unclamped_first=raw_actions[0],
        model_revision=MODEL_REVISION,
    )
    (root / "response.tmp").write_text(json.dumps(reply))
    (root / "response.tmp").replace(root / "response.json")
    print(
        json.dumps(
            {
                "request_id": seen,
                "inference_s": reply["inference_s"],
                "first_target": targets[0],
            }
        ),
        flush=True,
    )
