"""Thin webcam wrapper so the rest of the code doesn't touch cv2.VideoCapture directly."""

from __future__ import annotations

import logging
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class Camera:
    def __init__(self, index: int = 0):
        self.index = index
        self._cap: cv2.VideoCapture | None = None
        self._open_failed_logged = False

    def open(self, retries: int = 3, delay: float = 0.15) -> bool:
        if self._cap is not None:
            return True
        for attempt in range(retries):
            cap = cv2.VideoCapture(self.index)
            if cap.isOpened():
                # Request minimal buffer size to avoid stale buffered frames under V4L2
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if self._open_failed_logged:
                    logger.info("Successfully opened camera index %s", self.index)
                    self._open_failed_logged = False
                self._cap = cap
                return True
            cap.release()
            if attempt < retries - 1:
                time.sleep(delay)

        if not self._open_failed_logged:
            logger.warning("Could not open camera index %s", self.index)
            self._open_failed_logged = True
        return False

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
