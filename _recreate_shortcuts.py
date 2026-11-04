#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删除并重新创建 4 个桌面快捷方式，使用自定义手办主题图标"""
import os, sys, stat

desktop = r'D:\desktop'
ai_dir = r'E:\AI'
icon_dir = os.path.join(ai_dir, 'icons')

if not os.path.isdir(icon_dir):
    print(f"[ERR] icons dir not found: {icon_dir}"); sys.exit(1)

try:
    import win32com.client as wc
except ImportError:
    print("[ERR] pywin32 not installed"); sys.exit(1)

ws = wc.Dispatch('WScript.Shell')

shortcuts = [
    {
        'name': '手办AI流水线.lnk',
        'target': ai_dir,
        'args': '',
        'icon': os.path.join(icon_dir, '手办AI流水线.ico'),
        'desc': '二次元手办AI生成流水线 - E盘SSD',
        'workdir': ai_dir,
    },
    {
        'name': '手办AI启动器.lnk',
        'target': os.path.join(ai_dir, '启动器.html'),
        'args': '',
        'icon': os.path.join(icon_dir, '手办AI启动器.ico'),
        'desc': '傻瓜式可视化启动器',
        'workdir': ai_dir,
    },
    {
        'name': '手办AI命令行.lnk',
        'target': r'C:\Windows\System32\cmd.exe',
        'args': r'/k cd /d E:\AI',
        'icon': os.path.join(icon_dir, '手办AI命令行.ico'),
        'desc': '打开命令行进入 E:\\AI',
        'workdir': ai_dir,
    },
    {
        'name': '手办AI服务器.lnk',
        'target': os.path.join(ai_dir, '启动ComfyUI.bat'),
        'args': '',
        'icon': os.path.join(icon_dir, '手办AI服务器.ico'),
        'desc': '启动 ComfyUI 服务 (出图+3D推理)',
        'workdir': ai_dir,
    },
]

for s in shortcuts:
    p = os.path.join(desktop, s['name'])
    # 先删除旧的
    if os.path.exists(p):
        try:
            # 去掉只读属性
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            os.remove(p)
            print(f"  [DEL] {s['name']}")
        except Exception as e:
            print(f"  [DEL FAIL] {s['name']}: {e}")
            continue

    # 重新创建
    try:
        lnk = ws.CreateShortcut(p)
        lnk.TargetPath = s['target']
        if s['args']:
            lnk.Arguments = s['args']
        lnk.WorkingDirectory = s['workdir']
        lnk.IconLocation = f"{s['icon']},0"
        lnk.Description = s['desc']
        lnk.Save()
        sz = os.path.getsize(p)
        print(f"  [OK] {s['name']} ({sz} bytes)")
    except Exception as e:
        print(f"  [CREATE FAIL] {s['name']}: {e}")

print("\ndone!")
