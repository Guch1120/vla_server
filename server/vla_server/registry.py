"""明示登録したAdapterのみ使用する。外部コードや重みを取得しない。"""

from typing import Literal, Protocol
from pydantic import ConfigDict, Field
from .schemas import StrictModel, PredictRequest, PredictResponse


class ModelSpec(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    model_id: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    checkpoint: str = Field(min_length=1)
    license: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    preprocessing_version: str = Field(min_length=1)
    normalization_version: str = Field(min_length=1)
    observation_schema: str = Field(min_length=1)
    camera_order: list[str]
    robot_id: str = Field(min_length=1)
    action_schema: str = Field(min_length=1)
    action_kind: Literal["joint_position", "joint_velocity", "ee_twist"]
    unit: Literal["rad", "rad/s", "m/s,rad/s"]
    frame_id: str = Field(min_length=1)
    joint_names: list[str] = Field(min_length=1)
    action_hz: float = Field(gt=0, le=1000, allow_inf_nan=False)
    output_horizon: int = Field(gt=0, le=256)
    ready: bool = True
    trained: bool = False


class PolicyAdapter(Protocol):
    def load(self) -> None: ...
    def infer(self, request: PredictRequest) -> list[list[float]]: ...
    def unload(self) -> None: ...


class MockPolicy:
    """合成fixture。学習済み方策ではない。"""

    def __init__(self, spec):
        self.spec = spec

    def load(self):
        pass

    def unload(self):
        pass

    def infer(self, request):
        width = 6 if self.spec.action_kind == "ee_twist" else len(self.spec.joint_names)
        return [[0.0] * width for _ in range(self.spec.output_horizon)]


class Registry:
    def __init__(self):
        self.specs = {}
        self.adapters = {}

    def register(self, spec: ModelSpec, adapter: PolicyAdapter):
        if spec.model_id in self.specs:
            raise ValueError("duplicate model_id")
        if len(set(spec.joint_names)) != len(spec.joint_names):
            raise ValueError("duplicate joints")
        PredictResponse(
            request_id="validation",
            model_id=spec.model_id,
            **{
                k: getattr(spec, k)
                for k in (
                    "action_schema",
                    "action_kind",
                    "unit",
                    "frame_id",
                    "robot_id",
                    "joint_names",
                    "action_hz",
                )
            },
            actions=[
                [0.0] * (6 if spec.action_kind == "ee_twist" else len(spec.joint_names))
            ],
            source_timestamp_ns=1,
            generated_timestamp_ns=1,
            inference_ms=0.0,
        )
        adapter.load()
        self.specs[spec.model_id] = spec
        self.adapters[spec.model_id] = adapter


def default_registry():
    registry = Registry()
    for model_id, cameras in (("mock_piper", []), ("mock_rgb", ["front"])):
        spec = ModelSpec(
            model_id=model_id,
            adapter="mock",
            checkpoint="synthetic:zeros-v1",
            license="Apache-2.0",
            adapter_version="1",
            preprocessing_version="rgb8-v1",
            normalization_version="identity-v1",
            observation_schema="observation_v1",
            camera_order=cameras,
            robot_id="synthetic_fixture",
            action_schema="mock_joint_position_v1",
            action_kind="joint_position",
            unit="rad",
            frame_id="synthetic_base",
            joint_names=["joint_1", "joint_2"],
            action_hz=20.0,
            output_horizon=2,
        )
        registry.register(spec, MockPolicy(spec))
    return registry
