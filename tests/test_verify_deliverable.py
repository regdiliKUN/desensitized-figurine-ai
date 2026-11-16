# -*- coding: utf-8 -*-
"""R26：交付物文件级独立复验的回归保护。

正例验证 final4 全套 11 项检查；负例分别验证「法线朝内」「开口网格」
「哈希不符」能被真正拒绝，避免新增验收只是永远返回 True 的摆设。
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# R37：None 本身是要测的「顶层为 null」样本，不能同时充当「未指定」哨兵。
_UNSET = object()

# R44：verify_deliverable 顶层只依赖标准库，纯 PNG 解码/几何绑定回归在缺
# trimesh 的环境也必须能跑；不能把 vd 绑在 trimesh 的导入结果上。
import verify_deliverable as vd

try:
    import trimesh
    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False


def good_verdict(**extra):
    """按 build_verdict 的真实契约构造 verdict。

    R33：旧夹具只写 {"probe": True}，与生产的固定 5 项 + required_checks
    不符；独立复验改为严格校验后，失真夹具会制造假失败。单一真值取自
    vd.VERDICT_KNOWN_CHECKS，避免测试与生产各写一份判据集合。
    """
    out = {"pass": True,
           "checks": dict.fromkeys(vd.VERDICT_KNOWN_CHECKS, True),
           "required_checks": list(vd.VERDICT_KNOWN_CHECKS),
           "evaluated_on": "final_mesh"}
    out.update(extra)
    return out


@unittest.skipUnless(HAS_TRIMESH, "缺 trimesh，文件级复验不可用")
class TestVerifyDeliverable(unittest.TestCase):

    @staticmethod
    def _box():
        return trimesh.creation.box(extents=(2.0, 3.0, 4.0))

    def test_missing_stl_is_a_hard_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                vd.verify(os.path.join(d, "no_such_file.stl"))

    def test_flipped_normals_are_rejected(self):
        """水密但法线朝内：体积为负，切片软件会当成空壳。"""
        box = self._box()
        flipped = trimesh.Trimesh(
            vertices=box.vertices.copy(),
            faces=box.faces[:, [0, 2, 1]].copy(), process=False)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "flipped.stl")
            flipped.export(path)
            result = vd.verify(path, stl_only=True)
        self.assertTrue(result["checks"]["welded_watertight"])
        self.assertFalse(result["checks"]["positive_volume"])
        self.assertFalse(result["pass"])

    def test_open_mesh_is_rejected(self):
        """删掉一个面后焊接拓扑必须不再闭合。"""
        box = self._box()
        opened = trimesh.Trimesh(
            vertices=box.vertices.copy(),
            faces=box.faces[:-1].copy(), process=False)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "open.stl")
            opened.export(path)
            result = vd.verify(path, stl_only=True)
        self.assertFalse(result["checks"]["welded_watertight"])
        self.assertFalse(result["pass"])

    def test_manifest_hash_mismatch_is_rejected(self):
        """报告/清单与文件不是同一个东西时必须拒绝。"""
        box = self._box()
        report = {
            "schema_version": "2.0",
            "final_mesh": {
                "faces": len(box.faces), "vertices": len(box.vertices),
                "extents_xyz": [float(v) for v in box.extents],
                "watertight": True, "boundary_edges": 0,
                "nonmanifold_edges": 0, "silhouette_iou": 0.9},
            "verdict": good_verdict(),
        }
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep = os.path.join(d, "m_fidelity.json")
            man = os.path.join(d, "m_manifest.json")
            box.export(stl)
            # R31：条目路径正确、只有哈希被篡改，才是本用例要测的「哈希不符」。
            manifest = {"outputs": [{"path": os.path.abspath(stl),
                                     "sha256": "0" * 64}]}
            with open(rep, "w", encoding="utf-8") as f:
                json.dump(report, f)
            with open(man, "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            result = vd.verify(stl, rep, man)
        self.assertFalse(result["checks"]["file_sha256_matches_manifest"])
        self.assertTrue(result["checks"]["faces_match_report"])
        self.assertFalse(result["pass"])

    def test_floating_parts_are_reported_and_optionally_rejected(self):
        """R28：多实体也能通过 is_watertight，悬空碎块必须被看见、可被硬拒绝。"""
        a = self._box()
        b = self._box()
        b.apply_translation([10.0, 0.0, 0.0])
        twin = trimesh.util.concatenate([a, b])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "twin.stl")
            twin.export(path)
            soft = vd.verify(path, stl_only=True)
            hard = vd.verify(path, stl_only=True, strict_single_body=True)
        self.assertEqual(soft["metrics"]["connected_parts"], 2)
        self.assertEqual(soft["metrics"]["floating_parts"], 1)
        self.assertEqual(soft["metrics"]["degenerate_faces"], 0)
        self.assertTrue(any("悬空连通块" in w for w in soft["warnings"]))
        self.assertTrue(soft["pass"], "默认只告警，不推翻既有验收结论")
        self.assertFalse(hard["checks"]["single_body"])
        self.assertFalse(hard["pass"])

    def test_final4_floating_parts_are_quantified(self):
        """落地成品实测 7 个连通块（6 个悬空碎块），此前 27 轮从未检测。"""
        base = os.path.join(ROOT, "print_ready", "_verify2", "final4")
        stl = os.path.join(base, "target_final4.stl")
        if not all(os.path.isfile(os.path.join(base, n)) for n in (
                "target_final4.stl", "target_final4_fidelity.json",
                "target_final4_manifest.json")):
            self.skipTest("缺少 final4 交付样本")
        result = vd.verify(stl)
        self.assertEqual(len(result["checks"]), 12)
        self.assertTrue(result["pass"])
        self.assertEqual(result["metrics"]["connected_parts"], 7)
        self.assertEqual(result["metrics"]["floating_parts"], 6)
        self.assertEqual(result["metrics"]["degenerate_faces"], 0)
        self.assertLess(result["metrics"]["floating_volume_ratio"], 0.001)
        self.assertTrue(any("悬空连通块" in w for w in result["warnings"]))

    def test_final4_passes_all_file_level_checks(self):
        base = os.path.join(ROOT, "print_ready", "_verify2", "final4")
        stl = os.path.join(base, "target_final4.stl")
        if not all(os.path.isfile(os.path.join(base, n)) for n in (
                "target_final4.stl", "target_final4_fidelity.json",
                "target_final4_manifest.json")):
            self.skipTest("缺少 final4 交付样本")
        result = vd.verify(stl)
        self.assertEqual(len(result["checks"]), 12)
        self.assertTrue(result["pass"], str(result["checks"]))
        self.assertTrue(result["checks"]["positive_volume"])
        self.assertTrue(result["checks"]["closed_solid"])
        self.assertGreater(result["metrics"]["volume_signed"], 0)


    # ---- R31：清单条目定位不再依赖「STL 排在 outputs[0]」 ----

    def _write_bundle(self, directory, make_outputs):
        """构造一份几何/报告/清单自洽的交付物，outputs 由调用方自由排列。"""
        box = self._box()
        stl = os.path.join(directory, "m.stl")
        rep = os.path.join(directory, "m_fidelity.json")
        man = os.path.join(directory, "m_manifest.json")
        box.export(stl)
        report = {
            "schema_version": "2.0",
            "final_mesh": {
                "faces": len(box.faces), "vertices": len(box.vertices),
                "extents_xyz": [float(v) for v in box.extents],
                "watertight": True, "boundary_edges": 0,
                "nonmanifold_edges": 0, "silhouette_iou": 0.9},
            "verdict": good_verdict(),
        }
        stl_entry = {"path": os.path.abspath(stl),
                     "bytes": os.path.getsize(stl),
                     "sha256": vd._sha256(stl)}
        manifest = {"outputs": make_outputs(stl_entry, directory)}
        with open(rep, "w", encoding="utf-8") as f:
            json.dump(report, f)
        with open(man, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        return stl, rep, man

    def test_multi_format_manifest_matches_stl_by_path(self):
        """R31：fig.py print 默认 obj/stl/3mf/ply，STL 不在首位也必须 PASS。"""
        with tempfile.TemporaryDirectory() as d:
            def outputs(stl_entry, directory):
                return [
                    {"path": os.path.join(directory, "m.obj"), "sha256": "a" * 64},
                    {"path": os.path.join(directory, "m.3mf"), "sha256": "b" * 64},
                    stl_entry,
                    {"path": os.path.join(directory, "m.ply"), "sha256": "c" * 64},
                ]
            stl, rep, man = self._write_bundle(d, outputs)
            result = vd.verify(stl, rep, man)
        self.assertTrue(result["checks"]["file_sha256_matches_manifest"],
                        str(result["checks"]))
        self.assertEqual(result["metrics"]["manifest_stl_output_index"], 2)
        self.assertTrue(result["pass"], str(result["checks"]))

    def test_manifest_without_stl_entry_is_rejected(self):
        """清单里根本没有待复验 STL 的记录：必须 FAIL，不能静默放过。"""
        with tempfile.TemporaryDirectory() as d:
            def outputs(stl_entry, directory):
                return [{"path": os.path.join(directory, "m.obj"),
                         "sha256": "a" * 64}]
            stl, rep, man = self._write_bundle(d, outputs)
            result = vd.verify(stl, rep, man)
        self.assertFalse(result["checks"]["file_sha256_matches_manifest"])
        self.assertIsNone(result["metrics"]["manifest_stl_output_index"])
        self.assertFalse(result["pass"])

    def test_manifest_with_malformed_entries_does_not_crash(self):
        """describe() 会写入 None，畸形条目也不能让复验抛 traceback。"""
        with tempfile.TemporaryDirectory() as d:
            def outputs(stl_entry, directory):
                return [None, "malformed", {"path": 123, "sha256": "x"},
                        stl_entry]
            stl, rep, man = self._write_bundle(d, outputs)
            result = vd.verify(stl, rep, man)
        self.assertTrue(result["checks"]["file_sha256_matches_manifest"],
                        str(result["checks"]))
        self.assertEqual(result["metrics"]["manifest_stl_output_index"], 3)
        self.assertTrue(result["pass"], str(result["checks"]))

    def test_tampered_stl_hash_in_multi_format_is_still_rejected(self):
        """按路径定位不能退化成「只要找到条目就通过」。"""
        with tempfile.TemporaryDirectory() as d:
            def outputs(stl_entry, directory):
                tampered = dict(stl_entry, sha256="0" * 64)
                return [{"path": os.path.join(directory, "m.obj"),
                         "sha256": "a" * 64}, tampered]
            stl, rep, man = self._write_bundle(d, outputs)
            result = vd.verify(stl, rep, man)
        self.assertFalse(result["checks"]["file_sha256_matches_manifest"])
        self.assertEqual(result["metrics"]["manifest_stl_output_index"], 1)
        self.assertFalse(result["pass"])

    def test_find_output_sha256_tolerates_broken_manifest_shapes(self):
        """清单顶层/ outputs 字段类型异常时返回 (None, None)，而不是抛栈。"""
        self.assertEqual(vd.find_output_sha256(None, "x.stl"), (None, None))
        self.assertEqual(vd.find_output_sha256([], "x.stl"), (None, None))
        self.assertEqual(vd.find_output_sha256({"outputs": "oops"}, "x.stl"),
                         (None, None))
        self.assertEqual(vd.find_output_sha256({"outputs": []}, "x.stl"),
                         (None, None))


    # ---- R32：独立复验必须核对主链路 file_verification 的逐项内容 ----

    def _write_fv_bundle(self, directory, mutate=None, sync_manifest=False):
        """构造报告/清单/STL 自洽、且带主链路文件级结论的交付物。

        ``sync_manifest=True`` 模拟「两处同源被同步篡改」，用于隔离 R32 的
        内容核对本身；否则 R35 的交叉契约会先报「报告与清单不一致」。
        """
        box = self._box()
        stl = os.path.join(directory, "m.stl")
        rep = os.path.join(directory, "m_fidelity.json")
        man = os.path.join(directory, "m_manifest.json")
        box.export(stl)
        report = {
            "schema_version": "2.0",
            "final_mesh": {
                "faces": len(box.faces), "vertices": len(box.vertices),
                "extents_xyz": [float(v) for v in box.extents],
                "watertight": True, "boundary_edges": 0,
                "nonmanifold_edges": 0, "silhouette_iou": 0.9},
            "verdict": good_verdict(file_verification_pass=True),
            "file_verification": {
                "pass": True, "stl": os.path.abspath(stl),
                "checks": {
                    "welded_watertight": True, "winding_consistent": True,
                    "positive_volume": True, "closed_solid": True,
                    "faces_match_memory": True, "single_body": True},
            },
        }
        # R35：write_manifest 会把同一个 file_verification 写进清单。夹具必须
        # 保存**篡改前**的原始副本，否则「删掉报告字段」的样本会被误当成
        # 「两处都没有」的合法旧报告，无法复现实证缺陷。
        original_fv = copy.deepcopy(report["file_verification"])
        if mutate:
            mutate(report)
        manifest_fv = (copy.deepcopy(report.get("file_verification"))
                       if sync_manifest else original_fv)
        manifest = {"outputs": [{"path": os.path.abspath(stl),
                                 "bytes": os.path.getsize(stl),
                                 "sha256": vd._sha256(stl)}],
                    "file_verification": manifest_fv}
        with open(rep, "w", encoding="utf-8") as f:
            json.dump(report, f)
        with open(man, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        return stl, rep, man

    def _verify_fv(self, mutate=None, sync_manifest=False):
        with tempfile.TemporaryDirectory() as d:
            stl, rep, man = self._write_fv_bundle(d, mutate, sync_manifest)
            return vd.verify(stl, rep, man)

    def test_fv_consistency_accepts_self_consistent_report(self):
        result = self._verify_fv()
        self.assertEqual(len(result["checks"]), 12)
        self.assertTrue(result["checks"]["file_verification_consistent"])
        self.assertIsNone(result["metrics"]["file_verification_reason"])
        self.assertTrue(result["pass"], str(result["checks"]))

    def test_fv_single_false_check_is_rejected_even_if_pass_true(self):
        """实证缺陷：只改逐项 single_body=False、保留 pass=True 曾照样 PASS。"""
        def mutate(report):
            report["file_verification"]["checks"]["single_body"] = False
        # 同步篡改两处，隔离 R32 内容核对本身（R35 交叉契约此时不介入）。
        result = self._verify_fv(mutate, sync_manifest=True)
        self.assertFalse(result["checks"]["file_verification_consistent"])
        self.assertFalse(result["pass"])
        self.assertIn("逐项 checks", result["metrics"]["file_verification_reason"])

    def test_fv_checks_contradicting_independent_geometry_is_rejected(self):
        """报告说 welded_watertight=False，独立复验自己算出 True —— 必须拒绝。"""
        def mutate(report):
            report["file_verification"]["checks"]["welded_watertight"] = False
        result = self._verify_fv(mutate)
        self.assertTrue(result["checks"]["welded_watertight"])
        self.assertFalse(result["checks"]["file_verification_consistent"])
        self.assertFalse(result["pass"])

    def test_empty_or_missing_fv_checks_is_rejected(self):
        for mutate in (
                lambda r: r["file_verification"].update(checks={}),
                lambda r: r["file_verification"].pop("checks"),
                lambda r: r["file_verification"].update(checks="oops")):
            with self.subTest(mutate=mutate):
                result = self._verify_fv(mutate)
                self.assertFalse(result["checks"]["file_verification_consistent"])
                self.assertFalse(result["pass"])

    def test_non_boolean_fv_flag_is_rejected(self):
        """字符串 "false" 不能被 bool() 当成真值蒙混过关。"""
        def mutate(report):
            report["file_verification"]["checks"]["single_body"] = "false"
        result = self._verify_fv(mutate)
        self.assertFalse(result["checks"]["file_verification_consistent"])
        self.assertFalse(result["pass"])

    def test_malformed_fv_object_is_rejected_not_crash(self):
        result = self._verify_fv(lambda r: r.update(file_verification="oops"))
        self.assertFalse(result["checks"]["file_verification_consistent"])
        self.assertFalse(result["pass"])

    def test_final5_file_verification_consistency_still_passes(self):
        """真实交付物的 8 项主链路结论必须逐项自洽。"""
        base = os.path.join(ROOT, "print_ready", "_verify2", "final5")
        stl = os.path.join(base, "target_final5.stl")
        if not os.path.isfile(stl):
            self.skipTest("缺少 final5 交付样本")
        result = vd.verify(stl)
        self.assertTrue(result["checks"]["file_verification_consistent"],
                        str(result["metrics"].get("file_verification_reason")))
        self.assertEqual(result["metrics"]["file_verification_checks"], 8)
        self.assertTrue(result["pass"], str(result["checks"]))


    # ---------- R33：verdict 汇总字段的绕过防护 ----------

    def _verdict_reason(self, mutate=None):
        result = self._verify_fv(mutate)
        return result, result["metrics"].get("verdict_reason")

    def test_r33_baseline_verdict_is_self_consistent(self):
        result, reason = self._verdict_reason()
        self.assertTrue(result["checks"]["verdict_consistent"])
        self.assertIsNone(reason)
        self.assertEqual(result["metrics"]["verdict_checks"], 5)
        self.assertTrue(result["pass"], str(result["checks"]))

    def test_r33_non_boolean_verdict_flag_is_rejected(self):
        """实证缺陷：字符串 "false"/整数 2 曾被 truthy 判为通过。"""
        for value in ("false", 2, "yes", 1.0):
            with self.subTest(value=value):
                result, reason = self._verdict_reason(
                    lambda r, v=value: r["verdict"]["checks"].update(watertight=v))
                self.assertFalse(result["checks"]["verdict_consistent"])
                self.assertIn("非布尔值", reason)
                self.assertFalse(result["pass"])

    def test_r33_missing_known_check_is_rejected(self):
        result, reason = self._verdict_reason(
            lambda r: r["verdict"]["checks"].pop("watertight"))
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertIn("缺少必需判据", reason)

    def test_r33_trimming_required_checks_does_not_hide_removed_check(self):
        def mutate(r):
            r["verdict"]["checks"].pop("watertight")
            r["verdict"]["required_checks"].remove("watertight")
        result, _ = self._verdict_reason(mutate)
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertFalse(result["pass"])

    def test_r33_forged_checks_dict_is_rejected(self):
        result, reason = self._verdict_reason(
            lambda r: r["verdict"].update(checks={"forged": True}))
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertIn("缺少必需判据", reason)

    def test_r33_always_required_checks_cannot_be_dropped(self):
        result, reason = self._verdict_reason(
            lambda r: r["verdict"].update(required_checks=["silhouette_iou"]))
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertIn("永远必需", reason)

    def test_r33_required_check_pointing_to_absent_key_is_rejected(self):
        result, reason = self._verdict_reason(
            lambda r: r["verdict"]["required_checks"].append("invented"))
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertIn("不存在", reason)

    def test_r33_pass_mismatch_is_rejected(self):
        result, reason = self._verdict_reason(
            lambda r: r["verdict"].update({"pass": False}))
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertIn("重算", reason)

    def test_r33_malformed_verdict_is_rejected_not_crash(self):
        result, reason = self._verdict_reason(
            lambda r: r.update(verdict="PASS"))
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertFalse(result["pass"])
        self.assertIn("不是对象", reason)

    def test_r33_default_mode_does_not_require_all_five_checks_true(self):
        """默认关闭 --strict-watertight 时 required 只有 2 项，不能误伤。"""
        def mutate(r):
            r["verdict"]["required_checks"] = list(vd.VERDICT_ALWAYS_REQUIRED)
            r["verdict"]["checks"]["no_boundary_edges"] = False
            r["verdict"]["checks"]["no_nonmanifold_edges"] = False
        result, reason = self._verdict_reason(mutate)
        self.assertTrue(result["checks"]["verdict_consistent"], str(reason))
        self.assertTrue(result["pass"], str(result["checks"]))

    def test_r33_verdict_watertight_must_agree_with_disk_geometry(self):
        def mutate(r):
            r["verdict"]["required_checks"] = list(vd.VERDICT_ALWAYS_REQUIRED)
            r["verdict"]["checks"]["watertight"] = False
        result, reason = self._verdict_reason(mutate)
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertIn("磁盘 STL", reason)

    def test_r33_final5_verdict_still_passes(self):
        base = os.path.join(ROOT, "print_ready", "_verify2", "final5")
        stl = os.path.join(base, "target_final5.stl")
        if not os.path.isfile(stl):
            self.skipTest("缺少 final5 交付样本")
        result = vd.verify(stl)
        self.assertTrue(result["checks"]["verdict_consistent"],
                        str(result["metrics"].get("verdict_reason")))
        self.assertIsNone(result["metrics"].get("verdict_reason"))
        self.assertTrue(result["pass"], str(result["checks"]))


    # ---------- R34：verdict.pass 的复合语义与跨模块契约 ----------

    @staticmethod
    def _main_chain_geometry():
        return {"welded_watertight": True, "winding_consistent": True,
                "positive_volume": True, "closed_solid": True}

    def _build_main_chain_verdict(self, strict=True):
        try:
            import convert_3d as c
        except ImportError:
            self.skipTest("缺少 convert_3d 依赖")
        report = {
            "final_mesh": {"watertight_indexed": True, "boundary_edges": 0,
                           "nonmanifold_edges": 0, "silhouette_iou": 0.83},
            "aspect_error_pct": 0.4,
        }
        return c, c.build_verdict(report, min_iou=0.55,
                                  strict_watertight=strict)

    def test_r34_build_verdict_contract_matches_known_checks(self):
        """固化上一轮手工深审：主链路改判据后独立复验不得悄悄漂移。"""
        for strict in (False, True):
            with self.subTest(strict=strict):
                _, verdict = self._build_main_chain_verdict(strict)
                self.assertEqual(set(verdict["checks"]),
                                 set(vd.VERDICT_KNOWN_CHECKS))
                self.assertTrue(set(vd.VERDICT_ALWAYS_REQUIRED).issubset(
                    set(verdict["required_checks"])))
                ok, reason = vd.verdict_checks_valid(
                    verdict, self._main_chain_geometry())
                self.assertTrue(ok, str(reason))

    def test_r34_real_main_chain_failed_verdict_is_diagnosed(self):
        """主链路 apply_file_verification 的真实失败输出：结论 FAIL 且原因准确。"""
        convert, verdict = self._build_main_chain_verdict(True)
        failed = convert.apply_file_verification(
            verdict, {"pass": False, "checks": {"single_body": False},
                      "error": None})
        self.assertFalse(failed["pass"])
        self.assertFalse(failed["file_verification_pass"])
        ok, reason = vd.verdict_checks_valid(
            failed, self._main_chain_geometry())
        self.assertFalse(ok)
        self.assertIn("文件级复验未通过", reason)
        self.assertIn("single_body", reason)
        self.assertNotIn("不一致", reason)

    def test_r34_honest_file_verification_failure_diagnoses_correctly(self):
        """合法的不合格报告不能被称为「汇总不一致」（R33 的误诊）。"""
        def mutate(r):
            r["verdict"]["pass"] = False
            r["verdict"]["file_verification_pass"] = False
            r["verdict"]["file_verification_failure"] = "single_body"
            r["file_verification"]["pass"] = False
            r["file_verification"]["checks"]["single_body"] = False
        result, reason = self._verdict_reason(mutate)
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertFalse(result["pass"])
        self.assertIn("文件级复验未通过", reason)
        self.assertNotIn("不一致", reason)

    def test_r34_memory_failure_diagnoses_correctly(self):
        """无文件级字段、内存判据失败的自洽报告也要指向正确环节。"""
        def mutate(r):
            r["verdict"].pop("file_verification_pass", None)
            r["verdict"]["required_checks"] = list(vd.VERDICT_ALWAYS_REQUIRED)
            r["verdict"]["checks"]["silhouette_iou"] = False
            r["verdict"]["pass"] = False
        result, reason = self._verdict_reason(mutate)
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertIn("内存判据未通过", reason)

    def test_r34_pass_true_with_file_verification_false_is_rejected(self):
        """篡改：文件级复验失败却把汇总 pass 写成 True。"""
        result, reason = self._verdict_reason(
            lambda r: r["verdict"].update(file_verification_pass=False))
        self.assertFalse(result["checks"]["verdict_consistent"])
        self.assertFalse(result["pass"])
        self.assertIn("复合重算", reason)

    def test_r34_non_boolean_pass_is_rejected(self):
        """verdict.pass 自身也必须是严格布尔，不能被字符串/整数蒙混。"""
        for value in ("true", 2, None):
            with self.subTest(value=value):
                result, reason = self._verdict_reason(
                    lambda r, v=value: r["verdict"].update({"pass": v}))
                self.assertFalse(result["checks"]["verdict_consistent"])
                self.assertIn("不是布尔值", reason)


    # ---------- R35：文件级闭环字段不得被整段删除 / 两处结论必须一致 ----------

    def test_r35_deleting_report_file_verification_is_rejected(self):
        """实证缺陷：旧实现「缺失即向后兼容跳过」会静默退回 11 项口径。"""
        result = self._verify_fv(lambda r: r.pop("file_verification", None))
        self.assertFalse(result["checks"]["file_verification_consistent"])
        self.assertFalse(result["pass"])
        self.assertIn("删掉了", result["metrics"]["file_verification_reason"])

    def test_r35_deleting_both_file_level_flags_is_rejected(self):
        """连 verdict.file_verification_pass 一起删也绕不过清单证据。"""
        result = self._verify_fv(lambda r: (
            r.pop("file_verification", None),
            r["verdict"].pop("file_verification_pass", None)))
        self.assertFalse(result["checks"]["file_verification_consistent"])
        self.assertFalse(result["pass"])

    def test_r35_report_without_manifest_record_is_rejected(self):
        """报告声明验过、清单却没记录 —— 同样是证据链断裂。"""
        with tempfile.TemporaryDirectory() as d:
            stl, rep, man = self._write_fv_bundle(d)
            with open(man, encoding="utf-8") as f:
                data = json.load(f)
            data.pop("file_verification", None)
            with open(man, "w", encoding="utf-8") as f:
                json.dump(data, f)
            result = vd.verify(stl, rep, man)
        self.assertFalse(result["checks"]["file_verification_consistent"])
        self.assertIn("清单未记录",
                      result["metrics"]["file_verification_reason"])

    def test_r35_manifest_and_report_conclusions_must_agree(self):
        """两处 pass / checks / stl 任一不一致都要拒绝。"""
        cases = (
            ("pass", lambda m: m["file_verification"].update({"pass": False})),
            ("checks", lambda m: m["file_verification"]["checks"].update(
                {"single_body": False})),
            ("stl", lambda m: m["file_verification"].update({"stl": "other.stl"})),
        )
        for label, mutate in cases:
            with self.subTest(field=label):
                with tempfile.TemporaryDirectory() as d:
                    stl, rep, man = self._write_fv_bundle(d)
                    with open(man, encoding="utf-8") as f:
                        data = json.load(f)
                    mutate(data)
                    with open(man, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    result = vd.verify(stl, rep, man)
                self.assertFalse(result["checks"]["file_verification_consistent"])
                self.assertFalse(result["pass"])

    def test_r35_legacy_report_both_absent_is_still_accepted(self):
        """R27 之前的 final4：向后兼容，但检查项不再静默减少。"""
        base = os.path.join(ROOT, "print_ready", "_verify2", "final4")
        stl = os.path.join(base, "target_final4.stl")
        if not os.path.isfile(stl):
            self.skipTest("缺少 final4 历史样本")
        result = vd.verify(stl)
        self.assertEqual(len(result["checks"]), 12)
        self.assertTrue(result["checks"]["file_verification_consistent"])
        self.assertFalse(result["metrics"]["file_verification_contract_required"])
        self.assertTrue(result["pass"], str(result["checks"]))

    def test_r35_require_file_verification_rejects_legacy_report(self):
        base = os.path.join(ROOT, "print_ready", "_verify2", "final4")
        stl = os.path.join(base, "target_final4.stl")
        if not os.path.isfile(stl):
            self.skipTest("缺少 final4 历史样本")
        result = vd.verify(stl, require_file_verification=True)
        self.assertFalse(result["checks"]["file_verification_consistent"])
        self.assertFalse(result["pass"])

    def test_r35_require_file_verification_accepts_final5(self):
        base = os.path.join(ROOT, "print_ready", "_verify2", "final5")
        stl = os.path.join(base, "target_final5.stl")
        if not os.path.isfile(stl):
            self.skipTest("缺少 final5 交付样本")
        result = vd.verify(stl, require_file_verification=True)
        self.assertTrue(result["checks"]["file_verification_consistent"])
        self.assertTrue(result["metrics"]["file_verification_contract_required"])
        self.assertTrue(result["pass"], str(result["checks"]))

    def test_r35_contract_helper_rejects_malformed_objects(self):
        """畸形报告/清单/verdict 判失败而非抛栈。"""
        stl = "x.stl"
        good = {"file_verification": {"stl": os.path.abspath(stl),
                                      "pass": True, "checks": {"a": True}}}
        cases = (
            (good, {"file_verification": "oops"}, {}, stl),
            ({"file_verification": "oops"}, good, {}, stl),
            (good, good, {}, stl),
            (good, "not-a-dict", {"file_verification_pass": True}, stl),
        )
        for index, (rep, man, ver, path) in enumerate(cases):
            with self.subTest(case=index):
                _required, ok, reason = vd.file_verification_contract(
                    rep, man, ver, path)
                self.assertFalse(ok)
                self.assertIsInstance(reason, str)
                self.assertTrue(reason)


    # ---------- R36：参数契约与结构化证据写盘安全 ----------

    def _cli(self, stl, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "verify_deliverable.py"),
             "--stl", stl] + list(extra),
            cwd=ROOT, capture_output=True, text=True, timeout=180)

    def test_r36_mode_contract_accepts_plain_stl_only(self):
        """单独 --stl-only 仍是合法用法，不能被新校验误伤。"""
        self.assertIsNone(vd.check_mode_contract(True))
        self.assertIsNone(vd.check_mode_contract(
            True, require_file_verification=False))
        self.assertIsNone(vd.check_mode_contract(
            False, "r.json", "m.json", True))

    def test_r36_mode_contract_rejects_each_conflict(self):
        """三种显式要求与 stl-only 冲突时都必须抛 ValueError。"""
        cases = (
            (("--report",), (True, "r.json", None, False)),
            (("--manifest",), (True, None, "m.json", False)),
            (("--require-file-verification",), (True, None, None, True)),
            (("--report", "--manifest", "--require-file-verification"),
             (True, "r.json", "m.json", True)),
        )
        for flags, args in cases:
            with self.subTest(conflict="+".join(flags)):
                with self.assertRaises(ValueError) as ctx:
                    vd.check_mode_contract(*args)
                self.assertIn("冲突", str(ctx.exception))
                for flag in flags:
                    self.assertIn(flag, str(ctx.exception))

    def test_r36_verify_library_rejects_conflict(self):
        """库调用同样受契约约束，不能只在 CLI 层拦截。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            with self.assertRaises(ValueError):
                vd.verify(stl, stl_only=True, require_file_verification=True)
            with self.assertRaises(ValueError):
                vd.verify(stl, report_path=os.path.join(d, "m_fidelity.json"),
                          stl_only=True)
            self.assertTrue(vd.verify(stl, stl_only=True)["pass"])

    def test_r36_atomic_write_produces_valid_json_without_leftovers(self):
        """写出的结果可解析，且临时文件不残留。"""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "verify.json")
            vd.write_json_atomic(out, {"pass": True, "x": float("nan")})
            with open(out, encoding="utf-8") as f:
                data = json.load(f)
            self.assertTrue(data["pass"])
            self.assertIsNone(data["x"])  # json_safe 仍生效
            self.assertEqual(
                [n for n in os.listdir(d) if n.endswith(".tmp")], [])
            # 覆盖自身是允许的（重生成证据）
            vd.write_json_atomic(out, {"pass": False})
            with open(out, encoding="utf-8") as f:
                self.assertFalse(json.load(f)["pass"])

    def test_r36_atomic_write_refuses_to_overwrite_evidence(self):
        """--json 指向 STL / 报告 / 清单时必须拒绝且不改文件。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep = os.path.join(d, "m_fidelity.json")
            man = os.path.join(d, "m_manifest.json")
            self._box().export(stl)
            with open(rep, "w", encoding="utf-8") as f:
                json.dump({"a": 1}, f)
            with open(man, "w", encoding="utf-8") as f:
                json.dump({"b": 2}, f)
            before = {}
            for path in (stl, rep, man):
                with open(path, "rb") as f:
                    before[path] = f.read()
            for path in (stl, rep, man):
                with self.subTest(target=os.path.basename(path)):
                    with self.assertRaises(ValueError):
                        vd.write_json_atomic(path, {"pass": True}, (stl, rep, man))
            for path, content in before.items():
                with open(path, "rb") as f:
                    self.assertEqual(f.read(), content)

    def test_r36_atomic_write_missing_parent_is_clean(self):
        """父目录不存在时抛 OSError，且不留下临时文件。"""
        with tempfile.TemporaryDirectory() as d:
            missing = os.path.join(d, "no_such_dir", "verify.json")
            with self.assertRaises(FileNotFoundError):
                vd.write_json_atomic(missing, {"pass": True})
            self.assertEqual(os.listdir(d), [])

    def test_r36_cli_rejects_stl_only_conflicts(self):
        """实证缺陷：旧实现静默忽略并 rc=0 PASS，现必须 rc=2 且无 traceback。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            rep = os.path.join(d, "forged.json")
            with open(rep, "w", encoding="utf-8") as f:
                json.dump({"verdict": {"checks": {"forged": True}}}, f)
            cases = (
                ["--stl-only", "--require-file-verification"],
                ["--stl-only", "--report", rep],
                ["--stl-only", "--manifest", rep],
            )
            for extra in cases:
                with self.subTest(extra=extra[1]):
                    proc = self._cli(stl, *extra)
                    self.assertEqual(proc.returncode, 2,
                                     proc.stdout + proc.stderr)
                    self.assertIn("冲突", proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)

    def test_r36_cli_json_failure_exits_2_without_traceback(self):
        """证据写出失败不能伪装成验收 FAIL(1)，也不能抛裸 traceback。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            bad = os.path.join(d, "no_such_dir", "out.json")
            proc = self._cli(stl, "--stl-only", "--json", bad)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("结构化结果未写出", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("验收结论: PASS", proc.stdout)

    def test_r36_cli_json_cannot_overwrite_stl(self):
        """R13 同类事故回归：--json 指向 STL 时必须拒绝且 STL 字节不变。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            digest = vd._sha256(stl)
            proc = self._cli(stl, "--stl-only", "--json", stl)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("不能覆盖", proc.stderr)
            self.assertEqual(vd._sha256(stl), digest)

    def test_r36_cli_stl_only_is_clearly_labelled(self):
        """只做几何复验时不得让人误以为是完整交付验收。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            proc = self._cli(stl, "--stl-only")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("仅几何复验", proc.stdout)
            self.assertIn("不等同于完整交付验收", proc.stdout)


    # ---------- R37：畸形证据文件必须结构化拒绝，不得裸 traceback ----------

    def _seed_full_pair(self, directory, stl, report=_UNSET, manifest=_UNSET):
        """生成一套完整模式可用的最小证据文件，供顶层结构替换复现。"""
        box = self._box()
        box.export(stl)
        rep = os.path.join(directory, "m_fidelity.json")
        man = os.path.join(directory, "m_manifest.json")
        baseline = {
            "schema_version": "2.0",
            "final_mesh": {
                "faces": len(box.faces),
                "vertices": len(box.vertices),
                "extents_xyz": [float(x) for x in box.extents],
                "watertight": True, "boundary_edges": 0,
                "nonmanifold_edges": 0, "silhouette_iou": 0.9},
            "verdict": good_verdict(),
        }
        mf = {"outputs": [{"path": os.path.abspath(stl),
                           "sha256": vd._sha256(stl)}]}
        with open(rep, "w", encoding="utf-8") as f:
            json.dump(baseline if report is _UNSET else report, f)
        with open(man, "w", encoding="utf-8") as f:
            json.dump(mf if manifest is _UNSET else manifest, f)
        return rep, man

    def test_r37_clean_pair_still_passes(self):
        """加固不能误伤正常完整模式：12 项检查仍全部通过。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep, man = self._seed_full_pair(d, stl)
            result = vd.verify(stl, rep, man)
            self.assertTrue(result["pass"], result["checks"])
            self.assertEqual(len(result["checks"]), 12)

    def test_r37_load_json_object_accepts_only_objects(self):
        """纯函数：只有顶层 dict 合法，其余一律 ValueError。"""
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.json")
            with open(good, "w", encoding="utf-8") as f:
                json.dump({"a": 1}, f)
            self.assertEqual(vd.load_json_object(good, "x"), {"a": 1})
            for index, bad in enumerate(([1, 2], "str", 7, None, True)):
                path = os.path.join(d, f"bad{index}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(bad, f)
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError) as ctx:
                        vd.load_json_object(path, "fidelity.json")
                    self.assertIn("顶层不是 JSON 对象", str(ctx.exception))

    def test_r37_malformed_report_toplevel_exits_2_without_traceback(self):
        """实证缺陷：旧实现抛 AttributeError + traceback + rc=1（伪装成验收不通过）。"""
        for bad in ([1, 2], "str", 7, None):
            with tempfile.TemporaryDirectory() as d:
                stl = os.path.join(d, "m.stl")
                rep, man = self._seed_full_pair(d, stl, report=bad)
                proc = self._cli(stl, "--report", rep, "--manifest", man)
                self.assertEqual(proc.returncode, 2,
                                 proc.stdout + proc.stderr)
                self.assertIn("顶层不是 JSON 对象", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertNotIn("验收结论", proc.stdout)

    def test_r37_malformed_manifest_toplevel_exits_2_without_traceback(self):
        """清单侧同样不能有裸异常，且不能被当成「验收不通过」。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep, man = self._seed_full_pair(d, stl, manifest=[1, 2])
            proc = self._cli(stl, "--report", rep, "--manifest", man)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("顶层不是 JSON 对象", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertNotIn("验收结论", proc.stdout)

    def test_r37_malformed_extents_is_fail_not_exception(self):
        """畸形 extents_xyz 判该项 FAIL，而不是让整个复验抛栈。"""
        cases = ("abc", {"x": 1}, [1, 2], [1.0, 2.0, "NaN"], None)
        for bad in cases:
            with tempfile.TemporaryDirectory() as d:
                stl = os.path.join(d, "m.stl")
                rep, man = self._seed_full_pair(d, stl)
                with open(rep, encoding="utf-8") as f:
                    data = json.load(f)
                data["final_mesh"]["extents_xyz"] = bad
                with open(rep, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                result = vd.verify(stl, rep, man)
                self.assertFalse(result["checks"]["extents_match_report"])
                self.assertFalse(result["pass"])

    # ---------- R38：--json 证据保护补全（R36 残留风险 15 落地） ----------

    def test_r38_evidence_paths_covers_all_derived_evidence(self):
        """日志与三视图必须进入保护集合；复验结果本身不能被误伤。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            norm = {os.path.normcase(p) for p in vd.evidence_paths(stl)}
            for name in ("m.stl", "m_fidelity.json", "m_manifest.json",
                         "m_front.png", "m_back.png", "m_side.png", "run.log"):
                with self.subTest(name=name):
                    self.assertIn(
                        os.path.normcase(os.path.join(d, name)), norm)
            self.assertNotIn(
                os.path.normcase(os.path.join(d, "m_verify.json")), norm)

    def test_r38_atomic_write_rejects_non_json_targets(self):
        """通用护栏：派生列表之外的非 .json 目标同样拒绝，且不创建文件。"""
        with tempfile.TemporaryDirectory() as d:
            for name in ("out.txt", "run.log", "view.png", "noext", "m.stl"):
                path = os.path.join(d, name)
                with self.subTest(name=name):
                    with self.assertRaises(ValueError) as ctx:
                        vd.write_json_atomic(path, {"pass": True})
                    self.assertIn(".json", str(ctx.exception))
                    self.assertFalse(os.path.exists(path))
            ok = os.path.join(d, "result.json")
            vd.write_json_atomic(ok, {"pass": True})
            with open(ok, encoding="utf-8") as f:
                self.assertTrue(json.load(f)["pass"])

    def test_r38_cli_json_cannot_overwrite_log_or_views(self):
        """实证缺陷：旧实现覆盖 run.log / 三视图且仍 rc=0，现必须 rc=2 且字节不变。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            evidence = {}
            for name in ("run.log", "m_front.png", "m_back.png", "m_side.png"):
                path = os.path.join(d, name)
                payload = b"ORIGINAL-EVIDENCE-" + name.encode()
                with open(path, "wb") as f:
                    f.write(payload)
                evidence[path] = payload
            for path in evidence:
                with self.subTest(target=os.path.basename(path)):
                    proc = self._cli(stl, "--stl-only", "--json", path)
                    self.assertEqual(proc.returncode, 2,
                                     proc.stdout + proc.stderr)
                    self.assertIn("不能覆盖", proc.stderr)
                    self.assertNotIn("Traceback", proc.stderr)
                    with open(path, "rb") as f:
                        self.assertEqual(f.read(), evidence[path])

    def test_r38_cli_json_rejects_arbitrary_non_json_target(self):
        """调用方自定义命名的证据文件也受通用护栏保护。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            notes = os.path.join(d, "notes.txt")
            with open(notes, "w", encoding="utf-8") as f:
                f.write("keep me")
            proc = self._cli(stl, "--stl-only", "--json", notes)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("必须是 .json 文件", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            with open(notes, encoding="utf-8") as f:
                self.assertEqual(f.read(), "keep me")

    def test_r38_cli_json_verify_result_is_still_writable(self):
        """加固不得误伤正常用法：复验结果 JSON 仍可写出并被解析。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            out = os.path.join(d, "m_verify.json")
            proc = self._cli(stl, "--stl-only", "--json", out)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            with open(out, encoding="utf-8") as f:
                data = json.load(f)
            self.assertTrue(data["pass"])
            self.assertTrue(data["stl_only"])


    # ---------- R41：输入溯源「报告 ↔ 清单 ↔ 磁盘」三重印证（opt-in） ----------

    def _seed_provenance(self, d, stl):
        """构造带合法输入模型/参考图溯源的完整交付证据。"""
        rep, man = self._seed_full_pair(d, stl)
        src_in = os.path.abspath(os.path.join(d, "source_model.bin"))
        src_ref = os.path.abspath(os.path.join(d, "source_ref.bin"))
        with open(src_in, "wb") as f:
            f.write(b"INPUT-MODEL-BYTES" * 8)
        with open(src_ref, "wb") as f:
            f.write(b"REFERENCE-IMAGE-BYTES" * 8)
        h_in, h_ref = vd._sha256(src_in), vd._sha256(src_ref)
        with open(rep, encoding="utf-8") as f:
            r = json.load(f)
        r.update({"input_mesh": src_in, "reference": src_ref,
                  "input_mesh_sha256": h_in,
                  "reference_image_sha256": h_ref})
        with open(rep, "w", encoding="utf-8") as f:
            json.dump(r, f)
        with open(man, encoding="utf-8") as f:
            m = json.load(f)
        m["input"] = {"path": src_in, "bytes": os.path.getsize(src_in),
                      "sha256": h_in}
        m["reference_image"] = {"path": src_ref,
                                "bytes": os.path.getsize(src_ref),
                                "sha256": h_ref}
        with open(man, "w", encoding="utf-8") as f:
            json.dump(m, f)
        return rep, man

    @staticmethod
    def _patch_json(path, mutate):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        mutate(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_r41_default_mode_output_is_unchanged(self):
        """默认关闭：仍是 12 项，且结果里不出现任何 R41 新键。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep, man = self._seed_provenance(d, stl)
            result = vd.verify(stl, rep, man)
            self.assertTrue(result["pass"], result["checks"])
            self.assertEqual(len(result["checks"]), 12)
            self.assertNotIn("source_provenance_valid", result["checks"])
            self.assertNotIn("require_source_provenance", result)
            self.assertNotIn("source_provenance_reason", result["metrics"])

    def test_r41_clean_provenance_passes_with_three_way_agreement(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep, man = self._seed_provenance(d, stl)
            result = vd.verify(stl, rep, man,
                               require_source_provenance=True)
            self.assertTrue(result["checks"]["source_provenance_valid"])
            self.assertTrue(result["pass"], result["checks"])
            self.assertEqual(len(result["checks"]), 13)
            self.assertIsNone(result["metrics"]["source_provenance_reason"])
            sources = result["metrics"]["source_provenance_sources"]
            self.assertEqual(len(sources), 2)
            self.assertTrue(all("disk_sha256" in s for s in sources))

    def test_r41_tampered_or_deleted_report_hashes_fail(self):
        """实证缺陷：改假值 / 全零 / 删除 / null 旧实现仍 12/12 PASS。"""
        cases = (
            ("任意字符串", lambda r: r.__setitem__("input_mesh_sha256", "TAMPERED_INPUT")),
            ("全零", lambda r: r.__setitem__("reference_image_sha256", "0" * 64)),
            ("整段删除", lambda r: r.pop("input_mesh_sha256")),
            ("null", lambda r: r.__setitem__("reference_image_sha256", None)),
        )
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep, man = self._seed_provenance(d, stl)
            for label, mutate in cases:
                with self.subTest(case=label):
                    self._patch_json(rep, mutate)
                    base = vd.verify(stl, rep, man)
                    self.assertTrue(base["pass"], "默认模式不应改变历史结论")
                    strict = vd.verify(stl, rep, man,
                                       require_source_provenance=True)
                    self.assertFalse(strict["checks"]["source_provenance_valid"])
                    self.assertFalse(strict["pass"])
                    self.assertTrue(strict["metrics"]["source_provenance_reason"])
                    # 复原，让各 subTest 互不干扰
                    self._seed_provenance(d, stl)

    def test_r41_manifest_is_an_independent_second_source(self):
        """只篡改清单哈希（报告仍正确）也必须被拒绝。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep, man = self._seed_provenance(d, stl)
            self._patch_json(man, lambda m: m["input"].__setitem__(
                "sha256", "a" * 64))
            result = vd.verify(stl, rep, man,
                               require_source_provenance=True)
            self.assertFalse(result["checks"]["source_provenance_valid"])
            self.assertFalse(result["pass"])
            self.assertIn("input.sha256", result["metrics"]["source_provenance_reason"])

    def test_r41_path_disagreement_and_missing_source_fail_cleanly(self):
        """路径不一致 / 源文件缺失应判 FAIL，不得抛 OSError 变成 rc=2。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep, man = self._seed_provenance(d, stl)
            other = os.path.join(d, "another.png")
            with open(other, "wb") as f:
                f.write(b"OTHER")
            self._patch_json(rep, lambda r: r.__setitem__(
                "input_mesh", os.path.abspath(other)))
            r1 = vd.verify(stl, rep, man, require_source_provenance=True)
            self.assertFalse(r1["checks"]["source_provenance_valid"])
            self.assertIn("不同的源文件路径",
                          r1["metrics"]["source_provenance_reason"])
            self._seed_provenance(d, stl)
            self._patch_json(man, lambda m: m["reference_image"].__setitem__(
                "path", os.path.join(d, "gone.png")))
            r2 = vd.verify(stl, rep, man, require_source_provenance=True)
            self.assertFalse(r2["checks"]["source_provenance_valid"])
            self.assertIn("不存在或不可读",
                          r2["metrics"]["source_provenance_reason"])

    def test_r41_mode_contract_rejects_stl_only_with_provenance(self):
        """R36 契约延伸：新 flag 与 --stl-only 冲突不得被静默忽略。"""
        with self.assertRaises(ValueError) as ctx:
            vd.check_mode_contract(True, require_source_provenance=True)
        self.assertIn("--require-source-provenance", str(ctx.exception))
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            self._box().export(stl)
            proc = self._cli(stl, "--stl-only", "--require-source-provenance")
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("--require-source-provenance", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            rep, man = self._seed_provenance(d, stl)
            ok = self._cli(stl, "--require-source-provenance",
                           "--report", rep, "--manifest", man)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("输入溯源", ok.stdout)
            self.assertIn("PASS  source_provenance_valid", ok.stdout)

    def test_r41_real_final5_provenance_passes(self):
        """真实交付样本三方一致，新门禁不得误伤已交付成品。"""
        base = os.path.join(ROOT, "print_ready", "_verify2", "final5")
        stl = os.path.join(base, "target_final5.stl")
        if not os.path.isfile(stl):
            self.skipTest("缺少 final5 交付样本")
        result = vd.verify(stl, require_source_provenance=True)
        self.assertTrue(result["checks"]["source_provenance_valid"],
                        result["metrics"].get("source_provenance_reason"))
        self.assertTrue(result["pass"], result["checks"])
        self.assertEqual(len(result["checks"]), 13)


    # ---------- R42：verdict 数值判据必须可按已落盘阈值重算 ----------

    def _r42_report(self, d, stl=None):
        """复制真实 final5 报告/清单到临时目录，STL 与清单保持原位。"""
        base = os.path.join(ROOT, "print_ready", "_verify2", "final5")
        src = os.path.join(base, "target_final5_fidelity.json")
        rep = os.path.join(d, "m_fidelity.json")
        with open(src, encoding="utf-8") as f:
            data = json.load(f)
        with open(rep, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return rep, os.path.join(base, "target_final5_manifest.json"), \
            os.path.join(base, "target_final5.stl")

    def test_r42_tolerance_constant_is_shared_both_sides(self):
        import convert_3d as c
        self.assertEqual(c.ASPECT_SELF_CHECK_TOL_PCT,
                         vd.ASPECT_SELF_CHECK_TOL_PCT)
        self.assertEqual(vd.ASPECT_SELF_CHECK_TOL_PCT, 1.0)

    def test_r42_pure_function_recomputes_both_numeric_checks(self):
        checks = dict.fromkeys(vd.VERDICT_KNOWN_CHECKS, True)
        report = {"min_iou": 0.55, "aspect_error_pct": 0.0,
                  "final_mesh": {"silhouette_iou": 0.8281}}
        manifest = {"parameters": {"min_iou": 0.55}}
        self.assertEqual(
            vd.verdict_numeric_consistency(report, manifest, checks),
            (True, None))
        bad = (
            ("IoU 改低", lambda r: r["final_mesh"].__setitem__("silhouette_iou", 0.20)),
            ("阈值抬高", lambda r: r.__setitem__("min_iou", 0.99)),
            ("宽高比误差改大", lambda r: r.__setitem__("aspect_error_pct", 99.0)),
            ("IoU 畸形", lambda r: r["final_mesh"].__setitem__("silhouette_iou", "abc")),
            ("阈值畸形", lambda r: r.__setitem__("min_iou", None)),
            ("aspect 畸形", lambda r: r.__setitem__("aspect_error_pct", float("nan"))),
        )
        for label, mutate in bad:
            with self.subTest(case=label):
                r = copy.deepcopy(report)
                mutate(r)
                ok, reason = vd.verdict_numeric_consistency(r, manifest, checks)
                self.assertFalse(ok, label)
                self.assertTrue(reason)

    def test_r42_threshold_double_source_is_consistent(self):
        checks = dict.fromkeys(vd.VERDICT_KNOWN_CHECKS, True)
        base = {"aspect_error_pct": 0.0,
                "final_mesh": {"silhouette_iou": 0.8281}}
        ok, reason = vd.verdict_numeric_consistency(
            dict(base, min_iou=0.55), {"parameters": {"min_iou": 0.90}}, checks)
        self.assertFalse(ok)
        self.assertIn("不一致", reason)
        # 只有清单有阈值：仍可重算，不被单方删字段绕过
        ok2, reason2 = vd.verdict_numeric_consistency(
            dict(base), {"parameters": {"min_iou": 0.55}}, checks)
        self.assertEqual((ok2, reason2), (True, None))
        # 两处都无阈值：兼容旧报告，跳过数值重算
        ok3, reason3 = vd.verdict_numeric_consistency(dict(base), {}, checks)
        self.assertEqual((ok3, reason3), (True, None))
        # verdict 判据缺失也不该抛栈
        ok4, _ = vd.verdict_numeric_consistency(
            dict(base, min_iou=0.55), {}, {"aspect_self_check": True})
        self.assertFalse(ok4)

    def test_r42_verify_detects_numeric_contradictions(self):
        """实证缺陷：4 类数值篡改修复前仍 12/12 PASS，现必须 FAIL。"""
        base = os.path.join(ROOT, "print_ready", "_verify2", "final5")
        if not os.path.isfile(os.path.join(base, "target_final5.stl")):
            self.skipTest("缺少 final5 交付样本")
        cases = (
            ("IoU 0.20", lambda r: r["final_mesh"].__setitem__("silhouette_iou", 0.20)),
            ("min_iou 0.99", lambda r: r.__setitem__("min_iou", 0.99)),
            ("aspect 99", lambda r: r.__setitem__("aspect_error_pct", 99.0)),
            ("阈值两处同时抬高", lambda r: r.__setitem__("min_iou", 0.99)),
        )
        with tempfile.TemporaryDirectory() as d:
            for label, mutate in cases:
                with self.subTest(case=label):
                    rep, man, stl = self._r42_report(d)
                    self._patch_json(rep, mutate)
                    if label == "阈值两处同时抬高":
                        # 清单也跟着改，验证「两处都改」仍按重算结论拒绝
                        m2 = os.path.join(d, "m_manifest.json")
                        with open(man, encoding="utf-8") as f:
                            m = json.load(f)
                        m["parameters"]["min_iou"] = 0.99
                        with open(m2, "w", encoding="utf-8") as f:
                            json.dump(m, f)
                        man = m2
                    out = vd.verify(stl, rep, man)
                    self.assertFalse(out["checks"]["verdict_consistent"], label)
                    self.assertFalse(out["pass"], label)
                    self.assertTrue(out["metrics"]["verdict_reason"])
                    self.assertIn("重算", out["metrics"]["verdict_reason"])

    def test_r42_default_output_is_byte_identical(self):
        """数值重算不得改变正常报告的 12 项口径与交付证据字节。"""
        base = os.path.join(ROOT, "print_ready", "_verify2", "final5")
        stl = os.path.join(base, "target_final5.stl")
        verify_json = os.path.join(base, "target_final5_verify.json")
        if not os.path.isfile(stl):
            self.skipTest("缺少 final5 交付样本")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "probe.json")
            result = vd.verify(stl)
            vd.write_json_atomic(out, result)
            self.assertEqual(len(result["checks"]), 12)
            self.assertIsNone(result["metrics"]["verdict_reason"])
            with open(out, "rb") as f, open(verify_json, "rb") as g:
                self.assertEqual(f.read(), g.read())

    def test_r42_legacy_pair_without_thresholds_still_passes(self):
        """兼容不含 min_iou / aspect_error_pct 的最小合成证据，不误伤。"""
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            rep, man = self._seed_full_pair(d, stl)
            result = vd.verify(stl, rep, man)
            self.assertTrue(result["pass"], result["checks"])
            self.assertEqual(len(result["checks"]), 12)
            self.assertIsNone(result["metrics"]["verdict_reason"])

    def test_r42_real_final5_and_final4_still_pass(self):
        for folder, prefix in (("final5", "target_final5"),
                               ("final4", "target_final4")):
            with self.subTest(folder=folder):
                base = os.path.join(ROOT, "print_ready", "_verify2", folder)
                stl = os.path.join(base, prefix + ".stl")
                if not os.path.isfile(stl):
                    continue
                result = vd.verify(stl)
                self.assertTrue(result["pass"], result["checks"])
                self.assertIsNone(result["metrics"]["verdict_reason"])


# ---------- R43：交付证据（三视图 / run.log）完整性闭环 ----------

def _png_chunk(ctype, payload, bad_crc=False):
    import struct
    import zlib
    crc = zlib.crc32(ctype + payload) & 0xFFFFFFFF
    if bad_crc:
        crc ^= 0x1
    return (struct.pack(">I", len(payload)) + ctype + payload
            + struct.pack(">I", crc))


def _make_png(path, value=200, size=8, bad_crc=False, truncate=False):
    """零依赖构造一张结构完好的小 PNG，供证据容器校验做正/负例。"""
    import struct
    import zlib
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes((value, value, value)) * size
    data = (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(row * size), bad_crc)
            + _png_chunk(b"IEND", b""))
    if truncate:
        data = data[:-6]
    with open(path, "wb") as handle:
        handle.write(data)


@unittest.skipUnless(HAS_TRIMESH, "trimesh 不可用")
class TestR43EvidenceIndex(unittest.TestCase):
    """实证：三视图被替换/删除/复制冒充时旧复验仍 12/12 PASS，现须能拒。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")

    def _seed(self, directory, values=(200, 120, 60)):
        """在临时目录构造一套自洽的迷你交付，绝不触碰真实产物。

        R46：生成侧现在要与复验侧共用几何绑定判据，占位 STL + 纯色小 PNG
        已不再合法。这里造一个真实可解析的 ASCII STL（包围盒 10×10×40，
        front/back/side 期望比例均为 0.25）与三张 128² 深背景渲染图
        （前景轮廓包围盒 24×96，比例同为 0.25），三图用不同亮度保证哈希
        互异。R51 把正例从纯色矩形升级为轮廓状，夹具升级而非放宽判据。
        """
        stl = os.path.join(directory, "m.stl")
        with open(stl, "w", encoding="ascii") as handle:
            handle.write(
                "solid mini\n facet normal 0 0 1\n  outer loop\n"
                "   vertex 0 0 0\n   vertex 10 0 0\n   vertex 0 10 40\n"
                "  endloop\n endfacet\nendsolid mini\n")
        for view, value in zip(("front", "back", "side"), values):
            fg = 150 + (int(value) % 47)  # 150..196，恒高于背景 58+40
            _make_silhouette_png(
                os.path.join(directory, "m_%s.png" % view),
                size=128, rect=(24, 96), bg=58, fg=fg)
        with open(os.path.join(directory, "run.log"), "w", encoding="utf-8") as f:
            f.write("[*] run log for evidence index test\n")
        index = vd.build_evidence_index(stl)
        vd.write_json_atomic(vd.evidence_index_path(stl), index)
        return stl, index

    def _run(self, stl, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "verify_deliverable.py"),
             "--stl", stl] + list(extra),
            cwd=ROOT, capture_output=True, text=True, timeout=180)

    def test_r43_png_container_accepts_valid_and_rejects_damage(self):
        """零依赖 CRC 校验：垃圾字节 / 截断 / CRC 改坏 / 缺 IEND 全拒。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ok.png")
            _make_png(p)
            ok, reason, w, h = vd.png_container_valid(p)
            self.assertTrue(ok, reason)
            self.assertEqual((w, h), (8, 8))
            cases = {}
            junk = os.path.join(d, "junk.png")
            with open(junk, "wb") as f:
                f.write(b"NOT_A_PNG_AT_ALL")
            cases["junk"] = junk
            trunc = os.path.join(d, "trunc.png")
            _make_png(trunc, truncate=True)
            cases["truncated"] = trunc
            crc = os.path.join(d, "crc.png")
            _make_png(crc, bad_crc=True)
            cases["bad_crc"] = crc
            niend = os.path.join(d, "noend.png")
            with open(p, "rb") as src:
                head = src.read()
            with open(niend, "wb") as f:
                f.write(head[:-12])
            cases["no_iend"] = niend
            for label, path in cases.items():
                with self.subTest(case=label):
                    ok, reason, _, _ = vd.png_container_valid(path)
                    self.assertFalse(ok, label)
                    self.assertTrue(reason)

    def test_r43_build_index_is_complete_and_clean_pair_passes(self):
        """基线含 4 项 + STL 锚点；干净迷你交付必须全绿。"""
        with tempfile.TemporaryDirectory() as d:
            stl, index = self._seed(d)
            self.assertEqual(index["schema_version"], vd.EVIDENCE_INDEX_SCHEMA)
            self.assertEqual(len(index["evidence"]), len(vd.EVIDENCE_ITEMS))
            self.assertEqual(
                {e["role"] for e in index["evidence"]},
                {role for role, _, _ in vd.EVIDENCE_ITEMS})
            self.assertEqual(index["stl"]["sha256"], vd._sha256(stl))
            ok, reason, details = vd.evidence_index_checks(stl)
            self.assertTrue(ok, reason)
            self.assertIsNone(reason)
            self.assertEqual(len(details), 4)

    def test_r43_replaced_or_deleted_evidence_is_rejected(self):
        """这次真实事故的复现（隔离副本）：垃圾字节 / 删除 / 复制冒充 / 空日志。"""
        with tempfile.TemporaryDirectory() as d:
            stl, _ = self._seed(d)
            front = os.path.join(d, "m_front.png")
            back = os.path.join(d, "m_back.png")
            side = os.path.join(d, "m_side.png")
            log = os.path.join(d, "run.log")

            with open(front, "wb") as f:
                f.write(b"NOT_A_PNG_AT_ALL")
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertFalse(ok)
            self.assertIn("front_view", reason)

            self._seed(d)
            import shutil
            shutil.copyfile(back, front)  # 复制冒充：合法 PNG，但内容不是正面
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertFalse(ok)
            self.assertTrue("复制冒充" in reason or "SHA256" in reason, reason)

            self._seed(d)
            os.remove(side)
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertFalse(ok)
            self.assertIn("已丢失", reason)

            self._seed(d)
            with open(log, "w", encoding="utf-8") as f:
                f.write("  \n")
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertFalse(ok)
            self.assertIn("为空", reason)

    def test_r43_index_tampering_and_path_traversal_are_rejected(self):
        """基线自身被改哈希/删条目/写越界路径/换顶层结构均结构化 FAIL。"""
        with tempfile.TemporaryDirectory() as d:
            stl, index = self._seed(d)
            ipath = vd.evidence_index_path(stl)

            def mutate(fn, source=None):
                data = copy.deepcopy(source if source is not None else index)
                fn(data)
                vd.write_json_atomic(ipath, data)
                return vd.evidence_index_checks(stl)

            ok, reason, _ = mutate(lambda x: x["evidence"][0].update(
                sha256="0" * 64))
            self.assertFalse(ok)
            self.assertIn("SHA256", reason)
            ok, reason, _ = mutate(lambda x: x["evidence"].pop())
            self.assertFalse(ok)
            self.assertIn("条目集合不完整", reason)
            ok, reason, _ = mutate(lambda x: x["evidence"][0].update(
                file="../evil.png"))
            self.assertFalse(ok)
            self.assertIn("路径穿越", reason)
            ok, reason, _ = mutate(lambda x: x.update(schema_version="9.9"))
            self.assertFalse(ok)
            self.assertIn("schema_version", reason)
            with open(ipath, "w", encoding="utf-8") as f:
                json.dump([1, 2, 3], f)
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertFalse(ok)
            self.assertIn("结构非法", reason)

            # STL 锚点被改也应拒绝
            vd.write_json_atomic(ipath, index)
            with open(stl, "ab") as f:
                f.write(b"X")
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertFalse(ok)
            self.assertIn("STL", reason)

    def test_r43_mode_contract_covers_new_flags(self):
        """--stl-only 冲突与自写自验都必须显式拒绝。"""
        with self.assertRaises(ValueError) as ctx:
            vd.check_mode_contract(True, require_evidence_index=True)
        self.assertIn("--require-evidence-index", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            vd.check_mode_contract(False, write_evidence_index=True,
                                   require_evidence_index=True)
        self.assertIn("互斥", str(ctx.exception))
        self.assertIsNone(vd.check_mode_contract(
            False, require_evidence_index=True))

    def test_r43_evidence_index_is_protected_from_json_overwrite(self):
        """R38 保护集合必须包含新基线，--json 不得覆写它。"""
        with tempfile.TemporaryDirectory() as d:
            stl, _ = self._seed(d)
            ipath = vd.evidence_index_path(stl)
            with open(ipath, "rb") as f:
                before = f.read()
            self.assertIn(os.path.normcase(ipath),
                          {os.path.normcase(p) for p in vd.evidence_paths(stl)})
            with self.assertRaises(ValueError):
                vd.write_json_atomic(ipath, {"pass": True},
                                     vd.evidence_paths(stl))
            with open(ipath, "rb") as f:
                self.assertEqual(f.read(), before)

    def test_r43_cli_write_and_conflict_contracts(self):
        """CLI：写基线独立动作、两种冲突 rc=2 且无 traceback。"""
        with tempfile.TemporaryDirectory() as d:
            stl = self._seed(d)[0]
            ipath = vd.evidence_index_path(stl)
            os.remove(ipath)
            written = self._run(stl, "--write-evidence-index")
            self.assertEqual(written.returncode, 0, written.stderr)
            self.assertTrue(os.path.isfile(ipath))
            self.assertIn("证据基线已生成", written.stdout)
            for extra in (("--write-evidence-index",
                           "--require-evidence-index"),
                          ("--stl-only", "--require-evidence-index")):
                with self.subTest(extra=extra):
                    out = self._run(stl, *extra)
                    self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
                    self.assertNotIn("Traceback", out.stderr)
                    self.assertIn("--require-evidence-index", out.stderr)

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r43_real_final5_default_unchanged_and_gate_passes(self):
        """真实交付：默认仍 12 项且逐字节不变；启用门禁 13 项全过。"""
        with open(os.path.splitext(self.REAL_STL)[0] + "_verify.json",
                  encoding="utf-8") as f:
            shipped = json.load(f)
        plain = vd.verify(self.REAL_STL)
        self.assertEqual(len(plain["checks"]), 12)
        self.assertNotIn("evidence_index_valid", plain["checks"])
        self.assertEqual(plain["checks"], shipped["checks"])
        gated = vd.verify(self.REAL_STL, require_evidence_index=True)
        self.assertEqual(len(gated["checks"]), 13)
        self.assertTrue(gated["checks"]["evidence_index_valid"])
        self.assertTrue(gated["pass"], gated["metrics"]["evidence_index_reason"])
        out = self._run(self.REAL_STL, "--require-evidence-index")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("交付证据", out.stdout)


# ---------- R44：三视图像素轮廓与 STL 几何绑定 ----------

def _make_render_like_png(path, size=768, rect=(300, 686), bg=58, fg=170):
    """零依赖造一张「另一模型」的正交渲染图：深背景 + 亮色矩形轮廓。

    矩形宽高比 300/686≈0.437，与 final5 侧视图期望 0.197 明显不同；
    容器/CRC 完好、尺寸仍是 768²，因此 R43 的哈希+容器校验无法识破。
    """
    import struct
    import zlib
    x0 = (size - rect[0]) // 2
    x1 = x0 + rect[0]
    y0 = (size - rect[1]) // 2
    y1 = y0 + rect[1]
    bg_row = b"\x00" + bytes((bg, bg, bg)) * size
    fg_row = (b"\x00" + bytes((bg, bg, bg)) * x0
              + bytes((fg, fg, fg)) * rect[0]
              + bytes((bg, bg, bg)) * (size - x1))
    rows = b"".join(fg_row if y0 <= y < y1 else bg_row
                    for y in range(size))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(rows, 6))
            + _png_chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(data)


def _make_silhouette_png(path, size=128, rect=(24, 96), bg=58, fg=170):
    """R51：造一张「轮廓状」正交渲染图，替代此前作为正例的纯色矩形。

    包围盒仍是 rect（比例不变），但逐行宽度按头/颈/身/裙/腿起伏，填充率
    约 0.7、行宽变异约 0.3 —— 与真实三视图同属「轮廓」而非色块。产品
    判据收紧后，夹具必须同步升级，绝不靠放宽阈值让旧矩形继续蒙混过关。
    """
    import struct
    import zlib
    w, h = rect
    x0 = (size - w) // 2
    y0 = (size - h) // 2
    bg_row = b"\x00" + bytes((bg, bg, bg)) * size
    rows = []
    for y in range(size):
        if not (y0 <= y < y0 + h):
            rows.append(bg_row)
            continue
        t = (y - y0) / float(max(h - 1, 1))
        if t < 0.18:
            width = max(1, int(w * 0.88))
        elif t < 0.30:
            width = max(1, int(w * 0.50))
        elif t < 0.58:
            width = max(1, int(w * 0.76))
        elif t < 0.72:
            width = w
        else:
            width = max(1, int(w * 0.44))
        if (y - y0) % 9 == 0:
            width = max(1, width - 1)
        left = x0 + (w - width) // 2
        rows.append(b"\x00" + bytes((bg, bg, bg)) * left
                    + bytes((fg, fg, fg)) * width
                    + bytes((bg, bg, bg)) * (size - left - width))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
            + _png_chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(data)


def _make_diamond_png(path, size=768, rect=(174, 686), bg=58, fg=170):
    """R56 负例：非矩形、统计量完全像轮廓，但形状与真实 STL 不同。"""
    import struct
    import zlib
    w, h = rect
    x0, y0 = (size - w) // 2, (size - h) // 2
    rows = []
    for y in range(size):
        row = b"\x00" + bytes((bg, bg, bg)) * size
        if y0 <= y < y0 + h:
            t = (y - y0) / float(max(h - 1, 1))
            width = max(1, int(w * min(t * 2, (1 - t) * 2)))
            left = x0 + (w - width) // 2
            row = (b"\x00" + bytes((bg, bg, bg)) * left
                   + bytes((fg, fg, fg)) * width
                   + bytes((bg, bg, bg)) * (size - left - width))
        rows.append(row)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
                     + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
                     + _png_chunk(b"IEND", b""))


class TestR44PngDecoder(unittest.TestCase):
    """纯标准库解码器：不依赖 trimesh / PIL / numpy，缺依赖环境也要能跑。"""

    def test_r44_decoder_rejects_broken_pixels_without_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            junk = os.path.join(d, "junk.png")
            with open(junk, "wb") as f:
                f.write(b"NOT_A_PNG_AT_ALL")
            bad_filter = os.path.join(d, "bad_filter.png")
            import struct
            import zlib
            size = 8
            ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
            rows = b"".join(b"\x09" + bytes((200, 200, 200)) * size
                            for _ in range(size))
            with open(bad_filter, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n"
                        + _png_chunk(b"IHDR", ihdr)
                        + _png_chunk(b"IDAT", zlib.compress(rows))
                        + _png_chunk(b"IEND", b""))
            short_idat = os.path.join(d, "short.png")
            with open(short_idat, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n"
                        + _png_chunk(b"IHDR", ihdr)
                        + _png_chunk(b"IDAT", zlib.compress(b"\x00" * 25)[:6])
                        + _png_chunk(b"IEND", b""))
            blank = os.path.join(d, "blank.png")
            _make_png(blank, value=58, size=64)
            for label, path in (("junk", junk), ("bad_filter", bad_filter),
                                ("short_idat", short_idat), ("blank", blank)):
                with self.subTest(case=label):
                    ok, reason, _ = vd.png_foreground_bbox(path)
                    self.assertFalse(ok, label)
                    self.assertTrue(reason, label)

    def test_r44_foreign_render_has_distinct_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "foreign.png")
            _make_render_like_png(path)
            ok, reason, info = vd.png_foreground_bbox(path)
            self.assertTrue(ok, reason)
            self.assertGreater(info["aspect_ratio"], 0.4)
            self.assertTrue(vd.png_container_valid(path)[0])

    def test_r44_binding_rejects_malformed_extents(self):
        with tempfile.TemporaryDirectory() as d:
            views = {"front_view": os.path.join(d, "f.png"),
                     "back_view": os.path.join(d, "b.png"),
                     "side_view": os.path.join(d, "s.png")}
            for path in views.values():
                _make_render_like_png(path)
            for bad in (None, ["x", 1, 1], [38, 29, 0], [38, 29],
                        [38, 29, float("nan")]):
                with self.subTest(extents=repr(bad)):
                    ok, reason, _ = vd.render_binding_checks(bad, views)
                    self.assertFalse(ok)
                    self.assertIn("extents_xyz", reason)


@unittest.skipUnless(HAS_TRIMESH, "trimesh 不可用")
class TestR44RenderBinding(unittest.TestCase):
    """实证：R43 的「哈希基线 + 容器校验」无法证明像素来自本次 STL。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")
    EXTENTS = [38.6374, 29.9549, 152.2445]

    @staticmethod
    def _views(stl):
        return {r: p for r, _, k, p in vd._evidence_names(stl)
                if k == "png"}

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r44_real_views_are_bound_to_stl_geometry(self):
        views = self._views(self.REAL_STL)
        ok, reason, details = vd.render_binding_checks(self.EXTENTS, views)
        self.assertTrue(ok, reason)
        self.assertIsNone(reason)
        self.assertEqual(len(details), 3)
        for item in details:
            self.assertTrue(item["ok"], item)
            self.assertLessEqual(item["error_pct"], vd.RENDER_RATIO_TOL_PCT)
        roles = {i["role"]: i for i in details}
        # front/back 期望 X/Z，side 期望 Y/Z，三者不可混用。
        self.assertAlmostEqual(roles["front_view"]["expected_ratio"],
                               roles["back_view"]["expected_ratio"], places=5)
        self.assertLess(roles["side_view"]["expected_ratio"],
                        roles["front_view"]["expected_ratio"])

    def test_r44_foreign_render_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            views = {}
            for role in ("front_view", "back_view", "side_view"):
                path = os.path.join(d, role + ".png")
                # 前两视图给「正面比例」的图，第三视图给明显不符的图。
                _make_render_like_png(
                    path, rect=(174, 686) if role != "side_view" else (300, 686))
                views[role] = path
            ok, reason, details = vd.render_binding_checks(self.EXTENTS, views)
            self.assertFalse(ok)
            self.assertIn("疑似来自其它模型", reason)
            self.assertIn("side_view", reason)
            self.assertFalse([i for i in details
                              if i["role"] == "side_view"][0]["ok"])

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r44_replaced_render_with_updated_baseline_is_rejected(self):
        """核心实证：换图并同步改基线后，R43 仍放行，R44 必须拒绝。"""
        import shutil
        src = os.path.dirname(self.REAL_STL)
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "target_final5.stl")
            shutil.copyfile(self.REAL_STL, stl)
            for suffix in ("_fidelity.json", "_manifest.json", "_evidence.json",
                           "_front.png", "_back.png", "_side.png"):
                shutil.copyfile(os.path.join(src, "target_final5" + suffix),
                                os.path.join(d, "target_final5" + suffix))
            shutil.copyfile(os.path.join(src, "run.log"),
                            os.path.join(d, "run.log"))
            # 清单按绝对路径定位 STL，副本需同步改写，保证其它 12 项不误伤。
            manifest_path = os.path.join(d, "target_final5_manifest.json")
            report_path = os.path.join(d, "target_final5_fidelity.json")
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            with open(report_path, encoding="utf-8") as f:
                report = json.load(f)
            for entry in manifest["outputs"]:
                if str(entry.get("path", "")).lower().endswith(
                        "target_final5.stl"):
                    entry["path"] = stl
            # R35 契约要求两处 file_verification.stl 都指向待复验 STL；
            # 副本必须同步改写，否则会把夹具自身的不自洽误算成产品缺陷。
            for obj in (manifest, report):
                fv = obj.get("file_verification")
                if isinstance(fv, dict):
                    fv["stl"] = stl
            vd.write_json_atomic(manifest_path, manifest)
            vd.write_json_atomic(report_path, report)
            # 换进一张别的模型渲染图，并把基线改成「自洽」的新哈希。
            side = os.path.join(d, "target_final5_side.png")
            _make_render_like_png(side)
            index_path = vd.evidence_index_path(stl)
            with open(index_path, encoding="utf-8") as f:
                index = json.load(f)
            with open(side, "rb") as f:
                payload = f.read()
            for entry in index["evidence"]:
                if entry["role"] == "side_view":
                    entry["sha256"] = vd._sha256(side)
                    entry["bytes"] = len(payload)
                    entry["width"] = entry["height"] = 768
            vd.write_json_atomic(index_path, index)

            # 旧口径：容器完好、哈希与基线一致、三视图互异 -> 仍判通过。
            ok43, reason43, _ = vd.evidence_index_checks(stl)
            self.assertTrue(ok43, reason43)
            # 新口径：几何绑定必须拒绝，且只拒绝这一项。
            gated = vd.verify(stl, require_evidence_index=True)
            self.assertFalse(gated["checks"]["evidence_index_valid"])
            self.assertIn("疑似来自其它模型",
                          gated["metrics"]["evidence_index_reason"])
            others = {k: v for k, v in gated["checks"].items()
                      if k != "evidence_index_valid"}
            self.assertEqual(len(others), 12)
            self.assertTrue(all(others.values()), others)
            # 默认口径不变：仍 12 项且通过。
            plain = vd.verify(stl)
            self.assertEqual(len(plain["checks"]), 12)
            self.assertTrue(plain["pass"], plain["checks"])

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r44_default_output_is_byte_identical_to_shipped(self):
        shipped_path = (os.path.splitext(self.REAL_STL)[0]
                        + "_verify.json")
        with open(shipped_path, encoding="utf-8") as f:
            shipped_text = f.read()
        rendered = json.dumps(vd.json_safe(vd.verify(self.REAL_STL)),
                              ensure_ascii=False, indent=2, allow_nan=False)
        self.assertEqual(rendered, shipped_text)


# ---------- R45：R44 像素解码器的资源上限与畸形 IHDR ----------

def _make_oversized_png(path, width, height):
    """构造 CRC 完好、但 IHDR 声明超大尺寸的 PNG（容器校验会通过）。"""
    import struct
    import zlib
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(b"\x00" * 25))
            + _png_chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(data)


class TestR45DecoderLimits(unittest.TestCase):
    """不依赖 trimesh：畸形尺寸必须结构化 FAIL，绝不抛栈。"""

    def test_r45_oversized_ihdr_is_structured_fail(self):
        with tempfile.TemporaryDirectory() as d:
            for label, (w, h) in (("u32_max", (4294967295, 4294967295)),
                                  ("over_pixels", (8192, 8192)),
                                  ("over_width", (8192, 8))):
                path = os.path.join(d, label + ".png")
                _make_oversized_png(path, w, h)
                with self.subTest(case=label):
                    # 容器层仍然判「完好」——拒绝理由必须由解码层给出。
                    self.assertTrue(vd.png_container_valid(path)[0])
                    ok, reason, _ = vd.png_foreground_bbox(path)
                    self.assertFalse(ok)
                    self.assertIn("上限", reason)
                    ok2, reason2, details = vd.render_binding_checks(
                        [38.6, 29.9, 152.2],
                        {"front_view": path, "back_view": path,
                         "side_view": path})
                    self.assertFalse(ok2)
                    self.assertIn("上限", reason2)
                    self.assertEqual(len(details), 3)
                    self.assertTrue(all(not i["ok"] for i in details))

    def test_r45_limits_do_not_reject_normal_render(self):
        """上限必须留足余量：768² 正常渲染图仍可解码并参与绑定。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "normal.png")
            _make_render_like_png(path)
            ok, reason, info = vd.png_foreground_bbox(path)
            self.assertTrue(ok, reason)
            self.assertGreater(info["aspect_ratio"], 0.4)


