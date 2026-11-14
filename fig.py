#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fig.py —— 二次元手办本地流水线 统一入口

把出图 / 图生3D / 格式转换 / 环境自检 / 去敏感化 收拢成一条命令，
不用再记 pipeline_figure.py、convert_3d.py 的一堆参数。

子命令:
    auto   "中文描述"                全自动：大脑写提示词 -> 出图 -> 图生3D -> 打印格式
    prompt "中文描述"                仅让本地大脑把中文转成英文 tags 提示词
    img    "英文提示词"              仅出图（Pony / Flux）
    i2i    "图片" "英文提示词"        图生图：以参考图+提示词重绘（img2img）
    model  "图片路径"                仅图生 3D -> .glb
    print  "模型路径"                转 3D 打印格式（STL/3MF/OBJ/PLY，可选水密化）
    all    "英文提示词"              出图 -> 图生3D -> 打印格式
    desensitize "图片路径"           ★ 图像去敏感化（过 Meshy/建模AI审核）
    edit_image "图片" "修改要求"     ★ 修改已有图片（涂抹区域局部重绘 / 整图重生成）
    restore "模型路径"               ★ 去敏化3D模型还原成敏感样子
    doctor                           环境自检（ComfyUI / 模型 / 脚本 / 依赖）
    serve                            启动 ComfyUI

示例:
    python fig.py auto "银发红瞳双马尾少女，水手服，全身立绘"
    python fig.py all "1girl, silver hair, red eyes, full body, white background" --model pony
    python fig.py img  "1girl, red eyes, swimming" --model pony --width 832 --height 1216
    python fig.py i2i  "参考图.png" "1girl, red eyes, swimsuit, beach" --strength 0.7
    python fig.py model "I:/AI/ComfyUI/output/pipeline_img_00003_.png"
    python fig.py print "I:/AI/print_ready/figure.glb" --solidify --scale 140
    python fig.py desensitize "敏感图.png" --strength auto
    python fig.py restore "meshy_output.glb" --original "敏感图.png"
"""
import argparse
import atexit
import re
import json
import os
import random
import subprocess
import shutil
import sys
import time
import urllib.request
import urllib.error
import uuid
import tempfile

HOST = "http://127.0.0.1:8188"
# 只清理「本进程自己拉起」的 ComfyUI，避免误杀用户手动开的服务。
_OWNED_COMFY_PROC = None
_CLEANUP_DONE = False


def _comfyui_queue_idle():
    """返回 True 表示 ComfyUI 没有正在执行/排队的任务。"""
    try:
        with urllib.request.urlopen(HOST + "/queue", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        return not data.get("queue_running") and not data.get("queue_pending")
    except Exception:  # noqa: BLE001
        return False


def _release_comfyui_memory():
    """让仍在运行的 ComfyUI 卸载模型并释放显存；不终止用户手动开启的服务。"""
    try:
        req = urllib.request.Request(
            HOST + "/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        print("    ✓ 已请求 ComfyUI 卸载模型并释放显存", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    ! 显存释放请求失败（{type(exc).__name__}: {exc}）", flush=True)
        return False


def _stop_owned_comfyui():
    """退出时终止本进程启动的 ComfyUI（含子进程），释放其占用的显存。

    为什么需要：``fig.py`` 遇到服务未启动会自动 Popen 一个 ComfyUI，但旧实现
    退出时不保留句柄，进程会永久残留并占住 ~20GB 显存。这里用 Popen 句柄精确
    终止，不按进程名乱杀；用户本来就开着的 ComfyUI 不会被误伤。
    """
    global _OWNED_COMFY_PROC
    proc, _OWNED_COMFY_PROC = _OWNED_COMFY_PROC, None
    if proc is None or proc.poll() is not None:
        return
    print("[*] 退出清理：停止本次启动的 ComfyUI（释放显存）...", flush=True)
    try:
        if os.name == "nt":
            # /T 连同 ComfyUI 可能拉起的子进程一起结束，避免残留占显存。
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=12)
        else:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("    ✓ ComfyUI 已停止", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    ! 停止 ComfyUI 失败：{exc}", flush=True)


def _cleanup_comfyui_on_exit():
    """统一的退出清理：自己启动的服务直接停止；外部服务只在空闲时卸载模型。"""
    global _CLEANUP_DONE
    if _CLEANUP_DONE:
        return
    _CLEANUP_DONE = True
    if _OWNED_COMFY_PROC is not None:
        _stop_owned_comfyui()
        return
    # 外部服务可能被启动器/用户显式保留；退出时只释放显存，不杀进程。
    try:
        urllib.request.urlopen(HOST + "/system_stats", timeout=2).close()
    except (urllib.error.URLError, OSError):
        return
    if not _comfyui_queue_idle():
        print("[*] 退出清理：ComfyUI 仍有任务在跑，跳过 /free，避免打断其他任务", flush=True)
        return
    print("[*] 退出清理：请求外部 ComfyUI 卸载模型（保留服务）...", flush=True)
    _release_comfyui_memory()


atexit.register(_cleanup_comfyui_on_exit)

# ★ 程序代码 + ComfyUI + 模型权重在 SSD (E:\AI) 加速推理
#   输出文件（出图/3D模型）也在 SSD（ComfyUI/output 默认就在 ComfyUI 下）
#   最终成品（STL/3MF）可转存到 HDD (I:\AI\最终成品) 不影响速度
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ComfyUI", "output")  # 动态跟随脚本位置
# 最终成品目录（HDD，不影响运行速度）
from paths_config import FINAL_DIR, find_python_with_trimesh as _find_py_with_trimesh

# ★ 3D 后处理需要 trimesh，而 trimesh 装在 CadQuery venv 里（ComfyUI venv 没有）。
#   自动探测可用解释器（结果带缓存，见 paths_config.py）。
PY = _find_py_with_trimesh()

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# cmd_img 选中的最佳出图路径（供 cmd_all 取用）
_LAST_PICKED = None
_LAST_GLB = None
_LAST_ENGINE_USED = None   # 上一次 3D 用的是 hunyuan 还是 meshy
# ★ 本次图生 3D **实际上传的那张图**：必须与 GLB 一起落盘，
#   否则 STL 阶段拿不到参考图，无法做任何几何保真校验（旧链路的根本断点）。
_LAST_REFERENCE_3D = None

# ★ print 子命令与 convert_3d.py 共享的默认参数。fig.py 是用户入口，
#   cmd_print 必须把这些值**显式**传给下游，不能依赖下游默认值 —— 否则
#   任一侧调整默认都会静默漂移（历史上 --smooth 10→0 就出现过这种不一致）。
PRINT_DEFAULTS = {
    # 高精度重建后仍用 0.25mm 水密化会抹掉刚补出的发束/衣褶；0.15mm 已实测
    # 能保住这些结构并通过单实体/水密验收，代价是文件更大、修复更慢。
    "smooth": 0, "voxel_mm": 0.15, "min_iou": 0.55,
    "repair_max_iou_drop": 0.02, "base": 0.03, "model_height": 0.0,
}

# ★ 导出侧的三项质量门禁（convert_3d.py 提供）。它们不是数值参数，故单独成表；
#   键名与 control_server.PRINT_FLAG_ARGS 一致，由回归测试防止两端漂移。
#   默认全部关闭以保持历史行为；启用后 cmd_print 必须显式透传，不能靠下游默认值。
PRINT_FLAG_DEFAULTS = {
    "strict_watertight": False,   # R18：非水密拒绝导出
    "drop_floating_parts": False, # R29：导出前剔除悬空碎块
    "strict_single_body": False,  # R29：落地 STL 必须单连通实体
}
PRINT_FLAG_ARGS = {
    "strict_watertight": "--strict-watertight",
    "drop_floating_parts": "--drop-floating-parts",
    "strict_single_body": "--strict-single-body",
}

DEFAULT_NEG = (
    "low quality, worst quality, blurry, deformed, extra limbs, bad hands, "
    "watermark, signature, "
    # 文字：Pony 常在背景画日文/英文标语，会被重建成凸起的文字块
    "text, letters, japanese text, kanji, hiragana, katakana, typography, "
    "caption, subtitle, logo, sign, banner, lettering, "
    # 背景/道具干扰项：Hunyuan3D 会把背景里的大件物体一起重建成几何体
    "mecha, robot, android, machine, machinery, vehicle, weapon, gun, sword, "
    "shield, armor, mechanical parts, giant object, background object, scenery, "
    "complex background, cluttered background, indoor, landscape, "
    "multiple characters, crowd, extra person, "
    # 影棚背景板：Pony 常在角色身后画一块灰色无缝背景纸，会被重建成一整面墙
    "backdrop, seamless backdrop, studio backdrop, background paper, "
    "gradient background, vignette, grey background, gray background, "
    "drapery, curtain, scenery background, shadow on wall, "
    "dark background, hard shadow, drop shadow, reflection, pedestal, platform, "
    # ★ 3D 致命项：背景色块和图案
    #   诊断实测：分离后的图有 15.6% 高饱和红色，其中 3.8% 在边缘——
    #   Pony 在白底上也会画红色/彩色圆形色块当装饰，Hunyuan3D 会把它们重建成背后的巨物
    "background circle, background pattern, colored background, red circle, "
    "geometric pattern, polka dots, sunburst, radial pattern, halation, "
    # ★ cel shading 伪影：平涂阴影被 Hunyuan3D 当成几何深度，产生蜂窝纹
    "cel shading, gradient shading, pixel shading, mesh pattern, honeycomb pattern, "
    "texture details, surface texture"
)
OLLAMA = "http://127.0.0.1:11434"
DEFAULT_BRAIN = "dolphin-mixtral"

# ----------------------------------------------------------------- 中文→英文 词典
# 确定性翻译：命中的词直接换成标准 danbooru 标签，LLM 只负责润色补全。
# 避免小模型把"水手服"翻成 swimsuit、把"银发"翻成 yellow hair，或复读术语表。
ZH_EN = {
    # 发色
    "银发": "silver hair", "银色头发": "silver hair", "银白色头发": "silver hair",
    "白发": "white hair", "白色头发": "white hair",
    "金发": "blonde hair", "金色头发": "blonde hair", "亚麻色头发": "light brown hair",
    "黑发": "black hair", "黑色头发": "black hair",
    "棕发": "brown hair", "棕色头发": "brown hair",
    "蓝发": "blue hair", "蓝色头发": "blue hair",
    "粉发": "pink hair", "粉色头发": "pink hair",
    "紫发": "purple hair", "紫色头发": "purple hair",
    "绿发": "green hair", "绿色头发": "green hair",
    "橙发": "orange hair", "橙色头发": "orange hair",
    "渐变发": "gradient hair", "渐变色头发": "gradient hair",
    # 发型
    "双马尾": "twintails", "侧马尾": "side ponytail", "高马尾": "ponytail",
    "低马尾": "low ponytail", "呆毛": "ahoge", "刘海": "bangs",
    "姬发式": "hime cut", "卷发": "curly hair", "直发": "straight hair",
    "波浪卷发": "wavy hair", "麻花辫": "braid", "辫子": "braid",
    "长发": "long hair", "短发": "short hair", "中长发": "medium hair",
    "碎发": "blunt bangs", "大波浪": "big wavy hair",
    # 瞳色 / 面部
    "红瞳": "red eyes", "红眼": "red eyes", "蓝色瞳": "blue eyes", "蓝瞳": "blue eyes",
    "金瞳": "amber eyes", "琥珀瞳": "amber eyes", "绿瞳": "green eyes",
    "紫瞳": "purple eyes", "异色瞳": "heterochromia", "竖瞳": "slit pupils",
    "眼罩": "eyepatch", "眼镜": "glasses", "泪眼": "teary eyes",
    "猫眼": "cat eyes", "狐狸眼": "fox eyes", "睡眼": "half-closed eyes",
    # 服装
    "水手服": "sailor uniform", "学生制服": "sailor uniform", "校服": "school uniform",
    "制服": "uniform", "旗袍": "cheongsam", "汉服": "hanfu", "和服": "kimono",
    "连帽衫": "hoodie", "卫衣": "sweatshirt", "T恤": "t-shirt", "衬衫": "shirt",
    "百褶裙": "pleated skirt", "短裙": "short skirt", "长裙": "long skirt",
    "连衣裙": "one-piece dress", "短上衣": "crop top", "吊带": "camisole",
    "运动服": "tracksuit", "体操服": "gym uniform", "泳装": "swimwear", "泳衣": "swimwear",
    "睡衣": "pajamas", "女仆装": "maid outfit", "巫女服": "miko outfit",
    "兔女郎": "bunny girl", "皮革夹克": "leather jacket", "风衣": "trench coat",
    "大衣": "coat", "斗篷": "cloak", "盔甲": "armor", "斗篷式": "cape",
    "婚纱": "wedding dress", "女仆头饰": "maid headband", "发带": "hair ribbon",
    "蝴蝶结": "bow", "花朵发饰": "flower hair ornament", "王冠": "crown",
    "丝袜": "stockings", "过膝袜": "over-knee socks", "长袜": "thighhighs",
    "短袜": "ankle socks", "连裤袜": "pantyhose", "手套": "gloves",
    "耳环": "earrings", "项链": "necklace", "围巾": "scarf",
    # 体型
    "巨乳": "large breasts", "丰满": "curvy figure", "细腰": "slender waist",
    "大长腿": "long legs", "修长": "slender", "娇小": "petite", "高挑": "tall",
    # 鞋子
    "高跟": "high heels", "靴子": "boots", "长靴": "long boots", "凉鞋": "sandals",
    # 动作 / 视角
    "全身": "full body", "全身立绘": "full body", "半身": "upper body",
    "半身像": "bust shot", "正面": "front view", "侧面": "side view",
    "背面": "back view", "站立": "standing", "站姿": "standing", "坐姿": "sitting",
    "跪姿": "kneeling", "趴着": "lying on stomach", "跳跃": "jumping",
    "奔跑": "running", "挥手": "waving hand", "比心": "heart hands",
    "叉腰": "hand on hip", "剪刀手": "peace sign", "侧身": "contrapposto",
    "持剑": "holding sword", "拿剑": "holding sword", "持枪": "holding gun",
    "魔杖": "magic wand", "雨伞": "umbrella", "书": "book", "相机": "camera",
    # 场景 / 画质
    "纯白背景": "white background", "白底": "white background", "白色背景": "white background",
    "简单背景": "simple background", "透明背景": "transparent background",
    "室内": "indoors", "室外": "outdoors", "夜景": "night, night sky",
    "阳光": "sunlight", "工作室灯光": "studio lighting", "最高画质": "masterpiece",
    "最佳画质": "best quality", "精细细节": "highly detailed", "水彩": "watercolor",
    "写实": "realistic", "二次元": "anime", "动漫": "anime", "手办": "figure",
}


def pre_translate(desc):
    """词典优先的中文→英文预翻译（长词优先，避免子串误命中）

    返回 (英文串, 命中词列表[(zh, en), ...])
    """
    hits = []
    text = desc

    # 先处理「颜色+长度+头发」的合并写法：黑长发 -> black hair, long hair
    color_map = {"银": "silver", "白": "white", "金": "blonde", "黑": "black",
                 "棕": "brown", "蓝": "blue", "粉": "pink", "紫": "purple",
                 "绿": "green", "橙": "orange", "红": "red"}
    len_map = {"长": "long", "短": "short", "中长": "medium", "超长": "very long"}

    def _hair_repl(m):
        c, l = m.group("color"), m.group("length")
        en = f"{color_map[c]} hair"
        if l:
            en += f", {len_map[l]} hair"
        hits.append((m.group(0), en))
        return en

    text = re.sub(
        r"(?P<color>银|白|金|黑|棕|蓝|粉|紫|绿|橙|红)(?:色)?(?P<length>中长|超长|长|短)?(?:头)?发",
        _hair_repl, text)

    for zh in sorted(ZH_EN, key=len, reverse=True):
        if zh in text:
            hits.append((zh, ZH_EN[zh]))
            text = text.replace(zh, ZH_EN[zh])
    return text, hits


LENGTH_WORDS = {"long", "short", "medium", "very", "super", "big", "tiny"}

# 提示词固定头尾：主体标识 + 画质/3D 友好项
# ★ 3D 友好提示词（诊断确认）：
#   - "flat shading" 防止 cel shading 平涂阴影被 Hunyuan3D 当成几何深度（蜂窝纹根因）
#   - "clean silhouette" 强调轮廓清晰，减少深度歧义
#   - "no shadow details" 减少平涂阴影区块
#   - "no background pattern, no background circle" 防止 Pony 在背景画红圆盘（实测 15.6% 红色残留）
STD_HEAD = ["1girl", "solo", "anime character"]
STD_TAIL = ["full body", "standing", "front view", "white background", "simple background",
            "isolated character", "character only", "no background props",
            "flat shading", "clean silhouette", "minimal shading", "no shadow details",
            "correct proportions", "masterpiece", "best quality", "highly detailed"]


def _norm(t):
    return t.lower().replace(" ", "").replace("-", "")


def _collides(llm_tag, dict_tags):
    """判断 LLM 生成的标签是否与词典命中项重复（含「black long hair」这类合并写法）"""
    n = _norm(llm_tag)
    for d in dict_tags:
        if n == _norm(d):
            return True
    if llm_tag.endswith(" hair"):
        words = {w for w in llm_tag.split()[:-1] if w not in LENGTH_WORDS}
        for d in dict_tags:
            if d.endswith(" hair"):
                dw = {w for w in d.split()[:-1]}
                if words and words == dw:
                    return True
    return False



# ----------------------------------------------------------------- 文本大脑
def brain_prompt(desc, model=DEFAULT_BRAIN, system=None, quiet=False):
    """中文描述 → 英文 tags 提示词。

    两段式：
      1. 本地词典 pre_translate 做**确定性**翻译（银发→silver hair、水手服→sailor uniform）
      2. 本地 LLM 只做润色/补全/去重，不允许重新翻译已有词

    LLM 不可用时自动降级为「纯词典翻译」，保证出图仍能用英文 tags。
    """
    translated, hits = pre_translate(desc)
    if hits and not quiet:
        print(f"    词典命中 {len(hits)} 项: " +
              ", ".join(f"{z}→{e}" for z, e in hits[:8]) +
              (" ..." if len(hits) > 8 else ""))
    dict_tags = []
    for _, en in hits:
        for t in en.split(","):
            t = " ".join(t.split()).strip(" .")
            if t and _norm(t) not in {_norm(x) for x in dict_tags}:
                dict_tags.append(t)

    if system is None:
        system = (
            "You convert an anime figure description into a comma-separated list of "
            "English danbooru-style tags for Stable Diffusion XL (Pony Diffusion) and "
            "for 3D figure generation.\n"
            "The description has ALREADY been partially translated to English tags by a "
            "reliable dictionary. Your job is ONLY to:\n"
            "  - keep every already-translated tag EXACTLY as given, never change it\n"
            "  - translate any remaining Chinese words into standard English tags\n"
            "  - reorder so that it starts with: 1girl, solo, anime character\n"
            "  - make sure these are present exactly once: full body, standing, front view, "
            "white background, simple background, correct proportions, masterpiece, "
            "best quality, highly detailed\n"
            "  - add any missing obvious visual traits\n"
            "Do NOT invent traits that are not implied. Do NOT repeat any tag. "
            "Output only the comma-separated tag list, no quotes, no explanation."
        )
    payload = {
        "model": model,
        "prompt": f"<|im_start|>system\n{system}<|im_end|>\n"
                  f"<|im_start|>user\n{translated}<|im_end|>\n<|im_start|>assistant\n",
        "stream": False,
        # keep_alive=0：请求结束立即卸载模型，把 24GB 显存还给 ComfyUI。
        # 否则 dolphin-mixtral 会一直占着显存，扩散模型被迫走 CPU，速度从 13s 掉到 150s+。
        "keep_alive": 0,
        "options": {"num_predict": 300, "temperature": 0.35, "top_p": 0.9, "repeat_penalty": 1.05},
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        # 降级：只用词典翻译结果
        if not quiet:
            print(f"    ! 大脑不可用（{type(e).__name__}），降级为纯词典翻译")
        return ", ".join(_dedup_tags(STD_HEAD + dict_tags + STD_TAIL))
    out = (data.get("response") or "").strip().strip("`").strip()
    if out.startswith('"') and out.endswith('"'):
        out = out[1:-1]
    out = out.strip()

    # LLM 输出只作为增量补充，丢掉与词典重复的
    seen = {_norm(t) for t in dict_tags}
    extras = []
    for t in out.split(","):
        t = " ".join(t.split()).strip(" .")
        if not t:
            continue
        if _norm(t) in seen or _collides(t, dict_tags):
            continue
        seen.add(_norm(t))
        extras.append(t)

    return ", ".join(_dedup_tags(STD_HEAD + dict_tags + extras + STD_TAIL))


def _dedup_tags(tags):
    """按归一化形式去重并保序"""
    out, seen = [], set()
    for t in tags:
        t = " ".join(str(t).split()).strip(" .")
        k = _norm(t)
        if not t or k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def gpu_mem():
    """返回 (已用 MB, 总 MB)，拿不到返回 (None, None)"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20)
        used, total = out.stdout.strip().splitlines()[0].split(",")
        return int(used.strip()), int(total.strip())
    except Exception:
        return None, None


def release_ollama_vram(verbose=True):
    """结束 Ollama 残留的 llama-server.exe runner，释放显存。

    实测坑：Ollama 即使在 keep_alive=0、`/api/ps` 已返回 models:[] 的情况下，
    llama-server.exe 进程仍会残留并占住 ~15.6GB 显存，导致 ComfyUI 只能 CPU 卸载，
    出图从 13 秒掉到 150 秒+。这里显式 taskkill 掉 runner。
    """
    if sys.platform != "win32":
        return
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=30)
        pids = []
        for line in out.stdout.splitlines():
            parts = [p.strip().strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].upper() == "LLAMA-SERVER.EXE":
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
        for pid in pids:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=30)
        if pids and verbose:
            print(f"    已结束残留 llama-server.exe ({len(pids)} 个) → 释放显存")
    except Exception as e:
        if verbose:
            print(f"    ! 清理 llama-server 失败（可忽略）: {e}")


