# -*- coding: utf-8 -*-
"""STL 链路保真回归测试。

    <项目 venv>\\Scripts\\python.exe -W error::ResourceWarning -m unittest discover -s tests -p "test_mesh_fidelity.py" -v
    （本机：C:\\Users\\xukunhang\\.venvs\\cadquery\\Scripts\\python.exe）

必需依赖：numpy、Pillow、trimesh（缺 trimesh 时相关用例 SKIP，不报 ERROR）；
scipy 为**可选**依赖：缺失时 mesh_fidelity 自动走逐像素等价的 numpy 降级，
由 TestOptionalScipy 回归保护。项目样本缺失的用例同样自动跳过，保证换机可跑。
"""
from __future__ import annotations

import os
import sys
import unittest
import zipfile
import re

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mesh_fidelity as mf  # noqa: E402


def _require_trimesh():
    """trimesh 是 3D 链路的必需依赖：缺失时用 SKIP 表达，而不是 9 个 ERROR。

    与 scipy 区别开：scipy 可选（有 numpy 降级），trimesh 不可降级。
    """
    from importlib import import_module
    try:
        return import_module("trimesh")
    except ImportError as exc:
        raise unittest.SkipTest(f"缺必需依赖 trimesh：{exc}") from exc


BAD_REF = os.path.join(ROOT, "ComfyUI", "output", "fig_edit_cfbf17969f53_00001_.png")
BAD_GLB = os.path.join(ROOT, "ComfyUI", "output", "figure_3d_47ec518d6886_00001_.glb")
BAD_STL_OLD = r"I:\AI\最终成品\figure_3d_47ec518d6886_00001_.stl"
BAD_STL_NEW = os.path.join(ROOT, "print_ready", "_verify",
                           "figure_3d_47ec518d6886_00001_.stl")
CLEAN_REF = r"I:\AI\最终成品\源图_分离后.png"
E2E_REF = os.path.join(ROOT, "ComfyUI", "output",
                       "figure_3d_16a672ab0e6d_00001__3d_input.png")
E2E_STL = os.path.join(ROOT, "print_ready", "_verify", "e2e",
                       "figure_3d_16a672ab0e6d_00001_.stl")
CONTROL_3MF = os.path.join(ROOT, "print_ready", "_verify", "control", "手办模型.3mf")
CONTROL_STL = os.path.join(ROOT, "print_ready", "_verify", "control", "手办模型.stl")
TARGET_REF = os.path.join(ROOT, "ComfyUI", "output",
                          "figure_3d_5b299f5bbb1a_00001__3d_input.png")
TARGET_STL = os.path.join(ROOT, "print_ready", "_verify2", "final2", "target_final2.stl")


def _exists(*paths):
    return all(os.path.isfile(p) for p in paths)


class TestInputGate(unittest.TestCase):
    def test_reclining_scene_is_rejected(self):
        """沙发躺姿 + 室内场景：必须在送进 3D 重建前被拦下。"""
        if not _exists(BAD_REF):
            self.skipTest("缺少失败样本参考图")
        ok, metrics, reasons, _ = mf.validate_3d_input(BAD_REF)
        self.assertFalse(ok)
        self.assertTrue(any("正面" in r for r in reasons))
        self.assertGreater(metrics["front_asymmetry"], 0.12)

    def test_clean_standing_is_accepted(self):
        if not _exists(CLEAN_REF):
            self.skipTest("缺少干净站立样本")
        ok, _, reasons, _ = mf.validate_3d_input(CLEAN_REF)
        self.assertTrue(ok, reasons)


class TestAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # docstring 承诺「换机可跑」：样本缺失必须整体跳过，而不是抛 FileNotFoundError
        if not _exists(BAD_REF, BAD_GLB):
            raise unittest.SkipTest("缺少对齐测试样本")
        trimesh = _require_trimesh()
        cls.ref, cls.info = mf.reference_mask(BAD_REF)
        # 该样本是复杂背景：缺 rembg/scipy 时会退化到 color_fallback，
        # 掩膜口径与 rembg 版本不同，IoU 断言失去可比性 -> 明确 SKIP 而非 FAIL。
        if cls.info["mask_method"] == "color_fallback":
            raise unittest.SkipTest("复杂背景样本需要 rembg/scipy，当前环境已降级到 color_fallback")
        cls.mesh = trimesh.load(BAD_GLB, force="mesh", process=False)

    def test_reference_z_up_convention(self):
        """内部掩膜必须翻成 +Z 朝上，否则会选出倒立朝向。"""
        self.assertTrue(self.info.get("z_up_flipped"))

    def test_orientation_and_aspect_improve_iou(self):
        aligned, detail = mf.align_mesh(self.mesh, self.ref, self.info, crop=False)
        self.assertGreaterEqual(detail["iou_after_orientation"],
                                detail["iou_as_imported"] + 0.20)
        self.assertGreaterEqual(detail["iou_after_aspect"], 0.68)
        rep = mf.build_report(aligned, self.ref, self.info)
        self.assertLessEqual(rep["aspect_error_pct"], 1.0)

    def test_crop_removes_out_of_silhouette_geometry(self):
        aligned, detail = mf.align_mesh(self.mesh, self.ref, self.info, crop=True)
        self.assertIsNotNone(detail["crop"])
        self.assertLess(len(aligned.faces), len(self.mesh.faces))
        self.assertGreater(detail["iou_final"], 0.68)


class TestDeliverables(unittest.TestCase):
    def test_fixed_stl_beats_original(self):
        if not _exists(BAD_STL_OLD, BAD_STL_NEW, BAD_REF):
            self.skipTest("缺少修复前后 STL")
        trimesh = _require_trimesh()
        ref, ref_info = mf.reference_mask(BAD_REF)
        if ref_info["mask_method"] == "color_fallback":
            self.skipTest("复杂背景样本需要 rembg/scipy，当前环境掩膜口径已变化")
        before = mf.iou(mf.silhouette(trimesh.load(BAD_STL_OLD, force="mesh", process=False))[0], ref)
        after = mf.iou(mf.silhouette(trimesh.load(BAD_STL_NEW, force="mesh", process=False))[0], ref)
        self.assertGreater(after, before + 0.20)
        self.assertGreater(after, 0.65)

    def test_e2e_stl_passes_gate(self):
        if not _exists(E2E_STL, E2E_REF):
            self.skipTest("缺少端到端产物")
        trimesh = _require_trimesh()
        ref, _ = mf.reference_mask(E2E_REF)
        score = mf.iou(mf.silhouette(trimesh.load(E2E_STL, force="mesh", process=False))[0], ref)
        self.assertGreater(score, 0.65)

    def test_final_target_stl_is_watertight_and_faithful(self):
        """最终目标角色 STL：必须水密、无非流形边，且轮廓 IoU 达标。"""
        if not _exists(TARGET_STL, TARGET_REF):
            self.skipTest("缺少最终目标角色产物")
        trimesh = _require_trimesh()
        m = trimesh.load(TARGET_STL, force="mesh", process=True)
        topo = mf.topology_metrics(m)
        self.assertTrue(m.is_watertight)
        self.assertEqual(topo["boundary_edges"], 0)
        self.assertEqual(topo["nonmanifold_edges"], 0)
        ref, _ = mf.reference_mask(TARGET_REF)
        score = mf.iou(mf.silhouette(m, accurate=True)[0], ref)
        self.assertGreater(score, 0.80)

    def test_3mf_and_stl_share_millimeter_coordinates(self):
        if not _exists(CONTROL_3MF, CONTROL_STL):
            self.skipTest("缺少对照 3MF/STL")
        trimesh = _require_trimesh()
        xml = zipfile.ZipFile(CONTROL_3MF).read("3D/3dmodel.model").decode("utf-8", "replace")
        self.assertIn('unit="millimeter"', xml)
        vs = np.array([[float(x), float(y), float(z)] for x, y, z in re.findall(
            r'x="([-0-9.]+)" y="([-0-9.]+)" z="([-0-9.]+)"', xml)], dtype=float)
        stl = trimesh.load(CONTROL_STL, force="mesh", process=False)
        v = np.asarray(stl.vertices)
        ratio = (vs.max(0) - vs.min(0)) / (v.max(0) - v.min(0))
        np.testing.assert_allclose(ratio, 1.0, atol=0.02)