@unittest.skipUnless(HAS_TRIMESH, "trimesh 不可用")
class TestR45Integration(unittest.TestCase):
    """实证：畸形证据不得把「验收不通过 rc=1」退化成裸 traceback。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r45_cli_rejects_oversized_evidence_without_traceback(self):
        import shutil
        src = os.path.dirname(self.REAL_STL)
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "target_final5.stl")
            shutil.copyfile(self.REAL_STL, stl)
            for suffix in ("_fidelity.json", "_manifest.json", "_evidence.json",
                           "_front.png", "_back.png", "_side.png"):
                shutil.copyfile(os.path.join(src, "target_final5" + suffix),
                                os.path.join(d, "target_final5" + suffix))
            shutil.copyfile(os.path.join(src, "run.log"),
                            os.path.join(d, "run.log"))
            manifest_path = os.path.join(d, "target_final5_manifest.json")
            report_path = os.path.join(d, "target_final5_fidelity.json")
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            with open(report_path, encoding="utf-8") as f:
                report = json.load(f)
            for entry in manifest["outputs"]:
                if str(entry.get("path", "")).lower().endswith(
                        "target_final5.stl"):
                    entry["path"] = stl
            for obj in (manifest, report):
                fv = obj.get("file_verification")
                if isinstance(fv, dict):
                    fv["stl"] = stl
            vd.write_json_atomic(manifest_path, manifest)
            vd.write_json_atomic(report_path, report)

            front = os.path.join(d, "target_final5_front.png")
            _make_oversized_png(front, 4294967295, 4294967295)
            index_path = vd.evidence_index_path(stl)
            with open(index_path, encoding="utf-8") as f:
                index = json.load(f)
            for entry in index["evidence"]:
                if entry["role"] == "front_view":
                    entry["sha256"] = vd._sha256(front)
                    entry["bytes"] = os.path.getsize(front)
            vd.write_json_atomic(index_path, index)

            out = subprocess.run(
                [sys.executable, os.path.join(ROOT, "verify_deliverable.py"),
                 "--stl", stl, "--require-evidence-index"],
                cwd=ROOT, capture_output=True, text=True, timeout=240)
            self.assertNotIn("Traceback", out.stderr, out.stderr)
            self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
            gated = vd.verify(stl, require_evidence_index=True)
            self.assertFalse(gated["checks"]["evidence_index_valid"])
            self.assertIn("上限", gated["metrics"]["evidence_index_reason"])
            # 默认口径不受影响，仍 12 项且通过。
            plain = vd.verify(stl)
            self.assertEqual(len(plain["checks"]), 12)
            self.assertTrue(plain["pass"], plain["checks"])


# ---------- R46：生成侧/复验侧判据一致 + 缺依赖结构化错误 ----------

def _seed_final5_copy(d):
    """把 final5 全套证据复制到隔离目录；绝不碰真实交付目录。"""
    import shutil
    src = os.path.join(ROOT, "print_ready", "_verify2", "final5")
    stl = os.path.join(d, "target_final5.stl")
    shutil.copyfile(os.path.join(src, "target_final5.stl"), stl)
    for suffix in ("_fidelity.json", "_manifest.json", "_evidence.json",
                   "_front.png", "_back.png", "_side.png"):
        shutil.copyfile(os.path.join(src, "target_final5" + suffix),
                        os.path.join(d, "target_final5" + suffix))
    shutil.copyfile(os.path.join(src, "run.log"), os.path.join(d, "run.log"))
    for name in ("target_final5_manifest.json", "target_final5_fidelity.json"):
        path = os.path.join(d, name)
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        for entry in obj.get("outputs", []):
            if str(entry.get("path", "")).lower().endswith("target_final5.stl"):
                entry["path"] = stl
        fv = obj.get("file_verification")
        if isinstance(fv, dict):
            fv["stl"] = stl
        vd.write_json_atomic(path, obj)
    return stl


_R46_MISSING_DEP_SCRIPT = """
import sys, builtins
sys.path.insert(0, {root!r})
_real = builtins.__import__
def _blocked(name, *a, **k):
    if name == 'trimesh' or name.startswith('trimesh.'):
        raise ModuleNotFoundError("No module named 'trimesh'")
    return _real(name, *a, **k)
