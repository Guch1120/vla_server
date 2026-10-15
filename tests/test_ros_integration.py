"""合成ROSトピック→HTTP→ログ用ROSトピック。実機出力は持たない。"""

import json
import socket
import threading
import time
import pytest

rclpy = pytest.importorskip("rclpy")
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
from builtin_interfaces.msg import Time
import uvicorn
from vla_server.api import create_app
from vla_bridge.bridge_node import Bridge


@pytest.mark.parametrize("domain", ["robot", "ros_sim", "robot_clock"])
def test_ros_rgb_roundtrip_and_disconnect(domain):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            f"server_url:=http://127.0.0.1:{port}",
            "-p",
            "model_id:=mock_piper_rgb6",
            "-p",
            "camera_topics:=[/synthetic/front]",
            "-p",
            "camera_names:=[front]",
            "-p",
            "infer_timeout_s:=0.5",
            "-p",
            "joint_names:=[joint1,joint2,joint3,joint4,joint5,joint6]",
            "-p",
            "joint_source_names:=[joint1,joint2,joint3,joint4,joint5,joint6]",
            "-p",
            "gripper_joint_name:=joint7",
            "-p",
            "gripper_calibration_id:=piper_finger_displacement_m_v1",
            "-p",
            f"use_sim_time:={str(domain != 'robot').lower()}",
            "-p",
            f"clock_domain:={'robot' if domain == 'robot_clock' else domain}",
        ]
    )
    bridge = None
    fixture = None
    executor = None
    try:
        bridge = Bridge()
        fixture = Node("synthetic_fixture")
        executor = SingleThreadedExecutor()
        executor.add_node(bridge)
        executor.add_node(fixture)
        received = []
        fixture.create_subscription(
            String,
            "/vla_bridge/dry_run_actions",
            lambda m: received.append(json.loads(m.data)),
            10,
        )
        images = fixture.create_publisher(Image, "/synthetic/front", 10)
        joints = fixture.create_publisher(JointState, "/joint_states", 10)
        clock_pub = fixture.create_publisher(Clock, "/clock", 10)
        started = time.monotonic()

        def publish():
            if domain == "robot":
                stamp = fixture.get_clock().now().to_msg()
            else:
                ns = int((100 + time.monotonic() - started) * 1e9)
                stamp = Time(sec=ns // 10**9, nanosec=ns % 10**9)
                clock_pub.publish(Clock(clock=stamp))
            image = Image()
            image.header.stamp = stamp
            image.header.frame_id = "synthetic_camera"
            image.encoding = "rgb8"
            image.width = 1
            image.height = 1
            image.step = 3
            image.data = [0, 0, 0]
            joint = JointState()
            joint.header.stamp = stamp
            joint.name = [
                "joint8",
                "joint6",
                "joint5",
                "joint4",
                "joint3",
                "joint2",
                "joint1",
                "joint7",
            ]
            joint.position = [-0.02, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.02]
            images.publish(image)
            joints.publish(joint)

        deadline = time.monotonic() + 8
        while not received and time.monotonic() < deadline:
            publish()
            executor.spin_once(timeout_sec=0.02)
        assert received and received[0]["model_id"] == "mock_piper_rgb6"
        assert received[0]["actions"] == [[0.0] * 6, [0.0] * 6]
        assert received[0]["source_clock_domain"] == (
            "robot" if domain == "robot_clock" else domain
        )
        assert not any(
            "trajectory" in n or "servo" in n
            for n, _ in bridge.get_publisher_names_and_types_by_node("vla_bridge", "/")
        )
        server.should_exit = True
        thread.join(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            publish()
            executor.spin_once(timeout_sec=0.02)
            if bridge.worker.state == "HOLD" and bridge.worker.client.spec is None:
                break
        assert bridge.worker.state == "HOLD"
        count = len(received)
        for _ in range(10):
            executor.spin_once(timeout_sec=0.02)
        assert len(received) == count
    finally:
        if executor:
            executor.shutdown()
        if bridge:
            bridge.destroy_node()
        if fixture:
            fixture.destroy_node()
        rclpy.shutdown()
        server.should_exit = True
        thread.join(timeout=3)
        sock.close()


def test_sensor_before_clock_and_reset_are_safe():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            "use_sim_time:=true",
            "-p",
            "camera_topics:=[/synthetic/front]",
            "-p",
            "camera_names:=[front]",
        ]
    )
    bridge = None
    try:
        bridge = Bridge()
        stamp = Time(sec=100)
        image = Image()
        image.header.stamp = stamp
        image.header.frame_id = "fixture"
        image.width = 1
        image.height = 1
        image.step = 3
        image.encoding = "rgb8"
        image.data = [1, 2, 3]
        joint = JointState()
        joint.header.stamp = stamp
        joint.name = ["joint_2", "joint_1"]
        joint.position = [0.2, 0.1]
        bridge.image("front", image)
        bridge.joints(joint)
        assert bridge.worker.pending is None
        assert len(bridge.joint_buffer) == 1 and len(bridge.images["front"]) == 1
        bridge.receive_clock(Clock(clock=stamp))
        pending = bridge.worker.pending
        assert pending["joint_positions_rad"] == [0.1, 0.2]
        assert pending["timestamp_ns"] == 100_000_000_000
        assert pending["clock_domain"] == "ros_sim"
        epoch = pending["clock_epoch"]
        bridge.receive_clock(Clock(clock=Time(sec=1)))
        assert bridge.worker.pending is None and bridge.worker.state == "HOLD"
        assert bridge.execution_clock.read().epoch != epoch
        assert not bridge.images["front"] and not bridge.joint_buffer
        bridge.execution_clock.last_progress -= 2.0
        bridge.poll()
        assert bridge.worker.state == "HOLD"
    finally:
        if bridge:
            bridge.destroy_node()
        rclpy.shutdown()


def test_simulation_domain_requires_clock_source():
    rclpy.init(args=["--ros-args", "-p", "clock_domain:=ros_sim"])
    try:
        with pytest.raises(ValueError, match="clock topic required"):
            Bridge()
    finally:
        rclpy.shutdown()
