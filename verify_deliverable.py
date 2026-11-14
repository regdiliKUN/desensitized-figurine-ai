# -*- coding: utf-8 -*-
"""交付物文件级独立复验：只依据磁盘上的 STL / fidelity.json / manifest.json。

与转换时生成的 ``verdict`` 互补，补上此前验收未覆盖的三类问题：
  1. STL 二进制每面存 3 个独立顶点，直接 ``load(..., process=False)`` 必然
     显示"非水密"；必须按位置焊接后再判闭合，否则会把格式特性误判成缺陷。
  2. 水密 + 绕向一致 != 可打印：法线整体朝内时体积为负，切片软件视为空壳。
     因此把「有符号体积 > 0 / is_volume」列为硬性检查。
  3. verdict 评价的是内存网格；本脚本核对**落地文件**的 SHA256、面数、
     焊接顶点数、包围盒是否与报告/清单一致，防止"报告与产物不是同一个东西"。
  4. R31：清单 outputs 按 --to 顺序排列，STL 未必是第一个输出；哈希记录
     必须按路径定位，否则多格式导出会把合格成品误判为 FAIL。
  5. R32：主链路报告里的 file_verification 汇总 pass 可能与逐项 checks
     自相矛盾；必须逐项核对并与独立复验重算的几何判据交叉比对。
  6. R33：verdict 侧同样可被绕过 —— 旧的 all(checks.values()) 是 Python
     truthy，字符串 "false"/整数 2 都算通过，且完全不检查判据集合是否完整
     （把 checks 换成 {"forged": True} 也能通过）。必须按 build_verdict 的
     固定 5 项契约校验结构、按 required_checks 重算汇总、并与磁盘几何交叉。
  7. R34：verdict.pass 并非「内存判据全通过」，而是「内存判据 ∧ 文件级复验」
     的复合结论（见 convert_3d.apply_file_verification）。R33 只按前者重算，
     会把主链路诚实产出的不合格报告误报为「汇总不一致」；必须按复合语义
     重算，并把「自洽地判定不合格」与「汇总字段被篡改」分别给出诊断。
  8. R35：R27 的文件级闭环字段若被**整段删除**，旧实现「缺失即向后兼容
     跳过」会静默退回 11 项口径，连 verdict.file_verification_pass 一起删
     则复合语义校验也被绕过，实证仍 PASS。write_manifest 把同一个
     file_verification 写进清单，因此清单是判定「该不该有这个字段」的
     独立第二证据源，两处还必须逐项一致。
  9. R36：stl_only 模式下 verify() 直接 return，CLI 上同时传入的
     --report / --manifest / --require-file-verification 会被静默丢弃却仍
     输出 PASS（实证：--stl-only 配一份明显篡改的报告照样 rc=0）。
     此外 --json 直接 open(path,'w')：父目录不存在时 stdout 已打印 PASS
     却以 traceback / rc=1 崩溃，路径误指向 STL 更会覆盖交付成品（R13
     同类事故）。现改为显式参数契约 + 原子写 + 证据文件保护。
 10. R37：fidelity.json / manifest.json 顶层被换成数组、字符串或 null 时，
     ``report.get`` 抛未捕获 AttributeError，CLI 裸 traceback + 退出码 1，
     与「验收不通过」混淆；extents_xyz 被换成畸形值也会让复验直接崩。
     现显式校验顶层对象、把畸形数值判为该项 FAIL，并让 main 兜底映射
     残余属性异常为退出码 2。
 11. R38：R36 的 --json 保护列表只派生了 STL 与两个 JSON，同目录的
     run.log / 三视图 PNG 仍会被原子替换（实证覆盖日志且 rc=0）。现按 STL
     枚举全部已知证据文件，并拒绝任何非 .json 目标作为通用护栏。
 12. R41：报告里的 input_mesh_sha256 / reference_image_sha256 此前**没有任何
     消费方**。实证把两者改成 'TAMPERED_INPUT' / 全零或直接整段删除，独立
     复验仍 12/12 PASS —— 「哪张参考图、哪个输入模型产生这份 STL」的溯源
     字段形同装饰；生成侧 save_report 又用 setdefault 让旧值/假值可原样落盘
     （见 mesh_fidelity.save_report 的 R40）。现提供显式门禁
     --require-source-provenance：按「报告 ↔ 清单 ↔ 磁盘源文件」三重印证
     重算哈希。默认关闭，保证历史交付的 12 项口径与证据文件逐字节不变。
 13. R42：verdict 的两项**数值判据**此前只校验布尔自洽，从不重算。实证把
     final_mesh.silhouette_iou 改成 0.20、min_iou 改成 0.99、aspect_error_pct
     改成 99，独立复验仍 12/12 PASS。报告与清单 parameters 都已落盘 min_iou，
     宽高比容差又与生成侧共享常量，因此现可按阈值重算两项数值结论，并把
     报告/清单阈值不一致、指标畸形也判 FAIL。默认生效、不增检查项、不改
     12 项口径，正常报告的 verdict_reason 仍为 None，默认输出逐字节不变。
 14. R43：三视图 PNG 与 run.log 是给用户看的**交付证据**，但清单 outputs
     只有 STL 一条，独立复验从不校验这些文件是否存在、是否有效、是否与
     本次交付绑定。实证把 front 换成垃圾字节/另一张视图、删掉 side，复验
     一律仍 12/12 PASS；R38 只保证「别被 --json 覆盖」，不保证内容完好。
     现提供 --write-evidence-index 生成证据基线（路径/字节数/SHA256/PNG
     尺寸）与 --require-evidence-index 校验：零依赖解析 PNG 容器 CRC、
     三视图哈希两两不同（防复制冒充）、run.log 非空、路径不得越界。
     默认关闭，历史 12 项口径与 _verify.json 逐字节不变。
 15. R46：两条「自相矛盾」缺口。① ``geometry_checks`` 直接 import
     trimesh，在缺依赖解释器上打印裸 Traceback 且默认 rc=1，把执行错误
     伪装成「验收不通过」（R25 只在 unittest 层用 skip 绕过，CLI 层从未
     验过）；现定义 MissingDependencyError 并由 CLI 映射 rc=2 + 中文诊断。
     ② ``--write-evidence-index`` 只验容器 CRC/哈希/互异，完全不跑 R44
     几何绑定：实证把侧视图换成另一模型的合规渲染图，生成侧仍打印
     [OK] rc=0 写出基线，而 --require-evidence-index 必然 FAIL。现新增零
     依赖 stl_extents_from_file（直接读 STL 本体算包围盒，支持二进制/ASCII，
     不信任任何报告元数据），生成侧复用 render_binding_checks；基线
     schema 与既有交付逐字段不变、默认输出零变化。
 16. R47：R36 同类缺陷换到另一个独立动作。``--write-evidence-index``
     的 CLI 分支自己只列了 3 个冲突参数，且**完全不调用**
     ``check_mode_contract``：实证把 ``--require-source-provenance`` /
     ``--require-file-verification`` / ``--strict-single-body`` /
     ``--report`` / ``--manifest`` 与写基线同时传入，用户显式要求的硬门禁
     被静默丢弃，却仍打印 ``[OK] 证据基线已生成``、rc=0。现把完整冲突
     集合收进 ``check_mode_contract`` 作为唯一真值，CLI 改为调用它；
     库层与 CLI 不再各写一份，8 类冲突均 rc=2 + 可读诊断。
 17. R48：R36/R38 的 protected 只加在 ``--json`` 分支，
     ``--write-evidence-index`` 调用 ``write_json_atomic(target, index)``
     一份都没传。``.json`` 后缀护栏挡得住 .stl/.png/.log，挡不住同为
     .json 的 fidelity/manifest/verify；实证把 ``--evidence-index``
     指向这些文件，甚至任意既有 JSON 或另一个交付的合法基线，一律
     ``[OK] rc=0`` 静默覆写。现新增 ``write_index_protected_paths``（放行
     默认 ``_evidence.json``、加回 ``_verify.json``）与
     ``guard_index_write_target``（目标已存在时必须是属于本次 STL 的合法
     基线），并把 ``write_json_atomic`` 的诊断按 label 参数化。
 18. R50：证据基线只校验「角色集合 + 文件名不越界 + 哈希自洽」，从不
     校验「哪个角色对应哪个文件」。实证把 front_view 改指向同目录另一张
     合规 PNG 并同步改哈希/字节数，13/13 仍 PASS —— 正面渲染图就此脱出
     哈希链。现由 ``expected_evidence_files`` 从 ``_evidence_names`` 派生
     唯一映射，逐条强制绑定。
 19. R51：R44 的几何绑定只比一个标量（前景包围盒宽高比）。实证两类绕过
     都能 13/13 PASS：比例凑对的纯色矩形、以及改了绝对取景高度但比例不变
     的图。现加三项轮廓形状判据（填充率 / 逐行宽度变异 / 四边背景同质性）
     与三视图共用正交相机下的像素尺度互校（Z 高度、正背 X 跨度），结果
     并入既有 ``evidence_index_valid``，不新增检查项、默认输出零变化。
 20. R52：清单/报告里的相对路径此前按**当前工作目录**解析，交付目录整体
     搬迁或清单改用相对路径后，从别的 CWD 复验会把合法成品误判 FAIL。
     现由 ``_resolve_evidence_path`` 按承载该路径的证据文件所在目录解析，
     覆盖清单 outputs、``file_verification.stl`` 与输入溯源三处；绝对路径
     语义不变，``origin_path=None`` 的库调用保持旧行为。
 21. R53：``geometry_checks`` 曾把同一个 37MB STL 完整解析两遍（只为拿到
     焊接副本），单实体时又对 ``split()`` 出的唯一一块重算体积。现单次
     加载 + ``copy()/process()`` 并复用已算体积，全部落盘指标逐字段不变
     （由回归锁定）。
 22. R54：R48 的两份 protected 列表靠回归偶然锁定语义，新增派生产物时
    极易只改一处。现由 ``DELIVERY_ARTIFACTS`` / ``delivery_artifact_paths``
    单一清单派生；``--json`` 只声明放行 ``verify_result``，写基线只声明
    放行 ``evidence_index``，其余一律保护。
 23. R56：R51 的三项形状判据仍属「可凑的统计量」。实证三张菱形假图同时
    满足比例、填充率、行宽变异、背景同质性与跨视图尺度互校，仍全过。
    现新增 ``stl_silhouette_checks``：把 STL 三角形正交光栅化成 96×96 的
    front/back/side 掩膜，与 PNG 前景各自按包围盒归一化后算轮廓 IoU
    （阈值 0.65，允许水平镜像以兼容正/背相机方向），仅在显式证据验收
    时启用并并入既有 ``evidence_index_valid``，默认 12 项输出逐字节不变。
    实测真实交付 IoU 0.8372 / 0.8602 / 0.8283。

用法：
    python verify_deliverable.py --stl <path> [--report <path>] [--manifest <path>]
    python verify_deliverable.py --stl <path> --stl-only        # 只做几何复验
    python verify_deliverable.py --stl <path> --json <path>     # 写结构化结果
    python verify_deliverable.py --stl <path> --require-file-verification
        # 强制要求报告/清单记录文件级复验（拒绝 R27 之前的旧报告）
    python verify_deliverable.py --stl <path> --require-source-provenance
        # 额外核验输入模型/参考图的报告哈希、清单哈希与磁盘文件三方一致
    python verify_deliverable.py --stl <path> --write-evidence-index
        # 依据当前磁盘产物生成 <prefix>_evidence.json 证据基线（独立动作）
    python verify_deliverable.py --stl <path> --require-evidence-index
        # 校验三视图/日志与证据基线逐项一致（启用时新增第 13 项检查），
        # 并做 STL 投影轮廓 IoU 绑定（R56：形状不再是统计量而是实际像素）

注意：--stl-only 与 --report / --manifest / --require-file-verification /
--require-source-provenance / --require-evidence-index 互斥，同时传入会以
退出码 2 明确拒绝，而不是静默忽略后给出 PASS。
--write-evidence-index 是独立动作，与 --stl-only / --report / --manifest /
--strict-single-body / --require-file-verification / --require-source-provenance /
--require-evidence-index / --json 均互斥（R47：避免静默丢弃验收要求或自写自验）。
--json 目标必须是 .json 文件，且不得覆盖 STL / fidelity / manifest /
三视图 / run.log / 证据基线等交付证据（R36/R38/R43）；复验结果
*_verify.json 可正常覆写。
--evidence-index 目标同样是 .json，但写基线时不得覆盖任何交付证据，
也不得覆写已存在却不属于本次 STL 的文件（R48：目标已存在时须为记录
相同 STL SHA256 的合法证据基线，否则 rc=2 拒绝覆写）。
R54：上述两份保护集合现在都从 DELIVERY_ARTIFACTS 单一清单派生，
新增派生产物时不再需要分别改动两处。

退出码：0 通过 / 1 验收不通过 / 2 输入、参数冲突或结构化结果写出失败。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import sys
import zlib
from datetime import datetime, timezone

SCHEMA_VERSION = "2.0"
# R42：与 convert_3d.ASPECT_SELF_CHECK_TOL_PCT 共享的契约，回归用例锁定相等。
ASPECT_SELF_CHECK_TOL_PCT = 1.0
EXTENT_TOL_MM = 0.01
DEGENERATE_AREA_MM2 = 1e-9
# R43：交付证据清单（与 fidelity/manifest 的 2.0 是不同的小契约，独立版本号）。
EVIDENCE_INDEX_SCHEMA = "1.0"
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
# (角色, 文件名规则, 类型)：下划线开头者按 STL 前缀派生，其余为同目录固定名。
EVIDENCE_ITEMS = (
    ("front_view", "_front.png", "png"),
    ("back_view", "_back.png", "png"),
    ("side_view", "_side.png", "png"),
    ("run_log", "run.log", "log"),
)
# R44：三视图与 STL 几何的绑定契约。与 print_ready/_verify/
# render_front_ortho.py 的正交相机约定一致：front/back 沿 ±Y 看，
# 水平为 X、垂直为 Z；side 沿 +X 看，水平为 Y、垂直为 Z。
RENDER_VIEW_AXES = {
    "front_view": (0, 2),
    "back_view": (0, 2),
    "side_view": (1, 2),
}
RENDER_FG_DELTA = 40            # 前景亮度高于背景边缘中位数的差值
RENDER_RATIO_TOL_PCT = 10.0     # 前景包围盒宽高比相对误差容限（%）
RENDER_MIN_FG_FRACTION = 0.005  # 前景像素占比下限，拒绝空白/纯背景图
# R51：只比宽高比可被「比例对的纯色矩形」「改绝对取景但比例不变」绕过。
# 真实正交渲染的前景是轮廓：包围盒内填充率约 0.46–0.51、逐行宽度变异
# 0.36–0.48、四边亮度极差 2；矩形分别是 1.0 / 0.0。阈值留足余量，
# 只拒绝「明显不是轮廓」与「背景估计不可靠」，不做形状识别。
RENDER_MAX_FILL_FRACTION = 0.90
RENDER_MIN_ROW_WIDTH_CV = 0.10
RENDER_MAX_EDGE_SPREAD = 24
# 渲染脚本对三视图共用 ortho_scale = max(Z, 水平跨度)*1.12，故 Z 像素高度
# 必须一致；front/back 沿 ±Y 看的 X 跨度也必须一致。容差覆盖抗锯齿与阴影。
RENDER_CROSS_VIEW_TOL_PCT = 5.0
# R56：统计量只能描述「像一个轮廓」，不能证明「就是这个 STL 的轮廓」。
# 将 STL 三角形与 PNG 前景分别归一化到 96² 后计算真正的轮廓 IoU。
RENDER_SILHOUETTE_GRID = 96
RENDER_MIN_SILHOUETTE_IOU = 0.65
# R45：像素解码的资源上限。MAX_EVIDENCE_BYTES 只限制输入文件字节，拦不住
# IHDR 声明 2^32×2^32 的畸形图：decompress 的 max_length 是 C 层 Py_ssize_t，
# 超限会抛 OverflowError（CLI 异常白名单原本不含它 -> 裸 traceback），逐行
# 反 filter 也会变成 CPU/内存炸弹。768² 交付图仅 0.59M 像素，余量充足。
MAX_PNG_DIMENSION = 4096
MAX_PNG_PIXELS = 4 * 1024 * 1024
MAX_PNG_RAW_BYTES = 32 * 1024 * 1024
# R46：生成侧零依赖解析 STL 本体的资源上限（交付 STL 约 37MB / 74 万面）。
MAX_STL_TRIANGLES = 5_000_000
MAX_STL_BYTES = 256 * 1024 * 1024


class MissingDependencyError(RuntimeError):
    """R46：几何复验依赖缺失；CLI 必须映射为 rc=2 的结构化执行错误。

    缺依赖既不是「验收不通过 rc=1」，更不是「通过 rc=0」。此前
    ``geometry_checks`` 直接 ``import trimesh``，未装依赖的解释器打印裸
    Traceback 且 Python 默认 rc=1 —— 与 R37/R45 的契约冲突。
    """


def _sha256(path):
    """流式哈希，避免把 37MB+ 的 STL 一次性读进内存。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(obj):
    """递归把 NaN/Inf 换成 None，保证复验结果永远是标准 JSON。

    损坏 STL 会让 trimesh 的 volume/extents 变成 NaN；Python 的 json.dump
    默认会写出 NaN 字面量，其他解析器直接拒绝，复验报告反而不可用。
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def load_json_object(path, label):
    """R37：证据文件顶层必须是 JSON 对象，畸形结构走结构化拒绝。

    旧实现 ``json.load`` 后直接 ``report.get(...)``：顶层被换成数组/字符串/
    null 时抛未捕获的 ``AttributeError``，CLI 打出裸 traceback 并以退出码 1
    结束，与「验收不通过」混淆 —— 正是 R36 刚修掉的同类问题换个入口复现。
    显式校验后抛 ValueError，由 ``main()`` 统一映射为退出码 2。
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(
            f"{label} 顶层不是 JSON 对象（实际为 "
            f"{type(data).__name__}）: {path}")
    return data


