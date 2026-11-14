import atexit, base64, http.server, io, json, os, re, secrets, subprocess, threading, time, urllib.error, urllib.parse, urllib.request, webbrowser
from pathlib import Path

from paths_config import FINAL_DIR, find_python_with_trimesh

ROOT = Path(__file__).resolve().parent
PY = ROOT / 'ComfyUI' / 'venv' / 'Scripts' / 'python.exe'
TOKEN = secrets.token_urlsafe(32)
PREFIX = '/' + TOKEN
jobs = {}
lock = threading.Lock()

# 控制中心页面心跳：浏览器关闭/工具退出后，若 10 分钟没有心跳且无任务在跑，
# 自动终止 ComfyUI 并释放显存。仅在页面曾经连上过时生效，避免误杀手动启动。
LAST_HEARTBEAT = 0.0
COMFY_IDLE_SECONDS = 600


def stop_comfyui(reason='idle'):
    """按命令行精确停止 ComfyUI（main.py --port 8188），不碰控制中心自身。

    Windows 下优先用 psutil；缺 psutil 时退回 PowerShell/CIM 按完整命令行
    匹配，避免给控制中心引入新的必装依赖。
    """
    removed = []
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmd = ' '.join(proc.info.get('cmdline') or [])
                name = (proc.info.get('name') or '').lower()
                if name not in ('python.exe', 'pythonw.exe'):
                    continue
                if 'main.py' in cmd and '--port' in cmd and '8188' in cmd:
                    print(f'[*] 释放显存：停止 ComfyUI PID={proc.pid}（{reason}）', flush=True)
                    kill = subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          timeout=12)
                    if kill.returncode == 0:
                        removed.append(proc.pid)
                    else:
                        print(f'[!] taskkill PID={proc.pid} 返回 {kill.returncode}', flush=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as exc:  # noqa: BLE001
        print(f'[*] psutil 不可用（{type(exc).__name__}），使用端口监听 PID 匹配', flush=True)
        script = r'''
$conn = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue
$pids = @($conn | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($p in $pids) {
  if ($p -and $p -ne $PID) {
    Write-Output ("STOP " + $p)
    & taskkill /PID $p /T /F | Out-Null
  }
}
'''
        try:
            proc = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for line in (proc.stdout or '').splitlines():
                if line.startswith('STOP '):
                    try:
                        removed.append(int(line.split()[1]))
                    except (ValueError, IndexError):
                        continue
            if removed:
                print(f'[*] 释放显存：停止 ComfyUI PID={",".join(map(str, removed))}（{reason}）',
                      flush=True)
            if proc.returncode != 0:
                print(f'[!] Windows 停止 ComfyUI 返回 {proc.returncode}: '
                      f'{(proc.stderr or proc.stdout or "")[-300:]}', flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f'[!] 自动释放显存失败：{exc}', flush=True)
    return removed


atexit.register(lambda: stop_comfyui('control_server exit'))


def _comfyui_running():
    try:
        urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=2).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def comfyui_idle_watchdog():
    """后台看门狗：页面失联且空闲时释放显存。"""
    while True:
        time.sleep(30)
        if not LAST_HEARTBEAT:
            continue
        if time.time() - LAST_HEARTBEAT < COMFY_IDLE_SECONDS:
            continue
        with lock:
            if jobs.get('running'):
                continue
        removed = stop_comfyui('UI closed / idle')
        if removed or not _comfyui_running():
            # 本次会话只清理一次；页面重新打开后会重新开始心跳。
            globals()['LAST_HEARTBEAT'] = 0.0
        else:
            print('[*] ComfyUI 仍在运行，30 秒后重试自动释放', flush=True)


CAPTION_FIELDS = ("subject", "pose", "hair_and_face", "clothing", "accessories", "style_and_composition")
CAPTION_SCHEMA = {
    "type": "object",
    "properties": {key: {"type": "array", "items": {"type": "string"}} for key in CAPTION_FIELDS},
    "required": list(CAPTION_FIELDS),
}

EDIT_MASK_METHODS = frozenset(("auto", "local", "remove"))
_INTERNAL_QWEN_EDIT_ARTIFACT = re.compile(r"^fig_edit_[0-9a-f]+_\d+_\.(?:png|jpg|jpeg|webp)$", re.IGNORECASE)

# R30：与 fig.PRINT_FLAG_DEFAULTS 使用同一套键名（回归测试防止两端漂移）。
# 控制中心把前端的布尔项翻译成 fig.py 的 CLI 开关，避免出现
# 「convert_3d 有能力、fig.py 有开关、但控制中心用不上」的断层。
PRINT_FLAG_ARGS = {
    'strict_watertight': '--strict-watertight',
    'drop_floating_parts': '--drop-floating-parts',
    'strict_single_body': '--strict-single-body',
}


