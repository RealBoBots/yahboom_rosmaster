#!/usr/bin/env python3
"""
Mecanum keyboard teleoperation for the ROSMASTER X3.

Why not teleop_twist_keyboard: the Humble build (2.4.1) blocks on
``sys.stdin.read(1)`` and publishes exactly one Twist per keystroke, with no
repeat option. The fork's cmd_vel_watchdog zeroes the command 0.5 s after the
last message, so a held key produces a stutter — move, stop, move — around the
terminal's autorepeat delay.

This node instead publishes continuously at a fixed rate and treats each
keystroke as refreshing the command for ``key_timeout`` seconds. Terminal
autorepeat then lands well inside that window, so holding a key drives
smoothly and releasing it coasts to a stop one timeout later. The watchdog
never trips, because there is always a publisher on /cmd_vel.

Layout (mecanum, strafing is a first-class axis, not a rotation):

     q  w  e         w/s : forward / back      q/e : diagonal
     a  s  d         a/d : strafe left / right
     j     l         j/l : rotate CCW / CW
   space / k : stop        z/x : slower / faster        Ctrl-C : quit
"""

import sys
import termios
import time
import threading
import tty

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node

# (x, y, theta) unit command per key. Diagonals stay at unit length on each
# axis; the mecanum base resolves them into wheel speeds itself.
MOVE_BINDINGS = {
    "w": (1.0, 0.0, 0.0),
    "s": (-1.0, 0.0, 0.0),
    "a": (0.0, 1.0, 0.0),
    "d": (0.0, -1.0, 0.0),
    "q": (1.0, 1.0, 0.0),
    "e": (1.0, -1.0, 0.0),
    "j": (0.0, 0.0, 1.0),
    "l": (0.0, 0.0, -1.0),
}

SPEED_BINDINGS = {"z": 0.9, "x": 1.1}
STOP_KEYS = (" ", "k")

BANNER = __doc__.split("Layout", 1)[1]


class KeyboardTeleop(Node):
    """Publish /cmd_vel at a steady rate from the most recent keystroke."""

    def __init__(self):
        super().__init__("jar_keyboard_teleop")

        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("linear_speed", 0.25)
        self.declare_parameter("angular_speed", 1.0)
        self.declare_parameter("publish_rate", 20.0)
        # Comfortably longer than a terminal's ~0.5 s autorepeat delay, so a
        # held key never falls through the gap and stutters.
        self.declare_parameter("key_timeout", 0.8)

        topic = self.get_parameter("cmd_vel_topic").value
        self.linear_speed = float(self.get_parameter("linear_speed").value)
        self.angular_speed = float(self.get_parameter("angular_speed").value)
        publish_rate = float(self.get_parameter("publish_rate").value)
        self.key_timeout = float(self.get_parameter("key_timeout").value)

        self.publisher = self.create_publisher(Twist, topic, 10)

        self._lock = threading.Lock()
        self._command = (0.0, 0.0, 0.0)
        self._expires_at = 0.0

        # Paced by a plain monotonic loop rather than a ROS timer. ROS timers
        # run on RCL_SYSTEM_TIME, i.e. CLOCK_REALTIME, and on a WSL2 host whose
        # clock is being stepped by competing time sync sources a nominal 20 Hz
        # timer degrades to 2-3 Hz. That is slower than the fork watchdog's
        # 0.5 s timeout, so the base would stutter no matter how a key is held.
        # See the package README for the host-side fix.
        self._publish_period = 1.0 / publish_rate
        self._running = True
        self._pump = threading.Thread(target=self._pump_commands, daemon=True)
        self._pump.start()
        self.get_logger().info(f"Publishing mecanum commands on {topic}")

    def set_command(self, command):
        """Latch a unit command and restart its expiry window.

        Keystroke expiry is wall-clock by nature, so it is timed on the
        monotonic clock. Using the node clock would tie it to use_sim_time,
        where a paused or slowed simulation would leave the last command
        latched indefinitely.
        """
        with self._lock:
            self._command = command
            self._expires_at = time.monotonic() + self.key_timeout

    def stop(self):
        with self._lock:
            self._command = (0.0, 0.0, 0.0)
            self._expires_at = 0.0

    def scale_speed(self, factor):
        self.linear_speed = max(0.01, min(2.0, self.linear_speed * factor))
        self.angular_speed = max(0.05, min(6.0, self.angular_speed * factor))
        return self.linear_speed, self.angular_speed

    def _pump_commands(self):
        next_send = time.monotonic()
        while self._running:
            self._publish()
            next_send += self._publish_period
            time.sleep(max(0.0, next_send - time.monotonic()))

    def shutdown(self):
        self._running = False
        self._pump.join(timeout=1.0)

    def _publish(self):
        now = time.monotonic()
        with self._lock:
            if now >= self._expires_at:
                self._command = (0.0, 0.0, 0.0)
            x, y, theta = self._command

        twist = Twist()
        twist.linear.x = x * self.linear_speed
        twist.linear.y = y * self.linear_speed
        twist.angular.z = theta * self.angular_speed
        self.publisher.publish(twist)


def _read_key(settings):
    """Read one raw keystroke, restoring cooked mode before returning."""
    tty.setraw(sys.stdin.fileno())
    key = sys.stdin.read(1)
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
    return key


def main(args=None):
    if not sys.stdin.isatty():
        print(
            "jar_keyboard_teleop needs an interactive terminal: it reads raw "
            "keystrokes from stdin. Run it with 'ros2 run', or through "
            "jar_bringup/teleop.launch.py, which opens its own xterm.",
            file=sys.stderr)
        return 1

    settings = termios.tcgetattr(sys.stdin)
    rclpy.init(args=args)
    node = KeyboardTeleop()

    spinner = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spinner.start()

    print(BANNER)
    print(f"speed: linear {node.linear_speed:.2f} m/s  "
          f"angular {node.angular_speed:.2f} rad/s")
    try:
        while True:
            key = _read_key(settings)
            if key == "\x03":  # Ctrl-C
                break
            if key in MOVE_BINDINGS:
                node.set_command(MOVE_BINDINGS[key])
            elif key in STOP_KEYS:
                node.stop()
            elif key in SPEED_BINDINGS:
                linear, angular = node.scale_speed(SPEED_BINDINGS[key])
                print(f"speed: linear {linear:.2f} m/s  angular {angular:.2f} rad/s\r")
    finally:
        # Leave the base stopped rather than relying on the watchdog timeout.
        node.stop()
        node._publish()
        node.shutdown()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
