import http.server, json, os, secrets, subprocess, threading, urllib.parse, urllib.request, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / 'ComfyUI' / 'venv' / 'Scripts' / 'python.exe'
TOKEN = secrets.token_urlsafe(32)
PREFIX = '/' + TOKEN
jobs = {}
lock = threading.Lock()

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
        if route == '/':
            data = (ROOT / '启动器.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','no-referrer'); self.end_headers(); self.wfile.write(data); return
        if route == '/api/status':
            with lock: data = dict(jobs)
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
            if size > 16384: raise ValueError('请求过大')
            body = json.loads(self.rfile.read(size))
            route = urllib.parse.urlsplit(self.path).path[len(PREFIX):]
            if route == '/api/open':
                dirs = {'output': ROOT/'ComfyUI'/'output', 'print':Path(r'I:\AI\最终成品'), 'project':ROOT}
                target = dirs[body['folder']]; target.mkdir(parents=True,exist_ok=True); os.startfile(str(target)); self.send_json({'ok':True}); return
            if route == '/api/pick':
                import tkinter as tk
                from tkinter import filedialog
                root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
                try:
                    kind=body.get('kind'); types=[('图片','*.png *.jpg *.jpeg *.webp'),('所有文件','*.*')] if kind == 'image' else [('3D 模型','*.glb *.gltf *.obj *.stl *.ply *.3mf'),('所有文件','*.*')]
                    path=filedialog.askopenfilename(parent=root,title='选择图片' if kind=='image' else '选择3D模型',filetypes=types,initialdir=str(ROOT/'ComfyUI'/'output'))
                finally: root.destroy()
                self.send_json({'path':path}); return
            if route == '/api/run':
                mode=body['mode']
                if mode not in ('auto','img','i2i','model','print','doctor'): raise ValueError('不支持的操作')
                args=[str(PY),'-u',str(ROOT/'fig.py'),mode]
                if mode in ('auto','img','i2i'):
                    prompt=str(body.get('prompt','')).strip()
                    if not prompt: raise ValueError('请输入描述或提示词')
                if mode in ('i2i','model','print'):
                    path=str(body.get('path',''))
                    if not os.path.isfile(path): raise ValueError('请选择存在的输入文件')
                    args.append(path)
                if mode in ('auto','img','i2i'): args.append(prompt)
                if mode in ('img','i2i'): args += ['--retry','1','--no-check-bg']
                if mode in ('auto','print'):
                    height=float(body.get('height',150)); base=float(body.get('base',3)); hollow=float(body.get('hollow',0))
                    if not 10 <= height <= 500 or not 0 <= base <= 15 or not 0 <= hollow <= 10: raise ValueError('尺寸参数超出范围')
                    args += ['--model-height',str(height),'--out-dir',r'I:\AI\最终成品','--base',str(base/100),'--hollow',str(hollow/100)]
                with lock:
                    if jobs.get('running'): raise ValueError('已有任务正在运行')
                    jobs.clear(); jobs.update(running=True, output='', exit_code=None, mode=mode)
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
                threading.Thread(target=worker,daemon=True).start(); self.send_json({'ok':True}); return
            raise ValueError('未知操作')
        except Exception as e: self.send_json({'error':str(e)},400)

def main():
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}{PREFIX}/'
    print('控制中心：'+url,flush=True)
    webbrowser.open(url)
    server.serve_forever()
if __name__ == '__main__': main()
