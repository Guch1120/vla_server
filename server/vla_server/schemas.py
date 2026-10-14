"""Synthetic JSON smoke-test wire contract; see docs/API_CONTRACT.md."""
from __future__ import annotations
import math
from pydantic import BaseModel, Field, model_validator

class Observation(BaseModel):
    timestamp_ns: int = Field(ge=0)
    joint_names: list[str] = Field(min_length=1, max_length=64)
    joint_positions_rad: list[float] = Field(min_length=1, max_length=64)
    images: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_obs(self):
        if len(self.joint_names) != len(self.joint_positions_rad):
            raise ValueError("joint name/position length mismatch")
        if len(set(self.joint_names)) != len(self.joint_names):
            raise ValueError("duplicate joint names")
        if not all(math.isfinite(x) for x in self.joint_positions_rad):
            raise ValueError("non-finite joint position")
        if self.images:
            raise ValueError("images unsupported by mock JSON endpoint; future binary API required")
        return self

class PredictRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    observation: Observation
    task: str = Field(default="", max_length=2048)

class PredictResponse(BaseModel):
    request_id: str
    model_id: str
    action_schema: str
    action_kind: str
    joint_names: list[str]
    action_hz: float
    actions: list[list[float]]
    source_timestamp_ns: int
    inference_ms: float
