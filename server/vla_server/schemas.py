"""物理量と時刻を保持する共通HTTP契約。"""

import base64
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Image(StrictModel):
    timestamp_ns: int = Field(gt=0)
    frame_id: str = Field(min_length=1, max_length=128)
    calibration_id: str = Field(min_length=1, max_length=128)
    encoding: Literal["rgb8"] = "rgb8"
    width: int = Field(gt=0, le=1024)
    height: int = Field(gt=0, le=1024)
    data_base64: str = Field(max_length=4194304)

    @model_validator(mode="after")
    def pixels(self):
        try:
            raw = base64.b64decode(self.data_base64, validate=True)
        except ValueError as exc:
            raise ValueError("invalid base64") from exc
        if len(raw) != self.width * self.height * 3:
            raise ValueError("RGB byte count mismatch")
        return self


class Observation(StrictModel):
    timestamp_ns: int = Field(gt=0)
    clock_domain: Literal["unix"] = "unix"
    joint_names: list[str] = Field(min_length=1, max_length=64)
    joint_positions_rad: list[FiniteFloat] = Field(min_length=1, max_length=64)
    images: dict[str, Image] = Field(default_factory=dict, max_length=4)

    @model_validator(mode="after")
    def shape(self):
        if (
            len(self.joint_names) != len(self.joint_positions_rad)
            or len(set(self.joint_names)) != len(self.joint_names)
            or any(not n or len(n) > 128 for n in self.joint_names)
        ):
            raise ValueError("invalid joint schema")
        if any(
            abs(i.timestamp_ns - self.timestamp_ns) > 50_000_000
            for i in self.images.values()
        ):
            raise ValueError("image/state skew exceeds 50ms")
        return self


class PredictRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    observation: Observation
    task: str = Field(default="", max_length=2048)
    dry_run: Literal[True] = True


class PredictResponse(StrictModel):
    request_id: str
    model_id: str
    action_schema: str
    action_kind: Literal["joint_position", "joint_velocity", "ee_twist"]
    unit: Literal["rad", "rad/s", "m/s,rad/s"]
    frame_id: str
    robot_id: str
    joint_names: list[str]
    action_hz: FiniteFloat = Field(gt=0, le=1000)
    actions: list[list[FiniteFloat]] = Field(min_length=1, max_length=256)
    source_timestamp_ns: int = Field(gt=0)
    generated_timestamp_ns: int = Field(gt=0)
    inference_ms: FiniteFloat = Field(ge=0)

    @model_validator(mode="after")
    def shape(self):
        width = 6 if self.action_kind == "ee_twist" else len(self.joint_names)
        expected = {
            "joint_position": "rad",
            "joint_velocity": "rad/s",
            "ee_twist": "m/s,rad/s",
        }
        if not width or any(len(row) != width for row in self.actions):
            raise ValueError("invalid action shape")
        if self.unit != expected[self.action_kind] or not self.frame_id:
            raise ValueError("invalid units/frame")
        if len(set(self.joint_names)) != len(self.joint_names):
            raise ValueError("duplicate action joints")
        return self
