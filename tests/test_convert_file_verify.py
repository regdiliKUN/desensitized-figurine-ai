# -*- coding: utf-8 -*-
"""R27：主链路「导出后文件级复验闭环」的回归保护。

R26 的 verify_deliverable.py 只是旁路 CLI；本组用例验证 convert_3d.py
确实在导出 STL 后回读磁盘文件、把结论写进报告/清单，并且失败会影响退出码。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import numpy  # noqa: F401  - convert_3d 依赖，缺它时整组用例跳过
    import trimesh
    from PIL import Image
    import convert_3d as c
    import verify_deliverable as vd
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


def good_verdict(**extra):
    """R33：夹具 verdict 必须与 build_verdict 的固定契约一致。"""
    out = {"pass": True,
           "checks": dict.fromkeys(vd.VERDICT_KNOWN_CHECKS, True),
           "required_checks": list(vd.VERDICT_KNOWN_CHECKS),
           "evaluated_on": "final_mesh"}
    out.update(extra)
    return out


@unittest.skipUnless(HAS_DEPS, "缺 trimesh/numpy，主链路文件级复验不可用")
class TestExportedStlVerification(unittest.TestCase):

    @staticmethod
    def _box():
        return trimesh.creation.box(extents=(2.0, 3.0, 4.0))

    def _export(self, mesh, directory, name="m.stl"):
        path = os.path.join(directory, name)
        mesh.export(path)
        return path

    def test_good_box_passes_all_seven_checks(self):
        box = self._box()
        with tempfile.TemporaryDirectory() as d:
            path = self._export(box, d)
            memory = trimesh.load(path, force="mesh", process=True)
            fv = c.verify_exported_stl(path, memory)
        self.assertTrue(fv["pass"], str(fv))
        self.assertEqual(len(fv["checks"]), 7)
        self.assertTrue(all(fv["checks"].values()), str(fv["checks"]))
        self.assertGreater(fv["metrics"]["volume_signed"], 0)
        self.assertIn("verified_at_utc", fv)

    def test_main_chain_reports_connected_parts(self):
        """R28：主链路复验结果也要带连通块/退化面指标，单实体时无告警。"""
        box = self._box()
        with tempfile.TemporaryDirectory() as d:
            path = self._export(box, d)
            memory = trimesh.load(path, force="mesh", process=True)
            fv = c.verify_exported_stl(path, memory)
        self.assertEqual(fv["metrics"]["connected_parts"], 1)
        self.assertEqual(fv["metrics"]["floating_parts"], 0)
        self.assertEqual(fv["metrics"]["degenerate_faces"], 0)
        self.assertEqual(fv["warnings"], [])
        self.assertTrue(fv["pass"])

    def test_flipped_normals_are_rejected_by_main_chain(self):
        box = self._box()
        flipped = trimesh.Trimesh(vertices=box.vertices.copy(),
                                  faces=box.faces[:, [0, 2, 1]].copy(),
                                  process=False)
        with tempfile.TemporaryDirectory() as d:
            path = self._export(flipped, d)
            memory = trimesh.load(path, force="mesh", process=True)
            fv = c.verify_exported_stl(path, memory)
        self.assertFalse(fv["pass"])
        self.assertFalse(fv["checks"]["positive_volume"])
        self.assertFalse(fv["checks"]["closed_solid"])

    def test_open_mesh_is_rejected(self):
        box = self._box()
        opened = trimesh.Trimesh(vertices=box.vertices.copy(),
                                 faces=box.faces[:-1].copy(), process=False)
        with tempfile.TemporaryDirectory() as d:
            path = self._export(opened, d)
            memory = trimesh.load(path, force="mesh", process=True)
            fv = c.verify_exported_stl(path, memory)
        self.assertFalse(fv["pass"])
        self.assertFalse(fv["checks"]["welded_watertight"])

    def test_memory_mismatches_are_detected(self):
        """面数 / 未焊接顶点 / 尺寸三项与内存网格比对必须逐项生效。"""
        box = self._box()
        with tempfile.TemporaryDirectory() as d:
            path = self._export(box, d)
            welded = trimesh.load(path, force="mesh", process=True)
            raw = trimesh.load(path, force="mesh", process=False)
            scaled = welded.copy()
            scaled.apply_scale(1.5)
            fewer_faces = trimesh.Trimesh(vertices=box.vertices.copy(),
                                          faces=box.faces[:-1].copy(), process=False)
            fv_bad_faces = c.verify_exported_stl(path, fewer_faces)
            fv_raw = c.verify_exported_stl(path, raw)
            fv_scaled = c.verify_exported_stl(path, scaled)
        self.assertFalse(fv_bad_faces["checks"]["faces_match_memory"])
        self.assertFalse(fv_raw["checks"]["vertices_match_memory"])
        self.assertFalse(fv_scaled["checks"]["extents_match_memory"])

    def test_missing_or_broken_stl_is_a_readable_failure(self):
        with tempfile.TemporaryDirectory() as d:
            missing = os.path.join(d, "no_such.stl")
            fv = c.verify_exported_stl(missing, self._box())
            broken = os.path.join(d, "broken.stl")
            with open(broken, "wb") as handle:
                handle.write(b"not an stl file")
            fv_broken = c.verify_exported_stl(broken, self._box())
        self.assertIs(fv["pass"], False)
        self.assertIn("error", fv)
        self.assertIs(fv_broken["pass"], False)
        # 损坏网格会产生 NaN 体积/尺寸；复验结果本身仍必须是标准 JSON。
        for item in (fv, fv_broken):
            payload = json.dumps(item, ensure_ascii=False, allow_nan=False)
            self.assertIsInstance(json.loads(payload), dict)

    def test_missing_optional_dependency_is_skipped_not_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(c, "_file_verify", None):
                fv = c.verify_exported_stl(os.path.join(d, "x.stl"), self._box())
        self.assertIsNone(fv["pass"])
        self.assertTrue(fv["skipped"])
        self.assertIn("reason", fv)

    def test_r49_missing_geometry_dependency_is_classified_not_swallowed(self):
        """R46 把异常改成 RuntimeError 子类后，旧 ImportError 分支失效。"""
        self.assertFalse(issubclass(vd.MissingDependencyError, ImportError))
        self.assertIs(c._file_verify.MissingDependencyError,
                      vd.MissingDependencyError)
        missing = vd.MissingDependencyError("几何复验需要 trimesh")
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(c._file_verify, "geometry_checks",
                                   side_effect=missing):
                fv = c.verify_exported_stl(os.path.join(d, "x.stl"),
                                           self._box())
        self.assertIs(fv["pass"], False)
        self.assertIs(fv["skipped"], False)
        self.assertIs(fv["dependency_missing"], True)
        self.assertIn("环境缺依赖", fv["error"])
        self.assertIn("trimesh", fv["error"])
        self.assertEqual(fv["checks"], {})
        # 结构化结果必须能直接落盘，且 verdict 带得走这条诊断。
        json.dumps(fv, ensure_ascii=False, allow_nan=False)
        verdict = good_verdict()
        applied = c.apply_file_verification(verdict, fv)
        self.assertFalse(applied["pass"])
        self.assertFalse(applied["file_verification_pass"])
        self.assertIn("环境缺依赖", applied["file_verification_failure"])

    def test_r49_legacy_importerror_and_generic_error_are_distinguished(self):
        """旧版异常同样分类；真正的几何异常不能被误标成缺依赖。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.stl")
            with mock.patch.object(c._file_verify, "geometry_checks",
                                   side_effect=ImportError("no trimesh")):
                legacy = c.verify_exported_stl(path, self._box())
            with mock.patch.object(c._file_verify, "geometry_checks",
                                   side_effect=ValueError("stl 损坏")):
                broken = c.verify_exported_stl(path, self._box())
        self.assertIs(legacy["dependency_missing"], True)
        self.assertIs(legacy["pass"], False)
        self.assertIs(broken["pass"], False)
        self.assertNotIn("dependency_missing", broken)
        self.assertIn("stl 损坏", broken["error"])

    def test_apply_file_verification_keeps_five_check_contract(self):
        good = {"final_mesh": {"silhouette_iou": 0.83, "watertight_indexed": True,
                               "boundary_edges": 0, "nonmanifold_edges": 0},
                "aspect_error_pct": 0.0}
        verdict = c.build_verdict(good, 0.55, True)
        self.assertTrue(verdict["pass"])
        ok = c.apply_file_verification(verdict, {"pass": True, "checks": {"a": True}})
        self.assertTrue(ok["pass"])
        self.assertTrue(ok["file_verification_pass"])
        self.assertEqual(len(ok["checks"]), 5)
        self.assertEqual(ok["evaluated_on"], "final_mesh")

        bad = c.apply_file_verification(
            verdict, {"pass": False, "checks": {"positive_volume": False,
                                                "welded_watertight": True}})
        self.assertFalse(bad["pass"])
        self.assertIn("positive_volume", bad["file_verification_failure"])
        self.assertTrue(verdict["pass"], "不得就地改写原 verdict")
        self.assertIs(c.apply_file_verification(verdict, {"pass": None,
                                                         "skipped": True}), verdict)

    def test_manifest_records_file_verification(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.glb")
            self._box().export(src)
            args = argparse.Namespace(input=src, blender_exe=None, to=["stl"])
            fv = {"pass": True, "checks": {"probe": True}, "stl": src}
            path = c.write_manifest(d, "r27", args, 0.0, [], None, None, fv)
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        self.assertEqual(data["file_verification"], fv)

    def test_standalone_verifier_cross_checks_main_chain_result(self):
        """旁路 CLI 必须核对报告里的文件级结论，避免两处结论互相矛盾。"""
        box = self._box()
        with tempfile.TemporaryDirectory() as d:
            stl = self._export(box, d)
            rep = os.path.join(d, "m_fidelity.json")
            man = os.path.join(d, "m_manifest.json")
            base_report = {
                "schema_version": "2.0",
                "final_mesh": {
                    "faces": len(box.faces), "vertices": len(box.vertices),
                    "extents_xyz": [float(v) for v in box.extents],
                    "watertight": True, "boundary_edges": 0,
                    "nonmanifold_edges": 0, "silhouette_iou": 0.9},
                "verdict": good_verdict(file_verification_pass=True),
                # R32：夹具必须包含主链路与独立复验共享的 4 项几何判据，
                # 否则会因「逐项交叉核对」失败，属夹具失真而非判据过严。
                "file_verification": {
                    "pass": True, "stl": os.path.abspath(stl),
                    "checks": {"welded_watertight": True,
                               "winding_consistent": True,
                               "positive_volume": True,
                               "closed_solid": True,
                               "probe": True}},
            }
            # R31：清单条目必须与 convert_3d.write_manifest.describe 的真实
            # 结构一致（path/bytes/sha256）；旧夹具只给 sha256，修复后会因
            # 按路径定位不到条目而误报，属夹具失真而非判据过严。
            # R35：write_manifest 会把同一个 file_verification 写进清单；
            # 夹具保留篡改前的原始副本，才不会把「删报告字段」误当旧报告。
            with open(man, "w", encoding="utf-8") as handle:
                json.dump({"outputs": [{
                    "path": os.path.abspath(stl),
                    "bytes": os.path.getsize(stl),
                    "sha256": vd._sha256(stl)}],
                    "file_verification": copy.deepcopy(
                        base_report["file_verification"])}, handle)
            with open(rep, "w", encoding="utf-8") as handle:
                json.dump(base_report, handle)
            good = vd.verify(stl, rep, man)
            self.assertEqual(len(good["checks"]), 12)
            self.assertTrue(good["checks"]["file_verification_consistent"])
            self.assertEqual(good["metrics"]["manifest_stl_output_index"], 0)
            self.assertTrue(good["pass"], str(good["checks"]))

            falsified = dict(base_report["file_verification"])
            falsified["pass"] = False
            tampered = dict(base_report, file_verification=falsified)
            with open(rep, "w", encoding="utf-8") as handle:
                json.dump(tampered, handle)
            bad = vd.verify(stl, rep, man)
            self.assertFalse(bad["checks"]["file_verification_consistent"])
            self.assertFalse(bad["pass"])

    def test_cli_end_to_end_writes_file_verification(self):
        """真实跑一次主链路：清单里必须有 PASS 的文件级复验结果。"""
        with tempfile.TemporaryDirectory() as d:
            glb = os.path.join(d, "small.glb")
            self._box().export(glb)
            argv = [os.path.join(ROOT, "convert_3d.py"), glb,
                    "--to", "stl", "--no-fidelity", "--no-blender-repair",
                    "--no-orient", "--no-base", "--no-hollow", "--no-diagnose",
                    "--out-dir", d, "--out-prefix", "r27"]
            proc = subprocess.run([sys.executable] + argv, cwd=ROOT,
                                  capture_output=True, text=True, timeout=180)
            self.assertEqual(proc.returncode, 0, proc.stdout[-1500:] + proc.stderr[-1500:])
            man_path = os.path.join(d, "r27_manifest.json")
            self.assertTrue(os.path.isfile(man_path), proc.stdout[-1500:])
            with open(man_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            fv = manifest.get("file_verification")
            self.assertIsNotNone(fv, "主链路未把文件级复验写入清单")
            self.assertIs(fv.get("pass"), True, str(fv))
            self.assertIn("文件级复验: PASS", proc.stdout)

    def test_cli_file_verification_failure_returns_nonzero(self):
        """注入一个失败的几何复验：主链路必须返回非零退出码并留下记录。"""
        with tempfile.TemporaryDirectory() as d:
            glb = os.path.join(d, "small.glb")
            self._box().export(glb)
            argv = ["convert_3d.py", glb, "--to", "stl", "--no-fidelity",
                    "--no-blender-repair", "--no-orient", "--no-base",
                    "--no-hollow", "--no-diagnose",
                    "--out-dir", d, "--out-prefix", "r27bad"]

            def fake_checks(path):
                return ({"welded_watertight": False, "winding_consistent": True,
                         "positive_volume": True, "closed_solid": False},
                        {"faces": 12, "vertices_raw": 36, "vertices_welded": 8,
                         "volume_signed": 24.0, "euler_number": 2,
                         "extents_xyz": [2.0, 3.0, 4.0]})

            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(c._file_verify, "geometry_checks",
                                      side_effect=fake_checks), \
                    contextlib.redirect_stdout(io.StringIO()):
                rc = c.main()
            self.assertEqual(rc, 1)
            with open(os.path.join(d, "r27bad_manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertIs(manifest["file_verification"]["pass"], False)
            self.assertIn("welded_watertight",
                          manifest["file_verification"]["checks"])


@unittest.skipUnless(HAS_DEPS, "缺 trimesh/numpy/Pillow，连通块清理不可用")
class TestFloatingPartsHandling(unittest.TestCase):
    """R29：把 R28 只告警的悬空碎块变成可剔除、可硬拒绝的一等公民。"""

    @staticmethod
    def _multi_body():
        main = trimesh.creation.box(extents=(2.0, 3.0, 4.0))       # 24 mm³
        chip1 = trimesh.creation.box(extents=(1.0, 1.0, 1.0)).apply_translation((10, 0, 0))
        chip2 = trimesh.creation.box(extents=(0.5, 0.5, 0.5)).apply_translation((-10, 0, 0))
        return trimesh.util.concatenate([main, chip1, chip2])

    @staticmethod
    def _write_case(directory):
        glb = os.path.join(directory, "multi.glb")
        TestFloatingPartsHandling._multi_body().export(glb)
        ref = os.path.join(directory, "multi_3d_input.png")
        px = numpy.full((256, 256, 3), 255, numpy.uint8)
        px[40:210, 80:180] = 25
        Image.fromarray(px).save(ref)
        return glb

    @staticmethod
    def _argv(glb, directory, prefix, *extra):
        return [os.path.join(ROOT, "convert_3d.py"), glb,
                "--to", "stl", "--min-iou", "0",
                "--no-crop-background", "--no-orient", "--no-base",
                "--no-hollow", "--no-diagnose", "--no-blender-repair",
                "--out-dir", directory, "--out-prefix", prefix, *extra]

    def test_drop_floating_parts_keeps_only_largest_connected_body(self):
        mesh = self._multi_body()
        self.assertEqual(len(mesh.split(only_watertight=False)), 3)
        cleaned, info = c.drop_floating_parts(mesh)
        self.assertIs(info["accepted"], True)
        self.assertEqual(info["connected_parts_before"], 3)
        self.assertEqual(info["connected_parts_after"], 1)
        self.assertEqual(info["removed_parts"], 2)
        self.assertEqual(info["removed_faces"], 24)
        self.assertAlmostEqual(info["removed_volume_mm3"], 1.125, places=3)
        self.assertEqual(len(cleaned.split(only_watertight=False)), 1)
        self.assertIs(bool(cleaned.is_watertight), True)
        self.assertAlmostEqual(float(cleaned.volume), 24.0, places=3)
        self.assertTrue(numpy.allclose(cleaned.extents, [2.0, 3.0, 4.0]))

    def test_drop_floating_parts_is_noop_on_single_body(self):
        mesh = trimesh.creation.box(extents=(2.0, 3.0, 4.0))
        cleaned, info = c.drop_floating_parts(mesh)
        self.assertEqual(len(cleaned.faces), len(mesh.faces))
        self.assertEqual(info["removed_parts"], 0)
        self.assertIs(info["accepted"], True)
        self.assertIn("已是单实体", info["reason"])

    def test_drop_floating_parts_falls_back_on_empty_mesh(self):
        mesh = trimesh.Trimesh(vertices=[], faces=[], process=False)
        cleaned, info = c.drop_floating_parts(mesh)
        self.assertIs(cleaned, mesh)
        self.assertIs(info["accepted"], False)
        self.assertIn("空网格", info["reason"])

    def test_enforce_single_body_rejects_multi_body_without_mutating_input(self):
        fv = {"checks": {"welded_watertight": True},
              "metrics": {"connected_parts": 2}, "pass": True}
        out = c.enforce_single_body(fv)
        self.assertIs(out["pass"], False)
        self.assertIs(out["checks"]["single_body"], False)
        self.assertIn("drop-floating-parts", out["single_body_failure"])
        self.assertNotIn("single_body", fv["checks"], "不得原地修改输入")
        self.assertIs(c.enforce_single_body({"skipped": True, "pass": None})["pass"], None)

    def test_validate_args_rejects_strict_gate_without_stl(self):
        a = argparse.Namespace(height=0.0, scale=1.0, base=0.0, hollow=0.0,
                               min_iou=0.0, voxel_mm=0.25,
                               repair_max_iou_drop=0.02, decimate=0,
                               smooth=0, pitch=0.01, to=["glb"],
                               strict_single_body=True)
        self.assertTrue(any("strict-single-body" in e for e in c.validate_args(a)))
        a.to = ["stl"]
        self.assertEqual(c.validate_args(a), [])

    def test_cli_end_to_end_produces_single_body_stl(self):
        """真实跑主链路：清理后落地 STL 单实体，报告/清单/verdict 三处自证。"""
        with tempfile.TemporaryDirectory() as d:
            glb = self._write_case(d)
            argv = self._argv(glb, d, "r29", "--ref-image",
                              os.path.join(d, "multi_3d_input.png"),
                              "--drop-floating-parts", "--strict-single-body")
            proc = subprocess.run([sys.executable] + argv, cwd=ROOT,
                                  capture_output=True, text=True, timeout=180)
            self.assertEqual(proc.returncode, 0, proc.stdout[-1800:] + proc.stderr[-1800:])
            stl = os.path.join(d, "r29.stl")
            welded = trimesh.load(stl, force="mesh", process=True)
            self.assertEqual(len(welded.split(only_watertight=False)), 1)
            with open(os.path.join(d, "r29_fidelity.json"), encoding="utf-8") as f:
                report = json.load(f)
            with open(os.path.join(d, "r29_manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)
            cleanup = report.get("geometry_cleanup")
            self.assertIsNotNone(cleanup, "报告未记录连通块清理")
            self.assertEqual(cleanup["connected_parts_after"], 1)
            fv = report.get("file_verification")
            self.assertIs(fv["pass"], True, str(fv))
            self.assertIs(fv["checks"]["single_body"], True)
            self.assertIs(report["verdict"]["file_verification_pass"], True)
            self.assertIs(manifest["parameters"]["drop_floating_parts"], True)
            self.assertIs(manifest["parameters"]["strict_single_body"], True)
            self.assertIn("连通块清理", proc.stdout)

    def test_cli_strict_gate_rejects_multi_body_when_cleanup_disabled(self):
        """不清理时硬门禁必须让验收 FAIL 且退出码非零，而不是只打告警。"""
        with tempfile.TemporaryDirectory() as d:
            glb = self._write_case(d)
            argv = self._argv(glb, d, "r29bad", "--ref-image",
                              os.path.join(d, "multi_3d_input.png"),
                              "--strict-single-body")
            proc = subprocess.run([sys.executable] + argv, cwd=ROOT,
                                  capture_output=True, text=True, timeout=180)
            self.assertNotEqual(proc.returncode, 0, proc.stdout[-1800:])
            with open(os.path.join(d, "r29bad_manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)
            fv = manifest.get("file_verification")
            self.assertIs(fv["pass"], False, str(fv))
            self.assertIs(fv["checks"]["single_body"], False)
            with open(os.path.join(d, "r29bad_fidelity.json"), encoding="utf-8") as f:
                report = json.load(f)
            self.assertIs(report["verdict"]["file_verification_pass"], False)


@unittest.skipUnless(HAS_DEPS, "缺 trimesh/numpy/Pillow，多格式复验不可用")
class TestMultiFormatIndependentVerify(unittest.TestCase):
    """R31：真实主链路按 --to 顺序写清单，STL 不在首位时独立复验不得误判。"""

    def test_cli_multi_format_stl_hash_is_located_by_path(self):
        with tempfile.TemporaryDirectory() as d:
            box = trimesh.creation.box(extents=(2.0, 3.0, 4.0))
            glb = os.path.join(d, "m.glb")
            box.export(glb)
            ref = os.path.join(d, "ref.png")
            px = numpy.full((256, 256, 3), 255, numpy.uint8)
            px[28:228, 78:178] = 0
            Image.fromarray(px).save(ref)
            # fig.py print 默认 --formats obj stl 3mf ply；这里复现前两种，
            # 足以让 outputs[0] 变成 obj（修复前独立复验会误判 FAIL）。
            argv = [os.path.join(ROOT, "convert_3d.py"), glb,
                    "--to", "obj", "stl", "--min-iou", "0",
                    "--no-crop-background", "--no-orient", "--no-base",
                    "--no-hollow", "--no-diagnose", "--no-blender-repair",
                    "--out-dir", d, "--out-prefix", "multi",
                    "--ref-image", ref]
            proc = subprocess.run([sys.executable] + argv, cwd=ROOT,
                                  capture_output=True, text=True, timeout=180)
            self.assertEqual(proc.returncode, 0,
                             proc.stdout[-1800:] + proc.stderr[-800:])
            stl = os.path.join(d, "multi.stl")
            with open(os.path.join(d, "multi_manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertTrue(manifest["outputs"][0]["path"].endswith(".obj"),
                            "用例前提失效：STL 意外排在了首位")
            self.assertTrue(manifest["outputs"][1]["path"].endswith(".stl"))
            result = vd.verify(stl)
            self.assertTrue(result["checks"]["file_sha256_matches_manifest"],
                            str(result["checks"]))
            self.assertEqual(result["metrics"]["manifest_stl_output_index"], 1)


    def test_r35_cli_require_file_verification_is_wired(self):
        """--require-file-verification 必须由 CLI 透传：final5 过、旧报告拒。"""
        script = os.path.join(ROOT, "verify_deliverable.py")
        final5 = os.path.join(ROOT, "print_ready", "_verify2", "final5",
                              "target_final5.stl")
        legacy = os.path.join(ROOT, "print_ready", "_verify2", "final4",
                              "target_final4.stl")
        if not all(os.path.isfile(p) for p in (final5, legacy)):
            self.skipTest("缺少 final4/final5 历史样本")
        good = subprocess.run(
            [sys.executable, script, "--stl", final5,
             "--require-file-verification"],
            cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn("PASS  file_verification_consistent", good.stdout)
        old = subprocess.run(
            [sys.executable, script, "--stl", legacy,
             "--require-file-verification"],
            cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(old.returncode, 1, old.stdout + old.stderr)
        self.assertIn("FAIL  file_verification_consistent", old.stdout)


    # ---------- R39：生成侧 verdict 的输入契约（对齐独立复验侧） ----------

    @staticmethod
    def _good_report():
        return {"final_mesh": {"silhouette_iou": 0.83,
                               "watertight_indexed": True,
                               "boundary_edges": 0, "nonmanifold_edges": 0},
                "aspect_error_pct": 0.0}

    def test_r39_build_verdict_baseline_contract_unchanged(self):
        """加固不能改变合法报告的结论，也不得破坏 R34 的 5 项契约。"""
        v = c.build_verdict(self._good_report(), 0.55, True)
        self.assertTrue(v["pass"])
        self.assertEqual(set(v["checks"]), set(vd.VERDICT_KNOWN_CHECKS))
        self.assertEqual(v["required_checks"], list(vd.VERDICT_KNOWN_CHECKS))
        self.assertEqual(v["evaluated_on"], "final_mesh")
        self.assertNotIn("invalid_metrics", v)
        applied = c.apply_file_verification(
            v, {"pass": True, "checks": {"a": True}})
        self.assertEqual(len(applied["checks"]), 5)

    def test_r39_malformed_metrics_are_structured_failures(self):
        """实证：旧实现 float(None) / None <= 1.0 抛 TypeError 直接中断导出。"""
        cases = (
            ("iou_none", "final_mesh", "silhouette_iou", None),
            ("iou_str", "final_mesh", "silhouette_iou", "abc"),
            ("iou_nan", "final_mesh", "silhouette_iou", float("nan")),
            ("iou_inf", "final_mesh", "silhouette_iou", float("inf")),
            ("aspect_none", None, "aspect_error_pct", None),
            ("aspect_str", None, "aspect_error_pct", "oops"),
            ("aspect_nan", None, "aspect_error_pct", float("nan")),
            ("final_mesh_not_dict", "final_mesh", None, [1, 2]),
        )
        for label, section, key, value in cases:
            with self.subTest(case=label):
                report = self._good_report()
                if section == "final_mesh" and key is None:
                    report["final_mesh"] = value
                elif section is None:
                    report[key] = value
                else:
                    report[section][key] = value
                v = c.build_verdict(report, 0.55, True)
                self.assertFalse(v["pass"])
                self.assertIn("invalid_metrics", v)
                self.assertEqual(set(v["checks"]), set(vd.VERDICT_KNOWN_CHECKS))
                self.assertTrue(all(isinstance(x, bool)
                                    for x in v["checks"].values()))
                if key == "silhouette_iou":
                    self.assertFalse(v["checks"]["silhouette_iou"])
                if key == "aspect_error_pct":
                    self.assertFalse(v["checks"]["aspect_self_check"])

    def test_r39_invalid_min_iou_is_structured_failure(self):
        """门禁阈值本身畸形时也不能把 IoU 判据静默放行。"""
        for bad in (None, "abc", float("nan"), float("inf")):
            with self.subTest(min_iou=bad):
                v = c.build_verdict(self._good_report(), bad, True)
                self.assertFalse(v["pass"])
                self.assertFalse(v["checks"]["silhouette_iou"])
                self.assertIn("invalid_metrics", v)

    def test_r39_truthy_non_boolean_values_are_rejected(self):
        """实证：旧实现 bool("false") / bool(2) 把非水密报告判成水密。"""
        for bad in ("false", 2, "0", 0.5, [1], {"a": 1}):
            with self.subTest(value=bad):
                report = self._good_report()
                report["final_mesh"]["watertight_indexed"] = bad
                v = c.build_verdict(report, 0.55, True)
                self.assertFalse(v["checks"]["watertight"])
                self.assertFalse(v["pass"])
        # 数值 1 / 1.0 是合法的严格真值等价，不能误伤
        for ok in (True, 1, 1.0):
            with self.subTest(valid=ok):
                report = self._good_report()
                report["final_mesh"]["watertight_indexed"] = ok
                self.assertTrue(
                    c.build_verdict(report, 0.55, True)["checks"]["watertight"])

    def test_r39_false_is_not_zero_boundary_edges(self):
        """Python 里 False == 0，旧实现会把布尔假值判成「无边界边」。"""
        for field, check_name in (("boundary_edges", "no_boundary_edges"),
                                  ("nonmanifold_edges", "no_nonmanifold_edges")):
            with self.subTest(field=field):
                report = self._good_report()
                report["final_mesh"][field] = False
                v = c.build_verdict(report, 0.55, True)
                self.assertFalse(v["checks"][check_name])
                self.assertFalse(v["pass"])
        report = self._good_report()
        report["final_mesh"]["boundary_edges"] = "0"
        self.assertFalse(
            c.build_verdict(report, 0.55, True)["checks"]["no_boundary_edges"])

    def test_r39_final5_report_verdict_is_unchanged(self):
        """加固不得改变已交付成品结论：用真实 final5 报告重算 verdict。"""
        path = os.path.join(ROOT, "print_ready", "_verify2", "final5",
                            "target_final5_fidelity.json")
        if not os.path.isfile(path):
            self.skipTest("final5 报告不在本机，跳过交付对照")
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        recomputed = c.build_verdict(report, 0.55, True)
        stored = report["verdict"]
        self.assertEqual(recomputed["checks"], stored["checks"])
        self.assertEqual(recomputed["required_checks"],
                         stored["required_checks"])
        self.assertEqual(recomputed["evaluated_on"], stored["evaluated_on"])
        self.assertEqual(recomputed["pass"], stored["pass"])
        self.assertNotIn("invalid_metrics", recomputed)


@unittest.skipUnless(HAS_DEPS, "缺 trimesh/numpy/Pillow，主链路不可用")
class TestR55ExplicitReferenceFailClosed(unittest.TestCase):
    """R55：显式参考图是验收要求，不能像自动找图一样静默降级。"""

    @staticmethod
    def _input(directory):
        path = os.path.join(directory, "m.glb")
        trimesh.creation.box(extents=(2.0, 3.0, 4.0)).export(path)
        return path

    @staticmethod
    def _argv(glb, directory, ref, *extra):
        return [os.path.join(ROOT, "convert_3d.py"), glb,
                "--to", "stl", "--out-dir", directory, "--out-prefix", "r55",
                "--ref-image", ref, "--no-blender-repair", "--no-orient",
                "--no-base", "--no-hollow", "--no-diagnose", *extra]

    def _run(self, argv):
        return subprocess.run([sys.executable] + argv, cwd=ROOT,
                              capture_output=True, text=True, timeout=180)

    def test_r55_missing_explicit_reference_rejects_before_export(self):
        with tempfile.TemporaryDirectory() as d:
            glb = self._input(d)
            out = self._run(self._argv(glb, d, os.path.join(d, "missing.png")))
            self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
            self.assertIn("显式参考图不存在", out.stdout + out.stderr)
            self.assertIn("--no-fidelity", out.stdout + out.stderr)
            self.assertFalse(os.path.exists(os.path.join(d, "r55.stl")))

    def test_r55_broken_explicit_reference_rejects_before_export(self):
        with tempfile.TemporaryDirectory() as d:
            glb = self._input(d)
            ref = os.path.join(d, "broken.png")
            with open(ref, "wb") as handle:
                handle.write(b"not a png")
            out = self._run(self._argv(glb, d, ref))
            self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
            self.assertIn("显式参考图解析失败", out.stdout + out.stderr)
            self.assertFalse(os.path.exists(os.path.join(d, "r55.stl")))

    def test_r55_explicit_no_fidelity_remains_supported(self):
        """明确 opt-out 与参考图意外失效必须区分，不能破坏旧用法。"""
        with tempfile.TemporaryDirectory() as d:
            glb = self._input(d)
            argv = self._argv(glb, d, os.path.join(d, "missing.png"),
                              "--no-fidelity")
            out = self._run(argv)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "r55.stl")))
            self.assertIn("--no-fidelity", out.stdout)

    def test_r55_auto_discovery_failure_keeps_legacy_fallback(self):
        """未显式要求验收时，损坏的同名自动发现图仍只告警并降级。"""
        with tempfile.TemporaryDirectory() as d:
            glb = self._input(d)
            auto = os.path.join(d, "m_3d_input.png")
            with open(auto, "wb") as handle:
                handle.write(b"broken auto discovery")
            argv = [os.path.join(ROOT, "convert_3d.py"), glb,
                    "--to", "stl", "--out-dir", d, "--out-prefix", "auto",
                    "--no-blender-repair", "--no-orient", "--no-base",
                    "--no-hollow", "--no-diagnose"]
            out = self._run(argv)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("自动发现的参考图解析失败", out.stdout)
            self.assertTrue(os.path.isfile(os.path.join(d, "auto.stl")))


@unittest.skipUnless(HAS_DEPS, "缺 trimesh/numpy，主链路导出不可用")
class TestR57AtomicExport(unittest.TestCase):
    """R57：导出中途失败不得破坏既有成品，成功后报告仍指向交付文件。"""

    @staticmethod
    def _box():
        return trimesh.creation.box(extents=(2.0, 3.0, 4.0))

    @staticmethod
    def _leftovers(directory):
        return [n for n in os.listdir(directory) if n.startswith(".export_")]

    def test_r57_partial_export_failure_preserves_existing_stl(self):
        """修复前：先写 PARTIAL-STL 再抛错，原成品被覆盖成半成品。"""
        class HalfBroken:
            def export(self, path, file_type=None):
                with open(path, "wb") as handle:
                    handle.write(b"PARTIAL-STL")
                raise RuntimeError("simulated disk full")

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "good.stl")
            good = b"KNOWN-GOOD-STL"
            with open(out, "wb") as handle:
                handle.write(good)
            with self.assertRaises(RuntimeError):
                c.export_mesh_atomic(HalfBroken(), out, "stl",
                                     verify_mesh=self._box())
            with open(out, "rb") as handle:
                self.assertEqual(handle.read(), good)
            self.assertEqual(self._leftovers(d), [])

    def test_r57_success_replaces_file_and_records_final_path(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "m.stl")
            with open(out, "wb") as handle:
                handle.write(b"OLD")
            mesh = self._box()
            fv = c.export_mesh_atomic(mesh, out, "stl", verify_mesh=mesh)
            self.assertGreater(os.path.getsize(out), 100)
            self.assertEqual(os.path.normcase(os.path.abspath(fv["stl"])),
                             os.path.normcase(os.path.abspath(out)))
            self.assertNotIn(".export_", fv["stl"])
            self.assertTrue(fv["pass"], fv)
            self.assertEqual(len(trimesh.load(out, force="mesh").faces), 12)
            self.assertEqual(self._leftovers(d), [])

    def test_r57_companion_files_move_with_main_file(self):
        """OBJ 的 .mtl 等伴生文件必须随主文件一起换入，不能留在 staging。"""
        class WithCompanion:
            def export(self, path, file_type=None):
                with open(path, "w", encoding="ascii") as handle:
                    handle.write("obj")
                with open(os.path.splitext(path)[0] + ".mtl", "w",
                          encoding="ascii") as handle:
                    handle.write("mtl")

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "m.obj")
            c.export_mesh_atomic(WithCompanion(), out, "obj")
            with open(out, encoding="ascii") as handle:
                self.assertEqual(handle.read(), "obj")
            with open(os.path.join(d, "m.mtl"), encoding="ascii") as handle:
                self.assertEqual(handle.read(), "mtl")
            self.assertEqual(self._leftovers(d), [])

    def test_r57_supported_formats_still_export(self):
        """统一 staging 改造后，环境可用的 5 种格式都要能正常落地。

        3mf / fbx / usdz 需额外依赖（lxml / exporter），旧实现同样会走
        fail 分支，这里不把它们伪装成通过。
        """
        with tempfile.TemporaryDirectory() as d:
            mesh = self._box()
            for fmt in ("stl", "ply", "glb", "gltf", "obj"):
                with self.subTest(fmt=fmt):
                    target = os.path.join(d, "m_%s.%s" % (fmt, fmt))
                    c.export_mesh_atomic(
                        mesh, target, fmt,
                        verify_mesh=mesh if fmt == "stl" else None)
                    self.assertTrue(os.path.isfile(target))
                    self.assertGreater(os.path.getsize(target), 0)
            self.assertEqual(self._leftovers(d), [])

    def test_r57_cli_repeated_export_is_clean(self):
        """端到端：重复导出同一路径，成品仍合法且证据里不含 staging 路径。"""
        with tempfile.TemporaryDirectory() as d:
            glb = os.path.join(d, "m.glb")
            self._box().export(glb)
            argv = [sys.executable, os.path.join(ROOT, "convert_3d.py"), glb,
                    "--to", "stl", "--out-dir", d, "--out-prefix", "r57",
                    "--no-blender-repair", "--no-orient", "--no-base",
                    "--no-hollow", "--no-diagnose"]
            for _ in range(2):
                out = subprocess.run(argv, cwd=ROOT, capture_output=True,
                                     text=True, timeout=180)
                self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            stl = os.path.join(d, "r57.stl")
            self.assertTrue(os.path.isfile(stl))
            self.assertEqual(len(trimesh.load(stl, force="mesh").faces), 12)
            for name in ("r57_fidelity.json", "r57_manifest.json"):
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    with open(path, encoding="utf-8") as handle:
                        self.assertNotIn(".export_", handle.read())
            self.assertEqual(self._leftovers(d), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
