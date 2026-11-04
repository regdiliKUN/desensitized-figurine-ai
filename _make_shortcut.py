#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 D:\\desktop 创建指向 E:\\AI 的 .lnk 快捷方式（SSD 新位置）"""
import os, sys, glob

desktop = r'D:\desktop'
if not os.path.isdir(desktop):
    for cand in [r'D:\Desktop', os.path.join(os.environ['USERPROFILE'], 'Desktop')]:
        if os.path.isdir(cand):
            desktop = cand
            break
print(f"desktop: {desktop}")

ai_dir = r'E:\AI'

try:
    import win32com.client as wc
except ImportError:
    print("pip install pywin32"); sys.exit(1)

ws = wc.Dispatch('WScript.Shell')

# 1) 文件夹快捷方式
lnk1 = ws.CreateShortcut(os.path.join(desktop, '\u624b\u529eAI\u6d41\u6c34\u7ebf.lnk'))
lnk1.TargetPath = ai_dir
lnk1.WorkingDirectory = ai_dir
lnk1.IconLocation = r'C:\Windows\System32\imageres.dll, 4'
lnk1.Description = '\u4e8c\u6b21\u5143\u624b\u529eAI\u751f\u6210\u6d41\u6c34\u7ebf - E\u76d8SSD'
lnk1.Save()
p1 = os.path.join(desktop, '\u624b\u529eAI\u6d41\u6c34\u7ebf.lnk')
print(f"[OK] folder .lnk ({os.path.getsize(p1)} bytes)")

# 2) 启动器快捷方式
lnk2 = ws.CreateShortcut(os.path.join(desktop, '\u624b\u529eAI\u542f\u52a8\u5668.lnk'))
lnk2.TargetPath = os.path.join(ai_dir, '\u542f\u52a8\u5668.html')
lnk2.WorkingDirectory = ai_dir
lnk2.IconLocation = r'C:\Windows\System32\imageres.dll, 15'
lnk2.Description = '\u50bb\u74dc\u5f0f\u53ef\u89c6\u5316\u542f\u52a8\u5668'
lnk2.Save()
p2 = os.path.join(desktop, '\u624b\u529eAI\u542f\u52a8\u5668.lnk')
print(f"[OK] launcher .lnk ({os.path.getsize(p2)} bytes)")

# 3) 命令行快捷方式（打开终端到 E:\AI）
lnk3 = ws.CreateShortcut(os.path.join(desktop, '\u624b\u529eAI\u547d\u4ee4\u884c.lnk'))
lnk3.TargetPath = r'C:\Windows\System32\cmd.exe'
lnk3.Arguments = r'/k cd /d E:\AI'
lnk3.WorkingDirectory = ai_dir
lnk3.IconLocation = r'C:\Windows\System32\cmd.exe, 0'
lnk3.Description = '\u6253\u5f00\u547d\u4ee4\u884c\u8fdb\u5165 E:\\AI'
lnk3.Save()
p3 = os.path.join(desktop, '\u624b\u529eAI\u547d\u4ee4\u884c.lnk')
print(f"[OK] cmd .lnk ({os.path.getsize(p3)} bytes)")

# 4) ComfyUI 服务器快捷方式（双击启动推理服务）
lnk4 = ws.CreateShortcut(os.path.join(desktop, '\u624b\u529eAI\u670d\u52a1\u5668.lnk'))
lnk4.TargetPath = os.path.join(ai_dir, '\u542f\u52a8ComfyUI.bat')
lnk4.WorkingDirectory = ai_dir
lnk4.IconLocation = r'C:\Windows\System32\shell32.dll, 13'
lnk4.Description = '\u542f\u52a8 ComfyUI \u670d\u52a1 (\u51fa\u56fe+3D\u63a8\u7406)'
lnk4.Save()
p4 = os.path.join(desktop, '\u624b\u529eAI\u670d\u52a1\u5668.lnk')
print(f"[OK] server .lnk ({os.path.getsize(p4)} bytes)")

print(f"\ntarget: {ai_dir}")
print("done!")
