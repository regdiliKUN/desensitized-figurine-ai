# -*- coding: utf-8 -*-
"""一键释放显存：vram_release 模块 + 控制中心接口/看门狗。"""
import http.client
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import vram_release  # noqa: E402
import control_server as cs  # noqa: E402


class _Resp:
    def __init__(self, body=b"{}"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body

    def close(self):
        pass


class _Run:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode = stdout, returncode


class VramReleaseModuleTests(unittest.TestCase):
    def _fake_urlopen(self, calls, ps_models=("qwen2.5vl:7b",)):
        def fake(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            body = getattr(req, "data", None)
            calls.append((url, json.loads(body) if body else None))
            if url.endswith("/api/ps"):
                return _Resp(json.dumps({"models": [{"name": m} for m in ps_models]}).encode())
            return _Resp(b"{}")
        return fake

    def test_soft_release_unloads_comfy_and_ollama_without_stopping(self):
        calls, used = [], iter([20000, 3000, 3000, 3000, 3000, 3000, 3000])
        smi = lambda *a, **k: _Run(f"{next(used)}, 24564\n") if "--query-gpu=memory.used,memory.total" in a[0] else _Run("")
        stop = mock.Mock()
        with mock.patch.object(vram_release.urllib.request, "urlopen", side_effect=self._fake_urlopen(calls)), \
             mock.patch.object(vram_release.subprocess, "run", side_effect=smi), \
             mock.patch.object(vram_release.time, "sleep"):
            r = vram_release.release("soft", stop_comfyui=stop, log=lambda *a, **k: None)
        stop.assert_not_called()
        free = [c for c in calls if c[0].endswith("/free")]
        self.assertEqual(free[0][1], {"unload_models": True, "free_memory": True})
        self.assertIn(("http://127.0.0.1:11434/api/generate", {"model": "qwen2.5vl:7b", "keep_alive": 0}), calls)
        self.assertEqual((r["before_mb"], r["after_mb"], r["freed_mb"]), (20000, 3000, 17000))

    def test_full_release_also_stops_comfyui(self):
        stop = mock.Mock(return_value=[1234])
        with mock.patch.object(vram_release.urllib.request, "urlopen", side_effect=self._fake_urlopen([], ())), \
             mock.patch.object(vram_release.subprocess, "run", return_value=_Run("")), \
             mock.patch.object(vram_release.time, "sleep"):
            r = vram_release.release("full", stop_comfyui=stop, log=lambda *a, **k: None)
        stop.assert_called_once()
        self.assertEqual(r["comfyui_stopped_pids"], [1234])

    def test_services_down_is_safe(self):
        with mock.patch.object(vram_release.urllib.request, "urlopen",
                               side_effect=vram_release.urllib.error.URLError("down")), \
             mock.patch.object(vram_release.subprocess, "run", side_effect=FileNotFoundError), \
             mock.patch.object(vram_release.time, "sleep"):
            r = vram_release.release("soft", log=lambda *a, **k: None)
        self.assertEqual(r["comfyui"], "not_running")
        self.assertIsNone(r["after_mb"])

    def test_bad_mode_rejected(self):
        with self.assertRaises(ValueError):
            vram_release.release("everything")


class ControlServerVramApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = cs.http.server.ThreadingHTTPServer(("127.0.0.1", 0), cs.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        cs.jobs.clear()
        cs.LAST_HEARTBEAT = cs.PAGE_CLOSED_AT = 0.0
        cs.AUTO_RELEASE = True

    def _post(self, route, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        origin = f"http://127.0.0.1:{self.port}"
        c.request("POST", cs.PREFIX + route, json.dumps(body),
                  {"Content-Type": "application/json", "Origin": origin, "Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_release_endpoint_calls_module(self):
        with mock.patch.object(cs.vram_release, "release", return_value={"freed_mb": 1}) as rel, \
             mock.patch.object(cs.vram_release, "comfyui_busy", return_value=False):
            status, data = self._post("/api/release_vram", {"mode": "full"})
        self.assertEqual(status, 200)
        self.assertEqual(rel.call_args.args[0], "full")
        self.assertEqual(data["report"], {"freed_mb": 1})

    def test_release_refused_while_job_running(self):
        cs.jobs["running"] = True
        with mock.patch.object(cs.vram_release, "release") as rel:
            status, data = self._post("/api/release_vram", {"mode": "soft"})
        self.assertEqual(status, 400)
        rel.assert_not_called()

    def test_page_closed_respects_auto_flag(self):
        self._post("/api/page_closed", {"auto": False})
        self.assertEqual(cs.PAGE_CLOSED_AT, 0.0)
        self.assertFalse(cs.AUTO_RELEASE)
        self._post("/api/page_closed", {"auto": True})
        self.assertGreater(cs.PAGE_CLOSED_AT, 0)


class WatchdogTests(unittest.TestCase):
    """跑看门狗一轮：sleep 第二次调用时抛异常跳出死循环。"""

    def _one_round(self, now):
        calls = {"n": 0}

        def fake_sleep(_):
            calls["n"] += 1
            if calls["n"] > 1:
                raise StopIteration

        with mock.patch.object(cs.time, "sleep", side_effect=fake_sleep), \
             mock.patch.object(cs.time, "time", return_value=now), \
             mock.patch.object(cs, "release_vram") as rel, \
             mock.patch.object(cs.vram_release, "comfyui_busy", return_value=False), \
             mock.patch.object(cs.vram_release, "comfyui_running", return_value=False):
            with self.assertRaises(StopIteration):
                cs.comfyui_idle_watchdog()
        return rel

    def setUp(self):
        cs.jobs.clear()
        cs.AUTO_RELEASE = True

    def test_release_after_page_close_grace(self):
        cs.LAST_HEARTBEAT, cs.PAGE_CLOSED_AT = 1000.0, 1001.0
        rel = self._one_round(1001.0 + cs.PAGE_CLOSE_GRACE_SECONDS + 1)
        rel.assert_called_once_with("full", "UI closed")
        self.assertEqual(cs.PAGE_CLOSED_AT, 0.0)

    def test_refresh_cancels_release(self):
        cs.PAGE_CLOSED_AT, cs.LAST_HEARTBEAT = 1001.0, 1003.0  # 新页面发来了心跳
        self._one_round(1001.0 + cs.PAGE_CLOSE_GRACE_SECONDS + 1).assert_not_called()

    def test_waits_for_running_job(self):
        cs.LAST_HEARTBEAT, cs.PAGE_CLOSED_AT = 1000.0, 1001.0
        cs.jobs["running"] = True
        self._one_round(5000.0).assert_not_called()

    def test_auto_release_disabled(self):
        cs.LAST_HEARTBEAT, cs.PAGE_CLOSED_AT = 1000.0, 1001.0
        cs.AUTO_RELEASE = False
        self._one_round(5000.0).assert_not_called()

    def test_heartbeat_lost_fallback(self):
        cs.LAST_HEARTBEAT, cs.PAGE_CLOSED_AT = 1000.0, 0.0
        self._one_round(1000.0 + cs.COMFY_IDLE_SECONDS + 1).assert_called_once_with("full", "UI heartbeat lost")


if __name__ == "__main__":
    unittest.main()
