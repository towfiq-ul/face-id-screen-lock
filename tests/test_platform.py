import os
import subprocess
import unittest
from unittest.mock import patch

from facelock.platform.base import Backend
from facelock.platform.linux import LinuxBackend


class TestPlatformLinux(unittest.TestCase):
    def test_backend_subclass(self):
        backend = LinuxBackend()
        self.assertIsInstance(backend, Backend)

    @patch("subprocess.check_output")
    def test_session_id_prioritizes_display(self, mock_output):
        mock_output.return_value = "5\n"
        with patch.dict(os.environ, {"XDG_SESSION_ID": "2"}):
            backend = LinuxBackend()
            sid = backend._session_id()
            self.assertEqual(sid, "5")
            mock_output.assert_called_once()

    @patch("subprocess.check_output")
    def test_session_id_fallback_to_env(self, mock_output):
        mock_output.side_effect = subprocess.CalledProcessError(1, ["loginctl"])
        with patch.dict(os.environ, {"XDG_SESSION_ID": "2"}):
            backend = LinuxBackend()
            sid = backend._session_id()
            self.assertEqual(sid, "2")

    @patch("subprocess.check_output")
    def test_is_locked(self, mock_output):
        # First call for Display, second for LockedHint
        mock_output.side_effect = ["3\n", "yes\n"]
        backend = LinuxBackend()
        self.assertTrue(backend.is_locked())

        mock_output.side_effect = ["3\n", "no\n"]
        self.assertFalse(backend.is_locked())

    @patch("subprocess.run")
    @patch("subprocess.check_output")
    def test_lock_command(self, mock_output, mock_run):
        mock_output.return_value = "3\n"
        backend = LinuxBackend()
        backend.lock()
        mock_run.assert_called_once_with(["loginctl", "lock-session", "3"], check=False, timeout=3.0)


if __name__ == "__main__":
    unittest.main()
