"""隔離HumbleとWebシミュレータだけを接続する明示opt-in実験。"""

import argparse
import base64
from collections import deque
import io
import json
import os
from pathlib import Path
import time
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("--enable-simulation-motion", action="store_true")
parser.add_argument("--exchange", type=Path, default=Path("/exchange"))
args = parser.parse_args()
if (
    not args.enable_simulation_motion
    or os.environ.get("ROS_DOMAIN_ID") != "94"
    or os.environ.get("ROS_LOCALHOST_ONLY") != "1"
):
    parser.error(
        "requires explicit simulation opt-in and isolated ROS domain 94 / localhost only"
    )

import rclpy  # noqa: E402
from rclpy.node import Node  # noqa: E402
from sensor_msgs.msg import Image as RosImage, JointState  # noqa: E402
from rosgraph_msgs.msg import Clock  # noqa: E402
from PIL import Image  # noqa: E402
from vla_bridge.core import ExecutionClock  # noqa: E402
from vla_bridge.conversion import raw_rgb  # noqa: E402
from vla_bridge.sim_guard import validate_reply, synchronized_frame, TOPIC, LIMITS  # noqa: E402

root = args.exchange
names = [f"joint{i}" for i in range(1, 8)]
rclpy.init()
node = Node("pi05_isolated_sim_motion")
clock = ExecutionClock("ros_sim", stall_s=5)
joints, frames = deque(maxlen=128), deque(maxlen=8)
feedback = []


def stamp(msg):
    return msg.sec * 1_000_000_000 + msg.nanosec


def on_clock(msg):
    if clock.update(stamp(msg.clock)):
        joints.clear()
        frames.clear()


def on_joints(msg):
    values = dict(zip(msg.name, msg.position))
    if all(name in values for name in names):
        q = [float(values[name]) for name in names]
        joints.append((stamp(msg.header.stamp), q))
        feedback.append({"stamp_ns": stamp(msg.header.stamp), "positions": q})


node.create_subscription(Clock, "/clock", on_clock, 10)
node.create_subscription(JointState, "/joint_states", on_joints, 10)
node.create_subscription(
    RosImage,
    "/camera/camera/color/image_raw",
    lambda m: frames.append((stamp(m.header.stamp), m)),
    10,
)
publisher = node.create_publisher(JointState, TOPIC, 10)
trace = []
last_stamp = -1
deadline = time.monotonic() + 240


def spin_until(condition, wall_deadline):
    while rclpy.ok() and time.monotonic() < wall_deadline:
        rclpy.spin_once(node, timeout_sec=0.02)
        if condition():
            return True
    return False


def publish(q):
    message = JointState()
    now = clock.read().timestamp_ns
    message.header.stamp.sec, message.header.stamp.nanosec = divmod(now, 1_000_000_000)
    message.name, message.position = names, list(q)
    publisher.publish(message)


try:
    if not spin_until(
        lambda: (root / "ready.json").exists()
        and frames
        and joints
        and clock.read().valid,
        deadline,
    ):
        raise TimeoutError("model / simulator observations unavailable")
    for chunk_index in range(8):
        if not spin_until(
            lambda: synchronized_frame(frames, joints, clock.read(), last_stamp)
            is not None,
            time.monotonic() + 10,
        ):
            raise TimeoutError("no new camera frame")
        frame_stamp, frame, q = synchronized_frame(
            frames, joints, clock.read(), last_stamp
        )
        sample = clock.read()
        if (
            not sample.valid
            or not 0 <= sample.timestamp_ns - frame_stamp <= 1_000_000_000
        ):
            raise ValueError("stale simulation observation")
        width, height, pixels = raw_rgb(frame)
        buffer = io.BytesIO()
        Image.frombytes("RGB", (width, height), pixels).save(buffer, format="PNG")
        request = {
            "request_id": str(uuid.uuid4()),
            "stamp_ns": frame_stamp,
            "epoch": sample.epoch,
            "positions": q,
            "sent_wall_ns": time.time_ns(),
            "task": "Move the red cube onto the green target.",
            "image_png": base64.b64encode(buffer.getvalue()).decode(),
        }
        (root / "observation.tmp").write_text(json.dumps(request))
        (root / "observation.tmp").replace(root / "observation.json")
        sent = time.monotonic()

        def response_ready():
            try:
                return (
                    json.loads((root / "response.json").read_text())["request_id"]
                    == request["request_id"]
                )
            except (FileNotFoundError, json.JSONDecodeError):
                return False

        if not spin_until(response_ready, sent + 5):
            raise TimeoutError("inference timeout")
        reply = json.loads((root / "response.json").read_text())
        targets = validate_reply(reply, request, clock.read(), time.monotonic() - sent)
        # 50点のうち先頭10点だけを10Hzのシミュレーション時刻で実行する。
        begin = clock.read().timestamp_ns
        for index in range(10):
            if not spin_until(
                lambda: clock.read().timestamp_ns >= begin + index * 100_000_000,
                time.monotonic() + 5,
            ):
                raise TimeoutError("simulation clock stalled")
            current = clock.read()
            if not current.valid or current.epoch != sample.epoch:
                raise ValueError("simulation epoch invalidated")
            publish(targets[index])
        trace.append(
            {
                "chunk": chunk_index,
                "observation_stamp_ns": frame_stamp,
                "start_q": q,
                "first_target": targets[0],
                "last_target": targets[9],
                "inference_s": reply["inference_s"],
            }
        )
        (root / "motion.json").write_text(
            json.dumps({"chunks": trace, "feedback": feedback, "real_actuation": False})
        )
        print(json.dumps(trace[-1]), flush=True)
        last_stamp = frame_stamp
    spin_until(lambda: False, time.monotonic() + 3)
finally:
    # 指令キューを止め、最後に受信した実測位置で保持する。実機停止の実装ではない。
    if joints and clock.read().valid:
        publish([max(lo, min(hi, q)) for q, (lo, hi) in zip(joints[-1][1], LIMITS)])
        rclpy.spin_once(node, timeout_sec=0.1)
    (root / "stop").touch()
    (root / "motion.json").write_text(
        json.dumps({"chunks": trace, "feedback": feedback, "real_actuation": False})
    )
    node.destroy_node()
    rclpy.shutdown()
