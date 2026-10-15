"""π₀.₅ベースの推論専用検査。未知の32次元行動を関節指令として登録しない。"""

import math
import json
import hashlib
from pathlib import Path

MODEL_REVISION = "22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0"
MODEL_SHA256 = "0eb11ca9587678c1d2ef8cf32807c29f8ce53a2bfdfc1aa4a4c96f16fca59b0f"
TOKENIZER_SHA256 = "8986bb4f423f07f8c7f70d0dbe3526fb2316056c17bae71b1ea975e77a168fc6"
LEROBOT_REVISION = "8975047fbb76e7fef3f482988ceccc17e2102a90"


def validate_checkpoint(checkpoint: Path) -> dict:
    """GPUを確保する前に、必須ファイルと固定取得元を確認する。"""
    for name in ("model.safetensors", "config.json", "paligemma_tokenizer.model"):
        if not (checkpoint / name).is_file():
            raise FileNotFoundError(name)
    manifest = json.loads((checkpoint / "download_manifest.json").read_text())
    if manifest["model_id"] != "lerobot/pi05_base" or manifest["revision"] != MODEL_REVISION:
        raise ValueError("checkpoint revision mismatch")
    expected = manifest["files"]["model.safetensors"]["size"]
    if (checkpoint / "model.safetensors").stat().st_size != expected:
        raise ValueError("checkpoint size mismatch")
    return manifest


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError("checkpoint/tokenizer SHA256 mismatch")


def state_prompt(task: str, normalized_state: list[float]) -> str:
    """OpenPI/LeRobotと同じ256bin化。入力は正規化済みの検査fixtureのみ。"""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task is required")
    if len(normalized_state) != 32 or any(
        type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1
        for v in normalized_state
    ):
        raise ValueError("probe requires 32 finite normalized state values in [-1,1]")
    bins = [min(255, math.floor((v + 1) * 128)) for v in normalized_state]
    cleaned = task.strip().replace("_", " ").replace("\n", " ")
    return f"Task: {cleaned}, State: {' '.join(map(str, bins))};\nAction: "


class Pi05BaseProbe:
    """学習済み重みの読込失敗は例外にする。ランダム重みへの継続を許さない。"""

    def __init__(self, checkpoint: Path):
        validate_checkpoint(checkpoint)
        verify_sha256(checkpoint / "model.safetensors", MODEL_SHA256)
        verify_sha256(checkpoint / "paligemma_tokenizer.model", TOKENIZER_SHA256)
        import torch
        from lerobot.policies.pi05.configuration_pi05 import PI05Config
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy
        from safetensors.torch import load_file
        import sentencepiece

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for this tested probe")
        # 上流from_pretrainedは一部の読込例外を握り潰すため、変換後にstrict=Trueで直接検査する。
        config = PI05Config.from_pretrained(checkpoint)
        config.device = "cpu"
        # この固定版のmodel constructorは文字列でなくtorch.dtypeを要求する。
        config.dtype = torch.bfloat16
        config.compile_model = False
        # 上流の混合精度を保つ（vision/norm/一部action層はfloat32）。全層の強制castは行わない。
        self.policy = PI05Policy(config).to(device="cuda").eval()
        state = load_file(str(checkpoint / "model.safetensors"), device="cpu")
        converted = self.policy._convert_openpi_state_dict(state)
        self.policy.load_state_dict(converted, strict=True)
        del converted, state
        self.loaded_parameter_count = sum(p.numel() for p in self.policy.parameters())
        self.tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(checkpoint / "paligemma_tokenizer.model"))

    def infer(self, image, task: str, normalized_state: list[float], seed: int = 7):
        import numpy as np
        import torch

        prompt = state_prompt(task, normalized_state)
        tokens = self.tokenizer.encode(prompt, add_bos=True)
        length = self.policy.config.tokenizer_max_length
        if len(tokens) > length:
            raise ValueError("prompt exceeds tokenizer limit")
        mask = [True] * len(tokens) + [False] * (length - len(tokens))
        tokens += [0] * (length - len(tokens))
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32).copy() / 255
        # 実在する手首画像のみ渡す。欠けた2カメラは上流が明示maskで埋める。
        batch = {
            "observation.images.left_wrist_0_rgb": torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).cuda(),
            "observation.language.tokens": torch.tensor([tokens], device="cuda"),
            "observation.language.attention_mask": torch.tensor([mask], device="cuda"),
        }
        torch.manual_seed(seed)
        with torch.inference_mode():
            actions = self.policy.predict_action_chunk(batch)
        if tuple(actions.shape) != (1, 50, 32) or not torch.isfinite(actions).all():
            raise ValueError("invalid base action tensor")
        return actions.float().cpu().numpy()[0]
