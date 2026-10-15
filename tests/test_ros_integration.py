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
import uvicorn
from vla_server.api import create_app
from vla_bridge.bridge_node import Bridge


def test_ros_rgb_roundtrip_and_disconnect():
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
            "model_id:=mock_rgb",
            "-p",
            "camera_topics:=[/synthetic/front]",
            "-p",
            "camera_names:=[front]",
            "-p",
            "infer_timeout_s:=0.2",
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

        def publish():
            stamp = fixture.get_clock().now().to_msg()
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
            joint.name = ["joint_1", "joint_2"]
            joint.position = [0.0, 0.0]
            images.publish(image)
            joints.publish(joint)

        deadline = time.monotonic() + 8
        while not received and time.monotonic() < deadline:
            publish()
            executor.spin_once(timeout_sec=0.02)
        assert received and received[0]["model_id"] == "mock_rgb"
        assert received[0]["actions"] == [[0.0, 0.0], [0.0, 0.0]]
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
