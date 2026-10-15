"""シミュレーション専用の実験指令を検査する。実機モードは提供しない。"""

import math

TOPIC = "/sim/piper_standalone/joint_targets"
SCHEMA = "experimental_pi05_first7_delta_rad_finger_m_v1"
LIMITS = [
    (-2.618, 2.618),
    (0, 3.14),
    (-2.967, 0),
    (-1.745, 1.745),
    (-1.22, 1.22),
    (-2.0944, 2.0944),
    (0, 0.035),
]


def synchronized_frame(frames, joints, clock, last_stamp):
    """画像と関節の到着順に依存せず、50ms以内の新しい組を待つ。"""
    if not clock.valid or not joints:
        return None
    for timestamp, frame in reversed(frames):
        if (
            timestamp <= last_stamp
            or not 0 <= clock.timestamp_ns - timestamp <= 1_000_000_000
        ):
            continue
        joint_stamp, positions = min(joints, key=lambda pair: abs(pair[0] - timestamp))
        if abs(joint_stamp - timestamp) <= 50_000_000:
            return timestamp, frame, positions
    return None


def validate_reply(reply, request, clock, elapsed_s):
    if not clock.valid or clock.domain != "ros_sim" or clock.epoch != request["epoch"]:
        raise ValueError("simulation clock changed or stalled")
    if (
        not 0 <= elapsed_s <= 5
        or not 0 <= clock.timestamp_ns - request["stamp_ns"] <= 3_000_000_000
    ):
        raise ValueError("expired simulation inference")
    if any(reply.get(k) != request[k] for k in ("request_id", "stamp_ns", "epoch")):
        raise ValueError("response identity mismatch")
    if reply.get("schema") != SCHEMA:
        raise ValueError("experimental schema mismatch")
    targets = reply.get("targets", [])
    if len(targets) != 50:
        raise ValueError("wrong horizon")
    for row in targets:
        if len(row) != 7 or any(
            type(v) not in (float, int) or not math.isfinite(v) or not lo <= v <= hi
            for v, (lo, hi) in zip(row, LIMITS)
        ):
            raise ValueError("invalid simulation joint target")
    return targets
