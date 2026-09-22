"""Config and on-disk paths for the facelock monitor.

All state lives under the user's own home directory (XDG dirs).
FaceLock operates self-contained with its own native PAM biometric unlock
and auto-lock monitor daemon.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))

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
    enroll_frame_count: int = 7
    liveness_enabled: bool = True
    liveness_min_pose_variance: float = 0.2  # Std dev in degrees across window
    liveness_window_size: int = 5  # Sliding window size for micro-movement check
    texture_anti_spoof_enabled: bool = True
    blink_detection_enabled: bool = True
    structural_match_enabled: bool = True
    cranial_liveness_enabled: bool = True
    neutral_v_ratio: float = 0.52
    neutral_h_offset: float = 0.0
    blink_close_ratio: float = 0.62
    blink_min_duration: float = 0.12
    blink_min_frames: int = 2
    min_laplacian_var: float = 8.0
    ir_camera_index: int | None = None

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            return cls()
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        defaults = asdict(cls())
        defaults.update({k: v for k, v in data.items() if k in defaults})
        return cls(**defaults)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            CONFIG_DIR.chmod(0o700)
        except OSError:
            pass
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            yaml.safe_dump(asdict(self), f, sort_keys=False)
        try:
            CONFIG_PATH.chmod(0o600)
        except OSError:
            pass


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except OSError:
        pass
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