def wait_vram_free(need_mb=6000, timeout=180, quiet=False):
    """等待显存释放到 need_mb 以上。

    等待其他程序自行释放显存，不强制结束进程。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        used, total = gpu_mem()
        if used is None:
            return True
        if total - used >= need_mb:
            if not quiet:
                print(f"    显存已就绪: 已用 {used}MB / 共 {total}MB")
            return True
        if not quiet:
            print(f"    等待显存释放: 已用 {used}MB / 共 {total}MB", flush=True)
        time.sleep(3)
    return False


def cmd_prompt(a):
    print(f"[*] 调用本地大脑 {a.brain} 生成提示词 ...")
    t0 = time.time()
    tags = brain_prompt(a.desc, a.brain)
    print(f"[✓] ({time.time()-t0:.1f}s)\n{tags}")
    print("\n[*] 可直接使用：")
    print(f'    python fig.py img "{tags}" --model pony')
    return 0



# ----------------------------------------------------------------- ComfyUI API
def api_get(path):
    req = urllib.request.Request(f"{HOST}{path}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post(path, payload):
    req = urllib.request.Request(
        f"{HOST}{path}", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_done(pid, timeout=1800, label=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        hist = api_get(f"/history/{pid}")
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI 工作流失败: {status.get('messages', [])}")
            return entry
        if label:
            el = int(time.time() - t0)
            if el % 30 == 0:
                print(f"    [{label}] 生成中 ... {el}s", flush=True)
    raise TimeoutError(f"{label} 超时")


def upload_image(path):
    boundary = "----WorkBuddyBoundary" + str(int(time.time() * 1000))
    fname = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    body = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{fname}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + \
           f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{HOST}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def collect_files(entry):
    files = []
    for node in entry.get("outputs", {}).values():
        for key in ("3d", "images", "gltf", "meshes"):
            for it in node.get(key, []) or []:
                if not isinstance(it, dict):
                    continue
                fn = it.get("filename")
                if fn:
                    files.append((fn, it.get("subfolder", ""), key))
        for k, v in node.items():
            if isinstance(v, str) and v.lower().endswith((".glb", ".gltf", ".obj", ".stl", ".ply", ".fbx")):
                files.append((os.path.basename(v), os.path.dirname(v).replace("\\", "/"), k))
    return files


def verified_output_path(filename, subfolder=""):
    """返回已实际写入输出目录的文件；拒绝失效缓存或越界路径。"""
    root = os.path.realpath(OUT)
    path = os.path.realpath(os.path.join(root, subfolder, filename))
    if os.path.commonpath([root, path]) != root or not os.path.isfile(path):
        raise FileNotFoundError(f"ComfyUI 返回了输出文件名，但文件不存在: {path}")
    if os.path.getsize(path) == 0:
        raise RuntimeError(f"ComfyUI 输出文件为空: {path}")
    return path


def unique_prefix(prefix):
    # 改变保存节点的输入，防止它复用已被删除的旧输出文件名。
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ----------------------------------------------------------------- 工作流构建
def build_image_wf(model, pos, neg, seed, w, h, steps):
    if model == "pony":
        return {
            "4": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": "ponyDiffusionV6XL_v6StartWithThisOne.safetensors"}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["4", 1]}},
            "3": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": steps, "cfg": 7.0,
                "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "fig_img"}},
        }
    return {
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-dev-fp8.safetensors"}},
        "20": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["10", 1]}},
        "21": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["10", 1]}},
        "30": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["20", 0], "guidance": 3.5}},
        "40": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "50": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
            "model": ["10", 0], "positive": ["30", 0], "negative": ["21", 0], "latent_image": ["40", 0]}},
        "60": {"class_type": "VAEDecode", "inputs": {"samples": ["50", 0], "vae": ["10", 2]}},
        "70": {"class_type": "SaveImage", "inputs": {"images": ["60", 0], "filename_prefix": "fig_img"}},
    }


def build_img2img_wf(model, pos, neg, seed, w, h, steps, denoise, image_name):
    """构建 img2img 工作流。

    与 txt2img 的区别：
      - LoadImage 替代 EmptyLatentImage / EmptySD3LatentImage
      - VAEEncode 把参考图编码到 latent 空间
      - KSampler 的 denoise 参数控制重绘强度：
          1.0 = 完全重绘（等同 txt2img）
          0.7 = 大幅修改但保留构图（常用）
          0.5 = 适度修改，保留大部分细节
          0.3 = 轻微调整（换颜色/小细节）
          0.0 = 不变
    """
    if model == "pony":
        return {
            "4": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": "ponyDiffusionV6XL_v6StartWithThisOne.safetensors"}},
            "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
            "5a": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["4", 2]}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["4", 1]}},
            "3": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": steps, "cfg": 7.0,
                "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": denoise,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["5a", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "fig_i2i"}},
        }
    # Flux img2img: FluxGuidance + SD3 latent
    return {
        "10": {"class_type": "CheckpointLoaderSimple",
               "inputs": {"ckpt_name": "flux1-dev-fp8.safetensors"}},
        "12": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "12a": {"class_type": "VAEEncode", "inputs": {"pixels": ["12", 0], "vae": ["10", 2]}},
        "20": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["10", 1]}},
        "21": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["10", 1]}},
        "30": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["20", 0], "guidance": 3.5}},
        "50": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": denoise,
            "model": ["10", 0], "positive": ["30", 0], "negative": ["21", 0],
            "latent_image": ["12a", 0]}},
        "60": {"class_type": "VAEDecode", "inputs": {"samples": ["50", 0], "vae": ["10", 2]}},
        "70": {"class_type": "SaveImage", "inputs": {"images": ["60", 0], "filename_prefix": "fig_i2i"}},
    }


def build_3d_wf(image_name, steps=50, resolution=3072, threshold=0.6, prefix="figure_3d",
                octree_resolution=512, mv_views=None,
                faces=0, crease=180.0, do_uv=False, do_preview=True,
                uv_resolution=2048, weld_distance=0.0,
                remesh_res=512, smooth_iters=3, band=1.0, project_back=0.0,
                high_precision=False, mv_images=None):
    """Hunyuan3D 2.1 图生3D（ComfyUI 核心原生节点）

    ★ ``mv_images``：多视图条件输入，形如 ``{"front": name, "left": name, ...}``。
      传入 2~4 个方位时改用 ``Hunyuan3Dv2ConditioningMultiView`` —— 这是解决
      「侧面/背面塌陷、长发糊成一坨、四肢缺证据」的正规路径；单图只有正面证据，
      模型只能靠猜测补背面。仅接受 Hunyuan 节点支持的 front/left/back/right；
      front 复用主图编码，其余方位各自 LoadImage + CLIPVisionEncode。
    ★ 默认稳定路径：高八叉树原始表面网格，不减面、不 UV、不 solid remesh。
      实测直接 solid remesh 会截掉头脚并错乱轴向，故只能显式实验启用。

    可选实验路径（high_precision=True）
      VoxelToMesh(surface net) -> RemeshMesh(solid) -> [DecimateMesh] -> UV -> 法线

      RemeshMesh 用窄带距离场 + Dual Contouring 重新提取均匀网格：
        - resolution=512 约 100 万面（相比旧路径 6 万面精细 17 倍）
        - sign_mode=solid 直接产出水密实体，无需二次体素化
        - smooth_iters=3 清理 DC 阶梯伪影（就是截图里的台阶）
      旧路径（high_precision=False）：
        VoxelToMesh -> DecimateMesh(60000) —— 面数少但表面呈明显阶梯状

    节点顺序铁律：减面 -> UV -> 法线
      DecimateMesh 只保留 (v,f,c)，丢弃 normals/uvs  -> 必须在 UV/法线之前
      UnwrapMesh   只输出 (v,f,uvs,colors)，不含 normals -> 必须在法线之前
      MeshSmoothNormals 通过 remap 保留已有 uvs         -> 放最后
    """
    wf = {
        "1": {"class_type": "ImageOnlyCheckpointLoader", "inputs": {"ckpt_name": "hunyuan_3d_v2.1.safetensors"}},
        "3": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 1.0, "model": ["1", 0]}},
        "12": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "13": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["1", 1], "image": ["12", 0], "crop": "center"}},
        "6": {"class_type": "Hunyuan3Dv2Conditioning", "inputs": {"clip_vision_output": ["13", 0]}},
        "4": {"class_type": "EmptyLatentHunyuan3Dv2", "inputs": {"resolution": resolution, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "seed": 894796671366012, "steps": steps, "cfg": 5.0,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
            "model": ["3", 0], "positive": ["6", 0], "negative": ["6", 1], "latent_image": ["4", 0]}},
        "8": {"class_type": "VAEDecodeHunyuan3D",
              "inputs": {"samples": ["7", 0], "vae": ["1", 2], "num_chunks": 8000,
                         "octree_resolution": octree_resolution}},
        "9": {"class_type": "VoxelToMesh", "inputs": {"voxel": ["8", 0], "threshold": threshold, "algorithm": "surface net"}},
    }
    if mv_images:
        allowed = ("front", "left", "back", "right")
        mv_images = {str(k).strip().lower(): str(v) for k, v in dict(mv_images).items()}
        bad = [k for k in mv_images if k not in allowed]
        if bad:
            raise ValueError("多视图方位无效: " + ",".join(bad) +
                             "（可用: " + ",".join(allowed) + "）")
        if len(mv_images) < 2:
            raise ValueError("多视图重建至少需要 2 个方位；单图请走普通 Hunyuan3Dv2Conditioning")
        if "front" not in mv_images:
            raise ValueError("多视图重建必须提供 front 方位，作为角色一致性锚点")
        for view in ("left", "back", "right"):
            if view not in mv_images:
                continue
            wf[f"mv_load_{view}"] = {"class_type": "LoadImage",
                                     "inputs": {"image": mv_images[view]}}
            wf[f"mv_clip_{view}"] = {"class_type": "CLIPVisionEncode", "inputs": {
                "clip_vision": ["1", 1], "image": [f"mv_load_{view}", 0], "crop": "center"}}
        wf["6"] = {"class_type": "Hunyuan3Dv2ConditioningMultiView", "inputs": {
            view: (["13", 0] if view == "front" else [f"mv_clip_{view}", 0])
            for view in ("front", "left", "back", "right") if view in mv_images}}
    tail = "9"
    if high_precision:
        # ★ RemeshMesh: 窄带 DC 重网格，产出水密且均匀细分的实体
        wf["31"] = {"class_type": "RemeshMesh", "inputs": {
            "mesh": ["9", 0], "resolution": remesh_res,
            "sign_mode": "solid", "sign_mode.fill": 20.0, "sign_mode.qef": False,
            "band": band, "project_back": project_back, "fix_poles": True,
            "smooth_iters": smooth_iters, "drop_small_components": 0.005,
            "precluster_max_verts": 20000000}}
        tail = "31"
    if faces and faces > 0:
        wf["16"] = {"class_type": "DecimateMesh", "inputs": {
            "mesh": [tail, 0], "target_face_count": faces, "placement_mode": "midpoint"}}
        tail = "16"
    if do_uv:
        # ★★ UnwrapMesh 会**撕裂网格**：实测在 440 万面网格上产生 49 万条边界边，
        #   水密性彻底丢失（RemeshMesh 之后本来是完全水密的，0 边界边）。
        #   3D 打印根本不需要 UV（UV 是给贴图/材质用的），
        #   所以默认**关闭 UV**，只在确实要做贴图时才加 --uv。
        wf["15"] = {"class_type": "UnwrapMesh", "inputs": {
            "mesh": [tail, 0], "segmenter": "pec", "resolution": uv_resolution,
            "padding": 4, "weld_distance": weld_distance}}
        tail = "15"
    # ★ crease_angle=180 = 完全平滑，拓扑不变（不分裂顶点，水密性保持）。
    #   低于 180 会「沿锐边分裂顶点」来保留硬边 —— 那会破坏水密性。
    #   3D 打印要的是水密实体，法线由切片软件自己算，所以用 180。
    wf["14"] = {"class_type": "MeshSmoothNormals", "inputs": {"mesh": [tail, 0], "crease_angle": crease}}
    tail = "14"
    wf["10"] = {"class_type": "MeshToFile3D", "inputs": {"mesh": [tail, 0]}}
    wf["11"] = {"class_type": "SaveGLB", "inputs": {"mesh": ["10", 0], "filename_prefix": prefix}}
    if do_preview:
        wf["20"] = {"class_type": "RenderMesh", "inputs": {
            "mesh": [tail, 0], "mode": "auto", "width": 1024, "height": 1024, "background": "#202020"}}
        wf["21"] = {"class_type": "SaveImage", "inputs": {"images": ["20", 0], "filename_prefix": prefix + "_preview"}}
        # 背面 / 侧面预览：只看正面很容易误判还原度
        wf["22"] = {"class_type": "RotateMesh", "inputs": {
            "mesh": [tail, 0], "mode": "euler_xyz",
            "mode.angle_x": 0.0, "mode.angle_y": 180.0, "mode.angle_z": 0.0}}
        wf["23"] = {"class_type": "RenderMesh", "inputs": {
            "mesh": ["22", 0], "mode": "solid", "width": 1024, "height": 1024, "background": "#202020"}}
        wf["24"] = {"class_type": "SaveImage", "inputs": {"images": ["23", 0],
                                                          "filename_prefix": prefix + "_preview_back"}}
        wf["25"] = {"class_type": "RotateMesh", "inputs": {
            "mesh": [tail, 0], "mode": "euler_xyz",
            "mode.angle_x": 0.0, "mode.angle_y": 90.0, "mode.angle_z": 0.0}}
        wf["26"] = {"class_type": "RenderMesh", "inputs": {
            "mesh": ["25", 0], "mode": "solid", "width": 1024, "height": 1024, "background": "#202020"}}
        wf["27"] = {"class_type": "SaveImage", "inputs": {"images": ["26", 0],
                                                          "filename_prefix": prefix + "_preview_side"}}
    # ★ 多视图定格：同一个网格绕竖轴旋转，渲染 8 个方位（姿势/比例完全不变）
    if mv_views:
        for view in mv_views:
            if view not in MV_ANGLES:
                continue
            rot = f"mv_{view}_rot"
            render = f"mv_{view}_render"
            save = f"mv_{view}_save"
            wf[rot] = {"class_type": "RotateMesh", "inputs": {
                "mesh": [tail, 0], "mode": "euler_xyz",
                "mode.angle_x": 0.0, "mode.angle_y": MV_ANGLES[view], "mode.angle_z": 0.0}}
            wf[render] = {"class_type": "RenderMesh", "inputs": {
                "mesh": [rot, 0], "mode": "solid", "width": 1024, "height": 1024,
                "background": "#202020"}}
            wf[save] = {"class_type": "SaveImage", "inputs": {
                "images": [render, 0], "filename_prefix": prefix + "_clay_" + view}}
    return wf


# ----------------------------------------------------------------- 子命令
def vram_warn(need_mb=4000):
    """启动前检查显存，不足则给出明确提示（避免莫名其妙变慢 10 倍）"""
    used, total = gpu_mem()
    if used is None:
        return
    free = total - used
    if free < need_mb:
        print(f"[!] 显存只剩 {free}MB / {total}MB，很可能不够用。")
        print("    请关闭占显存的程序：微信 / QQ / Wallpaper Engine / NVIDIA Broadcast /")
        print("                    TourBox Console / Steam / Edge / NVIDIA Overlay")
        print("    ComfyUI 若已加载模型，显存不会自动释放，可重启 ComfyUI。")
    else:
        print(f"    显存可用 {free}MB / {total}MB")


def cmd_img(a):
    global _LAST_PICKED
    pos = a.prompt
    neg = a.neg or DEFAULT_NEG
    print(f"[*] 出图: {a.model}  {a.width}x{a.height}  steps={a.steps}")
    vram_warn()

    # 自动挑好图：两个判据，任一不达标就换 seed 重抽
    #   1. 灰色背景板 —— 会被 Hunyuan3D 重建成一整面墙
    #   2. 非正面姿态 —— 3/4 侧身会导致 3D 重建丢腿（实测：正面双腿完整，侧身只剩裙子）
    # seed 对这两项的影响都远大于负面词，所以策略是「出图 → 检测 → 不达标就重抽」
    best = None
    attempts = max(1, a.retry)
    for i in range(attempts):
        seed = a.seed + i if a.seed >= 0 else int(time.time() * 1000) % 2**31 + i
        wf = build_image_wf(a.model, pos, neg, seed, a.width, a.height, a.steps)
        save_node = "9" if a.model == "pony" else "70"
        wf[save_node]["inputs"]["filename_prefix"] = unique_prefix("fig_img")
        pid = api_post("/prompt", {"prompt": wf}).get("prompt_id")
        if not pid:
            print("[!] 提交失败")
            return 1
        entry = wait_done(pid, 1800, "出图")
        files = collect_files(entry)
        if not files:
            print("[!] 无输出")
            return 1
        fn, sub, _ = files[0]
        p = verified_output_path(fn, sub)
        print(f"[✓] {p}  (seed={seed})")

        if not a.check_bg:
            _LAST_PICKED = p
            break

        score = 0.0
        ok = True
        ratio, verdict = check_background_cleanliness(p, a.bg_limit)
        print(f"    {verdict}")
        if ratio is not None:
            score += ratio
            if ratio > a.bg_limit:
                ok = False
        asym, v2 = check_front_view(p, a.asym_limit)
        print(f"    {v2}")
        if asym is not None:
            score += asym * 2      # 姿态问题更致命，权重加倍
            if asym > a.asym_limit:
                ok = False

        if best is None or score < best[0]:
            best = (score, p)
        if ok:
            _LAST_PICKED = p
            break   # 全部达标，收工
        if i < attempts - 1:
            print(f"    · 不达标，换 seed 重抽 ({i+2}/{attempts}) ...")
            continue
        # 全部尝试完，用评分最好的那张
        if best and best[1] != p:
            print(f"    · 采用历次最佳: {best[1]} (评分 {best[0]:.3f})")
        _LAST_PICKED = best[1] if best else p
        break
    return 0


def build_qwen_figure_edit_wf(image_name, prompt, seed, prefix, refs=None, cfg=4.0, steps=20):
    """Comfy 官方 Qwen-Image-Edit-2509 编辑流程（主图 + 最多 2 张参考图；无 Lightning LoRA）。"""
    wf = {
        "load": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "scale": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["load", 0]}},
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_edit_2509_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "sampling": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["unet", 0], "shift": 3.0}},
        "norm": {"class_type": "CFGNorm", "inputs": {"model": ["sampling", 0], "strength": 1.0}},
        "positive": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["clip", 0], "vae": ["vae", 0], "image1": ["scale", 0], "prompt": prompt}},
        "negative": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["clip", 0], "vae": ["vae", 0], "image1": ["scale", 0], "prompt": ""}},
        "latent": {"class_type": "VAEEncode", "inputs": {"pixels": ["scale", 0], "vae": ["vae", 0]}},
        "sample": {"class_type": "KSampler", "inputs": {"model": ["norm", 0], "seed": seed, "steps": max(8, min(30, int(steps))), "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "positive": ["positive", 0], "negative": ["negative", 0], "latent_image": ["latent", 0], "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": prefix}},
    }
    # ★ Qwen-Image-Edit-2509 原生支持 3 张图：image1=主图，image2/image3=参考图。
    #   TextEncodeQwenImageEditPlus 会分别缩放到 ~1024² 做 VAE 参考、~384² 给视觉塔。
    refs = [r for r in (refs or []) if r]
    for index, ref_name in enumerate(refs[:2]):
        node = f"ref{index + 2}"
        slot = f"image{index + 2}"
        wf[node] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
        wf["positive"]["inputs"][slot] = [node, 0]
        wf["negative"]["inputs"][slot] = [node, 0]
    if len(refs) > 2:
        print(f"[*] Qwen-2509 最多使用主图 + 2 张参考图，多余 {len(refs) - 2} 张已忽略。", flush=True)
    return wf


# ---------------------------------------------------------------- 图片编辑
EDIT_INSTRUCTION_HEAD = ("Edit the reference image according to this request. "
                         "Preserve all other visual details, the original 2D illustration style, "
                         "composition, subject identity and pose unless explicitly requested. ")
WHOLE_FRAME_INSTRUCTION = (
    "Return one complete image with the same full canvas, aspect ratio, framing and camera distance. "
    "Never crop, zoom into, or return only a body part. Do not blur, mosaic, cover, or simplify fine details. ")
CLEAR_MARKS_INSTRUCTION = (
    "Remove only the painted pose/rig guide marks inside the selected region and reconstruct the underlying "
    "lines, flat colours and shading naturally. Keep anatomy and every visible toe, finger, hair strand and "
    "clothing edge intact; do not use blur, mosaic, smudging or a solid cover-up. ")


def _load_rgb_image(path):
    from PIL import Image, ImageOps
    with Image.open(path) as f:
        return ImageOps.exif_transpose(f).convert("RGB")


def _load_edit_mask(mask_path, size):
    from PIL import Image
    with Image.open(mask_path) as f:
        return f.convert("L").resize(size, Image.Resampling.NEAREST)


def _box_sum(values, kernel):
    import numpy as np
    padded = np.pad(values, ((1, 0), (1, 0)), mode="constant")
    integral = padded.cumsum(0).cumsum(1)
    height, width = values.shape
    radius = kernel // 2
    y0 = np.clip(np.arange(height) - radius, 0, height)
    y1 = np.clip(np.arange(height) + radius + 1, 0, height)
    x0 = np.clip(np.arange(width) - radius, 0, width)
    x1 = np.clip(np.arange(width) + radius + 1, 0, width)
    return (integral[np.ix_(y1, x1)] - integral[np.ix_(y0, x1)]
            - integral[np.ix_(y1, x0)] + integral[np.ix_(y0, x0)])


def _local_variance(gray, kernel=9):
    import numpy as np
    total = _box_sum(gray, kernel)
    total2 = _box_sum(gray * gray, kernel)
    count = _box_sum(np.ones_like(gray), kernel)
    mean = total / count
    return np.maximum(total2 / count - mean * mean, 0.0)


def flat_noise_ratio(original, edited, mask=None, size=384, kernel=9, flat_var=12.0):
    """测量「平坦区域噪点放大倍数」：≈1 正常，>8 说明整片背景被画成了雪花/马赛克。

    实测：Qwen-Image-Edit-2509 在个别随机种子下会把平滑背景整片生成成高频噪点
    （用户看到的就是「像打了马赛克」）。正常结果的倍数在 0.9~1.2，失败结果在
    300~2000 倍，两者区分度极大，所以可以据此自动换种子重试。
    """
    import numpy as np
    from PIL import Image, ImageFilter
    width, height = original.size
    scale = min(1.0, size / max(width, height))
    small = (max(32, round(width * scale)), max(32, round(height * scale)))
    orig = np.asarray(original.convert("L").resize(small, Image.Resampling.LANCZOS),
                      dtype=np.float64)
    edit = np.asarray(edited.convert("L").resize(small, Image.Resampling.LANCZOS),
                      dtype=np.float64)
    orig_var = _local_variance(orig, kernel)
    edit_var = _local_variance(edit, kernel)
    valid = orig_var < flat_var
    if mask is not None:
        region = np.asarray(mask.convert("L").resize(small, Image.Resampling.NEAREST),
                            dtype=np.uint8) > 32
        radius = max(2, round(max(small) * 0.015))
        grown = Image.fromarray(region.astype(np.uint8) * 255).filter(
            ImageFilter.MaxFilter(2 * radius + 1))
        valid = valid & ~(np.asarray(grown) > 128)
    if int(valid.sum()) < 200:
        return 1.0, "平坦区域太少，跳过检测"
    orig_mean = float(orig_var[valid].mean())
    edit_mean = float(edit_var[valid].mean())
    return (edit_mean + 0.5) / (orig_mean + 0.5), f"var {orig_mean:.1f}→{edit_mean:.1f}"


def feather_alpha(mask, grow=4, blur=4):
    """涂抹区域向外扩一点再羽化，回贴时边界过渡自然。"""
    from PIL import ImageFilter
    grown = mask.filter(ImageFilter.MaxFilter(2 * grow + 1)) if grow > 0 else mask
    return grown.filter(ImageFilter.GaussianBlur(blur))


def _local_crop_plan(original, mask):
    """根据涂抹区域算一个“裁剪 + 放大”的重绘计划：像素集中花在目标区域。"""
    from PIL import Image
    width, height = original.size
    binary = mask.point(lambda x: 255 if x > 16 else 0)
    bbox = binary.getbbox()
    if not bbox:
        return None
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = max(48, int(round(max(bw, bh) * 0.5)))
    box = (max(0, bbox[0] - margin), max(0, bbox[1] - margin),
           min(width, bbox[2] + margin), min(height, bbox[3] + margin))
    crop = original.crop(box)
    long_side = max(crop.size)
    scale = min(3.0, max(1.0, 1024.0 / max(1, long_side)))
    size = (max(16, round(crop.width * scale)), max(16, round(crop.height * scale)))
    up = crop.resize(size, Image.Resampling.LANCZOS)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        up.save(tmp.name)
        name = upload_image(tmp.name).get("name")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    if not name:
        return None
    return {"name": name, "box": box, "crop_size": crop.size, "scale": scale}


def _run_local_crop_edit(plan, original, instruction, seed, cfg=4.0, steps=16):
    """在裁剪放大图上重绘，再贴回原图（只作为“重绘结果”，最终由羽化/融合决定保留范围）。"""
    from PIL import Image
    crop_instruction = (
        "This image is a zoomed-in crop from a larger 2D illustration. Preserve its original drawing style, "
        "flat colours, line work and lighting. Keep the framing identical and edit ONLY the requested content "
        "inside this crop; leave all other structure, lines and details unchanged. Do not add borders, frames, "
        "text or extra objects. "
        + instruction)
    _, raw_image = run_qwen_edit(plan["name"], crop_instruction, seed, [], cfg=cfg, steps=steps)
    edited_crop = raw_image.resize(plan["crop_size"], Image.Resampling.LANCZOS)
    edited_full = original.copy()
    edited_full.paste(edited_crop, plan["box"][:2])
    return edited_full


def _refine_local_blend(original, edited, mask, preserve_details=False):
    """把重绘结果回贴到原图；标记清理模式避免会抹糊线稿的强融合。"""
    from PIL import Image, ImageFilter, ImageStat, ImageChops
    import numpy as np
    width, height = original.size
    binary = mask.point(lambda x: 255 if x > 16 else 0)
    if preserve_details:
        # Guide-mark cleanup should retain crisp line art/anatomy.  The legacy
        # Poisson path is useful for broad photographic edits, but it can turn
        # fine toes and outlines into a visibly smudged patch.
        narrow = binary.filter(ImageFilter.GaussianBlur(0.8))
        return Image.composite(edited, original, narrow)
    diag = max(width, height)
    grow = max(3, int(round(diag * 0.004)))
    blur = max(2, int(round(diag * 0.006)))
    grown = binary.filter(ImageFilter.MaxFilter(2 * grow + 1))
    alpha = grown.filter(ImageFilter.GaussianBlur(blur))

    # ① 用选区外一圈的颜色统计校正重绘区域，去掉“色块/贴图”感
    inner = binary.filter(ImageFilter.MaxFilter(2 * (grow + 4) + 1))
    outer = binary.filter(ImageFilter.MaxFilter(2 * (grow + 4 + max(10, blur * 4)) + 1))
    band = ImageChops.subtract(outer, inner)
    if band.getbbox():
        try:
            o_stat = ImageStat.Stat(original, band)
            e_stat = ImageStat.Stat(edited, band)
            arr = np.asarray(edited, dtype=np.float32).copy()
            for c in range(3):
                gain = (o_stat.stddev[c] + 1e-6) / (e_stat.stddev[c] + 1e-6)
                gain = min(1.2, max(0.85, gain))
                offset = o_stat.mean[c] - e_stat.mean[c] * gain
                arr[..., c] = arr[..., c] * gain + offset
            edited = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
        except Exception:  # noqa: BLE001
            pass

    merged = Image.composite(edited, original, alpha)

    # ② Poisson 无缝融合：边缘按梯度过渡，而不是生硬的 alpha 混合
    try:
        import cv2
        mask_u8 = np.asarray(grown, dtype=np.uint8)
        ys, xs = np.where(mask_u8 > 128)
        if len(xs) > 100 and xs.min() > 0 and ys.min() > 0 and xs.max() < width - 1 and ys.max() < height - 1:
            center = (int(xs.mean()), int(ys.mean()))
            src_bgr = cv2.cvtColor(np.asarray(edited), cv2.COLOR_RGB2BGR)
            dst_bgr = cv2.cvtColor(np.asarray(original), cv2.COLOR_RGB2BGR)
            cloned = cv2.seamlessClone(src_bgr, dst_bgr, mask_u8, center, cv2.NORMAL_CLONE)
            merged = Image.fromarray(cv2.cvtColor(cloned, cv2.COLOR_BGR2RGB))
    except Exception:  # noqa: BLE001
        pass

    # ③ 选区内轻度锐化：避免整块发虚（用腐蚀内区，避免边缘出现白边）
    try:
        core = binary.filter(ImageFilter.MinFilter(2 * max(2, grow) + 1))
        if core.getbbox():
            arr = np.asarray(merged, dtype=np.float32)
            blur_arr = np.asarray(merged.filter(ImageFilter.GaussianBlur(1.1)), dtype=np.float32)
            sharp = np.clip(arr + (arr - blur_arr) * 0.5, 0, 255)
            sel = np.asarray(core) > 128
            arr[sel] = sharp[sel]
            merged = Image.fromarray(arr.astype("uint8"))
    except Exception:  # noqa: BLE001
        pass
    return merged


def run_qwen_edit(image_name, instruction, seed, refs=None, cfg=4.0, steps=16):
    """跑一次 Qwen-Image-Edit 编辑，返回 (ComfyUI 输出路径, PIL RGB 图像)。

    image_name / refs 都是已经上传到 ComfyUI 的文件名（同一轮里只上传一次）。
    """
    wf = build_qwen_figure_edit_wf(image_name, instruction, seed, unique_prefix("fig_edit"),
                                   refs, cfg=cfg, steps=steps)
    pid = api_post("/prompt", {"prompt": wf}).get("prompt_id")
    if not pid:
        raise RuntimeError("编辑任务提交失败")
    files = collect_files(wait_done(pid, 1800, "图片编辑"))
    images = [(fn, sub) for fn, sub, kind in files
              if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    if not images:
        raise RuntimeError("编辑任务没有输出图片")
    filename, subfolder = images[0]
    path = verified_output_path(filename, subfolder)
    return path, _load_rgb_image(path)


def ensure_comfyui_running():
    """ComfyUI 没启动时自动拉起；退出时由 atexit 精确停止本进程拉起的实例。"""
    global _OWNED_COMFY_PROC
    try:
        urllib.request.urlopen(HOST + "/system_stats", timeout=3).close()
        return
    except (urllib.error.URLError, OSError):
        pass

    # 互斥启动：两个 CLI/任务同时发现服务未启动时，不能各起一份 ComfyUI。
    lock_path = os.path.join(HERE, "ComfyUI", ".fig_start.lock")
    lock_owned = False
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        lock_owned = True
    except FileExistsError:
        try:
            age = time.time() - os.path.getmtime(lock_path)
        except OSError:
            age = 0
        if age > 120:
            try:
                os.remove(lock_path)
            except OSError:
                pass
            return ensure_comfyui_running()
        print("[*] 另一个进程正在启动 ComfyUI，等待其就绪……", flush=True)
        for _ in range(90):
            time.sleep(1)
            try:
                urllib.request.urlopen(HOST + "/system_stats", timeout=2).close()
                return
            except (urllib.error.URLError, OSError):
                pass
        raise RuntimeError("ComfyUI 正在被另一个进程启动，但 90 秒内未就绪")

    try:
        print("[*] ComfyUI 尚未运行，正在启动并等待就绪……", flush=True)
        log_path = os.path.join(HERE, "ComfyUI", "comfyui_auto.log")
        with open(log_path, "ab") as log:
            log.write(b"\n--- fig.py auto start ---\n")
            log.flush()
            _OWNED_COMFY_PROC = subprocess.Popen(
                [sys.executable, "main.py", "--port", "8188"],
                cwd=os.path.join(HERE, "ComfyUI"),
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(90):
            time.sleep(1)
            try:
                urllib.request.urlopen(HOST + "/system_stats", timeout=2).close()
                return
            except (urllib.error.URLError, OSError):
                pass
        _stop_owned_comfyui()
        try:
            tail = open(log_path, "r", encoding="utf-8", errors="replace").read()[-1200:]
        except OSError:
            tail = ""
        raise RuntimeError("ComfyUI 启动超时。最近日志：\n" + tail)
    finally:
        if lock_owned:
            try:
                os.remove(lock_path)
            except OSError:
                pass


def cmd_edit_image(a):
    """按修改要求编辑已有图片。

    两种模式：
      · 局部重绘（涂抹区域 + local/auto/remove）：Qwen 重画整张图，但只把「涂抹
        区域」回贴到原图（边缘羽化过渡），选区外像素保持原样。
      · 整图重生成（whole，或不涂抹的 ai）：整张图都换成重生成结果。

    ★ 随机种子 + 质量检测：旧的固定种子 123456 会把平滑背景整片生成成高频噪点
    （看起来就是「像马赛克/雪花打码」）。现在默认随机种子，生成后检测平坦区域
    噪点放大倍数，异常就自动换种子重试，避免把失败图交给用户。
    """
    if not os.path.isfile(a.image):
        print(f"[!] 图片不存在: {a.image}")
        return 1
    request = a.instruction.strip()
    if not request:
        print("[!] 修改要求不能为空")
        return 1
    method = getattr(a, "method", "auto") or "auto"
    if method == "fast":
        print("[!] “快速背景插值”会留下模糊色块，已停用；请改用“局部重绘”。", flush=True)
        return 1
    whole_mode = method in ("ai", "whole")
    # `whole` is an explicit full-frame operation.  A UI may still submit its
    # visible paint layer, but it must never turn this request into a cropped
    # local edit (which otherwise emits a close-up and blends it back badly).
    use_mask = bool(a.mask) and not whole_mode
    preserve_mark_details = method == "remove"
    original = _load_rgb_image(a.image)
    mask = _load_edit_mask(a.mask, original.size) if use_mask else None
    if mask is not None:
        from PIL import ImageStat
        filled = ImageStat.Stat(mask).sum[0] / (255.0 * original.size[0] * original.size[1])
        if not mask.getbbox() or filled <= 0.002:
            print("[!] 涂抹区域为空，请先涂抹需要修改的区域", flush=True)
            return 1
        if filled > 0.9:
            print("[*] 涂抹范围接近整张图，按整图重生成处理。", flush=True)
            use_mask = False
            mask = None
    print(f"[*] 编辑图片: {os.path.abspath(a.image)}", flush=True)
    print(f"[*] 修改要求: {request}", flush=True)
    if whole_mode:
        print("[*] 模式: 整图重生成（不使用涂抹遮罩）", flush=True)
    elif preserve_mark_details:
        print("[*] 模式: 标记清理（保真局部重绘，选区外保持原图像素）", flush=True)
    elif use_mask:
        print("[*] 模式: 局部重绘（只替换涂抹区域，选区外保持原图像素）", flush=True)
    else:
        print("[*] 模式: 整图重生成", flush=True)
    ensure_comfyui_running()
    uploaded_main = upload_image(a.image).get("name")
    if not uploaded_main:
        raise RuntimeError("图片上传失败")
    uploaded_refs = []
    for ref_path in (getattr(a, "refs", None) or []):
        if not os.path.isfile(ref_path):
            print(f"[!] 参考图不存在，已跳过: {ref_path}", flush=True)
            continue
        ref_name = upload_image(ref_path).get("name")
        if ref_name:
            uploaded_refs.append(ref_name)
    instruction = EDIT_INSTRUCTION_HEAD
    if whole_mode:
        instruction += WHOLE_FRAME_INSTRUCTION
    if preserve_mark_details:
        instruction += CLEAR_MARKS_INSTRUCTION
    instruction += request
    if uploaded_refs:
        print(f"[*] 已附加 {len(uploaded_refs)} 张参考图（主图之外）。", flush=True)
        instruction = ("The first image is the image to edit; the following images are reference images "
                       "for design details (character, outfit, colors, style). Use them only as reference; "
                       "do not copy their background or composition. " + instruction)

    from PIL import Image
    # 局部重绘默认走“裁剪放大重绘”（像素集中花在目标区域），可用 --no-crop-local 关闭
    use_crop_local = bool(use_mask) and not getattr(a, "no_crop_local", False)
    crop_plan = None
    if use_crop_local:
        crop_plan = _local_crop_plan(original, mask)
        if crop_plan:
            print(f"[*] 局部高清重绘：裁剪 {crop_plan['crop_size'][0]}x{crop_plan['crop_size'][1]} "
                  f"放大 {crop_plan['scale']:.1f}×", flush=True)
        else:
            use_crop_local = False
    mask_bin = mask.point(lambda x: 255 if x > 16 else 0) if use_mask else None
    # One clean candidate is the normal fast path.  A second retry remains
    # available for callers that explicitly request it, but no longer doubles
    # a user's wait by default when the first result is healthy.
    attempts = max(1, min(2, int(getattr(a, "attempts", 1) or 1)))
    candidates = max(1, min(3, int(getattr(a, "candidates", 1) or 1)))
    steps = max(8, min(30, int(getattr(a, "steps", 16) or 16)))
    print(f"[*] Qwen 采样: {steps} 步；主方案 {attempts} 次尝试；共 {candidates} 个展示方案。", flush=True)
    threshold = 8.0
    best = None
    candidate_results = []
    # 多方案：不同 cfg + 不同措辞，避免每次生成几乎一样
    cfg_samples = [4.0, 5.4, 3.2]
    variant_hints = [
        "",
        "Try an alternative, clearly different interpretation of this modification while keeping it faithful.",
        "Apply the requested change more boldly and completely than a minimal edit.",
    ]
    for index in range(attempts):
        seed = a.seed if (index == 0 and a.seed >= 0) else random.randint(0, 2 ** 31 - 1)
        print(f"[*] 生成第 {index + 1}/{attempts} 张（seed={seed}）……", flush=True)
        if use_crop_local:
            edited = _run_local_crop_edit(crop_plan, original, instruction, seed, steps=steps)
            raw_path = ""
        else:
            raw_path, raw_image = run_qwen_edit(uploaded_main, instruction, seed, uploaded_refs, steps=steps)
            edited = raw_image.resize(original.size, Image.Resampling.LANCZOS)
        edited_check = Image.composite(edited, original, mask_bin) if use_mask else edited
        ratio, detail = flat_noise_ratio(original, edited_check, mask if use_mask else None)
        print(f"    质量检测：平坦区域噪点 ×{ratio:.2f}（{detail}）", flush=True)
        if best is None or ratio < best[0]:
            best = (ratio, seed, edited, raw_path)
        if ratio <= threshold:
            break
        if index < attempts - 1:
            print("    · 检测到异常噪点，换随机种子重试……", flush=True)

    ratio, seed, edited, raw_path = best
    # 额外方案（只用于“多方案”预览；默认 1 张不额外耗时）
    for extra_index in range(1, candidates):
        extra_seed = random.randint(0, 2 ** 31 - 1)
        extra_cfg = cfg_samples[extra_index] if extra_index < len(cfg_samples) else 4.0
        hint = variant_hints[extra_index] if extra_index < len(variant_hints) else ""
        variant_instruction = instruction + ((" " + hint) if hint else "")
        print(f"[*] 生成备选方案 {extra_index + 1}/{candidates}（seed={extra_seed}, cfg={extra_cfg}）……",
              flush=True)
        try:
            if use_crop_local:
                edited2 = _run_local_crop_edit(crop_plan, original, variant_instruction,
                                               extra_seed, cfg=extra_cfg, steps=steps)
            else:
                raw2, img2 = run_qwen_edit(uploaded_main, variant_instruction, extra_seed,
                                           uploaded_refs, cfg=extra_cfg, steps=steps)
                edited2 = img2.resize(original.size, Image.Resampling.LANCZOS)
            edited2_check = Image.composite(edited2, original, mask_bin) if use_mask else edited2
            r2, d2 = flat_noise_ratio(original, edited2_check, mask if use_mask else None)
            print(f"    备选质量：平坦区域噪点 ×{r2:.2f}（{d2}）", flush=True)
            candidate_results.append((extra_index + 1, extra_seed, edited2))
        except Exception as exc:  # noqa: BLE001
            print(f"[!] 备选方案 {extra_index + 1} 失败: {exc}", flush=True)
    if ratio > threshold:
        print(f"[!] 提示：本次结果可能仍有噪点（×{ratio:.2f}）；可再次点击生成或调整修改要求。",
              flush=True)
    else:
        print(f"[*] 质量检测通过（噪点 ×{ratio:.2f}，seed={seed}）。", flush=True)

    if use_mask:
        merged = _refine_local_blend(original, edited, mask, preserve_details=preserve_mark_details)
        destination = os.path.join(OUT, unique_prefix("fig_edit_local") + ".png")
        merged.save(destination)
        result = verified_output_path(os.path.basename(destination))
        print("[*] 已把涂抹区域的结果回贴到原图，选区外像素保持不变。", flush=True)
    else:
        destination = os.path.join(OUT, unique_prefix("fig_edit_whole") + ".png")
        edited.save(destination)
        result = verified_output_path(os.path.basename(destination))
        print(f"[*] 已按原图尺寸 {original.size[0]}x{original.size[1]} 保存整图结果。", flush=True)
    print(f"[✓] 编辑结果: {result}", flush=True)
    for cand_no, cand_seed, cand_img in candidate_results:
        if use_mask:
            cand = _refine_local_blend(original, cand_img, mask, preserve_details=preserve_mark_details)
            cand_dest = os.path.join(OUT, unique_prefix(f"fig_edit_local_c{cand_no}") + ".png")
        else:
            cand = cand_img
            cand_dest = os.path.join(OUT, unique_prefix(f"fig_edit_whole_c{cand_no}") + ".png")
        cand.save(cand_dest)
        print(f"[候选 {cand_no}] seed={cand_seed} {verified_output_path(os.path.basename(cand_dest))}",
              flush=True)
    return 0


def qwen_figure_instruction(description, style):
    target = "a studio product photograph" if style == "figure_photo" else "a detailed studio 3D render"
    return (f"Transform the illustrated character in the reference into {target} of a painted collectible figurine. "
            "Preserve the same number of characters, their poses, silhouettes, viewing angle, hairstyles and colors, "
            "face design, outfit and visible accessories. Preserve the composition without adding extra "
            "heads or limbs. Make the hair sculpted in coherent solid clumps and use painted resin/PVC "
            "materials with realistic surface shading, soft studio lighting and clean detail. "
            "If the illustration is printed on a photographed object, depict the illustrated character "
            "as the figurine instead of reproducing the physical holder or reflections. "
            f"Visible reference details to retain, subject to the source image: {description}")


def apply_sdxl_canny(wf, control_name, strength=0.65):
    """给 Pony/SDXL 图生图加原图轮廓条件，按约 100 万像素保留比例。"""
    wf["5scale"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {
        "image": ["5", 0], "upscale_method": "lanczos", "megapixels": 1.0, "resolution_steps": 8}}
    wf["5a"]["inputs"]["pixels"] = ["5scale", 0]
    wf["canny"] = {"class_type": "Canny", "inputs": {
        "image": ["5scale", 0], "low_threshold": 0.25, "high_threshold": 0.55}}
    wf["control_loader"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": control_name}}
    wf["control_apply"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
        "positive": ["6", 0], "negative": ["7", 0],
        "control_net": ["control_loader", 0], "image": ["canny", 0],
        "strength": strength, "start_percent": 0.0, "end_percent": 0.8}}
    wf["3"]["inputs"]["positive"] = ["control_apply", 0]
    wf["3"]["inputs"]["negative"] = ["control_apply", 1]
    return wf


def cmd_img2img(a):
    """图生图（img2img）：上传参考图 + 提示词 -> ComfyUI 重绘。

    核心参数 --strength（denoise）控制重绘强度：
      1.0 = 完全重画（几乎不保留原图）   0.7 = 大幅修改
      0.5 = 适度修改                       0.3 = 尽量保留参考图
    """
    global _LAST_PICKED
    src = a.image
    if not os.path.isfile(src):
        print(f"[!] 找不到图片: {src}")
        return 1

    styles = {
        "original": ("", "photorealistic, photo, realistic skin, 3d render, "),
        "figure_render": ("3d render of a painted collectible figurine, sculpted solid forms, "
                          "painted resin material, detailed surface, studio lighting", "flat illustration, 2d drawing, "),
        "figure_photo": ("product photograph of a painted collectible figurine, sculpted solid forms, "
                         "painted resin material, studio lighting, realistic materials", "flat illustration, 2d drawing, "),
    }
    style_prompt, style_negative = styles[a.style]
    pos = f"{style_prompt}, {a.prompt}" if style_prompt else a.prompt
    # 目标风格不同，负面提示词也必须不同；不要排斥选中的3D或实拍风格。
    neg = a.neg or (style_negative + "blurry, low quality, watermark, signature, "
                    "extra limbs, extra head, malformed anatomy")
    denoise = a.strength
    control_name = "xinsir_controlnet_canny_sdxl.safetensors"
    if a.engine == "qwen":
        required = [("diffusion_models", "qwen_image_edit_2509_fp8_e4m3fn.safetensors"),
                    ("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors"),
                    ("vae", "qwen_image_vae.safetensors")]
        missing = [os.path.join(HERE, "ComfyUI", "models", d, f) for d, f in required
                   if not os.path.isfile(os.path.join(HERE, "ComfyUI", "models", d, f))]
        if missing:
            raise FileNotFoundError("Qwen 手办编辑模型尚未就绪: " + ", ".join(missing))
        if a.style == "original": raise ValueError("Qwen 手办流程请选择手办渲染或手办实拍")
        print("[*] Qwen 2509 固定编辑流程（20步；不使用重绘强度滑块和 SDXL Canny）")
    if a.engine == "pony" and a.structure == "canny":
        if a.model != "pony":
            raise ValueError("轮廓控制仅支持 Pony/SDXL 模型")
        control_path = os.path.join(HERE, "ComfyUI", "models", "controlnet", control_name)
        if not os.path.isfile(control_path):
            raise FileNotFoundError(f"缺少轮廓控制模型: {control_path}")
        print("[*] 轮廓控制: SDXL Canny，目标约100万像素；照片背景和边框也会进入轮廓")
    if a.engine == "qwen":
        print(f"[*] 图生图: Qwen 2509  style={a.style}  src={os.path.basename(src)}  steps=20")
    else:
        print(f"[*] 图生图: {a.model}  style={a.style}  src={os.path.basename(src)}  "
              f"denoise={denoise}  steps={a.steps}")
    vram_warn()

    # 上传参考图到 ComfyUI
    up = upload_image(src)
    image_name = up.get("name")
    if not image_name:
        print(f"[!] 上传失败: {up}")
        return 1
    print(f"    已上传参考图: {image_name}")
    ref_names = []
    extra_refs = [p for p in (getattr(a, "refs", None) or []) if p]
    if extra_refs:
        if a.engine != "qwen":
            raise ValueError("多参考图仅 Qwen 编辑流程支持（Pony 图生图没有参考图入参）")
        for ref_path in extra_refs:
            if not os.path.isfile(ref_path):
                print(f"[!] 参考图不存在，已跳过: {ref_path}", flush=True)
                continue
            ref_name = upload_image(ref_path).get("name")
            if ref_name:
                ref_names.append(ref_name)
        print(f"    已附加参考图: {len(ref_names)} 张")

    best = None
    attempts = max(1, a.retry)
    if a.engine == "qwen":
        # Qwen-Image-Edit 个别随机种子会把平滑背景整片生成成雪花噪点，至少给两次机会
        attempts = max(2, attempts)
        source_image = _load_rgb_image(src)
    for i in range(attempts):
        seed = a.seed + i if a.seed >= 0 else int(time.time() * 1000) % 2**31 + i
        if a.engine == "qwen":
            instruction = qwen_figure_instruction(a.prompt, a.style)
            if ref_names:
                instruction = ("The first image is the main reference; the following images are additional "
                               "references for character/outfit/color details. Follow the main image for pose, "
                               "composition and camera angle. " + instruction)
            wf = build_qwen_figure_edit_wf(image_name, instruction, seed,
                                           unique_prefix("fig_qwen"), ref_names)
        else:
            wf = build_img2img_wf(a.model, pos, neg, seed,
                                  a.width, a.height, a.steps, denoise, image_name)
            if a.structure == "canny":
                apply_sdxl_canny(wf, control_name, a.control_strength)
            save_node = "9" if a.model == "pony" else "70"
            wf[save_node]["inputs"]["filename_prefix"] = unique_prefix("fig_i2i")
        pid = api_post("/prompt", {"prompt": wf}).get("prompt_id")
        if not pid:
            print("[!] 提交失败")
            return 1
        entry = wait_done(pid, 1800, "图生图")
        files = collect_files(entry)
        if not files:
            print("[!] 无输出")
            return 1
        fn, sub, _ = files[0]
        p = verified_output_path(fn, sub)
        print(f"[✓] {p}  (seed={seed})")

        if a.engine == "qwen":
            ratio, detail = flat_noise_ratio(source_image, _load_rgb_image(p))
            print(f"    质量检测：平坦区域噪点 ×{ratio:.2f}（{detail}）", flush=True)
            if ratio > 80.0 and i < attempts - 1:
                print("    · 检测到异常噪点，换随机种子重试……", flush=True)
                continue
            if ratio > 80.0:
                print(f"[!] 提示：本次结果可能仍有噪点（×{ratio:.2f}），建议重试。", flush=True)
            best = (ratio, p)
            break

        if not a.check_bg:
            best = (0.0, p)
            break

        # 背景检测（与 cmd_img 相同逻辑）
        score = 0.0
        ok = True
        ratio, verdict = check_background_cleanliness(p, a.bg_limit)
        print(f"    {verdict}")
        if ratio is not None:
            score += ratio
            if ratio > a.bg_limit:
                ok = False
        asym, v2 = check_front_view(p, a.asym_limit)
        print(f"    {v2}")
        if asym is not None:
            score += asym * 2
            if asym > a.asym_limit:
                ok = False

        if best is None or score < best[0]:
            best = (score, p)
        if ok:
            break
        if i < attempts - 1:
            print(f"    · 不达标，换 seed 重抽 ({i+2}/{attempts}) ...")
            continue
        if best and best[1] != p:
            print(f"    · 采用历次最佳: {best[1]} (评分 {best[0]:.3f})")
        break

    _LAST_PICKED = best[1] if best else p
    return 0


def check_background_cleanliness(src, max_lowsat_ratio=0.30):
    """检测源图里是否存在会影响 3D 重建的背景干扰。

    ┌────────────────────────────────────────────────────────────┐
    │ 实测结论（16 组对照实验 + 11 张实测样本验证）：            │
    │ **只有「灰色背景板」能在出图阶段可靠检出**。              │
    │  判据 = 低饱和（S<0.18）且中明度（0.15<V<0.80）像素占比，   │
    │  11/11 全部判对（干净图 0.9-2.4%，脏图 23.7-87.4%）。      │
    │                                                            │
    │ 「背景文字」和「背景圆形色块」**故意不在这里检测** ——      │
    │  它们与角色身上的高饱和区域（红领结/红瞳/红鞋）颜色完全相同，│
    │  纯颜色分析无法区分（试过 rembg 掩膜、边缘连通、离散块计数，│
    │  都会误判干净图）。                                        │
    │  → 交给**背景分离阶段**用「连通域 + 面积过滤」解决。        │
    └────────────────────────────────────────────────────────────┘

    返回 (ratio, verdict) —— ratio 是低饱和灰区占比。
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None, "（缺 numpy，跳过检查）"
    try:
        im = Image.open(src).convert("RGB")
        a = np.array(im).astype(np.float32) / 255.0
        mx = a.max(axis=2)
        mn = a.min(axis=2)
        sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)

        # 低饱和灰区 = 影棚背景板
        lowsat = (sat < 0.18) & (mx > 0.15) & (mx < 0.80)
        low_ratio = float(lowsat.mean())

        # 附带一个宽松提示：背景区（非角色）里的高饱和占比，仅作参考不改判定
        strong_all = (sat > 0.45) & (mx < 0.92)
        edge_bg = _edge_connected_mask(strong_all, a.shape[:2])
        hint = ""
        if edge_bg is not None:
            bg_sat_ratio = float((strong_all & edge_bg).mean())
            if bg_sat_ratio > 0.05:
                hint = f"，背景区另有高饱和色块 {bg_sat_ratio:.1%}（文字/图案，靠背景分离清理）"

        if low_ratio > max_lowsat_ratio:
            verdict = (f"⚠ 检出灰色背景板！低饱和灰区占 {low_ratio:.1%}"
                       f"（阈值 {max_lowsat_ratio:.0%}）—— 建议换 seed 重出图{hint}")
        else:
            verdict = f"✓ 无灰色背景板（低饱和灰区 {low_ratio:.1%}）{hint}"
        return low_ratio, verdict
    except Exception as e:
        return None, f"（检查失败：{type(e).__name__}）"