class TestRobustness(unittest.TestCase):
    """边界情况回归：这些用例在修复前会直接抛异常或给出错误指标。"""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _png(self, name):
        return os.path.join(self.tmp.name, name)

    def test_exif_orientation_is_applied(self):
        from PIL import Image
        arr = np.zeros((400, 200, 3), dtype=np.uint8) + 255
        arr[60:340, 70:130] = 0
        ex = Image.Exif()
        ex[274] = 6  # 旋转 90°
        p = self._png("exif.png")
        Image.fromarray(arr).save(p, exif=ex)
        _, info = mf.reference_mask(p)
        self.assertEqual(info["image_size"], [400, 200])

    def test_rgba_transparency_is_composited_on_white(self):
        from PIL import Image
        arr = np.zeros((400, 200, 4), dtype=np.uint8)
        arr[60:340, 70:130] = [0, 0, 0, 255]
        p = self._png("rgba.png")
        Image.fromarray(arr).save(p)
        _, info = mf.reference_mask(p)
        self.assertLess(info["foreground_ratio"], 0.35)

    def test_missing_corrupt_and_blank_images_are_rejected(self):
        from PIL import Image
        blank = self._png("blank.png")
        Image.new("RGB", (128, 128), (255, 255, 255)).save(blank)
        broken = self._png("broken.png")
        with open(broken, "wb") as f:
            f.write(b"not-a-png")
        for p in (self._png("missing.png"), broken, blank):
            ok, _, reasons, _ = mf.validate_3d_input(p)
            self.assertFalse(ok)
            self.assertTrue(reasons)

    def test_empty_and_nonfinite_mesh_do_not_crash(self):
        trimesh = _require_trimesh()
        empty = trimesh.Trimesh(vertices=np.zeros((0, 3)),
                                faces=np.zeros((0, 3), int), process=False)
        for accurate in (False, True):
            sil, _ = mf.silhouette(empty, size=64, accurate=accurate)
            self.assertFalse(sil.any())
        self.assertFalse(mf.topology_metrics(empty)["watertight_indexed"])
        v = np.array([[0, 0, 0], [1, 0, 1], [0, 0, 2],
                      [np.nan, 0, 1], [np.inf, 0, 1]], dtype=float)
        nan_mesh = trimesh.Trimesh(vertices=v, faces=np.array([[0, 1, 2]]),
                                   process=False)
        self.assertTrue(mf.silhouette(nan_mesh, size=64)[0].any())

    def test_visual_hull_matches_reference_implementation(self):
        rng = np.random.default_rng(11)
        occ = rng.random((128, 128)) < 0.02
        got = mf._visual_hull(occ)
        gap = max(2, int(128 * 0.06))

        def fill(mat):
            out = np.zeros_like(mat)
            for i in range(mat.shape[0]):
                xs = np.where(mat[i])[0]
                if not len(xs):
                    continue
                start = prev = int(xs[0])
                for x in xs[1:]:
                    if x - prev > gap:
                        out[i, start:prev + 1] = True
                        start = x
                    prev = x
                out[i, start:prev + 1] = True
            return out

        np.testing.assert_array_equal(got, fill(occ) & fill(occ.T).T)

    def test_crop_vote_is_not_identical_to_centroid(self):
        """四点投票应比单点重心保留更多跨边界细长面。"""
        if not _exists(BAD_REF, BAD_GLB):
            self.skipTest("缺少对齐测试样本")
        trimesh = _require_trimesh()
        ref, info = mf.reference_mask(BAD_REF)
        mesh = trimesh.load(BAD_GLB, force="mesh", process=False)
        aligned, _ = mf.align_mesh(mesh, ref, info, crop=False)
        projector = mf.make_projector(aligned)
        sil = mf.silhouette(aligned, projector, accurate=True)[0]
        moved, _ = mf.align_reference_mask(ref, sil)
        _, legacy = mf.crop_to_reference(aligned, moved, projector=projector,
                                         mode="centroid")
        _, voted = mf.crop_to_reference(aligned, moved, projector=projector)
        self.assertEqual(voted["mode"], "vertices")
        self.assertGreater(voted["faces_after"], legacy["faces_after"])


