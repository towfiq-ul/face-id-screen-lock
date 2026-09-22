from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from facelock import auth, pam


class TestAuthAndPAM(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_load_user_profiles_empty(self):
        empty_dir = self.tmp_path / "empty"
        empty_dir.mkdir()
        profiles = auth.load_user_profiles(empty_dir)
        self.assertEqual(profiles, {})

    def test_load_user_profiles_legacy(self):
        legacy_dir = self.tmp_path / "legacy"
        legacy_dir.mkdir()
        arr = np.random.randn(7, 136).astype(np.float32)
        np.save(legacy_dir / "known_face.npy", arr)

        profiles = auth.load_user_profiles(legacy_dir)
        self.assertIn("user", profiles)
        self.assertEqual(profiles["user"].shape, (7, 136))

    def test_authenticate_no_profiles(self):
        with patch("facelock.auth.load_user_profiles", return_value={}):
            success = auth.authenticate("dummy_user")
            self.assertFalse(success)

    def test_authenticate_success(self):
        dummy_profiles = {"Towfiq": np.random.randn(7, 136).astype(np.float32)}
        mock_cam = MagicMock()
        mock_cam._cap = MagicMock()
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_cam.read.return_value = test_frame

        with patch("facelock.auth.load_user_profiles", return_value=dummy_profiles):
            with patch("facelock.auth.Camera", return_value=mock_cam):
                with patch("facelock.auth.FaceEngine") as mock_engine_cls:
                    engine_inst = MagicMock()
                    face_row = np.zeros(15, dtype=np.float32)
                    face_row[:4] = [100, 100, 150, 150]
                    face_row[14] = 0.95
                    engine_inst.best_face.return_value = face_row

                    match_res = MagicMock()
                    match_res.matched = True
                    match_res.fused_score = 0.78
                    engine_inst.match_detailed.return_value = match_res
                    mock_engine_cls.return_value = engine_inst

                    with patch("facelock.auth.check_texture_liveness", return_value=(True, 20.0)):
                        success = auth.authenticate("Towfiq", timeout_seconds=1.0)
                        self.assertTrue(success)

    def test_pam_status_mocked(self):
        fake_pam = self.tmp_path / "fake_pam"
        fake_pam.write_text("# standard pam\n@include common-auth\n")

        with patch.object(pam, "PAM_GDM_PATH", fake_pam):
            self.assertFalse(pam.is_pam_enabled(fake_pam))

            fake_pam.write_text(f"# standard pam\n{pam.PAM_RULE}\n@include common-auth\n")
            self.assertTrue(pam.is_pam_enabled(fake_pam))

    def test_load_user_profiles_path_traversal_sanitized(self):
        import json
        data_dir = self.tmp_path / "user_data"
        faces_dir = data_dir / "faces"
        faces_dir.mkdir(parents=True)

        # Place a vector in parent dir
        secret_file = self.tmp_path / "secret.npy"
        np.save(secret_file, np.zeros((7, 136), dtype=np.float32))

        # profiles.json attempting path traversal
        meta = {
            "profiles": [
                {"name": "Attacker", "filename": "../../../secret.npy"}
            ]
        }
        with (data_dir / "profiles.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f)

        # Because Path(filename).name strips directory components, it searches faces/secret.npy (which doesn't exist)
        profiles = auth.load_user_profiles(data_dir)
        self.assertNotIn("Attacker", profiles)