def check_front_view(src, max_asymmetry=0.12):
    """检测角色是否「正面站立」—— 左右对称度。

    ★ 为什么重要：Hunyuan3D 对 3/4 侧身姿态的重建会丢腿。
      实测：正面站姿 → 双腿完整；3/4 侧身 → 只到裙子，后腿消失。

    判据：把图缩到 160×240 灰度，左右两半做镜像差。
      实测正面对称度 0.03-0.04，侧身 0.15-0.27，阈值 0.12。

    返回 (asymmetry, verdict)
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None, "（缺 numpy，跳过检查）"
    try:
        a = np.array(Image.open(src).convert("L").resize((160, 240)), dtype=float)
        left = a[:, :80]
        right = a[:, 80:][:, ::-1]
        asym = float(np.abs(left - right).mean() / 255.0)
        if asym > max_asymmetry:
            verdict = (f"⚠ 非正面姿态（左右不对称度 {asym:.3f} > {max_asymmetry}）—— "
                       f"3D 重建可能丢腿，建议换 seed 重出图")
        else:
            verdict = f"✓ 正面姿态（不对称度 {asym:.3f}）"
        return asym, verdict
    except Exception as e:
        return None, f"（检查失败：{type(e).__name__}）"


def _scattered_blob_ratio(strong_all, edge_bg, shape):
    """离散饱和块（文字笔画）的面积占比。

    文字特征：大量分散的小连通块。角色特征：1~2 个大块。
    判据：统计「不与边缘相连」且「面积占比 < 8%」的块，若数量 >= 6 则判定为文字。
    """
    try:
        import numpy as np
        from scipy import ndimage
        H, W = shape
        lab, n = ndimage.label(strong_all)
        if n == 0:
            return 0.0
        border = set()
        border.update(np.unique(lab[0, :]).tolist())
        border.update(np.unique(lab[-1, :]).tolist())
        border.update(np.unique(lab[:, 0]).tolist())
        border.update(np.unique(lab[:, -1]).tolist())
        border.discard(0)
        sizes = ndimage.sum(strong_all, lab, range(1, n + 1))
        total = float(strong_all.sum()) or 1.0
        scattered = 0
        for i, s in enumerate(sizes, start=1):
            if i in border:
                continue
            frac = s / total
            # 小块（笔画），且不是单个巨大的块
            if frac < 0.08:
                scattered += 1
        if scattered < 6:
            return 0.0
        # 散块总面积占比
        sc_area = sum(sizes[i - 1] for i in range(1, n + 1)
                      if i not in border and (sizes[i - 1] / total) < 0.08)
        return float(sc_area / total)
    except Exception:
        return 0.0


def _edge_connected_mask(strong, shape):
    """找出与画面边缘连通的强饱和像素（背景污染），返回布尔掩膜。

    角色是画面中央的孤立主体，不与边缘相连；
    背景里的文字 / 圆形色块则一路连到画面边缘。

    用 scipy.ndimage 做连通域标记 + 二分查找边界标签。
    没有 scipy 时返回 None（调用方退化到边缘条带法）。
    """
    try:
        import numpy as np
        from scipy import ndimage
    except ImportError:
        return None
    try:
        H, W = shape
        lab, n = ndimage.label(strong)
        if n == 0:
            return np.zeros((H, W), dtype=bool)
        # 收集边界上的标签
        border_labels = set()
        border_labels.update(np.unique(lab[0, :]).tolist())
        border_labels.update(np.unique(lab[-1, :]).tolist())
        border_labels.update(np.unique(lab[:, 0]).tolist())
        border_labels.update(np.unique(lab[:, -1]).tolist())
        border_labels.discard(0)
        if not border_labels:
            return np.zeros((H, W), dtype=bool)
        return np.isin(lab, list(border_labels))
    except Exception:
        return None


def _background_mask(src, W, H):
    """用 rembg 得到角色掩膜（True=角色）。失败返回 None。"""
    try:
        import io
        from rembg import remove, new_session
        from PIL import Image
        if not hasattr(_background_mask, "_sess"):
            _background_mask._sess = new_session("isnet-anime")
        with open(src, "rb") as f:
            data = f.read()
        out = remove(data, session=_background_mask._sess)
        img = Image.open(io.BytesIO(out)).convert("RGBA")
        if img.size != (W, H):
            img = img.resize((W, H))
        alpha = np.array(img.split()[-1]) if _HAS_NUMPY else None
        if alpha is None:
            return None
        return alpha > 32
    except Exception:
        return None


def _largest_saturated_blob(strong_bg, shape):
    """背景里最大高饱和连通块的面积占比（用于识别圆形色块）。"""
    try:
        import numpy as np
        H, W = shape
        if not strong_bg.any():
            return 0.0
        # 用行投影近似：每一行里高饱和像素的最大连续段
        best_area = 0
        rows_with = strong_bg.any(axis=1)
        n_rows = int(rows_with.sum())
        if n_rows == 0:
            return 0.0
        # 找一个代表行，量它的宽度
        mid = int(np.where(rows_with)[0][n_rows // 2])
        row = strong_bg[mid]
        # 最长连续段
        best = cur = 0
        for v in row:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        # 面积估算：宽度 × 覆盖高度
        area = (best / W) * (n_rows / H)
        # 只有当它占背景相当比例、且宽度不小，才认为是大色块
        if best < W * 0.12:
            return 0.0
        return float(area)
    except Exception:
        return 0.0


def _component_ratio(a, b):
    """b 相对 a 少了多少（0 表示完全一致）。"""
    pa = a.tobytes()
    pb = b.tobytes()
    n = len(pa)
    if n == 0:
        return 0.0
    # 只比较前 4 个字节做粗略判断开销小；真正对比逐像素
    same = sum(1 for i in range(0, n) if pa[i] == pb[i])
    return 1.0 - same / float(n)


def _keep_largest_components(mask, keep=3, drop_flat_ratio=0.0):
    """连通域标记：只保留面积最大的 keep 个连通块，其余（背景碎片）置黑。

    ★ 额外过滤「又大又扁」的块 —— 背景板/色块在掩膜里往往是宽而扁的，
      而角色是竖长的。drop_flat_ratio > 0 时，宽高比超过该值的块直接丢弃。

    mask: PIL "L" 模式二值图（255=前景）
    """
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        arr = np.array(mask) > 0
    except Exception:
        return None
    if not arr.any():
        return None
    H, W = arr.shape

    lab = None
    try:
        from scipy import ndimage
        lab, n = ndimage.label(arr)
        sizes = ndimage.sum(arr, lab, range(1, n + 1))
        boxes = ndimage.find_objects(lab)
        comps = []
        for i in range(n):
            sl = boxes[i]
            if sl is None:
                continue
            bh = sl[0].stop - sl[0].start
            bw = sl[1].stop - sl[1].start
            comps.append((int(sizes[i]), i + 1, bh, bw))
    except ImportError:
        comps = None

    if comps is None:
        # 无 scipy：退化到纯 Python 洪泛
        comps = []
        labels = np.zeros((H, W), dtype=np.int32)
        cur = 0
        for sy in range(H):
            for sx in range(W):
                if not arr[sy, sx] or labels[sy, sx]:
                    continue
                cur += 1
                stack = [(sy, sx)]
                labels[sy, sx] = cur
                size = 0
                while stack:
                    y, x = stack.pop()
                    size += 1
                    if y > 0 and arr[y - 1, x] and not labels[y - 1, x]:
                        labels[y - 1, x] = cur; stack.append((y - 1, x))
                    if y < H - 1 and arr[y + 1, x] and not labels[y + 1, x]:
                        labels[y + 1, x] = cur; stack.append((y + 1, x))
                    if x > 0 and arr[y, x - 1] and not labels[y, x - 1]:
                        labels[y, x - 1] = cur; stack.append((y, x - 1))
                    if x < W - 1 and arr[y, x + 1] and not labels[y, x + 1]:
                        labels[y, x + 1] = cur; stack.append((y, x + 1))
                comps.append((size, cur, 1, 1))
        keep_arr = np.isin(labels, [c[1] for c in sorted(comps, reverse=True)[:keep]])
        from PIL import Image
        return Image.fromarray((keep_arr * 255).astype("uint8"), mode="L")

    # 排序 + 形状过滤
    comps.sort(reverse=True)
    selected = []
    for size, lid, bh, bw in comps:
        if drop_flat_ratio > 0 and size > 0:
            # 宽高比：宽 >> 高 → 扁块（背景板/色带）；角色是竖长的
            ratio = bw / max(bh, 1)
            if ratio > drop_flat_ratio and size < 0.25 * comps[0][0]:
                continue   # 丢弃：又扁又相对不大
        selected.append(lid)
        if len(selected) >= keep:
            break
    if not selected:
        selected = [comps[0][1]]
    keep_arr = np.isin(lab, selected)
    from PIL import Image
    return Image.fromarray((keep_arr * 255).astype("uint8"), mode="L")


def _drop_color_blobs(img, mask, sat_thresh=0.45, gb_max=0.28, gb_tol=0.06,
                      purity_max=0.06, blob_min_frac=0.020, keep_min_frac=0.25):
    """★ 剔除 mask 中与角色主体分离的高饱和色块（背景红圆盘等）。

    问题：isnet-anime 会把背景里高饱和的圆形色块（红圆盘）也当前景抠出来，
    而且它紧贴角色、在 mask 里和角色粘连，「是否分离」「是否在边缘」都判不准
    （实测角色躯干宽度被圆盘撑到 87% 图宽，参照物本身被污染）。

    ★ 判据（四轮实测后确定，用**颜色指纹**而非形状）：
      1. **绿蓝通道双低且相等** —— 纯暗红（红圆盘）的 G、B 都接近 0 且彼此
         几乎相等（实测 (0.62, 0.15, 0.17)）；而角色的红色装饰（领结）因为
         混入了白色高光，G、B 明显更高（实测 (0.64, 0.37, 0.40)）。
      2. **纯度高** —— 到块均色的平均 RGB 距离极小（实测 0.024-0.062），
         说明是纯色块；角色的装饰带有描边和渐变，纯度差得多（0.10+）。
      3. **面积够大** —— blob_min_frac 排除小装饰（红眼睛 0.03%、
         领结 0.34%）。

      ★ 关键实现要点：**不能只删「连通块本体」**。
        圆盘被角色切成左右两半，其余部分又被 rembg 判成背景，
        真正需要清掉的是「mask 内所有属于该纯色的像素」。
        实测：暗红目标像素 78,295（占前景 31%），而单个连通块只有 33,308。
        所以做法是：先定位大块拿到**颜色指纹**，再按指纹把全图同色像素
        一次性从 mask 里扣掉。

    img: PIL RGBA 原图（rembg 输出）
    mask: PIL "L" 二值图（255=前景）
    返回新的 PIL "L" mask，或 None（无可处理数据）
    """
    try:
        import numpy as np
        from scipy import ndimage
        from PIL import Image
    except ImportError:
        return None

    arr_img = np.array(img.convert("RGB")).astype(float) / 255.0
    arr_mask = np.array(mask) > 0
    H, W = arr_mask.shape
    total_px = H * W

    r, g, b = arr_img[:, :, 0], arr_img[:, :, 1], arr_img[:, :, 2]
    mx = arr_img.max(axis=2)
    mn = arr_img.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)

    # ★ 目标像素：mask 内 + 高饱和 + 绿蓝双低且相等（纯暗红/纯色背景块）
    low_gb = (g <= gb_max) & (b <= gb_max) & (np.abs(g - b) <= gb_tol)
    target = arr_mask & (sat > sat_thresh) & low_gb
    if target.sum() < 50:
        return mask

    lab, n = ndimage.label(target)
    if n == 0:
        return mask

    sizes = ndimage.sum(target, lab, range(1, n + 1))
    boxes = ndimage.find_objects(lab)

    removed = np.zeros_like(arr_mask)
    for i in range(n):
        if sizes[i] < total_px * blob_min_frac:
            continue  # 太小，是角色装饰（领结/眼睛）
        sl = boxes[i]
        if sl is None:
            continue
        blob = (lab == i + 1)
        px = arr_img[blob]
        mu = px.mean(axis=0)
        # ★ 纯度：到块均色的平均 RGB 距离
        purity = float(np.sqrt(((px - mu) ** 2).sum(axis=1)).mean())
        if purity > purity_max:
            continue  # 不是纯色块，是带渐变的角色区域
        # ★ 按颜色指纹一次性清除全图同色像素（不只连通块本体）
        #   阈值 0.16 覆盖抗锯齿过渡像素，实测能把残边一起清掉
        d = np.sqrt(((arr_img - mu) ** 2).sum(axis=2))
        same_color = (d <= 0.16) & arr_mask
        struct = ndimage.generate_binary_structure(2, 1)
        same_color = ndimage.binary_dilation(same_color, structure=struct,
                                            iterations=2)
        removed |= (same_color & arr_mask)
        bh = sl[0].stop - sl[0].start
        bw = sl[1].stop - sl[1].start
        print(f"    · 剔除背景色块: {int(sizes[i]):,} px ({sizes[i]/total_px:.1%})  "
              f"bbox {bw}x{bh}  均色=({mu[0]:.2f},{mu[1]:.2f},{mu[2]:.2f})  "
              f"纯度={purity:.3f}  同色清除 {int(same_color.sum()):,} px")

    if not removed.any():
        return mask

    new_arr = arr_mask & ~removed
    keep_frac = new_arr.sum() / max(arr_mask.sum(), 1)
    if keep_frac < keep_min_frac:
        print(f"    · 色块剔除后主体仅剩 {keep_frac:.0%}，放弃本次剔除")
        return mask
    return Image.fromarray((new_arr * 255).astype("uint8"), mode="L")


def _flatten_shading(src, dst, compress=0.20, blur=6.0):
    """★ 色调平坦化：把二次元平涂阴影压淡，消除 Hunyuan3D 的「蜂窝纹」。

    问题：二次元立绘的阴影是**色块**（cel shading）。Hunyuan3D 的形状生成器
    把明暗变化当成几何深度，在表面重建出「人字纹 / 蜂窝纹 / 拉丝纹」。
    实测：hq_clean 模型法线抖动>0.15 的边占 16.1%，肉眼看满身蜂窝。

    原理：
      1. 算低频亮度（强模糊）= 角色的整体立体感
      2. detail = 原亮度 - 低频亮度 = 平涂阴影 + 描边等局部明暗细节
      3. new = 低频 + detail * compress  → 按比例压缩局部明暗
         compress=1.0 等于原图；0.2 = 只保留 20% 的阴影对比

      这样**大尺度明暗保留**（角色仍有立体感，不是剪影），
      **局部阴影被压扁**（Hunyuan3D 没有明暗可以误当深度）。

    实测（compress=0.2）：局部明暗对比降 46%，角色依然完全清晰可辨。

    src/dst: 图片路径
    """
    try:
        import numpy as np
        from PIL import Image, ImageFilter
    except ImportError:
        return False
    try:
        img = Image.open(src).convert("RGB")
        arr = np.array(img).astype(float) / 255.0
        mx = arr.max(axis=2)
        fg = mx < 0.98          # 前景（非白）
        if fg.sum() < 100:
            return False

        gray_img = Image.fromarray((mx * 255).astype("uint8"))
        r = int(max(3, blur))
        low = np.array(gray_img.filter(ImageFilter.GaussianBlur(r))).astype(float) / 255.0

        detail = mx - low
        new_gray = low + detail * compress

        # 把明度变化按比例映射回 RGB，保留色相与饱和度
        ratio = np.where(mx > 1e-6, new_gray / np.maximum(mx, 1e-6), 1.0)
        out = arr * ratio[:, :, None]
        out = np.where(fg[:, :, None], out, 1.0)

        Image.fromarray((np.clip(out, 0, 1) * 255).astype("uint8")).save(dst)
        print(f"    · 色调平坦化：阴影压缩至 {compress:.0%}（消除蜂窝纹伪影）")
        return True
    except Exception as e:
        print(f"    ! 色调平坦化失败（{type(e).__name__}: {e}），沿用原图")
        return False


def isolate_background(src, dst, alpha_thresh=32, margin=0.08, long_side=1024,
                      model="isnet-anime", keep_components=3, fill_holes=True,
                      drop_flat_ratio=2.5, drop_color_blobs=True):
    """用 rembg 抠掉背景，把角色放到纯白底上。

    为什么必须有这一步：Hunyuan3D 会把**整张图**都重建成几何体。
    如果 Pony 在角色背后画了机甲/武器/场景，3D 结果就会是一坨含背景的乱块
    （实测：带巨大机甲背景的立绘 → 3D 出来是一块 1.95×1.95×0.13 的平板）。

    六个关键处理，缺一不可（按顺序）：
      1. rembg 抠图。**优先用 isnet-anime**（针对二次元角色训练），
         u2net 对动漫插画会把「角色身后的深色幕布」一起抠成前景。
      2. **alpha 阈值二值化** —— rembg 会给背景残留一圈低置信度灰影，
         Hunyuan3D 会把这圈残影重建成一整面墙（实测角色右侧多出一块板）
      3. **连通域主体提取** —— 只保留面积最大的 N 个连通块，
         把与角色分离的背景碎片（幕布、地面、台座）剔除
      4. ★ **高饱和色块剔除** —— isnet-anime 会把背景里的高饱和圆形色块
         （红圆盘等）误判为前景，导致 Hunyuan3D 把它重建成背后的巨物。
         通过检测 mask 中高饱和像素的分布，剔除与角色主体颜色不连续的大块
      5. **空洞填充** —— 角色衣服上的镂空会被 rembg 误判成背景而挖穿，
         用二值形态学闭运算补回来，避免 3D 出现贯穿的洞
      6. **按角色包围盒裁切 + 留白**，去掉边缘空场，提升 3D 有效分辨率

    rembg 不可用时返回 False，调用方继续用原图。
    """
    try:
        from rembg import remove, new_session
        from PIL import Image, ImageFilter
        import io
    except ImportError:
        print("    (未安装 rembg，跳过背景分离；pip install rembg onnxruntime)")
        return False
    try:
        # isnet-anime 首次使用会自动下载（~176MB），之后走本地缓存
        if not hasattr(isolate_background, "_sessions"):
            isolate_background._sessions = {}
        if model not in isolate_background._sessions:
            print(f"    载入背景分离模型 ({model}) ...")
            isolate_background._sessions[model] = new_session(model)
        session = isolate_background._sessions[model]
        with open(src, "rb") as f:
            data = f.read()
        out = remove(data, session=session)
        img = Image.open(io.BytesIO(out)).convert("RGBA")
        alpha = img.split()[-1]

        # 2) 阈值二值化，抹掉低置信度残影
        mask = alpha.point(lambda a: 255 if a > alpha_thresh else 0)
        mask = mask.filter(ImageFilter.MinFilter(3))   # 轻微腐蚀，收紧边缘
        bbox = mask.getbbox()
        if not bbox:
            return False

        # 3) 连通域主体提取：只保留最大的若干个连通块
        if keep_components > 0:
            kept = _keep_largest_components(mask, keep_components,
                                           drop_flat_ratio=drop_flat_ratio)
            if kept is not None:
                if _component_ratio(mask, kept) < 0.999:
                    print(f"    · 连通域清理：剔除 {_component_ratio(mask, kept):.1%} 的背景碎片")
                mask = kept

        # 3.5) ★ 高饱和色块剔除：isnet-anime 会把背景红圆盘等误判为前景
        #   诊断数据：分离后的图有 15.6% 高饱和红色，其中 3.8% 在边缘区域
        #   两个最大红色连通块各占 5.5% 和 4.4% —— 这就是被当角色的背景色块
        #   策略：在 mask 的边缘区域（外 20%）检测高饱和像素，如果某区域
        #   的高饱和占比超过阈值且与主体中心距离远，则从 mask 中剔除
        if drop_color_blobs:
            new_mask = _drop_color_blobs(img, mask)
            if new_mask is not None:
                removed = _component_ratio(mask, new_mask)
                if removed > 0.001:
                    print(f"    · 色块剔除：移除 {removed:.1%} 的背景高饱和色块")
                mask = new_mask

        # 4) 空洞填充（闭运算）：补回衣服镂空，避免 3D 出现贯穿的洞
        if fill_holes:
            mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))

        bbox = mask.getbbox()
        if not bbox:
            return False

        # 3) 裁切到角色包围盒，留 8% 边距
        W, H = img.size
        x0, y0, x1, y1 = bbox
        mx, my = int((x1 - x0) * margin), int((y1 - y0) * margin)
        x0 = max(0, x0 - mx); y0 = max(0, y0 - my)
        x1 = min(W, x1 + mx); y1 = min(H, y1 + my)
        img = img.crop((x0, y0, x1, y1))
        mask = mask.crop((x0, y0, x1, y1))

        # 缩放到长边 long_side（3D 输入分辨率越高细节越好，但别超过 1536）
        w, h = img.size
        s = long_side / float(max(w, h))
        if s < 1.0:
            nw, nh = max(1, int(w * s)), max(1, int(h * s))
            img = img.resize((nw, nh), Image.LANCZOS)
            mask = mask.resize((nw, nh), Image.LANCZOS)

        # 合成到纯白底
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, (0, 0), mask)
        bg.convert("RGB").save(dst)
        print(f"    ✓ 角色区域 {bg.size[0]}×{bg.size[1]}")
        return True
    except Exception as e:
        print(f"    ! 背景分离失败（{type(e).__name__}: {e}），沿用原图")
        return False


def prepare_3d_square(src, dst):
    """等比填充正方形，避免 CLIP 中心裁切竖幅图的头和脚。"""
    from PIL import Image, ImageOps
    with Image.open(src) as image:
        image = ImageOps.exif_transpose(image)
        image.load()
        rgba = image.convert('RGBA')
        side = max(rgba.size)
        canvas = Image.new('RGBA', (side, side), (255, 255, 255, 255))
        offset = ((side - rgba.width) // 2, (side - rgba.height) // 2)
        canvas.alpha_composite(rgba, offset)
        canvas.convert('RGB').save(dst, 'PNG')
        print(f"    完整画面填充为正方形: {rgba.width}x{rgba.height} → {side}x{side}", flush=True)


def _parse_mv_refs(value):
    """解析 ``--mv-refs left=path back=path``；返回 {view: abs_path}。"""
    mapping = {}
    for spec in (value or []):
        text = str(spec).strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"--mv-refs 格式应为 view=path，收到: {text}")
        view, path = text.split("=", 1)
        view = view.strip().lower()
        path = os.path.abspath(os.path.expanduser(path.strip()))
        if view not in ("front", "left", "back", "right"):
            raise ValueError("多视图方位无效: " + view +
                             "（可用: front,left,back,right）")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"多视图参考图不存在: {path}")
        if path in mapping.values():
            raise ValueError(f"同一张图不能同时充当多个方位: {path}")
        if view in mapping:
            raise ValueError(f"多视图方位重复: {view}")
        mapping[view] = path
    return mapping


def _prepare_mv_conditioning(a, main_uploaded, main_prepared, scratch):
    """把用户提供的多视图图处理/上传成 Hunyuan 多视图条件。

    主图始终是 front 一致性锚点；用户可用 ``--mv-refs front=...`` 覆盖。
    其它方位默认也做背景分离 + 白底正方形，避免 Qwen 输出的轻微背景
    被当成 3D 结构。只返回 2 个及以上方位的映射，否则返回 None。
    """
    requested = _parse_mv_refs(getattr(a, "mv_refs", None))
    if not requested:
        return None
    if len(requested) < 2:
        raise ValueError("--mv-refs 至少需要 2 个方位（如 left=... back=...）；"
                         "单图重建请不要传该参数")
    paths = dict(requested)
    if "front" not in paths:
        paths["front"] = main_prepared
    prepared = {}
    for view in ("front", "left", "back", "right"):
        if view not in paths:
            continue
        if view == "front" and os.path.abspath(paths["front"]) == \
                os.path.abspath(main_prepared):
            prepared[view] = main_uploaded
            print(f"    ✓ 多视图 front（主图锚点）: {main_uploaded}", flush=True)
            continue
        src = paths[view]
        if not getattr(a, "no_isolate", False):
            iso = os.path.join(scratch, f"mv_{view}_iso.png")
            print(f"[*] 多视图 {view} 背景分离 ...", flush=True)
            if not isolate_background(src, iso, model=getattr(a, "iso_model", "isnet-anime"),
                                      keep_components=getattr(a, "iso_components", 3),
                                      drop_color_blobs=True, drop_flat_ratio=2.5):
                raise RuntimeError(f"多视图 {view} 背景分离失败: {src}")
            src = iso
        square = os.path.join(scratch, f"mv_{view}.png")
        prepare_3d_square(src, square)
        name = upload_image(square).get("name")
        if not name:
            raise RuntimeError(f"多视图 {view} 上传失败: {square}")
        prepared[view] = name
        print(f"    ✓ 多视图 {view}: {name}", flush=True)
    if len(prepared) < 2:
        return None
    return prepared


def _cmd_model_local(a):
    global _LAST_GLB, _LAST_REFERENCE_3D
    _LAST_GLB = None
    _LAST_REFERENCE_3D = None
    img = a.image
    if not os.path.exists(img):
        print(f"[!] 图片不存在: {img}")
        return 1
    # 背景分离：Hunyuan3D 会把背景里的大件物体也重建成几何体
    if not a.no_isolate:
        iso = os.path.join(os.path.dirname(os.path.abspath(img)),
                           "_iso_" + os.path.basename(img))
        print("[*] 背景分离（只保留角色）...")
        if not isolate_background(img, iso, model=a.iso_model,
                                  keep_components=a.iso_components,
                                  drop_color_blobs=True, drop_flat_ratio=2.5):
            print("[!] 背景分离失败，已停止生成；请检查依赖/模型或使用已去背景图并显式跳过分离")
            return 1
        img = iso
        print(f"    ✓ {iso}")
    # ★ 色调平坦化：压缩 cel shading 阴影，消除 Hunyuan3D 蜂窝纹
    #   在背景分离之后、上传之前执行，确保送入 3D 的是「明暗干净」的图
    if not getattr(a, 'no_flatten', False):
        flat = os.path.join(os.path.dirname(os.path.abspath(img)),
                            "_flat_" + os.path.basename(img))
        print("[*] 色调平坦化（消除蜂窝纹）...")
        if _flatten_shading(img, flat, compress=getattr(a, 'flatten_compress', 0.20)):
            img = flat
            print(f"    ✓ {flat}")
    print(f"[*] 3D 输入准备（保留完整画面）: {os.path.basename(img)} ...")
    with tempfile.TemporaryDirectory(prefix="figure_3d_") as scratch:
        prepared = os.path.join(scratch, "figure_3d_input_" + uuid.uuid4().hex + ".png")
        prepare_3d_square(img, prepared)
        _gate_3d_input(a, prepared)
        up_name = upload_image(prepared).get("name")
        # 多视图条件：必须在 scratch 关闭前完成处理与上传，ComfyUI 会保存副本
        mv_images = _prepare_mv_conditioning(a, up_name, prepared, scratch)
        if mv_images:
            print(f"[*] 多视图重建条件: " + ", ".join(
                f"{k}={v}" for k, v in mv_images.items()), flush=True)
        # 暂存到输出目录：临时目录退出即删，参考图必须活到 STL 阶段
        staged = os.path.join(OUT, "_3d_input_" + uuid.uuid4().hex + ".png")
        shutil.copy2(prepared, staged)
    if not up_name:
        raise RuntimeError("上传图生3D输入失败")
    print(f"[*] 图生3D  resolution={a.resolution} steps={a.steps3d} "
          f"octree={getattr(a, 'octree_res', 512)} faces<={a.faces}"
          + (f"  multiview={','.join(mv_images)}" if mv_images else ""), flush=True)
    wf = build_3d_wf(up_name, a.steps3d, a.resolution, threshold=a.threshold,
                      prefix=unique_prefix(a.prefix), octree_resolution=getattr(a, 'octree_res', 512),
                      faces=a.faces, crease=a.crease,
                      uv_resolution=a.uv_resolution, weld_distance=a.weld_distance,
                      do_uv=a.uv, do_preview=not a.no_preview,
                      remesh_res=a.remesh_res, smooth_iters=a.smooth_iters,
                      band=a.remesh_band, project_back=a.project_back,
                      high_precision=getattr(a, 'remesh_solid', False) and not a.low_precision,
                      mv_images=mv_images)
    pid = api_post("/prompt", {"prompt": wf}).get("prompt_id")
    if not pid:
        print("[!] 提交失败")
        return 1
    entry = wait_done(pid, 3600, "图生3D")
    files = collect_files(entry)
    if not files:
        print("[!] 无输出")
        return 1
    glb = None
    for fn, sub, typ in files:
        p = verified_output_path(fn, sub)
        sz = os.path.getsize(p) / 1e6
        print(f"[✓] {fn}  ({typ}, {sz:.2f} MB)\n    {p}")
        if fn.lower().endswith(".glb") and glb is None:
            glb = p
    _LAST_GLB = glb
    if glb:
        _persist_3d_reference(staged, glb)
        try:
            os.remove(staged)
        except OSError:
            pass
    return 0


# ---------------------------------------------------------------- Meshy 云 3D
def _meshy_settings(a):
    r"""合并 CLI 参数与 E:\AI\meshy_config.json 配置。"""
    import meshy_client
    cfg = getattr(meshy_client, "CONFIG", {}) or {}
    ai_model = getattr(a, "meshy_model", None) or cfg.get("ai_model") or meshy_client.DEFAULT_MODEL
    geometry = getattr(a, "meshy_geometry", "standard") or "standard"
    desensitize = getattr(a, "meshy_desensitize", None)
    if desensitize is None:
        desensitize = bool(cfg.get("desensitize_before_upload", False))
    return {
        "ai_model": ai_model,
        "geometry": geometry,
        "desensitize": bool(desensitize),
        "strength": getattr(a, "meshy_strength", "auto") or "auto",
        "poly": int(getattr(a, "meshy_poly", 0) or cfg.get("target_polycount", 300000) or 0),
        "texture": bool(getattr(a, "meshy_texture", False)),
    }


def _prepare_3d_source(a, src_path, scratch_dir):
    """3D 输入预处理：背景分离 + 正方形白底填充 + 输入门禁。

    旧实现在这里把 drop_color_blobs / drop_flat_ratio 全部关掉、却保留 3 个连通块，
    与本地 Hunyuan 路径的默认清理参数不一致 —— 同一张图走云端和走本地会得到
    完全不同的 3D 输入。这里统一成与本地一致的清理强度，并在上传前做量化门禁。
    """
    proc = src_path
    if not getattr(a, "no_isolate", False):
        iso = os.path.join(scratch_dir, "iso.png")
        print("[*] 背景分离（只保留角色）...", flush=True)
        try:
            if isolate_background(proc, iso, model=getattr(a, "iso_model", "isnet-anime"),
                                  keep_components=getattr(a, "iso_components", 3),
                                  drop_color_blobs=True, drop_flat_ratio=2.5):
                proc = iso
                print(f"    ✓ {iso}", flush=True)
            else:
                print("    ! 背景分离失败，直接使用原图", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"    ! 背景分离异常（{exc}），直接使用原图", flush=True)
    prepared = os.path.join(scratch_dir, "meshy_input.png")
    prepare_3d_square(proc, prepared)
    print(f"    ✓ 3D 输入: {prepared}", flush=True)

    # ★ 3D 输入门禁：图生 3D 会把整张图（含场景）重建成几何，
    #   躺姿 / 带沙发 / 主体贴边的输入，后处理无论如何都救不回来。
    _gate_3d_input(a, prepared)
    return prepared


def _gate_3d_input(a, prepared):
    """对**实际送进 3D 重建的图**做量化检查；不合格直接终止，不浪费算力/积分。"""
    try:
        import mesh_fidelity
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 3D 输入门禁不可用（{exc}），跳过检查", flush=True)
        return True
    try:
        ok, metrics, reasons, warnings = mesh_fidelity.validate_3d_input(
            prepared, max_asymmetry=float(getattr(a, "input_asym_limit", 0.12)))
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 3D 输入门禁异常（{exc}），跳过检查", flush=True)
        return True
    print("[*] 3D 输入门禁: " + ", ".join(
        f"{k}={v}" for k, v in metrics.items()
        if k in ("mask_method", "foreground_ratio", "edge_contact_ratio",
                 "front_asymmetry", "lowsat_bg_ratio")), flush=True)
    for w in warnings:
        print(f"    ! {w}", flush=True)
    if ok:
        print("    ✓ 输入合格", flush=True)
        return True
    for r in reasons:
        print(f"    ✗ {r}", flush=True)
    if getattr(a, "allow_bad_3d_input", False):
        print("    ! --allow-bad-3d-input 已指定，强制继续（结果大概率不可用）", flush=True)
        return True
    print("[✗] 3D 输入不合格，已中止。请换成「正面站立 / 纯白底 / 无场景道具」的"
          "角色图再重建；或在明确接受风险时加 --allow-bad-3d-input。", flush=True)
    raise SystemExit(2)


def _persist_3d_reference(prepared, glb_path):
    """把实际 3D 输入图复制到 GLB 旁边，供 convert_3d.py 自动发现。"""
    global _LAST_REFERENCE_3D
    if not prepared or not glb_path or not os.path.isfile(prepared):
        return None
    dest = os.path.splitext(glb_path)[0] + "_3d_input.png"
    try:
        shutil.copy2(prepared, dest)
        _LAST_REFERENCE_3D = dest
        print(f"    ✓ 参考图已随模型落盘: {dest}", flush=True)
        return dest
    except Exception as exc:  # noqa: BLE001
        print(f"    ! 参考图落盘失败（{exc}），STL 阶段将退回旧启发式", flush=True)
        return None


def cmd_model_meshy(a):
    """Meshy 云端图生3D：可选“上传前脱敏 → 生成 → 本地贴图还原”。"""
    global _LAST_GLB, _LAST_ENGINE_USED, _LAST_REFERENCE_3D
    _LAST_GLB = None
    _LAST_REFERENCE_3D = None
    if not os.path.exists(a.image):
        print(f"[!] 图片不存在: {a.image}")
        return 1
    try:
        import meshy_client
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 无法加载 meshy_client.py：{exc}")
        return 1
    try:
        balance_before = meshy_client.balance()
        print(f"[*] Meshy 剩余积分: {balance_before}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 连接 Meshy 失败：{exc}")
        print("    检查：网络是否可达 api.meshy.ai、MESHY_API_KEY / meshy_config.json 是否正确")
        return 1
    settings = _meshy_settings(a)
    print(f"[*] Meshy 图生3D  model={settings['ai_model']}  geometry={settings['geometry']}  "
          f"texture={settings['texture']}  desensitize={settings['desensitize']}", flush=True)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="meshy_3d_") as scratch:
        prepared = _prepare_3d_source(a, a.image, scratch)
        used_desensitize = False
        if settings["desensitize"]:
            clean = os.path.join(scratch, "meshy_safe.png")
            print(f"[*] 上传前脱敏（strength={settings['strength']}）...", flush=True)
            try:
                ok, info = _desensitize_image(prepared, clean, strength=settings["strength"])
            except Exception as exc:  # noqa: BLE001
                ok, info = False, str(exc)
            if ok and os.path.isfile(clean):
                prepared = clean
                used_desensitize = True
                print(f"    ✓ {info}", flush=True)
            else:
                print(f"    ! 脱敏失败（{info}），将上传未脱敏图（可能被审核拒绝）", flush=True)
        glb_path, task = meshy_client.image_to_3d(
            prepared, out_dir=OUT, ai_model=settings["ai_model"],
            geometry_resolution=settings["geometry"], should_texture=settings["texture"],
            target_polycount=settings["poly"],
            prefix=unique_prefix("fig_meshy"), timeout=1800)
        # 实际上传的那张图必须与模型一起落盘，STL 阶段才能做保真校验
        _persist_3d_reference(prepared, glb_path)
    final_glb = glb_path
    if used_desensitize:
        restored = os.path.splitext(glb_path)[0] + "_restored.glb"
        print("[*] 把原图正面贴图还原到 Meshy 模型（背面/侧面为拉伸投影）...", flush=True)
        rc = subprocess.call([PY, os.path.join(HERE, "restore_texture.py"),
                              glb_path, a.image, restored])
        if rc == 0 and os.path.isfile(restored):
            final_glb = restored
            print("    ✓ 已还原敏感外观（仅贴图，几何仍按脱敏版生成）", flush=True)
        else:
            print("    ! 贴图还原失败，保留 Meshy 原始模型", flush=True)
    try:
        balance_after = meshy_client.balance()
        print(f"[*] Meshy 积分: {balance_before} → {balance_after}"
              f"（本次消耗 {balance_before - balance_after:.0f}）", flush=True)
    except Exception:  # noqa: BLE001
        pass
    _LAST_GLB = final_glb
    _LAST_ENGINE_USED = "meshy"
    print(f"[✓] Meshy 3D 模型: {final_glb}  ({os.path.getsize(final_glb)/1e6:.2f} MB)", flush=True)
    return 0


def cmd_model_meshy_mv(a):
    """Meshy 官方多视图：image-to-image 生成侧/背视图 → Multi-Image to 3D。"""
    global _LAST_GLB, _LAST_ENGINE_USED, _LAST_REFERENCE_3D
    _LAST_GLB = None
    _LAST_REFERENCE_3D = None
    if not os.path.isfile(a.image):
        print(f"[!] 图片不存在: {a.image}")
        return 1
    try:
        import meshy_client
        balance_before = meshy_client.balance()
        print(f"[*] Meshy 剩余积分: {balance_before}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 连接 Meshy 失败：{exc}")
        return 1
    settings = _meshy_settings(a)
    if settings.get("desensitize"):
        print("[!] Meshy 多视图暂不支持脱敏后贴图还原；本次忽略 meshy_config 中的 "
              "desensitize_before_upload，改用原始参考图", flush=True)
    # Multi-Image to 3D 不支持 4k；2k 是该接口的最细档。
    geometry = "2k" if settings["geometry"] in ("2k", "4k") else "standard"
    # 复用用户给的多视图（front 缺省用主图锚定），避免每次重复扣 3 积分。
    reuse_views = []
    try:
        mv = _parse_mv_refs(getattr(a, "mv_refs", None))
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 多视图参数无效：{exc}", flush=True)
        return 1
    if mv:
        if "front" not in mv:
            mv["front"] = os.path.abspath(a.image)
        reuse_views = [mv[k] for k in ("front", "left", "back", "right") if k in mv]
        if len(reuse_views) < 2:
            print("[!] Meshy 多视图至少需要 2 个方位", flush=True)
            return 1
        print(f"[*] 复用多视图参考: {len(reuse_views)} 张（跳过 image-to-image）", flush=True)
    need = meshy_client.estimate_multiview_credits(
        geometry_resolution=geometry, generate_views=not reuse_views,
        should_texture=settings["texture"])
    if balance_before is not None and int(balance_before) < need:
        print(f"[!] Meshy 余额不足：当前 {balance_before}，本次至少需要约 {need} 积分", flush=True)
        return 1
    print(f"[*] Meshy 多视图图生3D  model={settings['ai_model']}  "
          f"geometry={geometry}  texture={settings['texture']}  预计≈{need}积分", flush=True)
    try:
        glb_path, view_paths, task = meshy_client.multiview_to_3d(
            a.image, out_dir=OUT, ai_model=settings["ai_model"],
            geometry_resolution=geometry, should_texture=settings["texture"],
            target_polycount=settings["poly"] if settings["texture"] else 0,
            prefix=unique_prefix("fig_meshy_mv"), timeout=1800,
            view_paths=reuse_views or None, min_balance=need,
            known_balance=balance_before)
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Meshy 多视图重建失败：{exc}", flush=True)
        return 1
    for path in view_paths:
        print(f"    ✓ 多视图参考: {path}", flush=True)
    _persist_3d_reference(a.image, glb_path)
    try:
        balance_after = meshy_client.balance()
        print(f"[*] Meshy 积分: {balance_before} → {balance_after}"
              f"（本次消耗 {balance_before - balance_after:.0f}）", flush=True)
    except Exception:  # noqa: BLE001
        pass
    _LAST_GLB = glb_path
    _LAST_ENGINE_USED = "meshy-mv"
    print(f"[✓] Meshy 多视图 3D 模型: {glb_path}  "
          f"({os.path.getsize(glb_path)/1e6:.2f} MB)", flush=True)
    return 0


def cmd_model(a):
    """3D 引擎分发：hunyuan（本地）/ meshy（云）/ meshy-mv（云多视图）/ auto。"""
    global _LAST_ENGINE_USED
    _LAST_ENGINE_USED = None
    engine = getattr(a, "engine", "hunyuan") or "hunyuan"
    if engine == "meshy":
        return cmd_model_meshy(a)
    if engine == "meshy-mv":
        return cmd_model_meshy_mv(a)
    if engine == "auto":
        print("[*] 引擎=auto：先跑本地 Hunyuan3D，失败再回退 Meshy", flush=True)
        try:
            rc = _cmd_model_local(a)
        except Exception as exc:  # noqa: BLE001
            print(f"[!] 本地 Hunyuan3D 异常：{exc}", flush=True)
            rc = 1
        if rc == 0:
            return 0
        print("[*] 本地 3D 失败，回退到 Meshy 云端……", flush=True)
        return cmd_model_meshy(a)
    _LAST_ENGINE_USED = "hunyuan"
    return _cmd_model_local(a)


# ---------------------------------------------------------------- 多视图测试图
MV_VIEWS = {
    "front":       ("正面", "front view (0°, camera directly facing the character, full body)"),
    "back":        ("背面", "back view (180°, camera behind the character showing the back, full body)"),
    "left":        ("左侧", "left profile view (90°, camera at the character's left side, full body)"),
    "right":       ("右侧", "right profile view (90°, camera at the character's right side, full body)"),
    "front_left":  ("左前45°", "front-left three-quarter view (45° between front and left side, full body)"),
    "front_right": ("右前45°", "front-right three-quarter view (45° between front and right side, full body)"),
    "back_left":   ("左后45°", "back-left three-quarter view (45° behind, showing the back-left side, full body)"),
    "back_right":  ("右后45°", "back-right three-quarter view (45° behind, showing the back-right side, full body)"),
}
MV_ANGLES = {
    "front": 0.0, "back": 180.0, "left": 90.0, "right": 270.0,
    "front_left": 45.0, "front_right": 315.0, "back_left": 135.0, "back_right": 225.0,
}
MV3D_REPAINT = (
    "The first image is the character reference. The second image is a rough 3D render of the SAME "
    "character seen from another camera angle. Repaint the second image to look exactly like the "
    "character in the first image — same face, hairstyle, hair color, outfit, accessories, body "
    "proportions, colors, materials and art style — while keeping the second image's pose, camera "
    "angle, framing and background composition EXACTLY unchanged. Do not change the pose, limb "
    "positions, silhouette or the prop; do not add or remove characters, text or watermark. "
)
MV_INSTRUCTION = (
    "The first image is the main reference. Reproduce the SAME character and the SAME scene: same pose "
    "and action, same limb positions, same hairstyle, hair color, face, outfit, accessories, body "
    "proportions, art style and colors. Only change the camera viewpoint to: {angle}. Show the complete "
    "subject from head to toe, centered, on a clean neutral studio background with soft even lighting. "
    "Do not change the character's posture and do not remove the prop (e.g. the swim ring); do not add "
    "other characters, props, text or watermark. If the reference is a photograph of a printed acrylic "
    "standee, depict it as a three-dimensional painted collectible figurine consistent with the "
    "reference instead of a flat print. "
)


def cmd_multiview(a):
    """按方位逐张生成多视图测试图（前/后/左/右 + 4 个斜侧位）。"""
    main = a.image
    if not os.path.isfile(main):
        print(f"[!] 图片不存在: {main}")
        return 1
    views = [str(v).strip() for v in (a.views or ["front"]) if str(v).strip()]
    unknown = [v for v in views if v not in MV_VIEWS]
    if unknown:
        print(f"[!] 无效的方位: {', '.join(unknown)}")
        print("    可用: " + ", ".join(MV_VIEWS))
        return 1
    ensure_comfyui_running()
    uploaded_main = upload_image(main).get("name")
    if not uploaded_main:
        print("[!] 主图上传失败")
        return 1
    ref_names = []
    for ref_path in (getattr(a, "refs", None) or []):
        if not os.path.isfile(ref_path):
            print(f"[!] 参考图不存在，已跳过: {ref_path}", flush=True)
            continue
        ref_name = upload_image(ref_path).get("name")
        if ref_name:
            ref_names.append(ref_name)
    if ref_names:
        print(f"[*] 一致性参考图: {len(ref_names)} 张", flush=True)
    base_text = (getattr(a, "prompt", "") or "").strip()
    extra_text = (getattr(a, "extra", "") or "").strip()
    print(f"[*] 多视图生成: {len(views)} 张  {views}", flush=True)
    from PIL import Image
    original = _load_rgb_image(main)
    ok_count = 0
    for view in views:
        label, angle = MV_VIEWS[view]
        print(f"[*] 生成 {label} ({view}) ...", flush=True)
        instruction = MV_INSTRUCTION.format(angle=angle)
        if ref_names:
            instruction += ("The following images are other views of the same character; keep the "
                            "character design consistent with them. ")
        if base_text:
            instruction += "Additional requirements: " + base_text + " "
        if extra_text:
            instruction += "Specific requirement for this view: " + extra_text + " "
        raw_image = None
        for attempt in range(2):
            seed = a.seed if (attempt == 0 and getattr(a, "seed", -1) >= 0) else random.randint(0, 2 ** 31 - 1)
            raw_path, raw_image = run_qwen_edit(uploaded_main, instruction, seed, ref_names)
            ratio, detail = flat_noise_ratio(original, raw_image)
            print(f"    质量检测：噪点 ×{ratio:.1f}（{detail}）", flush=True)
            if ratio > 300.0 and attempt == 0:
                print("    · 结果异常（可能整片噪点），换种子重试……", flush=True)
                continue
            break
        dest = os.path.join(OUT, unique_prefix(f"fig_mv_{view}") + ".png")
        raw_image.convert("RGB").save(dest)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            ok_count += 1
            print(f"[✓] 多视图结果: {view}:{dest}", flush=True)
        else:
            print(f"[!] 多视图保存失败: {view}", flush=True)
    print(f"[*] 多视图完成: {ok_count}/{len(views)} 张", flush=True)
    return 0 if ok_count else 1


def _glb_extents(glb_path):
    """用带 trimesh 的解释器读 GLB 包围盒尺寸。"""
    try:
        code = ("import sys, trimesh; m=trimesh.load(sys.argv[1], force='mesh'); "
                "print(' '.join(str(round(float(x), 6)) for x in m.extents))")
        out = subprocess.check_output([PY, "-c", code, glb_path], text=True, timeout=180).strip()
        return [float(x) for x in out.split()]
    except Exception:  # noqa: BLE001
        return None


def _find_blender():
    """找到 Blender 可执行文件。"""
    cands = []
    env = os.environ.get("BLENDER_EXE")
    if env:
        cands.append(env)
    try:
        import json as _json
        cfg_path = os.path.join(HERE, "meshy_config.json")
        if os.path.isfile(cfg_path):
            cfg = _json.load(open(cfg_path, encoding="utf-8"))
            if cfg.get("blender_exe"):
                cands.append(cfg["blender_exe"])
    except Exception:  # noqa: BLE001
        pass
    base = r"C:\Program Files\Blender Foundation"
    if os.path.isdir(base):
        for name in sorted(os.listdir(base), reverse=True):
            exe = os.path.join(base, name, "blender.exe")
            if os.path.isfile(exe):
                cands.append(exe)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def cmd_mv3d(a):
    """多视图（姿势锁定）：
    stage=build   从原图建 3D 粗模（本地 Hunyuan 免费 / Meshy 带贴图 30 积分）
    stage=render  用 Blender 无头渲染 N 个方位（同一模型旋转，姿势/道具完全不变）
    """
    stage = getattr(a, "stage", "build")
    if not os.path.isfile(a.image):
        print(f"[!] 图片不存在: {a.image}")
        return 1
    views = [str(v).strip() for v in (getattr(a, "views", None) or list(MV_VIEWS))]
    unknown = [v for v in views if v not in MV_VIEWS]
    if unknown:
        print(f"[!] 无效的方位: {', '.join(unknown)}")
        return 1

    if stage == "build":
        engine = getattr(a, "engine", "hunyuan") or "hunyuan"
        if engine == "meshy":
            return _mv3d_build_meshy(a)
        return _mv3d_build_hunyuan(a)

    if stage == "render":
        glb = getattr(a, "glb", None)
        if not glb or not os.path.isfile(glb):
            print("[!] 缺少 3D 模型：请先用 --stage build 生成，或传 --glb 模型路径")
            return 1
        blender = _find_blender()
        if not blender:
            print("[!] 找不到 Blender（需要它来渲染 8 方位）。")
            print("    安装 Blender 或在 meshy_config.json 里配置 blender_exe 路径")
            return 1
        size = int(getattr(a, "size", 1024) or 1024)
        import tempfile
        with tempfile.TemporaryDirectory(prefix="mv3d_render_") as scratch:
            cmd = [blender, "--background", "--factory-startup",
                   "--python", os.path.join(HERE, "render_views.py"), "--",
                   "--glb", glb, "--out_dir", scratch,
                   "--views", ",".join(views), "--size", str(size)]
            print(f"[*] Blender 渲染 {len(views)} 个方位 ...", flush=True)
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            except subprocess.TimeoutExpired:
                print("[!] Blender 渲染超时")
                return 1
            if proc.returncode != 0:
                print("[!] Blender 渲染失败：")
                print((proc.stderr or proc.stdout or "")[-1500:])
                return 1
            ok = 0
            for view in views:
                src_png = os.path.join(scratch, f"clay_{view}.png")
                if not os.path.isfile(src_png):
                    print(f"[!] 渲染缺失: {view}", flush=True)
                    continue
                dest = os.path.join(OUT, unique_prefix(f"fig_mv3d_{view}") + ".png")
                shutil.copy2(src_png, dest)
                print(f"[✓] 多视图结果: {view}:{dest}", flush=True)
                ok += 1
            print(f"[*] 多视图渲染完成: {ok}/{len(views)}", flush=True)
            return 0 if ok else 1

    # stage=repaint（旧的灰模重绘路径，保留兼容）
    from PIL import Image
    uploaded_main = upload_image(a.image).get("name")
    if not uploaded_main:
        print("[!] 主图上传失败")
        return 1
    ensure_comfyui_running()
    original = _load_rgb_image(a.image)
    base_text = (getattr(a, "prompt", "") or "").strip()
    specs = getattr(a, "clay", None) or []
    if not specs:
        print("[!] 缺少灰模路径：请先 stage=build，或传 --clay 方位:灰模路径")
        return 1
    ok = 0
    for spec in specs:
        if ":" not in spec:
            print(f"[!] 跳过格式错误的灰模参数: {spec}")
            continue
        view, clay_path = spec.split(":", 1)
        view = view.strip()
        if view not in MV_VIEWS or not os.path.isfile(clay_path):
            print(f"[!] 跳过无效灰模: {spec}")
            continue
        clay_name = upload_image(clay_path).get("name")
        if not clay_name:
            print(f"[!] 灰模上传失败: {clay_path}")
            continue
        instruction = MV3D_REPAINT
        if base_text:
            instruction += "Additional requirements: " + base_text + " "
        print(f"[*] 重绘 {MV_VIEWS[view][0]} ({view}) ...", flush=True)
        raw_image = None
        for attempt in range(2):
            seed = a.seed if (attempt == 0 and getattr(a, "seed", -1) >= 0) else random.randint(0, 2 ** 31 - 1)
            _, raw_image = run_qwen_edit(uploaded_main, instruction, seed, [clay_name])
            ratio, detail = flat_noise_ratio(original, raw_image)
            print(f"    质量检测：噪点 ×{ratio:.1f}（{detail}）", flush=True)
            if ratio > 300.0 and attempt == 0:
                print("    · 结果异常（可能整片噪点），换种子重试……", flush=True)
                continue
            break
        dest = os.path.join(OUT, unique_prefix(f"fig_mv3d_{view}") + ".png")
        raw_image.convert("RGB").save(dest)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            ok += 1
            print(f"[✓] 多视图结果: {view}:{dest}", flush=True)
    print(f"[*] 灰模重绘完成: {ok}/{len(specs)}", flush=True)
    return 0 if ok else 1


def _mv3d_build_hunyuan(a):
    ensure_comfyui_running()
    uploaded = upload_image(a.image).get("name")
    if not uploaded:
        print("[!] 主图上传失败")
        return 1
    print("[*] 本地 Hunyuan3D 建粗模 ...", flush=True)
    wf = build_3d_wf(uploaded, steps=30, resolution=3072, threshold=0.6,
                     prefix=unique_prefix("fig_mv3d"), octree_resolution=getattr(a, "octree_res", 384),
                     faces=0, crease=180.0, do_uv=False, do_preview=False, high_precision=False)
    pid = api_post("/prompt", {"prompt": wf}).get("prompt_id")
    if not pid:
        print("[!] 提交失败")
        return 1
    entry = wait_done(pid, 1800, "3D粗模")
    glb = None
    for fn, sub, typ in collect_files(entry):
        p = verified_output_path(fn, sub)
        if fn.lower().endswith(".glb"):
            glb = p
            break
    if not glb:
        print("[!] 没有生成 GLB")
        return 1
    print(f"[✓] 粗模: {glb}", flush=True)
    extents = _glb_extents(glb)
    if extents:
        print(f"[*] 粗模尺寸: {extents[0]:.2f} x {extents[1]:.2f} x {extents[2]:.2f}", flush=True)
        if min(extents) < 0.12 * max(extents):
            print("[!] 警告：粗模非常扁（像纸片），8 方位会失真。输入图很可能是平面立牌/插画——"
                  "请先用「图生图」把它转成手办渲染图，再用那张图做多视图，或用 Meshy 建粗模。", flush=True)
    return 0


def _mv3d_build_meshy(a):
    """Meshy 带贴图建粗模（30 积分左右），渲染出来是彩色 8 方位。"""
    try:
        import meshy_client
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 无法加载 meshy_client.py：{exc}")
        return 1
    try:
        before = meshy_client.balance()
        print(f"[*] Meshy 剩余积分: {before}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 连接 Meshy 失败：{exc}")
        return 1
    import tempfile
    with tempfile.TemporaryDirectory(prefix="mv3d_meshy_") as scratch:
        print("[*] 预处理（抠图+方图）...", flush=True)
        prepared = _prepare_3d_source(a, a.image, scratch)
        desens = bool(getattr(a, "meshy_desensitize", None))
        if desens:
            safe = os.path.join(scratch, "safe.png")
            ok, info = _desensitize_image(prepared, safe, strength=getattr(a, "meshy_strength", "auto"))
            print(f"[*] 上传前脱敏: {info}", flush=True)
            if ok and os.path.isfile(safe):
                prepared = safe
        print("[*] Meshy 生成带贴图 3D（约 30 积分）...", flush=True)
        glb, task = meshy_client.image_to_3d(
            prepared, out_dir=OUT, ai_model=getattr(a, "meshy_model", None) or meshy_client.CONFIG.get("ai_model", "meshy-7.1"),
            geometry_resolution="standard", should_texture=True, texture_resolution="2k",
            target_polycount=int(getattr(a, "meshy_poly", 0) or meshy_client.CONFIG.get("target_polycount", 300000) or 0),
            prefix=unique_prefix("fig_mv3d_meshy"), timeout=1800)
    try:
        after = meshy_client.balance()
        print(f"[*] Meshy 积分: {before} → {after}（消耗 {before-after:.0f}）", flush=True)
    except Exception:  # noqa: BLE001
        pass
    print(f"[✓] 粗模: {glb}", flush=True)
    return 0


# ---------------------------------------------------------------- 模型文件修改
MODEL_EXTS = (".glb", ".gltf", ".obj", ".stl", ".3mf", ".ply")


def _render_views_of(model_path, views, size, scratch):
    """用 Blender 渲染任意模型文件的指定方位，返回 {view: png}。"""
    blender = _find_blender()
    if not blender:
        raise RuntimeError("找不到 Blender，无法渲染模型（安装 Blender 或在 meshy_config.json 配 blender_exe）")
    cmd = [blender, "--background", "--factory-startup",
           "--python", os.path.join(HERE, "render_views.py"), "--",
           "--glb", model_path, "--out_dir", scratch,
           "--views", ",".join(views), "--size", str(size)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError("Blender 渲染失败：" + ((proc.stderr or proc.stdout or "")[-800:]))
    result = {}
    for view in views:
        p = os.path.join(scratch, f"clay_{view}.png")
        if os.path.isfile(p):
            result[view] = p
    if not result:
        raise RuntimeError("Blender 没有输出渲染图")
    return result


def cmd_model_edit(a):
    """导入 3D 模型，按自然语言要求修改模型文件。

    edit-mode:
      texture  渲染正面 → Qwen 按文字修改渲染图 → 把修改后的贴图投影回模型（快，改外观/涂装）
      rebuild  渲染正面 → Qwen 修改 → Meshy 图生3D 重建模型（改形状/删物体，约 20 积分）
    """
    model_path = a.model
    if not os.path.isfile(model_path):
        print(f"[!] 找不到模型文件: {model_path}")
        return 1
    if os.path.splitext(model_path)[1].lower() not in MODEL_EXTS:
        print(f"[!] 不支持的模型格式（支持 {', '.join(MODEL_EXTS)}）")
        return 1
    instruction = (a.instruction or "").strip()
    if not instruction:
        print("[!] 修改要求不能为空")
        return 1
    edit_mode = getattr(a, "edit_mode", "texture") or "texture"
    size = int(getattr(a, "size", 1024) or 1024)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="model_edit_") as scratch:
        print(f"[*] 模型: {os.path.abspath(model_path)}", flush=True)
        print(f"[*] 修改要求: {instruction}", flush=True)
        print("[*] 渲染模型正面 ...", flush=True)
        renders = _render_views_of(model_path, ["front"], size, scratch)
        front = renders["front"]

        # 用 Qwen 编辑渲染图
        ensure_comfyui_running()
        uploaded = upload_image(front).get("name")
        if not uploaded:
            print("[!] 渲染图上传失败")
            return 1
        edit_instruction = (
            "This is a rendered front view of a 3D model, centered on a plain neutral background. "
            "Apply this modification to the image: " + instruction + " "
            "Keep the same camera angle, framing and the model's silhouette, pose and proportions; "
            "only change what the request asks. Do not add frames, borders, text, watermarks or extra objects. "
            "Keep the background clean and neutral.")
        seed = a.seed if (getattr(a, "seed", -1) >= 0) else random.randint(0, 2 ** 31 - 1)
        print(f"[*] Qwen 修改渲染图（seed={seed}）……", flush=True)
        _, edited_image = run_qwen_edit(uploaded, edit_instruction, seed)
        edited_path = os.path.join(scratch, "edited_front.png")
        edited_image.convert("RGB").save(edited_path)
        print(f"[✓] 修改后的渲染图: {edited_path}", flush=True)

        if edit_mode == "rebuild":
            try:
                import meshy_client
            except Exception as exc:  # noqa: BLE001
                print(f"[!] 无法加载 meshy_client.py：{exc}")
                return 1
            upload_img = edited_path
            if getattr(a, "meshy_desensitize", None):
                safe = os.path.join(scratch, "edited_safe.png")
                ok, info = _desensitize_image(uploaded, safe, strength="auto")
                print(f"[*] 上传前脱敏: {info}", flush=True)
                if ok and os.path.isfile(safe):
                    upload_img = safe
            print("[*] Meshy 图生3D 重建模型（约 20 积分）…", flush=True)
            result_glb, task = meshy_client.image_to_3d(
                upload_img, out_dir=OUT, ai_model=meshy_client.CONFIG.get("ai_model", "meshy-7.1"),
                geometry_resolution="standard", should_texture=True, texture_resolution="2k",
                target_polycount=int(meshy_client.CONFIG.get("target_polycount", 300000) or 0),
                prefix=unique_prefix("fig_model_rebuild"), timeout=1800)
        else:
            result_glb = os.path.join(OUT, unique_prefix("fig_model_edit") + ".glb")
            print("[*] 把修改后的贴图投影回模型 ...", flush=True)
            proc = subprocess.run([PY, os.path.join(HERE, "project_texture.py"),
                                   model_path, edited_path, result_glb],
                                  capture_output=True, text=True, timeout=1800)
            if proc.returncode != 0:
                print("[!] 贴图投影失败：")
                print((proc.stderr or proc.stdout or "")[-1200:])
                return 1
            print((proc.stdout or "").strip(), flush=True)

        # 结果预览：渲染正面/侧面
        print("[*] 渲染修改后的模型预览 ...", flush=True)
        try:
            previews = _render_views_of(result_glb, ["front", "front_left"], size, scratch)
            saved = []
            for view, png in previews.items():
                dest = os.path.join(OUT, unique_prefix(f"fig_model_edit_preview_{view}") + ".png")
                shutil.copy2(png, dest)
                saved.append(dest)
                print(f"[✓] 模型修改预览: {view}:{dest}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[!] 预览渲染失败（不影响模型）: {exc}", flush=True)

        print(f"[✓] 模型修改结果: {result_glb}", flush=True)
        return 0


def cmd_print(a):
    cmd = [PY, os.path.join(HERE, "convert_3d.py"), a.model,
           "--out-dir", a.out_dir, "--to"] + a.formats
    if a.out_prefix:
        cmd += ["--out-prefix", a.out_prefix]
    # ★ 当前默认：不做 Taubin 平滑（实测在非流形网格上提前平滑会打出坑点/
    #   尖刺），也不做 --solidify 粗体素化；导出前由 convert_3d.py 用 Blender
    #   的 0.25mm 体素重建完成水密化，并带尺寸/轮廓回退检查。
    if a.solidify:
        cmd.append("--solidify")
    # 尺寸校正：RemeshMesh 输出未反归一化（固定在 [-0.5,0.5] 立方体）
    if a.ref_model and os.path.exists(a.ref_model):
        cmd += ["--ref", a.ref_model]
    if a.decimate > 0:
        cmd += ["--decimate", str(a.decimate)]
    # 始终显式透传，不依赖 convert_3d.py 的默认值
    cmd += ["--smooth", str(a.smooth)]
    # --model-height：按成品实际高度(mm)缩放，商业手办最实用的参数
    # 高度换算交给 convert_3d.py 自己做（它跑在带 trimesh 的解释器里）
    if a.model_height > 0:
        cmd += ["--height", str(a.model_height)]
    elif a.scale != 1.0:
        cmd += ["--scale", str(a.scale)]
    cmd += ["--unit", a.unit]
    if a.solidify and a.pitch != 0.005:
        cmd += ["--pitch", str(a.pitch)]
    # ★★ 手板制作增强参数 ★★
    if getattr(a, 'no_orient', False):
        cmd.append("--no-orient")
    if getattr(a, 'base', 0) > 0:
        cmd += ["--base", str(a.base)]
    if getattr(a, 'hollow', 0) > 0:
        cmd += ["--hollow", str(a.hollow)]
    if getattr(a, 'no_diagnose', False):
        cmd.append("--no-diagnose")
    # ★★ 参考图保真参数：把「本次 3D 实际用的图」一路传到 STL 导出环节 ★★
    ref = getattr(a, 'ref_image', None) or _LAST_REFERENCE_3D
    if ref and os.path.isfile(ref):
        cmd += ["--ref-image", ref]
    elif not getattr(a, 'ref_image', None):
        print("[*] 本次进程无内存中的参考图，convert_3d 将自动查找模型同名的 "
              "<模型>_3d_input.png", flush=True)
    if getattr(a, 'min_iou', None) is not None:
        cmd += ["--min-iou", str(a.min_iou)]
    if getattr(a, 'allow_low_fidelity', False):
        cmd.append("--allow-low-fidelity")
    if getattr(a, 'no_fidelity', False):
        cmd.append("--no-fidelity")
    if getattr(a, 'no_crop_background', False):
        cmd.append("--no-crop-background")
    if getattr(a, 'fidelity_report', None):
        cmd += ["--fidelity-report", a.fidelity_report]
    if getattr(a, 'no_blender_repair', False):
        cmd.append("--no-blender-repair")
    if getattr(a, 'voxel_mm', None) is not None:
        cmd += ["--voxel-mm", str(a.voxel_mm)]
    if getattr(a, 'repair_max_iou_drop', None) is not None:
        cmd += ["--repair-max-iou-drop", str(a.repair_max_iou_drop)]
    # ★ R30：导出质量门禁必须走产品入口，否则 final5 这类成品只能绕过 fig.py
    #   直接调底层脚本才能复现。前置校验与 convert_3d.validate_args 同口径。
    if getattr(a, 'strict_single_body', False) and not any(
            str(f).lower().lstrip('.') == 'stl' for f in (a.formats or [])):
        print("[!] --strict-single-body 需要 --formats 包含 stl，否则门禁无法落地", flush=True)
        return 2
    for key, flag in PRINT_FLAG_ARGS.items():
        if getattr(a, key, False):
            cmd.append(flag)
    return subprocess.call(cmd)


def cmd_all(a):
    global _LAST_PICKED
    # 1) 出图
    pos = a.prompt
    if a.model == "pony" and "white background" not in pos.lower() and \
            "simple background" not in pos.lower():
        pos += (", full body, standing, front view, white background, simple background, "
                "isolated character, character only, correct proportions")
    print(f"[*] 阶段1/3 出图 ({a.model}) ...")
    before = set(os.listdir(OUT))
    rc = cmd_img(a)
    if rc != 0:
        return rc
    # 优先用 cmd_img 选中的那张（重抽时它可能是历次最佳，不一定是最后一张）
    img = _LAST_PICKED
    if not img or not os.path.exists(img):
        # 兜底：只取本次新生成的图，按时间倒序取最新的
        after = set(os.listdir(OUT))
        new_files = [f for f in after - before
                     if f.endswith(".png") and f.startswith("fig_img")]
        if not new_files:
            print("[!] 本次没有生成新的出图文件，停止后续步骤")
            return 1
        new_files.sort(key=lambda f: os.path.getmtime(os.path.join(OUT, f)), reverse=True)
        img = os.path.join(OUT, new_files[0])
    print(f"[*] 阶段2/3 图生3D <- {os.path.basename(img)}")
    a.image = img
    rc = cmd_model(a)
    if rc != 0:
        return rc
    # 只能使用本次任务生成的模型，避免误用旧文件。
    glb = _LAST_GLB
    if not glb or not os.path.isfile(glb):
        print("[!] 本次图生3D没有生成 GLB，停止打印转换")
        return 1
    print(f"[*] 阶段3/3 转打印格式 <- {os.path.basename(glb)}")
    a.model = glb
    return cmd_print(a)


def cmd_image_print(a):
    """使用用户选定的图片直接生成3D，再转换为打印文件。"""
    print(f"[*] 本次参考图: {os.path.abspath(a.image)}", flush=True)
    rc = cmd_model(a)
    if rc != 0:
        return rc
    if not _LAST_GLB or not os.path.isfile(_LAST_GLB):
        print("[!] 本次没有生成有效3D模型，停止转换")
        return 1
    # ★ 旧实现在这里强制打开 --solidify（体素重建）。项目文档自己记录了该操作
    #   会把锐边从 0.4% 碾到 20%+，是「细节糊掉」的直接来源。
    #   改为由 convert_3d.py 做拓扑级补洞 + 法线修复（不体素化、不损表面）。
    if _LAST_ENGINE_USED == "meshy" and not getattr(a, "solidify", False):
        print("[*] Meshy 网格非水密：convert_3d 将做拓扑补洞（不再体素重建）", flush=True)
    # 用户显式指定的参考图优先；否则用本次 3D 实际输入图
    if getattr(a, "ref_image", None):
        global _LAST_REFERENCE_3D
        _LAST_REFERENCE_3D = a.ref_image
    a.model = _LAST_GLB
    print(f"[*] 转换本次模型: {a.model}", flush=True)
    rc = cmd_print(a)
    if rc == 0:
        print(f"[✓] STL 成品目录: {os.path.abspath(a.out_dir)}", flush=True)
    return rc


def cmd_auto(a):
    """中文描述 -> 大脑生成 tags -> 出图 -> 图生3D -> 打印格式，全自动一条龙"""
    print(f"[*] 阶段0/4 本地大脑 {a.brain} 理解中文描述 ...")
    t0 = time.time()
    try:
        tags = brain_prompt(a.desc, a.brain)
    except Exception as e:
        print(f"[!] 大脑调用失败（{e}），退回直接使用原文作提示词")
        tags = a.desc
    print(f"[✓] ({time.time()-t0:.1f}s) tags: {tags}")
    # 大脑已用完，把显存还给 ComfyUI（否则扩散模型被迫 CPU 卸载，慢 10 倍）
    wait_vram_free(need_mb=6000, timeout=120)
    a.prompt = tags
    return cmd_all(a)


def cmd_doctor(a):
    print("=" * 58)
    print(" 二次元手办本地流水线 · 环境自检")
    print("=" * 58)

    print("\n[1] ComfyUI")
    try:
        st = api_get("/system_stats")
        print(f"    ✓ 服务正常  http://{HOST}   版本 {st['system']['comfyui_version']}")
        try:
            obj = api_get("/object_info")
            need = ["Hunyuan3Dv2Conditioning", "VoxelToMesh", "DecimateMesh",
                    "UnwrapMesh", "MeshSmoothNormals", "MeshToFile3D", "SaveGLB",
                    "RenderMesh", "RemeshMesh", "BakeTextureFromVoxel"]
            have = [n for n in need if n in obj]
            miss = [n for n in need if n not in obj]
            print(f"    ✓ 3D 节点 {len(have)}/{len(need)} 存在" +
                  (f"   缺失: {miss}" if miss else ""))
        except Exception as e:
            print(f"    ! 节点列表获取失败: {e}")
    except Exception as e:
        print(f"    ✗ 连不上 {HOST}: {e}")
        print("      启动：python fig.py serve")

    print("\n[2] 模型权重")
    roots = [
        os.path.join(HERE, "ComfyUI", "models", "checkpoints"),
        os.path.join(HERE, "ComfyUI", "models", "diffusion_models"),
        os.path.join(HERE, "ComfyUI", "models", "unet"),
    ]
    found = []
    for r in roots:
        if os.path.isdir(r):
            for fn in os.listdir(r):
                if fn.endswith(".safetensors"):
                    found.append((fn, r))
    for fn, r in found:
        sz = os.path.getsize(os.path.join(r, fn)) / 1e9
        print(f"    ✓ {fn}  ({sz:.2f} GB)  [{os.path.basename(r)}]")
    if not found:
        print("    ! 未找到 safetensors")

    print("\n[3] Python 依赖")
    for mod in ["trimesh", "numpy", "scipy", "networkx", "PIL", "skimage", "lxml"]:
        try:
            __import__(mod)
            print(f"    ✓ {mod}")
        except ImportError:
            print(f"    ✗ {mod}  -> pip install {mod}")
    print("    （图生3D / 格式转换全部走标准库 urllib，无需 requests）")

    print("\n[4] 脚本")
    for s in ["fig.py", "pipeline_figure.py", "convert_3d.py", "make_print_ready.py",
              "test_3d_enhanced.py", "test_hunyuan3d.py", "workflow_pony_api.json"]:
        p = os.path.join(HERE, s)
        print(f"    {'✓' if os.path.exists(p) else '✗'} {s}")

    print("\n[5] Ollama（文本大脑）")
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=20)
        print("    " + "\n    ".join(out.stdout.strip().splitlines()))
    except Exception as e:
        print(f"    ! ollama 不可用: {e}")

    print("\n[6] GPU")
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
        print(f"    {out.stdout.strip()}")
    except Exception as e:
        print(f"    ! nvidia-smi 不可用: {e}")

    print("\n" + "=" * 58)
    print(" 常用命令:")
    print("   python fig.py all \"1girl, silver hair, red eyes\" --model pony")
    print("   python fig.py doctor")
    print("=" * 58)
    return 0


def cmd_serve(a):
    d = os.path.join(HERE, "ComfyUI")
    print(f"[*] 启动 ComfyUI: {d}")
    os.chdir(d)
    os.execv(sys.executable, [sys.executable, "main.py", "--port", str(a.port)])
    return 0


# =================================================================
# ★★ 图像去敏感化（desensitize）★★
#
# 商业手办工作流：
#   敏感原图 → 去敏化(遮挡关键部位, 保留轮廓姿态)
#   → 上传 Meshy / 其他建模 AI（过审核）
#   → Meshy 生成 3D → 拿回来 → restore 还原成敏感样子
#
# 技术方案：
#   1. 肤色检测（HSV + YCbCr 双判据）
#   2. 按身体区域分级遮挡（胸部/腰部/下腹 = 高风险；四肢 = 低风险）
#   3. 遮挡方式：像素化 + 边缘模糊 + 服装色覆盖
#   4. 保留身体轮廓和姿态（不影响 3D 重建的几何信息）
# =================================================================

def _detect_skin(img_arr):
    """肤色检测：HSV + YCbCr 双判据 + 二次元肤色扩展，返回肤色 mask (bool array)

    ★ 二次元角色的肤色和真人不同：
      - 真人肤色偏黄/棕，Cb/Cr 值较高
      - 二次元肤色偏粉白/浅米色，饱和度更低，明度更高
      - 需要扩展判据覆盖「粉色皮肤」「浅色皮肤」等二次元常见肤色
    """
    import numpy as np
    r, g, b = img_arr[:, :, 0], img_arr[:, :, 1], img_arr[:, :, 2]

    # HSV 判据
    mx = img_arr.max(axis=2)
    mn = img_arr.min(axis=2)
    diff = mx - mn
    sat = np.where(mx > 1e-6, diff / np.maximum(mx, 1e-6), 0.0)
    hue = np.where(diff > 1e-6,
                   np.where(mx == r, (g - b) / np.maximum(diff, 1e-6),
                   np.where(mx == g, 2.0 + (b - r) / np.maximum(diff, 1e-6),
                            4.0 + (r - g) / np.maximum(diff, 1e-6))), 0.0)
    hue_deg = hue * 60.0
    hue_deg = np.where(hue_deg < 0, hue_deg + 360, hue_deg)

    # 真人肤色（HSV）
    skin_human = ((hue_deg >= 0) & (hue_deg <= 50) |
                  (hue_deg >= 330) & (hue_deg <= 360)) & \
                 (sat >= 0.15) & (sat <= 0.65) & (mx >= 0.30) & (mx <= 0.95)

    # YCbCr 判据
    y_val = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128 + 255 * (-0.168736 * r - 0.331264 * g + 0.5 * b)
    cr = 128 + 255 * (0.5 * r - 0.418688 * g - 0.081312 * b)
    skin_ycbcr = (cr >= 135) & (cr <= 180) & (cb >= 85) & (cb <= 135) & (y_val >= 0.25)

    # ★ 二次元肤色扩展：
    #   浅粉/米白肤色：R>B>G（偏暖），低饱和度，高明度
    #   典型值：R 0.85-1.0, G 0.70-0.90, B 0.65-0.85
    anime_skin = (r > g) & (g > b) & \
                 (r >= 0.75) & (r <= 1.0) & \
                 (sat >= 0.03) & (sat <= 0.25) & \
                 (y_val >= 0.70) & (y_val <= 0.98)

    # ★ 二次元深色肤色（小麦/棕色皮肤角色）
    anime_dark = (r > g) & (g > b) & \
                 (r >= 0.40) & (r <= 0.75) & \
                 (sat >= 0.10) & (sat <= 0.40) & \
                 (hue_deg >= 10) & (hue_deg <= 45)

    return (skin_human & skin_ycbcr) | anime_skin | anime_dark


def _pixelate_region(img_arr, mask, block=12):
    """对 mask 区域做像素化（马赛克）"""
    import numpy as np
    from scipy import ndimage
    H, W = img_arr.shape[:2]
    # 用均值池化做像素化
    labeled, n = ndimage.label(mask)
    if n == 0:
        return img_arr
    out = img_arr.copy()
    for label_id in range(1, n + 1):
        region = labeled == label_id
        ys, xs = np.where(region)
        if len(ys) < 10:
            continue
        y0, y1 = ys.min(), ys.max()
        x0, x1 = xs.min(), xs.max()
        # 分块取均值
        for by in range(y0, y1 + 1, block):
            for bx in range(x0, x1 + 1, block):
                sub = region[by:by+block, bx:bx+block]
                if sub.sum() < 1:
                    continue
                vals = img_arr[by:by+block, bx:bx+block][sub[None].transpose(1, 2, 0) if False else sub]
                # 直接取区域内的像素均值
                block_mask = region[by:by+block, bx:bx+block]
                if block_mask.any():
                    avg = img_arr[by:by+block, bx:bx+block][block_mask].mean(axis=0)
                    out[by:by+block, bx:bx+block][block_mask] = avg
    return out


def _detect_sensitive_regions(img_arr, skin_mask):
    """按身体区域分级检测敏感部位。

    返回 dict: {
        'high': bool mask,   # 高风险区域（胸/腰/下腹）
        'low':  bool mask,   # 低风险区域（四肢裸露）
    }
    """
    import numpy as np
    from scipy import ndimage
    H, W = img_arr.shape[:2]

    # 按纵向比例划分身体区域（假设全身立绘）
    # 0-15%: 头部
    # 15-35%: 胸部（高风险）
    # 35-50%: 腰腹（高风险）
    # 50-65%: 下腹/裆部（最高风险）
    # 65-100%: 腿部（低风险）
    rows = np.arange(H)
    y_frac = rows / H

    chest_mask = skin_mask & (y_frac[:, None] >= 0.15) & (y_frac[:, None] < 0.35)
    waist_mask = skin_mask & (y_frac[:, None] >= 0.35) & (y_frac[:, None] < 0.50)
    groin_mask = skin_mask & (y_frac[:, None] >= 0.50) & (y_frac[:, None] < 0.65)
    limb_mask = skin_mask & (y_frac[:, None] >= 0.65)

    high_risk = chest_mask | waist_mask | groin_mask
    low_risk = limb_mask

    # 连通块过滤：去掉太小的噪点
    for mask_name, mask_val in [('high', high_risk), ('low', low_risk)]:
        if mask_val.sum() < 20:
            continue
        labeled, n = ndimage.label(mask_val)
        if n > 0:
            sizes = ndimage.sum(mask_val, labeled, range(1, n + 1))
            min_size = max(30, mask_val.sum() * 0.02)
            keep = sizes >= min_size
            filtered = np.zeros_like(mask_val)
            for i, k in enumerate(keep):
                if k:
                    filtered |= (labeled == i + 1)
            if mask_name == 'high':
                high_risk = filtered
            else:
                low_risk = filtered

    return {'high': high_risk, 'low': low_risk}


def _clothe_region(img_arr, mask, color=(0.3, 0.3, 0.8)):
    """用服装色覆盖区域 + 边缘过渡"""
    import numpy as np
    from scipy import ndimage
    out = img_arr.copy()
    c = np.array(color)
    # 膨胀边缘做渐变过渡
    edge = ndimage.binary_dilation(mask, iterations=3) & ~mask
    out[mask] = c
    # 边缘混合
    if edge.any():
        out[edge] = out[edge] * 0.5 + c * 0.5
    return out


def _desensitize_image(src, dst, strength='auto', clothed=True, pixelate=True):
    """去敏感化主函数。

    strength:
        'auto' - 自动检测并遮挡高风险区域
        'full' - 全身肤色遮挡（最保守，保证过审）
        'minimal' - 只遮挡裆部
    clothed: 是否用服装色覆盖（否则纯像素化）
    pixelate: 是否做像素化

    返回 (success, 统计信息)
    """
    try:
        from PIL import Image, ImageFilter
        import numpy as np
    except ImportError:
        return False, "缺 PIL/numpy"

    try:
        img = Image.open(src).convert("RGB")
        arr = np.array(img).astype(float) / 255.0
        H, W = arr.shape[:2]

        print(f"    图像: {W}x{H}")

        # 1) 肤色检测
        skin = _detect_skin(arr)
        skin_ratio = float(skin.mean())
        print(f"    肤色占比: {skin_ratio:.1%}")

        if skin_ratio < 0.005:
            print("    肤色极少，可能已穿全身装或非人物图")
            # 直接保存原图
            img.save(dst)
            return True, "未检测到区域，图像未改变；请自行检查"

        # 2) 区域分级
        regions = _detect_sensitive_regions(arr, skin)
        high = regions['high']
        low = regions['low']
        high_ratio = float(high.mean())
        low_ratio = float(low.mean())
        print(f"    高风险区域: {high_ratio:.1%}  低风险: {low_ratio:.1%}")

        # 3) 确定遮挡范围
        if strength == 'full':
            mask_to_cover = skin  # 全身肤色
        elif strength == 'minimal':
            mask_to_cover = high & (np.arange(H)[:, None] / H >= 0.45)  # 只遮挡腰部以下
        else:  # auto
            mask_to_cover = high

        if mask_to_cover.sum() < 10:
            print("    未检出需要遮挡的区域")
            img.save(dst)
            return True, "未检测到区域，图像未改变；请自行检查"

        cover_ratio = float(mask_to_cover.mean())
        print(f"    遮挡面积: {cover_ratio:.1%}")

        # 4) 执行遮挡
        out = arr.copy()

        # 先做服装色覆盖（高风险区域）
        if clothed:
            # 服装色：深蓝/紫色调，像泳装/内衣
            cloth_color = (0.15, 0.15, 0.45)
            out = _clothe_region(out, mask_to_cover, color=cloth_color)

        # 再做像素化（让遮挡区域看起来像马赛克而不是纯色块）
        if pixelate and mask_to_cover.any():
            out = _pixelate_region(out, mask_to_cover, block=14)

        # 边缘柔化
        out_img = Image.fromarray((np.clip(out, 0, 1) * 255).astype("uint8"))
        # 对遮挡区域边缘做轻微模糊
        from scipy import ndimage
        edge = ndimage.binary_dilation(mask_to_cover, iterations=2) & ~mask_to_cover
        if edge.any():
            blurred = np.array(out_img.filter(ImageFilter.GaussianBlur(3))).astype(float) / 255.0
            out_arr = np.array(out_img).astype(float) / 255.0
            out_arr[edge] = out_arr[edge] * 0.4 + blurred[edge] * 0.6
            out_img = Image.fromarray((np.clip(out_arr, 0, 1) * 255).astype("uint8"))

        out_img.save(dst)
        return True, f"遮挡 {cover_ratio:.1%}（强度={strength}）"

    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def cmd_desensitize(a):
    """去敏感化子命令：敏感图 → 审核安全版"""
    src = a.image
    if not os.path.exists(src):
        print(f"[!] 图片不存在: {src}")
        return 1

    # 输出路径
    if a.output:
        dst = a.output
    else:
        base, ext = os.path.splitext(src)
        dst = base + "_desensitized" + (ext or ".png")

    print("=" * 58)
    print(" 图像自动遮挡")
    print("=" * 58)
    print(f"  输入: {src}")
    print(f"  输出: {dst}")
    print(f"  强度: {a.strength}")

    ok, info = _desensitize_image(src, dst, strength=a.strength,
                                  clothed=not a.no_clothe,
                                  pixelate=not a.no_pixelate)
    if ok:
        if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
            print("[!] 未生成有效输出文件")
            return 1
        print(f"\n[✓] 图像已保存: {dst}")
        print(f"    {info}")
        print("    请打开输出图检查实际遮挡范围；自动检测可能遗漏。")
    else:
        print(f"\n[!] 失败: {info}")
    return 0 if ok else 1


def cmd_restore(a):
    """将参考图片正面投影到模型，导出新的带纹理 GLB。"""
    if not os.path.isfile(a.model):
        print(f"[!] 找不到模型: {a.model}")
        return 1
    if not a.original or not os.path.isfile(a.original):
        print("[!] 请使用 --original 指定存在的参考图片")
        return 1
    output = a.output or os.path.splitext(a.model)[0] + "_projected.glb"
    return subprocess.call([PY, os.path.join(HERE, "restore_texture.py"), a.model, a.original, output])


def _reconfigure_stdio():
    """Windows 下控制台/管道可能是 GBK，直接 print 中文和 ✓ 会抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# ----------------------------------------------------------------- CLI