builtins.__import__ = _blocked
import verify_deliverable as vd
sys.exit(vd.main(['--stl', {stl!r}]))
"""


class TestR46MissingDependency(unittest.TestCase):
    """CLI 层：缺 trimesh 必须是 rc=2 结构化执行错误，不是裸 traceback/rc=1。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r46_missing_trimesh_is_rc2_without_traceback(self):
        code = _R46_MISSING_DEP_SCRIPT.format(root=ROOT, stl=self.REAL_STL)
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertNotIn("Traceback", out.stderr)
        self.assertIn("[ERROR]", out.stderr)
        self.assertIn("trimesh", out.stderr)


class TestR46StlExtents(unittest.TestCase):
    """R46 新增的零依赖 STL 包围盒解析：正例精确、负例结构化拒绝。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r46_real_binary_stl_extents(self):
        ok, reason, ext = vd.stl_extents_from_file(self.REAL_STL)
        self.assertTrue(ok, reason)
        self.assertAlmostEqual(ext[0], 38.637, delta=0.05)
        self.assertAlmostEqual(ext[1], 29.955, delta=0.05)
        self.assertAlmostEqual(ext[2], 152.244, delta=0.05)

    def test_r46_broken_stl_is_structured_reject(self):
        with tempfile.TemporaryDirectory() as d:
            cases = {}
            p = os.path.join(d, "empty.stl")
            with open(p, "wb") as f:
                f.write(b"")
            cases["空文件"] = p
            p = os.path.join(d, "badcount.stl")
            with open(p, "wb") as f:
                f.write(b"\x00" * 80 + (999).to_bytes(4, "little")
                        + b"\x00" * 50)
            cases["三角形数与文件大小不符"] = p
            p = os.path.join(d, "ascii.stl")
            with open(p, "w", encoding="ascii") as f:
                f.write("solid x\n facet normal 0 0 1\n  outer loop\n"
                        "   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n"
                        "  endloop\n endfacet\nendsolid x\n")
            cases["ASCII 无 Z 厚度"] = p
            for label, path in cases.items():
                with self.subTest(case=label):
                    ok, reason, ext = vd.stl_extents_from_file(path)
                    self.assertFalse(ok)
                    self.assertTrue(reason)
                    self.assertIsNone(ext)

    def test_r46_ascii_stl_extents(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "box.stl")
            pts = [(0, 0, 0), (2, 0, 0), (0, 4, 8)]
            with open(p, "w", encoding="ascii") as f:
                f.write("solid box\n facet normal 0 0 1\n  outer loop\n")
                for x, y, z in pts:
                    f.write(f"   vertex {x} {y} {z}\n")
                f.write("  endloop\n endfacet\nendsolid box\n")
            ok, reason, ext = vd.stl_extents_from_file(p)
            self.assertTrue(ok, reason)
            self.assertEqual(ext, [2.0, 4.0, 8.0])


class TestR46WriteIndexContract(unittest.TestCase):
    """生成侧必须拒掉复验侧必然 FAIL 的证据，不得打印 [OK] 写出矛盾基线。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r46_write_index_rejects_foreign_render(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_final5_copy(d)
            # 侧视图换成另一模型比例的合规渲染图：容器 CRC 完好、哈希互异。
            _make_render_like_png(os.path.join(d, "target_final5_side.png"),
                                  rect=(300, 686))
            with self.assertRaises(ValueError) as ctx:
                vd.build_evidence_index(stl)
            self.assertIn("绑定", str(ctx.exception))

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r46_write_index_rejects_oversized_ihdr(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_final5_copy(d)
            front = os.path.join(d, "target_final5_front.png")
            _make_oversized_png(front, 4294967295, 4294967295)
            # 容器层仍判「完好」，旧生成侧会照单全收并写基线。
            self.assertTrue(vd.png_container_valid(front)[0])
            with self.assertRaises(ValueError) as ctx:
                vd.build_evidence_index(stl)
            self.assertIn("上限", str(ctx.exception))

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r46_write_index_accepts_real_final5_and_schema_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_final5_copy(d)
            index = vd.build_evidence_index(stl)
            shipped_path = os.path.join(
                ROOT, "print_ready", "_verify2", "final5",
                "target_final5_evidence.json")
            with open(shipped_path, encoding="utf-8") as f:
                shipped = json.load(f)
            self.assertEqual(index["schema_version"], shipped["schema_version"])
            self.assertEqual(index["stl"], shipped["stl"])
            self.assertEqual(index["evidence"], shipped["evidence"])

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r46_write_cli_rejects_and_does_not_overwrite_index(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_final5_copy(d)
            _make_render_like_png(os.path.join(d, "target_final5_side.png"),
                                  rect=(300, 686))
            index_path = vd.evidence_index_path(stl)
            with open(index_path, "rb") as f:
                before = f.read()
            out = subprocess.run(
                [sys.executable, os.path.join(ROOT, "verify_deliverable.py"),
                 "--stl", stl, "--write-evidence-index"],
                capture_output=True, text=True)
            self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
            self.assertNotIn("Traceback", out.stderr)
            self.assertIn("[ERROR]", out.stderr)
            with open(index_path, "rb") as f:
                self.assertEqual(f.read(), before)


# ---------- R47：写基线独立动作不得静默丢弃验收参数 ----------

def _seed_write_only(d):
    """极小的几何自洽交付：只需 STL + 三视图 + run.log，绝不碰真实交付目录。

    R51：正例图改为轮廓状（与真实三视图同类），不再用纯色矩形蒙混过绑定。
    """
    stl = os.path.join(d, "m.stl")
    with open(stl, "w", encoding="ascii") as f:
        f.write("solid mini\n facet normal 0 0 1\n  outer loop\n"
                "   vertex 0 0 0\n   vertex 10 0 0\n   vertex 0 10 40\n"
                "  endloop\n endfacet\nendsolid mini\n")
    for view, fg in (("front", 162), ("back", 176), ("side", 163)):
        _make_silhouette_png(os.path.join(d, "m_%s.png" % view),
                             size=128, rect=(24, 96), bg=58, fg=fg)
    with open(os.path.join(d, "run.log"), "w", encoding="utf-8") as f:
        f.write("[*] run log for write-action contract test\n")
    return stl


def _run_cli(stl, *extra):
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "verify_deliverable.py"),
         "--stl", stl] + list(extra),
        cwd=ROOT, capture_output=True, text=True, timeout=180)


