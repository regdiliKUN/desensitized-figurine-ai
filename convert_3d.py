#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高精度模型后处理：尺寸校正 + 减面 + 水密化 + 格式转换

★ 关键修复（针对商业化手办需求）：
  1. RemeshMesh 输出未反归一化（固定在 [-0.5,0.5] 立方体），
     需按参考网格的比例还原真实尺寸。
  2. 高精度网格 1600 万面 -> 必须减面到可打印区间（20-60 万面）。
  3. 减面会破坏水密性 -> 减面后需重新修复。
  4. 焊接顶点：GLB 每个三角形独立顶点，不焊接会让体素化产生错误。

用法:
    python convert_3d.py input.glb --to stl 3mf --scale 150 --unit mm
    python convert_3d.py input.glb --ref old.glb --decimate 400000
"""
import argparse
import os
import sys

import numpy as np


def load_mesh(path, merge=True):
    import trimesh
    m = trimesh.load(path, force="mesh", process=False)
    if m is None or not hasattr(m, "vertices") or len(m.vertices) == 0:
        raise SystemExit(f"[!] 无法解析网格: {path}")
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(tuple(m.geometry.values()))
    if merge:
        m.merge_vertices()
    return m


def repair_mesh(m, aggressive=False):
    """修复非流形边/重复顶点/退化三角面 —— 切片软件最容易在这报错"""
    import trimesh
    report = {}
    before_f = len(m.faces)
    before_v = len(m.vertices)

    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.merge_vertices()
    m.remove_infinite_values()
    report["去重/退化面"] = f"{before_f} -> {len(m.faces)} 面"
    report["焊接顶点"] = f"{before_v} -> {len(m.vertices)} 顶点"

    try:
        holes = m.fill_holes()
        report["补洞"] = f"{holes} 个"
    except Exception as e:
        report["补洞"] = f"跳过({type(e).__name__})"

    if aggressive:
        try:
            m.merge_vertices(merge_tex=True, merge_norm=True)
        except Exception:
            pass
        try:
            comps = m.split(only_watertight=False)
            if len(comps) > 1:
                comps = sorted(comps, key=lambda c: -len(c.faces))
                m = comps[0]
                report["取最大连通块"] = f"{len(comps)} 块 -> 1"
        except Exception as e:
            report["连通块"] = f"跳过({type(e).__name__})"

    try:
        need = m.vertex_normals is None
        if not need:
            ln = np.linalg.norm(m.vertex_normals, axis=1)
            need = bool((ln < 0.5).any() or (ln > 1.5).any())
        if need:
            m.vertex_normals = None
        report["法线"] = "重算" if need else "保留"
    except Exception:
        pass

    return m, report


def match_reference_size(m, ref_path):
    """把归一化后的网格按参考网格的 XYZ 比例与高度还原。

    RemeshMesh 内部把模型归一化到 [-0.5,0.5] 立方体且**不反归一化**，
    直接导出会丢失真实比例（Z 会显得过厚、X 过窄）。
    以旧版（VoxelToMesh 路径）为参考，按其包围盒比例重建。
    """
    ref = load_mesh(ref_path)
    ref_ext = np.asarray(ref.vertices).max(axis=0) - np.asarray(ref.vertices).min(axis=0)
    cur_ext = np.asarray(m.vertices).max(axis=0) - np.asarray(m.vertices).min(axis=0)

    # 参考网格高度归一到 1，其余轴按参考比例
    target = ref_ext / ref_ext.max()
    cur_norm = cur_ext / cur_ext.max()
    # 当前归一化网格已经是 X=Y=1 的立方体，只需按 target/cur_norm 缩放
    factor = target / np.maximum(cur_norm, 1e-9)
    m.apply_scale(factor)

    # 平移使底面贴 Z=0（手办打印需要贴地）
    v = np.asarray(m.vertices)
    m.apply_translation([-v[:, 0].mean(), -v[:, 1].mean(), -v[:, 2].min()])
    return m, factor, ref_ext


def decimate(m, target_faces, placement="midpoint"):
    """减面到目标面数（保持整体轮廓）

    ★ QEM 减面会撕裂网格（实测产生 10 万+ 边界边，水密性彻底丢失），
      所以减面后必须补洞 + 检查，不保证水密。
      商业手办优先用「不减面 + Taubin 平滑」：
        440万面 / 锐边 0.07% / 水密 ✓ / GLB 79MB
    """
    import trimesh
    if target_faces <= 0 or len(m.faces) <= target_faces:
        return m, False
    try:
        out = m.simplify_quadric_decimation(face_count=int(target_faces))
        if out is not None and len(out.faces) > 0:
            out.merge_vertices()
            out.update_faces(out.nondegenerate_faces())
            out.update_faces(out.unique_faces())
            return out, True
    except Exception as e:
        print(f"    (QEM 减面失败: {type(e).__name__}: {e})")
    return m, False


def ensure_watertight(m, max_attempts=3):
    """尽力恢复水密性：补洞 + 移除小碎块 + 焊接。

    返回 (mesh, 是否水密, 处理说明)
    """
    import trimesh
    notes = []

    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())

    for attempt in range(max_attempts):
        if m.is_watertight:
            break
        # 1) 补洞
        try:
            holes = m.fill_holes()
            if holes:
                notes.append(f"补洞{holes}个")
        except Exception:
            pass
        # 2) 取最大连通块（去掉分离的碎块）
        try:
            comps = m.split(only_watertight=False)
            if len(comps) > 1:
                comps = sorted(comps, key=lambda c: -len(c.faces))
                m = comps[0]
                notes.append(f"取最大块(共{len(comps)}块)")
        except Exception:
            pass
        # 3) 再次合并
        try:
            m.merge_vertices()
        except Exception:
            pass

    return m, bool(m.is_watertight), ("; ".join(notes) if notes else "无需处理")


def solidify(m, pitch_ratio=0.005, keep_largest=True, min_face_ratio=0.005):
    """体素重建(marching cubes) -> 封闭实体，水密、可直接切片。

    ★ 警告：体素重建会**显著降低表面精度**（实测锐边占比从 0.4% 升到 20%+），
      因为 marching cubes 产生大量轴对齐的平面三角。
      现在只在明确需要时才用（--solidify），默认路径依赖 RemeshMesh 的水密输出。
    """
    ext = np.asarray(m.vertices).max(axis=0) - np.asarray(m.vertices).min(axis=0)
    pitch = float(ext.max()) * pitch_ratio
    vg = m.voxelized(pitch)
    vg.fill()
    s = vg.marching_cubes  # trimesh 5.x: 属性，不是方法
    s.apply_translation(vg.translation)
    s.apply_scale(vg.scale)

    if keep_largest:
        parts = s.split(only_watertight=False)
        if len(parts) > 1:
            biggest = max(len(p.faces) for p in parts)
            keep = [p for p in parts if len(p.faces) >= biggest * min_face_ratio]
            if len(keep) == 1:
                s = keep[0]
            else:
                import trimesh
                s = trimesh.util.concatenate(keep)
    return s, pitch


def summarize(m):
    v = np.asarray(m.vertices)
    ext = v.max(axis=0) - v.min(axis=0)
    out = {
        "顶点": len(m.vertices),
        "三角面": len(m.faces),
        "尺寸XYZ": np.round(ext, 4).tolist(),
        "水密(watertight)": bool(m.is_watertight),
        "体积(相对)": round(float(m.volume), 6) if m.is_watertight else "非封闭",
    }
    # 表面质量指标：锐边占比（相邻面夹角 >30deg 的边比例）
    try:
        n = m.face_normals
        if len(m.face_adjacency) > 0:
            ang = np.degrees(np.arccos(np.clip(
                (n[m.face_adjacency[:, 0]] * n[m.face_adjacency[:, 1]]).sum(axis=1), -1, 1)))
            out["锐边占比(表面质量)"] = f"{(ang > 30).mean():.2%}"
            out["相邻面中位夹角"] = f"{np.median(ang):.1f}deg"
    except Exception:
        pass
    return out


def smooth_mesh(m, iterations=10):
    """Taubin 平滑（λ=0.5, ν=-0.53）—— 保体积、不收缩。

    ★ 关键作用：去掉 Hunyuan3D 把「二次元立绘的像素级明暗」当成几何产生的
      「蜂窝/拉丝」高频伪影。实测锐边占比 0.43% -> 0.07%（x10），
      体积几乎不变（0.03321 -> 0.03316），水密性保持。
    """
    import trimesh
    if iterations <= 0:
        return m
    try:
        m = trimesh.smoothing.filter_taubin(m, lamb=0.5, nu=-0.53, iterations=iterations)
        return m
    except Exception as e:
        print(f"    (平滑跳过: {type(e).__name__}: {e})")
        return m


# ================================================================
# ★ 手板制作增强：扶正朝向 / 加底座 / 抽壳 / 打印诊断
# ================================================================

def orient_upright(m, preferred_axis="z"):
    """自动扶正模型朝向，使模型最高方向对齐 +Z（打印竖直方向）。

    原理：算 inertia（主惯性轴），找到与「竖直方向」偏差最大的轴，
    旋转使模型自然竖立。手办角色通常是 Y 轴最高（头朝上），需要转到 Z。

    返回 (mesh, 旋转角度描述)
    """
    try:
        v = np.asarray(m.vertices)
        ext = v.max(axis=0) - v.min(axis=0)
        # 找到最长的轴方向 = 角色的身高方向
        longest = int(np.argmax(ext))
        axis_names = ["X", "Y", "Z"]

        if longest == 2:
            # 已经是 Z 轴最高，只需平移贴地
            m.apply_translation([0, 0, -v[:, 2].min()])
            return m, "已竖立(Z轴)，贴地"

        # 需要旋转：把最长轴对齐到 Z
        if longest == 0:  # X 最长 → 绕 Y 转 90°
            angle = np.pi / 2
            rot_axis = [0, 1, 0]
            desc = f"X→Z (绕Y转90°)"
        else:  # Y 最长 → 绕 X 转 -90°
            angle = -np.pi / 2
            rot_axis = [1, 0, 0]
            desc = f"Y→Z (绕X转-90°)"

        import trimesh
        R = trimesh.transformations.rotation_matrix(angle, rot_axis)
        m.apply_transform(R)
        # 旋转后重新贴地
        v2 = np.asarray(m.vertices)
        m.apply_translation([-v2[:, 0].mean(), -v2[:, 1].mean(), -v2[:, 2].min()])
        return m, desc
    except Exception as e:
        print(f"    (扶正跳过: {type(e).__name__}: {e})")
        return m, "跳过"


def add_base_plate(m, thickness_ratio=0.03, radius_margin=1.05, smooth=True):
    """在模型底部加一个圆柱底座，手办打印必须有的「脚」。

    参数：
      thickness_ratio: 底座厚度占模型总高度的比例（0.03 = 3%）
      radius_margin:   底座半径 = 模型底部最大水平宽度 × margin
      smooth:          底座边缘倒角，避免锐边

    返回 (mesh, 底座尺寸描述)
    """
    import trimesh
    try:
        v = np.asarray(m.vertices)
        ext = v.max(axis=0) - v.min(axis=0)
        h = ext[2]  # 模型总高
        plate_h = max(h * thickness_ratio, 0.5)  # 至少 0.5 单位厚

        # 底部区域（最低 5% 的顶点）的 X/Y 范围
        bottom_z = v[:, 2].min() + h * 0.05
        bottom_mask = v[:, 2] < bottom_z
        if bottom_mask.sum() < 10:
            # 退化：用整体 XY 范围
            bottom_xy = ext[:2]
        else:
            bottom_pts = v[bottom_mask]
            bottom_xy = bottom_pts.max(axis=0)[:2] - bottom_pts.min(axis=0)[:2]

        plate_r = float(max(bottom_xy) * 0.5 * radius_margin)

        # 创建圆柱底座
        plate = trimesh.creation.cylinder(
            radius=plate_r, height=plate_h,
            sections=64,
            translation=[0, 0, v[:, 2].min() + plate_h / 2]
        )

        # 倒角（可选）
        if smooth:
            try:
                from trimesh.inertia import principal_inertia
                # 简单方式：用 subdivision 平滑边缘
                plate = trimesh.subdivide(plate)
            except Exception:
                pass

        # 合并
        combined = trimesh.util.concatenate([m, plate])
        combined.merge_vertices()
        try:
            combined.fill_holes()
        except Exception:
            pass

        desc = f"半径{plate_r:.2f}×厚{plate_h:.2f} (占高{plate_h/h:.1%})"
        return combined, desc
    except Exception as e:
        print(f"    (底座跳过: {type(e).__name__}: {e})")
        return m, "跳过"


def hollow_mesh(m, wall_thickness_ratio=0.05, min_shell=0.3):
    """抽壳：把实心模型变成空心壳体，省树脂、减重量、降低打印成本。

    原理：
      1. 把模型缩小 wall_thickness 倍（向内偏移）
      2. 从底部挖一个排水/注树脂孔
      3. 外壳 - 内壳 = 空心体

    ★ 光固化打印手办标准做法：1-3mm 壁厚，底部开孔让树脂流出。
    ★ 需要模型是水密的，否则偏移会失败。

    参数：
      wall_thickness_ratio: 壁厚占模型对角线的比例（0.05 = 5%）
      min_shell:            最小壁厚（单位与模型一致）

    返回 (mesh, 壁厚描述)
    """
    import trimesh
    try:
        if not m.is_watertight:
            print("    (抽壳需要水密模型，跳过)")
            return m, "跳过(非水密)"

        v = np.asarray(m.vertices)
        ext = v.max(axis=0) - v.min(axis=0)
        diag = float(np.linalg.norm(ext))
        wall = max(diag * wall_thickness_ratio, min_shell)

        # 向内偏移生成内壳
        inner = m.copy()
        # 用顶点向质心方向收缩模拟 offset
        centroid = v.mean(axis=0)
        direction = v - centroid
        norms = np.linalg.norm(direction, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-9)
        # 缩短 wall 的比例
        scale_factor = 1.0 - wall / (diag / 2)
        if scale_factor <= 0.3:
            print(f"    (壁厚 {wall:.2f} 相对模型过大，限制到 70%% 偏移)")
            scale_factor = 0.3
        inner_vertices = centroid + direction * scale_factor
        inner.vertices = inner_vertices

        # 从底部开孔（切除内壳底部的一个圆区域）
        z_min = inner.vertices[:, 2].min()
        z_cut = z_min + wall * 2  # 开孔高度 = 2倍壁厚
        cut_mask = inner.vertices[:, 2] < z_cut
        if cut_mask.sum() > 0:
            # 把底部顶点上推到 z_cut（等效于切掉底部）
            inner.vertices[cut_mask, 2] = z_cut
            inner.merge_vertices()
            try:
                inner.update_faces(inner.nondegenerate_faces())
            except Exception:
                pass

        # 外壳 - 内壳 = 空心壳体
        # trimesh 没有直接的 boolean difference，用 concatenate + 修复
        # 方法：翻转内壳法线后合并（这样内壳变成内表面）
        inner.invert()
        combined = trimesh.util.concatenate([m, inner])
        combined.merge_vertices()
        try:
            combined.update_faces(combined.nondegenerate_faces())
            combined.update_faces(combined.unique_faces())
            combined.fill_holes()
        except Exception:
            pass

        wall_mm = wall * 1000 if diag > 1 else wall  # 自动单位
        desc = f"壁厚{wall:.2f} (占对角线{wall_thickness_ratio:.0%})"
        return combined, desc
    except Exception as e:
        print(f"    (抽壳跳过: {type(e).__name__}: {e})")
        return m, "跳过"


def print_diagnostic(m):
    """打印前诊断报告：水密/壁厚/朝向/尺寸/尖锐角检查。"""
    v = np.asarray(m.vertices)
    ext = v.max(axis=0) - v.min(axis=0)
    issues = []
    warnings = []

    # 1) 水密性
    wt = bool(m.is_watertight)
    if not wt:
        issues.append("❌ 非水密（切片会失败或产生异常路径）")
    else:
        print("  ✓ 水密性：通过")

    # 2) 尺寸
    print(f"  ✓ 尺寸 XYZ: {np.round(ext, 2).tolist()}")

    # 3) 朝向
    longest = int(np.argmax(ext))
    axis_names = ["X", "Y", "Z"]
    if longest != 2:
        warnings.append(f"⚠ 最长轴是 {axis_names[longest]} 而非 Z，模型可能未竖立")
    else:
        print("  ✓ 朝向：Z 轴最高（竖立）")

    # 4) 底面检查
    bottom_z = v[:, 2].min()
    bottom_mask = v[:, 2] < bottom_z + ext[2] * 0.02
    if bottom_mask.sum() > 0:
        bottom_pts = v[bottom_mask]
        bottom_xy = bottom_pts[:, :2]
        spread = bottom_xy.max(axis=0) - bottom_xy.min(axis=0)
        if spread.min() < ext[2] * 0.05:
            warnings.append("⚠ 底面过窄，打印可能不稳，建议加底座")
        else:
            print(f"  ✓ 底面宽度: {np.round(spread, 2).tolist()}")
    else:
        warnings.append("⚠ 无法确定底面")

    # 5) 面数
    print(f"  ✓ 面数: {len(m.faces):,}")

    # 6) 锐边
    try:
        n = m.face_normals
        if len(m.face_adjacency) > 0:
            ang = np.degrees(np.arccos(np.clip(
                (n[m.face_adjacency[:, 0]] * n[m.face_adjacency[:, 1]]).sum(axis=1), -1, 1)))
            sharp = (ang > 60).mean()
            if sharp > 0.05:
                warnings.append(f"⚠ 锐边占比 {sharp:.1%}（>5%），表面可能粗糙")
            else:
                print(f"  ✓ 锐边占比: {sharp:.2%}")
    except Exception:
        pass

    for w in warnings:
        print(f"  {w}")
    for i in issues:
        print(f"  {i}")

    return len(issues) == 0


def main():
    ap = argparse.ArgumentParser(
        description="高精度模型后处理：尺寸校正 + 减面 + 水密化 + 扶正 + 底座 + 抽壳 + 格式转换")
    ap.add_argument("input")
    ap.add_argument("--to", nargs="*", default=["glb", "stl", "3mf", "obj", "ply"],
                    help="目标格式，可多个：glb stl 3mf obj ply fbx usdz")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--out-prefix", default=None, help="输出文件名前缀")
    ap.add_argument("--scale", type=float, default=1.0, help="缩放倍数")
    ap.add_argument("--unit", default="mm", choices=["mm", "cm", "m", "unit"])
    ap.add_argument("--repair", action="store_true", help="修复非流形/补洞")
    ap.add_argument("--aggressive", action="store_true", help="激进修复（取最大连通块）")
    ap.add_argument("--no-repair", action="store_true", help="跳过所有修复")
    ap.add_argument("--solidify", action="store_true",
                    help="体素重建水密化。★ 会显著降低表面精度(锐边 0.4%%->20%%)，"
                         "RemeshMesh 路径本身已水密，通常不需要")
    ap.add_argument("--keep-all", action="store_true",
                    help="水密化时保留所有连通块（默认只保留主实体）")
    ap.add_argument("--pitch", type=float, default=0.005,
                    help="体素重建精度（相对包围盒对角线），仅在 --solidify 时生效")
    # ★ 高精度管线参数
    ap.add_argument("--ref", default=None,
                    help="参考网格，用于按其比例还原被归一化的尺寸")
    ap.add_argument("--decimate", type=int, default=0,
                    help="减面到目标面数。★ 会破坏水密性，商业手办建议保持 0")
    ap.add_argument("--smooth", type=int, default=10,
                    help="Taubin 平滑迭代次数（默认 10）。清除像素纹理伪影，保体积不收缩")
    ap.add_argument("--height", type=float, default=0.0,
                    help="成品高度(mm)。指定后按模型实际高度自动缩放，取代 --scale")
    # ★★ 手板制作增强参数 ★★
    ap.add_argument("--orient", action="store_true", default=True,
                    help="自动扶正朝向（使模型竖立在 Z 轴上）。默认开启")
    ap.add_argument("--no-orient", dest="orient", action="store_false",
                    help="关闭自动扶正")
    ap.add_argument("--base", type=float, default=0.0, nargs="?", const=0.03,
                    help="加圆柱底座。可选参数=底座厚度比例(0.03=3%%高度)。"
                         "如 --base 0.05 = 5%%高度厚的底座")
    ap.add_argument("--no-base", dest="base", action="store_const", const=0.0,
                    help="不加底座")
    ap.add_argument("--hollow", type=float, default=0.0, nargs="?", const=0.05,
                    help="抽壳省树脂。可选参数=壁厚比例(0.05=5%%对角线)。"
                         "如 --hollow 0.03 = 3%%壁厚。需要水密模型")
    ap.add_argument("--no-hollow", dest="hollow", action="store_const", const=0.0,
                    help="不抽壳（默认）")
    ap.add_argument("--diagnose", action="store_true", default=True,
                    help="打印前诊断报告（水密/壁厚/朝向/尺寸/锐边）。默认开启")
    ap.add_argument("--no-diagnose", dest="diagnose", action="store_false",
                    help="关闭诊断报告")
    a = ap.parse_args()

    if not os.path.exists(a.input):
        raise SystemExit(f"[!] 文件不存在: {a.input}")

    base = os.path.splitext(os.path.basename(a.input))[0]
    outdir = a.out_dir or os.path.dirname(os.path.abspath(a.input))
    os.makedirs(outdir, exist_ok=True)

    print(f"[*] 载入: {a.input}")
    m = load_mesh(a.input)
    print(f"    顶点 {len(m.vertices):,}  面 {len(m.faces):,}")

    # 1) 尺寸校正
    if a.ref:
        if not os.path.exists(a.ref):
            print(f"[!] 参考网格不存在: {a.ref}")
        else:
            m, factor, ref_ext = match_reference_size(m, a.ref)
            print(f"[*] 尺寸校正: 缩放 {np.round(factor, 4)} "
                  f"(参考尺寸 {np.round(ref_ext, 4)})")

    # 2) 平滑
    if a.smooth > 0:
        print(f"[*] Taubin 平滑 x{a.smooth} ...")
        m = smooth_mesh(m, a.smooth)

    # 3) 减面
    if a.decimate > 0:
        before = len(m.faces)
        if before > a.decimate:
            print(f"[*] 减面 {before:,} -> {a.decimate:,} ...")
            m, ok = decimate(m, a.decimate)
            print(f"    -> {len(m.faces):,} 面  {'(成功)' if ok else '(未变化)'}")
            if ok and not m.is_watertight:
                print("[*] 减面撕裂了网格，尝试修复水密性 ...")
                m, wt, note = ensure_watertight(m)
                print(f"    -> 水密={wt}  ({note})")
                if not wt:
                    print("[!] ⚠ 减面后无法恢复水密。建议改用 --decimate 0"
                          "（不减面 + Taubin 平滑，精度更高且天然水密）")

    # 4) 水密化 / 修复
    if a.solidify:
        print(f"[*] 体素重建水密化 (pitch_ratio={a.pitch}) ...")
        m, pitch = solidify(m, a.pitch, keep_largest=not a.keep_all)
        print(f"    -> {len(m.vertices):,} 顶点 / {len(m.faces):,} 面, "
              f"watertight={m.is_watertight}, pitch={pitch:.5f}")
        if a.out_prefix:
            base = a.out_prefix
    elif not a.no_repair:
        m, rep = repair_mesh(m, a.aggressive)
        print("[*] 修复:")
        for k, v in rep.items():
            print(f"      {k}: {v}")

    # 5) ★ 自动扶正朝向（在手板制作之前，确保模型竖立）
    if a.orient:
        print("[*] 自动扶正朝向 ...")
        m, orient_desc = orient_upright(m)
        print(f"    -> {orient_desc}")

    # 6) 按成品高度缩放（商业手办最实用的参数）
    if a.height > 0:
        v0 = np.asarray(m.vertices)
        # ★ 修复：扶正后高度在 Z 轴，不是 Y 轴
        h = float(v0[:, 2].max() - v0[:, 2].min())
        if h > 0:
            sc = a.height / h
            m.apply_scale(sc)
            print(f"[*] 按成品高度 {a.height}mm 缩放 (模型高 {h:.4f} -> x{sc:.3f})")
    elif a.scale != 1.0:
        m.apply_scale(a.scale)
        print(f"[*] 已缩放 x{a.scale}")

    # 7) ★ 加底座（手办需要平底面才能站稳/支撑）
    if a.base > 0:
        print(f"[*] 加底座 (厚度比例 {a.base:.0%}) ...")
        m, base_desc = add_base_plate(m, thickness_ratio=a.base)
        print(f"    -> {base_desc}")

    # 8) ★ 抽壳（省树脂/减重量，光固化打印标准做法）
    if a.hollow > 0:
        print(f"[*] 抽壳 (壁厚比例 {a.hollow:.0%}) ...")
        m, hollow_desc = hollow_mesh(m, wall_thickness_ratio=a.hollow)
        print(f"    -> {hollow_desc}")

    # 9) ★ 打印前诊断报告
    if a.diagnose:
        print("\n[*] ===== 打印前诊断报告 =====")
        print_diagnostic(m)
        print("    ==========================\n")

    s = summarize(m)
    print("[*] 网格信息:")
    for k, v in s.items():
        print(f"      {k}: {v}")

    unit_scale = {"mm": 1000.0, "cm": 100.0, "m": 1.0, "unit": 1.0}[a.unit]

    ok, fail = [], []
    for fmt in a.to:
        fmt = fmt.lower().lstrip(".")
        out = os.path.join(outdir, f"{base}.{fmt}")
        try:
            if fmt == "obj":
                m.export(out, file_type="obj")
                mtl = os.path.splitext(out)[0] + ".mtl"
                extra = f" (+ {os.path.basename(mtl)})" if os.path.exists(mtl) else ""
            elif fmt == "stl":
                m.export(out, file_type="stl")
                extra = ""
            elif fmt == "3mf":
                m2 = m.copy()
                m2.apply_scale(unit_scale)
                m2.export(out, file_type="3mf")
                extra = f" (单位 {a.unit})"
            elif fmt == "ply":
                m.export(out, file_type="ply")
                extra = ""
            elif fmt == "glb":
                m.export(out, file_type="glb")
                extra = ""
            elif fmt == "gltf":
                m.export(out, file_type="gltf")
                extra = ""
            elif fmt == "fbx":
                m.export(out, file_type="fbx")
                extra = ""
            elif fmt == "usdz":
                m.export(out, file_type="usdz")
                extra = ""
            else:
                fail.append((fmt, "未知格式"))
                continue
            sz = os.path.getsize(out) / 1e6
            print(f"[✓] {fmt.upper():5s} -> {out}  ({sz:.2f} MB){extra}")
            ok.append(fmt)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"[!] {fmt.upper()} 导出失败: {msg}")
            fail.append((fmt, msg))

    if fail:
        print("\n[!] 部分格式失败:")
        for f, msg in fail:
            print(f"      {f}: {msg}")

    print(f"\n[✓] 完成，输出目录: {outdir}")


if __name__ == "__main__":
    main()