def print_quality_flags(body):
    """把质量门禁布尔项翻译成 fig.py 的 CLI 开关；非法类型显式报错而非静默忽略。"""
    if not isinstance(body, dict):
        raise ValueError('参数必须是对象')
    flags = []
    for key, flag in PRINT_FLAG_ARGS.items():
        value = body.get(key, False)
        if not isinstance(value, (bool, int, str, type(None))):
            raise ValueError('%s 必须是布尔值' % key)
        if isinstance(value, str):
            value = value.strip().lower()
        if value in (True, 1, '1', 'true'):
            flags.append(flag)
        elif value not in (False, 0, None, '', '0', 'false'):
            raise ValueError('%s 必须是布尔值' % key)
    return flags


def edit_requires_mask(method):
    """Only local edit variants consume a drawn mask; whole-frame edit never does."""
    return method in EDIT_MASK_METHODS


def is_internal_qwen_edit_artifact(path):
    """Hide Qwen's raw crop/frame from the user-facing recent-output gallery."""
    return bool(_INTERNAL_QWEN_EDIT_ARTIFACT.fullmatch(Path(path).name))

def clean_caption(data):
    if not isinstance(data, dict):
        raise ValueError('识图结果格式不正确，请重试或手动输入')
    seen, result = set(), []
    for field in CAPTION_FIELDS:
        items = data.get(field, [])
        if not isinstance(items, list):
            raise ValueError('识图结果格式不正确，请重试或手动输入')
        for item in items:
            if not isinstance(item, str):
                continue
            for tag in re.split(r'[,;\n]+', item):
                tag = re.sub(r'\s+', ' ', tag).strip(' .:-*')
                key = re.sub(r'[^\w]+', ' ', tag.casefold()).strip()
                if not key or key in seen or re.match(r'^(no|not visible|unknown|unclear|none|n a)\b', key):
                    continue
                seen.add(key)
                result.append(tag)
    prompt = ', '.join(result)
    if not prompt:
        raise ValueError('视觉模型没有返回可用的可见细节，请重试或手动输入')
    return prompt

