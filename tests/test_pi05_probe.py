"""重みなしで前処理の境界条件を検査する。"""

import pytest
import json
import hashlib
from vla_server.pi05_probe import state_prompt, validate_checkpoint, verify_sha256, MODEL_REVISION


def test_prompt_bins_and_cleaning():
    prompt = state_prompt("  red_cube\nmove ", [-1.0, 0.0, 1.0] + [0.0] * 29)
    assert prompt.startswith("Task: red cube move, State: 0 128 255 ")
    assert prompt.endswith(";\nAction: ")


@pytest.mark.parametrize("state", [[0.0], [float('nan')] * 32, [float('inf')] * 32,
                                  [1.01] * 32, [True] * 32])
def test_reject_invalid_probe_state(state):
    with pytest.raises(ValueError):
        state_prompt("move", state)


def test_reject_empty_task():
    with pytest.raises(ValueError):
        state_prompt(" ", [0.0] * 32)


def test_checkpoint_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_checkpoint(tmp_path)


@pytest.mark.parametrize("revision,size", [("wrong", 4), (MODEL_REVISION, 999)])
def test_checkpoint_reject_revision_or_truncated_file(tmp_path, revision, size):
    for name in ("model.safetensors", "config.json", "paligemma_tokenizer.model"):
        (tmp_path / name).write_bytes(b"test")
    (tmp_path / "download_manifest.json").write_text(json.dumps({
        "model_id": "lerobot/pi05_base", "revision": revision,
        "files": {"model.safetensors": {"size": size}},
    }))
    with pytest.raises(ValueError):
        validate_checkpoint(tmp_path)


def test_corruption_of_same_size_is_rejected(tmp_path):
    path = tmp_path / "weights"
    path.write_bytes(b"test")
    expected = hashlib.sha256(b"test").hexdigest()
    verify_sha256(path, expected)
    path.write_bytes(b"evil")
    with pytest.raises(ValueError):
        verify_sha256(path, expected)
