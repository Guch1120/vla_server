from setuptools import setup

setup(
    name="vla_bridge",
    version="0.0.1",
    packages=["vla_bridge"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/vla_bridge"]),
        ("share/vla_bridge", ["package.xml"]),
        ("share/vla_bridge/launch", ["launch/dry_run.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Project Maintainer",
    maintainer_email="maintainer@example.com",
    description="Dry-run ROS 2 VLA bridge scaffold",
    license="Apache-2.0",
    entry_points={"console_scripts": ["bridge_node = vla_bridge.bridge_node:main"]},
)
