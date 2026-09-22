from __future__ import annotations

import logging
import os
import subprocess

from facelock.platform.base import Backend

logger = logging.getLogger(__name__)


class LinuxBackend(Backend):
    """Uses logind (loginctl) — works across GNOME/KDE/etc since it's the standard session API."""

    def _session_id(self) -> str | None:
        # "Display" is logind's property for the user's graphical session id.
        # Check this first so running from SSH or non-graphical terminal multiplexers
        # still targets the desktop graphical session rather than the terminal session.
        try:
            out = subprocess.check_output(
                ["loginctl", "show-user", str(os.getuid()), "-p", "Display", "--value"],
                text=True,
                timeout=3.0,
            ).strip()
            if out:
                return out
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return os.environ.get("XDG_SESSION_ID") or None

    def lock(self) -> None:
        sid = self._session_id()
        cmd = ["loginctl", "lock-session"] + ([sid] if sid else [])
        logger.info("Locking session: %s", cmd)
        try:
            subprocess.run(cmd, check=False, timeout=3.0)
        except subprocess.TimeoutExpired:
            logger.warning("Lock session command timed out")

    def is_locked(self) -> bool:
        sid = self._session_id()
        if not sid:
            return False
        try:
            out = subprocess.check_output(
                ["loginctl", "show-session", sid, "-p", "LockedHint", "--value"],
                text=True,
                timeout=3.0,
            ).strip()
            return out == "yes"
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _get_gnome_mutter_idle(self) -> float | None:
        try:
            out = subprocess.check_output(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.Mutter.IdleMonitor",
                    "--object-path",
                    "/org/gnome/Mutter/IdleMonitor/Core",
                    "--method",
                    "org.gnome.Mutter.IdleMonitor.GetIdletime",
                ],
                text=True,
                timeout=1.5,
                stderr=subprocess.DEVNULL,
            ).strip()
            # Result format: '(uint64 12345,)'
            parts = out.strip("(),").split()
            if len(parts) >= 2:
                return float(parts[1]) / 1000.0
        except Exception:
            pass
        return None

    def _get_x11_idle(self) -> float | None:
        try:
            import ctypes

            class XScreenSaverInfo(ctypes.Structure):
                _fields_ = [
                    ("window", ctypes.c_ulong),
                    ("state", ctypes.c_int),
                    ("kind", ctypes.c_int),
                    ("til_or_since", ctypes.c_ulong),
                    ("idle", ctypes.c_ulong),
                    ("eventMask", ctypes.c_ulong),
                ]

            xlib = ctypes.cdll.LoadLibrary("libX11.so.6")
            xss = ctypes.cdll.LoadLibrary("libXss.so.1")
            display_str = os.environ.get("DISPLAY", ":0").encode()
            dpy = xlib.XOpenDisplay(display_str)
            if not dpy:
                return None
            root = xlib.XDefaultRootWindow(dpy)
            info = XScreenSaverInfo()
            xss.XScreenSaverQueryInfo(dpy, root, ctypes.byref(info))
            idle_s = float(info.idle) / 1000.0
            xlib.XCloseDisplay(dpy)
            return idle_s
        except Exception:
            pass
        return None

    def _get_xprintidle(self) -> float | None:
        try:
            out = subprocess.check_output(
                ["xprintidle"],
                text=True,
                timeout=1.0,
                stderr=subprocess.DEVNULL,
            ).strip()
            return float(out) / 1000.0
        except Exception:
            pass
        return None

    def get_idle_seconds(self) -> float | None:
        """Return the number of seconds since last user interaction.

        Queries input devices (keyboard, mouse, touchpad, touchscreen)
        across GNOME Mutter (Wayland/X11) and X11 XScreenSaver.
        """
        idle = self._get_gnome_mutter_idle()
        if idle is not None:
            return idle

        idle = self._get_x11_idle()
        if idle is not None:
            return idle

        idle = self._get_xprintidle()
        if idle is not None:
            return idle

        return None
