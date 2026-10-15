"""実行側の時計とROS型を共通APIへ揃える。モータpublisherは作成しない。"""

import base64
import time
from collections import deque
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image, JointState
from rosgraph_msgs.msg import Clock as ClockMessage
from std_msgs.msg import String
from .core import DryRunClient, ExecutionClock, LatestWorker
from .conversion import compressed_rgb, joint_observation, raw_rgb


class Bridge(Node):
    def __init__(self):
        super().__init__("vla_bridge")
        defaults = {
            "server_url": "http://127.0.0.1:8000",
            "model_id": "mock_piper",
            "task": "",
            "dry_run": True,
            "camera_topics": [""],
            "camera_names": [""],
            "camera_calibration_ids": ["synthetic_unverified"],
            "image_transport": "raw",
            "image_qos": "best_effort",
            "joint_state_topic": "/joint_states",
            "joint_qos": "best_effort",
            "sync_receive_age_s": 1.0,
            "infer_timeout_s": 1.0,
            "clock_domain": "auto",
            "clock_stall_s": 1.0,
            "clock_topic": "",
            "clock_qos": "best_effort",
            "joint_names": ["joint_1", "joint_2"],
            "joint_source_names": ["joint_1", "joint_2"],
            "gripper_joint_name": "",
            "gripper_scale": 1.0,
            "gripper_offset_m": 0.0,
            "gripper_calibration_id": "",
        }
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        p = lambda key: self.get_parameter(key).value
        domain = p("clock_domain")
        if domain == "auto":
            domain = "ros_sim" if p("use_sim_time") else "robot"
        self.execution_clock = ExecutionClock(domain, p("clock_stall_s"))
        clock_topic = p("clock_topic") or ("/clock" if p("use_sim_time") else "")
        self.clock_from_topic = bool(clock_topic)
        if domain == "ros_sim" and not self.clock_from_topic:
            raise ValueError("simulation execution clock topic required")
        if not self.clock_from_topic:
            self.execution_clock.update(self.get_clock().now().nanoseconds)
        topics = [t for t in p("camera_topics") if t]
        names = [n for n in p("camera_names") if n]
        calibrations = p("camera_calibration_ids")
        if len(calibrations) == 1:
            calibrations = calibrations * len(names)
        if (
            len(topics) != len(names)
            or len(set(names)) != len(names)
            or len(calibrations) != len(names)
            or not all(calibrations)
        ):
            raise ValueError("invalid camera mapping")
        self.calibrations = dict(zip(names, calibrations))
        self.joint_names = list(p("joint_names"))
        self.source_names = list(p("joint_source_names"))
        self.gripper_config = dict(
            gripper_name=p("gripper_joint_name"),
            gripper_scale=p("gripper_scale"),
            gripper_offset_m=p("gripper_offset_m"),
            gripper_calibration_id=p("gripper_calibration_id"),
        )
        joint_observation(
            self.source_names,
            [0.0] * len(self.source_names),
            self.joint_names,
            self.source_names,
        )
        if not self.joint_names:
            raise ValueError("arm joints required")
        if p("image_transport") not in ("raw", "compressed") or p("image_qos") not in (
            "reliable",
            "best_effort",
        ):
            raise ValueError("invalid image transport/QoS")
        self.decode_image = raw_rgb if p("image_transport") == "raw" else compressed_rgb
        self.images = {name: deque(maxlen=8) for name in names}
        self.joint_buffer = deque(maxlen=32)
        self.sync_receive_age_s = p("sync_receive_age_s")
        if not 0 < self.sync_receive_age_s <= 10:
            raise ValueError("invalid synchronization receive age")
        self.clock_valid = self.execution_clock.read().valid
        self.worker = LatestWorker(
            DryRunClient(
                p("server_url"),
                p("model_id"),
                p("task"),
                p("infer_timeout_s"),
                dry_run=p("dry_run"),
                clock=self.execution_clock,
            )
        )
        self.output = self.create_publisher(String, "~/dry_run_actions", 10)
        self.subscriptions_owned = []
        if p("clock_qos") not in ("reliable", "best_effort"):
            raise ValueError("invalid clock QoS")
        if clock_topic:
            clock_qos = QoSProfile(
                depth=10,
                reliability=(
                    ReliabilityPolicy.RELIABLE
                    if p("clock_qos") == "reliable"
                    else ReliabilityPolicy.BEST_EFFORT
                ),
            )
            self.subscriptions_owned.append(
                self.create_subscription(
                    ClockMessage, clock_topic, self.receive_clock, clock_qos
                )
            )
        image_qos = (
            QoSProfile(depth=2, reliability=ReliabilityPolicy.RELIABLE)
            if p("image_qos") == "reliable"
            else qos_profile_sensor_data
        )
        for name, topic in zip(names, topics):
            self.subscriptions_owned.append(
                self.create_subscription(
                    Image if p("image_transport") == "raw" else CompressedImage,
                    topic,
                    lambda msg, n=name: self.image(n, msg),
                    image_qos,
                )
            )
        if p("joint_qos") not in ("reliable", "best_effort"):
            raise ValueError("invalid joint QoS")
        self.subscriptions_owned.append(
            self.create_subscription(
                JointState,
                p("joint_state_topic"),
                self.joints,
                (
                    QoSProfile(depth=32, reliability=ReliabilityPolicy.RELIABLE)
                    if p("joint_qos") == "reliable"
                    else qos_profile_sensor_data
                ),
            )
        )
        # /clock停止中も通信期限とHOLD判定を進めるため、このタイマーはsteady clockを使う。
        self.steady_clock = rclpy.clock.Clock(
            clock_type=rclpy.clock.ClockType.STEADY_TIME
        )
        self.create_timer(0.02, self.poll, clock=self.steady_clock)

    @staticmethod
    def stamp(msg):
        return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec

    def update_clock(self, timestamp_ns=None):
        reset = False
        if timestamp_ns is not None:
            reset = self.execution_clock.update(timestamp_ns)
        elif not self.clock_from_topic:
            reset = self.execution_clock.update(self.get_clock().now().nanoseconds)
        valid = self.execution_clock.read().valid
        if reset or (self.clock_valid and not valid):
            for frames in self.images.values():
                frames.clear()
            self.joint_buffer.clear()
            self.worker.invalidate()
        self.clock_valid = valid
        return valid

    def receive_clock(self, msg):
        self.update_clock(msg.clock.sec * 1_000_000_000 + msg.clock.nanosec)
        self.synchronize()

    def image(self, name, msg):
        self.update_clock()
        try:
            width, height, pixels = self.decode_image(msg)
        except (ValueError, OSError):
            return
        self.images[name].append(
            dict(
                timestamp_ns=self.stamp(msg),
                frame_id=msg.header.frame_id,
                calibration_id=self.calibrations[name],
                width=width,
                height=height,
                encoding="rgb8",
                data_base64=base64.b64encode(pixels).decode(),
                _received_monotonic=time.monotonic(),
            )
        )
        self.synchronize()

    def joints(self, msg):
        self.update_clock()
        try:
            state = joint_observation(
                list(msg.name),
                list(msg.position),
                self.joint_names,
                self.source_names,
                **self.gripper_config,
            )
        except ValueError:
            return
        state["timestamp_ns"] = self.stamp(msg)
        state["_received_monotonic"] = time.monotonic()
        self.joint_buffer.append(state)
        self.synchronize()

    def synchronize(self):
        clock = self.execution_clock.read()
        if not clock.valid:
            return
        # 最新だけを見ると、画像より後着した近い関節状態を捨てるため有界履歴から選ぶ。
        for state in reversed(self.joint_buffer):
            if (
                time.monotonic() - state["_received_monotonic"]
                > self.sync_receive_age_s
            ):
                continue
            timestamp = state["timestamp_ns"]
            images = {}
            if not -50_000_000 <= clock.timestamp_ns - timestamp <= 1_000_000_000:
                continue
            for name, frames in self.images.items():
                if not frames:
                    break
                fresh = [
                    f
                    for f in frames
                    if time.monotonic() - f["_received_monotonic"]
                    <= self.sync_receive_age_s
                ]
                if not fresh:
                    break
                frame = min(fresh, key=lambda f: abs(f["timestamp_ns"] - timestamp))
                if abs(frame["timestamp_ns"] - timestamp) > 50_000_000:
                    break
                images[name] = {k: v for k, v in frame.items() if not k.startswith("_")}
            else:
                self.worker.offer(
                    dict(
                        **{k: v for k, v in state.items() if not k.startswith("_")},
                        clock_domain=clock.domain,
                        clock_epoch=clock.epoch,
                        images=images,
                    )
                )
                while (
                    self.joint_buffer
                    and self.joint_buffer[0]["timestamp_ns"] <= timestamp
                ):
                    self.joint_buffer.popleft()
                return

    def poll(self):
        self.update_clock()
        self.synchronize()
        result = self.worker.poll()
        if result is not None:
            self.output.publish(String(data=result.model_dump_json()))

    def destroy_node(self):
        self.worker.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = Bridge()
        rclpy.spin(node)
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
