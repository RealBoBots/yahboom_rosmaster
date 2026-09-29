#!/usr/bin/env python3
"""
Keyboard teleoperation for the ROSMASTER X3, in its own terminal window.

ros2 launch cannot hand a child process the controlling TTY, and the teleop
node reads raw keystrokes, so it is started under an xterm rather than
inheriting this launch's stdin. Launching it separately from sim.launch.py is
deliberate: teleop is restarted far more often than the simulation.

Run it directly instead if you already have a spare terminal:

    ros2 run jar_bringup keyboard_teleop
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _teleop_node(prefix, condition):
    return Node(
        package="jar_bringup",
        executable="keyboard_teleop",
        name="jar_keyboard_teleop",
        output="screen",
        prefix=prefix,
        parameters=[{
            "use_sim_time": LaunchConfiguration("use_sim_time"),
            "cmd_vel_topic": LaunchConfiguration("cmd_vel_topic"),
            "linear_speed": LaunchConfiguration("linear_speed"),
            "angular_speed": LaunchConfiguration("angular_speed"),
        }],
        condition=condition,
    )


def generate_launch_description():
    own_window = LaunchConfiguration("own_window")

    return LaunchDescription([
        DeclareLaunchArgument(
            "own_window", default_value="true",
            description=(
                "Open the teleop in its own xterm. Set false only when this "
                "launch already owns an interactive terminal")),
        DeclareLaunchArgument(
            "cmd_vel_topic", default_value="/cmd_vel",
            description="Public velocity topic the fork's cmd_vel_watchdog consumes"),
        DeclareLaunchArgument(
            "linear_speed", default_value="0.25",
            description="Metres per second at full deflection, before z/x scaling"),
        DeclareLaunchArgument(
            "angular_speed", default_value="1.0",
            description="Radians per second at full deflection, before z/x scaling"),
        # Off by default, unlike the rest of the stack. This node paces itself
        # on the monotonic clock and reads no header stamps, so simulation time
        # buys it nothing -- while subscribing to /clock, which Gazebo publishes
        # at hundreds of hertz, cost it 44% of a core for callbacks it discards.
        DeclareLaunchArgument(
            "use_sim_time", default_value="false",
            description=(
                "Leave false: the teleop is monotonic-paced and only pays for "
                "the /clock subscription")),

        # -hold keeps the window up if the node exits early, so the error is
        # readable instead of vanishing with the window.
        _teleop_node(
            "xterm -geometry 80x24 -title 'JAR teleop' -hold -e",
            IfCondition(own_window)),
        _teleop_node(None, UnlessCondition(own_window)),
    ])
