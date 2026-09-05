"""Config and on-disk paths for the facelock monitor.

All state lives under the user's own home directory (XDG dirs) — this
package never needs root and never touches system files. PAM/unlock is
handled entirely by Howdy, installed separately.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

CONFIG_DIR = XDG_CONFIG_HOME / "facelock"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

DATA_DIR = XDG_DATA_HOME / "facelock"
MODELS_DIR = DATA_DIR / "models"
KNOWN_FACE_PATH = DATA_DIR / "known_face.npy"


# These files are Git LFS-tracked in opencv_zoo, so they must come from the
# LFS media endpoint — plain raw.githubusercontent.com serves the LFS
# pointer text file instead of the actual binary.
YUNET_MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SFACE_MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)
YUNET_MODEL_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_MODEL_PATH = MODELS_DIR / "face_recognition_sface_2021dec.onnx"


@dataclass
class Config:
    camera_index: int = 0
    check_interval_seconds: float = 2.0
    unknown_face_timeout_seconds: float = 60.0
    match_threshold: float = 0.363  # SFace cosine-similarity match threshold
    detection_score_threshold: float = 0.9  # YuNet detection confidence
    enroll_frame_count: int = 8

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            return cls()
        with CONFIG_PATH.open("r") as f:
            data = yaml.safe_load(f) or {}
        defaults = asdict(cls())
        defaults.update({k: v for k, v in data.items() if k in defaults})
        return cls(**defaults)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_PATH.open("w") as f:
            yaml.safe_dump(asdict(self), f, sort_keys=False)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
