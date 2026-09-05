from __future__ import annotations

import logging
import os
import subprocess

from facelock.platform.base import Backend

logger = logging.getLogger(__name__)


class LinuxBackend(Backend):
    """Uses logind (loginctl) — works across GNOME/KDE/etc since it's the standard session API."""

    def _session_id(self) -> str | None:
        sid = os.environ.get("XDG_SESSION_ID")
        if sid:
            return sid
        try:
            # "Display" is logind's property for the user's graphical session id;
            # more reliable than the env var for a systemd --user service.
            out = subprocess.check_output(
                ["loginctl", "show-user", str(os.getuid()), "-p", "Display", "--value"],
                text=True,
            ).strip()
            return out or None
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def lock(self) -> None:
        sid = self._session_id()
        cmd = ["loginctl", "lock-session"] + ([sid] if sid else [])
        logger.info("Locking session: %s", cmd)
        subprocess.run(cmd, check=False)

    def is_locked(self) -> bool:
        sid = self._session_id()
        if not sid:
            return False
        try:
            out = subprocess.check_output(
                ["loginctl", "show-session", sid, "-p", "LockedHint", "--value"],
                text=True,
            ).strip()
            return out == "yes"
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
