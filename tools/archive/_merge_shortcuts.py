#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删除桌面 4 个旧快捷方式，只创建 1 个「手办AI」入口"""
import os, sys, stat

desktop = r'D:\desktop'
ai_dir = r'E:\AI'

try:
    import win32com.client as wc
except ImportError:
    print("[ERR] pywin32 not installed"); sys.exit(1)

ws = wc.Dispatch('WScript.Shell')

# 1) 删除 4 个旧快捷方式
old_names = [
    '手办AI流水线.lnk',
    '手办AI启动器.lnk',
    '手办AI命令行.lnk',
    '手办AI服务器.lnk',
]
for name in old_names:
    p = os.path.join(desktop, name)
    if os.path.exists(p):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            os.remove(p)
            print(f"  [DEL] {name}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
    else:
        print(f"  [MISS] {name}")

# 2) 创建唯一入口：手办AI.lnk → 一键启动.bat
bat_path = os.path.join(ai_dir, '一键启动.bat')
icon_path = os.path.join(ai_dir, 'icons', '手办AI启动器.ico')  # 用启动器图标
lnk_path = os.path.join(desktop, '手办AI.lnk')

# 如果图标不存在，用流水线图标
if not os.path.exists(icon_path):
    icon_path = os.path.join(ai_dir, 'icons', '手办AI流水线.ico')

lnk = ws.CreateShortcut(lnk_path)
lnk.TargetPath = bat_path
lnk.WorkingDirectory = ai_dir
lnk.IconLocation = f"{icon_path},0"
lnk.Description = '一键启动手办AI（ComfyUI服务 + 可视化界面）'
lnk.Save()
sz = os.path.getsize(lnk_path)
print(f"\n  [OK] 手办AI.lnk ({sz} bytes) -> {bat_path}")
print(f"  图标: {icon_path}")
print(f"\n  桌面现在只有 1 个图标：手办AI")
print("  双击 → 自动启动 ComfyUI + 打开控制中心界面")
print("\ndone!")
