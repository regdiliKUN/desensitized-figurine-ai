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
import re
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

HOST = "http://127.0.0.1:8188"
# ★ 程序代码 + ComfyUI + 模型权重在 SSD (E:\AI) 加速推理
#   输出文件（出图/3D模型）也在 SSD（ComfyUI/output 默认就在 ComfyUI 下）
#   最终成品（STL/3MF）可转存到 HDD (I:\AI\最终成品) 不影响速度
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ComfyUI", "output")  # 动态跟随脚本位置
# 最终成品目录（HDD，不影响运行速度）
FINAL_DIR = r"I:\AI\最终成品"

# ★ 3D 后处理需要 trimesh，而 trimesh 装在 CadQuery venv 里（ComfyUI venv 没有）。
#   自动探测可用解释器，避免 "ModuleNotFoundError: No module named 'trimesh'"。
def _find_py_with_trimesh():
    cands = [
        r"C:\Users\xukunhang\.venvs\cadquery\Scripts\python.exe",
        os.path.join(HERE, "venv_trimesh", "Scripts", "python.exe"),
    ]
    for c in cands:
        if os.path.exists(c):
            try:
                import subprocess
                r = subprocess.run([c, "-c", "import trimesh"],
                                   capture_output=True, timeout=30)
                if r.returncode == 0:
                    return c
            except Exception:
                continue
    # 退而求其次：用当前解释器（可能已装 trimesh）
    try:
        import trimesh  # noqa
        return sys.executable
    except ImportError:
        return sys.executable


PY = _find_py_with_trimesh()

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# cmd_img 选中的最佳出图路径（供 cmd_all 取用）
_LAST_PICKED = None
_LAST_GLB = None

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


