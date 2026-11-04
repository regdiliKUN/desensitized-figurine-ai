#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复：只创建缺失的 手办AI服务器.lnk，并验证已有3个快捷方式"""
import os, sys

desktop = r'D:\desktop'
ai_dir = r'E:\AI'

if not os.path.isdir(desktop):
    print(f"[ERR] desktop not found: {desktop}")
    sys.exit(1)

try:
    import win32com.client as wc
except ImportError:
    print("[ERR] pywin32 not installed, run: pip install pywin32")
    sys.exit(1)

ws = wc.Dispatch('WScript.Shell')

# --- 验证已有3个 ---
checks = [
    ('手办AI流水线.lnk', ai_dir),
    ('手办AI启动器.lnk', os.path.join(ai_dir, '启动器.html')),
    ('手办AI命令行.lnk', r'C:\Windows\System32\cmd.exe'),
]

for name, expected_target in checks:
    p = os.path.join(desktop, name)
    if os.path.isfile(p):
        sz = os.path.getsize(p)
        print(f"[OK] {name} ({sz} bytes)")
    else:
        print(f"[MISS] {name} - will create")
        # 如果缺失则创建
        lnk = ws.CreateShortcut(p)
        if 'cmd.exe' in expected_target:
            lnk.TargetPath = expected_target
            lnk.Arguments = r'/k cd /d E:\AI'
            lnk.WorkingDirectory = ai_dir
            lnk.IconLocation = r'C:\Windows\System32\cmd.exe, 0'
        elif name == '手办AI流水线.lnk':
            lnk.TargetPath = ai_dir
            lnk.WorkingDirectory = ai_dir
            lnk.IconLocation = r'C:\Windows\System32\imageres.dll, 4'
        elif name == '手办AI启动器.lnk':
            lnk.TargetPath = expected_target
            lnk.WorkingDirectory = ai_dir
            lnk.IconLocation = r'C:\Windows\System32\imageres.dll, 15'
        lnk.Description = 'E:\\AI SSD'
        lnk.Save()
        print(f"  -> created ({os.path.getsize(p)} bytes)")

# --- 创建第4个：服务器 ---
server_lnk = os.path.join(desktop, '手办AI服务器.lnk')
bat_path = os.path.join(ai_dir, '启动ComfyUI.bat')

if os.path.isfile(server_lnk):
    print(f"[OK] 手办AI服务器.lnk already exists ({os.path.getsize(server_lnk)} bytes)")
else:
    print(f"[CREATE] 手办AI服务器.lnk -> {bat_path}")
    lnk4 = ws.CreateShortcut(server_lnk)
    lnk4.TargetPath = bat_path
    lnk4.WorkingDirectory = ai_dir
    lnk4.IconLocation = r'C:\Windows\System32\shell32.dll, 13'
    lnk4.Description = '启动 ComfyUI 服务 (出图+3D推理) - E:\\AI SSD'
    lnk4.Save()
    sz = os.path.getsize(server_lnk)
    print(f"  -> created ({sz} bytes)")

# --- 最终验证 ---
print("\n=== 最终桌面快捷方式 ===")
for name in ['手办AI流水线.lnk', '手办AI启动器.lnk', '手办AI命令行.lnk', '手办AI服务器.lnk']:
    p = os.path.join(desktop, name)
    if os.path.isfile(p):
        print(f"  [OK] {name} ({os.path.getsize(p)} bytes)")
    else:
        print(f"  [FAIL] {name}")

print("\ndone!")
