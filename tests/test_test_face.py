from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from facelock.test_face import run_test


class TestFaceVerifier(unittest.TestCase):
    def test_run_test_no_profile(self):
        with patch("facelock.test_face.profiles.list_profiles", return_value={}):
            with patch("builtins.print") as mock_print:
                run_test(show_window=False, max_frames=1)
                self.assertTrue(any("No face profiles found" in str(c) for c in mock_print.call_args_list))

    def test_run_test_with_mocked_camera(self):
        dummy_embeddings = np.random.randn(7, 136).astype(np.float32)
        mock_cam = MagicMock()
        mock_cam._cap = MagicMock()
        # Return 2 valid test frames
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_cam.read.side_effect = [test_frame, test_frame, None]

        with patch("facelock.test_face.profiles.list_profiles", return_value={"MockUser": dummy_embeddings}):
            with patch("facelock.test_face.Camera", return_value=mock_cam):
                with patch("facelock.test_face.check_texture_liveness", return_value=(True, 25.0)):
                    with patch("facelock.test_face.FaceEngine") as mock_engine_cls:
                        engine_inst = MagicMock()
                        # Face row with confidence 0.95
                        face_row = np.zeros(15, dtype=np.float32)
                        face_row[0:4] = [100, 100, 150, 150]
                        # 5 landmarks
                        face_row[4:14] = [130, 130, 200, 130, 165, 170, 140, 210, 190, 210]
                        face_row[14] = 0.95
                        engine_inst.best_face.return_value = face_row

                        match_res = MagicMock()
                        match_res.matched = True
                        match_res.fused_score = 0.75
                        match_res.structure_score = 0.85
                        engine_inst.match_detailed.return_value = match_res
                        mock_engine_cls.return_value = engine_inst

                        # Run test for 2 frames
                        run_test(show_window=False, max_frames=2)
                        mock_cam.release.assert_called_once()