def check_mode_contract(stl_only, report_path=None, manifest_path=None,
                        require_file_verification=False,
                        require_source_provenance=False,
                        require_evidence_index=False,
                        write_evidence_index=False,
                        strict_single_body=False, json_path=None):
    """R36/R47：显式拒绝「静默丢弃用户验收要求」的参数组合。

    旧实现在 ``stl_only=True`` 时直接 return，CLI 上的 ``--report`` /
    ``--manifest`` / ``--require-file-verification`` 全部被丢弃，却仍输出
    PASS、退出码 0：用户以为强制要求了文件级闭环，实际连证据文件都没读。
    这里显式抛 ValueError（CLI 映射为退出码 2），库调用与 CLI 共用同一份
    契约，避免两层行为漂移。R43 又把 --require-evidence-index 纳入冲突，
    并拒绝 --write-evidence-index 与 --require-evidence-index 自写自验。
    R47 把「写基线」的完整冲突集合收进本函数：旧 CLI 自己只列了 3 项，
    其余 5 个验收参数被静默吞掉仍打印 [OK] rc=0 —— 正是 R36 同类缺陷。
    """
    if write_evidence_index:
        # R47：独立动作模式下任何会改变复验语义的参数都必须显式拒绝。
        # CLI 不再另维护一份 others 列表，本函数是唯一真值。
        conflicts = [name for name, used in (
            ("--stl-only", bool(stl_only)),
            ("--report", bool(report_path)),
            ("--manifest", bool(manifest_path)),
            ("--strict-single-body", bool(strict_single_body)),
            ("--require-file-verification",
             bool(require_file_verification)),
            ("--require-source-provenance",
             bool(require_source_provenance)),
            ("--require-evidence-index", bool(require_evidence_index)),
            ("--json", bool(json_path)),
        ) if used]
        if conflicts:
            raise ValueError(
                "--write-evidence-index 是独立动作，与 "
                + " / ".join(conflicts)
                + " 互斥：请先单独生成基线，再另行复验"
                  "（验收参数不会被静默丢弃）")
        return
    if not stl_only:
        return
    conflicts = [name for name, used in (
        ("--report", bool(report_path)),
        ("--manifest", bool(manifest_path)),
        ("--require-file-verification", bool(require_file_verification)),
        ("--require-source-provenance", bool(require_source_provenance)),
        ("--require-evidence-index", bool(require_evidence_index)),
    ) if used]
    if conflicts:
        raise ValueError(
            "--stl-only 只做几何复验，与 " + " / ".join(conflicts) +
            " 冲突：请去掉 --stl-only，或改用完整复验模式")


_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
# (清单键, 报告里的源文件路径键, 报告里的哈希键)
SOURCE_PROVENANCE_ITEMS = (
    ("input", "input_mesh", "input_mesh_sha256"),
    ("reference_image", "reference", "reference_image_sha256"),
)


def _resolve_evidence_path(value, origin_path=None):
    """R52：证据里记录的路径按「承载它的证据文件所在目录」解析。

    旧实现把所有路径交给 ``os.path.abspath``，即按**当前工作目录**解析。
    交付目录整体搬迁、或清单/报告改用相对路径后，从别的 CWD 复验会把
    合法成品误判 FAIL（清单定位不到 STL、源文件被判「不存在」）。
    绝对路径语义不变；``origin_path`` 缺省时退化为旧行为，保持库调用兼容。
    返回规范化绝对路径，非法输入返回 None。
    """
    if not isinstance(value, str) or not value:
        return None
    if os.path.isabs(value):
        return os.path.normcase(os.path.abspath(value))
    base = (os.path.dirname(os.path.abspath(origin_path))
            if origin_path else os.getcwd())
    return os.path.normcase(os.path.abspath(os.path.join(base, value)))


def source_provenance_checks(report, manifest, manifest_path=None,
                             report_path=None):
    """R41：把报告里的输入溯源哈希从「装饰」变成可验证据。

    对每个源文件做「报告哈希 == 清单哈希 == 磁盘重算哈希」三重印证，并要求
    报告与清单指向同一个路径。任一源文件缺失、哈希格式非法、路径不一致或
    三方哈希不符即 FAIL，附带中文可读诊断。R52：路径分别按报告/清单自身
    所在目录解析，支持交付目录整体搬迁后的复验。

    旧实现完全不读这两个字段：实证改成 'TAMPERED_INPUT' / 全零 / 整段删除，
    独立复验仍 12/12 PASS。生成侧 R40 已保证新报告不会再落下假哈希，但历史
    报告或外部替换仍需复验侧能查。该门禁默认关闭，避免把源文件已归档移走的
    历史交付误判为不合格；调用方显式要求「可溯源」时才启用。
    """
    details = []
    problems = []
    for mkey, rpath_key, rhash_key in SOURCE_PROVENANCE_ITEMS:
        entry = manifest.get(mkey)
        entry = entry if isinstance(entry, dict) else {}
        m_hash, m_path_raw = entry.get("sha256"), entry.get("path")
        r_hash = report.get(rhash_key)
        r_path_raw = report.get(rpath_key) or report.get(mkey)
        m_path = _resolve_evidence_path(m_path_raw, manifest_path)
        r_path = _resolve_evidence_path(r_path_raw, report_path)
        item = {"source": mkey, "report_field": rhash_key}
        if not (isinstance(r_hash, str) and _HEX64.fullmatch(r_hash)):
            problems.append(f"报告 {rhash_key} 缺失或不是 64 位小写十六进制")
            item["report_sha256_valid"] = False
        if not (isinstance(m_hash, str) and _HEX64.fullmatch(m_hash)):
            problems.append(f"清单 {mkey}.sha256 缺失或格式非法")
            item["manifest_sha256_valid"] = False
        path_ok = m_path is not None and os.path.isfile(m_path)
        if not path_ok:
            problems.append(f"清单 {mkey}.path 指向的源文件不存在或不可读")
            item["source_file_exists"] = False
        if r_path is None:
            problems.append(f"报告 {rpath_key} 未记录源文件路径")
            item["report_path_valid"] = False
        elif m_path is not None and r_path != m_path:
            problems.append(f"报告与清单对 {mkey} 记录了不同的源文件路径")
            item["paths_agree"] = False
        # 只在路径合法时读盘：源文件缺失应判 FAIL，而不是抛 OSError 变成 rc=2。
        if path_ok:
            try:
                disk = _sha256(m_path)
            except OSError as exc:
                problems.append(f"{mkey} 源文件读取失败: {exc}")
                item["source_file_exists"] = False
            else:
                item["disk_sha256"] = disk
                if isinstance(r_hash, str) and r_hash != disk:
                    problems.append(f"报告 {rhash_key} 与磁盘源文件哈希不一致")
                if isinstance(m_hash, str) and m_hash != disk:
                    problems.append(f"清单 {mkey}.sha256 与磁盘源文件哈希不一致")
        details.append(item)
    return not problems, ("；".join(problems) if problems else None), details


