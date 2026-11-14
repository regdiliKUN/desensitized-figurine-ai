#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修正桌面快捷方式：真实桌面是 D:\Desktop，删除误建的 C 盘快捷方式，重建指向 EXE"""

import os
import stat
import sys

try:
    import win32com.client
except ImportError:
    print("[!] 缺少 pywin32")
    sys.exit(1)

exe_path = r"E:\AI\手办AI.exe"
icon_path = r"E:\AI\手办AI启动器.ico"

# 两个桌面位置
desktops = {
    "D": r"D:\Desktop",
    "C": os.path.join(os.path.expanduser("~"), "Desktop"),  # C:\Users\xukunhang\Desktop
}

shell = win32com.client.Dispatch("WScript.Shell")

# 检查 D 盘旧 lnk 指向
old_d = os.path.join(desktops["D"], "手办AI.lnk")
if os.path.exists(old_d):
    sc = shell.CreateShortcut(old_d)
    print(f"[i] D盘旧 lnk 指向: {sc.TargetPath}")

# 删除 C 盘误建的 lnk（指向 EXE 的那个，但位置错了）
c_lnk = os.path.join(desktops["C"], "手办AI.lnk")
if os.path.exists(c_lnk):
    os.chmod(c_lnk, stat.S_IWRITE)
    os.remove(c_lnk)
    print(f"[+] 已删除误建的 C 盘快捷方式: {c_lnk}")

# 删除旧的 D 盘 lnk（指向 .bat 的），重建指向 EXE
if os.path.exists(old_d):
    os.chmod(old_d, stat.S_IWRITE)
    os.remove(old_d)
    print(f"[+] 已删除旧的 D 盘快捷方式: {old_d}")

# 在 D 盘创建指向 EXE 的新快捷方式
shortcut = shell.CreateShortcut(old_d)
shortcut.TargetPath = exe_path
shortcut.WorkingDirectory = r"E:\AI"
shortcut.Description = "二次元手办 AI 流水线 一键启动"
shortcut.IconLocation = f"{icon_path},0"
shortcut.WindowStyle = 1
shortcut.Save()
print(f"[+] 已在 D 盘桌面创建快捷方式: {old_d}")
print(f"    目标: {exe_path}")
