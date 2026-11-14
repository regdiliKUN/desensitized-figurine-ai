#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""创建桌面快捷方式指向 EXE 一键启动器"""

import os
import sys
import stat

# 用系统 Python 3.14（含 pywin32）
try:
    import win32com.client
    import pythoncom
except ImportError:
    print("[!] 缺少 pywin32，无法创建 .lnk")
    sys.exit(1)

exe_path = r"E:\AI\手办AI.exe"
icon_path = r"E:\AI\手办AI启动器.ico"
desktop = os.path.join(os.path.expanduser("~"), "Desktop")
lnk_path = os.path.join(desktop, "手办AI.lnk")

# 如果已存在，先删除（可能只读）
if os.path.exists(lnk_path):
    os.chmod(lnk_path, stat.S_IWRITE)
    os.remove(lnk_path)

shell = win32com.client.Dispatch("WScript.Shell")
shortcut = shell.CreateShortcut(lnk_path)
shortcut.TargetPath = exe_path
shortcut.WorkingDirectory = r"E:\AI"
shortcut.Description = "二次元手办 AI 流水线 一键启动"
shortcut.IconLocation = f"{icon_path},0"
shortcut.WindowStyle = 1  # 正常窗口
shortcut.Save()

print(f"[+] 快捷方式已创建: {lnk_path}")
print(f"    目标: {exe_path}")
print(f"    图标: {icon_path}")
