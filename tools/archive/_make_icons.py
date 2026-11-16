#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为 4 个桌面快捷方式生成「二次元手办生成」主题的自定义 .ico 图标。

图标设计理念：
  - 共同色板：粉紫渐变（二次元）+ 青蓝点缀（科技感）+ 暗色背景
  - 每个图标都有一个核心符号 + 装饰元素，在 32x32 也清晰可辨
  - 256x256 高清绘制，自动生成多尺寸 ICO

输出：E:\AI\icons\*.ico
"""
import os
import math
from PIL import Image, ImageDraw, ImageFilter

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
os.makedirs(OUT_DIR, exist_ok=True)

# 色板
BG_DARK = (15, 17, 23)          # 深色背景
BG_CARD = (26, 29, 39)          # 卡片背景
PINK = (232, 93, 138)           # 二次元粉
PURPLE = (124, 92, 252)         # 紫色
CYAN = (96, 200, 220)           # 青色
GREEN = (74, 222, 128)          # 绿色
ORANGE = (251, 146, 60)         # 橙色
WHITE = (232, 232, 232)         # 白色
DIM = (120, 120, 140)           # 暗灰


def round_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """画圆角矩形"""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_gradient_bg(size=256):
    """画渐变背景"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 圆角方形背景
    margin = 8
    round_rect(draw, [margin, margin, size - margin, size - margin],
               radius=48, fill=BG_DARK)
    # 渐变叠加（从左上粉紫到右下深蓝）
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for i in range(size):
        t = i / size
        r = int(PURPLE[0] * (1 - t) * 0.3 + BG_DARK[0])
        g = int(PURPLE[1] * (1 - t) * 0.2 + BG_DARK[1])
        b = int(PURPLE[2] * (1 - t) * 0.4 + BG_DARK[2])
        od.line([(0, i), (size, i)], fill=(r, g, b, 120))
    # 裁剪 overlay 到圆角
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([margin, margin, size - margin, size - margin], radius=48, fill=255)
    img.paste(overlay, (0, 0), mask)
    return img


def draw_figure_silhouette(draw, cx, cy, scale=1.0, color=PINK):
    """画一个简化的二次元手办人形剪影（头+身体）"""
    s = scale
    # 头部（圆形）
    head_r = int(18 * s)
    head_y = int(cy - 35 * s)
    draw.ellipse([cx - head_r, head_y - head_r,
                  cx + head_r, head_y + head_r], fill=color)
    # 身体（梯形/水滴形）
    body_top = head_y + head_r - int(4 * s)
    body_bottom = int(cy + 45 * s)
    body_w_top = int(16 * s)
    body_w_bot = int(28 * s)
    # 用多边形画身体
    points = [
        (cx - body_w_top, body_top),
        (cx + body_w_top, body_top),
        (cx + body_w_bot, body_bottom),
        (cx - body_w_bot, body_bottom),
    ]
    draw.polygon(points, fill=color)
    # 双马尾装饰（两个小三角从头部两侧伸出）
    if scale > 0.5:
        tw = int(10 * s)
        th = int(22 * s)
        # 左马尾
        draw.polygon([
            (cx - head_r + 2, head_y - int(5 * s)),
            (cx - head_r - tw, head_y + th),
            (cx - head_r + 2, head_y + int(8 * s)),
        ], fill=color)
        # 右马尾
        draw.polygon([
            (cx + head_r - 2, head_y - int(5 * s)),
            (cx + head_r + tw, head_y + th),
            (cx + head_r - 2, head_y + int(8 * s)),
        ], fill=color)