class TestReportContract(unittest.TestCase):
    def test_core_metrics_cannot_be_overridden(self):
        trimesh = _require_trimesh()
        if not _exists(TARGET_REF, TARGET_STL):
            self.skipTest("缺少目标产物")
        mesh = trimesh.load(TARGET_STL, force="mesh", process=True)
        ref, info = mf.reference_mask(TARGET_REF, size=128)
        rep = mf.build_report(mesh, ref, info, size=128,
                              extra={"silhouette_iou": 0.99, "faces": 1,
                                     "note": "allowed"})
        self.assertLess(rep["silhouette_iou"], 0.99)
        self.assertGreater(rep["faces"], 1)
        self.assertEqual(rep["note"], "allowed")
        self.assertIn("silhouette_iou", rep["extra_overrides_ignored"])

    def test_aspect_error_is_flagged_as_non_evidence(self):
        trimesh = _require_trimesh()
        if not _exists(TARGET_REF, TARGET_STL):
            self.skipTest("缺少目标产物")
        mesh = trimesh.load(TARGET_STL, force="mesh", process=True)
        ref, info = mf.reference_mask(TARGET_REF, size=128)
        rep = mf.build_report(mesh, ref, info, size=128, extra={
            "aspect_correction": {"aspect_before": info["aspect"] * 1.2}})
        self.assertFalse(rep["aspect_error_is_evidence"])
        self.assertGreater(rep["aspect_error_before_pct"], 1.0)
        self.assertGreaterEqual(rep["silhouette_samples"], 200000)  # 采样下限
        self.assertLessEqual(rep["silhouette_samples"], 1000000)
        self.assertEqual(rep["silhouette_seed"], mf.SAMPLE_SEED)

    def test_save_report_adds_schema_hash_and_dictionary(self):
        import json
        import tempfile
        if not _exists(TARGET_REF):
            self.skipTest("缺少参考图")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rep.json")
            mf.save_report({"reference": TARGET_REF}, p)
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        self.assertEqual(data["schema_version"], mf.SCHEMA_VERSION)
        self.assertEqual(len(data["reference_image_sha256"]), 64)
        self.assertIn("aspect_error_pct", data["metric_dictionary"])
        self.assertIn("generated_at_utc", data)

    def test_verdict_strict_watertight(self):
        import convert_3d as c
        good = {"final_mesh": {"silhouette_iou": 0.83, "watertight_indexed": True,
                               "boundary_edges": 0, "nonmanifold_edges": 0},
                "aspect_error_pct": 0.0}
        bad = dict(good, final_mesh=dict(good["final_mesh"],
                                         watertight_indexed=False,
                                         boundary_edges=10))
        self.assertTrue(c.build_verdict(good, 0.55, True)["pass"])
        self.assertFalse(c.build_verdict(bad, 0.55, True)["pass"])
        self.assertTrue(c.build_verdict(bad, 0.55, False)["pass"])

    def test_cli_argument_ranges(self):
        import argparse
        import convert_3d as c
        base = dict(height=150.0, scale=1.0, base=0.03, hollow=0.0,
                    min_iou=0.55, voxel_mm=0.25, repair_max_iou_drop=0.02,
                    decimate=0, smooth=0, pitch=0.005, to=["stl"])
        self.assertEqual(c.validate_args(argparse.Namespace(**base)), [])
        for override in ({"height": -1}, {"voxel_mm": -1}, {"min_iou": 2},
                         {"base": 5}, {"smooth": -3}, {"to": []}):
            self.assertTrue(c.validate_args(argparse.Namespace(**dict(base, **override))))

    def test_print_defaults_match_convert_defaults(self):
        """fig.py 与 convert_3d.py 的共享默认值不得静默漂移。"""
        import ast
        import re
        with open(os.path.join(ROOT, "fig.py"), encoding="utf-8") as f:
            fig_src = f.read()
        block = re.search(r"PRINT_DEFAULTS\s*=\s*\{[^}]+\}", fig_src).group(0)
        defaults = ast.literal_eval(block.split("=", 1)[1].strip())
        with open(os.path.join(ROOT, "convert_3d.py"), encoding="utf-8") as f:
            conv = f.read()
        for key, flag in (("smooth", "smooth"), ("voxel_mm", "voxel-mm"),
                          ("min_iou", "min-iou"),
                          ("repair_max_iou_drop", "repair-max-iou-drop")):
            m = re.search(r'add_argument\("--' + flag + r'"[^\)]*default=([\d.]+)', conv)
            self.assertIsNotNone(m, flag)
            self.assertAlmostEqual(float(m.group(1)), float(defaults[key]))


