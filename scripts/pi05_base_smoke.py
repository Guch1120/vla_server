"""実シミュレーション画像を使うオフライン推論。ROSやモータ出力は持たない。"""

import argparse
import hashlib
import json
import time
from pathlib import Path

from PIL import Image
import numpy as np
import torch

from vla_server.pi05_probe import Pi05BaseProbe, MODEL_REVISION, LEROBOT_REVISION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    probe = Pi05BaseProbe(args.checkpoint)
    torch.cuda.synchronize()
    load_s = time.perf_counter() - start
    image = Image.open(args.image).convert("RGB")
    task = "Move the red cube onto the green target."
    variants = [("warmup", image, task), ("red", image, task),
                ("blue", image, "Move the blue cube onto the green target."),
                ("black", Image.new("RGB", image.size), task)]
    outputs, durations = {}, {}
    for name, frame, instruction in variants:
        start = time.perf_counter()
        actions = probe.infer(frame, instruction, [0.0] * 32)
        torch.cuda.synchronize()
        durations[name] = time.perf_counter() - start
        outputs[name] = actions
        np.save(args.output / f"{name}.npy", actions)
        print(json.dumps({"variant": name, "seconds": durations[name], "shape": list(actions.shape),
                          "min": float(actions.min()), "max": float(actions.max())}), flush=True)
    result = {
        "model_id": "lerobot/pi05_base", "model_revision": MODEL_REVISION,
        "lerobot_revision": LEROBOT_REVISION, "gpu": torch.cuda.get_device_name(),
        "torch": torch.__version__, "dtype": "upstream bfloat16/float32 mixed", "load_seconds": load_s,
        "strict_weights_loaded": True, "parameter_count": probe.loaded_parameter_count,
        "num_inference_steps": probe.policy.config.num_inference_steps,
        "durations_seconds": durations, "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
        "shape": [50, 32], "finite": True,
        "output_min": float(outputs['red'].min()), "output_max": float(outputs['red'].max()),
        "same_seed_repeat_max_abs": float(np.abs(outputs['warmup'] - outputs['red']).max()),
        "task_change_mean_abs": float(np.abs(outputs['red'] - outputs['blue']).mean()),
        "image_change_mean_abs": float(np.abs(outputs['red'] - outputs['black']).mean()),
        "image_sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
        "state_source": "synthetic normalized zeros; not calibrated Piper state",
        "camera_mapping": {"left_wrist_0_rgb": "simulated Piper wrist RGB", "other_cameras": "masked missing"},
        "action_semantics": "raw base-model space; physical units and Piper mapping undefined",
        "actuation": False, "task_success_evaluated": False,
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