def draw_sparkle(draw, x, y, size=8, color=WHITE):
    """画一个四角星/闪光"""
    s = size
    draw.polygon([
        (x, y - s),
        (x + s // 3, y - s // 3),
        (x + s, y),
        (x + s // 3, y + s // 3),
        (x, y + s),
        (x - s // 3, y + s // 3),
        (x - s, y),
        (x - s // 3, y - s // 3),
    ], fill=color)


# ================================================================
# 图标 1：手办AI流水线（文件夹图标 + 流水线节点）
# ================================================================
def icon_pipeline():
    size = 256
    img = draw_gradient_bg(size)
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    # 文件夹形状（经典 tab folder）
    fw, fh = 140, 100
    fx = cx - fw // 2
    fy = cy - fh // 2 + 10
    # 文件夹主体
    round_rect(draw, [fx, fy + 20, fx + fw, fy + fh],
               radius=8, fill=(124, 92, 252, 200), outline=PURPLE, width=2)
    # 文件夹 tab
    draw.polygon([
        (fx, fy + 20),
        (fx + 35, fy),
        (fx + 60, fy),
        (fx + 60, fy + 20),
    ], fill=(124, 92, 252, 200))
    draw.line([(fx, fy + 20), (fx + 35, fy), (fx + 60, fy), (fx + 60, fy + 20)],
              fill=PURPLE, width=2)

    # 在文件夹上画 3 个流水线节点（出图→3D→打印）
    node_y = fy + 45
    node_r = 12
    nodes = [
        (fx + 30, node_y, PINK),      # 出图
        (fx + 70, node_y, CYAN),      # 3D
        (fx + 110, node_y, GREEN),    # 打印
    ]
    for nx, ny, nc in nodes:
        draw.ellipse([nx - node_r, ny - node_r, nx + node_r, ny + node_r],
                     fill=nc, outline=WHITE, width=1)
    # 连接线
    draw.line([(nodes[0][0] + node_r, node_y), (nodes[1][0] - node_r, node_y)],
              fill=WHITE, width=2)
    draw.line([(nodes[1][0] + node_r, node_y), (nodes[2][0] - node_r, node_y)],
              fill=WHITE, width=2)

    # 顶部小手办剪影
    draw_figure_silhouette(draw, cx, fy - 5, scale=0.5, color=PINK)

    # 闪光装饰
    draw_sparkle(draw, fx + fw - 10, fy + 10, size=6, color=WHITE)
    draw_sparkle(draw, fx + 10, fy + fh - 10, size=5, color=CYAN)

    return img


# ================================================================
# 图标 2：手办AI启动器（播放按钮 + 手办 + UI 窗口）
# ================================================================
def icon_launcher():
    size = 256
    img = draw_gradient_bg(size)
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    # UI 窗口框
    ww, wh = 160, 120
    wx = cx - ww // 2
    wy = cy - wh // 2
    round_rect(draw, [wx, wy, wx + ww, wy + wh],
               radius=12, fill=(26, 29, 39, 220), outline=PURPLE, width=2)
    # 窗口顶栏
    round_rect(draw, [wx, wy, wx + ww, wy + 24],
               radius=12, fill=(124, 92, 252, 100))
    # 三个小圆点（窗口按钮）
    for i, c in enumerate([PINK, ORANGE, GREEN]):
        draw.ellipse([wx + 10 + i * 14, wy + 8, wx + 18 + i * 14, wy + 16], fill=c)

    # 大播放按钮（三角形）
    btn_r = 32
    btn_cx = cx
    btn_cy = wy + wh // 2 + 8
    # 按钮圆形背景
    draw.ellipse([btn_cx - btn_r, btn_cy - btn_r, btn_cx + btn_r, btn_cy + btn_r],
                 fill=PINK, outline=WHITE, width=2)
    # 播放三角
    ts = 16
    draw.polygon([
        (btn_cx - ts // 2 + 4, btn_cy - ts),
        (btn_cx - ts // 2 + 4, btn_cy + ts),
        (btn_cx + ts - 2, btn_cy),
    ], fill=WHITE)

    # 底部小手办
    draw_figure_silhouette(draw, wx + 25, wy + wh - 5, scale=0.35, color=CYAN)
    draw_figure_silhouette(draw, wx + ww - 25, wy + wh - 5, scale=0.35, color=PURPLE)

    # 闪光
    draw_sparkle(draw, btn_cx + btn_r - 4, btn_cy - btn_r + 4, size=7, color=WHITE)

    return img


# ================================================================
# 图标 3：手办AI命令行（终端窗口 + 提示符 + 代码）
# ================================================================
def icon_terminal():
    size = 256
    img = draw_gradient_bg(size)
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    # 终端窗口
    tw, th = 150, 110
    tx = cx - tw // 2
    ty = cy - th // 2
    round_rect(draw, [tx, ty, tx + tw, ty + th],
               radius=10, fill=(10, 11, 15, 230), outline=GREEN, width=2)
    # 顶栏
    round_rect(draw, [tx, ty, tx + tw, ty + 22],
               radius=10, fill=(20, 40, 25, 200))
    draw.ellipse([tx + 8, ty + 7, tx + 16, ty + 15], fill=PINK)
    draw.ellipse([tx + 20, ty + 7, tx + 28, ty + 15], fill=ORANGE)
    draw.ellipse([tx + 32, ty + 7, tx + 40, ty + 15], fill=GREEN)

    # 提示符 >_
    prompt_y = ty + 40
    # ">" 符号
    draw.line([(tx + 15, prompt_y), (tx + 25, prompt_y + 8), (tx + 15, prompt_y + 16)],
              fill=GREEN, width=3)
    # 代码行（几条短横线模拟文字）
    line_x = tx + 35
    for i, (lw, lc) in enumerate([(40, WHITE), (30, CYAN), (50, WHITE), (25, PINK)]):
        ly = prompt_y + i * 16
        draw.line([(line_x, ly + 8), (line_x + lw, ly + 8)], fill=lc, width=2)

    # 底部手办小图标
    draw_figure_silhouette(draw, tx + tw - 20, ty + th - 5, scale=0.3, color=PURPLE)

    return img


# ================================================================
# 图标 4：手办AI服务器（齿轮 + 3D 立方体 + 连接）
# ================================================================
def icon_server():
    size = 256
    img = draw_gradient_bg(size)
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    # 3D 立方体（等轴测）
    cu_size = 40
    cu_cx = cx
    cu_cy = cy - 15
    # 立方体六个面（等轴测投影）
    # 顶面（菱形）
    top = [
        (cu_cx, cu_cy - cu_size),
        (cu_cx + cu_size * 0.866, cu_cy - cu_size * 0.5),
        (cu_cx, cu_cy),
        (cu_cx - cu_size * 0.866, cu_cy - cu_size * 0.5),
    ]
    # 左面
    left = [
        (cu_cx - cu_size * 0.866, cu_cy - cu_size * 0.5),
        (cu_cx, cu_cy),
        (cu_cx, cu_cy + cu_size),
        (cu_cx - cu_size * 0.866, cu_cy + cu_size * 0.5),
    ]
    # 右面
    right = [
        (cu_cx, cu_cy),
        (cu_cx + cu_size * 0.866, cu_cy - cu_size * 0.5),
        (cu_cx + cu_size * 0.866, cu_cy + cu_size * 0.5),
        (cu_cx, cu_cy + cu_size),
    ]
    draw.polygon(top, fill=(124, 92, 252, 220), outline=WHITE, width=2)
    draw.polygon(left, fill=(90, 70, 200, 220), outline=WHITE, width=2)
    draw.polygon(right, fill=(160, 120, 255, 220), outline=WHITE, width=2)

    # 齿轮（在立方体下方）
    gear_cx = cx
    gear_cy = cy + 55
    gear_r = 18
    # 齿轮齿
    teeth = 8
    for i in range(teeth):
        angle = i * 2 * math.pi / teeth
        tx = gear_cx + math.cos(angle) * (gear_r + 6)
        ty = gear_cy + math.sin(angle) * (gear_r + 6)
        draw.ellipse([tx - 4, ty - 4, tx + 4, ty + 4], fill=CYAN)
    # 齿轮主体
    draw.ellipse([gear_cx - gear_r, gear_cy - gear_r,
                  gear_cx + gear_r, gear_cy + gear_r], fill=CYAN, outline=WHITE, width=2)
    # 中心孔
    draw.ellipse([gear_cx - 6, gear_cy - 6, gear_cx + 6, gear_cy + 6], fill=BG_DARK)

    # 连接线（立方体到齿轮）
    draw.line([(cx, cu_cy + cu_size), (gear_cx, gear_cy - gear_r)],
              fill=WHITE, width=2)

    # 顶部状态灯
    draw.ellipse([cx - 4, cu_cy - cu_size - 12, cx + 4, cu_cy - cu_size - 4], fill=GREEN)
    draw_sparkle(draw, cx, cu_cy - cu_size - 14, size=5, color=GREEN)

    return img


# ================================================================
# 生成所有图标
# ================================================================
def save_ico(img, name, sizes=(256, 128, 64, 48, 32, 16)):
    """保存为多尺寸 ICO"""
    path = os.path.join(OUT_DIR, f"{name}.ico")
    # 确保有 alpha 通道
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    # PIL 的 ICO 保存：传入 size 列表会自动生成多尺寸
    img.save(path, format="ICO", sizes=[(s, s) for s in sizes])
    sz = os.path.getsize(path)
    print(f"  [OK] {name}.ico ({sz} bytes) -> {path}")
    return path


def main():
    print(f"[*] 生成手办主题图标到 {OUT_DIR}")
    icons = [
        ("手办AI流水线", icon_pipeline),
        ("手办AI启动器", icon_launcher),
        ("手办AI命令行", icon_terminal),
        ("手办AI服务器", icon_server),
    ]
    for name, func in icons:
        print(f"  绘制 {name} ...")
        img = func()
        # 轻微抗锯齿
        img = img.filter(ImageFilter.SMOOTH)
        save_ico(img, name)
    print(f"\n[✓] 完成！{len(icons)} 个图标已生成到 {OUT_DIR}")


if __name__ == "__main__":
    main()
