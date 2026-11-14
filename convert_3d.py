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
import glob
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import numpy as np

# 参考图驱动的几何保真（只服务 STL 链路；与图像生成链路无关）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import mesh_fidelity as _fidelity
except Exception as _exc:  # noqa: BLE001
    _fidelity = None
    _FIDELITY_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
else:
    _FIDELITY_IMPORT_ERROR = None

# 交付物文件级复验（R27）：与独立复验脚本共用同一套几何判据，避免主链路
# 与 CLI 工具各写一份判据而口径漂移。模块级只依赖标准库，导入失败可降级。
try:
    import verify_deliverable as _file_verify
except Exception as _exc:  # noqa: BLE001
    _file_verify = None
    _FILE_VERIFY_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
else:
    _FILE_VERIFY_IMPORT_ERROR = None


def _resolve_ref_image(input_path, explicit):
    """优先用显式参考图，其次找与模型同名的 3D 输入图（fig.py 会落盘）。"""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    folder, stem = os.path.split(os.path.abspath(input_path))
    base = os.path.splitext(stem)[0]
    for name in (base + "_3d_input.png", base + "_reference.png",
                 base + ".png", base + ".jpg"):
        cand = os.path.join(folder, name)
        if os.path.isfile(cand):
            return cand
    return None


def _find_blender(explicit=None):
    """使用项目已有的 Blender；不引入新的网格处理依赖。

    ★ 显式指定的路径若不存在就直接失败，不再静默回退到其他安装 —— 否则
      用户以为用的是指定版本，实际跑的是另一个，排障时会误判。
    """
    if explicit and not os.path.isfile(explicit):
        return None
    candidates = [explicit, os.environ.get("BLENDER_EXE")]
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meshy_config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            candidates.append(json.load(f).get("blender_exe"))
    except Exception:
        pass
    candidates.extend(glob.glob(r"C:\Program Files\Blender Foundation\*\blender.exe"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _finite_float(value):
    """R39：把报告里的数值指标安全地转成有限浮点数。

    ``None`` / 非数值 / NaN / Inf / 布尔一律返回 None，由 ``build_verdict``
    判为该项 FAIL 并写入 ``invalid_metrics``；绝不让 ``float()`` 抛栈中断
    导出，也不让 NaN 混进阈值比较后给出误导性结论。
    """
    if value is None or isinstance(value, (bool, str, bytes)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if bool(np.isfinite(number)) else None


def _strict_true(value):
    """R39：只接受真正的布尔真或数值 1，杜绝 ``"false"`` / ``2`` 这类 truthy 误判。"""
    if value is True:
        return True
    if isinstance(value, (bool, str, bytes)) or value is None:
        return False
    number = _finite_float(value)
    return number is not None and number == 1.0


def _strict_zero(value):
    """R39：只接受数值 0；``False == 0`` / ``"0"`` 不能算「无边界边」。"""
    if value is None or isinstance(value, (bool, str, bytes)):
        return False
    number = _finite_float(value)
    return number is not None and number == 0.0


# R42：宽高比自检容差是生成侧与独立复验侧共享的契约，不能两处各写一个魔法数。
# verify_deliverable.ASPECT_SELF_CHECK_TOL_PCT 必须与此值相等（回归用例锁定）。
ASPECT_SELF_CHECK_TOL_PCT = 1.0


def build_verdict(report, min_iou=0.55, strict_watertight=False):
    """把散落的指标收敛成一份可执行的验收结论。

    final_mesh 是「含底座 + 水密化之后」真正要导出的网格，必须用它判定，
    不能用加底座前的 pre_base_mesh 指标冒充成品。

    R39：生成侧与独立复验侧共用同一套严格契约 —— 数值指标只允许有限
    浮点数，布尔/计数判据只接受真正的布尔真或数值 0/1。旧实现直接
    ``float(...)`` / ``<=``，在 IoU 或宽高比评估被跳过（值为 None）时抛
    TypeError 中断导出；``bool("false")`` 会把明确的非水密报告误判为
    水密通过，``False == 0`` 会把布尔假值误判成「无边界边」。畸形输入
    一律判该项 FAIL 并写入 ``invalid_metrics``，不再抛栈、不再静默放行。

    R42：宽高比容差提为模块常量 ``ASPECT_SELF_CHECK_TOL_PCT``，由独立复验侧
    同值常量与回归锁定，使两侧能按同一阈值重算数值判据。注意 IoU 取自
    ``final_mesh``（成品网格），宽高比自检取自**顶层** ``aspect_error_pct``
    （``aspect_correction`` 变换是否执行成功；加底座后包围盒必然变化，不能用
    ``final_mesh.aspect_error_pct`` 代替），两者评价对象不同是刻意设计。
    """
    if not isinstance(report, dict):
        report = {}
    final = report.get("final_mesh")
    final = final if isinstance(final, dict) else {}
    iou = _finite_float(final.get("silhouette_iou",
                                 report.get("silhouette_iou")))
    aspect = _finite_float(report.get("aspect_error_pct"))
    threshold = _finite_float(min_iou)
    invalid = []
    if iou is None:
        invalid.append("silhouette_iou 缺失或非有限数值")
    if aspect is None:
        invalid.append("aspect_error_pct 缺失或非有限数值")
    if threshold is None:
        invalid.append("min_iou 缺失或非有限数值")
    checks = {
        "silhouette_iou": bool(iou is not None and threshold is not None
                               and iou >= threshold),
        "watertight": _strict_true(final.get("watertight_indexed", False)),
        "no_boundary_edges": _strict_zero(final.get("boundary_edges")),
        "no_nonmanifold_edges": _strict_zero(final.get("nonmanifold_edges")),
        "aspect_self_check": bool(
            aspect is not None and aspect <= ASPECT_SELF_CHECK_TOL_PCT),
    }
    required = list(checks) if strict_watertight else [
        "silhouette_iou", "aspect_self_check"]
    passed = all(checks[k] for k in required)
    out = {"pass": passed, "checks": checks,
           "strict_watertight": strict_watertight,
           "required_checks": required,
           "evaluated_on": "final_mesh" if final else "pre_base_mesh"}
    if invalid:
        out["invalid_metrics"] = invalid
    return out


def verify_exported_stl(stl_path, mesh):
    """导出后回读磁盘 STL，做文件级闭环复验（R27）。

    ``build_verdict`` 只评价**内存网格**；导出器若改写法线、写盘被截断、
    或落地文件与报告不是同一个东西，旧链路仍会给出 verdict=PASS。
    这里复用 ``verify_deliverable.geometry_checks`` 的同一套判据
    （焊接闭合 / 绕向 / 正体积 / 闭合实体），再叠加与内存网格的三项比对。

    返回结构：``pass`` 为 True/False/None。None **只**在 ``verify_deliverable``
    模块本身都无法导入时出现（整条复验能力不存在，调用方按历史语义跳过）。

    R49：R46 把 ``geometry_checks`` 的缺依赖异常从 ``ImportError`` 改成
    ``MissingDependencyError``（继承 RuntimeError）。旧 ``except ImportError``
    分支因此变成死代码，缺 trimesh/numpy 被 ``except Exception`` 吞成一句
    「几何复验失败」——既没有机器可读的分类，也把环境问题伪装成成品缺陷。
    现在显式识别两类缺依赖异常，结构化 fail-closed（``pass=False``、
    ``dependency_missing=True``、``skipped=False``）：既不降级为 PASS，
    也不冒充「成品几何不合格」，并给出可执行的诊断。
    """
    fv = {
        "stl": os.path.abspath(stl_path),
        "checks": {}, "metrics": {},
        "verified_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if _file_verify is None:
        fv.update({"pass": None, "skipped": True,
                   "reason": f"verify_deliverable 不可用: {_FILE_VERIFY_IMPORT_ERROR}"})
        return fv
    # 兼容旧版 verify_deliverable（当时缺依赖仍抛 ImportError）。
    dep_error = getattr(_file_verify, "MissingDependencyError", ImportError)
    try:
        checks, metrics = _file_verify.geometry_checks(stl_path)
    except (ImportError, dep_error) as exc:
        fv.update({
            "pass": False, "skipped": False, "dependency_missing": True,
            "error": ("环境缺依赖，文件级复验无法执行（不是成品几何问题）: "
                      f"{type(exc).__name__}: {exc}"),
        })
        return fv
    except Exception as exc:  # noqa: BLE001 - 损坏文件必须变成可读的失败结论
        fv.update({"pass": False, "error": f"{type(exc).__name__}: {exc}"})
        return fv

    got_ext = np.asarray(metrics["extents_xyz"], dtype=float)
    want_ext = np.asarray(mesh.extents, dtype=float)
    checks.update({
        "faces_match_memory": int(metrics["faces"]) == int(len(mesh.faces)),
        # 内存网格是 merge=True 的焊接拓扑，与 STL 焊接后应逐点一致。
        "vertices_match_memory":
            int(metrics["vertices_welded"]) == int(len(mesh.vertices)),
        "extents_match_memory": bool(
            got_ext.shape == (3,) and
            float(np.max(np.abs(got_ext - want_ext))) <= 0.01),
    })
    fv["checks"] = dict(checks)
    fv["metrics"] = _file_verify.json_safe(metrics)
    fv["warnings"] = _file_verify.json_safe(list(metrics.get("warnings") or []))
    fv["pass"] = bool(all(checks.values()) and len(checks) >= 7)
    # 报告/清单会直接 json.dump 这个结构，必须保证没有 NaN/Inf 字面量。
    return _file_verify.json_safe(fv)


def export_mesh_atomic(mesh, out_path, fmt, verify_mesh=None):
    """R57：把「可能产生半成品」的导出限制在目标同目录的 staging 内。

    ``mesh.export(out_path)`` 直接写最终路径时，磁盘写满、进程被中断或
    导出器写到一半抛异常，都会把既有成品截成不可恢复的半成品（实测：
    先写 ``PARTIAL-STL`` 再抛 RuntimeError，原文件即被覆盖）。这里先导出
    到同目录的临时子目录，只有导出成功（且 STL 完成回读复验）后才用
    ``os.replace`` 一次性换入；任何异常都只清理 staging，绝不触碰
    ``out_path`` 上已有的成品。

    staging 与交付目录同盘，``os.replace`` 是原子操作，不会出现「半个
    文件」的可见状态。OBJ 的 .mtl、glTF 的 .bin / 纹理等伴生文件按原名
    一起换入，主文件最后替换，保证主文件出现时伴生文件已就位。非 STL
    格式不做文件级复验（与 R27 既有语义一致）。

    返回 ``file_verification``（仅 STL 且 ``verify_mesh`` 不为 None 时
    非 None）；其中的 ``stl`` 字段已改写为最终交付路径，报告/清单契约不变。
    """
    out_abs = os.path.abspath(out_path)
    directory, filename = os.path.split(out_abs)
    os.makedirs(directory, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".export_", dir=directory) as staging:
        staged = os.path.join(staging, filename)
        mesh.export(staged, file_type=fmt)
        fv = None
        if fmt == "stl" and verify_mesh is not None:
            fv = verify_exported_stl(staged, verify_mesh)
            # 复验发生在 staging 文件上，但报告/清单必须记录最终交付路径。
            if isinstance(fv, dict):
                fv["stl"] = out_abs
        companions = sorted(n for n in os.listdir(staging) if n != filename)
        for name in companions:
            os.replace(os.path.join(staging, name), os.path.join(directory, name))
        os.replace(staged, out_abs)
        return fv


def apply_file_verification(verdict, fv):
    """把文件级复验叠加到验收结论，同时保持 build_verdict 的 5 项 checks 契约。

    checks 只描述内存网格，刻意不混入文件级判据（R18 的 required_checks、
    verify_deliverable 的 verdict_consistent 都依赖这个结构）；文件级结果用
    ``file_verification_pass`` 单列，并与原结论一起决定最终 ``pass``。
    """
    if not verdict or not fv or fv.get("skipped") or fv.get("pass") is None:
        return verdict
    out = dict(verdict)
    passed = bool(fv.get("pass"))
    out["file_verification_pass"] = passed
    out["pass"] = bool(out.get("pass")) and passed
    if not passed:
        failed = [k for k, v in (fv.get("checks") or {}).items() if not v]
        out["file_verification_failure"] = fv.get("error") or ", ".join(failed)
    return out


def drop_floating_parts(mesh):
    """R29：剔除与主实体不相连的悬空闭合壳，只保留面数最多的连通块。

    Blender 体素重建会在发丝断环、薄壁附近留下互不相连的微小闭合体；
    ``is_watertight`` 对「多个闭合体」同样返回 True，所以 R28 之前它们
    从未进入验收口径。这里按**拓扑连通性**而不是面数阈值剔除：能连到
    主体的发丝细节一定属于最大连通块，不受影响；被删的只有悬空碎料。

    返回 ``(网格, info)``。任何异常、空网格、或清理后主体不再闭合/体积
    非正时都原样回退并写明原因 —— 绝不为了"干净"把主体弄坏。
    """
    import trimesh

    info = {
        "enabled": True, "accepted": False, "reason": None,
        "connected_parts_before": None, "connected_parts_after": None,
        "faces_before": int(len(mesh.faces)), "faces_after": int(len(mesh.faces)),
        "removed_parts": 0, "removed_faces": 0,
        "removed_volume_mm3": 0.0, "main_body_face_ratio": None,
        "watertight_after": bool(getattr(mesh, "is_watertight", False)),
    }
    try:
        if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
            info["reason"] = "空网格，跳过"
            return mesh, info
        parts = mesh.split(only_watertight=False)
        info["connected_parts_before"] = len(parts)
        if len(parts) <= 1:
            info.update({"accepted": True, "reason": "已是单实体，无需剔除",
                         "connected_parts_after": 1,
                         "main_body_face_ratio": 1.0})
            return mesh, info
        part_faces = [int(len(q.faces)) for q in parts]
        main_idx = int(np.argmax(part_faces))
        main = parts[main_idx]
        main_faces = part_faces[main_idx]
        removed_vol = 0.0
        for i, q in enumerate(parts):
            if i == main_idx:
                continue
            v = float(q.volume)
            if np.isfinite(v):
                removed_vol += abs(v)
        cleaned = trimesh.Trimesh(vertices=main.vertices.copy(),
                                  faces=main.faces.copy(), process=True)
        if len(cleaned.faces) == 0 or not bool(np.all(np.isfinite(cleaned.vertices))):
            info["reason"] = "剔除后网格为空或含非有限坐标，回退原网格"
            return mesh, info
        volume = float(cleaned.volume)
        if not bool(cleaned.is_watertight) or not (np.isfinite(volume) and volume > 0):
            info["reason"] = "剩余主体非闭合或体积非正，回退原网格"
            return mesh, info
        remaining = cleaned.split(only_watertight=False)
        info.update({
            "accepted": True,
            "reason": f"保留最大连通块，剔除 {len(parts) - 1} 个悬空碎块",
            "connected_parts_after": len(remaining),
            "faces_after": int(len(cleaned.faces)),
            "removed_parts": len(parts) - 1,
            "removed_faces": int(info["faces_before"] - main_faces),
            "removed_volume_mm3": round(removed_vol, 6),
            "main_body_face_ratio": round(main_faces / max(info["faces_before"], 1), 6),
            "watertight_after": True,
        })
        return cleaned, info
    except Exception as exc:  # noqa: BLE001 - 几何清理失败绝不能中断导出
        info["reason"] = f"{type(exc).__name__}: {exc}"
        return mesh, info


def enforce_single_body(fv):
    """R29：把「只允许单一连通实体」作为硬门禁叠加到文件级复验结论。

    只改 ``checks`` / ``pass`` 与显式字段，保持 R18 的 5 项 verdict checks
    契约不变；因缺依赖而跳过的复验不升级为失败（沿用 R27 既定约定）。
    """
    if not fv or fv.get("skipped") or fv.get("pass") is None:
        return fv
    out = dict(fv)
    checks = dict(out.get("checks") or {})
    parts = int((out.get("metrics") or {}).get("connected_parts") or 0)
    checks["single_body"] = bool(parts == 1)
    out["checks"] = checks
    out["strict_single_body"] = True
    out["single_body_parts"] = parts
    out["pass"] = bool(out.get("pass")) and checks["single_body"]
    if not checks["single_body"]:
        out["single_body_failure"] = (
            f"落地 STL 含 {parts} 个连通块；启用 --drop-floating-parts "
            "可在导出前剔除悬空碎块")
    return out


def _sharp_edge_ratio(mesh, degrees=30.0):
    try:
        angles = mesh.face_adjacency_angles
        if angles is None or len(angles) == 0:
            return None  # 单面/无邻接网格，避免 mean of empty slice 产生 NaN
        return round(float((angles > np.radians(degrees)).mean() * 100), 3)
    except Exception:
        return None


def repair_with_blender(mesh, ref_mask=None, ref_info=None, voxel_mm=0.25,
                        blender_exe=None, max_iou_drop=0.02, timeout=900):
    """导出前水密化：先拓扑修复，必要时按 mm 分辨率做体素重建。

    接受条件：输出非空、三轴尺寸变化 <=2%、轮廓 IoU 下降不超过 max_iou_drop；
    不满足则回退到修复前网格，避免为了水密把角色形状弄坏。
    """
    blender = _find_blender(blender_exe)
    if not blender:
        return mesh, {"accepted": False, "reason": "未找到 Blender"}
    before_ext = np.asarray(mesh.extents, dtype=np.float64)
    before_sharp = _sharp_edge_ratio(mesh)
    before_iou = None
    if ref_mask is not None and _fidelity is not None:
        before_iou = _fidelity.iou(
            _fidelity.silhouette(mesh, size=_fidelity.GRID, accurate=True)[0], ref_mask)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repair_mesh_blender.py")
    stats = {}
    try:
        with tempfile.TemporaryDirectory(prefix="fig_blender_repair_") as tmp:
            src = os.path.join(tmp, "input.stl")
            dst = os.path.join(tmp, "output.stl")
            stats_path = os.path.join(tmp, "stats.json")
            mesh.export(src, file_type="stl")
            cmd = [blender, "--background", "--factory-startup", "--python", script,
                   "--", src, dst, "--voxel-mm", str(float(voxel_mm)),
                   "--json", stats_path]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout)
            output_tail = (proc.stdout or "")[-2000:]
            if os.path.isfile(stats_path):
                try:
                    with open(stats_path, "r", encoding="utf-8") as f:
                        stats = json.load(f)
                except (OSError, ValueError) as exc:
                    stats = {"stats_parse_error": f"{type(exc).__name__}: {exc}"}
            if proc.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
                return mesh, {"accepted": False, "reason": "Blender 修复失败",
                              "returncode": proc.returncode,
                              "output_tail": output_tail, "stats": stats}
            repaired = load_mesh(dst)
    except subprocess.TimeoutExpired:
        return mesh, {"accepted": False, "reason": f"Blender 修复超时（>{timeout}s）",
                      "stats": stats}
    except Exception as exc:  # noqa: BLE001 - 修复失败必须降级，不能中断导出
        return mesh, {"accepted": False,
                      "reason": f"Blender 修复异常，已回退: {type(exc).__name__}: {exc}",
                      "stats": stats}
    after_ext = np.asarray(repaired.extents, dtype=np.float64)
    ext_delta = np.abs(after_ext - before_ext) / np.maximum(before_ext, 1e-9)
    info = {"stats": stats, "voxel_mm": voxel_mm,
            "extents_before": before_ext.round(4).tolist(),
            "extents_after": after_ext.round(4).tolist(),
            "max_extent_delta_pct": round(float(ext_delta.max() * 100), 4),
            "sharp30_before_pct": before_sharp,
            "sharp30_after_pct": _sharp_edge_ratio(repaired),
            "watertight_before": bool(mesh.is_watertight),
            "watertight_after": bool(repaired.is_watertight)}
    if len(repaired.vertices) == 0 or len(repaired.faces) == 0:
        info.update(accepted=False, reason="修复输出为空")
        return mesh, info
    if float(ext_delta.max()) > 0.02:
        info.update(accepted=False, reason="尺寸变化超过 2%，已回退")
        return mesh, info
    if ref_mask is not None and _fidelity is not None and before_iou is not None:
        after_iou = _fidelity.iou(
            _fidelity.silhouette(repaired, size=_fidelity.GRID, accurate=True)[0], ref_mask)
        info["iou_before_repair"] = round(before_iou, 4)
        info["iou_after_repair"] = round(after_iou, 4)
        if before_iou - after_iou > max_iou_drop:
            info.update(accepted=False,
                        reason=f"轮廓 IoU 下降 {before_iou - after_iou:.4f}，已回退")
            return mesh, info
    if ref_mask is not None and before_iou is None:
        info["iou_check"] = "skipped（保真模块不可用，无法做轮廓回退检查）"
    else:
        info["iou_check"] = "performed"
    info.update(accepted=True, reason="通过尺寸与轮廓回退检查")
    return repaired, info


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

        # ★ 底部区域（最低 5% 的顶点）求底座中心与半径。
        #   旧实现用 max(XY 包围盒)，一旦网格里混进背景板，底座会被撑得比主体还大，
        #   把整块背景焊进成品；且中心硬编码 [0,0]，未扶正/未居中的模型会偏出底座。
        #   改用「中位数中心 + 95 分位半径」，对少量离群背景顶点稳健。
        bottom_z = v[:, 2].min() + h * 0.05
        bottom_mask = v[:, 2] < bottom_z
        bottom_pts = v[bottom_mask] if bottom_mask.sum() >= 10 else v
        center_xy = np.median(bottom_pts[:, :2], axis=0)
        radial = np.linalg.norm(bottom_pts[:, :2] - center_xy, axis=1)
        plate_r = float(np.percentile(radial, 95) * radius_margin)
        plate_r = float(np.clip(plate_r, h * 0.03, max(ext[0], ext[1]) * 0.65))

        # 创建圆柱底座（对齐主体底部中心，而非世界原点）
        plate = trimesh.creation.cylinder(
            radius=plate_r, height=plate_h,
            sections=64,
            translation=[float(center_xy[0]), float(center_xy[1]),
                         v[:, 2].min() + plate_h / 2]
        )

        # 倒角（可选）
        if smooth:
            try:
                from trimesh.inertia import principal_inertia
                # 简单方式：用 subdivision 平滑边缘
                plate = trimesh.subdivide(plate)
            except Exception:
                pass

        # 合并：只焊接重合顶点，不做 fill_holes。
        # 旧实现在非水密网格上盲目 fill_holes，会把背景板与角色缝成一块薄壳。
        combined = trimesh.util.concatenate([m, plate])
        combined.merge_vertices()

        desc = (f"半径{plate_r:.2f}×厚{plate_h:.2f} (占高{plate_h/h:.1%})，"
                f"中心({center_xy[0]:.2f},{center_xy[1]:.2f})")
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


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_manifest(outdir, base, args, started, outputs, fidelity_report=None,
                   ref_image=None, file_verification=None):
    """记录一次转换的完整可复现上下文：命令、解释器、输入/输出哈希、耗时。

    指标报告回答「好不好」，manifest 回答「这是怎么来的」。两者分开写，
    避免把运行元数据混进几何指标里。
    """
    def describe(path):
        if not path or not os.path.isfile(path):
            return None
        return {"path": os.path.abspath(path), "bytes": os.path.getsize(path),
                "sha256": _sha256_file(path)}

    manifest = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": list(sys.argv),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "elapsed_sec": round(time.time() - started, 3),
        "input": describe(args.input),
        "reference_image": describe(ref_image),
        "parameters": {k: v for k, v in vars(args).items()
                       if k not in ("input", "blender_exe")},
        "outputs": [describe(p) for p in outputs if p],
        "fidelity_schema": getattr(_fidelity, "SCHEMA_VERSION", None) if _fidelity else None,
        # R27：记录导出后对**磁盘文件**的复验结果，让"怎么来的"同时包含"验过没有"。
        "file_verification": file_verification,
        "verdict": (fidelity_report or {}).get("verdict"),
    }
    path = os.path.join(outdir, f"{base}_manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path


def validate_args(a):
    """集中校验数值参数边界，返回可读错误列表。

    ★ 这些参数过去直接透传到几何运算，非法值不会立刻报错，而是在
      缩放/体素化/门禁环节产生「看似成功但几何已毁」的产物。
    """
    errors = []

    def check(name, value, low, high, allow_zero=True):
        if value is None:
            return
        if value == 0 and not allow_zero:
            errors.append(f"--{name} 必须 > 0，当前 {value}")
        elif not (low <= value <= high):
            errors.append(f"--{name} 应在 [{low}, {high}]，当前 {value}")

    if a.height != 0:  # 0 = 不启用高度缩放；负数同样非法，不能跳过
        check("height", a.height, 10.0, 500.0)
    check("scale", a.scale, 0.001, 1000.0, allow_zero=False)
    check("base", a.base, 0.0, 0.20)
    check("hollow", a.hollow, 0.0, 0.20)
    check("min-iou", a.min_iou, 0.0, 1.0)
    check("voxel-mm", a.voxel_mm, 0.0, 5.0)
    check("repair-max-iou-drop", a.repair_max_iou_drop, 0.0, 1.0)
    check("decimate", getattr(a, "decimate", 0), 0, 50_000_000)
    check("smooth", a.smooth, 0, 100)
    check("pitch", a.pitch, 0.0001, 0.05, allow_zero=False)
    if not a.to:
        errors.append("--to 至少需要一个目标格式")
    # R29：硬门禁只能在导出 STL 后对落地文件生效，否则会静默"启用但没验"。
    if getattr(a, "strict_single_body", False) and not any(
            str(f).lower().lstrip(".") == "stl" for f in (a.to or [])):
        errors.append("--strict-single-body 需要 --to 包含 stl，否则门禁无法落地")
    return errors


def main():
    started = time.time()
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
    ap.add_argument("--smooth", type=int, default=0,
                    help="Taubin 平滑迭代次数（默认 0）。非水密网格会推迟到水密化后执行；"
                         "实测在非流形网格上提前平滑会产生坑点/尖刺")
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
    # ★★ 参考图保真（STL 链路专用）★★
    ap.add_argument("--ref-image", default=None,
                    help="3D 重建时用的参考原图。缺省时自动找同名 <模型>_3d_input.png")
    ap.add_argument("--no-fidelity", action="store_true",
                    help="关闭参考图对齐，退回旧的「最长包围盒轴=身高」启发式")
    ap.add_argument("--no-crop-background", action="store_true",
                    help="不裁掉投影落在参考轮廓外的背景几何")
    ap.add_argument("--min-iou", type=float, default=0.55,
                    help="导出前轮廓相似度门禁（默认 0.55）；设 0 可关闭")
    ap.add_argument("--allow-low-fidelity", action="store_true",
                    help="相似度不达标时仍强制导出（不推荐）")
    ap.add_argument("--fidelity-report", default=None,
                    help="保真报告 JSON 路径（默认 <输出目录>/<模型名>_fidelity.json）")
    # ★★ 导出前水密化（项目已有 Blender）★★
    ap.add_argument("--blender-repair", dest="blender_repair", action="store_true", default=True,
                    help="非水密时自动用 Blender 修复（默认开启）")
    ap.add_argument("--no-blender-repair", dest="blender_repair", action="store_false",
                    help="关闭 Blender 导出前修复")
    ap.add_argument("--voxel-mm", type=float, default=0.15,
                    help="体素水密化分辨率(mm)，默认 0.15（高精度保留细节）；"
                         "0.25=兼容旧版且更快，0=只做拓扑修复（可能仍非水密）")
    ap.add_argument("--repair-max-iou-drop", type=float, default=0.02,
                    help="修复导致轮廓 IoU 下降超过此值时回退，默认 0.02")
    ap.add_argument("--blender-exe", default=None, help="Blender 可执行文件路径")
    ap.add_argument("--strict-watertight", action="store_true",
                    help="最终网格仍非水密/有边界或非流形边时拒绝导出（退出码 3）")
    # R29：R28 只能告警的悬空碎块，现在可在导出前剔除、或作为硬门禁拒绝。
    ap.add_argument("--drop-floating-parts", action="store_true",
                    help="导出前剔除与主实体不相连的悬空闭合壳（只保留最大连通块）")
    ap.add_argument("--strict-single-body", action="store_true",
                    help="落地 STL 必须是单一连通实体，否则验收 FAIL 并返回非零（仅对 stl 生效）")
    a = ap.parse_args()
    arg_errors = validate_args(a)
    if arg_errors:
        for msg in arg_errors:
            print(f"[!] 参数错误: {msg}")
        raise SystemExit(2)

    if not os.path.exists(a.input):
        raise SystemExit(f"[!] 文件不存在: {a.input}")

    # R55：显式 --ref-image 是用户主动要求的保真验收，不得与「自动找图
    # 没找到」一样静默退回旧启发式。实证旧链路在参考图不存在时仍 rc=0
    # 导出 STL、且不生成 fidelity.json，用户拿到的是未做轮廓门禁的成品。
    # --no-fidelity 是明确 opt-out，不受此限制；自动发现失败仍保持兼容。
    if a.ref_image and not a.no_fidelity:
        if not os.path.isfile(a.ref_image):
            print(f"[!] 显式参考图不存在或不是文件: {a.ref_image}；"
                  "已停止，未导出未经保真验收的 STL。若确实不需要校验，"
                  "请显式使用 --no-fidelity")
            raise SystemExit(2)
        if _fidelity is None:
            print("[!] 显式参考图需要 mesh_fidelity，但模块不可用: "
                  f"{_FIDELITY_IMPORT_ERROR}；已停止，未静默跳过保真验收")
            raise SystemExit(2)

    base = os.path.splitext(os.path.basename(a.input))[0]
    # ★ 旧实现只在 --solidify 分支里应用 --out-prefix，其余情况静默忽略；
    #   导致同目录多次转换互相覆盖。统一在这里生效。
    if a.out_prefix:
        base = a.out_prefix
    outdir = a.out_dir or os.path.dirname(os.path.abspath(a.input))
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"[!] 输出目录不可写: {outdir} ({exc})")
    input_abs = os.path.normcase(os.path.abspath(a.input))
    if outdir == os.path.dirname(os.path.abspath(a.input)) and not a.out_prefix:
        print("[!] 未指定 --out-dir/--out-prefix，产物将写入输入文件所在目录；"
              "与输入同名的格式会被自动跳过以防覆盖")

    print(f"[*] 载入: {a.input}")
    m = load_mesh(a.input)
    print(f"    顶点 {len(m.vertices):,}  面 {len(m.faces):,}")

    # 0) 参考图解析：没有参考图 = 旧行为（无保真校验），但明确告警
    ref_image = _resolve_ref_image(a.input, a.ref_image)
    use_fidelity = bool(ref_image) and not a.no_fidelity and _fidelity is not None
    ref_mask = ref_info = None
    if use_fidelity:
        try:
            ref_mask, ref_info = _fidelity.reference_mask(ref_image)
            print(f"[*] 参考图保真: {ref_image}")
            print(f"    掩膜方法={ref_info['mask_method']} 宽高比={ref_info['aspect']:.4f} "
                  f"前景占比={ref_info['foreground_ratio']:.1%}")
        except Exception as exc:  # noqa: BLE001
            # R55：文件存在不等于参考图可用。显式参考图损坏/格式不受支持时，
            # 继续导出会让用户误以为已经过保真门禁，必须与缺失文件同样
            # fail-closed；只有自动发现的同名图解析失败才保留历史降级。
            if a.ref_image:
                print(f"[!] 显式参考图解析失败（{type(exc).__name__}: {exc}）；"
                      "已停止，未导出未经保真验收的 STL")
                raise SystemExit(2) from exc
            print(f"[!] 自动发现的参考图解析失败（{type(exc).__name__}: {exc}），"
                  "退回旧行为；如需强制验收请显式传 --ref-image")
            use_fidelity = False
    if not use_fidelity:
        msg = ""
        if a.no_fidelity:
            msg = "（--no-fidelity）"
        elif _fidelity is None:
            msg = f"（mesh_fidelity 不可用: {_FIDELITY_IMPORT_ERROR}）"
        elif not ref_image:
            msg = "（未找到 --ref-image 或同名 3d_input 图）"
        print(f"[!] 跳过轮廓保真校验，退回旧启发式 {msg}")

    # 1) 尺寸校正
    if a.ref:
        if not os.path.exists(a.ref):
            print(f"[!] 参考网格不存在: {a.ref}")
        else:
            m, factor, ref_ext = match_reference_size(m, a.ref)
            print(f"[*] 尺寸校正: 缩放 {np.round(factor, 4)} "
                  f"(参考尺寸 {np.round(ref_ext, 4)})")

    # 2) 平滑：非流形/非水密网格上提前做 Taubin 会把顶点沿错误邻接关系拉坏。
    #    实测本角色 x10 后面部/衣服出现坑点、发梢与脚部出现尖刺；改为水密化后再做。
    deferred_smooth = 0
    if a.smooth > 0:
        if m.is_watertight:
            print(f"[*] Taubin 平滑 x{a.smooth} ...")
            m = smooth_mesh(m, a.smooth)
        else:
            deferred_smooth = a.smooth
            print(f"[!] 当前网格非水密，Taubin x{a.smooth} 推迟到水密化之后；"
                  f"若未做水密化则跳过，避免破坏表面")

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
    elif not a.no_repair:
        m, rep = repair_mesh(m, a.aggressive)
        print("[*] 修复:")
        for k, v in rep.items():
            print(f"      {k}: {v}")

    # 5) ★ 朝向：优先用参考图轮廓选朝向，取代「最长包围盒轴 = 身高」的错误启发式
    fidelity_detail = None
    if a.orient and use_fidelity:
        print("[*] 参考图驱动对齐（朝向 / 比例 / 背景几何）...")
        crop_requested = not a.no_crop_background
        m_before_align = m.copy()
        m, fidelity_detail = _fidelity.align_mesh(m, ref_mask, ref_info,
                                                  crop=crop_requested)
        # 裁剪超过 15% 面数说明掩膜与网格严重不符，撤销裁剪避免削掉主体
        ci = fidelity_detail.get("crop") or {}
        if ci.get("removed_ratio", 0) > 0.15:
            print(f"[!] 背景裁剪将移除 {ci['removed_ratio']:.1%} 面，超过安全上限，"
                  f"撤销裁剪（可用 --no-crop-background 关闭）")
            m, fidelity_detail = _fidelity.align_mesh(
                m_before_align, ref_mask, ref_info, crop=False)
        del m_before_align
        print(f"    -> 朝向 idx={fidelity_detail['orientation_index']} "
              f"轮廓 IoU {fidelity_detail['iou_as_imported']:.4f} → "
              f"{fidelity_detail['iou_after_orientation']:.4f} → "
              f"{fidelity_detail['iou_after_aspect']:.4f} → "
              f"{fidelity_detail['iou_final']:.4f}")
        ci = fidelity_detail.get("crop") or {}
        if ci:
            print(f"    -> 背景几何裁剪：移除 {ci['faces_before'] - ci['faces_after']:,} 面 "
                  f"({ci['removed_ratio']:.1%})")
        # 居中 X/Y、贴地 Z=0（底座与高度换算都依赖这一步）
        v = np.asarray(m.vertices)
        m.apply_translation([-float(np.median(v[:, 0])),
                             -float(np.median(v[:, 1])),
                             -float(v[:, 2].min())])
        # 裁剪会留下开口边界，做拓扑级修复（不体素化、不碾平表面）
        m, watertight, notes = _fidelity.repair_watertight(m)
        print(f"    -> 拓扑修复: 水密={watertight} {notes}")
    elif a.orient:
        print("[*] 自动扶正朝向（旧启发式，无参考图）...")
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

    # 保真评估用「加底座之前」的网格：底座圆盘会污染正面轮廓
    pre_base_mesh = m.copy() if use_fidelity else None

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

    # 8.5) ★ 参考图保真评估（用加底座之前的网格）
    #     这是原来完全缺失的「评估环节」：坏模型过去一路绿灯导出。
    fidelity_report = None
    if use_fidelity and fidelity_detail is None:
        # --no-orient 时不做对齐，但仍要给导入态打分并走门禁
        imported = _fidelity.iou(_fidelity.silhouette(m)[0], ref_mask)
        fidelity_detail = {"iou_as_imported": round(imported, 4),
                           "iou_after_orientation": round(imported, 4),
                           "iou_after_aspect": round(imported, 4),
                           "iou_final": round(imported, 4),
                           "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                           "orientation_index": -1,
                           "aspect_correction": None,
                           "aspect_correction_after_crop": None,
                           "crop": None}
        print("[!] --no-orient：跳过参考对齐，仅按导入态打分")
    if use_fidelity:
        report_extra = {
            "evaluated_before_base_plate": True,
            "input_mesh": os.path.abspath(a.input),
            "reference_image": os.path.abspath(ref_image),
            "iou_as_imported": fidelity_detail["iou_as_imported"],
            "iou_after_orientation": fidelity_detail["iou_after_orientation"],
            "iou_after_aspect": fidelity_detail["iou_after_aspect"],
            "iou_final": fidelity_detail["iou_final"],
            "rotation": fidelity_detail["rotation"],
            "orientation_index": fidelity_detail["orientation_index"],
            "front_back_resolution": fidelity_detail.get("front_back_resolution"),
            "aspect_correction": fidelity_detail["aspect_correction"],
            "aspect_correction_after_crop": fidelity_detail["aspect_correction_after_crop"],
            "crop": fidelity_detail["crop"],
            "min_iou": a.min_iou,
        }
        fidelity_report = _fidelity.build_report(pre_base_mesh, ref_mask, ref_info,
                                                  extra=report_extra)
        report_path = a.fidelity_report or os.path.join(outdir, f"{base}_fidelity.json")
        _fidelity.save_report(fidelity_report, report_path)
        print(f"\n[*] ===== 轮廓保真报告 =====")
        print(f"    参考图 IoU: {fidelity_report['iou_as_imported']:.4f} (导入态) "
              f"-> {fidelity_report['silhouette_iou']:.4f} (成品)")
        print(f"    宽高比误差: {fidelity_report['aspect_error_pct']:.2f}%  "
              f"水密: {fidelity_report['watertight']}  "
              f"面数: {fidelity_report['faces']:,}")
        print(f"    报告: {report_path}")
        print("    ==========================\n")
        if a.min_iou > 0 and fidelity_report["silhouette_iou"] < a.min_iou \
                and not a.allow_low_fidelity:
            print(f"[✗] 轮廓相似度 {fidelity_report['silhouette_iou']:.4f} < "
                  f"门禁 {a.min_iou:.2f}，拒绝导出 STL。"
                  f" 请更换合格的正面站立参考图重建，或用 "
                  f"--allow-low-fidelity 强制导出（不推荐）。")
            raise SystemExit(2)

    # 8.6) ★ 导出前水密化：只做拓扑修复通常不够，非流形边多时必须体素重建；
    #     但强制做尺寸/轮廓回退检查，防止「为了水密把角色修没」。
    repair_info = None
    if a.blender_repair and not m.is_watertight:
        print(f"[*] Blender 导出前修复（体素分辨率 {a.voxel_mm}mm）...")
        m, repair_info = repair_with_blender(
            m, ref_mask=ref_mask if use_fidelity else None,
            ref_info=ref_info, voxel_mm=a.voxel_mm,
            blender_exe=a.blender_exe, max_iou_drop=a.repair_max_iou_drop)
        print(f"    -> 采用修复结果: {repair_info.get('accepted')}  {repair_info.get('reason')}")
        if repair_info.get("iou_before_repair") is not None:
            print(f"    -> 修复轮廓 IoU {repair_info['iou_before_repair']:.4f} → "
                  f"{repair_info['iou_after_repair']:.4f}")
        print(f"    -> 水密: {repair_info.get('watertight_before')} → "
              f"{repair_info.get('watertight_after')}；"
              f"锐边30°: {repair_info.get('sharp30_before_pct')}% → "
              f"{repair_info.get('sharp30_after_pct')}%")

    # 8.65) 仅在已经水密的网格上执行被推迟的平滑
    if deferred_smooth > 0:
        if m.is_watertight:
            print(f"[*] 水密化后执行 Taubin 平滑 x{deferred_smooth} ...")
            m = smooth_mesh(m, deferred_smooth)
        else:
            print("[!] 网格仍非水密，跳过 Taubin 平滑以保留原始表面")

    # 8.66) ★ R29：可选剔除 Blender 体素重建留下的悬空闭合壳。
    #      必须放在 8.7 最终评估之前，让 final_mesh 报告评价的就是真正导出的网格，
    #      否则又会出现「报告说的是内存副本、成品是另一个东西」的 R27 类缺陷。
    geometry_cleanup = None
    if a.drop_floating_parts:
        m, geometry_cleanup = drop_floating_parts(m)
        print(f"[*] 连通块清理: 采用={geometry_cleanup['accepted']}  "
              f"{geometry_cleanup['connected_parts_before']} -> "
              f"{geometry_cleanup['connected_parts_after']} 块，"
              f"剔除 {geometry_cleanup['removed_parts']} 块 / "
              f"{geometry_cleanup['removed_faces']} 面 "
              f"({geometry_cleanup['removed_volume_mm3']} mm³)")
        print(f"    -> {geometry_cleanup['reason']}")

    # 8.7) 最终导出网格的独立评估（含底座、含水密化结果）
    if use_fidelity:
        fidelity_report["final_mesh"] = _fidelity.build_report(m, ref_mask, ref_info)
        fidelity_report["blender_repair"] = repair_info
        if geometry_cleanup is not None:
            fidelity_report["geometry_cleanup"] = geometry_cleanup
        verdict = build_verdict(fidelity_report, a.min_iou, a.strict_watertight)
        fidelity_report["verdict"] = verdict
        _fidelity.save_report(fidelity_report, report_path)
        final_eval = fidelity_report["final_mesh"]
        print(f"[*] 最终导出网格: IoU={final_eval['silhouette_iou']:.4f}  "
              f"水密={final_eval.get('watertight_indexed')}  "
              f"边界边={final_eval.get('boundary_edges')}  "
              f"非流形边={final_eval.get('nonmanifold_edges')}")
        print(f"[*] 验收结论: {'PASS' if verdict['pass'] else 'FAIL'}  "
              f"检查项={verdict['checks']}  严格水密={a.strict_watertight}")
    elif repair_info is not None:
        repair_path = os.path.join(outdir, f"{base}_repair.json")
        with open(repair_path, "w", encoding="utf-8") as f:
            json.dump(repair_info, f, ensure_ascii=False, indent=2)
        print(f"[*] 修复报告: {repair_path}")

    # 8.8) 硬门禁：默认只提示，--strict-watertight 时不合格直接拒绝导出
    if a.strict_watertight and not m.is_watertight:
        print("[✗] --strict-watertight：最终网格仍非水密，拒绝导出。"
              " 请启用 Blender 修复（去掉 --no-blender-repair）或检查输入网格。")
        raise SystemExit(3)

    # 9) ★ 打印前诊断报告
    if a.diagnose:
        print("\n[*] ===== 打印前诊断报告 =====")
        print_diagnostic(m)
        print("    ==========================\n")

    s = summarize(m)
    print("[*] 网格信息:")
    for k, v in s.items():
        print(f"      {k}: {v}")

    # ★ 旧实现把 3MF 顶点的 mm 坐标再乘 1000，导致同一网格 STL=150mm、
    #   3MF=150000mm（实测历史成品 3MF 顶点 x=-74797mm）。3MF 规范默认单位就是
    #   毫米，trimesh 导出会写 unit="millimeter"，因此所有格式统一用当前 mm 坐标。
    if a.unit != "mm":
        print(f"[!] --unit {a.unit} 仅作兼容保留；几何已按 mm 归一，导出不做二次缩放")

    ok, fail, outputs = [], [], []
    file_verification = None
    # R57：格式白名单与「安全写盘」分离。所有格式统一走 staging → 原子替换，
    # 避免只保护 STL、其它格式仍能在导出中途失败时截掉既有成品。
    export_formats = {"obj", "stl", "3mf", "ply", "glb", "gltf", "fbx", "usdz"}
    for fmt in a.to:
        fmt = fmt.lower().lstrip(".")
        out = os.path.join(outdir, f"{base}.{fmt}")
        # ★ 绝不允许导出结果覆盖输入文件：默认 --to 含 glb、默认输出目录就是
        #   输入所在目录，旧实现会直接把重建结果替换成后处理结果且无法恢复。
        if os.path.normcase(os.path.abspath(out)) == input_abs:
            print(f"[!] {fmt.upper()} 输出路径与输入文件相同，跳过以防覆盖: {out}")
            fail.append((fmt, "输出路径与输入文件相同，已跳过"))
            continue
        if fmt not in export_formats:
            fail.append((fmt, "未知格式"))
            continue
        try:
            # R57：导出先落 staging，成功回读复验后再一次性原子替换；
            # 失败时既有成品保持原样、临时文件全部清理。
            fv = export_mesh_atomic(m, out, fmt, verify_mesh=m)
            if fmt == "stl":
                file_verification = fv  # R27：导出后立即回读磁盘文件复核
            suffix = ""
            if fmt == "obj":
                mtl = os.path.splitext(out)[0] + ".mtl"
                if os.path.exists(mtl):
                    suffix = f" (+ {os.path.basename(mtl)})"
            elif fmt == "3mf":
                suffix = " (单位 millimeter)"
            sz = os.path.getsize(out) / 1e6
            print(f"[✓] {fmt.upper():5s} -> {out}  ({sz:.2f} MB){suffix}")
            ok.append(fmt)
            outputs.append(out)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"[!] {fmt.upper()} 导出失败: {msg}")
            fail.append((fmt, msg))

    # ★ R27 文件级复验闭环：verdict 生成于导出之前，只评价内存网格。
    #   导出后必须回读磁盘文件复核，并把结果写进报告与清单；不合格不再静默 PASS。
    if file_verification is not None:
        fv = file_verification
        # R29：主链路的硬门禁。启用后单实体检查参与 pass，失败会让 verdict=FAIL
        # 且最终退出码非零，不再需要用户绕到旁路 CLI 才能发现碎块。
        if a.strict_single_body:
            fv = enforce_single_body(fv)
            file_verification = fv
        if fv.get("skipped"):
            print(f"[!] 文件级复验跳过: {fv.get('reason')}")
        else:
            print(f"[*] 文件级复验: {'PASS' if fv['pass'] else 'FAIL'}  "
                  f"检查项={fv['checks']}  "
                  f"有符号体积={fv['metrics'].get('volume_signed')}")
            print(f"[*] 连通块={fv['metrics'].get('connected_parts')}  "
                  f"悬空块={fv['metrics'].get('floating_parts')}  "
                  f"退化面={fv['metrics'].get('degenerate_faces')}")
            # R28：悬空碎块属软告警，不推翻既有验收结论，但必须在导出时可见。
            for warning in (fv.get("warnings")
                            or fv["metrics"].get("warnings") or []):
                print(f"[!] {warning}")
        if use_fidelity and fidelity_report is not None:
            fidelity_report["file_verification"] = fv
            fidelity_report["verdict"] = apply_file_verification(
                fidelity_report.get("verdict"), fv)
            _fidelity.save_report(fidelity_report, report_path)
            print(f"[*] 报告已同步文件级复验: {report_path}")
        if fv.get("pass") is False:
            reason = fv.get("error") or "文件级复验失败: " + ", ".join(
                k for k, v in (fv.get("checks") or {}).items() if not v)
            print(f"[✗] {reason}（成品已写出，但验收结论为 FAIL）")
            fail.append(("stl-file-verify", reason))

    if fail:
        print("\n[!] 部分格式失败:")
        for f, msg in fail:
            print(f"      {f}: {msg}")

    # 失败时同样留 manifest，便于复盘「哪一步没产出文件」。
    try:
        manifest_path = write_manifest(outdir, base, a, started, outputs,
                                       fidelity_report, ref_image,
                                       file_verification)
        print(f"[*] 运行清单: {manifest_path}")
    except Exception as exc:  # noqa: BLE001 - 清单写入失败不应让成品导出失败
        print(f"[!] 运行清单写入失败（不影响成品）: {type(exc).__name__}: {exc}")

    print(f"[*] 成功导出格式: {ok or '无'}  失败: {[f for f, _ in fail] or '无'}")
    print(f"\n[✓] 完成，输出目录: {outdir}")
    # 有任一格式失败就返回非零，CI / control_server 才能据此判定任务失败。
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