class TestOptionalScipy(unittest.TestCase):
    """R25：scipy 是可选依赖，缺失时 numpy 降级须与主路径等价或保守跳过。"""

    @staticmethod
    def _mask():
        rng = np.random.default_rng(11)
        m = rng.random((37, 41)) < 0.18
        m[10:22, 12:28] = True       # 明确的主体 + 随机碎片
        return m

    def test_numpy_ndimage_matches_scipy_pixelwise(self):
        try:
            from scipy import ndimage as sn
        except ImportError:
            self.skipTest("本环境无 scipy，无法做逐像素对照")
        m, impl = self._mask(), mf._NumpyNdimage
        full = np.ones((3, 3), dtype=bool)
        for conn in (1, 2):
            st = impl.generate_binary_structure(2, conn)
            se = sn.generate_binary_structure(2, conn)
            self.assertTrue(np.array_equal(st, se))
            l1, n1 = impl.label(m, structure=st)
            l2, n2 = sn.label(m, structure=se)
            self.assertEqual(n1, n2)
            self.assertTrue(np.array_equal(l1, l2))
            self.assertTrue(np.array_equal(impl.sum(m, l1, range(1, n1 + 1)),
                                           sn.sum(m, l2, range(1, n2 + 1))))
        for it in (1, 2):
            self.assertTrue(np.array_equal(
                impl.binary_dilation(m, iterations=it, structure=full),
                sn.binary_dilation(m, iterations=it, structure=full)))
            self.assertTrue(np.array_equal(
                impl.binary_erosion(m, iterations=it, structure=full),
                sn.binary_erosion(m, iterations=it, structure=full)))
            self.assertTrue(np.array_equal(
                impl.binary_closing(m, structure=full, iterations=it),
                sn.binary_closing(m, structure=full, iterations=it)))
        self.assertTrue(np.array_equal(impl.binary_fill_holes(m),
                                       sn.binary_fill_holes(m)))
        lab, n = sn.label(m, structure=sn.generate_binary_structure(2, 2))
        sizes = sn.sum(m, lab, range(1, n + 1))
        expected = lab == (int(np.argmax(sizes)) + 1)
        self.assertTrue(np.array_equal(mf._largest_component(m), expected))
        # 最近邻仿射：多组缩放/平移下都必须逐像素等价（含坐标越界的边界行）
        src = m.astype(np.float32)
        for f, dx, dy in ((0.90, -12, 6), (1.0, 0, 0), (1.10, 12, -6)):
            size = 47
            center = (size - 1) / 2.0
            off = [center * (1 - 1 / f) - dx / f,
                   center * (1 - 1 / f) - dy / f]
            matrix = np.diag([1 / f, 1 / f])
            expected_a = sn.affine_transform(
                src, matrix=matrix, offset=off,
                output_shape=(size, size), order=0)
            got_a = impl.affine_transform(
                src, matrix, off, (size, size), order=0)
            self.assertTrue(np.array_equal(got_a, expected_a),
                            f"affine f={f} dx={dx} dy={dy} 不等价")

    def test_core_paths_run_without_scipy(self):
        """模拟无 scipy：参考图提取与裁剪对齐不得抛 ModuleNotFoundError。"""
        import tempfile
        from unittest import mock
        from PIL import Image
        m = self._mask()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ref.png")
            Image.fromarray((~m * 255).astype(np.uint8)).save(p)
            mf._ndimage.cache_clear()
            with mock.patch.dict(sys.modules,
                                 {"scipy": None, "scipy.ndimage": None}):
                self.assertIsInstance(mf._ndimage(), mf._NumpyNdimage)
                mask, info = mf.reference_mask(p, size=64)
                self.assertEqual(mask.shape, (64, 64))
                self.assertFalse(info.get("empty_mask", False))
                aligned, ainfo = mf.align_reference_mask(mask, mask, size=64)
                self.assertNotIn("degraded_no_scipy", ainfo)
                self.assertIsInstance(ainfo["iou_for_crop"], float)
                self.assertEqual(len(ainfo["offset_px"]), 2)
                self.assertEqual(aligned.shape, (64, 64))
            mf._ndimage.cache_clear()

    def test_silhouette_without_scipy(self):
        """无 scipy 时轮廓栅格化（闭运算 + 填洞）仍可用且结果不退化。"""
        import contextlib
        from unittest import mock
        try:
            trimesh = _require_trimesh()
            from scipy import ndimage  # noqa: F401
            has_scipy = True
        except ImportError:
            has_scipy = False
        if not has_scipy:
            try:
                trimesh = _require_trimesh()  # noqa: F401
            except ImportError:
                self.skipTest("缺 trimesh，无法构造测试网格")
        mesh = trimesh.creation.box(extents=(1.0, 0.6, 2.0))
        proj = mf.make_projector(mesh, size=64)
        baseline = mf.rasterize_silhouette(mesh, proj, samples=20000)
        mf._ndimage.cache_clear()
        blocker = (mock.patch.dict(sys.modules,
                                   {"scipy": None, "scipy.ndimage": None})
                   if has_scipy else contextlib.nullcontext())
        with blocker:
            self.assertIsInstance(mf._ndimage(), mf._NumpyNdimage)
            degraded = mf.rasterize_silhouette(mesh, proj, samples=20000)
        mf._ndimage.cache_clear()
        self.assertTrue(baseline.any())
        self.assertTrue(np.array_equal(baseline, degraded))


