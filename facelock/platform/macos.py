"""macOS platform backend for FaceLock."""

from __future__ import annotations

import ctypes
import logging
import subprocess

from facelock.platform.base import Backend

logger = logging.getLogger(__name__)


class MacOSBackend(Backend):
    """macOS backend using CoreGraphics/IOKit/AppleScript."""

    def lock(self) -> None:
        """Trigger native macOS screen lock (Ctrl + Cmd + Q or login framework)."""
        # 1. Attempt instantaneous lock via private login framework
        try:
            login = ctypes.cdll.LoadLibrary(
                "/System/Library/PrivateFrameworks/login.framework/Versions/Current/login"
            )
            if hasattr(login, "SACLockScreenImmediate"):
                login.SACLockScreenImmediate()
                logger.info("Triggered macOS screen lock via SACLockScreenImmediate")
                return
        except Exception:
            pass

        # 2. Hotkey fallback via AppleScript System Events (Ctrl+Cmd+Q)
        cmd = [
            "osascript",
            "-e",
            'tell application "System Events" to key code 12 using {control down, command down}',
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0:
                logger.info("Triggered macOS screen lock via AppleScript key code 12")
                return
        except Exception:
            pass

        # 3. CGSession suspend fallback
        try:
            cgsession_bin = (
                "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession"
            )
            subprocess.run([cgsession_bin, "-suspend"], check=False, timeout=3.0)
            logger.info("Triggered macOS screen lock via CGSession -suspend")
            return
        except Exception:
            pass

        # 4. Display sleep fallback
        try:
            subprocess.run(["pmset", "displaysleepnow"], check=False, timeout=3.0)
            logger.info("Triggered macOS screen lock via pmset displaysleepnow")
        except Exception as e:
            logger.warning("Failed to trigger macOS screen lock: %s", e)

    def is_locked(self) -> bool:
        """Check whether the macOS session is currently locked.

        Queries Quartz CoreGraphics session dictionary, falling back to ioreg.
        """
        # 1. Check via PyObjC Quartz if installed
        try:
            import Quartz  # type: ignore[import-not-found]

            session_dict = Quartz.CGSessionCopyCurrentDictionary()
            if session_dict and session_dict.get("CGSSessionScreenIsLocked"):
                return True
            return False
        except ImportError:
            pass
        except Exception:
            pass

        # 2. Check via ioreg root property dictionary
        try:
            out = subprocess.check_output(
                ["ioreg", "-n", "Root", "-d1"],
                text=True,
                timeout=2.0,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if "CGSSessionScreenIsLocked" in line:
                    # Output is usually: "CGSSessionScreenIsLocked" = Yes
                    return "Yes" in line or "true" in line.lower()
        except Exception:
            pass

        return False

    def get_idle_seconds(self) -> float | None:
        """Query system-wide input idle time via IOKit HIDSystem.

        Returns the elapsed seconds since the last mouse, keyboard, or trackpad event.
        """
        try:
            out = subprocess.check_output(
                ["ioreg", "-c", "IOHIDSystem"],
                text=True,
                timeout=1.5,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if "HIDIdleTime" in line:
                    # Line format: "HIDIdleTime" = 1234567890
                    parts = line.split("=")
                    if len(parts) >= 2:
                        val = parts[1].strip()
                        return float(val) / 1_000_000_000.0
        except Exception:
            pass

        return None
