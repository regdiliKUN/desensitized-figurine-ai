# -*- coding: utf-8 -*-
"""R58/R59：Meshy 输入链路的下载完整性与重试边界回归。

全部离线：urlopen / sleep / api_key 均被 mock，不访问网络、不消耗积分。
修复前对应两条实证缺陷：
  * HTTP 200 的 JSON 错误页被当成合法 GLB，原子覆盖既有成品并返回成功；
  * Retry-After 为 RFC 7231 允许的 HTTP-date 时 float() 裸抛 ValueError。
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import meshy_client as mc  # noqa: E402


class _FakeResponse:
    """支持 context manager、分块 read 与中途断流的最小响应体。"""

    def __init__(self, body, fail_after=None):
        self.body = body
        self.pos = 0
        self.fail_after = fail_after

    def read(self, n=-1):
        if self.fail_after is not None and self.pos >= self.fail_after:
            raise OSError("connection reset mid-stream")
        if n is None or n < 0:
            out = self.body[self.pos:]
            self.pos = len(self.body)
            return out
        if self.pos >= len(self.body):
            return b""
        out = self.body[self.pos:self.pos + n]
        self.pos += n
        return out

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _glb_bytes(truncate=False, bad_length=False):
    """构造不依赖 trimesh 的最小合法 GLB，只用于魔数/长度校验。"""
    payload = b'{"asset":{"version":"2.0"}}'
    payload = payload.ljust((len(payload) + 3) // 4 * 4, b" ")
    total = 12 + 8 + len(payload)
    declared = total + 7 if bad_length else total
    data = (b"glTF" + (2).to_bytes(4, "little")
            + declared.to_bytes(4, "little")
            + len(payload).to_bytes(4, "little") + b"JSON" + payload)
    return data[:-5] if truncate else data


def _http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://api.meshy.ai/x", code, "err",
                                  headers, io.BytesIO(b""))


class TestR58DownloadIntegrity(unittest.TestCase):
    """下载体必须是目标格式，且失败时不得覆盖既有成品、不得留下半成品。"""

    def setUp(self):
        mock.patch("time.sleep").start()
        self.addCleanup(mock.patch.stopall)

    def _download(self, body, out, **kwargs):
        with mock.patch.object(mc.urllib.request, "urlopen",
                               return_value=_FakeResponse(body)):
            return mc.download("https://example.invalid/m.glb", out, **kwargs)

    def test_r58_error_json_does_not_overwrite_existing_glb(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "model.glb")
            good = _glb_bytes()
            with open(out, "wb") as f:
                f.write(good)
            with self.assertRaises(RuntimeError) as ctx:
                self._download(b'{"error":"bad signature"}', out, attempts=1)
            self.assertIn("不是 GLB", str(ctx.exception))
            with open(out, "rb") as f:
                self.assertEqual(f.read(), good)
            self.assertEqual([n for n in os.listdir(d) if ".part" in n], [])

    def test_r58_valid_glb_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "m.glb")
            data = _glb_bytes()
            self.assertEqual(self._download(data, out, attempts=1), out)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), data)
            self.assertEqual([n for n in os.listdir(d) if ".part" in n], [])

    def test_r58_truncated_and_misdeclared_glb_are_rejected(self):
        for label, body in (("truncated", _glb_bytes(truncate=True)),
                            ("misdeclared", _glb_bytes(bad_length=True))):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "m.glb")
                good = _glb_bytes()
                with open(out, "wb") as f:
                    f.write(good)
                with self.assertRaises(RuntimeError):
                    self._download(body, out, attempts=1)
                with open(out, "rb") as f:
                    self.assertEqual(f.read(), good)

    def test_r58_png_error_page_is_rejected_but_valid_png_accepted(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "preview.png")
            with self.assertRaises(RuntimeError) as ctx:
                self._download(b"<!doctype html>error", out, attempts=1)
            self.assertIn("不是 PNG", str(ctx.exception))
            self.assertFalse(os.path.exists(out))
            self.assertEqual(self._download(png, out, attempts=1), out)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), png)

    def test_r58_mid_stream_failure_leaves_no_part_files(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "m.glb")
            good = _glb_bytes()
            with open(out, "wb") as f:
                f.write(good)
            resp = _FakeResponse(good, fail_after=8)
            with mock.patch.object(mc.urllib.request, "urlopen",
                                   return_value=resp):
                with self.assertRaises(RuntimeError):
                    mc.download("https://example.invalid/m.glb", out,
                                attempts=2)
            with open(out, "rb") as f:
                self.assertEqual(f.read(), good)
            self.assertEqual([n for n in os.listdir(d) if ".part" in n], [])


class TestR59RetryAfter(unittest.TestCase):
    """429/5xx 的退避解析必须容忍秒数、HTTP-date、非法值与越界值。"""

    def test_r59_seconds_clamp_and_fallback(self):
        self.assertAlmostEqual(mc._retry_after_seconds("12", 0), 12.0)
        self.assertAlmostEqual(mc._retry_after_seconds("99999", 0), 30.0)
        self.assertAlmostEqual(mc._retry_after_seconds("-5", 0), 0.0)
        self.assertAlmostEqual(mc._retry_after_seconds("nonsense", 0), 2.0)
        self.assertAlmostEqual(mc._retry_after_seconds("nan", 0), 2.0)
        self.assertAlmostEqual(mc._retry_after_seconds("inf", 0), 2.0)
        self.assertAlmostEqual(mc._retry_after_seconds(None, 2), 8.0)

    def test_r59_http_date_is_bounded_not_crashed(self):
        # 过去时间 -> 0；修复前 float('Wed, ...') 直接抛 ValueError。
        self.assertAlmostEqual(
            mc._retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT", 0), 0.0)

    def test_r59_http_date_429_is_retried_instead_of_crashing(self):
        responses = [_http_error(429, "Wed, 21 Oct 2015 07:28:00 GMT"),
                     _FakeResponse(b'{"ok": 1}')]
        self.addCleanup(getattr(responses[0], "close", lambda: None))
        with mock.patch.object(mc, "api_key", return_value="test-key"), \
             mock.patch.object(mc.urllib.request, "urlopen",
                               side_effect=responses), \
             mock.patch("time.sleep") as sleep:
            result = mc._request("GET", "/balance")
        self.assertEqual(result, {"ok": 1})
        sleep.assert_called_once()
        self.assertGreaterEqual(sleep.call_args[0][0], 0.0)
        self.assertLessEqual(sleep.call_args[0][0], 30.0)

    def test_r59_large_retry_after_is_honoured_then_clamped(self):
        responses = [_http_error(503, "99999"), _FakeResponse(b'{"ok": 1}')]
        self.addCleanup(getattr(responses[0], "close", lambda: None))
        with mock.patch.object(mc, "api_key", return_value="test-key"), \
             mock.patch.object(mc.urllib.request, "urlopen",
                               side_effect=responses), \
             mock.patch("time.sleep") as sleep:
            self.assertEqual(mc._request("GET", "/balance"), {"ok": 1})
        self.assertAlmostEqual(sleep.call_args[0][0], 30.0)


class TestMultiviewReuse(unittest.TestCase):
    def _views(self, d):
        paths = []
        for i in range(3):
            p = os.path.join(d, f"view{i}.png")
            with open(p, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\nfake")
            paths.append(p)
        return paths

    def test_reuse_views_skips_paid_image_generation(self):
        with tempfile.TemporaryDirectory() as d:
            views = self._views(d)
            source = os.path.join(d, "front.png")
            with open(source, "wb") as f:
                f.write(b"source")
            task = {"status": "SUCCEEDED", "model_urls": {"glb": "https://example.invalid/m.glb"}}
            with mock.patch.object(mc, "create_image_to_image") as i2i, \
                 mock.patch.object(mc, "create_multi_image_to_3d", return_value="task-1") as create, \
                 mock.patch.object(mc, "wait_endpoint_task", return_value=task), \
                 mock.patch.object(mc, "download"):
                glb, used, got = mc.multiview_to_3d(
                    source, out_dir=d, view_paths=views, should_texture=False)
            i2i.assert_not_called()
            self.assertEqual(used, views)
            self.assertEqual(got, task)
            create.assert_called_once()
            self.assertEqual(create.call_args.args[0], views)
            manifests = [n for n in os.listdir(os.path.join(d, "_meshy_views"))
                         if n.endswith("_views.json")]
            self.assertEqual(len(manifests), 1)

    def test_low_balance_aborts_before_paid_generation(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "front.png")
            with open(source, "wb") as f:
                f.write(b"source")
            with mock.patch.object(mc, "balance", return_value=5), \
                 mock.patch.object(mc, "create_image_to_image") as i2i:
                with self.assertRaises(RuntimeError):
                    mc.multiview_to_3d(source, out_dir=d)
            i2i.assert_not_called()


class TestFrontViewOrdering(unittest.TestCase):
    def test_front_view_is_moved_first_by_silhouette_iou(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as d:
            def make(name, box):
                im = Image.new("RGB", (128, 128), "white")
                ImageDraw.Draw(im).rectangle(box, fill="black")
                p = os.path.join(d, name)
                im.save(p)
                return p
            source = make("source.png", (24, 4, 104, 124))
            side = make("side.png", (48, 4, 80, 124))
            front = make("front.png", (24, 4, 104, 124))
            back = make("back.png", (32, 4, 96, 124))
            ordered, info = mc._pick_front_view([side, front, back], source)
            self.assertEqual(ordered[0], front)
            self.assertTrue(info["reordered"])
            self.assertEqual(info["front_index"], 1)


class TestInputValidation(unittest.TestCase):
    def _png(self, d, name, size=(64, 64)):
        from PIL import Image
        p = os.path.join(d, name)
        Image.new("RGB", size, "white").save(p)
        return p

    def test_data_uri_uses_actual_format_not_extension(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "actually_jpeg.png")
            from PIL import Image
            Image.new("RGB", (64, 64), "white").save(p, format="JPEG")
            uri = mc.data_uri(p)
            self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
            bad = os.path.join(d, "fake.png")
            with open(bad, "wb") as f:
                f.write(b"not an image")
            with self.assertRaises(ValueError):
                mc.data_uri(bad)

    def test_data_uri_rejects_too_small_image(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._png(d, "tiny.png", (16, 16))
            with self.assertRaises(ValueError):
                mc.data_uri(p)

    def test_explicit_view_order_is_not_reordered(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as d:
            def make(name, box):
                im = Image.new("RGB", (128, 128), "white")
                ImageDraw.Draw(im).rectangle(box, fill="black")
                p = os.path.join(d, name); im.save(p); return p
            source = make("source.png", (24, 4, 104, 124))
            side = make("side.png", (48, 4, 80, 124))
            front = make("front.png", (24, 4, 104, 124))
            ordered, info = mc._pick_front_view([side, front], source, auto=False)
            self.assertEqual(ordered, [side, front])
            self.assertFalse(info["reordered"])

    def test_credit_estimate_depends_on_geometry_and_reuse(self):
        self.assertEqual(mc.estimate_multiview_credits("2k", True), 28)
        self.assertEqual(mc.estimate_multiview_credits("2k", False), 25)
        self.assertEqual(mc.estimate_multiview_credits("standard", True), 23)

    def test_multiview_reuse_requires_at_least_two_views(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "one.png")
            with open(p, "wb") as f:
                f.write(b"x")
            with self.assertRaises(ValueError):
                mc.multiview_to_3d(p, out_dir=d, view_paths=[p])

    def test_download_image_uses_real_jpeg_extension(self):
        with tempfile.TemporaryDirectory() as d:
            jpeg = b"\xff\xd8\xff\xe0" + b"fake body"
            with mock.patch.object(mc.urllib.request, "urlopen",
                                   return_value=_FakeResponse(jpeg)):
                out = mc.download_image("https://example.invalid/view", os.path.join(d, "view0"))
            self.assertTrue(out.endswith(".jpg"))
            with open(out, "rb") as f:
                self.assertEqual(f.read(), jpeg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