class TestR40ReportProvenance(unittest.TestCase):
    """R40：报告里的溯源哈希 / schema / 指标口径必须由 save_report 权威生成。"""

    def _write(self, report):
        import json
        import tempfile
        d = tempfile.TemporaryDirectory(prefix="r40_")
        self.addCleanup(d.cleanup)
        p = os.path.join(d.name, "rep.json")
        mf.save_report(report, p)
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def _real_hash(self, path):
        return mf._sha256_if_exists(path)

    def test_r40_fake_hashes_are_recomputed(self):
        if not _exists(TARGET_REF):
            self.skipTest("缺少参考图")
        good = self._real_hash(TARGET_REF)
        data = self._write({
            "input_mesh": TARGET_REF, "reference": TARGET_REF,
            "mesh": TARGET_REF,
            "input_mesh_sha256": "FAKE_OLD_INPUT",
            "reference_image_sha256": "0" * 64,
            "mesh_sha256": "TAMPERED",
        })
        for key in ("input_mesh_sha256", "reference_image_sha256", "mesh_sha256"):
            self.assertEqual(data[key], good, key)
        self.assertEqual(sorted(data["metadata_corrections"]), sorted([
            "input_mesh_sha256", "reference_image_sha256", "mesh_sha256"]))
        self.assertNotIn("source_hashes_unverifiable", data)

    def test_r40_schema_and_dictionary_are_authoritative(self):
        data = self._write({"schema_version": "1.0",
                            "metric_dictionary": {"silhouette_iou": "伪造口径"}})
        self.assertEqual(data["schema_version"], mf.SCHEMA_VERSION)
        self.assertEqual(data["metric_dictionary"], mf.METRIC_DICTIONARY)
        self.assertIn("aspect_error_pct", data["metric_dictionary"])
        self.assertEqual(sorted(data["metadata_corrections"]),
                         ["metric_dictionary", "schema_version"])

    def test_r40_generated_at_utc_stays_injectable(self):
        # 时间是运行时上下文，不是本模块推导的事实；允许复现性测试固定它。
        fixed = "2020-01-01T00:00:00+00:00"
        data = self._write({"generated_at_utc": fixed})
        self.assertEqual(data["generated_at_utc"], fixed)
        self.assertNotIn("generated_at_utc", data.get("metadata_corrections", []))
        self.assertNotIn("metadata_corrections", data)

    def test_r40_missing_source_is_explicit_null_not_silent_omission(self):
        import json
        import tempfile
        d = tempfile.TemporaryDirectory(prefix="r40miss_")
        self.addCleanup(d.cleanup)
        ghost = os.path.join(d.name, "never_existed.glb")
        out = os.path.join(d.name, "rep.json")
        mf.save_report({"input_mesh": ghost,
                        "input_mesh_sha256": "STALE_FROM_OTHER_MACHINE"}, out)
        # 写出的必须是合法 JSON，不能因 None 变成 NaN 之类非法字面量
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("input_mesh_sha256", data)
        self.assertIsNone(data["input_mesh_sha256"])
        self.assertEqual(data["source_hashes_unverifiable"][0]["source"],
                         "input_mesh")
        self.assertIn("input_mesh_sha256", data["metadata_corrections"])

    def test_r40_clean_report_has_no_audit_noise(self):
        if not _exists(TARGET_REF):
            self.skipTest("缺少参考图")
        data = self._write({"input_mesh": TARGET_REF, "reference": TARGET_REF})
        self.assertNotIn("metadata_corrections", data)
        self.assertNotIn("source_hashes_unverifiable", data)
        self.assertEqual(data["reference_image_sha256"],
                         self._real_hash(TARGET_REF))
        self.assertEqual(data["schema_version"], mf.SCHEMA_VERSION)
        self.assertIn("generated_at_utc", data)

    def test_r40_real_final5_report_survives_rewrite(self):
        import json
        import tempfile
        src = os.path.join(ROOT, "print_ready", "_verify2", "final5",
                           "target_final5_fidelity.json")
        if not os.path.isfile(src):
            self.skipTest("缺少 final5 报告")
        with open(src, encoding="utf-8") as f:
            original = json.load(f)
        with tempfile.TemporaryDirectory(prefix="r40real_") as d:
            p = os.path.join(d, "rep.json")
            mf.save_report(dict(original), p)
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        for key in ("silhouette_iou", "final_mesh", "verdict",
                    "file_verification", "input_mesh_sha256",
                    "reference_image_sha256", "extents_xyz"):
            self.assertEqual(data[key], original[key], key)
        self.assertNotIn("metadata_corrections", data)
        self.assertNotIn("source_hashes_unverifiable", data)


