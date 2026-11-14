# -*- coding: utf-8 -*-
"""全项目共用的路径配置（fig.py / control_server.py 共同引用，避免各写一份硬编码）。

可用环境变量覆盖：
  FIG_FINAL_DIR   最终成品目录（默认 I:\\AI\\最终成品；I 盘不存在时退回 <项目>\\print_ready）
  FIG_TRIMESH_PY  带 trimesh 的 Python 解释器（默认 ~/.venvs/cadquery 里的 python）
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(ROOT, ".fig_cache")


def final_dir():
    env = os.environ.get("FIG_FINAL_DIR", "").strip()
    if env:
        return env
    preferred = r"I:\AI\最终成品"
    # 只看盘符是否存在：I 盘没插/换了电脑时不至于每次导出都报错。
    drive = os.path.splitdrive(preferred)[0]
    if os.name != "nt" or (drive and os.path.isdir(drive + os.sep)):
        return preferred
    return os.path.join(ROOT, "print_ready")


FINAL_DIR = final_dir()


def trimesh_python_candidates():
    env = os.environ.get("FIG_TRIMESH_PY", "").strip()
    cands = [env] if env else []
    cands += [
        os.path.join(os.path.expanduser("~"), ".venvs", "cadquery", "Scripts", "python.exe"),
        os.path.join(ROOT, "venv_trimesh", "Scripts", "python.exe"),
    ]
    return [c for c in cands if c]


def _cache_path():
    return os.path.join(_CACHE_DIR, "trimesh_python.json")


def find_python_with_trimesh():
    """找一个能 import trimesh 的解释器。

    旧实现每次启动 fig.py 都要另起一个 Python 去 import trimesh（Windows 上 1~3 秒），
    控制中心每个任务都会启动 fig.py，所以把结果按解释器文件的修改时间缓存起来。
    """
    cache = {}
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    for c in trimesh_python_candidates():
        if not os.path.isfile(c):
            continue
        try:
            mtime = os.path.getmtime(c)
        except OSError:
            continue
        hit = cache.get(c)
        if isinstance(hit, dict) and hit.get("mtime") == mtime and hit.get("ok"):
            return c
        try:
            r = subprocess.run([c, "-c", "import trimesh"], capture_output=True, timeout=30)
            ok = r.returncode == 0
        except Exception:  # noqa: BLE001
            ok = False
        cache[c] = {"mtime": mtime, "ok": ok}
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            tmp = _cache_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            os.replace(tmp, _cache_path())
        except OSError:
            pass
        if ok:
            return c
    # 退而求其次：用当前解释器（可能已装 trimesh）
    return sys.executable
