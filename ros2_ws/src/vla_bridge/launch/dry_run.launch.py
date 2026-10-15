"""モデルと接続先を指定してdry-runブリッジを起動する。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("server_url", default_value="http://127.0.0.1:8000"),
            DeclareLaunchArgument("model_id", default_value="mock_piper"),
            DeclareLaunchArgument("task", default_value="synthetic dry-run fixture"),
            Node(
                package="vla_bridge",
                executable="bridge_node",
                name="vla_bridge",
                parameters=[
                    {
                        "dry_run": True,
                        "server_url": LaunchConfiguration("server_url"),
                        "model_id": LaunchConfiguration("model_id"),
                        "task": LaunchConfiguration("task"),
                    }
                ],
                output="screen",
            ),
        ]
    )
