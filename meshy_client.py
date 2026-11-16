# -*- coding: utf-8 -*-
"""Meshy 官方 API 客户端（手办 AI 流水线用）。

用法：
    python meshy_client.py balance                      # 查积分（免费）
    python meshy_client.py image2 图.png [--out-dir ...]  # 图生3D（消耗积分，默认 mesh-only 20 credits）
    python meshy_client.py task <task_id>               # 查任务
    python meshy_client.py download <task_id> <out.glb> # 下载已完成任务的 GLB

配置读取顺序：
    1) 环境变量 MESHY_API_KEY
    2) E:\\AI\\meshy_config.json 的 api_key 字段
API key 不会打印到日志里。
"""
import argparse
import base64
import datetime
import io
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "meshy_config.json")
BASE = "https://api.meshy.ai/openapi/v1"
DEFAULT_MODEL = "meshy-7.1"
POLL_INTERVAL = 5          # 秒
DEFAULT_TIMEOUT = 1200     # 20 分钟（含排队）


def _load_config():
    cfg = {}
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except (OSError, json.JSONDecodeError):
            cfg = {}
    return cfg


CONFIG = _load_config()


def api_key():
    key = os.environ.get("MESHY_API_KEY", "").strip()
    if not key:
        key = str(CONFIG.get("api_key", "")).strip()
    if not key:
        raise RuntimeError("未配置 Meshy API key：请设置环境变量 MESHY_API_KEY 或填写 E:\\AI\\meshy_config.json")
    return key


