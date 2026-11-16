"""R30：导出质量门禁在用户入口（fig.py）与控制中心（control_server.py）的契约测试。

背景：convert_3d.py 提供了 --strict-watertight / --drop-floating-parts /
--strict-single-body，但 fig.py 既未定义也未透传，导致最终版本 final5 只能绕过
产品链路直接跑底层脚本才能复现。本组用例锁定三层 CLI 契约，防止再次漂移。
"""
import argparse
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import fig
    import control_server
    HAS_MODULES = True
except Exception:  # 缺依赖环境下整组跳过，不把 ImportError 变成 ERROR
    HAS_MODULES = False


def _print_args(**overrides):
    base = dict(
        model="m.glb", out_dir=".", formats=["obj", "stl", "3mf", "ply"],
        out_prefix=None, solidify=False, ref_model=None, decimate=0,
        smooth=0, model_height=0.0, scale=1.0, unit="mm", pitch=0.005,
        no_orient=False, base=0, hollow=0, no_diagnose=False,
        ref_image=None, min_iou=None, allow_low_fidelity=False,
        no_fidelity=False, no_crop_background=False, fidelity_report=None,
        no_blender_repair=False, voxel_mm=None, repair_max_iou_drop=None,
        strict_watertight=False, drop_floating_parts=False,
        strict_single_body=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


@unittest.skipUnless(HAS_MODULES, "fig/control_server 依赖不可用")
class TestPrintQualityFlags(unittest.TestCase):
    """正确性 / 一致性 / 边界情况：三层 CLI 开关一一对应。"""

    def test_flag_tables_agree_across_modules(self):
        self.assertEqual(set(fig.PRINT_FLAG_DEFAULTS),
                         set(control_server.PRINT_FLAG_ARGS))
        self.assertEqual(set(fig.PRINT_FLAG_ARGS),
                         set(fig.PRINT_FLAG_DEFAULTS))
        self.assertEqual(fig.PRINT_FLAG_ARGS, control_server.PRINT_FLAG_ARGS)
        self.assertTrue(all(v is False for v in fig.PRINT_FLAG_DEFAULTS.values()),
                        "默认必须全关，避免改变历史行为")

    def test_cmd_print_does_not_add_flags_by_default(self):
        with mock.patch.object(fig, "_LAST_REFERENCE_3D", None), \
                mock.patch.object(fig.subprocess, "call", return_value=0) as call:
            self.assertEqual(fig.cmd_print(_print_args()), 0)
        cmd = call.call_args[0][0]
        for flag in fig.PRINT_FLAG_ARGS.values():
            self.assertNotIn(flag, cmd)

    def test_cmd_print_forwards_all_flags(self):
        a = _print_args(strict_watertight=True, drop_floating_parts=True,
                        strict_single_body=True)
        with mock.patch.object(fig, "_LAST_REFERENCE_3D", None), \
                mock.patch.object(fig.subprocess, "call", return_value=0) as call:
            self.assertEqual(fig.cmd_print(a), 0)
        cmd = call.call_args[0][0]
        for flag in fig.PRINT_FLAG_ARGS.values():
            self.assertIn(flag, cmd)

    def test_strict_single_body_requires_stl_format(self):
        a = _print_args(strict_single_body=True, formats=["obj", "3mf"])
        with mock.patch.object(fig.subprocess, "call", return_value=0) as call:
            self.assertEqual(fig.cmd_print(a), 2)
        call.assert_not_called()

    def test_flags_defined_in_add_print_opts_and_downstream(self):
        import re
        with open(os.path.join(ROOT, "fig.py"), encoding="utf-8") as handle:
            fig_src = handle.read()
        block = re.search(
            r"def add_print_opts\(p\):(.*?)\n    p = sub\.add_parser\(\"img\"",
            fig_src, re.S).group(1)
        # add_print_opts 被 print / all / image_print / auto 四个子命令共用
        self.assertGreaterEqual(fig_src.count("add_print_opts(p)"), 4)
        with open(os.path.join(ROOT, "convert_3d.py"), encoding="utf-8") as handle:
            conv_src = handle.read()
        for flag in fig.PRINT_FLAG_ARGS.values():
            self.assertIn('"%s"' % flag, block)
            self.assertIn('add_argument("%s"' % flag, conv_src)

    def test_control_server_translation(self):
        self.assertEqual(control_server.print_quality_flags({}), [])
        self.assertEqual(
            control_server.print_quality_flags({
                "strict_watertight": True,
                "drop_floating_parts": "true",
                "strict_single_body": 1,
            }),
            ["--strict-watertight", "--drop-floating-parts",
             "--strict-single-body"])
        self.assertEqual(
            control_server.print_quality_flags({
                "strict_watertight": False,
                "drop_floating_parts": "0",
                "strict_single_body": None,
            }), [])
        for bad in ("yes", [], {"x": 1}, 2, -1):
            with self.assertRaises(ValueError):
                control_server.print_quality_flags({"strict_single_body": bad})
        with self.assertRaises(ValueError):
            control_server.print_quality_flags(["not", "a", "dict"])


    def test_high_detail_reconstruction_defaults_are_synchronized(self):
        """候选 B 实测有效的高精度参数不能只在 CLI 隐藏，GUI/主链路也要一致。"""
        self.assertEqual(fig.PRINT_DEFAULTS["voxel_mm"], 0.15)
        with open(os.path.join(ROOT, "fig.py"), encoding="utf-8") as handle:
            fig_src = handle.read()
        self.assertIn('"--steps3d", type=int, default=50', fig_src)
        self.assertIn('"--octree-res", type=int, default=512', fig_src)
        with open(os.path.join(ROOT, "convert_3d.py"), encoding="utf-8") as handle:
            conv_src = handle.read()
        self.assertIn('p.add_argument("--voxel-mm", type=float, default=0.15',
                      conv_src)
        with open(os.path.join(ROOT, "control_server.py"),
                  encoding="utf-8") as handle:
            control_src = handle.read()
        self.assertGreaterEqual(control_src.count("body.get('octree', 512)"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