def build_3d_wf(image_name, steps=30, resolution=3072, threshold=0.6, prefix="figure_3d",
                faces=400000, crease=60.0, do_uv=True, do_preview=True,
                uv_resolution=2048, weld_distance=0.0,
                remesh_res=512, smooth_iters=3, band=1.0, project_back=0.0,
                high_precision=True):
    """Hunyuan3D 2.1 图生3D（ComfyUI 核心原生节点）

    ★ 高精度路径（high_precision=True，默认）
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
              "inputs": {"samples": ["7", 0], "vae": ["1", 2], "num_chunks": 8000, "octree_resolution": 256}},
        "9": {"class_type": "VoxelToMesh", "inputs": {"voxel": ["8", 0], "threshold": threshold, "algorithm": "surface net"}},
    }
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
        p = f"{OUT}/{sub}/{fn}".replace("//", "/")
        print(f"[✓] {p}  (seed={seed})")

        if not a.check_bg:
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


def cmd_img2img(a):
    """图生图（img2img）：上传参考图 + 提示词 -> ComfyUI 重绘。

    核心参数 --strength（denoise）控制重绘强度：
      1.0 = 完全重画（几乎不保留原图）   0.7 = 大幅修改保留构图（默认推荐）
      0.5 = 适度修改保留大部分细节       0.3 = 轻微调整（换色/小改）
    """
    global _LAST_PICKED
    src = a.image
    if not os.path.isfile(src):
        print(f"[!] 找不到图片: {src}")
        return 1

    pos = a.prompt
    neg = a.neg or DEFAULT_NEG
    denoise = a.strength
    print(f"[*] 图生图: {a.model}  src={os.path.basename(src)}  "
          f"denoise={denoise}  steps={a.steps}")
    vram_warn()

    # 上传参考图到 ComfyUI
    up = upload_image(src)
    image_name = up.get("name")
    if not image_name:
        print(f"[!] 上传失败: {up}")
        return 1
    print(f"    已上传参考图: {image_name}")

    best = None
    attempts = max(1, a.retry)
    for i in range(attempts):
        seed = a.seed + i if a.seed >= 0 else int(time.time() * 1000) % 2**31 + i
        wf = build_img2img_wf(a.model, pos, neg, seed,
                              a.width, a.height, a.steps, denoise, image_name)
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
        p = f"{OUT}/{sub}/{fn}".replace("//", "/")
        print(f"[✓] {p}  (seed={seed})")

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


def cmd_model(a):
    global _LAST_GLB
    _LAST_GLB = None
    img = a.image
    if not os.path.exists(img):
        print(f"[!] 图片不存在: {img}")
        return 1
    # 背景分离：Hunyuan3D 会把背景里的大件物体也重建成几何体
    if not a.no_isolate:
        iso = os.path.join(os.path.dirname(os.path.abspath(img)),
                           "_iso_" + os.path.basename(img))
        print("[*] 背景分离（只保留角色）...")
        if isolate_background(img, iso, model=a.iso_model,
                              keep_components=a.iso_components):
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
    print(f"[*] 上传 {os.path.basename(img)} ...")
    up_name = upload_image(img).get("name")
    print(f"[*] 图生3D  resolution={a.resolution} steps={a.steps3d} faces<={a.faces}")
    wf = build_3d_wf(up_name, a.steps3d, a.resolution, threshold=a.threshold,
                      prefix=a.prefix, faces=a.faces, crease=a.crease,
                      uv_resolution=a.uv_resolution, weld_distance=a.weld_distance,
                      do_uv=a.uv, do_preview=not a.no_preview,
                      remesh_res=a.remesh_res, smooth_iters=a.smooth_iters,
                      band=a.remesh_band, project_back=a.project_back,
                      high_precision=not a.low_precision)
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
        p = f"{OUT}/{sub}/{fn}".replace("//", "/")
        sz = os.path.getsize(p) / 1e6 if os.path.exists(p) else 0
        print(f"[✓] {fn}  ({typ}, {sz:.2f} MB)\n    {p}")
        if fn.lower().endswith(".glb") and glb is None:
            glb = p
    _LAST_GLB = glb
    return 0


def cmd_print(a):
    cmd = [PY, os.path.join(HERE, "convert_3d.py"), a.model,
           "--out-dir", a.out_dir, "--to"] + a.formats
    if a.out_prefix:
        cmd += ["--out-prefix", a.out_prefix]
    # ★ 高精度路径：RemeshMesh(sign_mode=solid) 产出的网格本身已水密，
    #   再做体素重建(marching cubes)会把精细表面碾成 20%+ 锐边的粗糙块。
    #   因此默认关闭 --solidify，改用 Taubin 平滑（保体积、只清高频伪影）。
    if a.solidify:
        cmd.append("--solidify")
    # 尺寸校正：RemeshMesh 输出未反归一化（固定在 [-0.5,0.5] 立方体）
    if a.ref_model and os.path.exists(a.ref_model):
        cmd += ["--ref", a.ref_model]
    if a.decimate > 0:
        cmd += ["--decimate", str(a.decimate)]
    if a.smooth != 10:
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
            new_files = [f for f in os.listdir(OUT)
                         if f.endswith(".png") and f.startswith("fig_img")]
        if not new_files:
            print("[!] 找不到出图文件")
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
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
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
            return True, "无需处理（肤色极少）"

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
            return True, "无需遮挡"

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
    print(" 图像去敏感化（过 Meshy/建模 AI 审核）")
    print("=" * 58)
    print(f"  输入: {src}")
    print(f"  输出: {dst}")
    print(f"  强度: {a.strength}")

    ok, info = _desensitize_image(src, dst, strength=a.strength,
                                  clothed=not a.no_clothe,
                                  pixelate=not a.no_pixelate)
    if ok:
        print(f"\n[✓] 去敏化完成: {dst}")
        print(f"    {info}")
        print("\n  下一步:")
        print(f"    1. 把 {dst} 上传 Meshy / 其他建模 AI 生成 3D")
        print(f"    2. 下载 3D 模型")
        print(f"    3. 用 fig.py restore 还原（如有需要）")
    else:
        print(f"\n[!] 失败: {info}")
    return 0 if ok else 1


def cmd_restore(a):
    """还原子命令：把去敏化后的 3D 模型还原成敏感样子。

    策略：
    1. 如果有原图和去敏化图的对应关系，用原图作为纹理参考重新烘培
    2. 如果只有 3D 模型，用 trimesh 加载并替换纹理
    3. 本地无法自动「还原裸露」，需要用 ComfyUI img2img 以原图为参考重绘
    """
    model = a.model
    if not os.path.exists(model):
        print(f"[!] 模型不存在: {model}")
        return 1

    print("=" * 58)
    print(" 3D 模型还原（去敏化版 → 敏感样子）")
    print("=" * 58)
    print(f"  模型: {model}")

    if a.original:
        print(f"  原图: {a.original}")
    else:
        # 尝试自动找原图（去掉 _desensitized 后缀）
        base = os.path.splitext(os.path.basename(model))[0]
        dir_ = os.path.dirname(os.path.abspath(model))
        for suffix in ['_desensitized', '_desen']:
            cand = os.path.join(dir_, base.replace(suffix, '') + '.png')
            if os.path.exists(cand):
                a.original = cand
                print(f"  自动找到原图: {cand}")
                break

    if a.original and os.path.exists(a.original):
        print("\n  还原策略：以原图为参考，用 img2img 重烘培纹理")
        print("  （需要 ComfyUI 运行中）")
        print("\n  [提示] 还原流程：")
        print("    1. 用 trimesh 从 3D 模型提取 UV 展开")
        print("    2. 用原图对 UV 做纹理投影")
        print("    3. 重新烘培到模型纹理")
        print("    4. 或：用 ComfyUI img2img 以原图为 prompt 参考重绘")

        # 实际操作：用 trimesh 加载模型，检查是否有纹理
        try:
            import subprocess as sp
            cmd = [PY, "-c", f"""
