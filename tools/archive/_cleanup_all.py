#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删除 I:\\AI 下所有已迁移/不再使用的内容（用户确认全部删除）。

保留：
  - 最终成品/（STL/3MF 打印文件）
  - print_ready/（打印就绪文件）
  - assets/（参考素材）

删除：
  - ComfyUI/（40.4GB，已完整复制到 E:\AI\ComfyUI）
  - InstantMesh/（883MB，不再使用）
  - Models/（空目录）
  - 所有剩余脚本/日志/配置/报告
"""
import os, stat, shutil, sys

ROOT = r"I:\AI"
KEEP_DIRS = {"最终成品", "print_ready", "assets"}

deleted = []
errors = []
total_bytes = 0

def get_dir_size(path):
    total = 0
    for dp, _, fns in os.walk(path):
        for f in fns:
            fp = os.path.join(dp, f)
            try:
                total += os.path.getsize(fp)
            except Exception:
                pass
    return total

# 1) 删除目录
for name in os.listdir(ROOT):
    p = os.path.join(ROOT, name)
    if os.path.isdir(p):
        if name in KEEP_DIRS:
            print(f"  [KEEP] {name}/")
            continue
        sz = get_dir_size(p)
        print(f"  [DEL DIR] {name}/ ({sz/1e9:.2f} GB) ...", end=" ", flush=True)
        try:
            shutil.rmtree(p, ignore_errors=False)
            deleted.append((name + "/", sz))
            total_bytes += sz
            print("OK")
        except Exception as e:
            # 尝试强制去掉只读
            try:
                for dp, _, fns in os.walk(p):
                    for f in fns:
                        fp = os.path.join(dp, f)
                        try:
                            os.chmod(fp, stat.S_IWRITE | stat.S_IREAD)
                        except Exception:
                            pass
                shutil.rmtree(p, ignore_errors=True)
                if os.path.exists(p):
                    errors.append((name, str(e)))
                    print(f"FAIL: {e}")
                else:
                    deleted.append((name + "/", sz))
                    total_bytes += sz
                    print("OK (forced)")
            except Exception as e2:
                errors.append((name, str(e2)))
                print(f"FAIL: {e2}")

# 2) 删除文件
for name in os.listdir(ROOT):
    p = os.path.join(ROOT, name)
    if os.path.isfile(p):
        sz = os.path.getsize(p)
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            os.remove(p)
            deleted.append((name, sz))
            total_bytes += sz
        except Exception as e:
            errors.append((name, str(e)))

# 3) 报告
print()
print("=" * 58)
print(f" I:\\AI 清理完成")
print("=" * 58)
print(f"\n已删除 {len(deleted)} 项，共 {total_bytes/1e9:.2f} GB ({total_bytes/1e6:.1f} MB):")
for fn, sz in sorted(deleted, key=lambda x: -x[1]):
    unit = "GB" if sz > 1e9 else "MB" if sz > 1e6 else "KB"
    val = sz/1e9 if sz > 1e9 else sz/1e6 if sz > 1e6 else sz/1e3
    print(f"  [DEL] {fn:40s} {val:.2f} {unit}")

if errors:
    print(f"\n错误 {len(errors)} 项:")
    for fn, reason in errors:
        print(f"  [ERR] {fn}: {reason}")

# 剩余内容
print(f"\n保留的目录:")
if os.path.isdir(ROOT):
    for name in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, name)
        if os.path.isdir(p):
            sz = get_dir_size(p)
            print(f"  [KEEP] {name}/ ({sz/1e6:.1f} MB)")
        else:
            sz = os.path.getsize(p)
            print(f"  [KEEP] {name} ({sz/1e3:.1f} KB)")
else:
    print(f"  (I:\\AI 目录已不存在)")

print(f"\n[✓] 完成")
