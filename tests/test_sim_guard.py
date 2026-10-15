import pytest
from vla_bridge.core import ClockSample
from vla_bridge.sim_guard import validate_reply, synchronized_frame, synchronized_observation, SCHEMA


def test_wait_for_delayed_joint_then_select_matching_frame():
    clock = ClockSample(2_000_000_000, "ros_sim", "e")
    frames = [(1_900_000_000, "image"), (2_000_000_000, "newer")]
    joints = [(1_700_000_000, [0.0] * 7)]
    assert synchronized_frame(frames, joints, clock, 0) is None
    joints.append((1_910_000_000, [0.1] * 7))
    assert synchronized_frame(frames, joints, clock, 0) == (
        1_900_000_000,
        "image",
        [0.1] * 7,
    )
    assert synchronized_frame(frames, joints, clock, 1_900_000_000) is None


def test_synchronize_two_cameras_and_eight_joints():
    clock = ClockSample(2_000_000_000, "ros_sim", "e")
    result = synchronized_observation(
        [(1_990_000_000, "ee")], [(2_010_000_000, "external")],
        [(2_000_000_000, [0.0] * 8)], clock, 0,
    )
    assert result == (1_990_000_000, "ee", "external", [0.0] * 8)
    assert synchronized_observation(
        [(1_990_000_000, "ee")], [(2_100_000_000, "late")],
        [(2_000_000_000, [0.0] * 8)], clock, 0,
    ) is None


@pytest.mark.parametrize(
    "change", ["robot", "stale", "epoch", "schema", "nan", "limit", "request"]
)
def test_simulation_guard_refuses_invalid_commands(change):
    request = dict(request_id="a", stamp_ns=1_000_000_000, epoch="e")
    reply = dict(request, schema=SCHEMA, targets=[[0.0] * 8 for _ in range(50)])
    clock = ClockSample(1_100_000_000, "ros_sim", "e")
    if change == "robot":
        clock = ClockSample(clock.timestamp_ns, "robot", "e")
    if change == "stale":
        clock = ClockSample(5_000_000_000, "ros_sim", "e")
    if change == "epoch":
        clock = ClockSample(clock.timestamp_ns, "ros_sim", "new")
    if change == "schema":
        reply["schema"] = "piper_real"
    if change == "nan":
        reply["targets"][0][0] = float("nan")
    if change == "limit":
        reply["targets"][0][6] = 1.0
    if change == "request":
        reply["request_id"] = "old"
    with pytest.raises(ValueError):
        validate_reply(reply, request, clock, 0.2)


def test_valid_simulation_target():
    request = dict(request_id="a", stamp_ns=1_000_000_000, epoch="e")
    reply = dict(request, schema=SCHEMA, targets=[[0.0] * 8 for _ in range(50)])
    assert (
        len(
            validate_reply(
                reply, request, ClockSample(1_100_000_000, "ros_sim", "e"), 0.2
            )
        )
        == 50
    )


def test_validates_eight_joint_action_shape():
    request = dict(request_id="a", stamp_ns=1_000_000_000, epoch="e")
    reply = dict(request, schema=SCHEMA, targets=[[0.0] * 7 for _ in range(50)])
    with pytest.raises(ValueError, match="wrong joint dimension"):
        validate_reply(reply, request, ClockSample(1_100_000_000, "ros_sim", "e"), 0.2)
