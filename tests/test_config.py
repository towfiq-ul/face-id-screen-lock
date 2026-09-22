import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from facelock.config import Config


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = Config()
        self.assertEqual(cfg.camera_index, 0)
        self.assertEqual(cfg.check_interval_seconds, 2.0)
        self.assertEqual(cfg.unknown_face_timeout_seconds, 60.0)
        self.assertEqual(cfg.match_threshold, 0.363)
        self.assertEqual(cfg.detection_score_threshold, 0.9)
        self.assertEqual(cfg.enroll_frame_count, 7)
        self.assertTrue(cfg.idle_detection_enabled)
        self.assertEqual(cfg.idle_timeout_seconds, 120.0)
        self.assertEqual(cfg.face_check_window_seconds, 30.0)
        self.assertEqual(cfg.min_match_percent, 92.0)

    def test_save_and_load_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cfg_file = tmp_path / "config.yaml"

            with patch("facelock.config.CONFIG_DIR", tmp_path), patch(
                "facelock.config.CONFIG_PATH", cfg_file
            ):
                cfg = Config(camera_index=1, unknown_face_timeout_seconds=30.0)
                cfg.save()

                self.assertTrue(cfg_file.exists())

                loaded = Config.load()
                self.assertEqual(loaded.camera_index, 1)
                self.assertEqual(loaded.unknown_face_timeout_seconds, 30.0)
                # Defaults preserved for omitted fields
                self.assertEqual(loaded.check_interval_seconds, 2.0)

    def test_xdg_env_fallback(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": ""}):
            resolved = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
            self.assertNotEqual(str(resolved), ".")
            self.assertEqual(resolved, Path.home() / ".config")


if __name__ == "__main__":
    unittest.main()
