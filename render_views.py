"""用 Blender 无头渲染 GLB 的 8 方位视图（供 fig.py mv3d stage=render 调用）。

用法：
  blender --background --factory-startup --python render_views.py -- \
      --glb model.glb --out_dir OUTDIR --views front,back,left --size 1024
"""
import bpy
import sys
import math
import os
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
args = {}
i = 0
while i + 1 < len(argv):
    args[argv[i].lstrip("-")] = argv[i + 1]
    i += 2

glb = args["glb"]
out_dir = args["out_dir"]
views = args.get("views", "front").split(",")
size = int(args.get("size", "1024"))
angles = {
    "front": 0.0, "back": 180.0, "left": 90.0, "right": 270.0,
    "front_left": 45.0, "front_right": 315.0, "back_left": 135.0, "back_right": 225.0,
}
os.makedirs(out_dir, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
ext = os.path.splitext(glb)[1].lower()
if ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=glb)
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=glb)
elif ext == ".stl":
    bpy.ops.wm.stl_import(filepath=glb)
elif ext == ".ply":
    bpy.ops.wm.ply_import(filepath=glb)
else:
    raise SystemExit("unsupported model format for render: " + ext)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh imported")

mins = mathutils.Vector((1e9, 1e9, 1e9))
maxs = mathutils.Vector((-1e9, -1e9, -1e9))
for o in meshes:
    for corner in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(corner)
        mins.x = min(mins.x, w.x); mins.y = min(mins.y, w.y); mins.z = min(mins.z, w.z)
        maxs.x = max(maxs.x, w.x); maxs.y = max(maxs.y, w.y); maxs.z = max(maxs.z, w.z)
center = (mins + maxs) / 2.0
extent = maxs - mins
radius = max(extent.x, extent.y, extent.z) / 2.0
if radius <= 0:
    raise SystemExit("degenerate mesh")

# 物体挂到空物体上，绕中心旋转出不同视角
pivot = bpy.data.objects.new("Pivot", None)
bpy.context.scene.collection.objects.link(pivot)
pivot.location = center
for o in list(meshes):
    if o.parent is None:
        o.parent = pivot
        o.matrix_parent_inverse = pivot.matrix_world.inverted()

cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.scene.collection.objects.link(cam)
cam.location = (center.x, center.y - radius * 3.4, center.z + radius * 0.18)
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
cam_data.lens = 58
bpy.context.scene.camera = cam

key = bpy.data.lights.new("Key", type="AREA")
key.energy = 1200 * (radius ** 2)
key.size = radius * 2.5
key_obj = bpy.data.objects.new("Key", key)
bpy.context.scene.collection.objects.link(key_obj)
key_obj.location = (center.x + radius * 2.0, center.y - radius * 2.2, center.z + radius * 2.4)
key_obj.rotation_euler = (center - key_obj.location).to_track_quat("-Z", "Y").to_euler()

fill = bpy.data.lights.new("Fill", type="AREA")
fill.energy = 500 * (radius ** 2)
fill.size = radius * 3
fill_obj = bpy.data.objects.new("Fill", fill)
bpy.context.scene.collection.objects.link(fill_obj)
fill_obj.location = (center.x - radius * 2.2, center.y - radius * 1.6, center.z + radius)
fill_obj.rotation_euler = (center - fill_obj.location).to_track_quat("-Z", "Y").to_euler()

world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.13, 0.135, 0.15, 1.0)
bg.inputs[1].default_value = 0.7

scene = bpy.context.scene
for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"):
    try:
        scene.render.engine = engine
        break
    except Exception:
        continue
scene.render.resolution_x = size
scene.render.resolution_y = size
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
try:
    scene.view_settings.view_transform = "Standard"
except Exception:
    pass

for view in views:
    pivot.rotation_euler = (0.0, 0.0, math.radians(angles.get(view, 0.0)))
    bpy.context.view_layer.update()
    out = os.path.join(out_dir, f"clay_{view}.png")
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print(f"[blender] rendered {view} -> {out}", flush=True)
print("[blender] done", flush=True)