def write_json_atomic(json_path, result, protected=(), label="--json"):
    """R36：原子写结构化结果，且绝不覆盖 STL / 报告 / 清单等交付证据。

    旧实现直接 ``open(json_path, "w")``：父目录不存在时抛未捕获异常，
    stdout 已打印 PASS 却以退出码 1 崩溃（与「验收不通过」同码）；路径
    误指向 STL 时会把交付成品覆盖成一段 JSON（R13 同类事故）。这里先拒绝
    覆盖受保护文件，再写同目录临时文件并 ``os.replace``，失败清理临时文件。
    R48：``label`` 让「写复验结果」与「写证据基线」共用同一套护栏但给出
    正确参数名的诊断；两条分支传入各自的目标保护集合，不再共用一份。
    """
    target = os.path.normcase(os.path.abspath(json_path))
    for path in protected:
        if path and os.path.normcase(os.path.abspath(path)) == target:
            raise ValueError(f"{label} 不能覆盖输入或交付证据文件: {path}")
    # R38：输出是 JSON，任何非 .json 目标都意味着误指向了别的文件。
    # protected 是「按 STL 派生」的枚举，无法覆盖调用方自定义命名的证据；
    # 这条通用护栏保证 .log / .png / .stl / 无后缀文件绝不会被替换成 JSON。
    if os.path.splitext(os.path.basename(json_path))[1].lower() != ".json":
        raise ValueError(
            f"{label} 目标必须是 .json 文件，拒绝覆盖其它类型文件: {json_path}")
    parent = os.path.dirname(os.path.abspath(json_path))
    if not os.path.isdir(parent):
        raise FileNotFoundError(f"{label} 的父目录不存在: {parent}")
    tmp = os.path.join(
        parent, ".{}.{}.tmp".format(os.path.basename(json_path), os.getpid()))
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(json_safe(result), handle, ensure_ascii=False,
                      indent=2, allow_nan=False)
            handle.flush()
        os.replace(tmp, json_path)
    except BaseException:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


# R38：生产链路按 <prefix> 固定派生的证据文件。CLI 无法枚举调用方自行
# 维护的证据清单，因此这里枚举已知产出，再由 write_json_atomic 的
# 「必须 .json」通用护栏兜底。
# R54：本次交付目录内全部按 STL 前缀派生的产物，作为保护集合的**单一真值**。
# 旧实现有两份互不相干的列表：evidence_paths 手写 6 个后缀且刻意漏掉
# _verify.json，write_index_protected_paths 又从前者筛掉基线再手工补回
# _verify.json。新增证据文件（或改后缀）时只要漏改一处就会出现
# 「--json 能覆写、写基线不能」或反之的漂移，且只能靠回归偶然发现。
DELIVERY_ARTIFACTS = (
    ("fidelity_report", "_fidelity.json"),
    ("manifest", "_manifest.json"),
    ("evidence_index", "_evidence.json"),
    ("verify_result", "_verify.json"),
    ("front_view", "_front.png"),
    ("back_view", "_back.png"),
    ("side_view", "_side.png"),
)


def delivery_artifact_paths(stl_path, allow=()):
    """R54：派生全部交付产物路径；``allow`` 是本次动作的合法输出，其余全保护。

    ``run.log`` 是同目录固定名，STL 本体永远不可写；其余按
    ``DELIVERY_ARTIFACTS`` 单一清单派生。两个调用方只声明各自的合法输出，
    不再各自维护一份「哪些要保护」的列表。
    """
    absolute = os.path.abspath(stl_path)
    base = os.path.splitext(absolute)[0]
    allowed = set(allow)
    paths = [absolute, os.path.join(os.path.dirname(absolute), "run.log")]
    for name, suffix in DELIVERY_ARTIFACTS:
        if name not in allowed:
            paths.append(base + suffix)
    return tuple(paths)


def evidence_paths(stl_path):
    """R38/R54：``--json`` 分支的保护集合。

    R36 只保护 STL 与两个 JSON；实证 ``--stl-only --json <dir>/run.log``
    会把同目录运行日志原子替换成 JSON 且仍 rc=0，三视图 PNG 同理。
    ``*_verify.json`` 是 ``--json`` 的合法输出，故在此放行；其余派生
    产物（含 ``*_evidence.json``）一律保护。
    """
    return delivery_artifact_paths(stl_path, allow=("verify_result",))


def evidence_index_path(stl_path):
    """R43：证据清单按 STL 前缀派生，与 _fidelity / _manifest 同目录。"""
    return os.path.splitext(os.path.abspath(stl_path))[0] + "_evidence.json"


def write_index_protected_paths(stl_path):
    """R48/R54：写基线动作的保护集合。

    写基线的默认目标恰好是 ``*_evidence.json``，必须把它放行；而
    ``--json`` 刻意放行的 ``*_verify.json`` 在这里必须保护。两者面对
    同一批交付文件、只是合法输出不同，现在都从 ``DELIVERY_ARTIFACTS``
    派生，不再有两份手工列表可漂移。
    """
    return delivery_artifact_paths(stl_path, allow=("evidence_index",))


def guard_index_write_target(target, expected_stl_sha256):
    """R48：只允许创建文件或覆写「属于本次 STL」的既有基线（fail-closed）。

    ``protected`` 只能枚举按 STL 前缀派生的文件；调用方自定义命名的任意
    ``.json`` 路径不在其中。旧实现能把 ``--evidence-index`` 指向别人的
    报告、笔记甚至另一个交付的合法基线，一律静默覆写。这里补上纵深规则：
    目标已存在时必须是合法证据基线，且其中记录的 STL SHA256 与本次一致，
    否则抛 ValueError（CLI 映射 rc=2），绝不覆盖任何未知文件。
    """
    if not os.path.isfile(target):
        return
    try:
        obj = load_json_object(target, "--evidence-index 目标文件")
    except (OSError, ValueError) as exc:
        raise ValueError(
            "--evidence-index 目标已存在且不是合法 JSON 对象，拒绝覆写: "
            f"{exc}") from exc
    if (obj.get("schema_version") != EVIDENCE_INDEX_SCHEMA
            or not isinstance(obj.get("evidence"), list)
            or not isinstance(obj.get("stl"), dict)):
        raise ValueError(
            "--evidence-index 目标已存在但不是证据基线，拒绝覆写: "
            + target)
    if obj["stl"].get("sha256") != expected_stl_sha256:
        raise ValueError(
            "--evidence-index 目标基线属于另一个 STL（SHA256 不一致），"
            "拒绝跨交付覆写: " + target)


def _evidence_names(stl_path):
    absolute = os.path.abspath(stl_path)
    directory = os.path.dirname(absolute)
    stem = os.path.splitext(os.path.basename(absolute))[0]
    for role, suffix, kind in EVIDENCE_ITEMS:
        name = stem + suffix if suffix.startswith("_") else suffix
        yield role, name, kind, os.path.join(directory, name)


def expected_evidence_files(stl_path):
    """R50：角色 → 派生文件名的唯一真值（生成侧与复验侧共用）。

    ``build_evidence_index`` 按 ``_evidence_names`` 写文件名，而旧
    ``evidence_index_checks`` 只校验角色集合与哈希、不校验二者映射：实证把
    ``front_view`` 改指向同目录另一张合规 PNG 并同步改哈希/字节数，13/13
    仍 PASS —— 正面渲染图就此脱出哈希链，却没有任何一项检查察觉。
    """
    return {role: name for role, name, _, _ in _evidence_names(stl_path)}


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_container_valid(path):
    """R43：零第三方依赖校验 PNG 容器完整性，返回 (ok, reason, w, h)。

    不依赖 Pillow / trimesh，只用标准库逐 chunk 重算 CRC：垃圾字节、截断、
    CRC 被改、缺 IDAT/IEND、IEND 后有多余数据全部能查出。这只保证「文件是
    一张结构完好的 PNG」，不保证内容来自本次交付 —— 后者由证据清单的
    SHA256 与三视图互异校验负责。
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_EVIDENCE_BYTES + 1)
    except OSError as exc:
        return False, f"无法读取: {exc}", None, None
    if len(data) > MAX_EVIDENCE_BYTES:
        return False, f"PNG 超过 {MAX_EVIDENCE_BYTES} 字节上限", None, None
    if not data.startswith(_PNG_SIGNATURE):
        return False, "PNG 签名无效", None, None
    width = height = None
    has_idat = has_iend = False
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            return False, f"PNG chunk {ctype!r} 被截断", width, height
        payload = data[pos + 8:pos + 8 + length]
        stored_crc = struct.unpack(">I", data[pos + 8 + length:end])[0]
        if (zlib.crc32(ctype + payload) & 0xFFFFFFFF) != stored_crc:
            return False, f"PNG chunk {ctype.decode('latin1')} CRC 不符", width, height
        if ctype == b"IHDR":
            if length != 13:
                return False, "IHDR 长度不是 13", None, None
            width, height = struct.unpack(">II", payload[:8])
        elif ctype == b"IDAT":
            has_idat = True
        elif ctype == b"IEND":
            has_iend = True
            if end != len(data):
                return False, "IEND 之后存在多余字节", width, height
        pos = end
        if has_iend:
            break
    if not has_iend:
        return False, "PNG 缺少 IEND", width, height
    if not has_idat:
        return False, "PNG 缺少 IDAT", width, height
    if not (isinstance(width, int) and isinstance(height, int)
            and width > 0 and height > 0):
        return False, "IHDR 尺寸无效", width, height
    return True, None, width, height


def _decode_png_luma(path):
    """R44：零第三方依赖把 8-bit 非隔行 PNG 解成 (w, h, bytearray 亮度)。

    png_container_valid 只验容器/CRC；这里真正读像素，供渲染内容与 STL
    几何绑定。返回 (width, height, luma, None) 或 (None, None, None, reason)。
    支持 color type 0/2/4/6（灰/RGB/灰+Alpha/RGBA），位深固定 8；不支持的
    格式一律结构化拒绝，绝不抛栈（验收不通过须与执行错误 rc=2 区分）。
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_EVIDENCE_BYTES + 1)
    except OSError as exc:
        return None, None, None, f"无法读取: {exc}"
    if len(data) > MAX_EVIDENCE_BYTES:
        return None, None, None, "PNG 超过大小上限"
    if not data.startswith(_PNG_SIGNATURE):
        return None, None, None, "PNG 签名无效"
    width = height = depth = color = interlace = None
    idat = []
    pos = 8
    try:
        while pos + 8 <= len(data):
            length = struct.unpack(">I", data[pos:pos + 4])[0]
            ctype = data[pos + 4:pos + 8]
            end = pos + 12 + length
            if end > len(data):
                return None, None, None, "PNG chunk 被截断"
            if ctype == b"IHDR":
                if length != 13:
                    return None, None, None, "IHDR 长度不是 13"
                width, height, depth, color, _, _, interlace = struct.unpack(
                    ">IIBBBBB", data[pos + 8:pos + 21])
            elif ctype == b"IDAT":
                idat.append(data[pos + 8:pos + 8 + length])
            elif ctype == b"IEND":
                break
            pos = end
    except struct.error as exc:
        return None, None, None, f"PNG 结构解析失败: {exc}"
    if (not width or not height or depth != 8
            or color not in (0, 2, 4, 6) or interlace != 0):
        return None, None, None, "仅支持 8-bit 非隔行 灰/RGB/灰+Alpha/RGBA PNG"
    # R45：先按 IHDR 声明值设上限，再分配任何缓冲区 / 调 C 层解压。
    # 容器层（png_container_valid）仍可判这种 PNG「结构完好」，拒绝理由
    # 必须由解码层给出，且必须是结构化 FAIL 而不是异常。
    if (width > MAX_PNG_DIMENSION or height > MAX_PNG_DIMENSION
            or width * height > MAX_PNG_PIXELS):
        return None, None, None, (
            f"PNG 声明尺寸超过解码上限（单边 {MAX_PNG_DIMENSION}px / "
            f"{MAX_PNG_PIXELS} 像素）: {width}x{height}")
    bpp = {0: 1, 2: 3, 4: 2, 6: 4}[color]
    stride = width * bpp
    expected = (stride + 1) * height
    if expected > MAX_PNG_RAW_BYTES:
        return None, None, None, (
            f"PNG 解压后数据超过 {MAX_PNG_RAW_BYTES} 字节上限")
    # decompress 的 max_length 上限挡住解压炸弹：最多只取需要的字节数。
    try:
        raw = zlib.decompressobj().decompress(b"".join(idat), expected + 1)
    except (zlib.error, OverflowError, ValueError, MemoryError) as exc:
        return None, None, None, f"IDAT 解压失败或资源超限: {exc}"
    if len(raw) < expected:
        return None, None, None, "IDAT 像素数据不足"
    luma = bytearray(width * height)
    prev = bytearray(stride)
    src = 0
    for y in range(height):
        ftype = raw[src]
        src += 1
        line = bytearray(raw[src:src + stride])
        src += stride
        if ftype == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif ftype == 3:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif ftype == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        elif ftype != 0:
            return None, None, None, f"非法 PNG 行滤波器类型 {ftype}"
        base = y * width
        if bpp >= 3:
            for x in range(width):
                i = x * bpp
                luma[base + x] = (line[i] + line[i + 1] + line[i + 2]) // 3
        else:
            luma[base:base + width] = line[::bpp]
        prev = line
    return width, height, luma, None


