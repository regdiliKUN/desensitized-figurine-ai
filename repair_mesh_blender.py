# -*- coding: utf-8 -*-
"""拓扑级网格修复（不体素化、不改形状），供 convert_3d.py 在导出前调用。

为什么需要它：Hunyuan3D / Meshy 输出的 GLB 含大量重复顶点、退化面、
非流形边与开口边界，trimesh 的 fill_holes 对非流形拓扑无效；
而体素重建水密化会把表面碾粗。Blender 的 bmesh 能在**保持顶点位置**的
前提下做去重、退化清理、补洞与法线重算。

用法：
  blender --background --factory-startup --python repair_mesh_blender.py -- \
      <输入 glb/stl/obj> <输出.stl> [--voxel-mm 0.35] [--json stats.json]

--voxel-mm 缺省为 0：纯拓扑修复；>0 时才做体素重建（会损失细节，需显式指定）。
"""
import bpy
import bmesh
import json
import mathutils
import os
import sys

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
USAGE = ("用法: blender --background --factory-startup --python repair_mesh_blender.py -- "
         "<输入 glb/stl/obj> <输出.stl> [--voxel-mm 0.25] [--json stats.json]")
if len(argv) < 2:
    raise SystemExit(USAGE)
src, dst = argv[0], argv[1]
if not os.path.isfile(src):
    raise SystemExit(f"输入文件不存在: {src}")
voxel_mm = 0.0
stats_path = None
i = 2
while i < len(argv):
    key = argv[i]
    if key in ("--voxel-mm", "--json"):
        if i + 1 >= len(argv):
            raise SystemExit(f"参数 {key} 缺少取值。{USAGE}")
        value = argv[i + 1]
        if key == "--voxel-mm":
            try:
                voxel_mm = float(value)
            except ValueError:
                raise SystemExit(f"--voxel-mm 需要数字，收到: {value}")
            if not 0.0 <= voxel_mm <= 5.0:
                raise SystemExit(f"--voxel-mm 应在 [0, 5] mm，收到: {voxel_mm}")
        else:
            stats_path = value
        i += 2
    else:
        raise SystemExit(f"未知参数: {key}。{USAGE}")

bpy.ops.wm.read_factory_settings(use_empty=True)
ext = os.path.splitext(src)[1].lower()
if ext == ".stl":
    bpy.ops.wm.stl_import(filepath=src)
elif ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=src)
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=src)
else:
    raise SystemExit("unsupported: " + ext)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh imported")
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active

# 用整体包围盒尺度推导容差，避免把细节顶点误合并
corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
diag = (mathutils.Vector((max(c.x for c in corners), max(c.y for c in corners),
                          max(c.z for c in corners))) -
        mathutils.Vector((min(c.x for c in corners), min(c.y for c in corners),
                          min(c.z for c in corners)))).length
weld = max(diag * 1e-6, 1e-7)
degenerate = max(diag * 1e-8, 1e-9)


def measure(bm):
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    nonmanifold = sum(1 for e in bm.edges if not e.is_manifold)
    return {"vertices": len(bm.verts), "faces": len(bm.faces),
            "boundary_edges": boundary, "nonmanifold_edges": nonmanifold,
            "watertight": boundary == 0 and nonmanifold == 0}


bm = bmesh.new()
bm.from_mesh(obj.data)
before = measure(bm)

bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld)
bmesh.ops.dissolve_degenerate(bm, dist=degenerate, edges=list(bm.edges))
loose_verts = [v for v in bm.verts if not v.link_faces]
if loose_verts:
    bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
loose_edges = [e for e in bm.edges if not e.link_faces]
if loose_edges:
    bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
after_topology = measure(bm)

# ★ 拓扑修复（去重/补洞/法线）后已经水密时，不再做体素重建：
#   体素重建会把整个表面按 voxel_mm 重新采样，细发丝/衣褶/五官都会被抹平。
#   只有拓扑手段修不好（仍有边界边或非流形边）时才退回体素重建。
voxel_skipped = bool(voxel_mm > 0 and after_topology["watertight"])
if voxel_mm > 0 and not voxel_skipped:
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.remesh_voxel_size = float(voxel_mm)
    obj.data.use_remesh_preserve_volume = True
    bpy.ops.object.voxel_remesh()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

bm.normal_update()
bm.to_mesh(obj.data)
bm.free()
obj.data.validate(verbose=False)
obj.data.update()

check = bmesh.new()
check.from_mesh(obj.data)
final = measure(check)
check.free()

# STL 导入导出都用 Y-forward / Z-up、单位缩放 1，保持 mm 坐标不变
bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=False,
                      global_scale=1.0, use_scene_unit=False,
                      ascii_format=False, forward_axis="Y", up_axis="Z",
                      apply_modifiers=True)
if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
    raise SystemExit(f"导出失败：输出文件为空或不存在: {dst}")

stats = {"input": os.path.abspath(src), "output": os.path.abspath(dst),
         "output_bytes": os.path.getsize(dst),
         "bbox_diagonal": diag, "weld_tolerance": weld,
         "degenerate_tolerance": degenerate, "voxel_mm": voxel_mm,
         "voxel_skipped_topology_watertight": voxel_skipped,
         "before": before, "after_topology": after_topology, "final": final}
print("[blender-repair] " + json.dumps(stats, ensure_ascii=False), flush=True)
if stats_path:
    os.makedirs(os.path.dirname(os.path.abspath(stats_path)), exist_ok=True)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
