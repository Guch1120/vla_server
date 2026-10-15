"""実行時計とROS物理量変換の回帰テスト。"""

import io
from concurrent.futures import Future
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from vla_server.api import create_app
from vla_bridge.core import DryRunClient, ExecutionClock, LatestWorker
from vla_bridge.conversion import joint_observation, raw_rgb, compressed_rgb


def test_named_arm_and_gripper_are_separate():
    names = [
        "wheel",
        "joint8",
        "joint3",
        "joint1",
        "joint7",
        "joint6",
        "joint2",
        "joint5",
        "joint4",
    ]
    values = [9.0, -0.02, 0.3, 0.1, 0.02, 0.6, 0.2, 0.5, 0.4]
    joints = [f"joint{i}" for i in range(1, 7)]
    obs = joint_observation(
        names, values, joints, joints, "joint7", 1.0, 0.0, "finger_m_v1"
    )
    assert obs["joint_positions_rad"] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    assert obs["gripper"]["position_m"] == 0.02
    assert obs["gripper"]["calibration_id"] == "finger_m_v1"
    assert "joint8" not in obs["joint_names"]


@pytest.mark.parametrize(
    "names,positions",
    [
        (["joint1"], [0.0]),
        (["joint1", "joint1"], [0.0, 0.0]),
        (["joint1", "joint2"], [0.0, float("nan")]),
    ],
)
def test_missing_or_ambiguous_state_is_rejected(names, positions):
    with pytest.raises(ValueError):
        joint_observation(names, positions, ["joint1", "joint2"], ["joint1", "joint2"])


@pytest.mark.parametrize(
    "encoding,pixels",
    [
        ("rgb8", [1, 2, 3]),
        ("bgr8", [3, 2, 1]),
        ("rgba8", [1, 2, 3, 255]),
        ("bgra8", [3, 2, 1, 255]),
    ],
)
def test_color_encoding_and_padding(encoding, pixels):
    msg = SimpleNamespace(
        width=1,
        height=1,
        encoding=encoding,
        step=len(pixels) + 1,
        data=bytes(pixels + [99]),
    )
    assert raw_rgb(msg) == (1, 1, b"\x01\x02\x03")


def test_png_to_common_rgb():
    stream = io.BytesIO()
    Image.new("RGB", (2, 1), (1, 2, 3)).save(stream, format="PNG")
    assert compressed_rgb(SimpleNamespace(data=stream.getvalue())) == (
        2,
        1,
        b"\x01\x02\x03" * 2,
    )
    with pytest.raises((ValueError, OSError)):
        compressed_rgb(SimpleNamespace(data=b"invalid"))


def test_clock_pause_and_reset(monkeypatch):
    ticks = [1.0]
    monkeypatch.setattr("vla_bridge.core.time.monotonic", lambda: ticks[0])
    clock = ExecutionClock("ros_sim", 1.0)
    assert not clock.read().valid
    clock.update(100_000_000_000)
    epoch = clock.read().epoch
    assert clock.read().valid
    ticks[0] = 2.1
    assert not clock.read().valid
    assert clock.update(1_000_000_000)
    assert clock.read().epoch != epoch and clock.read().valid


@pytest.mark.parametrize("domain", ["robot", "ros_sim"])
def test_client_uses_execution_time_not_server_time(domain):
    clock = ExecutionClock(domain)
    clock.update(100_000_000_000)
    client = DryRunClient(
        "http://localhost", "mock_piper", client=TestClient(create_app()), clock=clock
    )
    obs = dict(
        timestamp_ns=99_990_000_000,
        clock_domain=domain,
        clock_epoch=clock.read().epoch,
        joint_names=["joint_1", "joint_2"],
        joint_positions_rad=[0.0, 0.0],
    )
    try:
        result = client.predict(obs)
        assert result.source_timestamp_ns == 99_990_000_000
        clock.update(1_000_000_000)
        with pytest.raises(ValueError):
            client.validate_clock(result)
    finally:
        client.close()


def test_inflight_response_before_clock_reset_is_discarded():
    clock = ExecutionClock("ros_sim")
    clock.update(100_000_000_000)
    client = DryRunClient(
        "http://localhost", "mock_piper", client=TestClient(create_app()), clock=clock
    )
    worker = LatestWorker(client)
    try:
        worker.future = Future()
        worker.future.set_result(SimpleNamespace(source_timestamp_ns=100_000_000_000))
        worker.invalidate()
        assert worker.poll() is None and worker.state == "HOLD"
    finally:
        worker.close()


def test_oversize_compressed_frame_fails_closed(monkeypatch):
    stream = io.BytesIO()
    Image.new("RGB", (1025, 1)).save(stream, format="PNG")
    with pytest.raises(ValueError):
        compressed_rgb(SimpleNamespace(data=stream.getvalue()))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    with pytest.raises(ValueError):
        compressed_rgb(SimpleNamespace(data=stream.getvalue()))