def _foreground_info(width, height, luma):
    """从已解码亮度图提取前景统计；供基础绑定与深度轮廓绑定共用。"""
    edge = [luma[x] for x in range(width)]
    edge += [luma[(height - 1) * width + x] for x in range(width)]
    edge += [luma[y * width] for y in range(height)]
    edge += [luma[y * width + width - 1] for y in range(height)]
    edge.sort()
    background = edge[len(edge) // 2]
    # R51：四边亮度极差过大说明背景不是纯色（渐变/发光边框），此时按边缘
    # 中位数估背景不可信，必须让调用方结构化拒绝，不能悄悄算出一个假轮廓。
    edge_spread = int(edge[-1] - edge[0])
    threshold = min(255, background + RENDER_FG_DELTA)
    min_x, min_y, max_x, max_y, count = width, height, -1, -1, 0
    for y in range(height):
        base = y * width
        for x in range(width):
            if luma[base + x] > threshold:
                count += 1
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    fraction = count / float(width * height)
    info = {"background_luma": background, "threshold": threshold,
            "foreground_fraction": round(fraction, 5),
            "edge_spread": edge_spread}
    if count == 0 or fraction < RENDER_MIN_FG_FRACTION:
        return False, "前景像素为空或占比过低，疑似纯背景图", info
    ratio = (max_x - min_x + 1) / float(max_y - min_y + 1)
    info["bbox_xyxy"] = [min_x, min_y, max_x, max_y]
    info["aspect_ratio"] = round(ratio, 5)
    # R51：只在包围盒内做第二遍扫描（约 12 万像素，远小于全图 59 万），
    # 得到填充率与逐行宽度变异，供 render_binding_checks 判断是不是轮廓。
    inner, row_widths = 0, []
    for y in range(min_y, max_y + 1):
        base = y * width
        lo, hi, row_count = -1, -1, 0
        for x in range(min_x, max_x + 1):
            if luma[base + x] > threshold:
                row_count += 1
                if lo < 0:
                    lo = x
                hi = x
        inner += row_count
        row_widths.append(hi - lo + 1 if row_count else 0)
    area = (max_x - min_x + 1) * (max_y - min_y + 1)
    mean = sum(row_widths) / float(len(row_widths))
    variance = sum((value - mean) ** 2 for value in row_widths) / float(len(row_widths))
    cv = math.sqrt(variance) / mean if mean else 0.0
    info["fill_fraction"] = round(inner / float(area), 5)
    info["row_width_cv"] = round(cv, 5)
    return True, None, info


def _png_foreground_details(path):
    """解码一次并返回统计与像素，避免深度绑定重复做昂贵的 PNG 解码。"""
    width, height, luma, reason = _decode_png_luma(path)
    if reason:
        return False, reason, None, width, height, luma
    ok, reason, info = _foreground_info(width, height, luma)
    return ok, reason, info, width, height, luma


def png_foreground_bbox(path):
    """R44：从渲染 PNG 提取前景包围盒/宽高比，返回 (ok, reason, info)。

    背景用图像四条边的亮度中位数估计（正交渲染四周必为纯背景），
    前景 = 亮度 > 背景 + RENDER_FG_DELTA。这样不依赖固定颜色，也不依赖
    Blender 的色域转换；只要求渲染脚本沿用「深色背景 + 浅色模型」。
    """
    ok, reason, info, _, _, _ = _png_foreground_details(path)
    return ok, reason, info


def render_binding_checks(extents_xyz, view_paths):
    """R44：把三视图的像素轮廓与 STL 正交投影几何绑定。

    与 R43 的 SHA256 基线不同，这里不信任任何落盘元数据：即使有人把证据
    文件与基线一起换成另一套自洽文件，只要 STL 不变，换进来的渲染图前景
    宽高比就必须与该 STL 的包围盒比例一致，否则拒绝。

    ``view_paths`` 为 {role: path}；``extents_xyz`` 来自独立几何复验。
    返回 (ok, reason, details)，不抛栈。

    R51：R44 只比「前景包围盒宽高比」。实证两张图能绕过：① 纯色矩形
    只要宽高比凑对（0.25364）就 13/13 PASS；② 把矩形整体缩小到
    152×600（比例仍 0.2533）也能 PASS。前者用轮廓形状指标拒绝，后者
    用三视图在同一正交相机下的像素尺度互校拒绝。两者都并回已有
    ``evidence_index_valid``，不新增检查项、不改默认输出。
    """
    problems, details = [], []
    try:
        extents = [float(v) for v in extents_xyz]
        if len(extents) != 3 or not all(
                math.isfinite(v) and v > 0 for v in extents):
            raise ValueError
    except (TypeError, ValueError):
        return False, "STL 包围盒 extents_xyz 非法，无法做渲染绑定", details
    for role, (h_axis, v_axis) in RENDER_VIEW_AXES.items():
        expected = extents[h_axis] / extents[v_axis]
        entry = {"role": role, "expected_ratio": round(expected, 5)}
        path = view_paths.get(role)
        if not path or not os.path.isfile(path):
            entry["ok"] = False
            entry["reason"] = "渲染图缺失"
            problems.append(f"{role} 渲染图缺失，无法做几何绑定")
            details.append(entry)
            continue
        ok, reason, info = png_foreground_bbox(path)
        if not ok:
            entry["ok"] = False
            entry["reason"] = reason
            problems.append(f"{role} 像素不可解析: {reason}")
            details.append(entry)
            continue
        error = abs(info["aspect_ratio"] - expected) / expected * 100.0
        shape_issues = []
        if info["fill_fraction"] > RENDER_MAX_FILL_FRACTION:
            shape_issues.append(
                f"前景填充率 {info['fill_fraction']} 过高，疑似纯色块而非模型轮廓")
        if info["row_width_cv"] < RENDER_MIN_ROW_WIDTH_CV:
            shape_issues.append(
                f"逐行前景宽度变异 {info['row_width_cv']} 过低，疑似等宽矩形")
        if info["edge_spread"] > RENDER_MAX_EDGE_SPREAD:
            shape_issues.append(
                f"四边亮度极差 {info['edge_spread']} 过大，背景估计不可靠")
        ratio_ok = error <= RENDER_RATIO_TOL_PCT
        entry.update({"ok": bool(ratio_ok and not shape_issues),
                      "measured_ratio": info["aspect_ratio"],
                      "error_pct": round(error, 2),
                      "bbox_xyxy": info["bbox_xyxy"],
                      "fill_fraction": info["fill_fraction"],
                      "row_width_cv": info["row_width_cv"],
                      "edge_spread": info["edge_spread"]})
        if not ratio_ok:
            problems.append(
                f"{role} 前景轮廓比例 {info['aspect_ratio']} 与 STL 期望 "
                f"{round(expected, 5)} 相差 {error:.1f}%（容差 "
                f"{RENDER_RATIO_TOL_PCT}%），疑似来自其它模型")
        for issue in shape_issues:
            problems.append(f"{role} {issue}")
        details.append(entry)

    # R51：三视图共用同一正交相机，Z 像素高度与 front/back 的 X 跨度
    # 必须互相一致。只比各自与 STL 的比例时，「换图但按正确比例绘制」
    # 或「改绝对取景高度」都察觉不到；这里做不依赖任何落盘元数据的互校。
    by_role = {item["role"]: item for item in details}
    boxes = {role: item.get("bbox_xyxy") for role, item in by_role.items()
             if isinstance(item.get("bbox_xyxy"), (list, tuple))
             and len(item["bbox_xyxy"]) == 4}
    if len(boxes) == len(RENDER_VIEW_AXES):
        heights = {role: box[3] - box[1] + 1 for role, box in boxes.items()}
        ref_height = heights["front_view"]
        for role, value in heights.items():
            deviation = abs(value - ref_height) / float(ref_height) * 100.0
            if deviation > RENDER_CROSS_VIEW_TOL_PCT:
                problems.append(
                    f"{role} 前景高度 {value}px 与正视图 {ref_height}px 相差 "
                    f"{deviation:.1f}%（同一正交相机下三视图 Z 尺度应一致，"
                    f"容差 {RENDER_CROSS_VIEW_TOL_PCT}%）")
                by_role[role]["ok"] = False
        front_w = boxes["front_view"][2] - boxes["front_view"][0] + 1
        back_w = boxes["back_view"][2] - boxes["back_view"][0] + 1
        width_dev = abs(front_w - back_w) / float(max(back_w, 1)) * 100.0
        if width_dev > RENDER_CROSS_VIEW_TOL_PCT:
            problems.append(
                f"正/背视图前景宽度 {front_w}px / {back_w}px 相差 "
                f"{width_dev:.1f}%（沿 ±Y 看的 X 跨度应一致）")
            by_role["front_view"]["ok"] = False
            by_role["back_view"]["ok"] = False
    return not problems, ("；".join(problems) if problems else None), details


def _normalized_png_foreground(path, grid_size, np, Image):
    """把 PNG 前景包围盒归一化为布尔掩膜；解码与统计只各做一次。"""
    ok, reason, info, width, height, luma = _png_foreground_details(path)
    if not ok:
        return None, reason
    x0, y0, x1, y1 = info["bbox_xyxy"]
    pixels = np.frombuffer(luma, dtype=np.uint8).reshape(height, width)
    crop = (pixels[y0:y1 + 1, x0:x1 + 1] > info["threshold"])
    image = Image.fromarray(crop.astype(np.uint8) * 255)
    resampling = getattr(Image, "Resampling", Image)
    image = image.resize((grid_size, grid_size), resampling.NEAREST)
    return np.asarray(image, dtype=bool), None


def _mask_iou(a, b, np):
    union = int(np.logical_or(a, b).sum())
    if not union:
        return 0.0
    return float(np.logical_and(a, b).sum()) / union


def stl_silhouette_checks(stl_path, view_paths, grid_size=None):
    """R56：直接比较 STL 正交投影与三视图前景的归一化轮廓 IoU。

    R44/R51 的包围盒、填充率、行宽变异都是「形状统计量」，可被另一形状
    针对性凑齐；实证三张菱形图在全部旧判据下仍 PASS。本函数不信任这些
    标量，而是从 STL 三角形本体重建三方向掩膜，与 PNG 前景逐像素比较。
    双方各自按前景包围盒归一化，因此不重复 R51 的绝对取景尺度判据；
    同时计算原向与水平镜像，兼容沿 ±Y 观察时相机水平轴方向差异。

    仅在显式证据验收中调用，默认 12 项输出与耗时不变。返回
    ``(ok, reason, details)``；缺依赖属于执行错误，畸形网格/图片为结构化
    FAIL，不抛裸栈。
    """
    grid = int(grid_size or RENDER_SILHOUETTE_GRID)
    if not 16 <= grid <= 256:
        return False, f"轮廓栅格尺寸必须在 [16, 256]，收到 {grid}", []
    try:
        import numpy as np
        import trimesh
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise MissingDependencyError(
            f"轮廓级证据绑定需要 numpy/trimesh/Pillow: {exc}") from exc

    try:
        mesh = trimesh.load(stl_path, force="mesh", process=False)
        triangles = np.asarray(mesh.triangles, dtype=np.float64)
        if (triangles.ndim != 3 or triangles.shape[1:] != (3, 3)
                or len(triangles) == 0):
            return False, "STL 没有可用于轮廓投影的三角面", []
        if len(triangles) > MAX_STL_TRIANGLES:
            return False, "STL 三角形数超过轮廓投影资源上限", []
        if not np.isfinite(triangles).all():
            return False, "STL 含非有限顶点，无法生成轮廓", []
        lower = triangles.min(axis=(0, 1))
        upper = triangles.max(axis=(0, 1))
        extents = upper - lower
        if not np.all(extents > 0):
            return False, "STL 某轴零厚度，无法生成三视图轮廓", []
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return False, f"STL 轮廓投影无法执行: {type(exc).__name__}: {exc}", []

    problems, details = [], []
    for role, (h_axis, v_axis) in RENDER_VIEW_AXES.items():
        entry = {"role": role, "grid_size": grid,
                 "min_iou": RENDER_MIN_SILHOUETTE_IOU}
        path = view_paths.get(role)
        if not path or not os.path.isfile(path):
            entry.update({"ok": False, "reason": "渲染图缺失"})
            problems.append(f"{role} 缺失，无法做轮廓级绑定")
            details.append(entry)
            continue
        try:
            projected = triangles[:, :, [h_axis, v_axis]].copy()
            projected[:, :, 0] = ((projected[:, :, 0] - lower[h_axis])
                                  / extents[h_axis] * (grid - 1))
            projected[:, :, 1] = ((upper[v_axis] - projected[:, :, 1])
                                  / extents[v_axis] * (grid - 1))
            canvas = Image.new("1", (grid, grid), 0)
            draw = ImageDraw.Draw(canvas)
            for triangle in projected:
                draw.polygon([(float(triangle[0, 0]), float(triangle[0, 1])),
                              (float(triangle[1, 0]), float(triangle[1, 1])),
                              (float(triangle[2, 0]), float(triangle[2, 1]))],
                             fill=1)
            mesh_mask = np.asarray(canvas, dtype=bool)
            png_mask, reason = _normalized_png_foreground(
                path, grid, np, Image)
            if png_mask is None:
                raise ValueError(reason)
            direct = _mask_iou(mesh_mask, png_mask, np)
            mirrored = _mask_iou(mesh_mask[:, ::-1], png_mask, np)
            score = max(direct, mirrored)
            entry.update({"ok": bool(score >= RENDER_MIN_SILHOUETTE_IOU),
                          "silhouette_iou": round(score, 5),
                          "direct_iou": round(direct, 5),
                          "mirrored_iou": round(mirrored, 5),
                          "used_horizontal_mirror": bool(mirrored > direct)})
            if not entry["ok"]:
                problems.append(
                    f"{role} 的 PNG 前景与 STL 投影轮廓 IoU 仅 {score:.4f}"
                    f"（要求 >= {RENDER_MIN_SILHOUETTE_IOU}），形状并非同一模型")
        except (OSError, ValueError, TypeError, MemoryError) as exc:
            entry.update({"ok": False, "reason": f"{type(exc).__name__}: {exc}"})
            problems.append(f"{role} 轮廓级绑定失败: {exc}")
        details.append(entry)
    return not problems, ("；".join(problems) if problems else None), details


def stl_extents_from_file(path):
    """R46：零第三方依赖从 STL 本体解析 XYZ 包围盒，返回 (ok, reason, extents)。

    ``--write-evidence-index`` 是独立动作模式，刻意不依赖 trimesh / numpy；
    但生成侧要与 R44 复验侧共用同一套几何绑定判据，就必须拿到 STL 的真实
    尺寸。这里只读 STL 本体，不读报告/清单里的 extents 元数据 —— 与 R44
    「不信任落盘元数据」同一原则。支持二进制与 ASCII STL；声明与文件大小
    不符、三角形数超限、无顶点、坐标非有限、某轴零厚度一律结构化拒绝。
    """
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return False, f"无法读取 STL: {exc}", None
    if size < 84:
        return False, "STL 文件过短（不足 84 字节）", None
    if size > MAX_STL_BYTES:
        return False, f"STL 超过 {MAX_STL_BYTES} 字节解析上限", None
    try:
        with open(path, "rb") as handle:
            head = handle.read(84)
            count = struct.unpack("<I", head[80:84])[0]
            # 用「文件大小 == 84 + 50*count」而非头 80 字节是否以 solid
            # 开头来判二进制：很多二进制 STL 的头恰好写着 "solid ..."。
            binary = (0 < count <= MAX_STL_TRIANGLES
                      and size == 84 + 50 * count)
            if binary:
                body = handle.read(50 * count)
                text = None
            else:
                body = None
                handle.seek(0)
                text = handle.read().decode("latin-1")
    except (OSError, struct.error, UnicodeError) as exc:
        return False, f"STL 读取/解析失败: {exc}", None

    minx = miny = minz = math.inf
    maxx = maxy = maxz = -math.inf
    vertices = 0
    if binary:
        try:
            for facet in struct.iter_unpack("<12fH", body):
                for base in (3, 6, 9):
                    x, y, z = facet[base], facet[base + 1], facet[base + 2]
                    if not (math.isfinite(x) and math.isfinite(y)
                            and math.isfinite(z)):
                        return False, "二进制 STL 含非有限顶点坐标", None
                    if x < minx:
                        minx = x
                    if x > maxx:
                        maxx = x
                    if y < miny:
                        miny = y
                    if y > maxy:
                        maxy = y
                    if z < minz:
                        minz = z
                    if z > maxz:
                        maxz = z
                    vertices += 1
        except struct.error as exc:
            return False, f"二进制 STL 三角形解析失败: {exc}", None
    else:
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0].lower() == "vertex":
                try:
                    x, y, z = (float(parts[1]), float(parts[2]),
                               float(parts[3]))
                except ValueError:
                    return False, "ASCII STL 含非法顶点坐标", None
                if not (math.isfinite(x) and math.isfinite(y)
                        and math.isfinite(z)):
                    return False, "ASCII STL 含非有限顶点坐标", None
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
                minz, maxz = min(minz, z), max(maxz, z)
                vertices += 1
    if vertices == 0:
        return False, "STL 中未找到任何顶点（或三角形数与文件大小不符）", None
    extents = [maxx - minx, maxy - miny, maxz - minz]
    if not all(math.isfinite(v) and v > 0 for v in extents):
        return False, "STL 包围盒非法（非有限值或某轴零厚度）", None
    return True, None, extents


