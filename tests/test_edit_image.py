"""Regression tests for the existing-image edit modes.

These tests stub the GPU call.  They protect the contract at the mode boundary:
selecting "whole image regeneration" must never route a painted selection through
the local crop-and-blend pipeline.
"""

from __future__ import annotations

import tempfile
import unittest
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fig
import control_server


class WholeImageEditModeTests(unittest.TestCase):
    def test_whole_mode_never_sends_a_selection_crop_to_qwen(self):
        """A UI whole-image choice may still carry a mask for user feedback.

        That mask must not change the backend into local crop editing: otherwise
        ComfyUI emits a close-up (for example just a leg) and the post-process
        pastes/blurs it back into the full image.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            mask_path = root / "marks.png"
            output = root / "output"
            output.mkdir()
            Image.new("RGB", (160, 96), (110, 160, 210)).save(source)
            selection = Image.new("L", (160, 96))
            ImageDraw.Draw(selection).rectangle((76, 24, 108, 78), fill=255)
            selection.save(mask_path)
            calls: list[tuple[str, str, int]] = []

            def fake_upload(path):
                return {"name": Path(path).name}

            def fake_qwen(image_name, instruction, seed, refs=None, cfg=4.0, steps=16):
                calls.append((image_name, instruction, steps))
                return "", Image.new("RGB", (160, 96), (60, 200, 130))

            args = SimpleNamespace(
                image=str(source), instruction="Remove the pose guide marks.",
                method="whole", mask=str(mask_path), seed=7, attempts=1,
                candidates=1, no_crop_local=False, refs=[],
            )
            with patch.object(fig, "OUT", str(output)), \
                 patch.object(fig, "ensure_comfyui_running"), \
                 patch.object(fig, "upload_image", side_effect=fake_upload), \
                 patch.object(fig, "run_qwen_edit", side_effect=fake_qwen), \
                 patch.object(fig, "flat_noise_ratio", return_value=(1.0, "ok")), \
                 patch.object(fig, "verified_output_path", side_effect=lambda name, *args: str(output / name)):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(fig.cmd_edit_image(args), 0)

            self.assertEqual([call[0] for call in calls], [source.name])
            self.assertIn("Never crop", calls[0][1])
            self.assertEqual(calls[0][2], 16)
            self.assertEqual(len(list(output.glob("fig_edit_whole*.png"))), 1)
            self.assertEqual(len(list(output.glob("fig_edit_local*.png"))), 0)

    def test_preserve_mark_cleanup_keeps_distant_source_pixels_and_crisp_core(self):
        original = Image.new("RGB", (40, 40), (40, 90, 180))
        edited = Image.new("RGB", (40, 40), (240, 90, 20))
        mask = Image.new("L", (40, 40))
        ImageDraw.Draw(mask).rectangle((12, 12, 27, 27), fill=255)

        result = fig._refine_local_blend(original, edited, mask, preserve_details=True)

        self.assertEqual(result.getpixel((0, 0)), original.getpixel((0, 0)))
        self.assertEqual(result.getpixel((20, 20)), edited.getpixel((20, 20)))

    def test_server_treats_only_local_variants_as_masked(self):
        self.assertTrue(control_server.edit_requires_mask("remove"))
        self.assertTrue(control_server.edit_requires_mask("local"))
        self.assertFalse(control_server.edit_requires_mask("whole"))
        self.assertFalse(control_server.edit_requires_mask("ai"))
        self.assertTrue(control_server.is_internal_qwen_edit_artifact("fig_edit_a0b1_00001_.png"))
        self.assertFalse(control_server.is_internal_qwen_edit_artifact("fig_edit_whole_a0b1.png"))


class ComfyUIExitCleanupTests(unittest.TestCase):
    class _FakeProc:
        def __init__(self):
            self.terminated = False
            self.killed = False
            self.waited = 0
            self.pid = 4321

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            self.waited = timeout
            return 0

    class _FakeResponse:
        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self):
            pass

        def read(self):
            return b"{}"

    def setUp(self):
        fig._CLEANUP_DONE = False
        fig._OWNED_COMFY_PROC = None

    def tearDown(self):
        fig._CLEANUP_DONE = False
        fig._OWNED_COMFY_PROC = None

    def test_owned_comfyui_is_stopped_with_process_tree(self):
        proc = self._FakeProc()
        fig._OWNED_COMFY_PROC = proc
        with patch.object(fig.subprocess, "run") as run:
            run.return_value.returncode = 0
            with contextlib.redirect_stdout(io.StringIO()):
                fig._cleanup_comfyui_on_exit()
        self.assertIsNone(fig._OWNED_COMFY_PROC)
        self.assertTrue(run.called)
        self.assertIn("/T", run.call_args.args[0])
        self.assertIn("/F", run.call_args.args[0])

    def test_external_comfyui_is_unloaded_but_not_killed(self):
        urls = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            urls.append(url)
            return self._FakeResponse(url)

        with patch.object(fig.urllib.request, "urlopen", side_effect=fake_urlopen), \
             contextlib.redirect_stdout(io.StringIO()):
            fig._cleanup_comfyui_on_exit()
        self.assertTrue(any(url.endswith("/free") for url in urls))

    def test_cleanup_is_safe_when_no_service_is_running(self):
        with patch.object(fig.urllib.request, "urlopen",
                          side_effect=fig.urllib.error.URLError("down")), \
             contextlib.redirect_stdout(io.StringIO()):
            fig._cleanup_comfyui_on_exit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
