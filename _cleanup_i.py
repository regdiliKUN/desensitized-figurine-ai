#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理 I:\AI 下的实验中间产物和不再使用的旧脚本。

保留：
  - ComfyUI/（用户要求保留作为备份）
  - 最终成品/、print_ready/、assets/
  - InstantMesh/（暂保留）

删除：
  - 所有 _*.py / _*.log / _*.txt / _*.json（实验产物）
  - test_*.py（旧测试脚本，已被 fig.py 替代）
  - pdl*.py, hq_3d.py, render_hq.py, make_print_ready.py（旧脚本）
  - pipeline_figure.py（已被 fig.py 替代）
  - 日志文件、旧启动脚本、旧配置
"""
import os
import stat

ROOT = r'I:\AI'

# 要删除的文件名模式（精确匹配）
DELETE_FILES = [
    # 实验脚本
    '_compare_all.py', '_compare_hq.py', '_compare_scan.py',
    '_diag_blob.py', '_diag_blob2.py', '_diag_blob3.py',
    '_diag_precision.py', '_diag_precision2.py',
    '_diag_source.py', '_diag_thr.py',
    '_eval_mesh.py',
    '_exp_backdrop.py', '_exp_commercial.py', '_exp_final.py',
    '_exp_flat.py', '_exp_flat2.py', '_exp_smooth.py', '_exp_watertight.py',
    '_scan_params.py', '_scan2.py',
    '_test_blob.py', '_test_full.py',
    '_make_shortcut.py',
    # 实验日志/数据
    '_auto_e2e.log', '_e2e_hq.log', '_e2e_v2.log', '_e2e_v3.log',
    '_e2e_v4.log', '_e2e_v5.log', '_e2e_v6.log', '_final_e2e.log',
    '_exp_results.txt', '_objinfo.json', '_ollama_dolphin.log',
    '_r2_pony.txt', '_r2_pony2.txt', '_r2_vae.txt',
    # 旧测试脚本
    'test_3d_enhanced.py', 'test_comfyui.py', 'test_comfyui_flux.py',
    'test_hunyuan3d.py',
    # 旧脚本（已被 fig.py 替代）
    'pdl.py', 'pdl2.py', 'hq_3d.py', 'render_hq.py',
    'make_print_ready.py', 'pipeline_figure.py',
    # 日志
    'comfyui_server.log', 'dolphin_pull.log',
    # 旧启动脚本
    'download_models.sh', 'launch_comfyui.bat',
    '启动_手办流水线.bat', '创建桌面快捷方式.bat',
    # 旧配置
    'hy3d_blueprint.json', 'hy3d_bp.json', 'hy3d_head.txt',
    'workflow_pony_api.json',
    # __pycache__
    # （目录单独处理）
]

deleted = []
skipped = []
total_bytes = 0

for fn in DELETE_FILES:
    p = os.path.join(ROOT, fn)
    if os.path.exists(p):
        try:
            sz = os.path.getsize(p)
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            os.remove(p)
            deleted.append((fn, sz))
            total_bytes += sz
        except Exception as e:
            skipped.append((fn, str(e)))
    else:
        skipped.append((fn, 'not found'))

# 删除 __pycache__ 目录
cache_dir = os.path.join(ROOT, '__pycache__')
if os.path.isdir(cache_dir):
    import shutil
    try:
        cache_size = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _, fns in os.walk(cache_dir)
            for f in fns if os.path.exists(os.path.join(dp, f))
        )
        shutil.rmtree(cache_dir)
        deleted.append(('__pycache__/', cache_size))
        total_bytes += cache_size
    except Exception as e:
        skipped.append(('__pycache__/', str(e)))

# 输出报告
print("=" * 58)
print(f" 清理 I:\\AI 实验产物")
print("=" * 58)
print(f"\n已删除 {len(deleted)} 项，共 {total_bytes / 1024:.1f} KB:")
for fn, sz in sorted(deleted):
    print(f"  [DEL] {fn:40s} {sz/1024:.1f} KB")

if skipped:
    print(f"\n跳过 {len(skipped)} 项:")
    for fn, reason in sorted(skipped):
        print(f"  [SKIP] {fn:40s} {reason}")

print(f"\n保留的目录:")
for d in ['ComfyUI', 'InstantMesh', 'Models', 'print_ready', 'assets', '最终成品']:
    p = os.path.join(ROOT, d)
    if os.path.exists(p):
        print(f"  [KEEP] {d}/")

print(f"\n保留的文件:")
import glob
remaining = [f for f in os.listdir(ROOT)
             if os.path.isfile(os.path.join(ROOT, f))]
for f in sorted(remaining):
    sz = os.path.getsize(os.path.join(ROOT, f))
    print(f"  [KEEP] {f:40s} {sz/1024:.1f} KB")

print(f"\n[✓] 完成")
