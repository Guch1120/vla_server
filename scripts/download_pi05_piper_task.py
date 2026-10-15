"""固定revisionの公開Piper π₀.₅ checkpointを取得し、取得物manifestを保存する。"""

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_ID = "samithva/task_e_pi05"
MODEL_REVISION = "c235d95044981460f7fb1984b01379899e68a4e4"

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=Path("/models/pi05-piper-task"))
parser.add_argument("--local-files-only", action="store_true")
args = parser.parse_args()
path = Path(snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_dir=args.output, local_files_only=args.local_files_only))
files = {}
for name in (
    "model.safetensors",
    "config.json",
    "policy_preprocessor.json",
    "policy_postprocessor.json",
    "policy_preprocessor_step_3_normalizer_processor.safetensors",
    "policy_postprocessor_step_0_unnormalizer_processor.safetensors",
):
    source = path / name
    if not source.is_file():
        raise FileNotFoundError(name)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    files[name] = {"size": source.stat().st_size, "sha256": digest.hexdigest()}
manifest = {"model_id": MODEL_ID, "revision": MODEL_REVISION, "files": files}
(path / "download_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"model_id": MODEL_ID, "revision": MODEL_REVISION, "files": files}, indent=2))
