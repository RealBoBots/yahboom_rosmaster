# jar_bringup

Club-side bringup for the **Challenge JAR 2026** (AIR Club UdeSA) ROSMASTER X3.

`src/yahboom_rosmaster` is a read-only fork. Nothing in this package modifies
it, or requires it to change — everything here works through the launch
arguments and topics the fork already exposes, so this directory can move to
another repository on its own.

## Render engine: avoiding the WSLg Gazebo crash

On WSLg with the Mesa D3D12 driver, Gazebo Fortress aborts with

```
OGRE EXCEPTION(9:UnimplementedException): in GL3PlusTextureGpu::copyTo
```

Ogre-Next 2.2 (the `ogre2` engine) generates hardware mipmaps through a
texture copy the D3D12 driver does not implement. It happens while the scene
materials are built, so it kills the **server** as soon as a rendering sensor
spawns *and* the **GUI client** as soon as it draws. `LIBGL_ALWAYS_SOFTWARE=1`
avoids it only by dropping the whole stack to llvmpipe.

Selecting the OGRE 1.x engine (`ogre`) avoids the crash while staying on the
GPU. It never takes the mipmap path, and RViz already proves OGRE 1.x is fine
on this driver.

**But OGRE 1.x does not drive the rendering sensors.** Its gpu_lidar returns
`range_min` on every ray: 1080 of 1080 pinned at 0.05 m in a maze where ogre2
reports 0.48 m to 3.63 m against the same walls. The simulation looks healthy
and the LiDAR is silently dead, which is worse than the crash it replaced.

So the engine choice is a choice between two working things, not one:

| you need | engine | LIBGL_ALWAYS_SOFTWARE | cost |
|---|---|---|---|
| motion, physics, teleop | `ogre` | 0 (GPU) | RTF ~1.0, no usable /scan |
| LiDAR or camera | `ogre2` | 1 (llvmpipe) | working sensors, RTF 0.5-0.8 |

`sim.launch.py` warns at startup when `ogre` is selected, and gives the server
llvmpipe only when `software_gl:=true`. The viewers keep the GPU either way
through `additional_env`: RViz on llvmpipe costs more than a full core, and
forcing it there stalled the whole simulation.

Measured on the Quadro M1000M via WSLg, empty world, full robot with LiDAR and
RGB-D camera:

| engine | server | GUI client | renderer | RTF |
|---|---|---|---|---|
| `ogre2` (upstream default) | aborts | aborts | — | — |
| `ogre2` + `LIBGL_ALWAYS_SOFTWARE=1` | runs | runs | llvmpipe | slow |
| `ogre` (this package's default) | runs | runs | D3D12 (NVIDIA Quadro M1000M) | ~0.94 |

The fork's launch file builds its `ign gazebo` command lines itself, so neither
`--render-engine` nor `--render-engine-server` can reach the server. The engine
therefore arrives by two different routes:

* **server** — `jar_bringup.world_render_engine` rewrites the
  `<render_engine>` element of the world's Sensors system into a generated copy
  under `/tmp/jar_bringup_worlds/`, and passes that copy to the fork's existing
  `world` argument. Only that one element changes; `model://` URIs keep
  resolving through `IGN_GAZEBO_RESOURCE_PATH`.
* **GUI client** — `sim.launch.py` starts its own `ign gazebo -g
  --render-engine-gui <engine>` and asks the fork for `gui:=false`, so exactly
  one client runs.

`sim.launch.py` also sets `LIBGL_ALWAYS_SOFTWARE=0`, which neutralises the old
workaround if it is still exported in your shell.

## Running it

```bash
ros2 launch jar_bringup sim.launch.py
```

Useful arguments (the rest are forwarded to the fork unchanged):

| argument | default | meaning |
|---|---|---|
| `render_engine` | `ogre` | `ogre` or `ogre2`. `ogre2` reproduces the upstream crash on this host |
| `world` | `empty.world` | name inside `yahboom_rosmaster_gazebo/worlds`, or an absolute path |
| `gui` / `rviz` / `headless` | `true` / `true` / `false` | as upstream |
| `motion_profile` | `stress` | `ideal` for the zero-slip baseline |
| `motion_bias` | `false` | uncalibrated motor drift, resampled per launch |

Maze world with the stock engine, to reproduce the crash:

```bash
ros2 launch jar_bringup sim.launch.py world:=maze_1_6x5 render_engine:=ogre2
```

## Performance: the physics step is the lever

Measured on this host, empty world, full robot with LiDAR and RGB-D camera,
`ogre` engine throughout:

| viewers | physics step | RTF |
|---|---|---|
| Gazebo GUI + RViz | 1 ms (stock) | 0.58 |
| Gazebo GUI only | 1 ms | 0.60–0.70 |
| RViz only | 1 ms | 0.72–0.77 |
| headless | 1 ms | 0.94 |
| headless, no rendering sensors | 1 ms | 0.97 |
| **Gazebo GUI + RViz** | **2 ms** | **0.99** |
| Gazebo GUI + RViz | 4 ms | 1.00 |

```bash
ros2 launch jar_bringup sim.launch.py physics_step:=0.002
```

Two things follow from that table.

**Rendering sensors are not the bottleneck.** Turning them off buys 0.03 RTF.
Do not chase them.

**The 1 ms physics step is.** It sets the server's own load *and* the `/clock`
rate, which every `use_sim_time` node pays for in callbacks — at 1 ms Gazebo
publishes `/clock` at roughly 1 kHz, and the fork's `calculated_odometry.py`
burns 70% of a core doing nothing but servicing it. At 4 ms that same node
drops to 7%, the server halves, and RViz falls by two thirds.

`physics_step` is **opt-in and defaults to the world's own value**, because it
coarsens contact physics and the fork's motion profiles are tuned at 1 ms.
Use 2 ms for interactive development, where it buys full real time at both
viewers for the smallest fidelity change. Leave it unset for anything whose
result has to be trustworthy — profile tuning, trajectory tests, final runs.
The generated world carries the step in its file name
(`empty.ogre.0.002s.world`), so it is always visible which pacing produced a
result.

`real_time_update_rate` is rewritten alongside `max_step_size`: it caps
iterations per second, so a world that pins it to 1000 (`maze_1_6x5` does)
would otherwise ignore the larger step entirely.

## Teleoperation

```bash
ros2 launch jar_bringup teleop.launch.py
```

Opens an xterm — `ros2 launch` cannot hand a child process the controlling
TTY, and the node reads raw keystrokes. If you already have a spare terminal:

```bash
ros2 run jar_bringup keyboard_teleop
```

```
     q  w  e         w/s : forward / back      q/e : diagonal
     a  s  d         a/d : strafe left / right
     j     l         j/l : rotate CCW / CW
   space / k : stop        z/x : slower / faster        Ctrl-C : quit
```

Publishes on `/cmd_vel`, which the fork's `cmd_vel_watchdog` relays to
`/cmd_vel_gz` and on to the native Gazebo MecanumDrive.

Not `teleop_twist_keyboard`: the Humble build (2.4.1) blocks on
`sys.stdin.read(1)` and emits one Twist per keystroke, with no repeat option.
The fork's watchdog zeroes the command 0.5 s after the last message, so a held
key stutters around the terminal's autorepeat delay. This node publishes
continuously and treats a keystroke as refreshing the command for
`key_timeout` (0.8 s), which autorepeat lands well inside.

## Checking the simulation without a human

```bash
ros2 run jar_bringup drive_check
```

Drives one segment per mecanum degree of freedom and prints the displacement
measured by both `/ground_truth/odom` (what happened) and `/odom` (what the
robot believes happened). A gap between the two on the strafe and rotate rows
is the slip the `stress` profile injects, not a failure.

## Host prerequisite: a stable CLOCK_REALTIME

**This host does not currently have one, and ROS 2 needs it.**

`systemd-timesyncd` and the WSL hypervisor's own time sync are both setting the
clock, roughly 87 seconds apart. `CLOCK_REALTIME` is stepped backwards and
forwards by that amount several times per second, while `CLOCK_MONOTONIC` stays
clean:

```
MONOTONIC   max_backward  +0.000000s
REALTIME    max_backward -86.981285s   max_forward_gap 86.983564s
```

`journalctl` records `Time jumped backwards, rotating` continuously, and
`timedatectl show-timesync` reports `Jitter=32.87s`.

ROS 2 timers run on `RCL_SYSTEM_TIME`, which is `CLOCK_REALTIME`. Every ROS
timer on this host is therefore degraded by roughly a factor of ten:

| what | asked for | measured |
|---|---|---|
| bare `rclpy` timer | 20 Hz | 2.6–3.5 Hz |
| `ros2 topic pub -r 20` | 20 Hz | 7.6 Hz |
| fork's `cmd_vel_watchdog` republish | 30 Hz | 1.8 Hz |

The watchdog's own timeout uses `time.monotonic()` and is fine, but its
*publish* timer is not, so commands reach MecanumDrive in sparse late bursts.
MecanumDrive holds the last command until replaced, so the base keeps coasting
into the next command — `drive_check` shows each segment's motion landing in
the following row. `ros2 topic hz` is equally unreliable here, reporting 87 s
gaps and negative intervals.

The nodes in this package publish from monotonic-paced threads rather than ROS
timers, so they are immune, but the fork's nodes are not and must not be
edited. **Fix the host clock**; the usual remedy is to let the hypervisor own
the clock:

```bash
sudo systemctl disable --now systemd-timesyncd
```

Then confirm the jumps are gone before trusting any timing result:

```bash
python3 -c "
import time
p=time.clock_gettime(time.CLOCK_REALTIME); w=0.0; t0=time.monotonic()
while time.monotonic()-t0 < 3:
    c=time.clock_gettime(time.CLOCK_REALTIME); w=min(w,c-p); p=c
print('max backward step:', w)"
```

This matters well beyond teleop: TF's transform buffer, controller_manager's
update loop, and Nav2's behaviour tree all key off the same clock.

## If a run starts behaving strangely, clear /dev/shm

FastDDS keeps its shared-memory transport in `/dev/shm`. A simulation killed
with `SIGKILL` rather than `Ctrl-C` leaves those segments locked, and the next
run fails discovery with

```
RTPS_TRANSPORT_SHM Error: Failed init_port fastrtps_port7423: open_and_lock_file failed
```

Topics then appear in `ros2 topic list` but carry no data, and the Gazebo GUI
client can segfault on startup. With every ROS process stopped:

```bash
rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_*
```

Stopping the simulation with Ctrl-C avoids this; the fork's launch file has a
shutdown handler that stops the bridges and Gazebo in the right order.