def main():
    _reconfigure_stdio()
    ap = argparse.ArgumentParser(
        prog="fig.py", description="二次元手办本地流水线统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_img_opts(p):
        p.add_argument("--model", default="pony", choices=["pony", "flux"])
        p.add_argument("--neg", default=None)
        p.add_argument("--seed", type=int, default=-1, help="随机种子；-1=每次随机（推荐）")
        p.add_argument("--width", type=int, default=832)
        p.add_argument("--height", type=int, default=1216)
        p.add_argument("--steps", type=int, default=25)
        p.add_argument("--retry", type=int, default=4,
                       help="背景不达标时最多换 seed 重抽几次（seed 影响远大于负面词）")
        p.add_argument("--check-bg", dest="check_bg", action="store_true", default=True,
                       help="出图后自动检测背景板，不达标自动换 seed 重抽")
        p.add_argument("--no-check-bg", dest="check_bg", action="store_false",
                       help="关闭背景板自动检测")
        p.add_argument("--bg-limit", type=float, default=0.12,
                       help="背景板判定阈值：低饱和灰区占比超过此值判为不合格")
        p.add_argument("--asym-limit", type=float, default=0.12,
                       help="正面姿态判定阈值：左右不对称度超过此值判为侧身（3D 会丢腿）")

    def add_3d_opts(p):
        # 细节实测：同一张原图，30 步/384 会把刘海和衣褶压成平滑壳；
        # 50 步/512 可稳定补出可辨发束与衣摆起伏。保持原图直接表面网格，
        # 不默认启用实验性 solid remesh（候选 A 会截头/轴向错乱）。
        p.add_argument("--steps3d", type=int, default=50,
                       help="Hunyuan3D 采样步数：50=默认高精度，30=较快")
        p.add_argument("--resolution", type=int, default=3072)
        p.add_argument("--octree-res", type=int, default=512, choices=[256, 384, 512],
                       help="三维重建八叉树精度：256=快但粗，384=兼容旧默认，"
                            "512=默认高精度（约 2~3 倍耗时/显存）")
        # ★ 3D 引擎：本地 Hunyuan（免费）/ Meshy 云（高精度，消耗积分）/ auto（本地失败回退云）
        p.add_argument("--engine", choices=["hunyuan", "meshy", "meshy-mv", "auto"], default="hunyuan",
                       help="3D 引擎：hunyuan=本地免费；meshy=Meshy 单图；"
                            "meshy-mv=Meshy 官方多视图（侧/背细节最稳，消耗积分）；auto=本地失败回退 Meshy")
        p.add_argument("--meshy-model", default=None,
                       help="Meshy 模型名，默认读 meshy_config.json（meshy-7.1 / meshy-6 / meshy-6-lite）")
        p.add_argument("--meshy-geometry", choices=["standard", "2k", "4k"], default="standard",
                       help="Meshy 几何精度：standard / 2k(Ultra) / 4k(Ultra 最细，+5 credits)")
        p.add_argument("--meshy-texture", action="store_true",
                       help="让 Meshy 生成贴图（打印不需要，会多花积分）")
        p.add_argument("--meshy-poly", type=int, default=0,
                       help="Meshy 目标面数，0=不限制（打印建议 150000~300000）")
        p.add_argument("--meshy-desensitize", dest="meshy_desensitize", action="store_true", default=None,
                       help="上传 Meshy 前先做脱敏（敏感内容过审用）；默认读配置")
        p.add_argument("--no-meshy-desensitize", dest="meshy_desensitize", action="store_false",
                       help="强制不做脱敏")
        p.add_argument("--meshy-strength", choices=["auto", "full", "minimal"], default="auto",
                       help="脱敏强度：auto=自动检测高风险区，full=全身，minimal=仅裆部")
        p.add_argument("--threshold", type=float, default=0.6)
        p.add_argument("--faces", type=int, default=0,
                       help="3D 目标面数上限。★ 0=不减面（默认，推荐）："
                            "440万面/锐边0.07%%/天然水密/GLB 79MB。"
                            "设 400000 可减到40万面（GLB 7MB，但水密性会丢失）")
        p.add_argument("--crease", type=float, default=180.0,
                       help="法线锐边角度。180=完全平滑(拓扑不变，保持水密，默认)；"
                            "低于180会分裂顶点保留硬边，破坏水密性")
        p.add_argument("--uv-resolution", type=int, default=2048)
        p.add_argument("--weld-distance", type=float, default=0.0,
                       help="顶点焊接半径(相对包围盒)。0=自动；出现 per-triangle charts 时调到 0.001")
        p.add_argument("--prefix", default="figure_3d")
        p.add_argument("--uv", action="store_true",
                       help="做 UV 展开。★ 会撕裂网格破坏水密性，3D打印不需要，默认关闭")
        p.add_argument("--no-preview", action="store_true")
        p.add_argument("--no-isolate", action="store_true",
                       help="跳过背景分离（原图已纯白底时可关，速度更快）")
        # ★ 3D 输入门禁
        p.add_argument("--allow-bad-3d-input", action="store_true",
                       help="强制放行不合格的 3D 输入（躺姿/带场景/主体贴边），默认拒绝")
        p.add_argument("--input-asym-limit", type=float, default=0.12,
                       help="3D 输入正面姿态判定阈值（左右不对称度），默认 0.12")
        # ★ 多视图重建：front/left/back/right=path。front 缺省用主图锚点。
        p.add_argument("--mv-refs", nargs="*", default=[],
                       help="Hunyuan 多视图条件参考图，格式 view=path；"
                            "至少 2 个方位（如 left=a.png back=b.png）。"
                            "专治侧面/背面塌陷、长发糊块、四肢缺证据")
        # ★ 高精度管线参数
        p.add_argument("--remesh-res", type=int, default=512,
                       help="RemeshMesh 体素分辨率。512≈100万面(推荐) / 768 / 1024")
        p.add_argument("--smooth-iters", type=int, default=3,
                       help="Taubin 平滑迭代。3 可清除 DC 阶梯伪影")
        p.add_argument("--remesh-band", type=float, default=1.0,
                       help="RemeshMesh 窄带宽度(体素单位)。越大缝隙桥接越强")
        p.add_argument("--project-back", type=float, default=0.0,
                       help="顶点向原表面投影比例。0=纯DC / 0.5=贴回原表面(更保形)")
        p.add_argument("--low-precision", action="store_true",
                       help="保留兼容参数：使用原始网格（默认）")
        p.add_argument("--remesh-solid", action="store_true",
                       help="实验性实体重网格，可能严重破坏人物形状")
        p.add_argument("--iso-model", default="isnet-anime",
                       help="rembg 分割模型。isnet-anime=二次元角色专用(推荐)；"
                            "u2net=通用；birefnet-general=高精但慢")
        p.add_argument("--iso-components", type=int, default=3,
                       help="背景分离时保留的最大连通块数量（0=不清理）。"
                            "用于剔除与角色分离的背景碎片")
        # ★ 色调平坦化：压缩 cel shading 阴影，消除 3D 蜂窝纹
        p.add_argument("--no-flatten", action="store_true", default=True,
                       help="跳过色调平坦化（默认）")
        p.add_argument("--flatten", dest="no_flatten", action="store_false",
                       help="实验性压缩阴影，可能改变参考图外观")
        p.add_argument("--flatten-compress", type=float, default=0.20,
                       help="色调平坦化压缩比。0.2=只保留20%%阴影对比（默认推荐）；"
                            "0.0=完全压平成剪影；1.0=不压缩")

    def add_print_opts(p):
        p.add_argument("--out-dir", default=os.path.join(HERE, "print_ready"))
        p.add_argument("--formats", nargs="*", default=["obj", "stl", "3mf", "ply"])
        p.add_argument("--solidify", action="store_true",
                       help="额外做体素重建水密化。★ 会把精细表面碾成粗糙块"
                            "（锐边 0.4%%->20%%），高精度路径下不需要")
        p.add_argument("--no-solidify", dest="no_solidify", action="store_true",
                       help="兼容保留（默认已不做体素重建）")
        p.add_argument("--scale", type=float, default=1.0)
        p.add_argument("--unit", default="mm", choices=["mm", "cm", "m", "unit"])
        p.add_argument("--pitch", type=float, default=0.005,
                       help="体素重建精度，仅在 --solidify 时生效")
        # ★ 高精度参数
        p.add_argument("--ref-model", default=None,
                       help="参考网格路径，用于还原被 RemeshMesh 归一化的尺寸")
        p.add_argument("--decimate", type=int, default=0,
                       help="减面到目标面数。★ 破坏水密性，商业手办建议 0")
        p.add_argument("--smooth", type=int, default=PRINT_DEFAULTS["smooth"],
                       help="Taubin 平滑迭代次数（默认 0）。非水密网格会推迟到水密化后；"
                            "实测提前平滑会打出坑点/尖刺")
        p.add_argument("--model-height", type=float, default=PRINT_DEFAULTS["model_height"],
                       help="成品高度(mm)。指定后自动按比例缩放，取代 --scale")
        p.add_argument("--out-prefix", default=None,
                       help="输出文件名前缀（不含扩展名）")
        # ★★ 手板制作增强参数 ★★
        p.add_argument("--no-orient", action="store_true",
                       help="跳过自动扶正朝向（默认自动把模型竖立到 Z 轴）")
        p.add_argument("--base", type=float, default=PRINT_DEFAULTS["base"], nargs="?", const=0.03,
                       help="加圆柱底座。参数=厚度比例(0.03=3%%高度)。如 --base 0.05")
        p.add_argument("--no-base", dest="base", action="store_const", const=0.0,
                       help="不加底座")
        p.add_argument("--hollow", type=float, default=0.0, nargs="?", const=0.05,
                       help="抽壳省树脂。参数=壁厚比例(0.05=5%%对角线)。如 --hollow 0.03")
        p.add_argument("--no-hollow", dest="hollow", action="store_const", const=0.0,
                       help="不抽壳（默认）")
        p.add_argument("--no-diagnose", action="store_true",
                       help="关闭打印前诊断报告")
        # ★★ STL 参考图保真 ★★
        p.add_argument("--ref-image", default=None,
                       help="3D 重建用的参考原图；缺省时自动用随模型落盘的 <模型>_3d_input.png")
        p.add_argument("--min-iou", type=float, default=PRINT_DEFAULTS["min_iou"],
                       help="导出前轮廓相似度门禁，默认 0.55；0=关闭")
        p.add_argument("--allow-low-fidelity", action="store_true",
                       help="相似度不达标仍强制导出（不推荐）")
        p.add_argument("--no-fidelity", action="store_true",
                       help="关闭参考对齐，退回旧的包围盒启发式")
        p.add_argument("--no-crop-background", action="store_true",
                       help="不裁掉投影落在参考轮廓外的背景几何")
        p.add_argument("--fidelity-report", default=None,
                       help="保真报告 JSON 输出路径")
        p.add_argument("--voxel-mm", type=float, default=PRINT_DEFAULTS["voxel_mm"],
                       help="导出前 Blender 体素水密化分辨率(mm)，默认 0.15（保留发束/衣褶）；"
                            "0.25=兼容旧版且更快，0=仅拓扑修复")
        p.add_argument("--no-blender-repair", action="store_true",
                       help="关闭导出前 Blender 水密化")
        p.add_argument("--repair-max-iou-drop", type=float, default=PRINT_DEFAULTS["repair_max_iou_drop"],
                       help="水密化导致轮廓 IoU 下降超过此值时回退")
        # ★ 导出质量门禁：与 convert_3d.py 同名开关一一对应，默认关闭。
        p.add_argument("--strict-watertight", action="store_true",
                       default=PRINT_FLAG_DEFAULTS["strict_watertight"],
                       help="最终网格非水密时拒绝导出（底层退出码 3）")
        p.add_argument("--drop-floating-parts", action="store_true",
                       default=PRINT_FLAG_DEFAULTS["drop_floating_parts"],
                       help="导出前按拓扑剔除悬空碎块，只保留最大连通实体（多件分体设计勿启用）")
        p.add_argument("--strict-single-body", action="store_true",
                       default=PRINT_FLAG_DEFAULTS["strict_single_body"],
                       help="落地 STL 必须是单一连通实体，否则验收 FAIL 并返回非零（需 --formats 含 stl）")

    p = sub.add_parser("img", help="仅出图")
    p.add_argument("prompt")
    add_img_opts(p)
    p.set_defaults(func=cmd_img)

    # ★★ 图生图 img2img ★★
    p = sub.add_parser("i2i", help="图生图：参考图+提示词重绘（img2img）")
    p.add_argument("image", help="参考图路径")
    p.add_argument("prompt", help="英文提示词")
    add_img_opts(p)
    p.add_argument("--strength", type=float, default=0.3,
                   help="重绘强度(denoise)：0.3=尽量保留参考图（默认），数值越大变化越大")
    p.add_argument("--style", choices=["original", "figure_render", "figure_photo"],
                   default="original", help="目标风格：保留原画、手办渲染或手办实拍")
    p.add_argument("--engine", choices=["pony", "qwen"], default="pony",
                   help="图生图引擎：Pony 或 Qwen 2509 手办编辑流程")
    p.add_argument("--structure", choices=["none", "canny"], default="none",
                   help="使用 SDXL Canny 控制原图轮廓（不等于姿势识别）")
    p.add_argument("--control-strength", type=float, default=0.65,
                   help="轮廓约束强度，建议 0.4–0.8")
    p.add_argument("--refs", nargs="*", default=[],
                   help="额外的参考图（最多 2 张，仅 --engine qwen）：人物/服装/配色参考")
    p.set_defaults(func=cmd_img2img)

    p = sub.add_parser("model", help="仅图生3D")
    p.add_argument("image")
    add_3d_opts(p)
    p.set_defaults(func=cmd_model)

    p = sub.add_parser("edit_image", help="按修改要求编辑已有图片")
    p.add_argument("image")
    p.add_argument("instruction")
    p.add_argument("--mask", default=None, help="可选的黑白遮罩：白色为允许修改的区域")
    p.add_argument("--method", choices=("auto", "local", "remove", "whole", "ai", "fast"),
                   default="auto",
                   help="局部重绘(local/auto/remove) / 整图重生成(whole,ai)；fast 已停用")
    p.add_argument("--seed", type=int, default=-1, help="随机种子；-1=每次随机（推荐）")
    p.add_argument("--attempts", type=int, default=1,
                   help="主方案最多尝试次数（默认1；检测到噪点时可显式设为2）")
    p.add_argument("--candidates", type=int, default=1, help="额外生成几张备选方案（1~3，用于挑选）")
    p.add_argument("--steps", type=int, default=16, help="Qwen 采样步数（8~30；16=平衡，20=精修）")
    p.add_argument("--no-crop-local", action="store_true",
                   help="局部重绘时不做“裁剪放大重绘”（默认会做，边缘更清晰）")
    p.add_argument("--refs", nargs="*", default=[],
                   help="额外的参考图（最多 2 张）：作为尺寸/设计参考传给 Qwen 编辑")
    p.set_defaults(func=cmd_edit_image)

    p = sub.add_parser("multiview", help="多视图测试图：按方位逐张生成（前/后/左/右 + 4 斜侧位）")
    p.add_argument("image", help="主图")
    p.add_argument("--views", nargs="+", default=["front"],
                   choices=list(MV_VIEWS.keys()),
                   help="要生成的方位：front/back/left/right/front_left/front_right/back_left/back_right")
    p.add_argument("--prompt", default="", help="整体要求（自然语言，中文可）")
    p.add_argument("--extra", default="", help="这一张的单独要求")
    p.add_argument("--refs", nargs="*", default=[], help="额外一致性参考图（最多 2 张，如已生成的其他视图）")
    p.add_argument("--seed", type=int, default=-1, help="随机种子；-1=每次随机")
    p.set_defaults(func=cmd_multiview)

    p = sub.add_parser("mv3d", help="多视图（姿势锁定）：build 建 3D 粗模 → render 用 Blender 渲染 8 方位")
    p.add_argument("image", help="主图")
    p.add_argument("--stage", required=True, choices=["build", "render", "repaint"],
                   help="build=建 3D 粗模；render=渲染 N 个方位；repaint=旧的灰模重绘路径")
    p.add_argument("--engine", choices=["hunyuan", "meshy"], default="hunyuan",
                   help="build 用：hunyuan=本地免费（灰模）；meshy=云端带贴图（约30积分，彩色）")
    p.add_argument("--meshy-desensitize", dest="meshy_desensitize", action="store_true", default=None,
                   help="Meshy build 时上传前先脱敏")
    p.add_argument("--views", nargs="+", default=list(MV_VIEWS.keys()), choices=list(MV_VIEWS.keys()))
    p.add_argument("--glb", default=None, help="render 用：3D 模型路径")
    p.add_argument("--size", type=int, default=1024, help="render 分辨率")
    p.add_argument("--clay", nargs="+", default=[], help="repaint 用：方位:灰模路径")
    p.add_argument("--prompt", default="", help="整体要求")
    p.add_argument("--octree-res", type=int, default=512, choices=[256, 384, 512],
                   help="与 add_3d_opts 同默认：512 高精度，384 兼容旧链路")
    p.add_argument("--seed", type=int, default=-1)
    p.set_defaults(func=cmd_mv3d)

    p = sub.add_parser("model_edit", help="导入 3D 模型，按自然语言要求修改模型文件")
    p.add_argument("model", help="模型文件（glb/gltf/obj/stl/3mf/ply）")
    p.add_argument("--instruction", required=True, help="修改要求（自然语言）")
    p.add_argument("--edit-mode", choices=["texture", "rebuild"], default="texture",
                   help="texture=渲染→AI修改→贴图投影回模型（快）；rebuild=渲染→AI修改→Meshy重建（约20积分）")
    p.add_argument("--meshy-desensitize", dest="meshy_desensitize", action="store_true", default=None)
    p.add_argument("--size", type=int, default=1024)
    p.add_argument("--seed", type=int, default=-1)
    p.set_defaults(func=cmd_model_edit)

    p = sub.add_parser("image_print", help="参考图片直接生成3D并转换打印格式")
    p.add_argument("image")
    add_3d_opts(p)
    add_print_opts(p)
    p.set_defaults(func=cmd_image_print)

    p = sub.add_parser("print", help="转 3D 打印格式")
    p.add_argument("model")
    add_print_opts(p)
    p.set_defaults(func=cmd_print)

    p = sub.add_parser("all", help="出图 -> 图生3D -> 打印格式")
    p.add_argument("prompt")
    add_img_opts(p)
    add_3d_opts(p)
    add_print_opts(p)
    p.set_defaults(func=cmd_all)

    p = sub.add_parser("doctor", help="环境自检")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("prompt", help="中文描述 -> 英文 tags 提示词（本地大脑）")
    p.add_argument("desc")
    p.add_argument("--brain", default=DEFAULT_BRAIN)
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("auto", help="全自动：中文 -> 大脑 -> 出图 -> 3D -> 打印格式")
    p.add_argument("desc")
    p.add_argument("--brain", default=DEFAULT_BRAIN)
    add_img_opts(p)
    add_3d_opts(p)
    add_print_opts(p)
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("serve", help="启动 ComfyUI")
    p.add_argument("--port", type=int, default=8188)
    p.set_defaults(func=cmd_serve)

    # ★★ 去敏感化 ★★
    p = sub.add_parser("desensitize",
                       help="图像去敏感化（过 Meshy/建模AI审核）")
    p.add_argument("image", help="输入图片路径")
    p.add_argument("-o", "--output", default=None,
                   help="输出路径（默认 原名_desensitized.png）")
    p.add_argument("--strength", default="auto",
                   choices=["auto", "full", "minimal"],
                   help="遮挡强度。auto=自动检测高风险区域(默认)；"
                        "full=全身肤色遮挡(最保守)；minimal=只遮挡裆部")
    p.add_argument("--no-clothe", action="store_true",
                   help="不用服装色覆盖（只用像素化）")
    p.add_argument("--no-pixelate", action="store_true",
                   help="不做像素化（只用服装色覆盖）")
    p.set_defaults(func=cmd_desensitize)

    # ★★ 还原 ★★
    p = sub.add_parser("restore",
                       help="把去敏化后的3D模型还原成敏感样子")
    p.add_argument("model", help="3D 模型路径（Meshy 输出的 .glb/.obj）")
    p.add_argument("--original", default=None,
                   help="敏感原图路径（用于纹理参考）")
    p.add_argument("-o", "--output", default=None,
                   help="输出路径")
    p.set_defaults(func=cmd_restore)

    a = ap.parse_args()
    try:
        try:
            sys.exit(a.func(a) or 0)
        except KeyboardInterrupt:
            print("\n[!] 已中断")
            sys.exit(130)
    finally:
        # 覆盖正常退出 / SystemExit / 未捕获异常；atexit 作为兜底。
        _cleanup_comfyui_on_exit()


if __name__ == "__main__":
    main()
