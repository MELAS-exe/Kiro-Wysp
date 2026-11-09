"""Build the "Pumpkin Patch" demo scene reproducibly.

    blender -b --python apps/blender-tutor/demo/build_scene.py -- --out apps/blender-tutor/demo/pumpkin.blend

The pumpkin has a Subdivision Surface and a Solidify modifier; the candle has none, so that adding
a Bevel to it is the natural first exercise.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy


def parse_out() -> Path:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if "--out" in argv:
        return Path(argv[argv.index("--out") + 1])
    return Path(__file__).with_name("pumpkin.blend")


def material(name: str, color: tuple[float, float, float, float]):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
    return mat


def move_to(obj, collection) -> None:
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    collection.objects.link(obj)


def active():
    return bpy.context.view_layer.objects.active


def main() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "Pumpkin Patch"
    patch = bpy.data.collections.new("Patch")
    props = bpy.data.collections.new("Props")
    env = bpy.data.collections.new("Environment")
    for c in (patch, props, env):
        scene.collection.children.link(c)

    orange = material("PumpkinOrange", (0.9, 0.35, 0.02, 1.0))
    green = material("StemGreen", (0.15, 0.4, 0.1, 1.0))
    cream = material("CandleCream", (0.95, 0.9, 0.75, 1.0))
    grass = material("GroundDark", (0.05, 0.08, 0.04, 1.0))

    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0, location=(0, 0, 0.85))
    pumpkin = active()
    pumpkin.name = "Pumpkin"
    pumpkin.scale = (1.0, 1.0, 0.85)
    bpy.ops.object.shade_smooth()
    pumpkin.data.materials.append(orange)
    sub = pumpkin.modifiers.new("Subdivision", "SUBSURF")
    sub.levels = 2
    sub.render_levels = 2
    sol = pumpkin.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = 0.05
    move_to(pumpkin, patch)

    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.12, depth=0.35, location=(0, 0, 1.75))
    stem = active()
    stem.name = "Stem"
    stem.data.materials.append(green)
    move_to(stem, patch)

    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.14, depth=0.5, location=(2.0, 0.4, 0.25))
    candle = active()
    candle.name = "Candle"
    candle.data.materials.append(cream)
    move_to(candle, props)

    bpy.ops.mesh.primitive_plane_add(size=10, location=(0, 0, 0))
    ground = active()
    ground.name = "Ground"
    ground.data.materials.append(grass)
    move_to(ground, env)

    light_data = bpy.data.lights.new("Lamp", "POINT")
    light_data.energy = 900
    lamp = bpy.data.objects.new("Lamp", light_data)
    lamp.location = (3, -3, 5)
    env.objects.link(lamp)

    cam_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", cam_data)
    camera.location = (6, -6, 4)
    camera.rotation_euler = (math.radians(63), 0, math.radians(46))
    env.objects.link(camera)
    scene.camera = camera

    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = pumpkin
    pumpkin.select_set(True)

    out = parse_out()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    print(f"WYSP-SCENE-SAVED {out}")


if __name__ == "__main__":
    main()
