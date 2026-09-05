"""Enrollment: capture several webcam frames of the user's face and store embeddings."""

from __future__ import annotations

import logging
import time

import numpy as np

from facelock import config as cfg
from facelock.camera import Camera
from facelock.face_engine import FaceEngine

logger = logging.getLogger(__name__)


def enroll(config: cfg.Config | None = None) -> None:
    config = config or cfg.Config.load()
    cfg.ensure_dirs()
    engine = FaceEngine(config)

    print(f"Enrolling face using camera index {config.camera_index}.")
    print("Look at the camera and slowly turn your head slightly between captures.")

    embeddings: list[np.ndarray] = []
    with Camera(config.camera_index) as camera:
        if camera._cap is None:
            raise SystemExit(f"Could not open camera index {config.camera_index}")

        last_capture = 0.0
        while len(embeddings) < config.enroll_frame_count:
            frame = camera.read()
            if frame is None:
                raise SystemExit("Camera stopped returning frames during enrollment")

            face = engine.best_face(frame)
            if face is None:
                continue

            now = time.monotonic()
            if now - last_capture < 0.5:
                continue  # let the user shift pose a little between captures

            embedding = engine.embed(frame, face)
            embeddings.append(embedding.reshape(-1))
            last_capture = now
            print(f"Captured {len(embeddings)}/{config.enroll_frame_count}")

    known = np.stack(embeddings)
    np.save(cfg.KNOWN_FACE_PATH, known)
    print(f"Saved {len(embeddings)} face embeddings to {cfg.KNOWN_FACE_PATH}")