def _checked_ref_paths(body):
    """校验并返回参考图路径列表（多参考图槽位用）。"""
    refs = body.get('refs') or []
    if not isinstance(refs, list) or len(refs) > 30:
        raise ValueError('参考图数量过多')
    refs = [str(p).strip() for p in refs if str(p).strip()]
    for ref_path in refs:
        if not os.path.isfile(ref_path):
            raise ValueError('参考图不存在: ' + ref_path)
    return refs


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(body)
    def allowed(self):
        origin = self.headers.get('Origin')
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and (not origin or origin == f'http://127.0.0.1:{self.server.server_port}') and self.path.startswith(PREFIX + '/')
    def do_GET(self):
        if not self.allowed(): self.send_error(403); return
        route = urllib.parse.urlsplit(self.path).path[len(PREFIX):]
        if route == '/completion':
            self.send_response(302)
            self.send_header('Location', PREFIX + '/#edit-completion')
            self.end_headers(); return
        if route == '/completion.js':
            data = (ROOT / 'completion.js').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/javascript; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers(); self.wfile.write(data); return
        if route == '/api/completion_capabilities':
            import completion
            self.send_json(completion.capabilities()); return
        if route == '/api/completion_image':
            try:
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                path = Path(query.get('path', [''])[0]).resolve()
                output_root = (ROOT / 'ComfyUI' / 'output').resolve()
                if not path.is_relative_to(output_root) or path.suffix.lower() != '.png' or not path.is_file():
                    raise ValueError('仅可读取输出目录中的 PNG 图片')
                data = path.read_bytes()
                self.send_response(200); self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-store'); self.send_header('Referrer-Policy', 'no-referrer')
                if query.get('download') == ['1']:
                    self.send_header('Content-Disposition', 'attachment; filename="' + path.name.encode('ascii', 'replace').decode('ascii') + '"')
                self.end_headers(); self.wfile.write(data); return
            except (ValueError, OSError) as exc:
                self.send_json({'error': str(exc)}, 400); return
        if route == '/':
            data = (ROOT / '启动器.html').read_text(encoding='utf-8').replace(
                '<!-- COMPLETION_INLINE -->', (ROOT / 'completion-panel.html').read_text(encoding='utf-8')).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','no-referrer'); self.end_headers(); self.wfile.write(data); return
        if route == '/api/meshy_config':
            cfg_path = ROOT / 'meshy_config.json'
            cfg = {}
            try:
                cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                cfg = {}
            key = os.environ.get('MESHY_API_KEY', '') or str(cfg.get('api_key', ''))
            masked = (key[:6] + '…' + key[-4:]) if len(key) > 12 else ('已配置' if key else '')
            self.send_json({'ok': True, 'has_key': bool(key), 'masked': masked,
                            'ai_model': cfg.get('ai_model') or 'meshy-7.1',
                            'source': 'env' if os.environ.get('MESHY_API_KEY') else 'file'}); return
        if route == '/api/meshy_balance':
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT))
                import meshy_client as _meshy
                self.send_json({'ok': True, 'balance': _meshy.balance()}); return
            except Exception as exc:  # noqa: BLE001
                self.send_json({'ok': False, 'error': str(exc)}); return
        if route == '/api/outputs':
            import time as _time
            outdir = ROOT / 'ComfyUI' / 'output'
            files = []
            try:
                entries = [p for p in outdir.iterdir()
                           if p.is_file() and p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
                           and not is_internal_qwen_edit_artifact(p)]
            except OSError:
                entries = []
            for p in sorted(entries, key=lambda q: q.stat().st_mtime, reverse=True)[:24]:
                files.append({'path': str(p), 'name': p.name, 'mtime': int(p.stat().st_mtime)})
            self.send_json({'files': files}); return
        if route == '/api/heartbeat':
            globals()['LAST_HEARTBEAT'] = time.time()
            self.send_json({'ok': True}); return
        if route == '/api/status':
            with lock: data = dict(jobs)
            qwen_files = [
                (ROOT/'ComfyUI'/'models'/'diffusion_models'/'qwen_image_edit_2509_fp8_e4m3fn.safetensors', 20430698424),
                (ROOT/'ComfyUI'/'models'/'text_encoders'/'qwen_2.5_vl_7b_fp8_scaled.safetensors', 9384670680),
                (ROOT/'ComfyUI'/'models'/'vae'/'qwen_image_vae.safetensors', 253806246),
            ]
            ready = all(path.is_file() and path.stat().st_size == size for path, size in qwen_files)
            downloaded = sum(min(size, path.stat().st_size if path.is_file() else
                                 Path(str(path)+'.part').stat().st_size if Path(str(path)+'.part').is_file() else 0)
                             for path, size in qwen_files)
            data['qwen_weights'] = {'ready': ready, 'downloaded': downloaded,
                                    'total': sum(size for _, size in qwen_files)}
            try:
                with urllib.request.urlopen('http://127.0.0.1:8188/system_stats',timeout=2) as r: data['comfy'] = json.load(r)
            except Exception: data['comfy'] = None
            try:
                with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=2): data['ollama'] = True
            except Exception: data['ollama'] = False
            self.send_json(data); return
        self.send_error(404)
    def do_POST(self):
        if not self.allowed() or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}' or self.headers.get('Content-Type') != 'application/json': self.send_error(403); return
        try:
            size = int(self.headers.get('Content-Length', 0))
            if size > 8 * 1024 * 1024: raise ValueError('请求过大')
            body = json.loads(self.rfile.read(size))
            route = urllib.parse.urlsplit(self.path).path[len(PREFIX):]
            if route == '/api/completion_validate':
                import completion
                project, image = completion.validate_project(body.get('project'))
                self.send_json({'project': project}); return
            if route == '/api/completion_preview':
                import completion
                import hashlib
                source_path = str(body.get('path', ''))
                image = completion.load_source(source_path)
                digest = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
                if body.get('source_sha256') and body['source_sha256'] != digest:
                    raise ValueError('原图内容已改变，请重新载入图片并检查标注')
                original_size = list(image.size)
                image.thumbnail((1600, 1600))
                buf = io.BytesIO(); image.save(buf, format='PNG')
                self.send_json({'source_size': original_size, 'source_sha256': digest,
                    'image': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')}); return
            if route == '/api/completion_save':
                import completion
                path, project, original, layers = completion.prepare(body.get('project'))
                self.send_json({'path': str(path), 'project': project,
                    'expanded_path': str(path.parent / 'expanded.png'),
                    'mask_path': str(path.parent / 'mask.png'), 'guide_path': str(path.parent / 'guide.png')}); return
            if route == '/api/open':
                dirs = {'output': ROOT/'ComfyUI'/'output', 'print':Path(FINAL_DIR), 'project':ROOT}
                target = dirs[body['folder']]; target.mkdir(parents=True,exist_ok=True); os.startfile(str(target)); self.send_json({'ok':True}); return
            if route == '/api/command':
                subprocess.Popen(['cmd.exe', '/K', 'cd /d "' + str(ROOT) + '"'], cwd=str(ROOT), creationflags=subprocess.CREATE_NEW_CONSOLE)
                self.send_json({'ok': True}); return
            if route == '/api/meshy_config':
                action = str(body.get('action', 'test'))
                cfg_path = ROOT / 'meshy_config.json'
                try:
                    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    cfg = {}
                import sys as _sys
                _sys.path.insert(0, str(ROOT))
                import meshy_client as _meshy
                if action == 'save':
                    key = str(body.get('api_key', '')).strip()
                    if not key:
                        raise ValueError('请填写 API key')
                    if len(key) < 20 or len(key) > 200 or not all(33 <= ord(c) <= 126 for c in key):
                        raise ValueError('API key 格式不对（应为 Meshy 控制台生成的密钥）')
                    cfg['api_key'] = key
                    cfg.setdefault('ai_model', 'meshy-7.1')
                    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
                    balance = None
                    try:
                        _meshy.CONFIG = cfg
                        balance = _meshy.balance()
                    except Exception:  # noqa: BLE001
                        balance = None
                    self.send_json({'ok': True, 'has_key': True, 'masked': key[:6] + '…' + key[-4:],
                                    'balance': balance, 'message': '已保存并生效'}); return
                if action == 'clear':
                    cfg.pop('api_key', None)
                    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
                    self.send_json({'ok': True, 'has_key': False, 'message': '已清除 API key'}); return
                # test
                try:
                    _meshy.CONFIG = cfg
                    balance = _meshy.balance()
                    self.send_json({'ok': True, 'balance': balance}); return
                except Exception as exc:  # noqa: BLE001
                    self.send_json({'ok': False, 'error': str(exc)}); return
            if route == '/api/mesh_info':
                path = str(body.get('path', ''))
                if not os.path.isfile(path):
                    raise ValueError('模型文件不存在')
                code = (
                    "import sys,json,trimesh\n"
                    "m=trimesh.load(sys.argv[1], force='mesh', process=True)\n"
                    "print(json.dumps({'faces':int(len(m.faces)),'vertices':int(len(m.vertices)),"
                    "'watertight':bool(m.is_watertight),'extents':[round(float(x),4) for x in m.extents]}))\n")
                try:
                    import sys as _sys
                    trimesh_py = find_python_with_trimesh()
                    runner = trimesh_py if trimesh_py != _sys.executable else str(PY)
                    out = subprocess.check_output([runner, '-c', code, path], text=True, timeout=300)
                    info = json.loads(out.strip().splitlines()[-1])
                except Exception as exc:  # noqa: BLE001
                    raise ValueError('读取模型失败: ' + str(exc))
                info['size_mb'] = round(os.path.getsize(path) / 1e6, 2)
                info['path'] = path
                self.send_json({'ok': True, 'info': info}); return
            if route == '/api/pick':
                import tkinter as tk
                from tkinter import filedialog
                root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
                try:
                    kind=body.get('kind'); types=[('图片','*.png *.jpg *.jpeg *.webp'),('所有文件','*.*')] if kind == 'image' else [('3D 模型','*.glb *.gltf *.obj *.stl *.ply *.3mf'),('所有文件','*.*')]
                    if body.get('multiple'):
                        paths=filedialog.askopenfilenames(parent=root,title='选择图片（可多选）',filetypes=types,initialdir=str(ROOT/'ComfyUI'/'output'))
                        chosen=list(paths)
                    else:
                        path=filedialog.askopenfilename(parent=root,title='选择图片' if kind=='image' else '选择3D模型',filetypes=types,initialdir=str(ROOT/'ComfyUI'/'output'))
                        chosen=[path] if path else []
                finally: root.destroy()
                self.send_json({'path': chosen[0] if chosen else '', 'paths': chosen}); return
            if route == '/api/caption':
                path = str(body.get('path', ''))
                if not os.path.isfile(path): raise ValueError('请选择存在的图片')
                from PIL import Image, ImageOps
                try:
                    with Image.open(path) as original:
                        original = ImageOps.exif_transpose(original)
                        original.thumbnail((1536, 1536))
                        if original.mode in ('RGBA', 'LA') or 'transparency' in original.info:
                            rgba = original.convert('RGBA')
                            image = Image.new('RGB', rgba.size, 'white')
                            image.paste(rgba, mask=rgba.getchannel('A'))
                        else:
                            image = original.convert('RGB')
                        buf = io.BytesIO()
                        image.save(buf, format='JPEG', quality=90)
                except (OSError, ValueError) as exc:
                    raise ValueError('无法读取图片，请选择有效的 PNG、JPG 或 WebP 文件') from exc
                instruction = (
                    'Describe the visible content of the reference image for a faithful image editing task. '
                    'Return the requested JSON object. For each field, use a short list of distinct English '
                    'phrases. Identify subject count, viewpoint, body pose and relative limb positions, '
                    'hair color and shape, visible face, clothing pieces and their colors, distinctive '
                    'accessories and their positions, and artistic style and composition. Distinguish the '
                    'depicted artwork from the photographed object and its surroundings. '
                    'Mention only clearly visible details; leave a field empty when uncertain. '
                    'Do not infer hidden anatomy, identity or invisible details. Never repeat a phrase.'
                )
                payload = json.dumps({
                    'model': 'qwen2.5vl:7b', 'prompt': instruction,
                    'images': [base64.b64encode(buf.getvalue()).decode('ascii')],
                    'format': CAPTION_SCHEMA, 'stream': False, 'keep_alive': 0,
                    'options': {'temperature': 0.1, 'num_predict': 700, 'repeat_penalty': 1.2}
                }).encode('utf-8')
                req = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=payload,
                                             headers={'Content-Type': 'application/json'})
                try:
                    with urllib.request.urlopen(req, timeout=300) as response:
                        result = json.load(response)
                except urllib.error.HTTPError as exc:
                    raise ValueError(f'本地视觉模型出错（HTTP {exc.code}）；请确认 qwen2.5vl:7b 可用') from exc
                except (urllib.error.URLError, TimeoutError) as exc:
                    raise ValueError('无法连接本地视觉模型或识别超时，请检查 Ollama 是否运行') from exc
                try:
                    details = json.loads(result.get('response', ''))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise ValueError('识图返回了不完整的描述，请重试或手动输入') from exc
                prompt = clean_caption(details)
                self.send_json({'prompt': prompt}); return
            if route == '/api/edit_preview':
                path = str(body.get('path', ''))
                if not os.path.isfile(path): raise ValueError('请选择存在的图片')
                from PIL import Image, ImageOps
                with Image.open(path) as f:
                    image = ImageOps.exif_transpose(f).convert('RGB')
                    image.thumbnail((1024, 1024))
                    buf = io.BytesIO(); image.save(buf, format='PNG')
                self.send_json({'image': 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')}); return
            if route == '/api/optimize_edit':
                request = str(body.get('request', '')).strip()
                if not request or len(request) > 2000: raise ValueError('请输入不超过2000字的修改要求')
                payload = json.dumps({'model':'qwen3:8b', 'stream':False, 'think':False,
                    'system': ('You rewrite image-edit requests. Preserve exactly the requested changes and restrictions. '
                               'Do not add new design details. Output only a short editing instruction in Chinese. '
                               'Do not mention steps, image generation parameters, or provide commentary.'),
                    'prompt':request, 'keep_alive':0,
                    'options':{'temperature':0.1,'num_predict':300,'repeat_penalty':1.15}}).encode('utf-8')
                req=urllib.request.Request('http://127.0.0.1:11434/api/generate',data=payload,headers={'Content-Type':'application/json'})
                try:
                    with urllib.request.urlopen(req,timeout=300) as response: result=json.load(response)
                except (urllib.error.URLError, TimeoutError) as exc:
                    raise ValueError('本地提示词优化不可用，请检查 Ollama 和 qwen3:8b') from exc
                optimized=re.sub(r'<think>.*?</think>', '', str(result.get('response','')), flags=re.DOTALL).strip()
                if not optimized: raise ValueError('优化结果为空，请重试或直接使用原要求')
                self.send_json({'instruction':optimized}); return
            if route == '/api/run':
                mode=body['mode']
                if mode not in ('auto','img','i2i','model','print','doctor','desensitize','restore','image_print','edit_image','multiview','mv3d_build','mv3d_render','mv3d_repaint','model_edit','complete_image'): raise ValueError('不支持的操作')
                args=[str(PY),'-u',str(ROOT/'fig.py'),mode]
                if mode == 'complete_image':
                    import completion
                    with lock:
                        if jobs.get('running'): raise ValueError('已有任务正在运行')
                    data = body.get('project')
                    if not isinstance(data, dict) or not str(data.get('instruction', '')).strip():
                        raise ValueError('请填写补全要求')
                    project_path, project, original, layers = completion.prepare(data)
                    args = [str(PY), '-u', str(ROOT/'completion.py'), str(project_path)]
                # mv3d_build / mv3d_render 都归到 mv3d 子命令，用 --stage 区分
                if mode.startswith('mv3d_'):
                    args[3] = 'mv3d'
                if mode in ('auto','img','i2i'):
                    prompt=str(body.get('prompt','')).strip()
                    if not prompt: raise ValueError('请输入描述或提示词')
                if mode in ('i2i','model','print','desensitize','restore','image_print','edit_image','multiview','mv3d_build','mv3d_repaint','model_edit'):
                    path=str(body.get('path',''))
                    if not os.path.isfile(path): raise ValueError('请选择存在的输入文件')
                    args.append(path)
                if mode in ('auto','img','i2i'): args.append(prompt)
                if mode == 'edit_image':
                    instruction = str(body.get('instruction', '')).strip()
                    if not instruction or len(instruction) > 8000: raise ValueError('请输入不超过8000字的修改要求')
                    args.append(instruction)
                    method = body.get('method', 'auto')
                    if method == 'fast':
                        raise ValueError('“快速背景插值”已停用（会留下模糊色块），请改用“局部重绘”')
                    if method not in ('auto', 'local', 'remove', 'whole', 'ai'):
                        raise ValueError('无效的图片编辑方式')
                    if edit_requires_mask(method) and not body.get('mask'):
                        raise ValueError('请先涂抹需要修改的区域')
                    args += ['--method', method]
                    # Older pages may still submit a visible mask with `whole`.
                    # Ignore it at the boundary so it cannot revive the crop path.
                    mask_data = body.get('mask') if edit_requires_mask(method) else None
                    if mask_data:
                        if not isinstance(mask_data, str) or not mask_data.startswith('data:image/png;base64,'):
                            raise ValueError('修改区域格式错误')
                        try: raw = base64.b64decode(mask_data.split(',',1)[1], validate=True)
                        except (ValueError, TypeError) as exc: raise ValueError('修改区域数据损坏') from exc
                        from PIL import Image
                        mask = Image.open(io.BytesIO(raw)).convert('L')
                        if mask.width > 2048 or mask.height > 2048 or not mask.getbbox():
                            raise ValueError('修改区域为空或尺寸过大')
                        mask_path = ROOT/'ComfyUI'/'temp'/('edit_mask_' + secrets.token_hex(8) + '.png')
                        mask_path.parent.mkdir(parents=True, exist_ok=True)
                        mask.save(mask_path)
                        args += ['--mask', str(mask_path)]
                    try: steps = int(body.get('steps', 16) or 16)
                    except (TypeError, ValueError): raise ValueError('无效的 Qwen 采样步数')
                    if not 8 <= steps <= 30: raise ValueError('Qwen 采样步数只能是 8~30')
                    args += ['--steps', str(steps)]
                    refs = _checked_ref_paths(body)
                    if refs: args += ['--refs'] + refs
                    try: candidates = int(body.get('candidates', 1) or 1)
                    except (TypeError, ValueError): raise ValueError('无效的方案数量')
                    if not 1 <= candidates <= 3: raise ValueError('方案数量只能是 1~3')
                    if candidates > 1: args += ['--candidates', str(candidates)]
                if mode == 'multiview':
                    allowed_views = ('front','back','left','right','front_left','front_right','back_left','back_right')
                    views = body.get('views') or []
                    if not isinstance(views, list) or not views:
                        raise ValueError('请至少选择一个方位')
                    views = [str(v) for v in views]
                    bad = [v for v in views if v not in allowed_views]
                    if bad:
                        raise ValueError('无效的方位: ' + ','.join(bad) + '（可用: ' + ','.join(allowed_views) + '）')
                    args += ['--views'] + views
                    mv_prompt = str(body.get('prompt', '')).strip()
                    if len(mv_prompt) > 2000:
                        raise ValueError('多视图要求过长（≤2000字）')
                    if mv_prompt:
                        args += ['--prompt', mv_prompt]
                    mv_extra = str(body.get('extra', '')).strip()
                    if mv_extra:
                        if len(mv_extra) > 800:
                            raise ValueError('单张要求过长（≤800字）')
                        args += ['--extra', mv_extra]
                    refs = _checked_ref_paths(body)
                    if refs:
                        args += ['--refs'] + refs
                if mode in ('mv3d_build', 'mv3d_render', 'mv3d_repaint'):
                    allowed_views = ('front','back','left','right','front_left','front_right','back_left','back_right')
                    if mode == 'mv3d_build':
                        views = body.get('views') or list(allowed_views)
                        if not isinstance(views, list) or not views:
                            raise ValueError('请至少选择一个方位')
                        views = [str(v) for v in views]
                        bad = [v for v in views if v not in allowed_views]
                        if bad: raise ValueError('无效的方位: ' + ','.join(bad))
                        args += ['--stage', 'build', '--views'] + views
                        build_engine = str(body.get('build_engine', 'hunyuan') or 'hunyuan')
                        if build_engine not in ('hunyuan', 'meshy'): raise ValueError('无效的 3D 来源')
                        args += ['--engine', build_engine]
                        if body.get('meshy_desensitize'): args += ['--meshy-desensitize']
                        try: octree = int(body.get('octree', 512))
                        except (TypeError, ValueError): raise ValueError('无效的 3D 精度')
                        if octree not in (256, 384, 512): raise ValueError('无效的 3D 精度')
                        args += ['--octree-res', str(octree)]
                    elif mode == 'mv3d_render':
                        glb = str(body.get('glb', ''))
                        if not os.path.isfile(glb): raise ValueError('找不到 3D 模型：请先生成粗模')
                        views = body.get('views') or []
                        if not isinstance(views, list) or not views: raise ValueError('请至少选择一个方位')
                        views = [str(v) for v in views]
                        bad = [v for v in views if v not in allowed_views]
                        if bad: raise ValueError('无效的方位: ' + ','.join(bad))
                        args.append(glb)  # 子命令要求 image 位置参数；render 阶段不用它，用 glb 占位
                        args += ['--stage', 'render', '--glb', glb, '--views'] + views
                        try: size = int(body.get('size', 1024) or 1024)
                        except (TypeError, ValueError): raise ValueError('无效的渲染尺寸')
                        if not 256 <= size <= 2048: raise ValueError('无效的渲染尺寸')
                        args += ['--size', str(size)]
                    else:
                        clay = body.get('clay') or []
                        if not isinstance(clay, list) or not clay:
                            raise ValueError('缺少 3D 定格灰模，请先生成定格')
                        specs = []
                        for item in clay:
                            if isinstance(item, (list, tuple)) and len(item) == 2:
                                view, clay_path = str(item[0]), str(item[1])
                            elif isinstance(item, str) and ':' in item:
                                view, clay_path = item.split(':', 1)
                            else:
                                raise ValueError('灰模参数格式错误')
                            view = view.strip()
                            if view not in allowed_views: raise ValueError('无效的方位: ' + view)
                            if not os.path.isfile(clay_path): raise ValueError('灰模文件不存在: ' + clay_path)
                            specs.append(view + ':' + clay_path)
                        args += ['--stage', 'repaint', '--clay'] + specs
                        mv_prompt = str(body.get('prompt', '')).strip()
                        if len(mv_prompt) > 2000: raise ValueError('多视图要求过长（≤2000字）')
                        if mv_prompt: args += ['--prompt', mv_prompt]
                if mode == 'model_edit':
                    instruction = str(body.get('instruction', '')).strip()
                    if not instruction or len(instruction) > 2000:
                        raise ValueError('请输入不超过2000字的修改要求')
                    edit_mode = str(body.get('edit_mode', 'texture'))
                    if edit_mode not in ('texture', 'rebuild'):
                        raise ValueError('无效的修改方式')
                    args += ['--instruction', instruction, '--edit-mode', edit_mode]
                    if body.get('meshy_desensitize'):
                        args += ['--meshy-desensitize']
                if mode == 'desensitize':
                    strength = str(body.get('strength', 'auto'))
                    if strength not in ('auto', 'full', 'minimal'): raise ValueError('无效的遮挡强度')
                    output = ROOT/'ComfyUI'/'output'/('desensitized_' + secrets.token_hex(8) + '.png')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    args += ['--strength', strength, '--output', str(output)]
                if mode == 'restore':
                    original = str(body.get('original', ''))
                    if not os.path.isfile(original): raise ValueError('请选择存在的参考图片')
                    output = ROOT/'ComfyUI'/'output'/('projected_' + secrets.token_hex(8) + '.glb')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    args += ['--original', original, '--output', str(output)]
                if mode in ('img','i2i'): args += ['--retry','1','--no-check-bg']
                if mode == 'i2i':
                    strength = float(body.get('strength', 0.3))
                    if not 0.05 <= strength <= 1.0: raise ValueError('重绘强度必须在 0.05 到 1.0 之间')
                    args += ['--strength', str(strength)]
                    style = str(body.get('style', 'original'))
                    if style not in ('original', 'figure_render', 'figure_photo'): raise ValueError('无效的目标风格')
                    args += ['--style', style]
                    engine = str(body.get('engine', 'pony'))
                    if engine not in ('pony', 'qwen'):
                        raise ValueError(f'无效的编辑引擎: {engine}（图生图引擎只能是 pony / qwen）')
                    args += ['--engine', engine]
                    refs = _checked_ref_paths(body)
                    if refs:
                        if engine != 'qwen': raise ValueError('多参考图仅 Qwen 编辑流程支持（Pony 没有参考图入参）')
                        args += ['--refs'] + refs
                    structure = str(body.get('structure', 'none'))
                    if structure not in ('none', 'canny'): raise ValueError('无效的轮廓控制选项')
                    args += ['--structure', structure]
                if mode in ('model','auto','image_print'):
                    # 3D 引擎用独立字段 engine3d（兼容老页面用 engine 传 3D 引擎的情况）
                    engine = str(body.get('engine3d') or body.get('engine') or 'hunyuan')
                    if engine not in ('hunyuan','meshy','meshy-mv','auto'):
                        raise ValueError(f'无效的 3D 引擎: {engine}（只能是 hunyuan / meshy / meshy-mv / auto）')
                    if engine == 'meshy-mv' and body.get('meshy_desensitize'):
                        raise ValueError('Meshy 多视图暂不支持“脱敏后贴图还原”；请改用 Meshy 单图模式')
                    args += ['--engine', engine]
                    octree = body.get('octree', 512)
                    try: octree = int(octree)
                    except (TypeError, ValueError): raise ValueError('无效的 3D 精度')
                    if octree not in (256, 384, 512): raise ValueError('无效的 3D 精度')
                    args += ['--octree-res', str(octree)]
                    # Hunyuan 多视图条件：left/back/right=path；front 缺省用主图。
                    mv_specs=[]
                    raw_mv=body.get('mv_refs') or []
                    if not isinstance(raw_mv,(list,tuple)): raise ValueError('mv_refs 必须是数组')
                    for item in raw_mv:
                        if isinstance(item,dict):
                            view=str(item.get('view','')).strip().lower(); path=str(item.get('path','')).strip()
                        else:
                            text=str(item).strip()
                            if '=' not in text: raise ValueError('mv_refs 格式应为 view=path')
                            view,path=text.split('=',1); view=view.strip().lower(); path=path.strip()
                        if view not in ('front','left','back','right'): raise ValueError('无效的多视图方位: '+view)
                        if not path or not os.path.isfile(path): raise ValueError('多视图参考图不存在: '+path)
                        mv_specs.append(view+'='+os.path.abspath(path))
                    if mv_specs: args += ['--mv-refs'] + mv_specs
                    if engine in ('meshy','auto'):
                        geometry = str(body.get('meshy_geometry', 'standard') or 'standard')
                        if geometry not in ('standard','2k','4k'): raise ValueError('无效的 Meshy 几何精度')
                        args += ['--meshy-geometry', geometry]
                        args += ['--meshy-desensitize'] if body.get('meshy_desensitize') else ['--no-meshy-desensitize']
                        if body.get('meshy_poly'):
                            try: poly = int(body['meshy_poly'])
                            except (TypeError, ValueError): raise ValueError('无效的 Meshy 面数')
                            if not 0 <= poly <= 2000000: raise ValueError('无效的 Meshy 面数')
                            if poly: args += ['--meshy-poly', str(poly)]
                if mode in ('auto','print','image_print'):
                    height=float(body.get('height',150)); base=float(body.get('base',3)); hollow=float(body.get('hollow',0))
                    if not 10 <= height <= 500 or not 0 <= base <= 15 or not 0 <= hollow <= 10: raise ValueError('尺寸参数超出范围')
                    args += ['--model-height',str(height),'--out-dir',FINAL_DIR,'--base',str(base/100),'--hollow',str(hollow/100)]
                    if mode == 'image_print': args += ['--formats', 'stl']
                    # 单独转已有模型时，允许带上对应的参考原图做轮廓保真校验
                    if mode == 'print':
                        ref=str(body.get('reference','')).strip()
                        if ref:
                            if not os.path.isfile(ref): raise ValueError('参考图不存在')
                            args += ['--ref-image', ref]
                    # R30：可选导出质量门禁，默认全部关闭（与 fig.py 默认值一致）
                    args += print_quality_flags(body)
                with lock:
                    if jobs.get('running'): raise ValueError('已有任务正在运行')
                    jobs.clear(); jobs.update(running=True, output='', exit_code=None, mode=mode, job_id=secrets.token_hex(8))
                    job_id = jobs['job_id']
                def worker():
                    try:
                        env=os.environ.copy(); env['PYTHONIOENCODING']='utf-8'; env['PYTHONUTF8']='1'
                        proc=subprocess.Popen(args,cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env,creationflags=subprocess.CREATE_NO_WINDOW)
                        for line in proc.stdout:
                            with lock: jobs['output']=(jobs['output']+line)[-120000:]
                        code=proc.wait()
                    except Exception as e:
                        code=1
                        with lock: jobs['output'] += '\n启动失败: '+str(e)
                    with lock: jobs.update(running=False,exit_code=code)
                threading.Thread(target=worker,daemon=True).start(); self.send_json({'ok':True, 'job_id':job_id}); return
            raise ValueError('未知操作')
        except Exception as e: self.send_json({'error':str(e)},400)

def main():
    import sys
    threading.Thread(target=comfyui_idle_watchdog, daemon=True).start()
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    page = '/#edit-completion' if '--completion' in sys.argv else '/'
    url=f'http://127.0.0.1:{server.server_port}{PREFIX}{page}'
    print('控制中心：'+url,flush=True)
    webbrowser.open(url)
    server.serve_forever()
if __name__ == '__main__': main()