class TestHighDetailTopology(unittest.TestCase):
    def test_two_million_face_model_is_evaluated_not_skipped(self):
        """0.15mm 高精度成品约 206 万面，旧上限 200 万会让报告缺拓扑判据。"""
        from types import SimpleNamespace
        faces = np.zeros((2_000_001, 3), dtype=np.int64)
        faces[:, 1] = 1
        faces[:, 2] = 2
        topo = mf.topology_metrics(SimpleNamespace(faces=faces))
        self.assertNotIn("skipped", topo)
        self.assertIn("watertight_indexed", topo)
        self.assertFalse(topo["watertight_indexed"])
        self.assertEqual(topo["nonmanifold_edges"], 3)

    def test_high_detail_reconstruction_defaults_are_active(self):
        """默认链路必须保持实测有效参数，不能只在测试命令里手动提精度。"""
        import fig
        wf = fig.build_3d_wf("reference.png")
        self.assertEqual(wf["7"]["inputs"]["steps"], 50)
        self.assertEqual(wf["8"]["inputs"]["octree_resolution"], 512)
        self.assertNotIn("31", wf)  # 不默认启用会破坏头脚/轴向的 solid remesh
        self.assertEqual(fig.PRINT_DEFAULTS["voxel_mm"], 0.15)

    def test_multiview_conditioning_is_wired_when_refs_given(self):
        """侧/背塌陷的正规修复是多视图条件；工作流必须真实接入 MultiView 节点。"""
        import fig
        wf = fig.build_3d_wf("front.png", mv_images={
            "front": "front.png", "left": "left.png",
            "back": "back.png", "right": "right.png"})
        self.assertEqual(wf["6"]["class_type"], "Hunyuan3Dv2ConditioningMultiView")
        self.assertEqual(wf["6"]["inputs"]["front"], ["13", 0])
        self.assertEqual(wf["6"]["inputs"]["back"], ["mv_clip_back", 0])
        self.assertEqual(wf["mv_load_back"]["inputs"]["image"], "back.png")
        self.assertEqual(wf["7"]["inputs"]["positive"], ["6", 0])

    def test_multiview_refs_reject_invalid_or_single_view(self):
        import fig
        with self.assertRaises(ValueError):
            fig.build_3d_wf("front.png", mv_images={"front": "a.png", "side": "b.png"})
        with self.assertRaises(ValueError):
            fig.build_3d_wf("front.png", mv_images={"front": "a.png"})
        with self.assertRaises(ValueError):
            fig.build_3d_wf("front.png", mv_images={"left": "a.png", "back": "b.png"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
