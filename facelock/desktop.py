"""Desktop Entry and Icon Theme Manager for FaceLock.

Manages XDG-compliant .desktop file and multi-resolution hicolor icon
installation for system-wide (/usr/share) or per-user (~/.local/share).
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys

logger = logging.getLogger("facelock.desktop")

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def resize_and_save_icon(src_img_path: Path, dst_path: Path, size: int) -> bool:
    """Resize image to square dimensions and save as PNG."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    # 1. Try PIL (Pillow)
    try:
        from PIL import Image

        with Image.open(src_img_path) as img:
            resized = img.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(dst_path, format="PNG")
            return True
    except Exception:
        pass

    # 2. Try OpenCV
    try:
        import cv2

        raw = cv2.imread(str(src_img_path), cv2.IMREAD_UNCHANGED)
        if raw is not None:
            scaled = cv2.resize(raw, (size, size), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(dst_path), scaled)
            return True
    except Exception:
        pass

    # 3. Fallback: Copy source file directly
    try:
        shutil.copy2(src_img_path, dst_path)
        return True
    except Exception as e:
        logger.error("Failed to copy icon to %s: %s", dst_path, e)
        return False


def get_target_dirs(system: bool = False, prefix: Path | None = None) -> tuple[Path, Path, Path]:
    """Return (applications_dir, pixmaps_dir, hicolor_dir)."""
    if prefix is not None:
        share = prefix / "share"
    elif system:
        share = Path("/usr/share")
    else:
        user_data = os.environ.get("XDG_DATA_HOME")
        if user_data:
            share = Path(user_data)
        else:
            share = Path.home() / ".local" / "share"

    apps_dir = share / "applications"
    pixmaps_dir = share / "pixmaps"
    hicolor_dir = share / "icons" / "hicolor"
    return apps_dir, pixmaps_dir, hicolor_dir


def install_desktop(
    repo_dir: Path | None = None,
    system: bool = False,
    prefix: Path | None = None,
) -> bool:
    """Install .desktop file and icons to target directory structure."""
    if repo_dir is None:
        repo_dir = Path(__file__).resolve().parent.parent

    desktop_src = repo_dir / "packaging" / "facelock.desktop"
    logo_src = repo_dir / "facelock" / "assets" / "logo.png"

    if not desktop_src.exists():
        logger.error("Desktop source not found: %s", desktop_src)
        return False

    if not logo_src.exists():
        logo_src = repo_dir / "facelock" / "assets" / "logo_small.png"
        if not logo_src.exists():
            logger.error("Logo source not found in %s", repo_dir / "facelock" / "assets")
            return False

    apps_dir, pixmaps_dir, hicolor_dir = get_target_dirs(system, prefix)

    apps_dir.mkdir(parents=True, exist_ok=True)
    pixmaps_dir.mkdir(parents=True, exist_ok=True)

    # 1. Install desktop file
    dst_desktop = apps_dir / "facelock.desktop"
    shutil.copy2(desktop_src, dst_desktop)
    os.chmod(dst_desktop, 0o644)
    logger.info("Installed desktop file -> %s", dst_desktop)

    # 2. Install pixmap icon
    dst_pixmap = pixmaps_dir / "facelock.png"
    shutil.copy2(logo_src, dst_pixmap)
    os.chmod(dst_pixmap, 0o644)
    logger.info("Installed pixmap icon -> %s", dst_pixmap)

    # 3. Generate multi-resolution hicolor icons
    for size in ICON_SIZES:
        dst_icon = hicolor_dir / f"{size}x{size}" / "apps" / "facelock.png"
        if resize_and_save_icon(logo_src, dst_icon, size):
            os.chmod(dst_icon, 0o644)
            logger.info("Installed hicolor %dx%d icon -> %s", size, size, dst_icon)

    # 4. Update desktop & icon caches if available and not custom prefix
    if prefix is None:
        update_caches(apps_dir, hicolor_dir)

    return True


def uninstall_desktop(
    system: bool = False,
    prefix: Path | None = None,
) -> bool:
    """Remove desktop file and installed icons."""
    apps_dir, pixmaps_dir, hicolor_dir = get_target_dirs(system, prefix)

    desktop_file = apps_dir / "facelock.desktop"
    if desktop_file.exists():
        desktop_file.unlink()
        logger.info("Removed %s", desktop_file)

    pixmap_file = pixmaps_dir / "facelock.png"
    if pixmap_file.exists():
        pixmap_file.unlink()
        logger.info("Removed %s", pixmap_file)

    for size in ICON_SIZES:
        icon_file = hicolor_dir / f"{size}x{size}" / "apps" / "facelock.png"
        if icon_file.exists():
            icon_file.unlink()
            logger.info("Removed %s", icon_file)

    if prefix is None:
        update_caches(apps_dir, hicolor_dir)

    return True


def update_caches(apps_dir: Path, hicolor_dir: Path) -> None:
    """Run update-desktop-database and gtk-update-icon-cache if tools exist."""
    if shutil.which("update-desktop-database"):
        try:
            subprocess.run(
                ["update-desktop-database", str(apps_dir)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    if shutil.which("gtk-update-icon-cache"):
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "-q", "-t", "-f", str(hicolor_dir)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install/Uninstall FaceLock desktop entry and icons.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Install desktop file and icons")
    group.add_argument("--uninstall", action="store_true", help="Uninstall desktop file and icons")

    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--system", action="store_true", help="Install system-wide (/usr/share)")
    target_group.add_argument("--user", action="store_true", default=True, help="Install for current user (~/.local/share)")

    parser.add_argument("--repo-dir", type=Path, default=None, help="Root directory of repository")
    parser.add_argument("--prefix", type=Path, default=None, help="Custom installation prefix (e.g. for testing)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    if args.install:
        success = install_desktop(repo_dir=args.repo_dir, system=args.system, prefix=args.prefix)
        return 0 if success else 1
    elif args.uninstall:
        success = uninstall_desktop(system=args.system, prefix=args.prefix)
        return 0 if success else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
