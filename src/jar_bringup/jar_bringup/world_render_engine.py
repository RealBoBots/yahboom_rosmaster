#!/usr/bin/env python3
"""
Retarget the Gazebo Fortress server render engine of a world file.

The worlds shipped by the read-only yahboom_rosmaster fork hardcode

    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>

and the fork's launch file builds the ``ign gazebo`` command line itself, so
neither ``--render-engine`` nor ``--render-engine-server`` can reach the
server. Rewriting that one element into a generated copy of the world is the
only way to pick an engine without touching the fork.

Why it matters on WSLg: Ogre-Next 2.2 (the ``ogre2`` engine) generates
hardware mipmaps through ``GL3PlusTextureGpu::copyTo``, which the Mesa D3D12
driver does not implement, so the server aborts with
``Ogre::UnimplementedException`` while creating the scene. OGRE 1.x (the
``ogre`` engine) never takes that path and runs GPU-accelerated.

The same generated copy is also where the optional physics step override
lands, for the same reason: the fork owns the world files and must not change.

Only these elements are rewritten; ``model://`` URIs keep resolving through
IGN_GAZEBO_RESOURCE_PATH, which the fork's launch already populates, so the
generated copy is safe to place outside the package.
"""

import os
import tempfile
import xml.etree.ElementTree as ElementTree

#: Engine the fork's worlds ship with. Selecting it means "leave the world alone".
DEFAULT_ENGINE = "ogre2"

#: Engines with an ign-rendering-6 plugin on a stock Fortress install.
SUPPORTED_ENGINES = ("ogre", "ogre2")

_SENSORS_SYSTEM_SUFFIX = "systems::Sensors"


def resolve_world_path(world, worlds_dir):
    """
    Resolve a world argument the same way the fork's launch file does.

    Accepts an absolute path, a bare file name inside ``worlds_dir``, or a
    name with the ``.world`` suffix left off. Returns the argument unchanged
    when nothing matches, so Gazebo reports the missing world itself.
    """
    if os.path.isabs(world) and os.path.exists(world):
        return world
    candidate = os.path.join(worlds_dir, world)
    if os.path.exists(candidate):
        return candidate
    candidate_ext = os.path.join(worlds_dir, f"{world}.world")
    if os.path.exists(candidate_ext):
        return candidate_ext
    return world


def _sensors_plugins(root):
    """Yield every Sensors system plugin element in the document."""
    for plugin in root.iter("plugin"):
        if plugin.get("name", "").endswith(_SENSORS_SYSTEM_SUFFIX):
            yield plugin


def _set_physics_step(root, step):
    """Rewrite every ``<physics>`` step size, and keep the update rate in sync.

    ``real_time_update_rate`` is the iterations-per-second cap, so a world
    that pins it to 1000 alongside a 1 ms step (maze_1_6x5 does) would keep
    running 1000 iterations a second and ignore the larger step. Both have to
    move together for the step size to mean anything.
    """
    patched = 0
    for physics in root.iter("physics"):
        element = physics.find("max_step_size")
        if element is None:
            element = ElementTree.SubElement(physics, "max_step_size")
        element.text = f"{step:g}"

        rate = physics.find("real_time_update_rate")
        if rate is not None:
            rate.text = f"{1.0 / step:g}"
        patched += 1
    return patched


def retarget_world(world_path, engine, output_dir=None, physics_step=None):
    """
    Write a copy of ``world_path`` with the requested overrides applied.

    ``engine`` selects the Sensors system's render engine. ``physics_step``,
    when given, replaces the physics step size in seconds.

    Returns ``(path, patched_count)``. ``patched_count`` counts the rewritten
    Sensors systems; 0 means the world renders no sensors server-side and the
    engine choice only affects the GUI client.
    """
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(
            f"Unsupported render engine '{engine}'; expected one of "
            f"{', '.join(SUPPORTED_ENGINES)}")
    if physics_step is not None and not 0.0 < physics_step <= 0.1:
        raise ValueError(
            f"physics_step must be within (0, 0.1] seconds, got {physics_step}")

    tree = ElementTree.parse(world_path)
    root = tree.getroot()

    patched = 0
    for plugin in _sensors_plugins(root):
        element = plugin.find("render_engine")
        if element is None:
            element = ElementTree.SubElement(plugin, "render_engine")
        element.text = engine
        patched += 1

    if physics_step is not None:
        _set_physics_step(root, physics_step)

    if output_dir is None:
        output_dir = os.path.join(tempfile.gettempdir(), "jar_bringup_worlds")
    os.makedirs(output_dir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(world_path))[0]
    # A deterministic name keeps the generated world inspectable across runs
    # and lets a repeated launch overwrite its own file instead of piling up.
    # The step size is part of the name so two differently paced runs of the
    # same world do not overwrite each other.
    suffix = engine if physics_step is None else f"{engine}.{physics_step:g}s"
    output_path = os.path.join(output_dir, f"{stem}.{suffix}.world")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path, patched