# CLI 上所有会改变复验语义、但在写基线动作里被静默吞掉的参数。
_R47_WRITE_CONFLICTS = (
    ("--require-source-provenance", ["--require-source-provenance"]),
    ("--require-file-verification", ["--require-file-verification"]),
    ("--strict-single-body", ["--strict-single-body"]),
    ("--report", ["--report", "some_fidelity.json"]),
    ("--manifest", ["--manifest", "some_manifest.json"]),
    ("--json", ["--json", "some_result.json"]),
    ("--require-evidence-index", ["--require-evidence-index"]),
    ("--stl-only", ["--stl-only"]),
)


class TestR47WriteActionContract(unittest.TestCase):
    """R36 同类缺口换到另一个独立动作：写基线时验收参数不得被静默丢弃。"""

    def test_r47_every_verification_flag_is_rejected_in_write_action(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_write_only(d)
            for flag, extra in _R47_WRITE_CONFLICTS:
                with self.subTest(flag=flag):
                    out = _run_cli(stl, "--write-evidence-index", *extra)
                    self.assertEqual(out.returncode, 2,
                                     out.stdout + out.stderr)
                    self.assertIn(flag, out.stderr)
                    self.assertNotIn("Traceback", out.stderr)

    def test_r47_library_contract_matches_cli(self):
        """库层与 CLI 必须共用同一份冲突集合，不许再各写一份。"""
        for flag, _ in _R47_WRITE_CONFLICTS:
            with self.subTest(flag=flag):
                kwargs = dict(write_evidence_index=True)
                if flag == "--require-source-provenance":
                    kwargs["require_source_provenance"] = True
                elif flag == "--require-file-verification":
                    kwargs["require_file_verification"] = True
                elif flag == "--strict-single-body":
                    kwargs["strict_single_body"] = True
                elif flag == "--report":
                    kwargs["report_path"] = "some_fidelity.json"
                elif flag == "--manifest":
                    kwargs["manifest_path"] = "some_manifest.json"
                elif flag == "--json":
                    kwargs["json_path"] = "some_result.json"
                elif flag == "--require-evidence-index":
                    kwargs["require_evidence_index"] = True
                elif flag == "--stl-only":
                    kwargs["stl_only"] = True
                stl_only = kwargs.pop("stl_only", False)
                with self.assertRaises(ValueError) as ctx:
                    vd.check_mode_contract(stl_only, **kwargs)
                self.assertIn(flag, str(ctx.exception))

    def test_r47_normal_write_and_custom_index_path_still_work(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_write_only(d)
            custom = os.path.join(d, "custom_baseline.json")
            out = _run_cli(stl, "--write-evidence-index",
                           "--evidence-index", custom)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertTrue(os.path.isfile(custom))
            with open(custom, encoding="utf-8") as f:
                index = json.load(f)
            self.assertEqual(index["schema_version"],
                             vd.EVIDENCE_INDEX_SCHEMA)
            self.assertEqual(len(index["evidence"]), len(vd.EVIDENCE_ITEMS))

    def test_r47_existing_contracts_and_default_verify_unchanged(self):
        """护栏：R43 两类冲突与默认 12 项口径不得被本轮改动破坏。"""
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_write_only(d)
            for extra in (("--write-evidence-index",
                           "--require-evidence-index"),
                          ("--stl-only", "--require-evidence-index")):
                with self.subTest(extra=extra):
                    out = _run_cli(stl, *extra)
                    self.assertEqual(out.returncode, 2,
                                     out.stdout + out.stderr)
                    self.assertIn("--require-evidence-index", out.stderr)
        self.assertIsNone(vd.check_mode_contract(
            False, require_evidence_index=True))


# ---------- R48：写基线输出目标不得覆写交付证据 / 他人基线 ----------

_R48_DELIVERY_JSON_SUFFIXES = (
    "_fidelity.json", "_manifest.json", "_verify.json",
)


class TestR48WriteIndexTargetGuard(unittest.TestCase):
    """R36/R38 同类缺口换到写基线动作：--json 当年补了 protected，
    --write-evidence-index 分支却调用 write_json_atomic(target, index)
    完全不传 protected。.json 后缀护栏挡得住 .stl/.png/.log，挡不住
    同为 .json 的报告/清单/复验结果，也挡不住覆写任意既有 JSON 或
    另一个 STL 的合法基线 —— 一律静默覆写且打印 [OK] rc=0。
    """

    def _seed(self, d):
        stl = _seed_write_only(d)
        # 造几份「交付证据」JSON：合法 JSON，但绝不是证据基线。
        for suffix in _R48_DELIVERY_JSON_SUFFIXES:
            with open(os.path.join(d, "m" + suffix), "w",
                      encoding="utf-8") as f:
                json.dump({"marker": suffix, "pass": True}, f)
        return stl

    def _write(self, stl, *extra):
        return _run_cli(stl, "--write-evidence-index", *extra)

    def test_r48_delivery_json_targets_are_never_overwritten(self):
        """报告/清单/复验结果/任意既有 JSON 都必须拒绝覆写且字节不变。"""
        with tempfile.TemporaryDirectory() as d:
            stl = self._seed(d)
            targets = [os.path.join(d, "m" + suffix)
                       for suffix in _R48_DELIVERY_JSON_SUFFIXES]
            arbitrary = os.path.join(d, "important_notes.json")
            with open(arbitrary, "w", encoding="utf-8") as f:
                json.dump({"user_data": "do not clobber"}, f)
            targets.append(arbitrary)
            for target in targets:
                with self.subTest(target=os.path.basename(target)):
                    with open(target, "rb") as f:
                        before = f.read()
                    out = self._write(stl, "--evidence-index", target)
                    self.assertEqual(out.returncode, 2,
                                     out.stdout + out.stderr)
                    self.assertNotIn("Traceback", out.stderr)
                    self.assertIn("拒绝", out.stderr)
                    with open(target, "rb") as f:
                        self.assertEqual(f.read(), before)

    def test_r48_foreign_baseline_is_not_overwritten(self):
        """目标已是另一个 STL 的合法基线时，禁止跨交付覆写。"""
        with tempfile.TemporaryDirectory() as d:
            stl = self._seed(d)
            foreign = os.path.join(d, "other_baseline.json")
            index = vd.build_evidence_index(stl)
            index["stl"]["sha256"] = "0" * 64
            vd.write_json_atomic(foreign, index)
            with open(foreign, "rb") as f:
                before = f.read()
            out = self._write(stl, "--evidence-index", foreign)
            self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
            self.assertNotIn("Traceback", out.stderr)
            self.assertIn("拒绝", out.stderr)
            with open(foreign, "rb") as f:
                self.assertEqual(f.read(), before)

    def test_r48_normal_generation_and_same_stl_regeneration_work(self):
        """护栏不能误伤：默认生成、同 STL 重新生成、自定义新路径仍 rc=0。"""
        with tempfile.TemporaryDirectory() as d:
            stl = self._seed(d)
            default = vd.evidence_index_path(stl)
            out = self._write(stl)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertTrue(os.path.isfile(default))
            with open(default, encoding="utf-8") as f:
                first = json.load(f)
            self.assertEqual(first["schema_version"],
                             vd.EVIDENCE_INDEX_SCHEMA)
            again = self._write(stl)
            self.assertEqual(again.returncode, 0,
                             again.stdout + again.stderr)
            with open(default, encoding="utf-8") as f:
                second = json.load(f)
            self.assertEqual(second["stl"], first["stl"])
            self.assertEqual(second["evidence"], first["evidence"])
            custom = os.path.join(d, "fresh_baseline.json")
            out3 = self._write(stl, "--evidence-index", custom)
            self.assertEqual(out3.returncode, 0, out3.stdout + out3.stderr)
            self.assertTrue(os.path.isfile(custom))

    def test_r48_library_protected_paths_contract(self):
        """库层保护集合：含全部派生证据与 _verify.json，唯独放行默认基线。"""
        with tempfile.TemporaryDirectory() as d:
            stl = self._seed(d)
            protected = {os.path.normcase(os.path.abspath(p))
                         for p in vd.write_index_protected_paths(stl)}
            baseline = os.path.normcase(
                os.path.abspath(vd.evidence_index_path(stl)))
            self.assertNotIn(baseline, protected)
            for name in ("m.stl", "run.log", "m_fidelity.json",
                         "m_manifest.json", "m_verify.json",
                         "m_front.png", "m_back.png", "m_side.png"):
                with self.subTest(name=name):
                    self.assertIn(os.path.normcase(
                        os.path.abspath(os.path.join(d, name))), protected)

    def test_r48_json_branch_protection_unchanged(self):
        """护栏：R36/R38 的 --json 保护与默认 label 不得被本轮误伤。

        刻意走库层而非 CLI：缺依赖解释器会在 geometry_checks 处以
        MissingDependencyError 提前 rc=2（R46），根本走不到 --json 写出，
        那样测的就不是护栏本身了。库层验证在三个环境语义完全一致。
        """
        with tempfile.TemporaryDirectory() as d:
            stl = self._seed(d)
            report = os.path.join(d, "m_fidelity.json")
            with open(report, "rb") as f:
                before = f.read()
            protected = vd.evidence_paths(stl) + (report,)
            with self.assertRaises(ValueError) as ctx:
                vd.write_json_atomic(report, {"pass": True}, protected)
            self.assertIn("不能覆盖", str(ctx.exception))
            self.assertIn("--json", str(ctx.exception))
            with open(report, "rb") as f:
                self.assertEqual(f.read(), before)


# ---------- R50：证据角色必须绑定到派生文件名 ----------

class TestR50EvidenceRoleBinding(unittest.TestCase):
    """修复前实证：把 front_view 改指向 decoy.png 并同步哈希，仍 13/13 PASS。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")

    @staticmethod
    def _rebind(index_path, role, filename, payload):
        import hashlib
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
        for entry in index["evidence"]:
            if entry["role"] == role:
                entry["file"] = filename
                entry["bytes"] = len(payload)
                entry["sha256"] = hashlib.sha256(payload).hexdigest()
        vd.write_json_atomic(index_path, index)

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r50_role_cannot_be_rebound_to_an_unrelated_png(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_final5_copy(d)
            decoy = os.path.join(d, "decoy.png")
            _make_render_like_png(decoy, size=768, rect=(174, 686))
            with open(decoy, "rb") as f:
                payload = f.read()
            index_path = vd.evidence_index_path(stl)
            self._rebind(index_path, "front_view", "decoy.png", payload)
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertFalse(ok)
            self.assertIn("绑定了错误的文件", reason)
            if HAS_TRIMESH:
                gated = vd.verify(stl, require_evidence_index=True)
                self.assertFalse(gated["checks"]["evidence_index_valid"])
                others = {k: v for k, v in gated["checks"].items()
                          if k != "evidence_index_valid"}
                self.assertEqual(len(others), 12)
                self.assertTrue(all(others.values()), others)

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r50_role_cannot_point_at_another_role_file(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_final5_copy(d)
            back = os.path.join(d, "target_final5_back.png")
            with open(back, "rb") as f:
                payload = f.read()
            self._rebind(vd.evidence_index_path(stl), "front_view",
                         "target_final5_back.png", payload)
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertFalse(ok)
            self.assertIn("绑定了错误的文件", reason)

    def test_r50_generated_baseline_uses_the_single_filename_map(self):
        """生成侧与复验侧共用 expected_evidence_files，杜绝两层漂移。"""
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_write_only(d)
            index = vd.build_evidence_index(stl)
            expected = vd.expected_evidence_files(stl)
            self.assertEqual({e["role"]: e["file"] for e in index["evidence"]},
                             expected)
            target = vd.evidence_index_path(stl)
            vd.write_json_atomic(target, index)
            ok, reason, _ = vd.evidence_index_checks(stl)
            self.assertTrue(ok, reason)


# ---------- R51：形状 + 跨视图一致性绑定 ----------

class TestR51RenderShapeBinding(unittest.TestCase):
    """修复前实证：比例正确的矩形、改绝对取景的轮廓都能 13/13 PASS。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")
    EXTENTS = [38.6374, 29.9549, 152.2445]

    @staticmethod
    def _views(stl):
        return {r: p for r, _, k, p in vd._evidence_names(stl) if k == "png"}

    @staticmethod
    def _rehash(stl, path):
        index_path = vd.evidence_index_path(stl)
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
        with open(path, "rb") as f:
            payload = f.read()
        for entry in index["evidence"]:
            if entry["role"] == "front_view":
                entry["bytes"] = len(payload)
                entry["sha256"] = vd._sha256(path)
        vd.write_json_atomic(index_path, index)

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r51_real_views_satisfy_shape_and_cross_view_contract(self):
        ok, reason, details = vd.render_binding_checks(
            self.EXTENTS, self._views(self.REAL_STL))
        self.assertTrue(ok, reason)
        for item in details:
            self.assertTrue(item["ok"], item)
            self.assertLess(item["fill_fraction"],
                            vd.RENDER_MAX_FILL_FRACTION)
            self.assertGreater(item["row_width_cv"],
                               vd.RENDER_MIN_ROW_WIDTH_CV)
            self.assertLessEqual(item["edge_spread"],
                                 vd.RENDER_MAX_EDGE_SPREAD)

    def test_r51_ratio_correct_rectangle_is_rejected(self):
        """宽高比凑对（0.25364）的纯色矩形不再是「模型轮廓」。"""
        with tempfile.TemporaryDirectory() as d:
            views = {}
            for role in ("front_view", "back_view", "side_view"):
                path = os.path.join(d, role + ".png")
                _make_silhouette_png(path, size=768, rect=(174, 686))
                views[role] = path
            _make_render_like_png(views["front_view"], size=768,
                                  rect=(174, 686))
            ok, reason, details = vd.render_binding_checks(self.EXTENTS, views)
            self.assertFalse(ok)
            self.assertIn("填充率", reason)
            self.assertIn("等宽矩形", reason)
            self.assertFalse([i for i in details
                              if i["role"] == "front_view"][0]["ok"])

    def test_r51_rescaled_render_is_rejected_by_cross_view_scale(self):
        """比例仍对（0.2533）但绝对取景高度不同，必须被三视图互校拒绝。"""
        with tempfile.TemporaryDirectory() as d:
            views = {}
            for role in ("front_view", "back_view", "side_view"):
                path = os.path.join(d, role + ".png")
                rect = (152, 600) if role == "front_view" else (174, 686)
                _make_silhouette_png(path, size=768, rect=rect)
                views[role] = path
            ok, reason, _ = vd.render_binding_checks(self.EXTENTS, views)
            self.assertFalse(ok)
            self.assertIn("前景高度", reason)
            self.assertIn("Z 尺度", reason)

    def test_r51_gradient_background_is_structured_reject(self):
        """背景不是纯色时不能静默算出一个假轮廓。"""
        import struct
        import zlib
        size = 64
        rows = []
        for y in range(size):
            bg = 20 + (y * 3) % 200
            row = bytearray(b"\x00")
            for x in range(size):
                fg = 245 if 20 <= x < 44 and 10 <= y < 54 else bg
                row += bytes((fg, fg, fg))
            rows.append(bytes(row))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gradient.png")
            ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n"
                        + _png_chunk(b"IHDR", ihdr)
                        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows)))
                        + _png_chunk(b"IEND", b""))
            ok, reason, _ = vd.render_binding_checks(
                self.EXTENTS, {r: path for r in vd.RENDER_VIEW_AXES})
            self.assertFalse(ok)
            self.assertIn("背景估计不可靠", reason)

    @unittest.skipUnless(os.path.isfile(REAL_STL) and HAS_TRIMESH,
                         "final5 交付或 trimesh 不可用")
    def test_r51_two_bypasses_are_rejected_end_to_end(self):
        """同步改基线后，两类绕过都必须只剩 evidence_index_valid 一项 FAIL。"""
        for label, keyword, make in (
                ("rectangle", "填充率", lambda p: _make_render_like_png(
                    p, size=768, rect=(174, 686))),
                ("rescaled", "前景高度", lambda p: _make_silhouette_png(
                    p, size=768, rect=(152, 600)))):
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as d:
                    stl = _seed_final5_copy(d)
                    front = os.path.join(d, "target_final5_front.png")
                    make(front)
                    self._rehash(stl, front)
                    ok43, reason43, _ = vd.evidence_index_checks(stl)
                    self.assertTrue(ok43, reason43)
                    gated = vd.verify(stl, require_evidence_index=True)
                    self.assertFalse(gated["checks"]["evidence_index_valid"])
                    self.assertIn(
                        keyword, gated["metrics"]["evidence_index_reason"])
                    others = {k: v for k, v in gated["checks"].items()
                              if k != "evidence_index_valid"}
                    self.assertEqual(len(others), 12)
                    self.assertTrue(all(others.values()), others)


