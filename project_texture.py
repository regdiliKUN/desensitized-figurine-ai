"""把一张图片作为正面贴图投影到任意 3D 模型上（用于“模型文件外观修改”）。

用法：
  python project_texture.py 模型.glb 贴图.png 输出.glb [--flip-u] [--flip-v]

自动判断竖直轴（包围盒最长轴），用 (水平轴, 竖直轴) 做平面投影 UV。
模型已有的 UV/贴图会被替换（贴在正面，背面/侧面为拉伸投影）。
"""
import argparse
import numpy as np
import trimesh
from PIL import Image, ImageOps


def project(model_path, image_path, output_path, up_axis="auto", flip_u=False, flip_v=False):
    mesh = trimesh.load(model_path, force="mesh", process=True)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError("模型没有可用三角网格")
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    if not np.isfinite(vertices).all():
        raise ValueError("模型包含无效顶点")

    extents = mesh.extents
    if up_axis == "auto":
        up = int(np.argmax(extents))
    else:
        up = {"x": 0, "y": 1, "z": 2}[up_axis.lower()]
    others = [i for i in (0, 1, 2) if i != up]
    # u 轴取剩余两轴中较宽的（人物正面通常沿水平方向展开）
    u = others[0] if extents[others[0]] >= extents[others[1]] else others[1]
    v = up

    u_vals = vertices[:, u]
    v_vals = vertices[:, v]
    if np.ptp(u_vals) < 1e-9 or np.ptp(v_vals) < 1e-9:
        raise ValueError("模型在投影平面上的尺寸为零，无法投影")

    nu = (u_vals - u_vals.min()) / np.ptp(u_vals)
    nv = (v_vals - v_vals.min()) / np.ptp(v_vals)
    if flip_u:
        nu = 1.0 - nu
    if flip_v:
        nv = 1.0 - nv
    uv = np.column_stack((nu, nv))

    with Image.open(image_path) as img:
        texture = ImageOps.exif_transpose(img).convert("RGBA")
        texture.load()

    mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uv, image=texture)
    data = mesh.export(file_type="glb")
    with open(output_path, "wb") as f:
        f.write(data)
    print(f"输出: {output_path}")
    print(f"顶点: {len(mesh.vertices)} 三角面: {len(mesh.faces)} 竖直轴: {'xyz'[up]} 水平轴: {'xyz'[u]}")
    return output_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("image")
    ap.add_argument("output")
    ap.add_argument("--up-axis", default="auto", choices=["auto", "x", "y", "z"])
    ap.add_argument("--flip-u", action="store_true")
    ap.add_argument("--flip-v", action="store_true")
    args = ap.parse_args()
    project(args.model, args.image, args.output, args.up_axis, args.flip_u, args.flip_v)
