import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from facelock.desktop import (
    ICON_SIZES,
    install_desktop,
    main,
    uninstall_desktop,
)


class TestDesktopIntegration(unittest.TestCase):
    def setUp(self):
        self.repo_dir = Path(__file__).resolve().parent.parent
        self.desktop_file = self.repo_dir / "packaging" / "facelock.desktop"
        self.logo_file = self.repo_dir / "facelock" / "assets" / "logo.png"

    def test_desktop_file_exists_and_fields(self):
        self.assertTrue(self.desktop_file.is_file(), "packaging/facelock.desktop should exist")
        content = self.desktop_file.read_text(encoding="utf-8")

        self.assertIn("[Desktop Entry]", content)
        self.assertIn("Name=FaceLock", content)
        self.assertIn("Exec=facelock-gui", content)
        self.assertIn("Icon=facelock", content)
        self.assertIn("StartupWMClass=facelock", content)
        self.assertIn("Categories=System;Security;", content)
        self.assertIn("Actions=Calibrate;Verify;", content)

    def test_desktop_file_validate_tool(self):
        if shutil.which("desktop-file-validate"):
            result = subprocess.run(
                ["desktop-file-validate", str(self.desktop_file)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"desktop-file-validate failed with errors/warnings: {result.stderr or result.stdout}",
            )

    def test_logo_asset_exists(self):
        self.assertTrue(self.logo_file.is_file(), "facelock/assets/logo.png should exist")
        self.assertGreater(self.logo_file.stat().st_size, 10000)

    def test_install_and_uninstall_desktop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir)
            installed = install_desktop(repo_dir=self.repo_dir, prefix=prefix)
            self.assertTrue(installed, "install_desktop should succeed")

            # Check desktop entry
            dst_desktop = prefix / "share" / "applications" / "facelock.desktop"
            self.assertTrue(dst_desktop.is_file(), "facelock.desktop should be installed")
            self.assertEqual(oct(os.stat(dst_desktop).st_mode & 0o777), "0o644")

            # Check pixmaps icon
            dst_pixmap = prefix / "share" / "pixmaps" / "facelock.png"
            self.assertTrue(dst_pixmap.is_file(), "facelock.png should be in pixmaps")

            # Check all hicolor icons
            for size in ICON_SIZES:
                dst_icon = prefix / "share" / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "facelock.png"
                self.assertTrue(dst_icon.is_file(), f"hicolor {size}x{size} icon should be created")

            # Test uninstall
            uninstalled = uninstall_desktop(prefix=prefix)
            self.assertTrue(uninstalled, "uninstall_desktop should succeed")

            self.assertFalse(dst_desktop.exists(), "facelock.desktop should be removed")
            self.assertFalse(dst_pixmap.exists(), "pixmaps icon should be removed")
            for size in ICON_SIZES:
                dst_icon = prefix / "share" / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "facelock.png"
                self.assertFalse(dst_icon.exists(), f"hicolor {size}x{size} icon should be removed")

    def test_cli_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir)
            ret = main(["--install", "--prefix", str(prefix), "--repo-dir", str(self.repo_dir)])
            self.assertEqual(ret, 0)
            self.assertTrue((prefix / "share" / "applications" / "facelock.desktop").is_file())

            ret_un = main(["--uninstall", "--prefix", str(prefix)])
            self.assertEqual(ret_un, 0)
            self.assertFalse((prefix / "share" / "applications" / "facelock.desktop").exists())


if __name__ == "__main__":
    unittest.main()
