#!/usr/bin/env python3
"""
Joystick teleoperation for the ROSMASTER X3.

Two nodes: `joy` reads the device and publishes /joy, `teleop_twist_joy` maps
that to the /cmd_vel the fork's cmd_vel_watchdog consumes. The mapping lives in
config/joystick_mecanum.yaml, where axis_linear.y is what makes it a mecanum
controller rather than a differential one -- strafing is its own axis.

The deadman button is deliberate. Fortress's MecanumDrive has no command
timeout of its own, so releasing the button is the only hard guarantee the base
stops; the watchdog's 0.5 s timeout is the second line, not the first.

Runs alongside the keyboard teleop only one at a time: two publishers on
/cmd_vel interleave and the watchdog relays whichever arrived last.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_config = os.path.join(
        get_package_share_directory("jar_bringup"),
        "config", "joystick_mecanum.yaml")

    return LaunchDescription([
        DeclareLaunchArgument(
            "device", default_value="/dev/input/js0",
            description="Joystick device. Check with `ls /dev/input/js*`"),
        DeclareLaunchArgument(
            "config", default_value=default_config,
            description="Axis and button mapping for teleop_twist_joy"),
        DeclareLaunchArgument(
            "cmd_vel_topic", default_value="/cmd_vel",
            description="Public velocity topic the fork's watchdog consumes"),

        Node(
            package="joy",
            executable="joy_node",
            name="joy_node",
            output="screen",
            parameters=[{
                "device_name": "",
                "dev": LaunchConfiguration("device"),
                # Ignore stick noise around centre so a resting joystick does
                # not trickle commands into the watchdog.
                "deadzone": 0.08,
                "autorepeat_rate": 20.0,
            }],
        ),

        Node(
            package="teleop_twist_joy",
            executable="teleop_node",
            name="teleop_twist_joy_node",
            output="screen",
            parameters=[LaunchConfiguration("config")],
            remappings=[("/cmd_vel", LaunchConfiguration("cmd_vel_topic"))],
        ),
    ])
