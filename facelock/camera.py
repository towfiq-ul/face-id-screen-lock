"""Thin webcam wrapper so the rest of the code doesn't touch cv2.VideoCapture directly."""

from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class Camera:
    def __init__(self, index: int = 0):
        self.index = index
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> bool:
        if self._cap is not None:
            return True
        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            cap.release()
            logger.warning("Could not open camera index %s", self.index)
            return False
        self._cap = cap
        return True

    def read(self) -> np.ndarray | None:
        if self._cap is None and not self.open():
            return None
        ok, frame = self._cap.read()
        if not ok:
            logger.warning("Camera read failed, releasing handle")
            self.release()
            return None
        return frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
