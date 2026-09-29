#!/usr/bin/env python3
"""
Challenge JAR 2026 simulation entrypoint for the ROSMASTER X3.

Wraps the read-only yahboom_rosmaster fork's canonical bringup and adds the
one thing it does not expose: a choice of Gazebo Fortress render engine.

On WSLg the default ``ogre2`` engine (Ogre-Next 2.2) aborts both the Gazebo
server and its GUI client with

    Ogre::UnimplementedException in GL3PlusTextureGpu::copyTo

because the Mesa D3D12 driver does not implement the hardware mipmap copy
Ogre-Next uses while building scene materials. ``LIBGL_ALWAYS_SOFTWARE=1``
avoids it by dropping to llvmpipe, at a large cost in speed. Selecting the
``ogre`` engine (OGRE 1.x) avoids the same crash while staying on the GPU.

The engine reaches the two processes by different routes, because the fork
builds its ``ign gazebo`` command lines itself and neither accepts a flag:

* server — the engine is written into a generated copy of the world file
  (see :mod:`jar_bringup.world_render_engine`), which the fork's existing
  ``world`` argument then loads.
* GUI client — this file starts its own ``ign gazebo -g`` with
  ``--render-engine-gui``, and asks the fork for ``gui:=false`` so only one
  client runs.

Nothing under ``src/yahboom_rosmaster`` is modified or required to change.
"""

import os
import shutil

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.logging import get_logger
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node

from jar_bringup.world_render_engine import (
    DEFAULT_ENGINE,
    SUPPORTED_ENGINES,
    resolve_world_path,
    retarget_world,
)


def _is_true(value):
    return value.lower() in ("true", "1", "yes")


def _on_wsl():
    """Detect WSL, where the GPU is reached through Mesa's D3D12 translation.

    That driver is the whole reason this package exists: ogre2 aborts on it in
    GL3PlusTextureGpu::copyTo, so the engine has to fall back to llvmpipe. A
    native Linux host with a real GL driver needs none of that, and must not
    inherit it -- the alternative engine leaves the rendering sensors dead, so
    a WSL-shaped default would silently blind a robot on a machine that was
    perfectly capable of running the correct one.
    """
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/sys/kernel/osrelease", encoding="utf-8") as release:
            return "microsoft" in release.read().lower()
    except OSError:
        return False


