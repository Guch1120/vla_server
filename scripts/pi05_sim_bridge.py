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
parser.add_argument("--observe-only", action="store_true", help="1回推論して出力を記録するが指令しない")
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
from vla_bridge.sim_guard import validate_reply, synchronized_observation, TOPIC, LIMITS  # noqa: E402
from vla_bridge.sim_guard import SCHEMA  # noqa: E402

root = args.exchange
names = [f"joint{i}" for i in range(1, 9)]
rclpy.init()
node = Node("pi05_isolated_sim_motion")
clock = ExecutionClock("ros_sim", stall_s=5)
joints, ee_frames, external_frames = deque(maxlen=128), deque(maxlen=8), deque(maxlen=8)
feedback = []


def stamp(msg):
    return msg.sec * 1_000_000_000 + msg.nanosec


def on_clock(msg):
    if clock.update(stamp(msg.clock)):
        joints.clear()
        ee_frames.clear()
        external_frames.clear()


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
    lambda m: ee_frames.append((stamp(m.header.stamp), m)),
    10,
)
node.create_subscription(
    RosImage,
    "/vla/observation/external/image_raw",
    lambda m: external_frames.append((stamp(m.header.stamp), m)),
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
    message.name, message.position = names, [float(value) for value in q]
    publisher.publish(message)


try:
    if not spin_until(
        lambda: (root / "ready.json").exists()
        and ee_frames
        and external_frames
        and joints
        and clock.read().valid,
        deadline,
    ):
        raise TimeoutError("model / simulator observations unavailable")
    for chunk_index in range(8):
        if not spin_until(
            lambda: synchronized_observation(ee_frames, external_frames, joints, clock.read(), last_stamp)
            is not None,
            time.monotonic() + 10,
        ):
            raise TimeoutError("no new camera frame")
        frame_stamp, ee_frame, external_frame, q = synchronized_observation(
            ee_frames, external_frames, joints, clock.read(), last_stamp
        )
        sample = clock.read()
        if (
            not sample.valid
            or not 0 <= sample.timestamp_ns - frame_stamp <= 1_000_000_000
        ):
            raise ValueError("stale simulation observation")
        def png(image):
            width, height, pixels = raw_rgb(image)
            buffer = io.BytesIO()
            Image.frombytes("RGB", (width, height), pixels).save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode()
        request = {
            "request_id": str(uuid.uuid4()),
            "stamp_ns": frame_stamp,
            "epoch": sample.epoch,
            "positions": q,
            "sent_wall_ns": time.time_ns(),
            "task": "pick and place the objects into the basket",
            "ee_image_png": png(ee_frame),
            "external_image_png": png(external_frame),
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
        if reply.get("schema") != SCHEMA or reply.get("action_mode") != "absolute_joint_positions":
            raise ValueError("task checkpoint action schema mismatch")
        if args.observe_only:
            trace.append({
                "chunk": chunk_index,
                "observation_stamp_ns": frame_stamp,
                "start_q": q,
                "model_first_target": targets[0],
                "unclamped_first_action": reply.get("unclamped_first"),
                "inference_s": reply["inference_s"],
                "observe_only": True,
            })
            (root / "motion.json").write_text(json.dumps({"chunks": trace, "feedback": feedback, "real_actuation": False}))
            print(json.dumps(trace[-1]), flush=True)
            break
        # JointTrajectory相当の絶対関節位置列を50Hzで低速に追従させる。
        # モデル出力は物理可動域へclamp済み。さらに速度/加速度を制限してシミュレータへ送る。
        begin = clock.read().timestamp_ns
        position, velocity = list(q), [0.0] * 8
        max_velocity = [0.35] * 6 + [0.02, 0.02]
        max_acceleration = [0.8] * 6 + [0.05, 0.05]
        safe_targets = []
        for target in targets:
            next_position = []
            for axis, goal in enumerate(target):
                dt = 0.02
                wanted_velocity = max(-max_velocity[axis], min(max_velocity[axis], (goal - position[axis]) / dt))
                delta_velocity = max(-max_acceleration[axis] * dt, min(max_acceleration[axis] * dt, wanted_velocity - velocity[axis]))
                velocity[axis] += delta_velocity
                lo, hi = LIMITS[axis]
                next_position.append(max(lo, min(hi, position[axis] + velocity[axis] * dt)))
            position = next_position
            safe_targets.append(position)
        for index in range(50):
            if not spin_until(
                lambda: clock.read().timestamp_ns >= begin + index * 20_000_000,
                time.monotonic() + 5,
            ):
                raise TimeoutError("simulation clock stalled")
            current = clock.read()
            if not current.valid or current.epoch != sample.epoch:
                raise ValueError("simulation epoch invalidated")
            publish(safe_targets[index])
        trace.append(
            {
                "chunk": chunk_index,
                "observation_stamp_ns": frame_stamp,
                "start_q": q,
                "first_target": targets[0],
                "last_target": safe_targets[-1],
                "model_first_target": targets[0],
                "unclamped_first_action": reply.get("unclamped_first"),
                "max_velocity_rad_s": max_velocity[:6],
                "max_acceleration_rad_s2": max_acceleration[:6],
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
    if not args.observe_only and joints and clock.read().valid:
        publish([max(lo, min(hi, q)) for q, (lo, hi) in zip(joints[-1][1], LIMITS)])
        rclpy.spin_once(node, timeout_sec=0.1)
    (root / "stop").touch()
    (root / "motion.json").write_text(
        json.dumps({"chunks": trace, "feedback": feedback, "real_actuation": False})
    )
    node.destroy_node()
    rclpy.shutdown()