import trimesh, sys
m = trimesh.load(r'{model}', force='mesh', process=False)
print(f"顶点: {{len(m.vertices):,}}  面: {{len(m.faces):,}}")
if m.visual.kind == 'texture':
    print("有纹理，可以替换")
    tex = m.visual.material
    print(f"纹理图: {{tex}}")
else:
    print("无纹理（纯色/顶点色），还原需要重新 UV + 投影")
"""]
            sp.run(cmd, timeout=60)
        except Exception as e:
            print(f"  (模型检查失败: {e})")

        if a.output:
            out = a.output
        else:
            out = os.path.splitext(model)[0] + "_restored.glb"
        print(f"\n  输出: {out}")
        print("\n  [!] 自动还原需要图像到3D的纹理迁移，当前版本提供指导。")
        print("      建议：把原图和模型一起放入 ComfyUI 做 img2img 纹理烘培。")
    else:
        print("\n  [!] 未找到原图。请用 --original 指定敏感原图路径。")
        print("      没有原图无法自动还原。")

    return 0


# ----------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(
        prog="fig.py", description="二次元手办本地流水线统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_img_opts(p):
        p.add_argument("--model", default="pony", choices=["pony", "flux"])
        p.add_argument("--neg", default=None)
        p.add_argument("--seed", type=int, default=123456)
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
        p.add_argument("--steps3d", type=int, default=30)
        p.add_argument("--resolution", type=int, default=3072)
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
                       help="用旧的低精度路径（VoxelToMesh+Decimate，快但表面阶梯状）")
        p.add_argument("--iso-model", default="isnet-anime",
                       help="rembg 分割模型。isnet-anime=二次元角色专用(推荐)；"
                            "u2net=通用；birefnet-general=高精但慢")
        p.add_argument("--iso-components", type=int, default=3,
                       help="背景分离时保留的最大连通块数量（0=不清理）。"
                            "用于剔除与角色分离的背景碎片")
        # ★ 色调平坦化：压缩 cel shading 阴影，消除 3D 蜂窝纹
        p.add_argument("--no-flatten", action="store_true",
                       help="跳过色调平坦化（默认开启，消除蜂窝纹伪影）")
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
        p.add_argument("--smooth", type=int, default=10,
                       help="Taubin 平滑迭代次数（默认 10）。清除像素纹理伪影")
        p.add_argument("--model-height", type=float, default=0.0,
                       help="成品高度(mm)。指定后自动按比例缩放，取代 --scale")
        p.add_argument("--out-prefix", default=None,
                       help="输出文件名前缀（不含扩展名）")
        # ★★ 手板制作增强参数 ★★
        p.add_argument("--no-orient", action="store_true",
                       help="跳过自动扶正朝向（默认自动把模型竖立到 Z 轴）")
        p.add_argument("--base", type=float, default=0.03, nargs="?", const=0.03,
                       help="加圆柱底座。参数=厚度比例(0.03=3%%高度)。如 --base 0.05")
        p.add_argument("--no-base", dest="base", action="store_const", const=0.0,
                       help="不加底座")
        p.add_argument("--hollow", type=float, default=0.0, nargs="?", const=0.05,
                       help="抽壳省树脂。参数=壁厚比例(0.05=5%%对角线)。如 --hollow 0.03")
        p.add_argument("--no-hollow", dest="hollow", action="store_const", const=0.0,
                       help="不抽壳（默认）")
        p.add_argument("--no-diagnose", action="store_true",
                       help="关闭打印前诊断报告")

    p = sub.add_parser("img", help="仅出图")
    p.add_argument("prompt")
    add_img_opts(p)
    p.set_defaults(func=cmd_img)

    # ★★ 图生图 img2img ★★
    p = sub.add_parser("i2i", help="图生图：参考图+提示词重绘（img2img）")
    p.add_argument("image", help="参考图路径")
    p.add_argument("prompt", help="英文提示词")
    add_img_opts(p)
    p.add_argument("--strength", type=float, default=0.7,
                   help="重绘强度(denoise)。1.0=完全重画 / 0.7=大幅修改保留构图(默认) "
                        "/ 0.5=适度修改 / 0.3=轻微调整")
    p.set_defaults(func=cmd_img2img)

    p = sub.add_parser("model", help="仅图生3D")
    p.add_argument("image")
    add_3d_opts(p)
    p.set_defaults(func=cmd_model)

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
        sys.exit(a.func(a) or 0)
    except KeyboardInterrupt:
        print("\n[!] 已中断")
        sys.exit(130)


if __name__ == "__main__":
    main()
