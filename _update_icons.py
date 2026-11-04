#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新 4 个桌面快捷方式的图标为自定义手办主题 .ico"""
import os, sys

desktop = r'D:\desktop'
ai_dir = r'E:\AI'
icon_dir = os.path.join(ai_dir, 'icons')

if not os.path.isdir(desktop):
    print(f"[ERR] desktop not found: {desktop}"); sys.exit(1)
if not os.path.isdir(icon_dir):
    print(f"[ERR] icons dir not found: {icon_dir}"); sys.exit(1)

try:
    import win32com.client as wc
except ImportError:
    print("[ERR] pywin32 not installed"); sys.exit(1)

ws = wc.Dispatch('WScript.Shell')

mapping = {
    '手办AI流水线.lnk': ('E:\\AI', '手办AI流水线.ico'),
    '手办AI启动器.lnk': (os.path.join(ai_dir, '启动器.html'), '手办AI启动器.ico'),
    '手办AI命令行.lnk': (r'C:\Windows\System32\cmd.exe', '手办AI命令行.ico'),
    '手办AI服务器.lnk': (os.path.join(ai_dir, '启动ComfyUI.bat'), '手办AI服务器.ico'),
}

for name, (target, icon_fn) in mapping.items():
    p = os.path.join(desktop, name)
    icon_path = os.path.join(icon_dir, icon_fn)
    if not os.path.exists(p):
        print(f"[MISS] {name}")
        continue
    if not os.path.exists(icon_path):
        print(f"[ERR] icon not found: {icon_path}")
        continue

    print(f"[*] 更新 {name} 图标 -> {icon_fn}")
    lnk = ws.CreateShortcut(p)
    # 只改图标，不动其他属性（避免某些 target 触发权限错误）
    lnk.IconLocation = f"{icon_path},0"
    lnk.Save()
    print(f"  [OK] {name}")

print("\ndone!")