def _retry_after_seconds(value, attempt):
    """R59：把 Retry-After 解析成有界的等待秒数。

    RFC 7231 允许 Retry-After 是「整数秒」或「HTTP-date」。旧实现直接
    ``float(value)``，遇到 HTTP-date 会抛 ValueError —— 恰恰在最需要退避的
    429 场景里让请求链崩溃并暴露裸栈；负数、NaN、超大值也没有上界。
    这里统一返回 ``[0, 30]`` 区间内的秒数，解析不了就退回指数退避。
    """
    fallback = min(30, 2 ** (attempt + 1))
    if value is None:
        return float(fallback)
    text = str(value).strip()
    if not text:
        return float(fallback)
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
            if when.tzinfo is None:
                when = when.replace(tzinfo=datetime.timezone.utc)
            seconds = (when - datetime.datetime.now(
                datetime.timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return float(fallback)
    if not math.isfinite(seconds):
        return float(fallback)
    return float(max(0.0, min(30.0, seconds)))


class InsufficientBalanceError(RuntimeError):
    """余额不足：必须中止任务。其它余额查询失败（网络/密钥）只告警不阻断。"""


def _request(method, path, payload=None, timeout=60, allow_retry=True):
    """发请求；429 按 Retry-After 退避，5xx/网络错误最多重试 3 次。"""
    url = BASE + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    headers = {"Authorization": "Bearer " + api_key()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    last_error = None
    for attempt in range(3 if allow_retry else 1):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            last_error = f"HTTP {exc.code}: {body}"
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if exc.code == 429 or exc.code >= 500:
                # R59：秒数 / HTTP-date / 非法值都走同一套有界解析，不再裸抛。
                wait = _retry_after_seconds(retry_after, attempt)
                print(f"    [meshy] {exc.code}，{wait:.0f}s 后重试……", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"Meshy API 出错：{last_error}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"无法连接 Meshy API：{exc}（检查网络/代理）") from exc
    raise RuntimeError(f"Meshy API 重试后仍失败：{last_error}")


def balance():
    """返回账户剩余积分（数字）。"""
    data = _request("GET", "/balance")
    return data.get("balance")


def _atomic_json(path, data):
    """同目录 staging + os.replace，避免进程中断留下半截 JSON。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".",
                               suffix=".part", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def data_uri(image_path):
    """把本地图片编码成 Meshy 接受的 data URI（≤20MB），并校验真实格式/尺寸。

    不能只看扩展名：``x.png`` 实际是 JPEG、损坏图、32px 以下小图都会被 Meshy
    以 400 拒绝。这里在付费任务提交前本地拦下，并选用真实 MIME 类型。
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(image_path)
    size = os.path.getsize(image_path)
    if size > 20 * 1024 * 1024:
        raise ValueError(f"图片超过 Meshy 20MB 限制（{size/1048576:.1f}MB）: {image_path}")
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            fmt = (im.format or "").upper()
            width, height = im.size
            im.verify()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"图片无法解码，不能上传 Meshy: {image_path}（{exc}）") from exc
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(fmt)
    if not mime:
        raise ValueError(f"Meshy 仅支持 JPG/PNG/WEBP，当前文件真实格式为 {fmt or '未知'}: {image_path}")
    if width < 32 or height < 32:
        raise ValueError(f"图片尺寸过小（{width}×{height}），Meshy 要求每边至少 32px")
    with open(image_path, "rb") as f:
        raw = f.read()
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def create_image_to_3d(image_path, ai_model=DEFAULT_MODEL, geometry_resolution="standard",
                       should_texture=False, texture_model=None, texture_resolution=None,
                       enable_pbr=False, should_remesh=True, target_polycount=0,
                       target_formats=("glb",), model_type="standard", pose_mode=None):
    """提交 Image to 3D 任务，返回 task_id。图片以 data URI 上传（≤20MB）。"""
    payload = {
        "image_url": data_uri(image_path),
        "model_type": model_type,
        "ai_model": ai_model,
        "geometry_resolution": geometry_resolution,
        "should_texture": bool(should_texture),
        "target_formats": list(target_formats),
    }
    if should_texture:
        if texture_model:
            payload["texture_model"] = texture_model
        if texture_resolution:
            payload["texture_resolution"] = texture_resolution
        payload["enable_pbr"] = bool(enable_pbr)
    if should_remesh:
        payload["should_remesh"] = True
        if target_polycount:
            payload["target_polycount"] = int(target_polycount)
    if pose_mode:
        payload["pose_mode"] = pose_mode
    result = _request("POST", "/image-to-3d", payload, timeout=120)
    task_id = result.get("result")
    if not task_id:
        raise RuntimeError(f"提交任务失败，返回：{result}")
    return task_id


def get_task(task_id):
    return _request("GET", f"/image-to-3d/{task_id}")


def wait_task(task_id, timeout=DEFAULT_TIMEOUT, poll=POLL_INTERVAL):
    """轮询到终态；返回任务对象（status == SUCCEEDED 时才读结果 URL）。"""
    started = time.time()
    last_progress = -1
    while time.time() - started < timeout:
        task = get_task(task_id)
        status = task.get("status")
        progress = int(task.get("progress") or 0)
        if progress != last_progress and progress % 10 == 0:
            print(f"    [meshy] {status} {progress}%", flush=True)
            last_progress = progress
        if status == "SUCCEEDED":
            if progress != 100:
                # 官方要求 status 与 progress 同时确认
                time.sleep(max(1, poll))
                continue
            return task
        if status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"Meshy 任务 {status}：{json.dumps(task.get('task_error') or {}, ensure_ascii=False)}")
        time.sleep(poll)
    raise TimeoutError(f"Meshy 任务超时（{timeout}s）：{task_id}")


def create_image_to_image(image_path, prompt, ai_model="nano-banana",
                          generate_multi_view=True, remove_background=True):
    """用 Meshy 图生图生成同一角色的多视角参考；返回 task_id。

    ``generate_multi_view=True`` 时返回通常 3 个视角 URL；Meshy 不保证
    固定为 front/left/back，必须由调用方下载后按视觉/顺序确认，不能凭
    下标记对应方位。
    """
    payload = {
        "ai_model": ai_model,
        "prompt": prompt,
        "reference_image_urls": [data_uri(image_path)],
        "generate_multi_view": bool(generate_multi_view),
        "remove_background": bool(remove_background),
    }
    result = _request("POST", "/image-to-image", payload, timeout=120)
    task_id = result.get("result")
    if not task_id:
        raise RuntimeError(f"Meshy image-to-image 提交失败：{result}")
    return task_id


def get_image_to_image_task(task_id):
    return _request("GET", f"/image-to-image/{task_id}")


def create_multi_image_to_3d(image_paths, ai_model=DEFAULT_MODEL,
                             geometry_resolution="standard", should_texture=False,
                             texture_model=None, texture_resolution=None,
                             enable_pbr=False, should_remesh=False,
                             target_polycount=0, target_formats=("glb",),
                             texture_image_paths=None, texture_prompt=None):
    """提交官方 Multi-Image to 3D；1–4 张同物体视图，第一张必须是 front。"""
    if not image_paths:
        raise ValueError("Multi-Image to 3D 需要至少 1 张图")
    if len(image_paths) > 4:
        raise ValueError("Multi-Image to 3D 最多 4 张图")
    payload = {
        "image_urls": [data_uri(p) for p in image_paths],
        "ai_model": ai_model,
        "geometry_resolution": geometry_resolution,
        "should_texture": bool(should_texture),
        "target_formats": list(target_formats),
        "remove_lighting": True,
    }
    if should_texture:
        if texture_model:
            payload["texture_model"] = texture_model
        if texture_resolution:
            payload["texture_resolution"] = texture_resolution
        payload["enable_pbr"] = bool(enable_pbr)
        if texture_image_paths:
            if len(texture_image_paths) > 4:
                raise ValueError("texture_image_urls 最多 4 张")
            payload["texture_image_urls"] = [data_uri(p) for p in texture_image_paths]
        if texture_prompt:
            payload["texture_prompt"] = texture_prompt[:800]
    if should_remesh:
        payload["should_remesh"] = True
        if target_polycount:
            payload["target_polycount"] = int(target_polycount)
    result = _request("POST", "/multi-image-to-3d", payload, timeout=180)
    task_id = result.get("result")
    if not task_id:
        raise RuntimeError(f"Meshy multi-image-to-3d 提交失败：{result}")
    return task_id


def get_multi_image_task(task_id):
    return _request("GET", f"/multi-image-to-3d/{task_id}")


def wait_endpoint_task(task_id, getter, timeout=DEFAULT_TIMEOUT, poll=POLL_INTERVAL,
                       label="Meshy"):
    """按指定 endpoint 轮询任务；Multi-Image / Image-to-Image 与单图任务不同源。"""
    started = time.time()
    last_progress = -1
    while time.time() - started < timeout:
        task = getter(task_id)
        status = task.get("status")
        progress = int(task.get("progress") or 0)
        if progress != last_progress and progress % 10 == 0:
            print(f"    [meshy] {label} {status} {progress}%", flush=True)
            last_progress = progress
        if status == "SUCCEEDED":
            if progress != 100:
                time.sleep(max(1, poll))
                continue
            return task
        if status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"Meshy {label} 任务 {status}："
                               f"{json.dumps(task.get('task_error') or {}, ensure_ascii=False)}")
        time.sleep(poll)
    raise TimeoutError(f"Meshy {label} 任务超时（{timeout}s）：{task_id}")


def _view_foreground_mask(path, size=128):
    """读取视图前景 mask；透明 PNG 用 alpha，白底图用非白像素。"""
    from PIL import Image
    import numpy as np
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
        rgba.thumbnail((size, size), Image.Resampling.LANCZOS)
        arr = np.asarray(rgba)
        alpha = arr[..., 3]
        if alpha.min() < 250:
            mask = alpha > 16
        else:
            rgb = arr[..., :3].astype(np.int16)
            mask = (rgb.max(axis=2) < 245) | ((rgb.max(axis=2) - rgb.min(axis=2)) > 10)
    return mask


def _pick_front_view(view_paths, source_path, auto=True):
    """把与源参考轮廓最接近的视图排到第一张（Multi-Image 要求 front 在首位）。

    Meshy image-to-image 只保证返回多张视图，不承诺固定顺序。多图接口又明确
    「第一张作为正视图」；顺序错会把侧面当正面，浪费一次付费重建。这里用
    前景轮廓 IoU 选 front，差距不足 0.03 时保持原顺序，避免过度猜测。

    ``auto=False`` 用于用户显式通过 --mv-refs 指定顺序的复用场景：此时必须
    尊重调用方给的 front，不能再用轮廓分数偷偷重排。
    """
    if not auto or len(view_paths) < 2:
        return list(view_paths), {"front_index": 0, "front_iou": None,
                                  "reordered": False, "assumed": not auto}
    try:
        from PIL import Image
        import numpy as np
        src = _view_foreground_mask(source_path)
        scores = []
        for path in view_paths:
            mask = _view_foreground_mask(path)
            h = max(src.shape[0], mask.shape[0])
            w = max(src.shape[1], mask.shape[1])
            a = np.zeros((h, w), dtype=bool); b = np.zeros((h, w), dtype=bool)
            a[:src.shape[0], :src.shape[1]] = src
            b[:mask.shape[0], :mask.shape[1]] = mask
            union = np.logical_or(a, b).sum()
            scores.append(float(np.logical_and(a, b).sum() / union) if union else 0.0)
        best = max(range(len(scores)), key=scores.__getitem__)
        second = max((s for i, s in enumerate(scores) if i != best), default=0.0)
        ordered = list(view_paths)
        reordered = best != 0 and scores[best] - second >= 0.03
        if reordered:
            ordered.insert(0, ordered.pop(best))
            print(f"    [meshy-mv] 自动把 view{best} 排为 front（轮廓 IoU "
                  f"{scores[best]:.3f} vs 次优 {second:.3f}）", flush=True)
        return ordered, {"front_index": best, "front_iou": round(scores[best], 4),
                         "second_iou": round(second, 4), "reordered": reordered,
                         "all_iou": [round(s, 4) for s in scores]}
    except Exception as exc:  # noqa: BLE001
        print(f"    [meshy-mv] front 自动识别跳过（{type(exc).__name__}: {exc}）", flush=True)
        return list(view_paths), {"front_index": 0, "front_iou": None, "reordered": False}


def estimate_multiview_credits(geometry_resolution="standard", generate_views=True,
                               should_texture=False, image_model="nano-banana"):
    """估算一次 Meshy 多视图的积分消耗，用于提交前预检与 UI 文案。"""
    geometry = 25 if geometry_resolution == "2k" else 20
    image_cost = {"nano-banana": 3, "nano-banana-2": 6,
                  "nano-banana-pro": 9, "gpt-image-2": 9}.get(image_model, 3)
    return geometry + (image_cost if generate_views else 0) + (10 if should_texture else 0)


def multiview_to_3d(image_path, out_dir=None, prompt=None, ai_model=DEFAULT_MODEL,
                    geometry_resolution="standard", should_texture=False,
                    texture_model=None, texture_resolution=None, enable_pbr=False,
                    should_remesh=False, target_polycount=0, prefix="meshy_mv",
                    image_model="nano-banana", timeout=DEFAULT_TIMEOUT,
                    keep_views_dir=None, view_paths=None, min_balance=None,
                    known_balance=None):
    """一站式官方多视图：图生图生成多视角 → Multi-Image to 3D → 下载 GLB。

    ``view_paths`` 非空时直接复用已有 1–4 张视图（第一张必须是 front），
    跳过 image-to-image，避免重复消耗积分；重新导出不同网格参数时尤其有用。
    否则会先检查余额，低于 ``min_balance`` 时在提交前中止。

    返回 ``(glb_path, view_paths, task)``。生成的中间视图保存在
    ``keep_views_dir``（缺省 ``out_dir/_meshy_views``），并落盘 views 清单。
    """
    out_dir = out_dir or os.path.join(HERE, "ComfyUI", "output")
    views_dir = keep_views_dir or os.path.join(out_dir, "_meshy_views")
    os.makedirs(views_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    i2i_id = None
    i2i_task = None
    explicit_views = bool(view_paths)

    if view_paths:
        view_paths = [os.path.abspath(p) for p in view_paths]
        if not 2 <= len(view_paths) <= 4:
            raise ValueError("复用视图必须为 2–4 张；单视图请用 Meshy 单图模式")
        missing = [p for p in view_paths if not os.path.isfile(p)]
        if missing:
            raise FileNotFoundError("视图不存在: " + ", ".join(missing))
        need = int(min_balance) if min_balance is not None else estimate_multiview_credits(
            geometry_resolution=geometry_resolution, generate_views=False,
            should_texture=should_texture, image_model=image_model)
        try:
            bal = known_balance if known_balance is not None else balance()
            if bal is not None and int(bal) < need:
                raise InsufficientBalanceError(f"Meshy 余额不足：当前 {bal}，复用视图重建至少需要约 {need} 积分")
            print(f"[meshy-mv] 复用已有 {len(view_paths)} 张视图，预计约 {need} 积分", flush=True)
        except InsufficientBalanceError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[meshy-mv] 余额查询失败，继续尝试: {exc}", flush=True)
        print(f"[meshy-mv] 复用已有 {len(view_paths)} 张视图，跳过 image-to-image", flush=True)
    else:
        need = int(min_balance) if min_balance is not None else estimate_multiview_credits(
            geometry_resolution=geometry_resolution, generate_views=True,
            should_texture=should_texture, image_model=image_model)
        try:
            bal = known_balance if known_balance is not None else balance()
            if bal is not None and int(bal) < need:
                raise InsufficientBalanceError(
                    f"Meshy 余额不足：当前 {bal}，多视图重建至少需要约 {need} 积分")
            print(f"[meshy-mv] 当前余额: {bal}（本次预计约 {need} 积分）", flush=True)
        except InsufficientBalanceError:
            raise
        except Exception as exc:  # noqa: BLE001
            # 余额查询失败不阻断任务，交给创建接口的 402 兜底。
            print(f"[meshy-mv] 余额查询失败，继续尝试: {exc}", flush=True)
        prompt = prompt or (
            "Generate consistent multi-angle views of the SAME character shown in the reference. "
            "Keep identity, hairstyle, outfit, colors, proportions and art style unchanged. "
            "Show the complete character from head to toe, centered, on a clean plain background "
            "with soft even lighting. No text, watermark or extra props.")
        print("[meshy-mv] 生成多视角参考图 ...", flush=True)
        i2i_id = create_image_to_image(image_path, prompt, ai_model=image_model,
                                       generate_multi_view=True, remove_background=True)
        print(f"    [meshy-mv] 视图任务: {i2i_id}", flush=True)
        i2i = wait_endpoint_task(i2i_id, get_image_to_image_task, timeout=timeout,
                                 label="image-to-image")
        i2i_task = i2i
        urls = i2i.get("image_urls") or []
        if len(urls) < 2:
            raise RuntimeError(f"image-to-image 只返回 {len(urls)} 张视图，"
                               "不足以做多视图重建（至少需要 2 张）")
        view_paths = []
        for index, url in enumerate(urls):
            path = download_image(
                url, os.path.join(views_dir, f"{prefix}_{stamp}_view{index}"))
            view_paths.append(path)
            print(f"    [meshy-mv] view{index}: {path}", flush=True)

    # 视图清单：记录来源与顺序，后续可用 --mv-refs / --views 复用，避免重复扣费。
    view_paths, front_info = _pick_front_view(view_paths, image_path, auto=not explicit_views)
    view_manifest = {
        "source": os.path.abspath(image_path),
        "created_at": stamp,
        "image_to_image_task": i2i_id,
        "order": ["front"] + [f"other_{i}" for i in range(1, len(view_paths))],
        "front_detection": front_info,
        "views": view_paths,
    }
    manifest_path = os.path.join(views_dir, f"{prefix}_{stamp}_views.json")
    try:
        _atomic_json(manifest_path, view_manifest)
        if i2i_task:
            _atomic_json(os.path.join(views_dir, f"{prefix}_{stamp}_i2i.json"), i2i_task)
        print(f"    [meshy-mv] 视图清单: {manifest_path}", flush=True)
    except OSError as exc:
        print(f"    ! 视图清单落盘失败: {exc}", flush=True)

    print(f"[meshy-mv] 提交 Multi-Image to 3D（{len(view_paths)} 视图）...", flush=True)
    task_id = create_multi_image_to_3d(
        view_paths, ai_model=ai_model, geometry_resolution=geometry_resolution,
        should_texture=should_texture, texture_model=texture_model,
        texture_resolution=texture_resolution, enable_pbr=enable_pbr,
        should_remesh=should_remesh, target_polycount=target_polycount,
        texture_image_paths=view_paths if should_texture else None)
    print(f"    [meshy-mv] 3D 任务: {task_id}", flush=True)
    task = wait_endpoint_task(task_id, get_multi_image_task, timeout=timeout,
                              label="multi-image-to-3d")
    url = (task.get("model_urls") or {}).get("glb")
    if not url:
        raise RuntimeError(f"Multi-Image to 3d 完成但没有 GLB：{list(task.get('model_urls') or {})}")
    out_path = os.path.join(out_dir, f"{prefix}_{stamp}_{task_id[:8]}.glb")
    download(url, out_path)
    try:
        _atomic_json(os.path.splitext(out_path)[0] + ".task.json", task)
    except Exception:  # noqa: BLE001
        pass
    print(f"    [meshy-mv] 已下载: {out_path}", flush=True)
    return out_path, view_paths, task


def _validate_download(tmp_path, out_path):
    """R58：按目标类型校验下载体，拒绝 HTTP 200 的错误页与截断文件。

    签名 URL 过期或被 CDN 拦截时，服务端可能返回 **HTTP 200 + JSON/HTML
    错误页**；旧实现只看「文件非空」，会把错误页原子替换成 ``.glb`` 并
    返回成功，损坏的「模型」随后流入重建链路却无人报错。GLB 还额外校验
    头部声明的总长度与实际字节数一致，用来抓传输截断。
    """
    ext = os.path.splitext(out_path)[1].lower()
    size = os.path.getsize(tmp_path)
    if size == 0:
        return False, "下载到的文件为空"
    with open(tmp_path, "rb") as f:
        head = f.read(16)
    if ext == ".glb":
        if head[:4] != b"glTF":
            return False, (f"下载体不是 GLB（缺少 glTF 魔数，开头 {head[:8]!r}），"
                           "疑似错误响应或过期签名 URL")
        if size < 12:
            return False, "GLB 头部不足 12 字节"
        declared = int.from_bytes(head[8:12], "little")
        if declared != size:
            return False, (f"GLB 声明长度 {declared} 与实际 {size} 字节不符，"
                           "下载被截断或拼接了错误响应")
    elif ext == ".png":
        if not head.startswith(b"\x89PNG\r\n\x1a\n"):
            return False, "下载体不是 PNG（缩略图链接可能返回错误页）"
    elif ext in (".jpg", ".jpeg"):
        if not head.startswith(b"\xff\xd8"):
            return False, "下载体不是 JPEG"
    return True, None


def download_image(url, dest_prefix, attempts=4):
    """下载远程图片并按真实魔数选择扩展名，返回最终路径。"""
    directory = os.path.dirname(os.path.abspath(dest_prefix))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(dest_prefix) + ".",
                               suffix=".img", dir=directory)
    os.close(fd)
    try:
        download(url, tmp, attempts=attempts)
        with open(tmp, "rb") as f:
            head = f.read(16)
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            ext = ".png"
        elif head.startswith(b"\xff\xd8"):
            ext = ".jpg"
        elif head.startswith(b"RIFF") and head[8:12] == b"WEBP":
            ext = ".webp"
        else:
            raise RuntimeError("下载图片既不是 PNG/JPEG/WEBP，疑似错误页")
        final = dest_prefix + ext
        os.replace(tmp, final)
        tmp = None
        return final
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def download(url, out_path, attempts=4):
    """下载签名 URL（会过期，SUCCEEDED 后尽快下载）；DNS/网络抖动自动重试。

    R58：只有「通过内容签名校验」的文件才会被原子替换到 ``out_path``。
    临时文件按目标同目录唯一命名（旧实现固定 ``.part``，并发下载会互相
    踩踏），任何失败路径都在 ``finally`` 清理，既有合法成品不会被半成品
    或错误响应覆盖。
    """
    out_abs = os.path.abspath(out_path)
    directory = os.path.dirname(out_abs)
    os.makedirs(directory, exist_ok=True)
    last_error = None
    for attempt in range(attempts):
        tmp = None
        try:
            req = urllib.request.Request(url)
            fd, tmp = tempfile.mkstemp(
                prefix="." + os.path.basename(out_abs) + ".",
                suffix=".part", dir=directory)
            with os.fdopen(fd, "wb") as f:
                with urllib.request.urlopen(req, timeout=180) as response:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)
            ok, reason = _validate_download(tmp, out_abs)
            if not ok:
                raise RuntimeError(reason)
            os.replace(tmp, out_abs)
            tmp = None
            return out_path
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            wait = 2 ** (attempt + 1)
            print(f"    [meshy] 下载失败（{exc}），{wait}s 后重试 {attempt + 1}/{attempts}……", flush=True)
            time.sleep(wait)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    raise RuntimeError(f"模型下载失败：{last_error}")


