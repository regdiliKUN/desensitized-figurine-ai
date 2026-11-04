#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为 EXE 启动器生成手办主题图标"""

from PIL import Image, ImageDraw
import os

size = 256
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# 粉紫渐变背景
for y in range(size):
    t = y / size
    r = int(120 + (75 - 120) * t)
    g = int(60 + (40 - 60) * t)
    b = int(200 + (160 - 200) * t)
    draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

# 圆角遮罩
mask = Image.new("L", (size, size), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle([8, 8, size - 8, size - 8], radius=48, fill=255)
img.putalpha(mask)

# 手办剪影
cx = size // 2
# 头
draw.ellipse([cx - 35, 30, cx + 35, 100], fill=(255, 200, 220, 255))
# 身体
draw.rounded_rectangle([cx - 45, 95, cx + 45, 200], radius=20, fill=(255, 200, 220, 255))
# 底座
draw.rounded_rectangle([cx - 60, 195, cx + 60, 225], radius=8, fill=(180, 180, 200, 255))
draw.rounded_rectangle([cx - 70, 220, cx + 70, 235], radius=6, fill=(150, 150, 170, 255))

# 装饰光点
for px, py, pr in [(40, 40, 6), (210, 50, 4), (200, 160, 5), (45, 170, 4)]:
    draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(255, 255, 255, 180))

ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "手办AI启动器.ico")
img.save(ico_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print(f"Icon saved: {ico_path}")
print(f"Size: {os.path.getsize(ico_path)} bytes")