# ---------- R56：STL 三角形投影与 PNG 前景的轮廓 IoU ----------

@unittest.skipUnless(HAS_TRIMESH, "缺 trimesh，轮廓投影不可用")
class TestR56SilhouetteBinding(unittest.TestCase):
    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")

    @staticmethod
    def _views(stl):
        return {r: p for r, _, k, p in vd._evidence_names(stl) if k == "png"}

    def test_r56_box_projection_accepts_rectangle_and_rejects_diamond(self):
        """判据必须比较实际形状，而不是再发明一个可凑的统计量。"""
        box = trimesh.creation.box(extents=(2.0, 3.0, 4.0))
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "box.stl")
            box.export(stl)
            rectangles, diamonds = {}, {}
            for role, width in (("front_view", 24), ("back_view", 24),
                                ("side_view", 36)):
                rectangles[role] = os.path.join(d, role + "_rect.png")
                diamonds[role] = os.path.join(d, role + "_diamond.png")
                _make_render_like_png(rectangles[role], size=128,
                                      rect=(width, 48))
                _make_diamond_png(diamonds[role], size=128,
                                  rect=(width, 48))
            good, good_reason, good_details = vd.stl_silhouette_checks(
                stl, rectangles, grid_size=48)
            bad, bad_reason, bad_details = vd.stl_silhouette_checks(
                stl, diamonds, grid_size=48)
        self.assertTrue(good, good_reason)
        self.assertTrue(all(i["silhouette_iou"] >= 0.90 for i in good_details),
                        good_details)
        self.assertFalse(bad, bad_details)
        self.assertIn("形状并非同一模型", bad_reason)
        self.assertTrue(all(i["silhouette_iou"] < vd.RENDER_MIN_SILHOUETTE_IOU
                            for i in bad_details), bad_details)

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r56_real_delivery_has_high_projection_iou(self):
        ok, reason, details = vd.stl_silhouette_checks(
            self.REAL_STL, self._views(self.REAL_STL))
        self.assertTrue(ok, reason)
        self.assertEqual(len(details), 3)
        for item in details:
            self.assertGreaterEqual(item["silhouette_iou"], 0.80, item)
            self.assertTrue(item["ok"], item)

    @unittest.skipUnless(os.path.isfile(REAL_STL), "final5 交付不存在")
    def test_r56_diamond_bypass_is_rejected_end_to_end(self):
        """修复前：菱形同时满足比例、形状统计和跨视图尺度，13/13 PASS。"""
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_final5_copy(d)
            paths = {
                "front_view": os.path.join(d, "target_final5_front.png"),
                "back_view": os.path.join(d, "target_final5_back.png"),
                "side_view": os.path.join(d, "target_final5_side.png"),
            }
            for index, (role, path) in enumerate(paths.items()):
                width = 135 if role == "side_view" else 174
                _make_diamond_png(path, size=768, rect=(width, 686),
                                  fg=170 + index * 6)
            index_path = vd.evidence_index_path(stl)
            with open(index_path, encoding="utf-8") as handle:
                evidence = json.load(handle)
            for entry in evidence["evidence"]:
                role = entry["role"]
                if role in paths:
                    entry["bytes"] = os.path.getsize(paths[role])
                    entry["sha256"] = vd._sha256(paths[role])
            vd.write_json_atomic(index_path, evidence)

            basic_ok, basic_reason, _ = vd.render_binding_checks(
                [38.6374, 29.9549, 152.2445], paths)
            self.assertTrue(basic_ok, basic_reason)
            gated = vd.verify(stl, require_evidence_index=True)
            self.assertFalse(gated["checks"]["evidence_index_valid"])
            self.assertIn("投影轮廓 IoU", gated["metrics"]["evidence_index_reason"])
            self.assertEqual(len(gated["metrics"]["render_silhouette"]), 3)
            others = {k: v for k, v in gated["checks"].items()
                      if k != "evidence_index_valid"}
            self.assertEqual(len(others), 12)
            self.assertTrue(all(others.values()), others)

    def test_r56_invalid_grid_and_missing_view_are_structured(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "box.stl")
            trimesh.creation.box().export(stl)
            ok, reason, details = vd.stl_silhouette_checks(
                stl, {}, grid_size=8)
            self.assertFalse(ok)
            self.assertIn("[16, 256]", reason)
            ok, reason, details = vd.stl_silhouette_checks(stl, {})
            self.assertFalse(ok)
            self.assertEqual(len(details), 3)
            self.assertTrue(all(not item["ok"] for item in details))


