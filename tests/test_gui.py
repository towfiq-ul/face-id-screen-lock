import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from facelock.config import Config
from facelock.gui import (
    ASSETS_DIR,
    LOGO_PATH,
    SPLASH_BANNER_PATH,
    FaceSetupGUI,
    SettingsDialog,
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
        self.assertIsNotNone(gui.btn_toggle_daemon)
        self.assertIsNotNone(gui.header_logo_img)
        gui._on_close()

    @patch("subprocess.run")
    @patch("facelock.gui.Camera")
    @patch("facelock.gui.FaceSetupGUI._video_loop")
    @patch("facelock.gui.FaceSetupGUI._update_daemon_status")
    def test_toggle_daemon_action(self, mock_status, mock_video, mock_cam, mock_sub):
        mock_cam.return_value.open.return_value = True
        config = Config()
        mock_engine = MagicMock()
        gui = FaceSetupGUI(config, mock_engine)
        gui.root.withdraw()

        gui.daemon_active = True
        gui._toggle_daemon()
        gui.root.update()
        # Should initiate stop command
        mock_sub.assert_called_with(["systemctl", "--user", "stop", "facelock-monitor"], check=False, timeout=5.0)

        gui._on_close()

    def test_settings_dialog_load_and_save(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()

        cfg = Config(
            idle_timeout_seconds=120.0,
            face_check_window_seconds=30.0,
            check_interval_seconds=2.0,
            min_match_percent=92.0,
        )
        saved_configs = []

        with patch.object(cfg, "save") as mock_save:
            dlg = SettingsDialog(root, cfg, on_save_callback=lambda c: saved_configs.append(c))
            dlg.withdraw()

            # Verify initial form values
            self.assertEqual(dlg.var_idle_timeout.get(), "120")
            self.assertEqual(dlg.var_face_window.get(), "30")
            self.assertEqual(dlg.var_check_interval.get(), "2.0")
            self.assertEqual(dlg.var_min_match.get(), 92.0)
            self.assertTrue(dlg.var_idle_enabled.get())

            # Change values
            dlg.var_idle_timeout.set("180")
            dlg.var_face_window.set("45")
            dlg.var_min_match.set(95.0)
            dlg.var_check_interval.set("1.5")

            dlg._save()

            mock_save.assert_called_once()
            self.assertEqual(len(saved_configs), 1)
            self.assertEqual(saved_configs[0].idle_timeout_seconds, 180.0)
            self.assertEqual(saved_configs[0].face_check_window_seconds, 45.0)
            self.assertEqual(saved_configs[0].min_match_percent, 95.0)
            self.assertEqual(saved_configs[0].check_interval_seconds, 1.5)

        root.destroy()

    @patch("tkinter.messagebox.showerror")
    def test_settings_dialog_validation_error(self, mock_err):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()

        cfg = Config()
        with patch.object(cfg, "save") as mock_save:
            dlg = SettingsDialog(root, cfg)
            dlg.withdraw()

            # Invalid idle timeout < 5 seconds
            dlg.var_idle_timeout.set("2")
            dlg._save()
            mock_err.assert_called_once()
            mock_save.assert_not_called()

            # Invalid face window < 2 seconds
            mock_err.reset_mock()
            dlg.var_idle_timeout.set("120")
            dlg.var_face_window.set("1")
            dlg._save()
            mock_err.assert_called_once()
            mock_save.assert_not_called()

            # Invalid camera index < 0
            mock_err.reset_mock()
            dlg.var_face_window.set("30")
            dlg.var_cam_idx.set("-1")
            dlg._save()
            mock_err.assert_called_once()
            mock_save.assert_not_called()

            dlg.destroy()

        root.destroy()

    @patch("facelock.gui.Camera")
    @patch("facelock.gui.FaceSetupGUI._video_loop")
    @patch("facelock.gui.FaceSetupGUI._update_daemon_status")
    @patch("tkinter.messagebox.showinfo")
    def test_face_setup_gui_settings_integration(self, mock_info, mock_status, mock_video, mock_cam):
        mock_cam.return_value.open.return_value = True
        config = Config(idle_timeout_seconds=120.0, face_check_window_seconds=30.0, min_match_percent=92.0)
        mock_engine = MagicMock()
        gui = FaceSetupGUI(config, mock_engine)
        gui.root.withdraw()

        # Check buttons and description
        self.assertIsNotNone(gui.btn_top_settings)
        self.assertIsNotNone(gui.btn_daemon_config)
        desc = gui._get_daemon_desc_text()
        self.assertIn("Idle: 120s", desc)
        self.assertIn("Window: 30s", desc)
        self.assertIn("Match: 92%", desc)

        # Test settings saved callback
        with patch.object(gui, "_restart_daemon") as mock_restart:
            new_cfg = Config(idle_timeout_seconds=300.0, face_check_window_seconds=45.0, min_match_percent=95.0)
            gui._on_settings_saved(new_cfg)
            self.assertEqual(gui.config.idle_timeout_seconds, 300.0)
            mock_restart.assert_called_once()
            mock_info.assert_called_once()
            self.assertIn("Idle: 300s", gui.daemon_desc_lbl.cget("text"))

        gui._on_close()


if __name__ == "__main__":
    unittest.main()

