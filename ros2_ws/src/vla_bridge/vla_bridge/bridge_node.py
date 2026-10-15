"""同期したRGB/関節状態を送る。モータpublisherは作成しない。"""

import base64
from collections import deque
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import String
from .core import DryRunClient, LatestWorker


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
            "joint_state_topic": "/joint_states",
            "infer_timeout_s": 1.0,
        }
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        p = lambda key: self.get_parameter(key).value
        if p("use_sim_time"):
            raise ValueError(
                "ROS simulation time is not supported by unix HTTP contract"
            )
        topics = [t for t in p("camera_topics") if t]
        names = [n for n in p("camera_names") if n]
        if len(topics) != len(names) or len(set(names)) != len(names):
            raise ValueError("invalid camera mapping")
        self.images = {name: deque(maxlen=8) for name in names}
        self.joint_buffer = deque(maxlen=8)
        self.worker = LatestWorker(
            DryRunClient(
                p("server_url"),
                p("model_id"),
                p("task"),
                p("infer_timeout_s"),
                dry_run=p("dry_run"),
            )
        )
        self.output = self.create_publisher(String, "~/dry_run_actions", 10)
        self.subscriptions_owned = []
        for name, topic in zip(names, topics):
            self.subscriptions_owned.append(
                self.create_subscription(
                    Image,
                    topic,
                    lambda msg, n=name: self.image(n, msg),
                    qos_profile_sensor_data,
                )
            )
        self.subscriptions_owned.append(
            self.create_subscription(
                JointState, p("joint_state_topic"), self.joints, qos_profile_sensor_data
            )
        )
        self.create_timer(0.02, self.poll)

    @staticmethod
    def stamp(msg):
        return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec

    def image(self, name, msg):
        if (
            msg.encoding != "rgb8"
            or not 0 < msg.width <= 1024
            or not 0 < msg.height <= 1024
            or msg.step < msg.width * 3
            or len(msg.data) != msg.step * msg.height
        ):
            return
        raw = bytes(msg.data)
        packed = b"".join(
            raw[i * msg.step : i * msg.step + msg.width * 3] for i in range(msg.height)
        )
        self.images[name].append(
            dict(
                timestamp_ns=self.stamp(msg),
                frame_id=msg.header.frame_id,
                calibration_id="synthetic_unverified",
                width=msg.width,
                height=msg.height,
                encoding="rgb8",
                data_base64=base64.b64encode(packed).decode(),
            )
        )
        self.synchronize()

    def joints(self, msg):
        self.joint_buffer.append(msg)
        self.synchronize()

    def synchronize(self):
        if not self.joint_buffer:
            return
        msg = self.joint_buffer[-1]
        timestamp = self.stamp(msg)
        images = {}
        for name, frames in self.images.items():
            if not frames:
                return
            frame = min(frames, key=lambda f: abs(f["timestamp_ns"] - timestamp))
            if abs(frame["timestamp_ns"] - timestamp) > 50_000_000:
                return
            images[name] = frame
        self.worker.offer(
            dict(
                timestamp_ns=timestamp,
                joint_names=list(msg.name),
                joint_positions_rad=list(msg.position),
                images=images,
            )
        )
        self.joint_buffer.clear()

    def poll(self):
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
