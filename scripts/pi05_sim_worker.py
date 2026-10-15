"""ネットワークなしの推論側。実験用ファイルIPCのみでBridgeへ返す。"""

import base64
import io
import json
import time
from pathlib import Path

import torch
from PIL import Image
from vla_server.pi05_probe import Pi05BaseProbe, MODEL_REVISION
from vla_server.sim_projection import probe_state, project_chunk, SCHEMA

root = Path("/exchange")
torch.set_num_threads(4)
probe = Pi05BaseProbe(Path("/workspace/checkpoints/pi05_base"))
(root / "ready.json").write_text(
    json.dumps({"revision": MODEL_REVISION, "schema": SCHEMA})
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
    image = Image.open(io.BytesIO(base64.b64decode(obs["image_png"])))
    before = time.monotonic()
    actions = probe.infer(image, obs["task"], probe_state(obs["positions"]), seed=7)
    targets = project_chunk(actions.tolist(), obs["positions"])
    reply = {k: obs[k] for k in ("request_id", "stamp_ns", "epoch")}
    reply.update(
        schema=SCHEMA,
        targets=targets,
        inference_s=time.monotonic() - before,
        raw_first=actions[0].tolist(),
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
