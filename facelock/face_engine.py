"""Face detection + recognition using OpenCV's bundled YuNet + SFace ONNX models.

Chosen instead of dlib/face_recognition specifically to avoid a from-source
dlib build (no cmake/build toolchain assumed on the target machine) — this
only needs `pip install opencv-python numpy`.
"""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from facelock import config as cfg

logger = logging.getLogger(__name__)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("Downloading %s -> %s", url, dest)
    urllib.request.urlretrieve(url, tmp)
    with tmp.open("rb") as f:
        head = f.read(64)
    if head.startswith(b"version https://git-lfs"):
        tmp.unlink()
        raise RuntimeError(f"Got a Git LFS pointer instead of model data from {url}")
    tmp.rename(dest)


def ensure_models() -> None:
    if not cfg.YUNET_MODEL_PATH.exists():
        _download(cfg.YUNET_MODEL_URL, cfg.YUNET_MODEL_PATH)
    if not cfg.SFACE_MODEL_PATH.exists():
        _download(cfg.SFACE_MODEL_URL, cfg.SFACE_MODEL_PATH)


class FaceEngine:
    """Wraps YuNet detection + SFace embedding/matching for one video frame size."""

    def __init__(self, config: cfg.Config):
        ensure_models()
        self.config = config
        self._detector = cv2.FaceDetectorYN.create(
            str(cfg.YUNET_MODEL_PATH),
            "",
            (320, 320),
            config.detection_score_threshold,
            0.3,  # nms threshold
            5000,  # top_k
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(cfg.SFACE_MODEL_PATH), "")
        self._last_size: tuple[int, int] | None = None

    def _set_input_size(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        if self._last_size != (w, h):
            self._detector.setInputSize((w, h))
            self._last_size = (w, h)

    def best_face(self, frame: np.ndarray) -> np.ndarray | None:
        """Return the highest-confidence detected face row (YuNet's 15-value format), or None."""
        self._set_input_size(frame)
        _, faces = self._detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None
        best_idx = int(np.argmax(faces[:, 14]))
        return faces[best_idx]

    def embed(self, frame: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        aligned = self._recognizer.alignCrop(frame, face_row)
        return self._recognizer.feature(aligned)

    def matches_any(self, embedding: np.ndarray, known_embeddings: np.ndarray) -> tuple[bool, float]:
        """Compare `embedding` against every row in `known_embeddings`, return (is_match, best_score)."""
        best_score = -1.0
        for known in known_embeddings:
            score = self._recognizer.match(
                embedding, known.reshape(1, -1), cv2.FaceRecognizerSF_FR_COSINE
            )
            best_score = max(best_score, score)
        return best_score >= self.config.match_threshold, best_score