def image_to_3d(image_path, out_dir=None, ai_model=DEFAULT_MODEL,
                geometry_resolution="standard", should_texture=False,
                texture_model=None, texture_resolution=None, enable_pbr=False,
                should_remesh=True, target_polycount=0, prefix="meshy",
                pose_mode=None, timeout=DEFAULT_TIMEOUT):
    """一站式：上传 → 轮询 → 立刻下载 GLB。返回 (glb_path, task_dict)。"""
    task_id = create_image_to_3d(
        image_path, ai_model=ai_model, geometry_resolution=geometry_resolution,
        should_texture=should_texture, texture_model=texture_model,
        texture_resolution=texture_resolution, enable_pbr=enable_pbr,
        should_remesh=should_remesh, target_polycount=target_polycount, pose_mode=pose_mode)
    print(f"    [meshy] 任务已提交: {task_id}", flush=True)
    task = wait_task(task_id, timeout=timeout)
    urls = task.get("model_urls") or {}
    url = urls.get("glb")
    if not url:
        raise RuntimeError(f"任务完成但没有 GLB 结果：{list(urls)}")
    out_dir = out_dir or os.path.join(HERE, "ComfyUI", "output")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"{prefix}_{stamp}_{task_id[:8]}.glb")
    try:
        download(url, out_path)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"模型已生成但下载失败（{exc}）。结果在 Meshy 保留 3 天，可用任务号重下：\n"
            f"    python meshy_client.py download {task_id} 目标.glb") from exc
    print(f"    [meshy] 已下载: {out_path}", flush=True)
    thumb_url = task.get("thumbnail_url")
    # 把任务信息存一份：下载失败/过期时可凭任务号在 3 天内重下
    try:
        meta_path = os.path.splitext(out_path)[0] + ".task.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(task, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    if thumb_url:
        try:
            thumb_path = os.path.splitext(out_path)[0] + "_preview.png"
            download(thumb_url, thumb_path)
            print(f"    [meshy] 预览图: {thumb_path}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"    [meshy] 预览图下载失败: {exc}", flush=True)
    return out_path, task


def main():
    ap = argparse.ArgumentParser(description="Meshy 官方 API 客户端")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("balance", help="查剩余积分")
    sub.add_parser("config", help="查看配置（不显示完整 key）")

    p = sub.add_parser("image2", help="图生3D")
    p.add_argument("image")
    p.add_argument("--out-dir", default=os.path.join(HERE, "ComfyUI", "output"))
    p.add_argument("--ai-model", default=DEFAULT_MODEL)
    p.add_argument("--geometry", default="standard", choices=["standard", "2k", "4k"])
    p.add_argument("--texture", action="store_true", help="生成贴图（+credits，打印不需要）")
    p.add_argument("--ultra", action="store_true", help="同 --geometry 2k")
    p.add_argument("--poly", type=int, default=0, help="target_polycount，0=不限制")
    p.add_argument("--prefix", default="meshy")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)

    p = sub.add_parser("mv2", help="多视图生成3D：Meshy 官方 image-to-image + multi-image-to-3d")
    p.add_argument("image")
    p.add_argument("--out-dir", default=os.path.join(HERE, "ComfyUI", "output"))
    p.add_argument("--ai-model", default=DEFAULT_MODEL)
    p.add_argument("--geometry", default="standard", choices=["standard", "2k"])
    p.add_argument("--texture", action="store_true")
    p.add_argument("--image-model", default="nano-banana")
    p.add_argument("--prompt", default=None)
    p.add_argument("--views", nargs="*", default=[],
                   help="复用已有视图（第一张必须 front）；提供后跳过 image-to-image")
    p.add_argument("--min-balance", type=int, default=25)
    p.add_argument("--prefix", default="meshy_mv")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)

    p = sub.add_parser("task", help="查任务")
    p.add_argument("task_id")

    p = sub.add_parser("download", help="下载已完成任务的 GLB")
    p.add_argument("task_id")
    p.add_argument("output")

    args = ap.parse_args()
    if args.cmd == "balance":
        print("Meshy 剩余积分:", balance())
    elif args.cmd == "config":
        print("配置文件:", CONFIG_PATH, "存在" if os.path.isfile(CONFIG_PATH) else "不存在")
        key = os.environ.get("MESHY_API_KEY") or str(CONFIG.get("api_key", ""))
        print("API key:", (key[:6] + "…" + key[-4:]) if key else "（未配置）")
    elif args.cmd == "image2":
        geometry = "2k" if args.ultra else args.geometry
        path, task = image_to_3d(
            args.image, out_dir=args.out_dir, ai_model=args.ai_model,
            geometry_resolution=geometry, should_texture=args.texture,
            target_polycount=args.poly, prefix=args.prefix, timeout=args.timeout)
        print("任务:", task.get("id"), "GLB:", path)
    elif args.cmd == "mv2":
        path, views, task = multiview_to_3d(
            args.image, out_dir=args.out_dir, prompt=args.prompt,
            ai_model=args.ai_model, geometry_resolution=args.geometry,
            should_texture=args.texture, image_model=args.image_model,
            prefix=args.prefix, timeout=args.timeout,
            view_paths=args.views or None, min_balance=args.min_balance)
        print("任务:", task.get("id"), "GLB:", path)
        print("视图:", "\n".join(views))
    elif args.cmd == "task":
        print(json.dumps(get_task(args.task_id), ensure_ascii=False, indent=2))
    elif args.cmd == "download":
        task = get_task(args.task_id)
        if task.get("status") != "SUCCEEDED":
            raise SystemExit("任务未完成: " + str(task.get("status")))
        print(download(task["model_urls"]["glb"], args.output))


if __name__ == "__main__":
    main()
