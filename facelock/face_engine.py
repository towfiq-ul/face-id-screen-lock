"""Face detection + recognition using OpenCV's bundled YuNet + SFace ONNX models.

Chosen instead of dlib/face_recognition specifically to avoid a from-source
dlib build (no cmake/build toolchain assumed on the target machine) — this
only needs `pip install opencv-python numpy`.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import shutil
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from facelock import config as cfg

# Silence spurious OpenCV internal graph backend warnings
try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass

logger = logging.getLogger(__name__)


def _is_valid_model(path: Path, min_size_bytes: int = 10_000) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= min_size_bytes
    except OSError:
        return False


def _download(url: str, dest: Path, timeout: float = 60.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("Downloading %s -> %s", url, dest)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "facelock"})
        with urllib.request.urlopen(req, timeout=timeout) as response, tmp.open("wb") as out_file:
            shutil.copyfileobj(response, out_file)

        with tmp.open("rb") as f:
            head = f.read(64)
        if head.startswith(b"version https://git-lfs"):
            raise RuntimeError(f"Got a Git LFS pointer instead of model data from {url}")
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def ensure_models() -> None:
    if not _is_valid_model(cfg.YUNET_MODEL_PATH, min_size_bytes=100_000):
        _download(cfg.YUNET_MODEL_URL, cfg.YUNET_MODEL_PATH)
    if not _is_valid_model(cfg.SFACE_MODEL_PATH, min_size_bytes=1_000_000):
        _download(cfg.SFACE_MODEL_URL, cfg.SFACE_MODEL_PATH)


@dataclass
class MatchResult:
    matched: bool
    fused_score: float
    deep_score: float
    structure_score: float
    cranial_verified: bool


def extract_cranial_structure(landmarks: np.ndarray) -> np.ndarray:
    """Extract invariant cranial bone structural ratios and triangle angles.

    Unlike cheek soft-tissue which expands or hollows when a person gains/loses
    weight ('healthy vs skinny'), rigid orbital spacing, nasal bone projection,
    and relative facial triangle angles remain invariant for the same skull.

    Returns an 8-element float64 vector normalized to [0, 1].
    """
    pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    re, le, no, rm, lm = pts

    d_eyes = float(np.hypot(*(le - re)))
    if d_eyes < 1e-6:
        return np.zeros(8, dtype=np.float64)

    e_mid = (re + le) / 2.0
    m_mid = (rm + lm) / 2.0

    w_mouth = float(np.hypot(*(lm - rm)))
    h_face = float(np.hypot(*(m_mid - e_mid)))
    d_nose_emid = float(np.hypot(*(no - e_mid)))

    r_aspect = h_face / (d_eyes + 1e-6)
    r_mouth_eyes = w_mouth / (d_eyes + 1e-6)
    r_nose_vert = d_nose_emid / (h_face + 1e-6)

    b = float(np.hypot(*(le - no)))
    c = float(np.hypot(*(re - no)))
    a = d_eyes

    def safe_angle(s_opp: float, s1: float, s2: float) -> float:
        denom = 2.0 * s1 * s2
        if denom < 1e-6:
            return 0.333
        cos_val = np.clip((s1 * s1 + s2 * s2 - s_opp * s_opp) / denom, -1.0, 1.0)
        return float(np.arccos(cos_val) / np.pi)

    ang_re = safe_angle(b, a, c)
    ang_le = safe_angle(c, a, b)
    ang_no = safe_angle(a, b, c)

    d1 = float(np.hypot(*(rm - no)))
    d2 = float(np.hypot(*(lm - no)))
    ang_oral = safe_angle(w_mouth, d1, d2)

    r_sym = min(b, c) / max(b, c, 1e-6)

    return np.array(
        [
            r_aspect,
            r_mouth_eyes,
            r_nose_vert,
            ang_re,
            ang_le,
            ang_no,
            ang_oral,
            r_sym,
        ],
        dtype=np.float64,
    )


def cranial_structure_similarity(v1: np.ndarray, v2: np.ndarray) -> tuple[float, float]:
    """Compute invariant cranial structure similarity between two 8D feature vectors.

    Returns (similarity_score in [0, 1], weighted_euclidean_distance).
    Same skull (healthy/skinny variations) scores > 0.72; different skulls score < 0.35.
    """
    weights = np.array([1.5, 1.2, 1.5, 1.0, 1.0, 1.5, 1.0, 1.0], dtype=np.float64)
    v1_arr = np.asarray(v1, dtype=np.float64).reshape(-1)
    v2_arr = np.asarray(v2, dtype=np.float64).reshape(-1)
    if len(v1_arr) < 8 or len(v2_arr) < 8:
        return 0.0, 1.0

    diff = float(np.sqrt(np.sum(weights * (v1_arr[:8] - v2_arr[:8]) ** 2) / np.sum(weights)))
    sim = float(np.exp(-4.5 * diff))
    return sim, diff


def enhance_low_light(
    frame: np.ndarray, clip_limit: float = 3.0
) -> tuple[np.ndarray, bool, float]:
    """Enhance low-light underexposed video frames using CLAHE in LAB color space.

    Returns:
        (enhanced_frame, is_low_light, mean_luminance)
    """
    if frame is None or frame.size == 0:
        return frame, False, 0.0

    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame

    mean_lum = float(np.mean(gray))
    is_low_light = mean_lum < 55.0

    if not is_low_light:
        return frame, False, mean_lum

    if frame.ndim == 3:
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        enhanced = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)
    else:
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        enhanced = clahe.apply(frame)

    return enhanced, True, mean_lum


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

    def best_face(
        self, frame: np.ndarray, allow_low_light_boost: bool = True
    ) -> np.ndarray | None:
        """Return the highest-confidence detected face row (YuNet's 15-value format), or None.

        In low-light or underexposed environments, automatically attempts CLAHE contrast
        enhancement with an adaptive score threshold if standard detection yields no face.
        """
        self._set_input_size(frame)
        _, faces = self._detector.detect(frame)
        if faces is not None and len(faces) > 0:
            best_idx = int(np.argmax(faces[:, 14]))
            return faces[best_idx]

        if not allow_low_light_boost:
            return None

        # Low-light adaptive enhancement pass
        enhanced, is_low_light, _ = enhance_low_light(frame)
        if is_low_light:
            orig_thresh = self.config.detection_score_threshold
            adaptive_thresh = min(orig_thresh, 0.65)
            self._detector.setScoreThreshold(adaptive_thresh)
            try:
                _, faces = self._detector.detect(enhanced)
                if faces is not None and len(faces) > 0:
                    best_idx = int(np.argmax(faces[:, 14]))
                    return faces[best_idx]
            finally:
                self._detector.setScoreThreshold(orig_thresh)

        return None

    def embed(self, frame: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        # If frame is severely underexposed, use enhanced frame for cleaner feature alignment
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_lum = float(np.mean(gray))
        else:
            mean_lum = float(np.mean(frame))

        align_frame = frame
        if mean_lum < 35.0:
            enhanced, is_low, _ = enhance_low_light(frame)
            if is_low:
                align_frame = enhanced

        aligned = self._recognizer.alignCrop(align_frame, face_row)
        deep_feat = self._recognizer.feature(aligned).reshape(-1)
        if len(face_row) >= 14:
            cranial_feat = extract_cranial_structure(face_row[4:14])
            return np.concatenate([deep_feat, cranial_feat], dtype=np.float32)
        return deep_feat

    def match_detailed(
        self,
        embedding: np.ndarray,
        known_embeddings: np.ndarray,
        landmarks: np.ndarray | None = None,
    ) -> MatchResult:
        emb_flat = np.asarray(embedding, dtype=np.float32).reshape(-1)
        emb_deep = emb_flat[:128].reshape(1, -1)

        probe_struct: np.ndarray | None = None
        if len(emb_flat) >= 136:
            probe_struct = emb_flat[128:136]
        elif landmarks is not None:
            probe_struct = extract_cranial_structure(landmarks)

        best_fused_score = -1.0
        best_deep_score = -1.0
        best_struct_score = 0.0
        cranial_verified = False
        matched = False

        threshold = self.config.match_threshold

        for known in known_embeddings:
            k_flat = np.asarray(known, dtype=np.float32).reshape(-1)
            k_deep = k_flat[:128].reshape(1, -1)
            deep_score = float(
                self._recognizer.match(emb_deep, k_deep, cv2.FaceRecognizerSF_FR_COSINE)
            )

            struct_score = 0.0
            if (
                self.config.structural_match_enabled
                and probe_struct is not None
                and len(k_flat) >= 136
            ):
                struct_score, _ = cranial_structure_similarity(probe_struct, k_flat[128:136])

            is_cranial_match = struct_score >= 0.72
            is_this_matched = False

            if deep_score >= threshold:
                is_this_matched = True
            elif (
                self.config.structural_match_enabled
                and is_cranial_match
                and deep_score >= (threshold - 0.07)
            ):
                # Facial structure matches: provides resilience against weight changes (healthy/skinny)
                is_this_matched = True

            if struct_score > 0.0:
                fused = max(deep_score, 0.70 * deep_score + 0.30 * struct_score)
            else:
                fused = deep_score

            if fused > best_fused_score:
                best_fused_score = fused
                best_deep_score = deep_score
                best_struct_score = struct_score
                cranial_verified = is_cranial_match

            if is_this_matched:
                matched = True

        return MatchResult(
            matched=matched,
            fused_score=best_fused_score,
            deep_score=best_deep_score,
            structure_score=best_struct_score,
            cranial_verified=cranial_verified,
        )

    def matches_any(
        self,
        embedding: np.ndarray,
        known_embeddings: np.ndarray,
        landmarks: np.ndarray | None = None,
    ) -> tuple[bool, float]:
        """Compare `embedding` against every row in `known_embeddings`, return (is_match, best_score)."""
        res = self.match_detailed(embedding, known_embeddings, landmarks=landmarks)
        return res.matched, res.fused_score