# ---------- R52：证据路径按证据文件所在目录解析 ----------

class TestR52RelativeEvidencePaths(unittest.TestCase):
    """修复前实证：清单用相对路径、从别的 CWD 复验，合法交付被判 FAIL。"""

    REAL_STL = os.path.join(
        ROOT, "print_ready", "_verify2", "final5", "target_final5.stl")

    @unittest.skipUnless(os.path.isfile(REAL_STL) and HAS_TRIMESH,
                         "final5 交付或 trimesh 不可用")
    def test_r52_full_verify_accepts_relative_paths_from_foreign_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            stl = _seed_final5_copy(d)
            report_path = os.path.join(d, "target_final5_fidelity.json")
            manifest_path = os.path.join(d, "target_final5_manifest.json")
            for path in (report_path, manifest_path):
                with open(path, encoding="utf-8") as f:
                    obj = json.load(f)
                for entry in obj.get("outputs", []):
                    if os.path.normcase(os.path.abspath(entry["path"])) == \
                            os.path.normcase(os.path.abspath(stl)):
                        entry["path"] = os.path.basename(stl)
                fv = obj.get("file_verification")
                if isinstance(fv, dict):
                    fv["stl"] = os.path.basename(stl)
                vd.write_json_atomic(path, obj)
            old_cwd = os.getcwd()
            try:
                os.chdir(ROOT)  # 与交付目录不同，旧实现按 ROOT 解析相对路径
                result = vd.verify(stl)
            finally:
                os.chdir(old_cwd)
            self.assertTrue(result["checks"]["file_sha256_matches_manifest"])
            self.assertTrue(result["checks"]["file_verification_consistent"])
            self.assertEqual(len(result["checks"]), 12)
            self.assertTrue(result["pass"], result["checks"])

    def test_r52_find_output_sha256_resolves_relative_to_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            manifest_path = os.path.join(d, "m_manifest.json")
            manifest = {"outputs": [{"path": "m.stl", "sha256": "a" * 64}]}
            got, idx = vd.find_output_sha256(
                manifest, os.path.join(d, "m.stl"), manifest_path)
            self.assertEqual(got, "a" * 64)
            self.assertEqual(idx, 0)
            # 指向别的目录的 STL 仍必须拒；绝对路径语义不变。
            self.assertEqual(
                vd.find_output_sha256(manifest, os.path.join(d, "other.stl"),
                                      manifest_path), (None, None))
            absolute = os.path.join(d, "m.stl")
            self.assertEqual(
                vd.find_output_sha256(
                    {"outputs": [{"path": absolute, "sha256": "b" * 64}]},
                    absolute, manifest_path), ("b" * 64, 0))

    def test_r52_source_provenance_resolves_relative_to_own_files(self):
        with tempfile.TemporaryDirectory() as d:
            for name, payload in (("input.glb", b"GLB-DATA"),
                                  ("ref.png", b"PNG-DATA")):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(payload)
            import hashlib
            h1 = hashlib.sha256(b"GLB-DATA").hexdigest()
            h2 = hashlib.sha256(b"PNG-DATA").hexdigest()
            report = {"input_mesh": "input.glb",
                      "input_mesh_sha256": h1,
                      "reference": "ref.png",
                      "reference_image_sha256": h2}
            manifest = {"input": {"path": "input.glb", "sha256": h1},
                        "reference_image": {"path": "ref.png",
                                           "sha256": h2}}
            report_path = os.path.join(d, "m_fidelity.json")
            manifest_path = os.path.join(d, "m_manifest.json")
            old_cwd = os.getcwd()
            try:
                os.chdir(ROOT)
                ok, reason, details = vd.source_provenance_checks(
                    report, manifest, manifest_path=manifest_path,
                    report_path=report_path)
            finally:
                os.chdir(old_cwd)
            self.assertTrue(ok, reason)
            self.assertIsNone(reason)
            self.assertEqual(len(details), 2)
            # 篡改仍必须被拒，不能因为支持相对路径而放宽判据。
            bad = dict(manifest)
            bad["input"] = {"path": "input.glb", "sha256": "0" * 64}
            ok_bad, reason_bad, _ = vd.source_provenance_checks(
                report, bad, manifest_path=manifest_path,
                report_path=report_path)
            self.assertFalse(ok_bad)
            self.assertIn("不一致", reason_bad)

    def test_r52_file_verification_contract_resolves_relative_stl(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            fv = {"stl": "m.stl", "pass": True, "checks": {"a": True}}
            report = {"file_verification": fv}
            manifest = {"file_verification": fv}
            verdict = {"file_verification_pass": True}
            required, ok, reason = vd.file_verification_contract(
                report, manifest, verdict, stl,
                os.path.join(d, "m_fidelity.json"),
                os.path.join(d, "m_manifest.json"))
            self.assertTrue(required)
            self.assertTrue(ok, reason)
            self.assertIsNone(reason)


# ---------- R53：几何复验不重复解析、不重复算体积 ----------

@unittest.skipUnless(HAS_TRIMESH, "缺 trimesh，几何复验不可用")
class TestR53GeometryChecksPerformance(unittest.TestCase):
    """用结构断言锁住性能改动，避免「回到两次 load」而无人察觉。"""

    def test_r53_stl_is_parsed_exactly_once(self):
        import trimesh
        box = trimesh.creation.box(extents=(2.0, 3.0, 4.0))
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            box.export(stl)
            with mock.patch.object(trimesh, "load",
                                   side_effect=lambda *a, **k: box.copy()) as load:
                checks, metrics = vd.geometry_checks(stl)
            self.assertEqual(load.call_count, 1, "不得把 37MB STL 解析两遍")
            self.assertTrue(checks["welded_watertight"])
            self.assertTrue(checks["positive_volume"])
            self.assertEqual(metrics["faces"], len(box.faces))
            self.assertEqual(metrics["connected_parts"], 1)

    def test_r53_single_body_shortcut_does_not_leak_into_multi_body(self):
        """体积复用只适用于单实体；多实体仍须逐块计算悬空体积占比。"""
        a = trimesh.creation.box(extents=(2.0, 3.0, 4.0))
        b = a.copy()
        b.apply_translation([10.0, 0.0, 0.0])
        twin = trimesh.util.concatenate([a, b])
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "twin.stl")
            twin.export(stl)
            checks, metrics = vd.geometry_checks(stl)
        self.assertTrue(checks["welded_watertight"])
        self.assertEqual(metrics["connected_parts"], 2)
        self.assertEqual(metrics["floating_parts"], 1)
        self.assertGreater(metrics["floating_volume_ratio"], 0.0)

    @unittest.skipUnless(
        os.path.isfile(os.path.join(
            ROOT, "print_ready", "_verify2", "final5",
            "target_final5.stl")), "final5 交付不存在")
    def test_r53_real_deliverable_metrics_unchanged(self):
        """优化不得改动任何落盘指标：与交付 _verify.json 逐字段比对。"""
        stl = os.path.join(ROOT, "print_ready", "_verify2", "final5",
                           "target_final5.stl")
        with open(os.path.splitext(stl)[0] + "_verify.json",
                  encoding="utf-8") as f:
            shipped = json.load(f)
        checks, metrics = vd.geometry_checks(stl)
        for key, value in checks.items():
            self.assertEqual(value, shipped["checks"][key], key)
        for key in ("faces", "vertices_raw", "vertices_welded",
                    "volume_signed", "euler_number", "extents_xyz",
                    "connected_parts", "main_body_face_ratio",
                    "floating_parts", "floating_parts_max_faces",
                    "floating_volume_ratio", "degenerate_faces"):
            self.assertEqual(metrics[key], shipped["metrics"][key], key)


