"""Dry-run ROS2 Humble bridge skeleton.

No subscriptions or motor publishers until P1 data/schema/safety are implemented.
"""
import rclpy
from rclpy.node import Node

class Bridge(Node):
    def __init__(self):
        super().__init__("vla_bridge")
        self.declare_parameter("server_url", "http://127.0.0.1:8000")
        self.declare_parameter("model_id", "mock_piper")
        self.declare_parameter("task", "")
        self.declare_parameter("dry_run", True)
        if not self.get_parameter("dry_run").value:
            raise RuntimeError("Live motion unsupported by scaffold; dry_run must remain true")
        self.get_logger().warn("Scaffold only: no camera subscriptions or action publishers")

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

if __name__ == "__main__":
    main()