def build_evidence_index(stl_path):
    """R43：从当前磁盘产物生成证据基线；只在动作模式下调用，不参与复验。

    刻意不把 *_verify.json / fidelty / manifest 纳入：那些是复验输入或输出，
    会随每次复验变化。这里锁定的是「用户直接查看、且此前无任何校验」的
    三视图与运行日志，外加 STL 自身的哈希做绑定锚点。
    """
    absolute = os.path.abspath(stl_path)
    if not os.path.isfile(absolute):
        raise FileNotFoundError(f"STL 不存在或不是文件: {absolute}")
    entries = []
    for role, name, kind, path in _evidence_names(absolute):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"交付证据缺失: {path}")
        with open(path, "rb") as handle:
            data = handle.read(MAX_EVIDENCE_BYTES + 1)
        if len(data) > MAX_EVIDENCE_BYTES:
            raise ValueError(f"交付证据超过大小上限: {path}")
        item = {"role": role, "file": name, "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
        if kind == "png":
            ok, reason, width, height = png_container_valid(path)
            if not ok:
                raise ValueError(f"{name} 不是完好的 PNG: {reason}")
            item["width"], item["height"] = width, height
        elif not data.strip():
            raise ValueError(f"{name} 为空或只含空白")
        entries.append(item)
    view_hashes = [e["sha256"] for e in entries if e["role"].endswith("_view")]
    if len(set(view_hashes)) != len(view_hashes):
        raise ValueError("三视图存在逐字节重复，疑似复制冒充")
    # R46：生成侧与复验侧必须共用同一套判据。旧实现只验容器 CRC + 哈希 +
    # 三视图互异，能对「换成别的模型渲染图」或 R45 畸形 IHDR 图打印 [OK]
    # 写出基线，而 --require-evidence-index 必然判 FAIL —— 用户拿到一份
    # 永远无法复验通过的自相矛盾基线。这里从 STL 本体算包围盒并复用
    # render_binding_checks，不信任任何落盘元数据；基线 schema 不变。
    ok, reason, extents = stl_extents_from_file(absolute)
    if not ok:
        raise ValueError(f"证据基线未写出：无法从 STL 本体解析包围盒: {reason}")
    view_paths = {role: path for role, _, kind, path
                  in _evidence_names(absolute) if kind == "png"}
    rb_ok, rb_reason, _ = render_binding_checks(extents, view_paths)
    if not rb_ok:
        raise ValueError(
            f"证据基线未写出：三视图与 STL 几何绑定失败: {rb_reason}")
    return {
        "schema_version": EVIDENCE_INDEX_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stl": {"file": os.path.basename(absolute),
                "bytes": os.path.getsize(absolute),
                "sha256": _sha256(absolute)},
        "evidence": entries,
    }


def _safe_evidence_filename(name):
    """R43：清单里只允许纯文件名，杜绝 ../ 与绝对路径造成的目录穿越。"""
    return (isinstance(name, str) and bool(name)
            and name not in (".", "..")
            and not os.path.isabs(name)
            and "/" not in name and "\\" not in name
            and ":" not in name and "\x00" not in name)


