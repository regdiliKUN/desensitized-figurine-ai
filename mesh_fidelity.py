# -*- coding: utf-8 -*-
"""参考图驱动的 STL 几何保真模块。

职责（只服务 STL 生成链路，不参与图像生成）：
  1. 从参考图提取主体轮廓掩膜；
  2. 用「轮廓 IoU」在 24 个立方体旋转中挑出与参考图一致的正面朝向，
     取代原先「最长包围盒轴 = 身高」的错误启发式；
  3. 按参考图宽高比校正被 3D 重建归一化过的比例；
  4. 可选：按参考轮廓裁掉混进网格的背景几何（沙发/背景板/色块）；
  5. 输出可复现的量化报告（IoU / 长宽比误差 / 水密性 / 面数 / 变换矩阵）。

依赖：numpy、Pillow（必需）；scipy 可选，缺失时自动走等价的 numpy 降级；
      trimesh 由调用方按需导入；rembg 可选。
"""
from __future__ import annotations

import hashlib
import io
import itertools
import json
import math
import os
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps

GRID = 256
PAD = 0.04
# 报告用更细的网格 + 面积均匀采样，避免「顶点散点 + 视觉外壳」的近似误差
REPORT_GRID = 512
SAMPLE_SEED = 0
SCHEMA_VERSION = "2.0"
# 高精度重建可合法产出数百万面（实测 0.15mm 成品约 206 万面）。
# 拓扑统计已向量化，仍保留上限只是防止极端文件耗尽内存；不能把高细节
# 成品静默跳过，否则报告会缺 watertight_indexed/boundary_edges 并误判。
TOPOLOGY_MAX_FACES = 8_000_000
_LAST_SILHOUETTE_FALLBACK = None  # 表面采样失败时记录降级原因，写进报告 geom

# 报告字段口径：下游脚本 / 人工验收都必须按此解释，避免把自检值当相似度证据。
METRIC_DICTIONARY = {
    "silhouette_iou": "正面正投影轮廓 IoU（0~1，越高越好）；只衡量外轮廓，不衡量五官/服饰特征",
    "eval_grid": "评估栅格边长；不同 grid 的 IoU 不可直接横向比较",
    "silhouette_samples": "表面面积均匀采样点数，seed 固定，可复现",
    "aspect_error_pct": "aspect_correction 之后的宽高比误差，是变换自检值，非保真证据",
    "aspect_error_before_pct": "校正前真实宽高比偏差；null 表示本次未做比例校正",
    "watertight_indexed": "焊接后是否每条边恰好被 2 个面共享（可打印性的必要指标）",
    "boundary_edges": "只被 1 个面使用的边数，必须为 0",
    "nonmanifold_edges": "被 >2 个面使用的边数，必须为 0",
    "depth_height_ratio": "Y 厚度 / Z 高度，用于识别纸片模型",
    "extents_xyz": "三轴包围盒尺寸，几何按 mm 归一后单位为 mm",
}


# ------------------------------------------------- 可选 scipy 依赖的等价降级
class _NumpyNdimage:
    """scipy.ndimage 的最小纯 numpy 替身，只覆盖本模块用到的 7 个操作。

    ★ 契约：装了 scipy 就永远走 scipy，主路径逐像素不变；只有缺 scipy 时启用。
      这样换解释器/换机不会因一个可选依赖让整条保真链路抛 ModuleNotFoundError，
      与 fig.py「无 scipy 退化到纯 Python 洪泛」的既有约定保持一致。
      等价性由 tests/test_mesh_fidelity.py 的 TestOptionalScipy 回归保护。
    """
    _CROSS = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)

    @staticmethod
    def generate_binary_structure(rank, connectivity):
        if rank != 2 or connectivity not in (1, 2):
            raise ValueError("numpy 降级仅支持二维 4/8 邻接结构元素")
        return (_NumpyNdimage._CROSS.copy() if connectivity == 1
                else np.ones((3, 3), dtype=bool))

    @staticmethod
    def label(mask, structure=None):
        """4/8 邻接连通域标记，返回 (labels, n)，语义与 ndimage.label 一致。"""
        from collections import deque
        arr = np.asarray(mask, dtype=bool)
        struct = (_NumpyNdimage._CROSS if structure is None
                  else np.asarray(structure, dtype=bool))
        offsets = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                   if struct[dy + 1, dx + 1] and (dy or dx)]
        h, w = arr.shape
        labels = np.zeros((h, w), dtype=np.int32)
        seen = np.zeros((h, w), dtype=bool)
        n = 0
        ys, xs = np.nonzero(arr)
        for y, x in zip(ys, xs):
            if seen[y, x]:
                continue
            n += 1
            seen[y, x] = True
            queue = deque([(int(y), int(x))])
            while queue:
                cy, cx = queue.popleft()
                labels[cy, cx] = n
                for dy, dx in offsets:
                    ny, nx = cy + dy, cx + dx
                    if (0 <= ny < h and 0 <= nx < w and arr[ny, nx]
                            and not seen[ny, nx]):
                        seen[ny, nx] = True
                        queue.append((ny, nx))
        return labels, n

    @staticmethod
    def sum(mask, labels, index):
        """按标签统计 mask 为真的像素数（ndimage.sum 在本模块的唯一用法）。"""
        arr = np.asarray(mask, dtype=bool)
        lab = np.asarray(labels)
        return np.asarray([float(np.count_nonzero(arr & (lab == i)))
                           for i in index], dtype=np.float64)

    @staticmethod
    def _shift_op(arr, structure, mode):
        struct = (np.ones((3, 3), dtype=bool) if structure is None
                  else np.asarray(structure, dtype=bool))
        h, w = arr.shape
        padded = np.pad(arr, 1, mode="constant", constant_values=False)
        out = (np.zeros((h, w), dtype=bool) if mode == "dilate"
               else np.ones((h, w), dtype=bool))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not struct[dy + 1, dx + 1]:
                    continue
                tile = padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                if mode == "dilate":
                    out |= tile
                else:
                    out &= tile
        return out

    @classmethod
    def binary_dilation(cls, arr, iterations=1, structure=None):
        out = np.asarray(arr, dtype=bool)
        for _ in range(int(iterations)):
            out = cls._shift_op(out, structure, "dilate")
        return out

    @classmethod
    def binary_erosion(cls, arr, iterations=1, structure=None):
        out = np.asarray(arr, dtype=bool)
        for _ in range(int(iterations)):
            out = cls._shift_op(out, structure, "erode")
        return out

    @classmethod
    def binary_closing(cls, arr, structure=None, iterations=1):
        dilated = cls.binary_dilation(arr, iterations=iterations,
                                      structure=structure)
        return cls.binary_erosion(dilated, iterations=iterations,
                                  structure=structure)

    @staticmethod
    def binary_fill_holes(arr):
        """4 邻接从画布边界洪泛背景，未被洪泛到的背景即为孔洞。"""
        from collections import deque
        img = np.asarray(arr, dtype=bool)
        h, w = img.shape
        reachable = np.zeros((h, w), dtype=bool)
        queue = deque()
        for x in range(w):
            for y in (0, h - 1):
                if not img[y, x] and not reachable[y, x]:
                    reachable[y, x] = True
                    queue.append((y, x))
        for y in range(h):
            for x in (0, w - 1):
                if not img[y, x] and not reachable[y, x]:
                    reachable[y, x] = True
                    queue.append((y, x))
        while queue:
            cy, cx = queue.popleft()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = cy + dy, cx + dx
                if (0 <= ny < h and 0 <= nx < w and not img[ny, nx]
                        and not reachable[ny, nx]):
                    reachable[ny, nx] = True
                    queue.append((ny, nx))
        return img | (~img & ~reachable)

    @staticmethod
    def affine_transform(src, matrix, offset, output_shape, order=0):
        """order=0 的二维最近邻仿射；仅支持对角矩阵，与本模块调用点一致。"""
        if order != 0:
            raise ValueError("numpy 降级仅支持 order=0")
        m = np.asarray(matrix, dtype=float)
        if m.shape != (2, 2) or abs(m[0, 1]) > 1e-12 or abs(m[1, 0]) > 1e-12:
            raise ValueError("numpy 降级仅支持对角 matrix")
        arr = np.asarray(src)
        h, w = int(output_shape[0]), int(output_shape[1])
        # scipy 的 order=0：先用**浮点坐标**判越界（0 <= coord <= size-1，
        # 越界填 cval=0），再对坐标做 floor(coord+0.5) 最近邻取整。
        # 若改用取整后的索引判越界，-0.5<coord<0 的半像素会被误判为有效，
        # 在画布上边界产生整行假前景（实测 39/4096 像素）。
        cy = np.broadcast_to(
            np.arange(h, dtype=float)[:, None] * m[0, 0] + float(offset[0]),
            (h, w))
        cx = np.broadcast_to(
            np.arange(w, dtype=float)[None, :] * m[1, 1] + float(offset[1]),
            (h, w))
        valid = ((cy >= 0) & (cy <= arr.shape[0] - 1) &
                 (cx >= 0) & (cx <= arr.shape[1] - 1))
        iy = np.clip(np.floor(cy + 0.5).astype(int), 0, arr.shape[0] - 1)
        ix = np.clip(np.floor(cx + 0.5).astype(int), 0, arr.shape[1] - 1)
        out = np.zeros((h, w), dtype=arr.dtype)
        out[valid] = arr[iy[valid], ix[valid]]
        return out


