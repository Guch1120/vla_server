"""Piper用π₀.₅チェックポイントを学習時の統計と2視点で推論する。"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

MODEL_ID = "samithva/task_e_pi05"
MODEL_REVISION = "c235d95044981460f7fb1984b01379899e68a4e4"
MODEL_SHA256 = "71c0c04d069d69840e34e9bd57bdd6f34868a778929f370abba50031c3ac5d81"
STATE_STATS_SHA256 = "00f85414f5581284441fed43c7f2255faba6e50d5a077db97a6bd3ec2e29ee05"
ACTION_STATS_SHA256 = "a209700295ae66b5974cbdd94704d642b612f6da258031683def3429fce058ee"
TOKENIZER_SHA256 = "8986bb4f423f07f8c7f70d0dbe3526fb2316056c17bae71b1ea975e77a168fc6"
SCHEMA = "pi05_piper_task_e_absolute_joint_positions_v1"
JOINT_NAMES = [f"joint{i}" for i in range(1, 9)]
LIMITS = [
    (-2.618, 2.618), (0.0, 3.14), (-2.967, 0.0), (-1.745, 1.745),
    (-1.22, 1.22), (-2.0944, 2.0944), (0.0, 0.035), (-0.035, 0.0),
]
TASK = "pick and place the objects into the basket"


def _validate_config(checkpoint: Path) -> dict:
    config = json.loads((checkpoint / "config.json").read_text())
    features = config.get("input_features", {})
    if (
        config.get("type") != "pi05"
        or config.get("repo_id") != MODEL_ID
        or config.get("chunk_size") != 50
        or features.get("observation.state", {}).get("shape") != [8]
        or config.get("output_features", {}).get("action", {}).get("shape") != [8]
        or set(k for k in features if k.startswith("observation.images."))
        != {"observation.images.ee", "observation.images.external"}
    ):
        raise ValueError("checkpoint config does not match the pinned Piper task schema")
    if not (checkpoint / "model.safetensors").is_file():
        raise FileNotFoundError("model.safetensors")
    manifest_path = checkpoint / "download_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("pinned checkpoint download manifest is missing")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("model_id") != MODEL_ID or manifest.get("revision") != MODEL_REVISION:
        raise ValueError("checkpoint download revision mismatch")
    expected = manifest.get("files", {}).get("model.safetensors", {}).get("size")
    if (
        type(expected) is not int
        or expected != 9_354_050_752
        or manifest.get("files", {}).get("model.safetensors", {}).get("sha256") != MODEL_SHA256
        or (checkpoint / "model.safetensors").stat().st_size != expected
    ):
        raise ValueError("checkpoint weight size mismatch")
    for name, expected_digest in (
        ("policy_preprocessor_step_3_normalizer_processor.safetensors", STATE_STATS_SHA256),
        ("policy_postprocessor_step_0_unnormalizer_processor.safetensors", ACTION_STATS_SHA256),
    ):
        if manifest.get("files", {}).get(name, {}).get("sha256") != expected_digest:
            raise ValueError(f"checkpoint {name} fingerprint mismatch")
    return config


def normalize_quantiles(values, q01, q99):
    """LeRobot QUANTILES 前処理と同じ線形正規化。"""
    import torch

    denom = q99 - q01
    denom = torch.where(denom == 0, torch.full_like(denom, 1e-8), denom)
    return 2.0 * (values - q01) / denom - 1.0


def unnormalize_quantiles(values, q01, q99):
    """保存済みpostprocessorと同じ逆正規化。"""
    import torch

    denom = q99 - q01
    denom = torch.where(denom == 0, torch.full_like(denom, 1e-8), denom)
    return (values + 1.0) * denom / 2.0 + q01


def bounded_targets(actions):
    """学習時のアクションをPiperのMJCF関節可動域へ閉じ込める。"""
    rows = actions.tolist()
    if len(rows) != 50 or any(len(row) != 8 for row in rows):
        raise ValueError("expected exactly 50 absolute 8-joint actions")
    output = []
    for row in rows:
        if any(not math.isfinite(float(v)) for v in row):
            raise ValueError("non-finite model action")
        output.append([max(lo, min(hi, float(v))) for v, (lo, hi) in zip(row, LIMITS)])
    return output


class Pi05PiperTask:
    """保存済みPiperタスク重みだけを厳密ロードする推論アダプタ。"""

    def __init__(self, checkpoint: Path, tokenizer_path: Path):
        import torch
        from safetensors.torch import load_file
        from lerobot.policies.pi05.configuration_pi05 import PI05Config
        from lerobot.policies.pi05.modeling_pi05 import PI05Policy
        import sentencepiece

        self.config_dict = _validate_config(checkpoint)
        digest = hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()
        if digest != TOKENIZER_SHA256:
            raise ValueError("PaliGemma tokenizer fingerprint mismatch")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for this checkpoint's tested inference path")
        self.device = torch.device("cuda")
        config = PI05Config.from_pretrained(checkpoint)
        config.device = "cpu"
        config.dtype = torch.bfloat16
        config.compile_model = False
        self.policy = PI05Policy(config).to(device=self.device).eval()
        state_dict = load_file(str(checkpoint / "model.safetensors"), device="cpu")
        converted = self.policy._convert_openpi_state_dict(state_dict)
        self.policy.load_state_dict(converted, strict=True)
        del converted, state_dict
        self.tokenizer = sentencepiece.SentencePieceProcessor(
            model_file=str(tokenizer_path)
        )
        stats_path = checkpoint / "policy_preprocessor_step_3_normalizer_processor.safetensors"
        stats = load_file(str(stats_path), device="cpu")
        post_stats = load_file(
            str(checkpoint / "policy_postprocessor_step_0_unnormalizer_processor.safetensors"),
            device="cpu",
        )
        self.state_q01 = stats["observation.state.q01"].to(self.device)
        self.state_q99 = stats["observation.state.q99"].to(self.device)
        self.action_q01 = post_stats["action.q01"].to(self.device)
        self.action_q99 = post_stats["action.q99"].to(self.device)
        # Checkpointの統計ファイルをmanifestへ記録するための固定fingerprint。
        self.stats_sha256 = hashlib.sha256(stats_path.read_bytes()).hexdigest()

    def infer(self, ee_image, external_image, positions, seed: int = 7):
        import numpy as np
        import torch

        if len(positions) != 8 or any(not math.isfinite(float(v)) for v in positions):
            raise ValueError("expected eight finite Piper joint positions")
        state = torch.tensor([positions], dtype=torch.float32, device=self.device)
        normalized = normalize_quantiles(state, self.state_q01, self.state_q99)
        bins = torch.bucketize(
            normalized[0].float(),
            torch.linspace(-1.0, 1.0, 257, device=self.device)[:-1],
        ) - 1
        state_text = " ".join(str(int(v)) for v in bins.clamp(0, 255).tolist())
        prompt = f"Task: {TASK}, State: {state_text};\nAction: "
        tokens = self.tokenizer.encode(prompt, add_bos=True)
        length = self.config_dict["tokenizer_max_length"]
        if len(tokens) > length:
            raise ValueError("tokenized task prompt exceeds checkpoint limit")
        mask = [True] * len(tokens) + [False] * (length - len(tokens))
        tokens += [0] * (length - len(tokens))

        def image_tensor(image):
            rgb = np.asarray(image.convert("RGB"), dtype=np.float32).copy() / 255.0
            return torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(self.device)

        batch = {
            "observation.images.ee": image_tensor(ee_image),
            "observation.images.external": image_tensor(external_image),
            "observation.language.tokens": torch.tensor([tokens], device=self.device),
            "observation.language.attention_mask": torch.tensor([mask], device=self.device),
        }
        torch.manual_seed(seed)
        with torch.inference_mode():
            normalized_actions = self.policy.predict_action_chunk(batch)
            actions = unnormalize_quantiles(
                normalized_actions[0].float(), self.action_q01, self.action_q99
            )
        if tuple(actions.shape) != (50, 8) or not torch.isfinite(actions).all():
            raise ValueError("invalid Piper task action tensor")
        raw = actions.tolist()
        return bounded_targets(actions), raw
