"""Minimal OS backend interface — the only thing the monitor needs per-platform."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Backend(ABC):
    @abstractmethod
    def lock(self) -> None:
        """Trigger the OS screen lock."""

    @abstractmethod
    def is_locked(self) -> bool:
        """Whether the current session is currently locked."""

    def get_idle_seconds(self) -> float | None:
        """Return the number of seconds since last user interaction.

        Returns None if idle detection is unsupported on the platform.
        """
        return None
