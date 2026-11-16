# -*- coding: utf-8 -*-
"""一键释放 GPU 显存（控制中心使用）。

两档：
  soft  卸载模型 + 清理缓存，ComfyUI 服务保留，下次出图需重新加载模型。
        - ComfyUI：POST /free {unload_models, free_memory}（内部会 torch.cuda.empty_cache）
        - Ollama：对 /api/ps 中每个模型发 keep_alive=0，并结束残留的 llama-server.exe
  full  soft 之后再结束 ComfyUI 进程。只有进程退出才能归还 CUDA 上下文本身
        （/free 之后仍会剩约 0.5~1.5GB），这一档才是“完全归还”。

所有步骤都是尽力而为：某个服务没开就跳过，不抛异常。
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

COMFY = "http://127.0.0.1:8188"
OLLAMA = "http://127.0.0.1:11434"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _post_json(url, payload, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def gpu_usage():
    """{'used_mb','total_mb','processes':[{'pid','name','used_mb'}]}；无 nvidia-smi 时返回 None。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW)
        used, total = out.stdout.strip().splitlines()[0].split(",")
        info = {"used_mb": int(used.strip()), "total_mb": int(total.strip()), "processes": []}
    except Exception:  # noqa: BLE001
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW)
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            try:
                mb = int(parts[2])
            except ValueError:
                mb = None  # Windows WDDM 下常为 [N/A]
            info["processes"].append({"pid": int(parts[0]) if parts[0].isdigit() else parts[0],
                                      "name": os.path.basename(parts[1]), "used_mb": mb})
    except Exception:  # noqa: BLE001
        pass
    return info


def comfyui_running():
    try:
        urllib.request.urlopen(COMFY + "/system_stats", timeout=2).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def comfyui_busy():
    """ComfyUI 正在执行/排队任务时返回 True（此时不该卸载模型）。"""
    try:
        q = _get_json(COMFY + "/queue")
        return bool(q.get("queue_running") or q.get("queue_pending"))
    except Exception:  # noqa: BLE001
        return False


def free_comfyui():
    """让 ComfyUI 卸载所有模型并清空 PyTorch 显存缓存。返回 'ok' / 'not_running' / 错误文本。"""
    if not comfyui_running():
        return "not_running"
    try:
        _post_json(COMFY + "/free", {"unload_models": True, "free_memory": True})
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"failed: {exc}"


def kill_llama_server():
    """结束 Ollama 残留的 llama-server.exe runner（keep_alive=0 后仍可能占着显存）。"""
    if os.name != "nt":
        return 0
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW)
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    for line in out.stdout.splitlines():
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].upper() == "LLAMA-SERVER.EXE" and parts[1].isdigit():
            r = subprocess.run(["taskkill", "/PID", parts[1], "/F"], capture_output=True,
                               timeout=20, creationflags=_NO_WINDOW)
            n += r.returncode == 0
    return n


def unload_ollama():
    """让 Ollama 立即卸载所有已加载模型。返回卸载的模型名列表。"""
    names = []
    try:
        for m in _get_json(OLLAMA + "/api/ps").get("models", []) or []:
            name = m.get("name") or m.get("model")
            if not name:
                continue
            try:
                _post_json(OLLAMA + "/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
                names.append(name)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return names


def release(mode="soft", stop_comfyui=None, log=print):
    """执行释放并返回报告。stop_comfyui：mode='full' 时用来结束 ComfyUI 进程的回调。"""
    if mode not in ("soft", "full"):
        raise ValueError("mode 只能是 soft 或 full")
    before = gpu_usage()
    report = {"mode": mode, "before_mb": before and before["used_mb"]}
    report["comfyui"] = free_comfyui()
    report["ollama_unloaded"] = unload_ollama()
    report["llama_server_killed"] = kill_llama_server()
    if mode == "full" and stop_comfyui is not None:
        report["comfyui_stopped_pids"] = stop_comfyui("一键完全释放显存") or []
    # 显存归还是异步的，稍等再读数
    after = None
    for _ in range(6):
        time.sleep(0.5)
        after = gpu_usage()
        if not after or before is None or after["used_mb"] < before["used_mb"] - 100:
            break
    report["after_mb"] = after and after["used_mb"]
    report["total_mb"] = after and after["total_mb"]
    if report["before_mb"] is not None and report["after_mb"] is not None:
        report["freed_mb"] = max(0, report["before_mb"] - report["after_mb"])
    report["remaining_processes"] = (after or {}).get("processes", [])
    log(f"[*] 显存释放（{mode}）：{report.get('before_mb')} → {report.get('after_mb')} MB；"
        f"ComfyUI={report['comfyui']}，Ollama 卸载 {len(report['ollama_unloaded'])} 个，"
        f"llama-server 结束 {report['llama_server_killed']} 个", flush=True)
    return report
