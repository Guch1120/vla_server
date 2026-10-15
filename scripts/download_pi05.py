"""公開ベースモデルを固定revisionで取得する。トークン・実機情報は扱わない。"""

import argparse
import json
import hashlib
import urllib.request
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

MODEL_ID = "lerobot/pi05_base"
REVISION = "22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    info = HfApi().model_info(MODEL_ID, revision=REVISION, files_metadata=True, token=False)
    print(json.dumps({"model": MODEL_ID, "revision": info.sha,
                      "bytes": sum(f.size or 0 for f in info.siblings)}, indent=2), flush=True)
    snapshot_download(MODEL_ID, revision=REVISION, local_dir=args.output, token=False)
    (args.output / "download_manifest.json").write_text(json.dumps({
        "model_id": MODEL_ID, "revision": REVISION, "license": "gemma",
        "files": {f.rfilename: {"size": f.size, "lfs": f.lfs.sha256 if f.lfs else None}
                  for f in info.siblings},
    }, indent=2))
    # OpenPIが公式に利用するGoogle公開SentencePiece。同じ語彙を匿名取得する。
    url = "https://storage.googleapis.com/big_vision/paligemma_tokenizer.model"
    data = urllib.request.urlopen(url, timeout=60).read()
    (args.output / "paligemma_tokenizer.model").write_bytes(data)
    (args.output / "tokenizer_manifest.json").write_text(json.dumps({
        "url": url, "sha256": hashlib.sha256(data).hexdigest(),
    }, indent=2))


if __name__ == "__main__":
    main()
