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
