# -*- coding: utf-8 -*-
"""工具生命周期回归：显存清理、启动互斥、视图参数边界。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fig  # noqa: E402


class _Resp:
    def __init__(self, body=b"{}"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body

    def close(self):
        return None


class TestCleanup(unittest.TestCase):
    def tearDown(self):
        fig._CLEANUP_DONE = False

    def test_external_free_is_one_shot_and_skipped_when_queue_busy(self):
        with mock.patch.object(fig, "_OWNED_COMFY_PROC", None), \
             mock.patch.object(fig, "_CLEANUP_DONE", False), \
             mock.patch.object(fig, "_comfyui_queue_idle", return_value=True), \
             mock.patch.object(fig.urllib.request, "urlopen", return_value=_Resp()), \
             mock.patch.object(fig, "_release_comfyui_memory") as free:
            fig._cleanup_comfyui_on_exit()
            fig._cleanup_comfyui_on_exit()
        free.assert_called_once()

    def test_external_free_not_called_while_other_job_runs(self):
        with mock.patch.object(fig, "_OWNED_COMFY_PROC", None), \
             mock.patch.object(fig, "_CLEANUP_DONE", False), \
             mock.patch.object(fig, "_comfyui_queue_idle", return_value=False), \
             mock.patch.object(fig.urllib.request, "urlopen", return_value=_Resp()), \
             mock.patch.object(fig, "_release_comfyui_memory") as free:
            fig._cleanup_comfyui_on_exit()
        free.assert_not_called()

    def test_owned_process_is_killed_with_tree_on_windows(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.pid = 4321
        with mock.patch.object(fig, "_OWNED_COMFY_PROC", proc), \
             mock.patch.object(fig.os, "name", "nt"), \
             mock.patch.object(fig.subprocess, "run") as run:
            run.return_value.returncode = 0
            fig._stop_owned_comfyui()
        run.assert_called_once()
        self.assertIn("/T", run.call_args.args[0])
        self.assertIn("/F", run.call_args.args[0])

    def test_queue_idle_returns_false_on_network_error(self):
        with mock.patch.object(fig.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertFalse(fig._comfyui_queue_idle())

    def test_queue_idle_requires_both_lists_empty(self):
        body = json.dumps({"queue_running": [], "queue_pending": []}).encode()
        with mock.patch.object(fig.urllib.request, "urlopen", return_value=_Resp(body)):
            self.assertTrue(fig._comfyui_queue_idle())
        body = json.dumps({"queue_running": [1], "queue_pending": []}).encode()
        with mock.patch.object(fig.urllib.request, "urlopen", return_value=_Resp(body)):
            self.assertFalse(fig._comfyui_queue_idle())


class TestViewArgs(unittest.TestCase):
    def test_same_file_cannot_be_two_views(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.png")
            with open(p, "wb") as f:
                f.write(b"x")
            with self.assertRaises(ValueError):
                fig._parse_mv_refs([f"front={p}", f"left={p}"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