def _launch_simulation(context):
    """Retarget the world, include the fork's bringup, and own the GUI client."""
    logger = get_logger("jar_sim")

    engine = LaunchConfiguration("render_engine").perform(context)
    world = LaunchConfiguration("world").perform(context)
    gui = LaunchConfiguration("gui").perform(context)
    headless = LaunchConfiguration("headless").perform(context)
    raw_step = LaunchConfiguration("physics_step").perform(context).strip()
    physics_step = float(raw_step) if raw_step else None

    # OGRE 1.x loads and runs, but its gpu_lidar returns range_min on every
    # ray -- 1080 of 1080 pinned at 0.05 m in a maze where ogre2 reports 0.48
    # to 3.63 m. The crash is gone and the sensor is silently dead, which is
    # worse than a crash, so say so at launch rather than let a run look fine.
    if engine == "ogre":
        get_logger("jar_sim").warning(
            "Render engine 'ogre' does not drive the rendering sensors: "
            "/scan reads range_min on every ray and the RGB-D camera is "
            "unreliable. Use it only for motion and physics work. For LiDAR "
            "or camera, pass render_engine:=ogre2 software_gl:=true")

    pkg_gz = get_package_share_directory("yahboom_rosmaster_gazebo")
    pkg_bringup = get_package_share_directory("yahboom_rosmaster_bringup")
    worlds_dir = os.path.join(pkg_gz, "worlds")

    world_path = resolve_world_path(world, worlds_dir)
    if engine == DEFAULT_ENGINE and physics_step is None:
        # Nothing to override: the fork's worlds already declare ogre2, so
        # leave the file untouched and keep stock behaviour reproducible.
        server_world = world_path
        logger.info(f"Render engine '{engine}' (stock); using world {world_path}")
    else:
        server_world, patched = retarget_world(
            world_path, engine, physics_step=physics_step)
        if patched:
            logger.info(
                f"Render engine '{engine}': rewrote {patched} Sensors "
                f"system(s) into {server_world}")
        else:
            logger.warning(
                f"World {world_path} declares no Sensors system; the '{engine}' "
                "engine will only apply to the GUI client")
        if physics_step is not None:
            logger.warning(
                f"Physics step overridden to {physics_step:g} s "
                f"({1.0 / physics_step:g} Hz). This changes contact and slip "
                "behaviour: the fork's motion profiles are tuned at 1 ms, so "
                "do not use a coarser step for tuning or for trajectory tests")

    include_fork = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_bringup, "launch", "rosmaster_x3_sim.launch.py")),
        launch_arguments={
            "world": server_world,
            # This file starts the GUI client itself so it can pass
            # --render-engine-gui; letting the fork start one too would put two
            # clients on the same scene.
            "gui": "false",
            "headless": headless,
            # RViz is started below instead, so it can be given its own
            # LIBGL_ALWAYS_SOFTWARE. Inside the fork's launch it would inherit
            # the server's, and llvmpipe costs RViz more than a full core.
            "rviz": "false",
            "motion_profile": LaunchConfiguration("motion_profile"),
            "motion_bias": LaunchConfiguration("motion_bias"),
            "use_sim_time": LaunchConfiguration("use_sim_time"),
        }.items(),
    )

    actions = [include_fork]

    # Only the server ever needs llvmpipe, and only because ogre2 is the one
    # engine whose rendering sensors work. The viewers show a scene that is
    # already computed, so they stay on the GPU with OGRE 1.x -- the same
    # combination RViz has always used successfully on this driver. Forcing
    # them to software instead saturates the machine: RViz alone took 134% of
    # a core and the whole simulation stalled.
    hardware_gl = {"LIBGL_ALWAYS_SOFTWARE": "0"}

    if _is_true(LaunchConfiguration("rviz").perform(context)):
        actions.append(TimerAction(period=5.0, actions=[Node(
            package="rviz2",
            executable="rviz2",
            # Our copy of the fork's config, with the sensor displays set to
            # Best Effort. The fork's own file asks for Reliable on the camera
            # while its relay publishes Best Effort, so that display stays
            # blank -- and the camera is the point of running RViz here.
            arguments=["-d", os.path.join(
                get_package_share_directory("jar_bringup"),
                "rviz", "jar_gazebo.rviz")],
            parameters=[{"use_sim_time": _is_true(
                LaunchConfiguration("use_sim_time").perform(context))}],
            additional_env=hardware_gl,
            output="screen",
        )]))

    if _is_true(gui) and not _is_true(headless):
        ign_executable = shutil.which("ign")
        if ign_executable is None:
            raise RuntimeError("Could not find the Gazebo Fortress 'ign' executable")
        gazebo_client = ExecuteProcess(
            # Invoked through ruby for the same reason the fork does it: `ign`
            # is a ruby script, and calling it directly picks up a shell
            # wrapper that swallows the version pin.
            # The client always renders with OGRE 1.x on the GPU: it only draws
            # the scene and never runs a sensor, so the engine's broken
            # gpu_lidar does not reach it.
            cmd=[
                "ruby", ign_executable, "gazebo", "-g",
                "--force-version", "6",
                "--render-engine-gui", "ogre",
            ],
            additional_env=hardware_gl,
            output="screen",
        )
        # The client asks the server for scene info as soon as it starts; a
        # short delay lets the server finish loading the world first.
        actions.append(TimerAction(period=4.0, actions=[gazebo_client]))

    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "render_engine",
            # ogre2 everywhere: it is the only engine whose rendering sensors
            # work, so the default is always the one that produces a robot
            # that can see. Speed is the opt-in trade-off, not correctness.
            default_value="ogre2",
            choices=list(SUPPORTED_ENGINES),
            description=(
                "ign-rendering engine for the server. 'ogre2' is the only one "
                "whose rendering sensors work. 'ogre' (OGRE 1.x) runs on the "
                "GPU under WSLg without aborting, but its gpu_lidar returns "
                "range_min on every ray -- motion work only"),
        ),
        DeclareLaunchArgument(
            "world", default_value="empty.world",
            description="World name inside yahboom_rosmaster_gazebo/worlds, or an absolute path"),
        DeclareLaunchArgument(
            "gui", default_value="true", description="Launch the Gazebo GUI client"),
        DeclareLaunchArgument(
            "headless", default_value="false", description="Server only, no GUI client"),
        DeclareLaunchArgument(
            "rviz", default_value="true", description="Launch RViz2"),
        DeclareLaunchArgument(
            "motion_profile", default_value="stress",
            description="Wheel contact physics profile (ideal, stress)"),
        DeclareLaunchArgument(
            "motion_bias", default_value="false",
            description="Enable the uncalibrated motor drift model"),
        DeclareLaunchArgument(
            "use_sim_time", default_value="true", description="Use the simulation clock"),
        DeclareLaunchArgument(
            "physics_step", default_value="",
            description=(
                "Override the world's physics step in seconds, e.g. 0.004. "
                "Empty keeps the world's own value (1 ms). Raising it is the "
                "single largest speed lever: it cuts both the server's physics "
                "load and the /clock rate every use_sim_time node pays for. It "
                "also coarsens contact physics, so keep it empty whenever the "
                "result has to be trustworthy"),
        ),

        DeclareLaunchArgument(
            "software_gl",
            # Only WSL needs llvmpipe, and only because ogre2 aborts on its
            # D3D12 driver. A native host runs the same engine on the GPU.
            default_value="true" if _on_wsl() else "false",
            description=(
                "Force llvmpipe. Required alongside render_engine:=ogre2, "
                "which is the only engine whose rendering sensors work but "
                "which aborts on this host's D3D12 driver without it"),
        ),
        # Explicit either way, so an inherited LIBGL_ALWAYS_SOFTWARE=1 from the
        # shell never silently decides this. Mesa reads "0" as false.
        SetEnvironmentVariable(
            "LIBGL_ALWAYS_SOFTWARE",
            PythonExpression([
                "'1' if '", LaunchConfiguration("software_gl"),
                "'.lower() in ('true','1','yes') else '0'"])),
        # The fork sets this for its own client; set it here too since this
        # file starts the client outside the fork's launch description.
        SetEnvironmentVariable("QT_QPA_PLATFORM", "xcb"),

        OpaqueFunction(function=_launch_simulation),
    ])
