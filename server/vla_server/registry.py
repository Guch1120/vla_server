"""Explicit, allowlisted model metadata; no remote dynamic code loading."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    adapter: str
    action_schema: str
    action_kind: str
    joint_names: tuple[str, ...]
    action_hz: float
    output_horizon: int

REGISTRY: dict[str, ModelSpec] = {
    "mock_piper": ModelSpec(
        model_id="mock_piper", adapter="mock",
        action_schema="mock_joint_position_v1", action_kind="joint_position",
        joint_names=("joint_1", "joint_2"), action_hz=20.0, output_horizon=2
    )
}
