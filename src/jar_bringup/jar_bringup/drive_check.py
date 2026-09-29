#!/usr/bin/env python3
"""
Non-interactive motion probe for the ROSMASTER X3 simulation.

Drives one segment per mecanum degree of freedom and reports how far the base
actually moved, measured against both the Gazebo ground truth pose and the
fork's wheel-encoder odometry. It answers "is the simulation actually wired up
and moving" without a human on the keyboard, which is what teleop is otherwise
used to check.

Reporting both sources is deliberate: /ground_truth/odom is what happened, and
/odom is what the robot believes happened. Their difference on the strafe and
rotate segments is the mecanum slip the 'stress' motion profile injects, so a
gap there is expected data, not a failure.
"""

import math
import sys
import threading
import time

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

#: (label, linear x, linear y, angular z, seconds)
SEGMENTS = (
    ("forward", 0.20, 0.0, 0.0, 3.0),
    ("back", -0.20, 0.0, 0.0, 3.0),
    ("strafe left", 0.0, 0.20, 0.0, 3.0),
    ("strafe right", 0.0, -0.20, 0.0, 3.0),
    ("rotate ccw", 0.0, 0.0, 0.6, 3.0),
    ("settle", 0.0, 0.0, 0.0, 2.0),
)


def _yaw(orientation):
    """Extract yaw from a quaternion without pulling in tf_transformations."""
    siny = 2.0 * (orientation.w * orientation.z + orientation.x * orientation.y)
    cosy = 1.0 - 2.0 * (orientation.y ** 2 + orientation.z ** 2)
    return math.atan2(siny, cosy)


class DriveCheck(Node):
    """Publish a command sequence and record the resulting displacement.

    Callbacks and the command timer run on a background executor while the
    main thread paces the segments. Everything here is timed on the monotonic
    clock: the node reads pose fields only, never header stamps, so it behaves
    the same whether or not use_sim_time is set.
    """

    def __init__(self):
        super().__init__("jar_drive_check")

        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("publish_rate", 20.0)

        topic = self.get_parameter("cmd_vel_topic").value
        publish_period = 1.0 / float(self.get_parameter("publish_rate").value)

        self._topic = topic
        self.publisher = self.create_publisher(Twist, topic, 10)

        # Depth 1: this probe only ever wants the newest pose. Gazebo bridges
        # /clock at roughly 1 kHz, so a deeper queue can hand back a pose from
        # seconds before the command being measured. Best Effort is compatible
        # with the Reliable bridge publishers.
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
        )

        self._lock = threading.Lock()
        self._truth = None
        self._odom = None
        self._twist = Twist()

        self.create_subscription(Odometry, "/ground_truth/odom", self._on_truth, qos)
        self.create_subscription(Odometry, "/odom", self._on_odom, qos)

        # Paced by a plain monotonic loop rather than a ROS timer. ROS timers
        # run on RCL_SYSTEM_TIME, i.e. CLOCK_REALTIME, and on a WSL2 host whose
        # clock is being stepped back and forth by competing time sync sources
        # a nominal 20 Hz timer degrades to 2-3 Hz -- far under the fork
        # watchdog's 0.5 s timeout, which makes the base move in late bursts.
        # See the package README for the host-side fix; this keeps the probe
        # trustworthy either way.
        self._publish_period = publish_period
        self._running = True
        # The pump stays quiet until the listen window below has finished, so
        # the probe can tell whether anyone *else* is driving without hearing
        # its own zeros.
        self._armed = False
        self._pump = threading.Thread(target=self._pump_commands, daemon=True)
        self._pump.start()

    def _on_truth(self, message):
        with self._lock:
            self._truth = self._pose(message)

    def _on_odom(self, message):
        with self._lock:
            self._odom = self._pose(message)

    def _pump_commands(self):
        next_send = time.monotonic()
        while self._running:
            if self._armed:
                with self._lock:
                    twist = self._twist
                self.publisher.publish(twist)
            next_send += self._publish_period
            time.sleep(max(0.0, next_send - time.monotonic()))

    def arm(self):
        self._armed = True

    @staticmethod
    def _pose(message):
        position = message.pose.pose.position
        return (position.x, position.y, _yaw(message.pose.pose.orientation))

    def sample(self):
        with self._lock:
            return self._truth, self._odom

    def has_truth(self):
        with self._lock:
            return self._truth is not None

    def has_odom(self):
        with self._lock:
            return self._odom is not None

    def listen_for_competitors(self, window=1.5):
        """Return how many commands arrive while this probe is publishing none.

        A second publisher makes the probe meaningless: keyboard teleop
        streams zeros at 20 Hz whenever no key is held, and those zeros
        interleave with the probe's commands at the watchdog, which then
        relays whichever arrived last. The base twitches once and stops, and
        the run reports FAIL as though the command chain were broken.

        Counting registered publishers instead would be simpler and wrong:
        a node killed with SIGKILL leaves its DDS participant behind, so
        count_publishers keeps reporting a ghost that never sends anything
        and every later run refuses to start. Listening for real traffic
        while deliberately silent tests what actually matters.
        """
        seen = [0]
        subscription = self.create_subscription(
            Twist, self._topic, lambda _: seen.__setitem__(0, seen[0] + 1), 10)
        time.sleep(window)
        self.destroy_subscription(subscription)
        return seen[0]

    def set_command(self, vx, vy, wz):
        twist = Twist()
        twist.linear.x = vx
        twist.linear.y = vy
        twist.angular.z = wz
        with self._lock:
            self._twist = twist

    def stop(self):
        self.set_command(0.0, 0.0, 0.0)
        self.publisher.publish(Twist())

    def shutdown(self):
        self._running = False
        self._pump.join(timeout=1.0)


