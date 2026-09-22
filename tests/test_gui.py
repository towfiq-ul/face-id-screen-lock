import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from facelock.config import Config
from facelock.gui import (
    ASSETS_DIR,
    LOGO_PATH,
    SPLASH_BANNER_PATH,
    FaceSetupGUI,
    SplashScreen,
    center_window_on_monitor,
    get_active_monitor_geometry,
)


class TestGUI(unittest.TestCase):
    def test_assets_exist(self):
        self.assertTrue(ASSETS_DIR.is_dir(), "ASSETS_DIR should be a directory")
        self.assertTrue(LOGO_PATH.is_file(), "logo_small.png should exist")
        self.assertTrue(SPLASH_BANNER_PATH.is_file(), "splash_banner.png should exist")
        self.assertGreater(LOGO_PATH.stat().st_size, 1000)
        self.assertGreater(SPLASH_BANNER_PATH.stat().st_size, 10000)

    def test_pose_prompts_count(self):
        self.assertEqual(len(FaceSetupGUI.POSE_PROMPTS), 7)
        targets = [p[2] for p in FaceSetupGUI.POSE_PROMPTS]
        self.assertEqual(targets, ["CENTER", "UP", "DOWN", "LEFT", "RIGHT", "BLINK", "SMILE"])

    @patch("subprocess.check_output")
    def test_get_active_monitor_geometry_multi_screen(self, mock_xrandr):
        # Multi-monitor setup: DP-1 on top, eDP-1 primary on bottom
        mock_xrandr.return_value = (
            "Monitors: 2\n"
            " 0: +*eDP-1 1920/309x1080/174+0+1080  eDP-1\n"
            " 1: +DP-1 1920/476x1080/268+0+0  DP-1\n"
        )
        # Pointer on top monitor (DP-1)
        mon_top = get_active_monitor_geometry(pointer_x=500, pointer_y=200)
        self.assertEqual(mon_top, (1920, 1080, 0, 0))

        # Pointer on bottom monitor (eDP-1)
        mon_bot = get_active_monitor_geometry(pointer_x=500, pointer_y=1500)
        self.assertEqual(mon_bot, (1920, 1080, 0, 1080))

        # Pointer unknown -> falls back to primary marked with * (eDP-1)
        mon_prim = get_active_monitor_geometry()
        self.assertEqual(mon_prim, (1920, 1080, 0, 1080))

    @patch("subprocess.check_output")
    def test_center_window_on_monitor_single_screen_confinement(self, mock_xrandr):
        mock_xrandr.return_value = (
            "Monitors: 2\n"
            " 0: +*eDP-1 1920/309x1080/174+0+1080  eDP-1\n"
            " 1: +DP-1 1920/476x1080/268+0+0  DP-1\n"
        )
        mock_root = MagicMock()
        mock_root.winfo_pointerxy.return_value = (500, 1500)  # on eDP-1
        center_window_on_monitor(mock_root, 620, 440)

        # Expected: x = 0 + (1920-620)//2 = 650, y = 1080 + (1080-440)//2 = 1400
        mock_root.geometry.assert_called_once_with("620x440+650+1400")

    @patch("threading.Thread")
    def test_splash_screen_init(self, mock_thread):
        cb = MagicMock()
        splash = SplashScreen(on_complete=cb)
        splash.root.withdraw()

        self.assertEqual(splash.on_complete, cb)

        # Test progress update helper
        splash.set_progress(50, "Halfway...")
        self.assertEqual(splash.status_lbl.cget("text"), "Halfway...")
        self.assertEqual(splash.percent_lbl.cget("text"), "50%")

        splash.root.destroy()

    def test_modern_button_custom_pad(self):
        import tkinter as tk
        from facelock.gui import ModernButton
        root = tk.Tk()
        root.withdraw()
        btn = ModernButton(root, text="Test", padx=10, pady=4)
        self.assertEqual(btn.cget("text"), "Test")
        root.destroy()

    @patch("facelock.gui.Camera")
    @patch("facelock.gui.FaceSetupGUI._video_loop")
    @patch("facelock.gui.FaceSetupGUI._update_daemon_status")
    def test_face_setup_gui_build_ui(self, mock_daemon, mock_video, mock_cam):
        mock_cam.return_value.open.return_value = True
        config = Config()
        mock_engine = MagicMock()
        gui = FaceSetupGUI(config, mock_engine)
        gui.root.withdraw()

        self.assertIsNotNone(gui.btn_top_calib)
        self.assertIsNotNone(gui.header_logo_img)
        gui._on_close()


if __name__ == "__main__":
    unittest.main()