def evidence_index_checks(stl_path, index_path=None):
    """R43：核对证据基线与磁盘产物，返回 (ok, reason, details)。

    清单结构畸形、条目缺失、文件名越界、字节数/哈希不符、PNG 容器损坏、
    三视图尺寸不一致、三视图被复制冒充、日志为空一律判 FAIL 并给中文诊断；
    不抛栈（验收不通过应与执行错误 rc=2 区分开）。
    """
    absolute = os.path.abspath(stl_path)
    directory = os.path.dirname(absolute)
    index_path = index_path or evidence_index_path(absolute)
    details, problems = [], []
    if not os.path.isfile(index_path):
        return False, f"证据清单不存在: {index_path}", details
    try:
        index = load_json_object(index_path, "evidence.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"证据清单不可读或结构非法: {exc}", details
    if index.get("schema_version") != EVIDENCE_INDEX_SCHEMA:
        problems.append(f"证据清单 schema_version 不是 {EVIDENCE_INDEX_SCHEMA}")

    stl_entry = index.get("stl")
    stl_entry = stl_entry if isinstance(stl_entry, dict) else {}
    if stl_entry.get("file") != os.path.basename(absolute):
        problems.append("证据清单记录的 STL 文件名与本次复验对象不一致")
    try:
        stl_bytes = os.path.getsize(absolute)
        stl_hash = _sha256(absolute)
    except OSError as exc:
        return False, f"STL 读取失败: {exc}", details
    if stl_entry.get("bytes") != stl_bytes or stl_entry.get("sha256") != stl_hash:
        problems.append("证据清单与磁盘 STL 的字节数或 SHA256 不一致")

    raw = index.get("evidence")
    raw = raw if isinstance(raw, list) else []
    expected_roles = {role for role, _, _ in EVIDENCE_ITEMS}
    expected_files = expected_evidence_files(absolute)
    got_roles = [e.get("role") for e in raw if isinstance(e, dict)]
    if len(raw) != len(EVIDENCE_ITEMS) or set(got_roles) != expected_roles:
        problems.append(
            f"证据条目集合不完整（应为 {sorted(expected_roles)}）")

    disk_view_hashes = []
    for item in raw:
        item = item if isinstance(item, dict) else {}
        role, name = item.get("role"), item.get("file")
        entry = {"role": role, "file": name}
        if not _safe_evidence_filename(name):
            problems.append(f"{role} 的文件名非法或含路径穿越: {name!r}")
            details.append(entry)
            continue
        # R50：角色必须绑定到该交付派生出的固定文件名。只查角色集合时，
        # 换成同目录另一张合规 PNG 并同步改哈希就能让某项证据脱离哈希链。
        want_name = expected_files.get(role)
        if want_name is not None and name != want_name:
            problems.append(
                f"{role} 绑定了错误的文件 {name!r}（应为 {want_name!r}）")
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            problems.append(f"{role} 对应的交付证据已丢失: {name}")
            details.append(entry)
            continue
        with open(path, "rb") as handle:
            data = handle.read(MAX_EVIDENCE_BYTES + 1)
        digest = hashlib.sha256(data).hexdigest()
        entry["bytes"], entry["sha256"] = len(data), digest
        if len(data) > MAX_EVIDENCE_BYTES:
            problems.append(f"{role} 超过大小上限: {name}")
        if item.get("bytes") != len(data) or item.get("sha256") != digest:
            problems.append(f"{role} 与证据清单的字节数或 SHA256 不一致: {name}")
        if role and role.endswith("_view"):
            ok, reason, width, height = png_container_valid(path)
            entry["png_valid"], entry["width"], entry["height"] = ok, width, height
            if not ok:
                problems.append(f"{role} 不是完好的 PNG: {name}（{reason}）")
            if item.get("width") != width or item.get("height") != height:
                problems.append(f"{role} 的 PNG 尺寸与证据清单不符: {name}")
            disk_view_hashes.append(digest)
        elif not data.strip():
            problems.append(f"{role} 为空或只含空白: {name}")
        details.append(entry)

    widths = {(e.get("width"), e.get("height")) for e in details
              if isinstance(e.get("role"), str) and e["role"].endswith("_view")
              and e.get("png_valid")}
    if len(widths) > 1:
        problems.append("三视图的 PNG 尺寸互不一致")
    if disk_view_hashes and len(set(disk_view_hashes)) != len(disk_view_hashes):
        problems.append("三视图存在逐字节重复，疑似复制冒充")
    return not problems, ("；".join(problems) if problems else None), details


# R32：主链路与独立复验共享的几何判据。独立复验不能只信报告里汇总的
# ``file_verification.pass``，必须拿自己重算的结果逐项对照。
FV_SHARED_GEOMETRY_CHECKS = (
    "welded_watertight", "winding_consistent",
    "positive_volume", "closed_solid",
)


def _flag_true(value):
    """只接受真正的布尔真或整数 1；拒绝 "false" 这类字符串蒙混过关。"""
    return value is True or (isinstance(value, int)
                             and not isinstance(value, bool) and value == 1)


# R33：build_verdict() 的 checks 恒为这 5 项（与 --strict-watertight 无关，
# 该开关只改 required_checks 的范围）。独立复验把这个集合作为内置契约，
# 不采信报告里可被删改的 required_checks，避免「少判几项也算通过」。
VERDICT_KNOWN_CHECKS = (
    "silhouette_iou", "watertight", "no_boundary_edges",
    "no_nonmanifold_edges", "aspect_self_check",
)
# build_verdict 在两种模式下都会把这两项列为必需，删掉它们必属篡改。
VERDICT_ALWAYS_REQUIRED = ("silhouette_iou", "aspect_self_check")


def _is_bool_flag(value):
    """判据值必须是真正的布尔或 0/1 整数，拒绝字符串与任意其他真值。"""
    return isinstance(value, bool) or (
        isinstance(value, int) and not isinstance(value, bool)
        and value in (0, 1))


def _finite_number(value):
    """R42：只把真正的有限数值转成 float；布尔/字符串/NaN/Inf 一律拒绝。"""
    if value is None or isinstance(value, (bool, str, bytes)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def verdict_numeric_consistency(report, manifest, checks):
    """R42：按已落盘的阈值与指标重算 verdict 的两项数值判据。

    R33/R34 只锁死布尔自洽与判据集合。实证把 ``final_mesh.silhouette_iou``
    改成 0.20、``min_iou`` 改成 0.99、``aspect_error_pct`` 改成 99，甚至删掉
    报告里的 ``min_iou``，独立复验仍 12/12 PASS —— 数值与结论自相矛盾完全
    查不出来。报告其实已写入 ``min_iou``，清单 ``parameters.min_iou`` 又是
    独立第二证据源，因此复验侧具备重算条件。

    阈值双源：两处都有且不一致即 FAIL；只有一处有则用该处；两处都无则
    跳过 IoU 数值重算（兼容不含该字段的旧报告）。宽高比容差取与生成侧
    共享的 ``ASPECT_SELF_CHECK_TOL_PCT``。通过时返回 ``(True, None)``，
    保证默认复验输出与历史交付逐字节一致。
    """
    problems = []
    report = report if isinstance(report, dict) else {}
    manifest = manifest if isinstance(manifest, dict) else {}
    if not isinstance(checks, dict):
        return False, "verdict.checks 缺失或不是对象"
    for key in ("silhouette_iou", "aspect_self_check"):
        if key not in checks:
            return False, f"verdict.checks 缺少 {key}"

    rep_threshold = _finite_number(report.get("min_iou"))
    params = manifest.get("parameters")
    man_threshold = _finite_number(
        params.get("min_iou") if isinstance(params, dict) else None)
    if (rep_threshold is not None and man_threshold is not None
            and abs(rep_threshold - man_threshold) > 1e-9):
        problems.append("报告 min_iou 与清单 parameters.min_iou 不一致")
    threshold = rep_threshold if rep_threshold is not None else man_threshold
    # 键存在但值畸形：不能静默退化到另一证据源（与 R39 生成侧同严）。
    if "min_iou" in report and rep_threshold is None:
        problems.append("报告 min_iou 不是有限数值")
    if isinstance(params, dict) and "min_iou" in params and man_threshold is None:
        problems.append("清单 parameters.min_iou 不是有限数值")

    final = report.get("final_mesh")
    final = final if isinstance(final, dict) else {}
    iou = _finite_number(final.get("silhouette_iou",
                                   report.get("silhouette_iou")))
    if threshold is not None:
        if iou is None:
            problems.append(
                "final_mesh.silhouette_iou 缺失或非有限数值，无法重算 IoU 判据")
        elif bool(checks["silhouette_iou"]) != bool(iou >= threshold):
            problems.append(
                f"verdict.silhouette_iou 与重算不符（IoU {iou} / 阈值 {threshold}）")

    aspect = _finite_number(report.get("aspect_error_pct"))
    if "aspect_error_pct" in report and aspect is None:
        problems.append("报告 aspect_error_pct 不是有限数值")
    if aspect is not None:
        expected = bool(aspect <= ASPECT_SELF_CHECK_TOL_PCT)
        if bool(checks["aspect_self_check"]) != expected:
            problems.append(
                f"verdict.aspect_self_check 与重算不符（误差 {aspect}% / 容差 "
                f"{ASPECT_SELF_CHECK_TOL_PCT}%）")
    return not problems, ("；".join(problems) if problems else None)


def verdict_checks_valid(verdict, geometry_checks, report=None, manifest=None):
    """独立校验 verdict 的结构、汇总自洽性与跨层一致性。

    R33 之前只做 ``all(verdict["checks"].values())``，实证可绕过：把某个
    判据写成 ``"false"``（truthy）、整数 2、删掉任一必需判据，甚至把整个
    checks 换成 ``{"forged": True}``，独立复验仍会 12/12 PASS。
    R34 修正语义：``verdict.pass`` 是「按 required_checks 重算的内存结论
    ∧ file_verification_pass」的复合结果，不是单纯的内存结论。

    R42：新增可选的 ``report`` / ``manifest``，按已落盘阈值重算两项数值
    判据（见 ``verdict_numeric_consistency``）；库调用不传时跳过，保持旧行为。

    返回 ``(ok, reason)``；reason 为 None 表示通过，否则是可诊断的中文原因。
    自洽地判定不合格也返回 False（交付物必须 PASS），但 reason 会指向真正的
    失败环节，而不是笼统报「汇总不一致」。畸形对象一律判失败，不抛栈。
    """
    if not isinstance(verdict, dict):
        return False, "verdict 缺失或不是对象"
    checks = verdict.get("checks")
    if not isinstance(checks, dict):
        return False, "verdict.checks 缺失或不是对象"
    missing = [k for k in VERDICT_KNOWN_CHECKS if k not in checks]
    if missing:
        return False, "verdict.checks 缺少必需判据: " + ",".join(missing)
    bad_type = [k for k, v in checks.items() if not _is_bool_flag(v)]
    if bad_type:
        return False, "verdict.checks 含非布尔值: " + ",".join(bad_type)
    required = verdict.get("required_checks")
    if not isinstance(required, (list, tuple)) or not required:
        return False, "verdict.required_checks 缺失或为空"
    if not all(isinstance(k, str) for k in required):
        return False, "verdict.required_checks 含非字符串项"
    if not set(VERDICT_ALWAYS_REQUIRED).issubset(set(required)):
        return False, "verdict.required_checks 删掉了永远必需的判据"
    absent = [k for k in required if k not in checks]
    if absent:
        return False, "required_checks 声明了 checks 中不存在的判据: " + ",".join(absent)
    # 默认模式下 required 只有 2 项，部分判据为 False 是合法设计，因此这里
    # 只按报告声明的 required 重算内存结论，不要求 5 项全真。
    memory_ok = all(_flag_true(checks[k]) for k in required)
    # R34：主链路 apply_file_verification 把文件级复验叠加进 verdict.pass，
    # 最终结论是「内存判据 ∧ 文件级复验」。字段缺失（旧报告 / fv 跳过）时
    # 退化为仅内存判据。只按内存判据重算，会把诚实产出的不合格报告误报为
    # 「汇总不一致」，掩盖真正的失败环节。
    fv_flag = verdict.get("file_verification_pass")
    expected_pass = (memory_ok and _flag_true(fv_flag)
                     if fv_flag is not None else memory_ok)
    if not _is_bool_flag(verdict.get("pass")):
        return False, "verdict.pass 不是布尔值"
    pass_value = _flag_true(verdict.get("pass"))
    if pass_value != expected_pass:
        return False, ("verdict.pass 与复合重算结论不一致"
                       "（应为 内存判据 ∧ 文件级复验）")
    if not pass_value:
        # 自洽地判定不合格：结论仍须 FAIL（交付物要求 PASS），但原因要指向
        # 真正的失败环节，避免让排障误以为是报告被篡改。
        if fv_flag is not None and not _flag_true(fv_flag):
            detail = (verdict.get("file_verification_failure")
                      or "见 file_verification")
            return False, ("文件级复验未通过，verdict 判定成品不合格"
                           f"（{detail}）")
        return False, "内存判据未通过，verdict 判定成品不合格"
    if verdict.get("evaluated_on") != "final_mesh":
        return False, "verdict 的评价对象不是 final_mesh"
    # 跨层：报告里的内存网格水密结论不能与磁盘 STL 重算结果互相矛盾。
    if bool(checks["watertight"]) != bool(geometry_checks.get("welded_watertight")):
        return False, "verdict.watertight 与磁盘 STL 重算的水密结论矛盾"
    # R42：复验侧拿到报告/清单时，连数值结论也重算；通过时 reason 仍为 None。
    if report is not None or manifest is not None:
        numeric_ok, numeric_reason = verdict_numeric_consistency(
            report, manifest, checks)
        if not numeric_ok:
            return False, numeric_reason
    return True, None


def find_output_sha256(manifest, stl_path, manifest_path=None):
    """在运行清单的 outputs 中按**路径**定位待复验 STL 的哈希记录。

    R31：旧实现直接取 ``outputs[0].sha256``，隐含假设「STL 永远是第一个
    输出」。但 ``convert_3d`` 按 ``--to`` 顺序追加 outputs，而 ``fig.py
    print`` 默认 ``--formats obj stl 3mf ply`` —— 此时 outputs[0] 是 obj，
    独立复验会把哈希完全正确的成品误判为 FAIL。写盘失败的条目在
    ``write_manifest.describe`` 里是 ``None``，畸形条目也不能让复验抛栈。

    返回 ``(sha256, index)``；未找到时返回 ``(None, None)``，调用方必须把
    「未找到」判为失败，不能静默放过。R52：``manifest_path`` 给出清单自身
    位置，相对路径据此解析；缺省时保持按当前工作目录解析的旧行为。
    """
    if not isinstance(manifest, dict):
        return None, None
    outputs = manifest.get("outputs")
    if not isinstance(outputs, (list, tuple)):
        return None, None
    target = os.path.normcase(os.path.abspath(stl_path))
    for index, entry in enumerate(outputs):
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        if _resolve_evidence_path(path, manifest_path) == target:
            return entry.get("sha256"), index
    return None, None


def file_verification_contract(report, manifest, verdict, stl_path,
                               report_path=None, manifest_path=None):
    """R35：用运行清单判定「本次是否做过文件级复验」，并交叉核对两处结论。

    ``write_manifest`` 把 ``file_verification`` 直接写进清单（与报告同源、
    但落在另一个文件）。旧实现只看报告：把 ``report.file_verification``
    整段删掉就会静默退回 R27 之前的 11 项口径，若连 verdict 里的
    ``file_verification_pass`` 一起删，R34 的复合语义校验也被绕过，实证仍
    可 PASS、退出码 0。清单因此是判定「该不该有这个字段」的独立第二证据源。

    返回 ``(required, ok, reason)``：required 表示清单证明本次运行做过文件级
    复验（报告必须带该字段）；ok/reason 是契约结论。两处都没有时视为 R27
    之前的合法旧报告，保持向后兼容；畸形对象一律判失败，不抛栈。
    """
    if not isinstance(manifest, dict):
        return False, False, "manifest 不是对象"
    mf = manifest.get("file_verification")
    rf = report.get("file_verification")
    if mf is not None and not isinstance(mf, dict):
        return False, False, "manifest.file_verification 不是对象"
    if rf is not None and not isinstance(rf, dict):
        return False, False, "report.file_verification 不是对象"
    required = isinstance(mf, dict)
    has_report = isinstance(rf, dict)
    if required and not has_report:
        return True, False, ("运行清单记录了文件级复验，报告却删掉了 "
                             "file_verification")
    if has_report and not required:
        return False, False, "报告声明文件级复验，但运行清单未记录"
    if not required:
        return False, True, None
    # 两处都有：必须指向同一次复验、结论逐项一致。
    target = os.path.normcase(os.path.abspath(stl_path))
    # R52：两处路径分别按承载它们的报告/清单目录解析，支持相对路径交付。
    for label, value, origin in (("report", rf.get("stl"), report_path),
                                 ("manifest", mf.get("stl"), manifest_path)):
        if _resolve_evidence_path(value, origin) != target:
            return True, False, f"{label}.file_verification.stl 与待复验 STL 不符"
    if mf.get("pass") != rf.get("pass"):
        return True, False, "报告与清单的 file_verification.pass 不一致"
    if mf.get("checks") != rf.get("checks"):
        return True, False, "报告与清单的 file_verification.checks 不一致"
    if not isinstance(verdict, dict) or "file_verification_pass" not in verdict:
        return True, False, "verdict 缺少 file_verification_pass"
    return True, True, None


def geometry_checks(stl_path):
    """只依赖 STL 文件本身的几何复验，返回 (checks, metrics)。"""
    # R46：依赖缺失是执行错误（rc=2），不是验收结论。此前裸 traceback +
    # rc=1 会被 CI 当成「验收不通过」，且没有任何可读诊断。
    try:
        import trimesh
    except ImportError as exc:
        raise MissingDependencyError(
            f"几何复验需要 trimesh，当前解释器无法导入: {exc}；"
            "请改用已安装依赖的 Python 3.12/3.14 环境。"
            "缺依赖不是「验收不通过」，也不会降级为「通过」") from exc

    raw = trimesh.load(stl_path, force="mesh", process=False)
    # process=True 按位置焊接顶点；未焊接的 STL 索引拓扑天然不闭合。
    # R53：旧实现把同一个 37MB STL 完整解析两遍（~1.04s），第二次只为拿到
    # 焊接副本。copy()+process() 在 final5 上逐项等价（面数/顶点/水密/
    # 绕向/体积/is_volume/包围盒/euler 全一致），省掉一次全量解析。
    welded = raw.copy()
    welded.process()
    volume_raw = float(welded.volume)
    finite = math.isfinite(volume_raw)
    checks = {
        "welded_watertight": bool(welded.is_watertight),
        "winding_consistent": bool(welded.is_winding_consistent),
        "positive_volume": bool(finite and volume_raw > 0),
        "closed_solid": bool(welded.is_volume and finite),
    }
    metrics = {
        "faces": int(len(raw.faces)),
        "vertices_raw": int(len(raw.vertices)),
        "vertices_welded": int(len(welded.vertices)),
        "volume_signed": round(volume_raw, 4) if finite else None,
        "euler_number": int(welded.euler_number),
        "extents_xyz": [
            round(float(v), 4) if math.isfinite(float(v)) else None
            for v in welded.extents],
    }
    # R28：整体水密 != 单实体。``is_watertight`` 对多个互不相连的闭合体同样为
    # True，悬空碎块（长发断环、体积为 0 的碎片）此前从未进入任何验收口径。
    # 这里只做量化 + 软告警：按面数删碎块会误删有效发丝细节，是否剔除应由
    # 人工结合三视图决定；需要硬拒绝时用 --strict-single-body。
    parts = welded.split(only_watertight=False)
    part_faces = [int(len(q.faces)) for q in parts]
    total_faces = max(sum(part_faces), 1)
    ordered = sorted(part_faces, reverse=True)
    main_faces = ordered[0] if ordered else 0
    rest = ordered[1:]
    # R53：单实体时 split 得到的唯一一块就是 welded 本身，重新算一遍体积
    # 白耗 ~0.32s；直接复用上面已算出的 volume_raw。多实体仍逐块重算。
    if len(parts) == 1:
        part_vol = [abs(volume_raw) if finite else 0.0]
    else:
        part_vol = []
        for q in parts:
            v = float(q.volume)
            part_vol.append(abs(v) if math.isfinite(v) else 0.0)
    denom = max(abs(volume_raw), 1e-9) if finite else 1e-9
    degenerate = int((welded.area_faces < DEGENERATE_AREA_MM2).sum())
    metrics.update({
        "connected_parts": len(parts),
        "main_body_face_ratio": round(main_faces / total_faces, 6),
        "floating_parts": len(parts) - 1,
        "floating_parts_max_faces": max(rest) if rest else 0,
        "floating_volume_ratio": round(
            max(sum(part_vol) - (max(part_vol) if part_vol else 0.0), 0.0) / denom,
            8),
        "degenerate_faces": degenerate,
    })
    warnings = []
    if metrics["floating_parts"] > 0:
        warnings.append(
            f"检测到 {metrics['floating_parts']} 个悬空连通块（最大 "
            f"{metrics['floating_parts_max_faces']} 面，体积占比 "
            f"{metrics['floating_volume_ratio']:.4%}）；切片前请结合三视图确认"
            "是有效细节还是需剔除的碎料")
    if degenerate:
        warnings.append(f"检测到 {degenerate} 个退化面（面积 < 1e-9 mm²）")
    metrics["warnings"] = warnings
    return checks, metrics


def verify(stl_path, report_path=None, manifest_path=None, stl_only=False,
           strict_single_body=False, require_file_verification=False,
           require_source_provenance=False, require_evidence_index=False,
           evidence_index=None):
    """复验交付物，返回结构化结果；文件缺失或损坏时抛异常由调用方处理。

    ``strict_single_body`` 把「只允许一个连通实体」升级为硬检查；默认关闭，
    悬空碎块只记为 ``warnings``，避免把已交付的多实体成品突然判为不合格。
    ``require_file_verification`` 强制要求报告/清单记录 R27 的文件级闭环，
    用于交付验收时拒绝 R27 之前的旧报告口径。

    R36/R41/R43：``stl_only`` 与报告/清单相关的显式要求互斥（含
    ``require_source_provenance`` 与 ``require_evidence_index``），冲突时抛
    ValueError，不再静默丢弃用户要求后给出误导性的 PASS。
    ``require_source_provenance`` 默认关闭：启用时额外按「报告 ↔ 清单 ↔
    磁盘源文件」三重印证输入模型与参考图的 SHA256，并新增一项检查；关闭时
    输出结构与历史交付逐字节一致。
    ``require_evidence_index`` 同为零影响的 opt-in：启用时核对三视图 /
    run.log 与证据基线，新增 ``evidence_index_valid`` 检查项。历史交付
    没有基线文件，故不设为默认硬门禁。
    """
    # R46：与 geometry_checks 同一契约，缺 numpy 也必须是结构化执行错误。
    try:
        import numpy as np
    except ImportError as exc:
        raise MissingDependencyError(
            f"独立复验需要 numpy，当前解释器无法导入: {exc}") from exc

    check_mode_contract(stl_only, report_path, manifest_path,
                        require_file_verification, require_source_provenance,
                        require_evidence_index)
    result = {"stl": os.path.abspath(stl_path), "checks": {}, "metrics": {},
              "warnings": [], "stl_only": bool(stl_only),
              "strict_single_body": bool(strict_single_body),
              "require_file_verification": bool(require_file_verification)}
    if not os.path.isfile(stl_path):
        raise FileNotFoundError(f"STL 不存在或不是文件: {stl_path}")

    checks, metrics = geometry_checks(stl_path)
    if strict_single_body:
        checks["single_body"] = bool(metrics.get("connected_parts") == 1)
    result["checks"].update(checks)
    result["metrics"].update(metrics)
    result["warnings"] = list(metrics.get("warnings") or [])
    if stl_only:
        result["pass"] = all(result["checks"].values())
        return result

    base = os.path.splitext(stl_path)[0]
    report_path = report_path or base + "_fidelity.json"
    manifest_path = manifest_path or base + "_manifest.json"
    for path in (report_path, manifest_path):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"验收文件不存在: {path}")
    # R37：顶层结构先校验，畸形证据文件走结构化拒绝而非裸 AttributeError。
    report = load_json_object(report_path, "fidelity.json")
    manifest = load_json_object(manifest_path, "manifest.json")

    # 畸形报告（字段被换成字符串/数组）不应让独立复验抛 AttributeError。
    final = report.get("final_mesh")
    final = final if isinstance(final, dict) else {}
    # R31：按路径定位 STL 的清单条目，不再假定它排在 outputs 第一位。
    expected_sha, stl_output_idx = find_output_sha256(
        manifest, stl_path, manifest_path)
    # R37：报告里的 extents_xyz 若被换成字符串/嵌套对象，np.asarray 会抛
    # ValueError。那属于「证据内容畸形」，应判该项 FAIL 而非让整个复验崩掉；
    # 同时显式拒绝 NaN/Inf，避免浮点比较把畸形值悄悄算成"一致"。
    try:
        ext = np.asarray(final.get("extents_xyz") or [], dtype=float)
        got_ext = np.asarray(result["metrics"]["extents_xyz"], dtype=float)
        extents_ok = bool(
            ext.shape == (3,) and got_ext.shape == (3,)
            and np.all(np.isfinite(ext)) and np.all(np.isfinite(got_ext))
            and float(np.max(np.abs(ext - got_ext))) <= EXTENT_TOL_MM)
    except (TypeError, ValueError, OverflowError):
        extents_ok = False
    verdict = report.get("verdict")
    verdict = verdict if isinstance(verdict, dict) else {}
    # R33：verdict 的结构/汇总/跨层一致性一次性校验，取代裸 all(values())。
    verdict_ok, verdict_reason = verdict_checks_valid(
        verdict, result["checks"], report, manifest)

    result["checks"].update({
        "file_sha256_matches_manifest": bool(
            isinstance(expected_sha, str) and bool(expected_sha)
            and _sha256(stl_path) == expected_sha),
        "faces_match_report":
            result["metrics"]["faces"] == final.get("faces"),
        "welded_vertices_match_report":
            result["metrics"]["vertices_welded"] == final.get("vertices"),
        "extents_match_report": extents_ok,
        "report_topology_clean": bool(
            final.get("watertight") is True
            and final.get("boundary_edges") == 0
            and final.get("nonmanifold_edges") == 0),
        "verdict_consistent": verdict_ok,
        "schema_version": report.get("schema_version") == SCHEMA_VERSION,
    })
    # R27/R32：主链路导出后写 file_verification；旁路复验必须逐项核对报告里的
    # 文件级结论，并与独立重算的 4 项几何判据交叉比对。
    # R35：契约始终校验并把检查项**始终写入**，不再让「整段删字段」静默退回
    # 11 项旧口径；清单是判定字段是否本该存在的独立第二证据源。
    required, contract_ok, contract_reason = file_verification_contract(
        report, manifest, verdict, stl_path, report_path, manifest_path)
    fv_raw = report.get("file_verification")
    fv = fv_raw if isinstance(fv_raw, dict) else {}
    fv_stl = fv.get("stl")
    # R52：报告里的 file_verification.stl 也可能是相对路径，须按报告目录解析。
    same_file = bool(
        _resolve_evidence_path(fv_stl, report_path) ==
        os.path.normcase(os.path.abspath(stl_path)))
    raw_checks = fv.get("checks")
    fv_checks = raw_checks if isinstance(raw_checks, dict) else {}
    fv_all_pass = bool(fv_checks) and all(
        _flag_true(value) for value in fv_checks.values())
    geometry_agrees = all(
        key in fv_checks
        and bool(fv_checks[key]) == bool(result["checks"].get(key))
        for key in FV_SHARED_GEOMETRY_CHECKS)
    content_ok = bool(
        fv.get("pass") is True
        and verdict.get("file_verification_pass") is True
        and fv_all_pass and geometry_agrees and same_file)
    if not contract_ok:
        consistent, fv_reason = False, contract_reason
    elif require_file_verification and not required:
        consistent = False
        fv_reason = "显式要求文件级复验闭环，但报告/清单未记录"
    elif required:
        consistent = content_ok
        fv_reason = (None if consistent else
                     "汇总 pass 与逐项 checks 或独立几何复验不一致")
    else:
        # 合法旧报告（R27 之前）：两处都无，跳过内容核对但保留检查项。
        consistent, fv_reason = True, None
    result["checks"]["file_verification_consistent"] = consistent
    result["metrics"]["file_verification_checks"] = len(fv_checks)
    result["metrics"]["file_verification_reason"] = fv_reason
    result["metrics"]["file_verification_contract_required"] = required
    result["metrics"]["schema_version"] = report.get("schema_version")
    # R31：记录匹配到的清单条目下标，便于诊断多格式导出与清单顺序问题。
    result["metrics"]["manifest_stl_output_index"] = stl_output_idx
    result["metrics"]["final_mesh_iou"] = final.get("silhouette_iou")
    result["metrics"]["verdict_checks"] = (
        len(verdict["checks"]) if isinstance(verdict.get("checks"), dict) else 0)
    result["metrics"]["verdict_reason"] = verdict_reason
    # R41：仅在显式要求时写入，保证默认 12 项口径与 _verify.json 字节不变。
    if require_source_provenance:
        prov_ok, prov_reason, prov_details = source_provenance_checks(
            report, manifest, manifest_path=manifest_path,
            report_path=report_path)
        result["checks"]["source_provenance_valid"] = bool(prov_ok)
        result["metrics"]["source_provenance_reason"] = prov_reason
        result["metrics"]["source_provenance_sources"] = prov_details
        result["require_source_provenance"] = True
    # R43：仅在显式要求时写入，保证默认 12 项口径与 _verify.json 字节不变。
    if require_evidence_index:
        ev_ok, ev_reason, ev_details = evidence_index_checks(
            stl_path, evidence_index)
        # R44：容器/哈希校验之外，再把三视图像素轮廓与本次 STL 几何绑定。
        # 只有当几何复验已给出合法包围盒时才能做；缺依赖或畸形 STL 一律
        # 结构化 FAIL，绝不静默跳过。
        view_paths = {role: path for role, _, kind, path
                      in _evidence_names(stl_path) if kind == "png"}
        rb_ok, rb_reason, rb_details = render_binding_checks(
            result["metrics"]["extents_xyz"], view_paths)
        # R56：基础统计全部通过后才值得额外解析三角形做逐像素轮廓比对；
        # 基础绑定已失败时保留原诊断，不用昂贵的深度计算淹没首要原因。
        sil_ok, sil_reason, sil_details = True, None, []
        if rb_ok:
            sil_ok, sil_reason, sil_details = stl_silhouette_checks(
                stl_path, view_paths)
        reasons = [r for r in (ev_reason, rb_reason, sil_reason) if r]
        result["checks"]["evidence_index_valid"] = bool(
            ev_ok and rb_ok and sil_ok)
        result["metrics"]["evidence_index_reason"] = (
            "；".join(reasons) if reasons else None)
        result["metrics"]["evidence_index_files"] = len(ev_details)
        result["metrics"]["render_binding"] = rb_details
        result["metrics"]["render_silhouette"] = sil_details
        result["require_evidence_index"] = True
    result["pass"] = (all(result["checks"].values())
                      and len(result["checks"]) >= 11)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="STL 交付物文件级独立复验")
    parser.add_argument("--stl", required=True, help="待复验的 STL 路径")
    parser.add_argument("--report", help="fidelity.json 路径（默认按同名前缀推导）")
    parser.add_argument("--manifest", help="manifest.json 路径（默认按同名前缀推导）")
    parser.add_argument("--stl-only", action="store_true",
                        help="只做几何复验，不要求报告/清单")
    parser.add_argument("--strict-single-body", action="store_true",
                        help="把悬空连通块升级为硬门禁（默认只告警）")
    parser.add_argument("--require-file-verification", action="store_true",
                        help="强制要求报告/清单记录导出后的文件级复验")
    parser.add_argument("--require-source-provenance", action="store_true",
                        help="额外核验输入模型/参考图在报告、清单与磁盘上的 SHA256 一致")
    parser.add_argument("--require-evidence-index", action="store_true",
                        help="核对三视图/运行日志与证据基线逐项一致")
    parser.add_argument("--write-evidence-index", action="store_true",
                        help="依据当前磁盘产物生成证据基线（独立动作，不与复验混用）")
    parser.add_argument("--evidence-index", dest="evidence_index",
                        help="证据基线路径（默认按 STL 同名前缀派生）")
    parser.add_argument("--json", dest="json_path", help="把结构化结果写到该路径")
    args = parser.parse_args(argv)

    # R43：生成基线是独立动作，不允许和任何复验模式混用（避免自写自验）。
    if args.write_evidence_index:
        # R47：冲突集合统一交给 check_mode_contract，CLI 不再另写一份，
        # 避免「库层加了一项、CLI 没跟上」的两层漂移（R36 的教训）。
        try:
            check_mode_contract(
                args.stl_only, args.report, args.manifest,
                args.require_file_verification,
                args.require_source_provenance,
                args.require_evidence_index,
                write_evidence_index=True,
                strict_single_body=args.strict_single_body,
                json_path=args.json_path)
            index = build_evidence_index(args.stl)
            target = args.evidence_index or evidence_index_path(args.stl)
            # R48：先按目标内容护栏拒绝覆写任意既有文件/他人基线，再按
            # 派生路径护栏拒绝本次交付的报告/清单/复验结果。两层职责不同：
            # 前者覆盖自定义命名路径，后者即使目标被删也能拦住。
            guard_index_write_target(target, index["stl"]["sha256"])
            write_json_atomic(target, index,
                              write_index_protected_paths(args.stl),
                              label="--evidence-index")
            print(f"[OK] 证据基线已生成: {target}（{len(index['evidence'])} 项）")
            return 0
        except (OSError, ValueError) as exc:
            print(f"[ERROR] 证据基线未写出: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2

    try:
        result = verify(args.stl, args.report, args.manifest, args.stl_only,
                        args.strict_single_body,
                        args.require_file_verification,
                        args.require_source_provenance,
                        args.require_evidence_index,
                        args.evidence_index)
    # R45：补上资源/数值类残余异常，任何未预期异常都映射为 rc=2 的结构化
    # 执行错误，而不是裸 traceback（与 R37「验收不通过 ≠ 执行错误」同一契约）。
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            OverflowError, MemoryError, MissingDependencyError,
            json.JSONDecodeError) as exc:
        print(f"[ERROR] 复验无法执行: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"[*] 文件级独立复验: {result['stl']}")
    if result["stl_only"]:
        print("[*] 模式: 仅几何复验（未核对 fidelity.json / manifest.json，"
              "不等同于完整交付验收）")
    for name, ok in result["checks"].items():
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
    print(f"[*] 面数={result['metrics']['faces']}  "
          f"焊接顶点={result['metrics']['vertices_welded']}  "
          f"有符号体积={result['metrics']['volume_signed']}  "
          f"尺寸={result['metrics']['extents_xyz']}")
    print(f"[*] 连通块={result['metrics'].get('connected_parts')}  "
          f"悬空块={result['metrics'].get('floating_parts')}  "
          f"退化面={result['metrics'].get('degenerate_faces')}")
    for warning in result["warnings"]:
        print(f"[!] {warning}")
    if not result["stl_only"]:
        print(f"[*] schema={result['metrics']['schema_version']}  "
              f"final_mesh IoU={result['metrics']['final_mesh_iou']}")
    if result.get("require_source_provenance"):
        reason = result["metrics"]["source_provenance_reason"]
        print("[*] 输入溯源: " + ("报告/清单/磁盘三方哈希一致" if reason is None
                                  else f"不一致 -> {reason}"))
    if result.get("require_evidence_index"):
        reason = result["metrics"]["evidence_index_reason"]
        n = result["metrics"]["evidence_index_files"]
        print("[*] 交付证据: " + (f"{n} 项与基线一致" if reason is None
                                else f"不一致 -> {reason}"))
        binding = result["metrics"].get("render_binding") or []
        if binding:
            summary = ", ".join(
                f"{item.get('role')}={item.get('error_pct', '?')}%"
                if item.get("error_pct") is not None
                else f"{item.get('role')}=不可解析" for item in binding)
            print(f"[*] 渲染几何绑定: {summary}")
        silhouettes = result["metrics"].get("render_silhouette") or []
        if silhouettes:
            summary = ", ".join(
                f"{item.get('role')}={item.get('silhouette_iou', '不可解析')}"
                for item in silhouettes)
            print(f"[*] STL 投影轮廓 IoU: {summary}")
    print(f"[{'OK' if result['pass'] else 'FAIL'}] 验收结论: "
          f"{'PASS' if result['pass'] else 'FAIL'}")
    rc = 0 if result["pass"] else 1
    if args.json_path:
        # R38/R43：保护全部派生证据（含日志、三视图与证据基线）以及显式
        # 传入的报告/清单/基线路径。
        protected = (evidence_paths(args.stl)
                     + (args.report, args.manifest, args.evidence_index))
        try:
            write_json_atomic(args.json_path, result, protected)
            print(f"[*] 结构化结果: {args.json_path}")
        except (OSError, ValueError) as exc:
            print(f"[ERROR] 结构化结果未写出: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            # 验收本身 PASS 但证据未落盘时返回 2（执行错误），不冒充 1
            # 「验收不通过」，也不冒充 0「通过且已产出证据」。
            if rc == 0:
                rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
