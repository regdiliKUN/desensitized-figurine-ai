#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
手办AI一键启动器 EXE
- 检测 ComfyUI 是否已运行
- 如未运行则后台启动
- 等待服务就绪
- 打开控制中心 HTML
- 带 GUI 状态窗口（tkinter）
"""

import os
import sys
import time
import threading
import subprocess
import urllib.request
import webbrowser
import tempfile
from pathlib import Path

# ═══════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════
# 打包成 exe 后以 exe 所在目录为项目根，源码运行时以脚本所在目录为根；
# 整个文件夹搬到别的盘也能用。
_ROOT = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
COMFYUI_DIR = os.path.join(_ROOT, "ComfyUI")
COMFYUI_PYTHON = os.path.join(COMFYUI_DIR, "venv", "Scripts", "python.exe")
COMFYUI_MAIN = os.path.join(COMFYUI_DIR, "main.py")
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://127.0.0.1:{COMFYUI_PORT}/system_stats"

LAUNCHER_HTML = os.path.join(_ROOT, "启动器.html")

MAX_WAIT = 120  # 最多等待秒数
POLL_INTERVAL = 3  # 轮询间隔

# ═══════════════════════════════════════════════════════════
#  内嵌图标（程序化生成，避免外部依赖）
# ═══════════════════════════════════════════════════════════
def generate_icon():
    """用 PIL 生成手办主题图标，写入临时文件"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角渐变背景（粉紫渐变模拟）
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

    # 手办剪影（简化人形）
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

    # 保存为临时 ico
    ico_path = os.path.join(tempfile.gettempdir(), "figai_launcher.ico")
    img.save(ico_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return ico_path


# ═══════════════════════════════════════════════════════════
#  核心逻辑
# ═══════════════════════════════════════════════════════════
def check_comfyui():
    """检测 ComfyUI 是否在运行"""
    try:
        req = urllib.request.Request(COMFYUI_URL)
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_comfyui():
    """后台启动 ComfyUI"""
    cmd = [COMFYUI_PYTHON, "main.py", "--port", str(COMFYUI_PORT)]
    creationflags = (
        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    )
    subprocess.Popen(
        cmd,
        cwd=COMFYUI_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def open_launcher():
    """打开控制中心"""
    if os.path.exists(LAUNCHER_HTML):
        webbrowser.open(f"file:///{LAUNCHER_HTML.replace(os.sep, '/')}")
    else:
        webbrowser.open(f"http://127.0.0.1:{COMFYUI_PORT}")


# ═══════════════════════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════════════════════
def run_gui():
    import tkinter as tk
    from tkinter import ttk

    ico_path = generate_icon()

    root = tk.Tk()
    root.title("手办 AI · 一键启动")
    root.geometry("520x380")
    root.resizable(False, False)

    if ico_path and os.path.exists(ico_path):
        try:
            root.iconbitmap(ico_path)
        except Exception:
            pass

    # 深色主题
    root.configure(bg="#1a1a2e")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # 标题
    title = tk.Label(
        root, text="二次元手办 AI 流水线",
        font=("Microsoft YaHei UI", 18, "bold"),
        fg="#e0e0e0", bg="#1a1a2e"
    )
    title.pack(pady=(25, 5))

    subtitle = tk.Label(
        root, text="ComfyUI + Hunyuan3D + Ollama 全本地部署",
        font=("Microsoft YaHei UI", 10),
        fg="#888", bg="#1a1a2e"
    )
    subtitle.pack(pady=(0, 15))

    # 状态标签
    status_var = tk.StringVar(value="正在检测 ComfyUI 状态...")
    status_label = tk.Label(
        root, textvariable=status_var,
        font=("Microsoft YaHei UI", 12),
        fg="#aaaaff", bg="#1a1a2e"
    )
    status_label.pack(pady=10)

    # 进度条
    progress = ttk.Progressbar(root, length=400, mode="determinate")
    progress.pack(pady=10)

    # 日志区
    log_text = tk.Text(
        root, height=8, width=60,
        font=("Consolas", 9),
        bg="#0d0d1a", fg="#00ff88",
        insertbackground="#00ff88",
        relief="flat", padx=8, pady=8,
        state="disabled"
    )
    log_text.pack(pady=(5, 10), padx=20)

    def log(msg):
        log_text.configure(state="normal")
        log_text.insert("end", msg + "\n")
        log_text.see("end")
        log_text.configure(state="disabled")
        root.update_idletasks()

    def set_status(msg, color="#aaaaff"):
        status_var.set(msg)
        status_label.configure(fg=color)

    def worker():
        # 1. 检测
        log("[*] 检测 ComfyUI 服务...")
        if check_comfyui():
            log("[+] ComfyUI 已在运行")
            set_status("ComfyUI 已就绪", "#00ff88")
            progress["value"] = 100
            time.sleep(0.5)
            log("[*] 打开控制中心...")
            open_launcher()
            log("[+] 启动完成！")
            set_status("完成 - 控制中心已打开", "#00ff88")
            time.sleep(2)
            root.after(0, root.destroy)
            return

        # 2. 检查路径
        if not os.path.exists(COMFYUI_PYTHON):
            log(f"[!] 找不到 Python: {COMFYUI_PYTHON}")
            set_status("错误: ComfyUI 未安装", "#ff4444")
            return
        if not os.path.exists(COMFYUI_MAIN):
            log(f"[!] 找不到 main.py: {COMFYUI_MAIN}")
            set_status("错误: ComfyUI 未安装", "#ff4444")
            return

        # 3. 启动
        log(f"[*] 启动 ComfyUI (端口 {COMFYUI_PORT})...")
        log(f"    路径: {COMFYUI_DIR}")
        set_status("正在启动 ComfyUI...", "#ffaa00")
        progress["value"] = 10
        start_comfyui()

        # 4. 等待就绪
        waited = 0
        while waited < MAX_WAIT:
            time.sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL
            pct = 10 + int(80 * waited / MAX_WAIT)
            progress["value"] = pct
            log(f"    等待中... {waited}s")

            if check_comfyui():
                log("[+] ComfyUI 服务已就绪！")
                set_status("ComfyUI 已就绪", "#00ff88")
                progress["value"] = 100
                time.sleep(0.5)
                log("[*] 打开控制中心...")
                open_launcher()
                log("[+] 启动完成！")
                set_status("完成 - 控制中心已打开", "#00ff88")
                time.sleep(2)
                root.after(0, root.destroy)
                return

        # 超时
        log(f"[!] 等待超时（{MAX_WAIT}秒）")
        log("[!] 可能原因: 首次加载模型较慢 / GPU 被占用")
        log(f"[i] 请稍后手动打开: {LAUNCHER_HTML}")
        set_status("超时 - 请稍后手动打开", "#ff6644")
        # 超时也尝试打开 HTML
        open_launcher()

    # 启动后台线程
    t = threading.Thread(target=worker, daemon=True)
    t.start()

    root.mainloop()


# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    run_gui()