@lru_cache(maxsize=1)
def _ndimage():
    """返回 scipy.ndimage 或等价降级对象；探测结果缓存，避免每朝向重复 import。"""
    try:
        from scipy import ndimage
        return ndimage
    except ImportError:
        return _NumpyNdimage()


# ---------------------------------------------------------------- 参考轮廓
def _load_rgb(path):
    """统一读图：应用 EXIF 旋转、把透明区合成到白底，再转 RGB。

    ★ 两个真实误判源：
      1) 手机/相机图带 EXIF orientation，忽略它会把横躺的角色当竖图评估；
      2) RGBA 透明背景直接 convert('RGB') 会变成纯黑，被颜色判据当成主体，
         前景占比虚高到接近 100%，门禁与掩膜全错。
    所有读图入口（掩膜 / 门禁 / 对称度）必须共用本函数，保证口径一致。
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"参考图不存在或不是文件: {path}")
    try:
        with Image.open(path) as src:
            src = ImageOps.exif_transpose(src)
            has_alpha = (src.mode in ("RGBA", "LA") or
                         (src.mode == "P" and "transparency" in src.info))
            if has_alpha:
                rgba = src.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                bg.alpha_composite(rgba)
                return bg.convert("RGB")
            return src.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError(f"参考图无法解码: {path} ({type(exc).__name__}: {exc})") from exc


def _largest_component(mask):
    """只保留面积最大的连通块，剔除与主体分离的碎片。"""
    ndimage = _ndimage()
    lab, n = ndimage.label(mask, structure=ndimage.generate_binary_structure(2, 2))
    if n <= 1:
        return mask
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    return lab == (int(np.argmax(sizes)) + 1)


def _fit_mask(mask, size=GRID, pad=PAD):
    """按主体包围盒等比缩放并居中放进方形画布，保留原始宽高比。

    ★ 全模块唯一坐标系约定（务必与 silhouette / save_comparison 保持一致）：
      画布「行号递增」== 世界坐标 +Z 递增。
      即第 0 行 = -Z（脚底），最后一行 = +Z（头顶）。
    原图 y 向下增大（第 0 行是头顶），所以这里把裁出的主体 **上下翻转**，
    让脚底落在第 0 行；silhouette() 的投影恰好是 world Z 越大行号越大，
    两者因此对齐。不翻转会选出头朝 -Z 的倒立朝向，底座会焊在头上。
    展示层（save_comparison / save_before_after）再翻一次回到「头在上」的观感。
    """
    ys, xs = np.where(mask)
    if not len(xs):
        return np.zeros((size, size), dtype=bool), {
            "aspect": 1.0, "bbox": [0, 0, 0, 0], "empty_mask": True,
            "grid": size, "pad": pad, "z_up_flipped": True}
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    crop = mask[y0:y1 + 1, x0:x1 + 1]
    h, w = crop.shape
    scale = size * (1 - 2 * pad) / float(max(h, w))
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    im = Image.fromarray((crop * 255).astype("uint8")).resize((nw, nh), Image.NEAREST)
    canvas = np.zeros((size, size), dtype=bool)
    oy, ox = (size - nh) // 2, (size - nw) // 2
    canvas[oy:oy + nh, ox:ox + nw] = np.asarray(im)[::-1] > 127
    return canvas, {"aspect": w / float(h), "bbox": [x0, y0, x1 + 1, y1 + 1],
                    "grid": size, "pad": pad, "z_up_flipped": True,
                    "empty_mask": False}


def reference_mask(path, size=GRID):
    """从参考图得到 (轮廓掩膜, 信息)。

    白底去背图走颜色判据（确定性、可复现）；复杂背景走 rembg 的主体分割，
    缺失时退化到亮度/饱和度判据。信息里同时给出「主体是否被背景缠绕」的
    可量化指标，供上游 3D 输入门禁使用。
    """
    path = os.path.abspath(path)
    im = _load_rgb(path)
    arr = np.asarray(im).astype(np.float32) / 255.0
    mx, mn = arr.max(axis=2), arr.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    near_white = (mn > 0.94) & (sat < 0.12)
    white_ratio = float(near_white.mean())

    method = "white_background"
    if white_ratio > 0.55:
        raw = ~near_white
    else:
        method = "rembg:isnet-anime"
        try:
            from rembg import new_session, remove
            if not hasattr(reference_mask, "_session"):
                reference_mask._session = new_session("isnet-anime")
            with open(path, "rb") as f:
                out = remove(f.read(), session=reference_mask._session)
            alpha = np.asarray(Image.open(io.BytesIO(out)).convert("RGBA").split()[-1])
            raw = alpha > 128
        except Exception:
            method = "color_fallback"
            raw = ~((mx > 0.88) & (sat < 0.12))

    coverage = float(raw.mean())
    border = np.zeros_like(raw)
    border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
    edge_contact = float((raw & border).sum()) / max(float(raw.sum()), 1.0)
    raw = _largest_component(raw)
    fitted, info = _fit_mask(raw, size=size)
    info.update({
        "reference": path,
        "image_size": [im.width, im.height],
        "mask_method": method,
        "white_ratio": round(white_ratio, 4),
        "foreground_ratio": round(coverage, 4),
        "edge_contact_ratio": round(edge_contact, 4),
        "kept_component_ratio": round(float(raw.sum()) / max(coverage * raw.size, 1.0), 4),
    })
    return fitted, info


# ---------------------------------------------------------------- 轮廓 IoU
def _visual_hull(occ, gap_ratio=0.06):
    """把散点投影变成闭合轮廓：逐行/逐列补短间隙，取两者交集（视觉外壳）。

    ★ 向量化实现：对每行用「最近左侧采样点」与「最近右侧采样点」的累积
      极值一次求出所有待填区间，替代原来的双层 Python 循环。语义与旧实现
      完全一致：相邻采样点间距 <= gap 时把中间补上，超出 gap 则断开。
    """
    h, w = occ.shape
    gap = max(2, int(w * gap_ratio))

    def _fill_dense(mat, g):
        width = mat.shape[1]
        x = np.arange(width, dtype=np.int64)[None, :]
        inf = width + g + 1
        left = np.maximum.accumulate(np.where(mat, x, -inf), axis=1)
        right = np.minimum.accumulate(
            np.where(mat, x, inf)[:, ::-1], axis=1)[:, ::-1]
        return ((x >= left) & (x <= right) & ((right - left) <= g) &
                (right < inf) & (left > -inf))

    def _fill_sparse(mat, g):
        # 采样点极少时，全数组累积运算反而比只遍历少量 True 点更贵。
        out = np.zeros_like(mat)
        for i in range(mat.shape[0]):
            xs = np.where(mat[i])[0]
            if not len(xs):
                continue
            start = prev = int(xs[0])
            for x in xs[1:]:
                x = int(x)
                if x - prev > g:
                    out[i, start:prev + 1] = True
                    start = x
                prev = x
            out[i, start:prev + 1] = True
        return out

    fill = _fill_sparse if float(occ.mean()) < 0.02 else _fill_dense
    return fill(occ, gap) & fill(occ.T, gap).T


def _finite_rows(arr):
    """丢弃含 NaN/Inf 的行，避免归一化与栅格化索引被污染。"""
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim != 2 or a.size == 0:
        return a.reshape(-1, a.shape[-1] if a.ndim == 2 else 1)
    return a[np.isfinite(a).all(axis=1)]


def _points_mask(points, size=GRID, pad=PAD, assume_finite=False):
    """二维点集 -> 等比归一化到方形画布的散点图。

    assume_finite=True 由朝向搜索内循环使用：调用方已在入口过滤过 NaN/Inf，
    这里跳过 24 次重复的 40 万点全量拷贝。
    """
    pts = points if assume_finite else _finite_rows(points)
    if not len(pts):
        return np.zeros((size, size), dtype=bool), {
            "scale": 1.0, "center": [0.0, 0.0], "extent": [0.0, 0.0], "empty": True}
    mn, mx = pts.min(axis=0), pts.max(axis=0)
    span = mx - mn
    scale = size * (1 - 2 * pad) / max(float(span.max()), 1e-9)
    xy = (pts - (mn + mx) / 2.0) * scale + size / 2.0
    ix = np.clip(np.round(xy[:, 0]).astype(int), 0, size - 1)
    iy = np.clip(np.round(xy[:, 1]).astype(int), 0, size - 1)
    occ = np.zeros((size, size), dtype=bool)
    occ[iy, ix] = True
    return occ, {"scale": scale, "center": ((mn + mx) / 2.0).tolist(),
                 "extent": span.tolist()}


def make_projector(mesh, axes=(0, 2), size=GRID):
    """固定「世界坐标 -> 轮廓网格」映射，使裁剪前后的 IoU 可严格比较。"""
    v = _finite_rows(mesh.vertices)[:, list(axes)]
    if not len(v):
        return {"size": size, "axes": list(axes), "scale": 1.0,
                "center": [0.0, 0.0], "empty": True}
    pts = v
    mn, mx = pts.min(axis=0), pts.max(axis=0)
    scale = size * (1 - 2 * PAD) / max(float((mx - mn).max()), 1e-9)
    return {"size": size, "axes": list(axes), "scale": scale,
            "center": ((mn + mx) / 2.0).tolist()}


def _occ_from_points(points, projector):
    size = projector["size"]
    scale = projector["scale"]
    center = np.asarray(projector["center"], dtype=np.float64)
    pts = _finite_rows(points)
    occ = np.zeros((size, size), dtype=bool)
    if not len(pts):
        return occ
    xy = (pts - center) * scale + size / 2.0
    ix = np.clip(np.round(xy[:, 0]).astype(int), 0, size - 1)
    iy = np.clip(np.round(xy[:, 1]).astype(int), 0, size - 1)
    occ[iy, ix] = True
    return occ


def rasterize_silhouette(mesh, projector, samples=None):
    """真实投影轮廓：在**三角面表面**做面积均匀采样后栅格化。

    旧实现只投影顶点，细长/大三角面内部没有样本，轮廓会漏面；
    这里用 sample_surface 按面积采样（固定随机种子，可复现），
    再做形态学闭运算 + 空洞填充得到实心轮廓。
    """
    ndimage = _ndimage()
    import trimesh
    size = projector["size"]
    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        return np.zeros((size, size), dtype=bool)
    if samples is None:
        # ★ 采样量应由「评估网格分辨率」决定，而不是面数：512² 网格只有 26 万
        #   像素，按 4×面数采到 297 万点属严重过采样。实测 3M→400k 时 IoU 只差
        #   0.0004，耗时降约 4.7 倍。固定 seed 保证可复现。
        samples = int(np.clip(2 * size * size, 200000, 1000000))
    fallback = None
    try:
        pts, _ = trimesh.sample.sample_surface(mesh, samples, seed=SAMPLE_SEED)
    except Exception as exc:  # noqa: BLE001
        fallback = type(exc).__name__
        pts = np.asarray(mesh.vertices, dtype=np.float64)
    occ = _occ_from_points(np.asarray(pts)[:, projector["axes"]], projector)
    if not occ.any():
        return occ
    closed = ndimage.binary_closing(occ, structure=np.ones((3, 3), dtype=bool), iterations=2)
    result = ndimage.binary_fill_holes(closed)
    global _LAST_SILHOUETTE_FALLBACK
    _LAST_SILHOUETTE_FALLBACK = fallback
    rasterize_silhouette.last_samples = int(samples)
    return result


def silhouette(mesh, projector=None, size=GRID, accurate=False):
    """网格沿指定两轴的正投影轮廓（前视图默认 X/Z，即丢掉 Y）。

    坐标系：行号递增 == +Z 递增（第 0 行脚底，最后一行头顶），
    与 _fit_mask 输出的参考掩膜严格一致；展示时才上下翻转。

    projector 不为空时使用固定映射（用于比较裁剪前后）；为空时按当前
    包围盒归一化（用于跨模型/跨朝向的独立打分）。
    accurate=True 用表面采样栅格化（报告用），False 用顶点散点（朝向粗筛用）。
    """
    axes = tuple(projector["axes"]) if projector else (0, 2)
    size = projector["size"] if projector else size
    if projector is None:
        projector = make_projector(mesh, axes=axes, size=size)
    if accurate:
        global _LAST_SILHOUETTE_FALLBACK
        _LAST_SILHOUETTE_FALLBACK = None
        return rasterize_silhouette(mesh, projector), {
            "scale": projector["scale"], "center": projector["center"],
            "method": "surface_sample", "grid": size,
            "samples": getattr(rasterize_silhouette, "last_samples", None),
            "seed": SAMPLE_SEED,
            "fallback": _LAST_SILHOUETTE_FALLBACK,
            "empty": bool(projector.get("empty"))}
    v = np.asarray(mesh.vertices, dtype=np.float64)[:, list(axes)]
    occ = _occ_from_points(v, projector)
    return _visual_hull(occ), {"scale": projector["scale"],
                               "center": projector["center"], "method": "vertex_scatter"}


def iou(a: np.ndarray, b: np.ndarray) -> float:
    """两个布尔掩膜的交并比；全空时返回 0 而不是 NaN。"""
    a, b = a.astype(bool), b.astype(bool)
    union = float((a | b).sum())
    return float((a & b).sum() / union) if union else 0.0


@lru_cache(maxsize=1)
def _cube_rotations_cached() -> tuple[np.ndarray, ...]:
    """惰性枚举一次 24 个行列式为 +1 的轴对齐旋转；返回不可变 tuple。"""
    result = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            r = np.zeros((3, 3), dtype=np.float64)
            for i, p in enumerate(perm):
                r[i, p] = signs[i]
            if round(np.linalg.det(r)) == 1:
                result.append(r)
    return tuple(result)


@lru_cache(maxsize=1)
def _cube_rotations_axes() -> tuple[tuple[tuple[int, float], ...], ...]:
    """基于上面的旋转表，预提取每个朝向的 (源轴, 符号) X/Z 分量。"""
    out = []
    for r in _cube_rotations_cached():
        rows = []
        for row in (0, 2):
            axis = int(np.argmax(np.abs(r[row])))
            rows.append((axis, float(r[row, axis])))
        out.append(tuple(rows))
    return tuple(out)


def cube_rotations() -> list[np.ndarray]:
    """24 个行列式为 +1 的轴对齐旋转（不含镜像）；返回新的副本列表。"""
    return [r.copy() for r in _cube_rotations_cached()]


def _rotation_angle(rot):
    """旋转角（弧度），用于在同分朝向里挑「离导入姿态最近」的那个。"""
    c = float(np.clip((np.trace(rot) - 1.0) / 2.0, -1.0, 1.0))
    return float(np.arccos(c))


def _projected_xz(v, axes_signed):
    """轴对齐旋转后只取 X/Z 两列：等价于 (v @ rot.T)[:, [0, 2]]，
    但省掉 3×3 矩阵乘和完整 N×3 中间数组（朝向搜索要跑 24 次）。"""
    out = np.empty((len(v), 2), dtype=np.float64)
    for col, (axis, sign) in enumerate(axes_signed):
        out[:, col] = v[:, axis] * sign
    return out


def front_detail_score(mesh, size=192, head_fraction=0.60):
    """估算「朝观察者的上半部表面」的几何起伏，用于区分正脸与后脑勺。

    轮廓 IoU 对绕 Z 轴 180° 几乎对称，单靠 IoU 排序会让背面以微小噪声分
    胜出。把顶点投影到 X/Z 网格、取 -Y 方向最近表面深度，再统计头部区域
    深度梯度：五官/刘海/衣领有明显起伏，后脑勺与背部是大面积平滑曲面。
    实测同一模型正面约 0.0089、背面约 0.0061。
    """
    v = _finite_rows(mesh.vertices)
    if len(v) == 0:
        return 0.0
    p = make_projector(mesh, (0, 2), size)
    xy = (v[:, [0, 2]] - np.asarray(p["center"])) * p["scale"] + size / 2.0
    ix = np.clip(np.round(xy[:, 0]).astype(int), 0, size - 1)
    iy = np.clip(np.round(xy[:, 1]).astype(int), 0, size - 1)
    depth = np.full((size, size), np.inf)
    np.minimum.at(depth, (iy, ix), v[:, 1])
    depth = np.where(np.isfinite(depth), depth, np.nan)
    head = np.zeros((size, size), dtype=bool)
    head[int(size * (1.0 - head_fraction)):, :] = True  # 行号大 = +Z = 头部
    gx = np.abs(np.diff(depth, axis=1))
    gy = np.abs(np.diff(depth, axis=0))
    vals = np.concatenate([gx[head[:, 1:]].ravel(), gy[head[1:, :]].ravel()])
    vals = vals[np.isfinite(vals)]
    return float(np.mean(np.clip(vals, 0.0, 5.0))) if len(vals) else 0.0


_Z_FLIP = np.diag([-1.0, -1.0, 1.0])


def _is_z_flip_pair(a, b):
    """两个朝向是否只差一个绕 Z 轴 180° 旋转（轮廓 IoU 对它们无法区分）。"""
    return bool(np.allclose(a @ b.T, _Z_FLIP, atol=1e-6))


def best_orientation(mesh, ref, size=GRID, sample=400000, tie_tol=0.02):
    """返回使正面轮廓 IoU 最大的旋转，以及全部候选得分。

    ★ 正/背面歧义：轮廓 IoU 对绕 Z 轴 180° 完全对称，纯按 IoU 排序会随机
    把背面当正面导出。这里在「与最优分差距 <= tie_tol」的候选里，改选
    **旋转角最小**的那个 —— 3D 重建器输出的导入姿态本身就是正面，
    最小旋转能保留它的朝向，而不是把模型翻到背面。
    """
    v = _finite_rows(mesh.vertices)  # 只在入口过滤一次，内循环不再重复
    if len(v) > sample:
        idx = np.linspace(0, len(v) - 1, sample).astype(int)
        v = v[idx]
    rotations = _cube_rotations_cached()
    axes_signed = _cube_rotations_axes()
    scored = []
    for i, r in enumerate(rotations):
        occ, _ = _points_mask(_projected_xz(v, axes_signed[i]), size=size,
                              assume_finite=True)
        score = iou(_visual_hull(occ), ref)
        scored.append((score, i, r))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0]
    tied = [s for s in scored if best - s[0] <= tie_tol]
    front_resolution = None
    # ★ 优先显式解决正/背面歧义：找出与最优朝向只差绕 Z 180° 的候选，
    #   用前表面几何起伏定正面，而不是让 0.01~0.02 的 IoU 噪声决定。
    flip = next((s for s in tied if _is_z_flip_pair(s[2], scored[0][2])), None)
    if flip is not None:
        a = front_detail_score(apply_rotation(mesh, scored[0][2]))
        b = front_detail_score(apply_rotation(mesh, flip[2]))
        if b > a * 1.05:
            chosen = flip
        else:
            chosen = scored[0]
        front_resolution = {
            "method": "front_surface_detail",
            "best_iou_candidate": scored[0][1], "z_flip_candidate": flip[1],
            "detail_best": round(a, 6), "detail_flipped": round(b, 6),
            "chosen_index": chosen[1],
        }
    else:
        tied.sort(key=lambda s: _rotation_angle(s[2]))
        chosen = tied[0]
    chosen = (chosen[0], chosen[1], chosen[2])
    top = [{"index": i, "iou": round(s, 4), "rotation_angle_deg": round(
        math.degrees(_rotation_angle(r)), 1),
        "rotation": np.round(r, 3).tolist()} for s, i, r in scored[:6]]
    return chosen, (top, front_resolution)


def apply_rotation(mesh, rotation):
    import trimesh
    t = np.eye(4)
    t[:3, :3] = rotation
    out = mesh.copy()
    out.apply_transform(t)
    return out


def align_reference_mask(ref, sil, size=GRID, scales=(0.90, 0.95, 1.0, 1.05, 1.10),
                         offsets=(-12, -6, 0, 6, 12)):
    """把参考掩膜做小幅「等比缩放 + 平移」以贴合网格投影。

    仅用于**背景几何裁剪**的对齐，不参与相似度打分：打分始终用未经变换的
    参考掩膜，避免用掩膜去迁就坏模型而虚高指标。
    """
    ndimage = _ndimage()
    # 有/无 scipy 都走同一套仿射：_NumpyNdimage.affine_transform 已按
    # 「浮点坐标判越界 + floor(coord+0.5) 取整」实现逐像素等价（见等价性测试），
    # 因此裁剪结果不因换解释器而变化。
    center = (size - 1) / 2.0
    best = (0.0, 1.0, 0, 0)
    src = ref.astype(np.float32)
    for f in scales:
        for dx in offsets:
            for dy in offsets:
                offset = [center * (1 - 1.0 / f) - dx / f,
                          center * (1 - 1.0 / f) - dy / f]
                moved = ndimage.affine_transform(
                    src, matrix=np.diag([1.0 / f, 1.0 / f]), offset=offset,
                    output_shape=(size, size), order=0) > 0.5
                score = iou(moved, sil)
                if score > best[0]:
                    best = (score, f, dx, dy)
    _, f, dx, dy = best
    offset = [center * (1 - 1.0 / f) - dx / f,
              center * (1 - 1.0 / f) - dy / f]
    moved = ndimage.affine_transform(
        src, matrix=np.diag([1.0 / f, 1.0 / f]), offset=offset,
        output_shape=(size, size), order=0) > 0.5
    return moved, {"iou_for_crop": round(best[0], 4), "scale": f,
                   "offset_px": [dx, dy]}


def align_mesh(mesh, ref, ref_info, size=GRID, crop=False):
    """完整参考对齐：朝向 -> 比例 -> （可选）背景几何裁剪。

    返回 (对齐后的网格, 细节)。相似度指标始终用**未经变换的原始参考掩膜**
    计算；固定投影仅用于裁剪前后可比，不会为迁就坏模型而移动参考掩膜。
    """
    imported_iou = iou(silhouette(mesh, size=size)[0], ref)
    (coarse, idx, rot), (top, front_resolution) = best_orientation(mesh, ref, size=size)
    out = apply_rotation(mesh, rot)
    oriented_iou = iou(silhouette(out, size=size)[0], ref)

    asp = None
    if ref_info.get("aspect"):
        out, asp = aspect_correction(out, float(ref_info["aspect"]))
    projector = make_projector(out, size=size)
    aspect_iou = iou(silhouette(out, projector)[0], ref)

    crop_info, mask_fit, asp2, fixed_iou = None, None, None, None
    if crop:
        sil = silhouette(out, projector, accurate=True)[0]
        moved, mask_fit = align_reference_mask(ref, sil, size=size)
        out, crop_info = crop_to_reference(out, moved, projector=projector)
        out.remove_unreferenced_vertices()
        # 裁剪会改变包围盒（背景板往往在 X 方向撑得很宽），必须二次校正比例，
        # 否则成品宽高比会再次偏离参考图。
        out, asp2 = aspect_correction(out, float(ref_info.get("aspect", 1.0)))
        fixed_iou = iou(silhouette(out, projector)[0], ref)

    # 对外报告一律用「自归一化」投影：平移/缩放不变，衡量的是形状本身，
    # 不会因为固定投影框里背景被裁掉而虚高。
    final_iou = iou(silhouette(out, size=size)[0], ref)
    detail = {
        "rotation": np.round(rot, 3).tolist(),
        "rotation_angle_deg": round(math.degrees(_rotation_angle(rot)), 2),
        "orientation_index": int(idx),
        "top_orientations": top,
        "front_back_resolution": front_resolution,
        "aspect_correction": asp,
        "aspect_correction_after_crop": asp2,
        "crop_mask_alignment": mask_fit,
        "crop": crop_info,
        "iou_as_imported": round(imported_iou, 4),
        "iou_after_orientation": round(oriented_iou, 4),
        "iou_after_aspect": round(aspect_iou, 4),
        "iou_final": round(final_iou, 4),
        "iou_fixed_projector_diagnostic": round(fixed_iou, 4) if fixed_iou is not None else None,
    }
    return out, detail


def aspect_correction(mesh, target_aspect, axes=(0, 2)):
    """按参考图宽高比校正被重建归一化压扁/撑宽的比例，返回缩放系数。"""
    v = np.asarray(mesh.vertices, dtype=np.float64)
    span = v.max(axis=0) - v.min(axis=0)
    current = float(span[axes[0]] / max(span[axes[1]], 1e-9))
    factor = float(np.clip(target_aspect / max(current, 1e-9), 0.35, 3.0))
    out = mesh.copy()
    s = [1.0, 1.0, 1.0]
    s[axes[0]] = factor
    out.apply_scale(s)
    return out, {"scale_xyz": s, "aspect_before": round(current, 4),
                 "aspect_target": round(float(target_aspect), 4),
                 "aspect_after": round(current * factor, 4)}


def crop_to_reference(mesh, ref, projector=None, size=GRID, dilation=3,
                      chunk=200000, mode="vertices"):
    """按参考轮廓裁掉网格里不属于主体的几何（背景板/沙发/色块）。

    mode="vertices"（默认）：用「重心 + 三个顶点」共 4 个投影点投票，>=2 点
      落在参考轮廓内才保留。重建网格里细长三角形很多，只判重心会让跨边界的
      主体面被误删、背景面被误留。
    mode="centroid"：旧的单点判定，保留作 A/B 对照与回归基线。
    projector 为空时按当前包围盒建立映射。
    """
    ndimage = _ndimage()
    keep_mask = ndimage.binary_dilation(ref, iterations=dilation) if dilation > 0 else ref
    if projector is None:
        projector = make_projector(mesh, size=size)
    axes = projector["axes"]
    scale = projector["scale"]
    center = np.asarray(projector["center"], dtype=np.float64)
    grid = projector["size"]
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces)
    keep = np.zeros(len(f), dtype=bool)
    for start in range(0, len(f), chunk):
        tri = v[f[start:start + chunk]]  # (B, 3, 3)
        if mode == "centroid":
            samples = tri.mean(axis=1)[:, axes][:, None, :]
            threshold = 1
        else:
            centroid = tri.mean(axis=1)[:, axes][:, None, :]
            samples = np.concatenate([centroid, tri[:, :, axes]], axis=1)
            threshold = 2
        xy = (samples - center) * scale + grid / 2.0
        ix = np.clip(np.round(xy[..., 0]).astype(int), 0, grid - 1)
        iy = np.clip(np.round(xy[..., 1]).astype(int), 0, grid - 1)
        inside = keep_mask[iy, ix]
        keep[start:start + len(tri)] = inside.sum(axis=1) >= threshold
    out = mesh.copy()
    before = len(out.faces)
    out.update_faces(keep)
    out.remove_unreferenced_vertices()
    return out, {"faces_before": int(before), "faces_after": int(len(out.faces)),
                 "removed_ratio": round(1.0 - len(out.faces) / max(before, 1), 4),
                 "mode": mode}


def repair_watertight(mesh):
    """尽力修复水密性；返回 (mesh, 是否水密, 说明)。"""
    notes = []
    m = mesh.copy()
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    for _ in range(3):
        if m.is_watertight:
            break
        try:
            holes = m.fill_holes()
            if holes:
                notes.append(f"fill_holes={holes}")
        except Exception as exc:
            notes.append(f"fill_holes_failed={type(exc).__name__}")
        try:
            m.fix_normals()
        except Exception:
            pass
        m.merge_vertices()
    try:
        winding = bool(m.is_winding_consistent)
    except Exception:
        winding = None
    return m, bool(m.is_watertight), {"notes": notes, "winding_consistent": winding}


def _safe_metric(fn, default=None):
    """退化网格上 trimesh 的 area/is_watertight 可能抛异常；报告不应因此中断。"""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def topology_metrics(mesh, max_faces=TOPOLOGY_MAX_FACES):
    """焊接后网格的真实拓扑指标（STL 三角形汤不能直接拿来判水密）。

    超过 ``TOPOLOGY_MAX_FACES`` 才降级为 skipped；正常高精度手办模型必须
    给出真实边界/非流形计数，不能让「面数多」被误报成拓扑不合格。
    """
    m = mesh
    if len(m.faces) == 0:
        return {"boundary_edges": 0, "nonmanifold_edges": 0, "shared_edges": 0,
                "watertight_indexed": False, "empty": True}
    if len(m.faces) > max_faces:
        return {"skipped": f"faces>{max_faces}"}
    f = np.asarray(m.faces, dtype=np.int64)
    pairs = np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    lo, hi = np.minimum(pairs[:, 0], pairs[:, 1]), np.maximum(pairs[:, 0], pairs[:, 1])
    # 顶点对编码成单个 int64，一维 unique 比 (N,2) 的逐行唯一化快一个数量级；
    # stride 取最大顶点 id+1 保证无碰撞，坐标量级远小于 2^63。
    keys = lo * (int(f.max()) + 1) + hi
    _, counts = np.unique(keys, return_counts=True)
    return {
        "boundary_edges": int((counts == 1).sum()),
        "nonmanifold_edges": int((counts > 2).sum()),
        "shared_edges": int((counts == 2).sum()),
        "watertight_indexed": bool((counts == 2).all()),
        "unique_edges": int(len(counts)),
    }


def build_report(mesh, ref, ref_info, size=REPORT_GRID, extra=None):
    """生成一份可落盘的量化保真报告。

    用表面采样的真实投影轮廓 + 更细网格。
    ★ 指标口径：aspect_error_pct 是 aspect_correction **强制对齐之后**的值，
      几乎必然为 0，属于「变换是否执行成功」的自检，不是相似度证据；
      aspect_error_before_pct 才记录校正前的真实偏差。两者都写进报告并显式
      标注 aspect_error_is_evidence=False，避免下游把它当保真指标。
    """
    sil, geom = silhouette(mesh, size=size, accurate=True)
    # 报告网格变细后，参考掩膜也要用同一网格重算，否则两边尺度不一致。
    # ref_info 可能来自内存构造（无文件路径），此时直接对已有掩膜做最近邻重采样。
    if ref_info.get("grid") != size:
        src = ref_info.get("reference")
        if src and os.path.isfile(src):
            ref, ref_info = reference_mask(src, size=size)
        else:
            ref = np.asarray(Image.fromarray((ref * 255).astype("uint8"))
                             .resize((size, size), Image.NEAREST)) > 127
            ref_info = dict(ref_info, grid=size)
    score = iou(sil, ref)
    v = _finite_rows(mesh.vertices)
    span = (v.max(axis=0) - v.min(axis=0)) if len(v) else np.zeros(3, dtype=np.float64)
    aspect = float(span[0] / max(span[2], 1e-9))
    target = float(ref_info.get("aspect", 1.0))
    # 校正前的宽高比来自 align_mesh 记录的变换详情；没有对齐时该项为 null。
    correction = (extra or {}).get("aspect_correction") or {}
    before_aspect = correction.get("aspect_before")
    before_err = (round(abs(float(before_aspect) - target) / max(target, 1e-9) * 100, 2)
                  if before_aspect is not None else None)
    report = {
        "reference": ref_info.get("reference"),
        "reference_image_size": ref_info.get("image_size"),
        "mask_method": ref_info.get("mask_method"),
        "silhouette_iou": round(score, 4),
        "silhouette_method": geom.get("method"),
        "eval_grid": size,
        "silhouette_samples": geom.get("samples"),
        "silhouette_seed": geom.get("seed"),
        "aspect_ratio": round(aspect, 4),
        "reference_aspect_ratio": round(target, 4),
        "aspect_error_pct": round(abs(aspect - target) / max(target, 1e-9) * 100, 2),
        "aspect_error_before_pct": before_err,
        "aspect_error_is_evidence": False,
        "aspect_error_note": "aspect_error_pct 由 aspect_correction 强制对齐，非保真证据；"
                             "真实偏差看 aspect_error_before_pct；相似度看 silhouette_iou",
        "extents_xyz": [round(float(x), 4) for x in span],
        "depth_height_ratio": round(float(span[1] / max(span[2], 1e-9)), 4),
        "surface_area": _safe_metric(lambda: round(float(mesh.area), 4)),
        "vertices": int(len(v)),
        "faces": int(len(mesh.faces)),
        "watertight": _safe_metric(lambda: bool(mesh.is_watertight), False),
        "winding_consistent": _safe_metric(lambda: bool(mesh.is_winding_consistent), False),
    }
    report.update(topology_metrics(mesh))
    if extra:
        # ★ 核心指标只能由本函数计算，调用方传入的 extra 不得覆盖（防止
        #   报告被「喂」一个好看的 IoU）。冲突项记录下来便于审计。
        protected = frozenset({
            "silhouette_iou", "eval_grid", "aspect_ratio", "reference_aspect_ratio",
            "aspect_error_pct", "aspect_error_before_pct", "vertices", "faces",
            "watertight", "winding_consistent", "surface_area", "extents_xyz",
            "depth_height_ratio", "boundary_edges", "nonmanifold_edges",
            "shared_edges", "watertight_indexed", "silhouette_method"})
        conflicts = [k for k in extra
                     if k in protected and k in report and extra[k] != report[k]]
        report.update({k: v for k, v in extra.items() if k not in conflicts})
        if conflicts:
            report["extra_overrides_ignored"] = sorted(conflicts)
    return report


@lru_cache(maxsize=32)
def _file_sha256(path, mtime_ns, size):
    """按 (路径, mtime, 大小) 缓存哈希；同一次转换写两次报告不会重复读 37MB。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _sha256_if_exists(path):
    try:
        st = os.stat(path)
        return _file_sha256(os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except (OSError, TypeError):
        return None


def save_report(report, path):
    """统一写报告：补齐 schema 版本、UTC 时间、输入哈希与指标口径字典。

    哈希让「哪张参考图 / 哪个 STL 对应这份指标」可事后复核，避免产物被覆盖后
    报告仍指向旧文件而无法察觉。

    R40：这些字段是**由本模块从常量/磁盘推导的事实**，不是调用方可注入的
    配置。旧实现一律 ``setdefault``：报告里若残留上次运行的值或被手写塞入
    ``'FAKE_OLD_INPUT'``，假哈希会原样落盘（实证），``schema_version`` /
    ``metric_dictionary`` 同理可被降级或换成假口径；源文件已移走时哈希字段
    又被静默省略，读报告的人无法区分「没算」与「算过但源文件丢了」。
    现强制以权威值覆盖，并把纠正项 / 不可验证项写进报告供审计；时间属于
    运行时上下文，仍允许调用方注入固定值以做复现性测试。
    """
    report = dict(report)
    unset = object()
    corrections = []
    unverifiable = []
    # schema 版本与指标口径是下游解析契约，只能由本模块决定。
    for key, value in (("schema_version", SCHEMA_VERSION),
                       ("metric_dictionary", METRIC_DICTIONARY)):
        old = report.get(key, unset)
        if old is not unset and old != value:
            corrections.append(key)
        report[key] = value
    report.setdefault("generated_at_utc",
                      datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for src_key, out_key in (("input_mesh", "input_mesh_sha256"),
                             ("reference", "reference_image_sha256"),
                             ("mesh", "mesh_sha256")):
        candidate = report.get(src_key)
        if not (isinstance(candidate, str) and candidate):
            continue  # 内存构造的报告没有源文件路径，不凭空造字段
        digest = _sha256_if_exists(candidate)
        old = report.get(out_key, unset)
        if digest:
            if old is not unset and old != digest:
                corrections.append(out_key)
            report[out_key] = digest
        else:
            if old is not unset and old is not None:
                corrections.append(out_key)
            report[out_key] = None
            unverifiable.append({"source": src_key, "field": out_key,
                                 "path": candidate,
                                 "reason": "源文件不存在或不可读，哈希无法核验"})
    if corrections:
        report["metadata_corrections"] = sorted(set(corrections))
    else:
        report.pop("metadata_corrections", None)
    if unverifiable:
        report["source_hashes_unverifiable"] = unverifiable
    else:
        report.pop("source_hashes_unverifiable", None)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------- 3D 输入门禁
def _front_asymmetry(path):
    """左右镜像差，复刻 fig.check_front_view 的判据（不依赖 fig.py）。"""
    im = _load_rgb(path).convert("L").resize((160, 240))
    a = np.asarray(im, dtype=np.float64)
    left, right = a[:, :80], a[:, 80:][:, ::-1]
    return float(np.abs(left - right).mean() / 255.0)


def validate_3d_input(path, max_asymmetry=0.12, max_edge_contact=0.02,
                      max_foreground=0.60, min_foreground=0.03,
                      min_component_ratio=0.75, max_lowsat=0.30):
    """在把图送进 3D 重建**之前**拦截不合格输入。

    这是 STL 链路唯一的前置门禁：图生 3D 会把整张图都重建成几何，
    躺姿 / 带场景 / 主体贴边 / 抠图碎裂的输入无论如何后处理都救不回来。

    返回 (是否通过, 指标, 拒绝原因列表, 警告列表)。
    ★ 门禁本身不允许抛异常：图不存在/解码失败/全白无主体时返回结构化拒绝，
      上游据此给出可读提示，而不是把栈打到用户面前。
    """
    try:
        ref, info = reference_mask(path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        return False, {"image": os.path.abspath(path), "error": str(exc)}, \
            [f"参考图不可用：{exc}"], []
    if info.get("empty_mask") or not bool(ref.any()):
        return False, {"image": os.path.abspath(path), "mask_method": info["mask_method"],
                       "foreground_ratio": info["foreground_ratio"], "empty_mask": True}, \
            ["参考图未检出主体（全白/全黑/纯透明），不能用于 3D 重建"], []
    arr = np.asarray(_load_rgb(path)).astype(np.float32) / 255.0
    mx, mn = arr.max(axis=2), arr.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    lowsat = float(((sat < 0.18) & (mx > 0.15) & (mx < 0.80)).mean())
    asym = _front_asymmetry(path)
    metrics = {
        "image": os.path.abspath(path),
        "mask_method": info["mask_method"],
        "foreground_ratio": info["foreground_ratio"],
        "edge_contact_ratio": info["edge_contact_ratio"],
        "kept_component_ratio": info["kept_component_ratio"],
        "aspect": round(info["aspect"], 4),
        "front_asymmetry": round(asym, 4),
        "lowsat_bg_ratio": round(lowsat, 4),
        "image_size": info["image_size"],
    }
    reasons, warnings = [], []
    if asym > max_asymmetry:
        reasons.append(f"非正面/躺姿：左右不对称度 {asym:.3f} > {max_asymmetry}")
    if info["edge_contact_ratio"] > max_edge_contact:
        reasons.append(f"主体贴边（可能被裁切/背景连成一片）：{info['edge_contact_ratio']:.3f}")
    if info["foreground_ratio"] > max_foreground:
        reasons.append(f"前景占比 {info['foreground_ratio']:.1%} 过大，疑似背景被当成主体")
    if info["foreground_ratio"] < min_foreground:
        reasons.append(f"前景占比 {info['foreground_ratio']:.1%} 过小，主体可能丢失")
    if info["kept_component_ratio"] < min_component_ratio:
        reasons.append(f"抠图碎裂，仅保留 {info['kept_component_ratio']:.1%} 主体连通块")
    if info["mask_method"] == "color_fallback":
        warnings.append("rembg 不可用，退化到颜色判据，掩膜不可靠")
    if lowsat > max_lowsat:
        warnings.append(f"低饱和灰背景占比 {lowsat:.1%}，建议重出图")
    return (not reasons), metrics, reasons, warnings


# ---------------------------------------------------------------- 可复现验证
def save_comparison(ref, sil, path, imported_sil=None):
    """输出参考轮廓 / 网格轮廓叠加图，供人工复核（红=参考，绿=模型，黄=重合）。"""
    # 展示时统一翻回「头在上」
    ref, sil = ref[::-1], sil[::-1]
    overlap = ref & sil
    rgb = np.zeros((ref.shape[0], ref.shape[1], 3), dtype=np.uint8)
    rgb[..., 0] = np.where(ref, 190, 0)
    rgb[..., 1] = np.where(sil, 190, 0)
    rgb[..., 2] = np.where(overlap, 90, 0)
    if imported_sil is not None:
        # 未对齐的原始轮廓用暗蓝描边，便于看出朝向错在哪
        ndimage = _ndimage()
        imp = imported_sil[::-1]
        edge = imp ^ ndimage.binary_erosion(imp, iterations=2)
        rgb[..., 2] = np.maximum(rgb[..., 2], np.where(edge, 110, 0).astype(np.uint8))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.fromarray(rgb).save(path)
    return path


def verify(mesh_path, ref_path, comparison=None, crop=False):
    """只读验证：给出「导入态 -> 参考对齐后」的轮廓 IoU 与完整报告。"""
    import trimesh
    mesh = trimesh.load(mesh_path, force="mesh", process=False)
    ref, info = reference_mask(ref_path)
    imported_sil = silhouette(mesh, accurate=True)[0]
    aligned, detail = align_mesh(mesh, ref, info, crop=crop)
    final_sil = silhouette(aligned, accurate=True)[0]
    report = build_report(aligned, ref, info)
    report.update({
        "mesh": os.path.abspath(mesh_path),
        "iou_as_imported": detail["iou_as_imported"],
        "iou_after_orientation": detail["iou_after_orientation"],
        "iou_after_aspect": detail["iou_after_aspect"],
        "iou_final": detail["iou_final"],
        "rotation": detail["rotation"],
        "front_back_resolution": detail.get("front_back_resolution"),
        "crop": detail["crop"],
        "crop_requested": crop,
    })
    if comparison:
        save_comparison(ref, final_sil, comparison, imported_sil)
        report["comparison"] = os.path.abspath(comparison)
    return report


def save_before_after(ref, before_sil, after_sil, path):
    """三联对比图：参考掩膜 / 修复前轮廓叠加 / 修复后轮廓叠加。"""
    size = ref.shape[0]
    panels = []
    for sil in (ref, before_sil, after_sil):
        rgb = np.zeros((size, size, 3), dtype=np.uint8)
        # 内部约定第 0 行 = -Z（脚底），展示时上下翻转回「头在上」的观感
        ref_v, sil_v = ref[::-1], sil[::-1]
        if sil is ref:
            rgb[..., 0] = np.where(ref_v, 200, 0)
            rgb[..., 1] = np.where(ref_v, 200, 0)
        else:
            rgb[..., 0] = np.where(ref_v, 175, 0)
            rgb[..., 1] = np.where(sil_v, 175, 0)
            rgb[..., 2] = np.where(ref_v & sil_v, 90, 0)
        panels.append(rgb)
    out = Image.new("RGB", (size * 3 + 24, size + 28), (24, 26, 30))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(out)
    for i, (panel, title) in enumerate(zip(panels, (
            "REFERENCE MASK", "BEFORE / original STL", "AFTER / repaired STL"))):
        out.paste(Image.fromarray(panel), (i * (size + 12), 24))
        draw.text((i * (size + 12) + 4, 6), title, fill=(230, 232, 236))
    draw.text((4, size + 26),
              "red = reference   green = mesh   yellow = overlap",
              fill=(150, 155, 165))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    out.save(path)
    return path


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="STL 链路参考图保真：门禁 + 验证")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("gate", help="检查图片能否作为 3D 重建输入")
    p.add_argument("image")
    p = sub.add_parser("verify", help="量化网格与参考图的轮廓一致性")
    p.add_argument("mesh")
    p.add_argument("reference")
    p.add_argument("--comparison", default=None)
    p.add_argument("--json", default=None)
    p.add_argument("--crop", action="store_true")
    p = sub.add_parser("compare", help="生成修复前/后轮廓叠加对比图")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "compare":
        import trimesh
        ref, _ = reference_mask(a.reference)
        before = silhouette(trimesh.load(a.before, force="mesh", process=False), accurate=True)[0]
        after = silhouette(trimesh.load(a.after, force="mesh", process=False), accurate=True)[0]
        save_before_after(ref, before, after, a.out)
        print(json.dumps({
            "reference": os.path.abspath(a.reference),
            "iou_before": round(iou(before, ref), 4),
            "iou_after": round(iou(after, ref), 4),
            "comparison": os.path.abspath(a.out),
        }, ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "gate":
        ok, metrics, reasons, warnings = validate_3d_input(a.image)
        print(json.dumps({"pass": ok, "metrics": metrics,
                          "reasons": reasons, "warnings": warnings},
                         ensure_ascii=False, indent=2))
        return 0 if ok else 2
    rep = verify(a.mesh, a.reference, a.comparison, a.crop)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if a.json:
        save_report(rep, a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