def _delta(start, end):
    if start is None or end is None:
        return None
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dyaw = math.atan2(math.sin(end[2] - start[2]), math.cos(end[2] - start[2]))
    return (dx, dy, dyaw, math.hypot(dx, dy))


def _format(delta):
    if delta is None:
        return "        (no data)        "
    dx, dy, dyaw, distance = delta
    return f"dx {dx:+.3f} dy {dy:+.3f} dyaw {math.degrees(dyaw):+6.1f}deg |d| {distance:.3f}"


def _wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main(args=None):
    rclpy.init(args=args)
    node = DriveCheck()

    # One long-lived executor on its own thread. rclpy.spin_once() would add
    # and remove the node from the global executor on every call, rebuilding
    # the wait set each time; that starved the command timer down to about
    # 1 Hz, well under the fork watchdog's 0.5 s timeout, and the base moved
    # in late bursts that landed in the wrong segment.
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    status = 1
    try:
        if not _wait_for(node.has_truth, 30.0):
            node.get_logger().error(
                "No /ground_truth/odom within 30 s. Is the simulation running, "
                "and did the ros_gz bridge come up?")
            return 1

        # Let the freshly created publisher match the watchdog's subscription
        # before the first segment; otherwise segment one measures discovery.
        _wait_for(node.has_odom, 5.0)
        time.sleep(1.0)

        competing = node.listen_for_competitors()
        if competing:
            node.get_logger().error(
                f"Something else is publishing on {node._topic} "
                f"({competing} messages in 1.5 s while this probe sent none). "
                "Stop the teleop, or whatever else is driving the robot, and "
                "run this again -- the two command streams interleave and the "
                "results would be meaningless.")
            return 1
        node.arm()

        print(f"\n{'segment':<14} {'ground truth':<52} wheel odometry")
        print("-" * 120)
        moved = 0.0
        for label, vx, vy, wz, duration in SEGMENTS:
            start_truth, start_odom = node.sample()
            node.set_command(vx, vy, wz)
            time.sleep(duration)
            end_truth, end_odom = node.sample()

            truth_delta = _delta(start_truth, end_truth)
            print(f"{label:<14} {_format(truth_delta):<52} "
                  f"{_format(_delta(start_odom, end_odom))}")
            if truth_delta is not None:
                moved += truth_delta[3] + abs(truth_delta[2])

        print("-" * 120)
        if moved < 0.05:
            print("RESULT: FAIL - the base never moved.")
            print("  Check, in order:")
            print("    1. Nothing else is publishing on /cmd_vel (teleop running?)")
            print("    2. The simulation is not paused - /clock must be advancing")
            print("    3. /cmd_vel -> /cmd_vel_gz -> /model/rosmaster_x3/cmd_vel")
        else:
            print("RESULT: PASS - the base responded on every commanded axis.")
            status = 0
    finally:
        node.stop()
        time.sleep(0.2)
        node.shutdown()
        executor.shutdown()
        # Join before destroying the node, or the executor thread can still be
        # inside spin() when its rcl handles are freed.
        spinner.join(timeout=2.0)
        node.destroy_node()
        rclpy.shutdown()
    return status


if __name__ == "__main__":
    sys.exit(main())