# ---------- R54：两份保护集合来自同一交付清单 ----------

class TestR54SingleArtifactSpec(unittest.TestCase):
    """消除「新增证据文件只改了一处 protected」的漂移风险。"""

    def test_r54_both_sets_are_complements_of_their_own_legal_output(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            norm = lambda p: os.path.normcase(os.path.abspath(p))
            everything = {norm(p) for p in vd.delivery_artifact_paths(stl)}
            json_set = {norm(p) for p in vd.evidence_paths(stl)}
            write_set = {norm(p) for p in
                         vd.write_index_protected_paths(stl)}
            verify_result = norm(os.path.join(d, "m_verify.json"))
            baseline = norm(os.path.join(d, "m_evidence.json"))
            self.assertEqual(json_set, everything - {verify_result})
            self.assertEqual(write_set, everything - {baseline})
            self.assertEqual(json_set ^ write_set,
                             {verify_result, baseline})
            # 任何派生产物都至少被一个动作保护，且 STL/日志两边都保护。
            for name, suffix in vd.DELIVERY_ARTIFACTS:
                target = norm(os.path.join(d, "m" + suffix))
                self.assertIn(target, everything)
                self.assertTrue(target in json_set or target in write_set)
            for name in ("m.stl", "run.log"):
                target = norm(os.path.join(d, name))
                self.assertIn(target, json_set)
                self.assertIn(target, write_set)

    def test_r54_adding_an_artifact_auto_protects_both_actions(self):
        """往单一清单加一项，两种动作都自动保护，无需改任何手写列表。"""
        extended = vd.DELIVERY_ARTIFACTS + (("audit_log", "_audit.json"),)
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            with mock.patch.object(vd, "DELIVERY_ARTIFACTS", extended):
                norm = lambda p: os.path.normcase(os.path.abspath(p))
                target = norm(os.path.join(d, "m_audit.json"))
                self.assertIn(target, {norm(p) for p in
                                       vd.evidence_paths(stl)})
                self.assertIn(target, {norm(p) for p in
                                       vd.write_index_protected_paths(stl)})

    def test_r54_write_guards_remain_behaviourally_effective(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "m.stl")
            for name, protected in (
                    ("m_verify.json", vd.write_index_protected_paths(stl)),
                    ("m_fidelity.json", vd.evidence_paths(stl))):
                target = os.path.join(d, name)
                with self.subTest(name=name):
                    with self.assertRaises(ValueError) as ctx:
                        vd.write_json_atomic(target, {"pass": True},
                                             protected)
                    self.assertIn("不能覆盖", str(ctx.exception))
            # 合法输出仍可写，护栏不误伤。
            for name, protected in (
                    ("m_verify.json", vd.evidence_paths(stl)),
                    ("m_evidence.json",
                     vd.write_index_protected_paths(stl))):
                target = os.path.join(d, name)
                with self.subTest(legal=name):
                    vd.write_json_atomic(target, {"pass": True}, protected)
                    self.assertTrue(os.path.isfile(target))


if __name__ == "__main__":
    unittest.main(verbosity=2)
