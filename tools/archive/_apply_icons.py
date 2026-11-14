#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把生成的 PNG 图标转换为 .ico 并更新 4 个桌面快捷方式"""
import os
import sys

desktop = r'D:\desktop'
ai_dir = r'E:\AI'
icon_dir = os.path.join(ai_dir, 'icons')
os.makedirs(icon_dir, exist_ok=True)

# 源 PNG 文件名按生成顺序对应：1=流水线 2=启动器 3=命令行 4=服务器
src_files = [
    ('App_icon_design__256x256__flat_2026-11-03T15-08-42.png', 'pipeline'),
    ('App_icon_design__256x256__flat_2026-11-03T15-08-59.png', 'launcher'),
    ('App_icon_design__256x256__flat_2026-11-03T15-09-12.png', 'terminal'),
    ('App_icon_design__256x256__flat_2026-11-03T15-09-27.png', 'server'),
]

# 转换 PNG -> ICO
try:
    from PIL import Image
except ImportError:
    print("pip install Pillow"); sys.exit(1)

ico_paths = {}
for src, name in src_files:
    src_path = os.path.join(icon_dir, src)
    if not os.path.isfile(src_path):
        print(f"[MISS] {src_path}")
        continue
    img = Image.open(src_path)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    # 贴到圆角矩形背景上，保证不透明区域完整
    # 目标：正方形 1024x1024，圆角
    w, h = img.size
    size = max(w, h)
    canvas = Image.new('RGBA', (size, size), (20, 25, 37, 255))

    # 缩小原图到圆角内框 (86%)
    box_size = int(size * 0.86)
    scaled = img.resize((box_size, box_size), Image.Resampling.LANCZOS)
    x = (size - box_size) // 2
    y = (size - box_size) // 2

    # 做圆角蒙版
    mask = Image.new('L', (size, size), 0)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(mask)
    r = size // 6
    draw.rounded_rectangle([0, 0, size-1, size-1], radius=r, fill=255)
    canvas.paste(scaled, (x, y), scaled)
    canvas.putalpha(mask)

    ico_path = os.path.join(icon_dir, f'{name}.ico')
    # Windows 图标常用尺寸
    sizes = [256, 128, 96, 64, 48, 32, 24, 16]
    ico_images = []
    for s in sizes:
        ico_images.append(canvas.resize((s, s), Image.Resampling.LANCZOS))
    ico_images[0].save(ico_path, format='ICO', sizes=[(s, s) for s in sizes])
    ico_paths[name] = ico_path
    print(f"[OK] {ico_path}")

# 更新快捷方式：删除旧文件后重新创建，避免 Save 失败
import win32com.client as wc
ws = wc.Dispatch('WScript.Shell')

shortcut_map = {
    '手办AI流水线.lnk': {
        'target': ai_dir,
        'args': '',
        'workdir': ai_dir,
        'icon': ico_paths.get('pipeline'),
        'desc': '二次元手办AI流水线文件夹 - E:\\AI SSD',
    },
    '手办AI启动器.lnk': {
        'target': os.path.join(ai_dir, '启动器.html'),
        'args': '',
        'workdir': ai_dir,
        'icon': ico_paths.get('launcher'),
        'desc': '傻瓜式可视化启动器',
    },
    '手办AI命令行.lnk': {
        'target': r'C:\Windows\System32\cmd.exe',
        'args': r'/k cd /d E:\AI',
        'workdir': ai_dir,
        'icon': ico_paths.get('terminal'),
        'desc': '打开命令行进入 E:\\AI',
    },
    '手办AI服务器.lnk': {
        'target': os.path.join(ai_dir, '启动ComfyUI.bat'),
        'args': '',
        'workdir': ai_dir,
        'icon': ico_paths.get('server'),
        'desc': '启动 ComfyUI 服务 (出图+3D推理)',
    },
}

for lnk_name, cfg in shortcut_map.items():
    lnk_path = os.path.join(desktop, lnk_name)
    # 删除旧快捷方式
    if os.path.isfile(lnk_path):
        try:
            os.remove(lnk_path)
            print(f"[DEL] old {lnk_name}")
        except Exception as e:
            print(f"[WARN] cannot delete {lnk_name}: {e}")
            continue

    lnk = ws.CreateShortcut(lnk_path)
    lnk.TargetPath = cfg['target']
    if cfg['args']:
        lnk.Arguments = cfg['args']
    lnk.WorkingDirectory = cfg['workdir']
    lnk.Description = cfg['desc']
    if cfg['icon'] and os.path.isfile(cfg['icon']):
        lnk.IconLocation = f"{cfg['icon']},0"
    else:
        # fallback
        lnk.IconLocation = r'C:\Windows\System32\imageres.dll,4'
    lnk.Save()
    print(f"[OK] {lnk_name} -> icon: {os.path.basename(cfg['icon']) if cfg['icon'] else 'fallback'}")

print("\ndone!")
