"""Liveness and anti-spoofing detection for facelock.

Defends against static photo attacks and screen replay attacks by analyzing:
1. 3D head pose estimation & temporal micro-movement variance via solvePnP.
2. Texture & sharpness characteristics (Laplacian variance, edge analysis).
"""

from __future__ import annotations

import collections
import logging
import time
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Standard 3D facial model for YuNet's 5 facial landmarks:
# Right eye, Left eye, Nose tip, Right mouth corner, Left mouth corner
CANONICAL_FACE_3D = np.array(
    [
        [-38.0, -40.0, -20.0],  # Right eye (subject's right)
        [38.0, -40.0, -20.0],   # Left eye
        [0.0, 0.0, 30.0],       # Nose tip
        [-30.0, 35.0, -10.0],   # Right mouth corner
        [30.0, 35.0, -10.0],    # Left mouth corner
    ],
    dtype=np.float64,
)

# Synthesize mid-eye and mid-mouth points to bring total points to 7,
# ensuring full compatibility with cv2.SOLVEPNP_ITERATIVE across OpenCV versions.
_EYE_MID_3D = (CANONICAL_FACE_3D[0] + CANONICAL_FACE_3D[1]) / 2.0
_MOUTH_MID_3D = (CANONICAL_FACE_3D[3] + CANONICAL_FACE_3D[4]) / 2.0
CANONICAL_FACE_7_3D = np.vstack([CANONICAL_FACE_3D, _EYE_MID_3D, _MOUTH_MID_3D])


def estimate_head_pose(
    landmarks: np.ndarray,
    frame_shape: tuple[int, int],
    mirrored: bool = False,
) -> tuple[float, float, float] | None:
    """Estimate head pose (pitch, yaw, roll in degrees) from 5 YuNet landmarks.

    landmarks: array-like of 5 points [[x, y], ...] or 10-element array [x0, y0, ...].
    frame_shape: (height, width) of the video frame.
    mirrored: True if the input frame/landmarks are horizontally flipped (e.g. GUI selfie view).
    """
    pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    h, w = frame_shape[:2]

    if mirrored:
        pts = pts.copy()
        pts[:, 0] = w - pts[:, 0]
        # In canonical 3D model, right eye (0) has X < 0 and left eye (1) has X > 0.
        # If un-mirroring inverts X order (pts[0].x > pts[1].x), swap left and right eyes and mouth corners.
        if pts[0, 0] > pts[1, 0]:
            pts[[0, 1]] = pts[[1, 0]]
            pts[[3, 4]] = pts[[4, 3]]

    # Synthesize mid-eye and mid-mouth 2D points to match 7-point 3D model
    eye_mid_2d = (pts[0] + pts[1]) / 2.0
    mouth_mid_2d = (pts[3] + pts[4]) / 2.0
    pts_7 = np.vstack([pts, eye_mid_2d, mouth_mid_2d])

    focal_length = float(w)
    center = (w / 2.0, h / 2.0)
    camera_matrix = np.array(
        [[focal_length, 0.0, center[0]], [0.0, focal_length, center[1]], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    try:
        ok, rvec, _ = cv2.solvePnP(
            CANONICAL_FACE_7_3D,
            pts_7,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_SQPNP,
        )
        if not ok or rvec is None:
            ok, rvec, _ = cv2.solvePnP(
                CANONICAL_FACE_7_3D,
                pts_7,
                camera_matrix,
                dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )
        if not ok or rvec is None:
            return None

        rmat, _ = cv2.Rodrigues(rvec)
        sy = np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        singular = sy < 1e-6
        if not singular:
            pitch = np.arctan2(rmat[2, 1], rmat[2, 2])
            yaw = np.arctan2(-rmat[2, 0], sy)
            roll = np.arctan2(rmat[1, 0], rmat[0, 0])
        else:
            pitch = np.arctan2(-rmat[1, 2], rmat[1, 1])
            yaw = np.arctan2(-rmat[2, 0], sy)
            roll = 0.0

        return float(np.degrees(pitch)), float(np.degrees(yaw)), float(np.degrees(roll))
    except (cv2.error, ValueError):
        return None


def check_3d_cranial_consistency(
    landmarks: np.ndarray,
    frame_shape: tuple[int, int],
    max_reproj_err: float = 6.5,
    mirrored: bool = False,
) -> tuple[bool, float]:
    """Verify that observed facial landmarks conform to a real 3D cranial structure.

    Computes reprojection error against the canonical 3D skull model via SQPNP.
    Genuine human heads conform closely (< 4.5px error); heavily warped or non-rigid
    distortions have high reprojection errors.
    """
    pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    if np.any(np.isnan(pts)) or np.any(np.isinf(pts)):
        return False, 999.0

    d_eyes = float(np.hypot(*(pts[1] - pts[0])))
    if d_eyes < 8.0:
        return False, 999.0

    h, w = frame_shape[:2]

    if mirrored:
        pts = pts.copy()
        pts[:, 0] = w - pts[:, 0]
        if pts[0, 0] > pts[1, 0]:
            pts[[0, 1]] = pts[[1, 0]]
            pts[[3, 4]] = pts[[4, 3]]
    elif pts[0, 0] > pts[1, 0]:
        # Unflipped camera view where eye coordinates are reversed
        pts = pts.copy()
        pts[[0, 1]] = pts[[1, 0]]
        pts[[3, 4]] = pts[[4, 3]]

    eye_mid = (pts[0] + pts[1]) / 2.0
    mouth_mid = (pts[3] + pts[4]) / 2.0
    pts_7 = np.vstack([pts, eye_mid, mouth_mid])

    focal_length = float(w)
    center = (w / 2.0, h / 2.0)
    camera_matrix = np.array(
        [[focal_length, 0.0, center[0]], [0.0, focal_length, center[1]], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    try:
        ok, rvec, tvec = cv2.solvePnP(
            CANONICAL_FACE_7_3D,
            pts_7,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_SQPNP,
        )
        if not ok or rvec is None or tvec is None:
            ok, rvec, tvec = cv2.solvePnP(
                CANONICAL_FACE_7_3D,
                pts_7,
                camera_matrix,
                dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE,
            )
        if not ok or rvec is None or tvec is None:
            return False, 999.0

        proj_pts, _ = cv2.projectPoints(
            CANONICAL_FACE_7_3D, rvec, tvec, camera_matrix, dist_coeffs
        )
        proj_pts = proj_pts.reshape(-1, 2)
        err = float(np.mean(np.linalg.norm(pts_7 - proj_pts, axis=1)))
        return err <= max_reproj_err, err
    except (cv2.error, ValueError):
        return False, 999.0


def analyze_facial_pose(
    landmarks: np.ndarray,
    mirrored: bool = False,
    pose: tuple[float, float, float] | None = None,
    neutral_v_ratio: float = 0.52,
    neutral_h_offset: float = 0.0,
) -> tuple[float, float, str]:
    """Calculate canonical roll-compensated horizontal and vertical offsets and classify head pose.

    Aligns the 5 landmarks to the eye-line horizontal axis to eliminate head-roll distortion.
    """
    pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    r_eye, l_eye, nose, r_mouth, l_mouth = pts

    dx = float(l_eye[0] - r_eye[0])
    dy = float(l_eye[1] - r_eye[1])
    roll = float(np.arctan2(dy, dx))

    eye_mid = (r_eye + l_eye) / 2.0
    cos_a, sin_a = np.cos(-roll), np.sin(-roll)

    # Canonical rotation of all 5 landmarks into upright facial space
    diff = pts - eye_mid
    rx = diff[:, 0] * cos_a - diff[:, 1] * sin_a
    ry = diff[:, 0] * sin_a + diff[:, 1] * cos_a

    eye_dist = abs(float(rx[1] - rx[0]))
    h_offset = float(rx[2] / (eye_dist + 1e-6))

    mouth_mid_y = (ry[3] + ry[4]) / 2.0
    face_h = mouth_mid_y
    v_ratio = float(ry[2] / (face_h + 1e-6))

    # Compute delta relative to neutral resting gaze
    delta_h = h_offset - neutral_h_offset
    delta_v = v_ratio - neutral_v_ratio

    # In mirrored mode (webcam selfie view): user turning their head right shifts nose right on screen
    if mirrored:
        is_right = delta_h > 0.14
        is_left = delta_h < -0.14
    else:
        is_right = delta_h < -0.14
        is_left = delta_h > 0.14

    # Vertical direction classification:
    # Upward chin tilt brings nose closer to eye line (delta_v < -0.12 or pitch > 7.0)
    # Downward tilt brings nose closer to mouth (delta_v > +0.13 or pitch < -9.5)
    is_up = delta_v < -0.12
    is_down = delta_v > 0.13

    if pose is not None:
        pitch = pose[0]
        # Only fuse pitch if roll is relatively small (|roll| < 20 deg) to avoid Euler gimbal cross-talk
        # and pitch is within realistic human head range (-45 to +45 deg) to reject Euler wrapping artifacts.
        if abs(np.degrees(roll)) < 20.0 and -45.0 <= pitch <= 45.0:
            if pitch >= 7.0:
                is_up = True
                is_down = False
            elif pitch <= -9.5:
                is_down = True
                is_up = False

    if is_up and is_right:
        direction = "UP_RIGHT"
    elif is_up and is_left:
        direction = "UP_LEFT"
    elif is_down and is_right:
        direction = "DOWN_RIGHT"
    elif is_down and is_left:
        direction = "DOWN_LEFT"
    elif is_right:
        direction = "RIGHT"
    elif is_left:
        direction = "LEFT"
    elif is_up:
        direction = "UP"
    elif is_down:
        direction = "DOWN"
    else:
        direction = "CENTER"

    return h_offset, v_ratio, direction


def check_texture_liveness(
    frame: np.ndarray, face_box: np.ndarray, min_laplacian_var: float = 8.0
) -> tuple[bool, float]:
    """Check image texture clarity and blurriness in the face region.

    Returns (is_live, score) where score is the Laplacian variance.
    Severely blurred or untextured images often indicate poor quality paper prints.
    In low lighting, the threshold is adaptively scaled to prevent false spoof
    rejections caused by camera sensor noise floors.
    """
    try:
        box_coords = [float(v) for v in face_box[:4]]
        if any(np.isnan(v) or np.isinf(v) for v in box_coords):
            return False, 0.0
        x, y, w, h = [int(v) for v in box_coords]
    except (ValueError, TypeError):
        return False, 0.0

    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return False, 0.0

    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return False, 0.0

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Low light adaptation: Laplacian variance scales quadratically with contrast
    mean_lum = float(np.mean(gray))
    if mean_lum < 50.0:
        lum_ratio = max(0.1, mean_lum / 50.0)
        effective_min = min_laplacian_var * max(0.18, min(1.0, lum_ratio ** 2))
    else:
        effective_min = min_laplacian_var

    return score >= effective_min, score


@dataclass
class BlinkState:
    is_blinking: bool = False
    blink_count: int = 0
    eye_openness: float = 0.0
    baseline_openness: float = 0.0
    is_closed: bool = False
    last_blink_time: float = 0.0


def calculate_eye_openness(frame: np.ndarray, landmarks: np.ndarray) -> float:
    """Calculate average photometric eye openness score for both eyes.

    Open eyes have dark pupils/irises bounded by eyelids producing strong
    vertical gradients and high standard deviation. Closed eyelids produce
    uniform skin texture with minimal gradients.
    """
    pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    if np.any(np.isnan(pts)) or np.any(np.isinf(pts)):
        return 0.0

    r_eye, l_eye = pts[0], pts[1]
    dx = float(l_eye[0] - r_eye[0])
    dy = float(l_eye[1] - r_eye[1])
    dist = float(np.hypot(dx, dy))
    if dist < 8.0:
        return 0.0

    fh, fw = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame

    crop_w = max(8, int(dist * 0.40))
    crop_h = max(8, int(dist * 0.28))

    scores: list[float] = []
    for cx, cy in (r_eye, l_eye):
        x1 = max(0, int(round(cx - crop_w / 2.0)))
        y1 = max(0, int(round(cy - crop_h / 2.0)))
        x2 = min(fw, x1 + crop_w)
        y2 = min(fh, y1 + crop_h)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        crop = gray[y1:y2, x1:x2]
        crop_std = cv2.resize(crop, (28, 28), interpolation=cv2.INTER_AREA)
        crop_blur = cv2.GaussianBlur(crop_std, (3, 3), 0)
        gy = cv2.Sobel(crop_blur, cv2.CV_64F, 0, 1, ksize=3)
        g_val = float(np.mean(np.abs(gy)))
        s_val = float(np.std(crop_blur))
        scores.append(0.6 * g_val + 0.4 * s_val)

    return float(np.mean(scores)) if scores else 0.0


class BlinkDetector:
    """Detects deliberate human eye blinks using multi-frame filtered eye openness."""

    def __init__(
        self,
        close_threshold_ratio: float = 0.62,
        reopen_threshold_ratio: float = 0.82,
        min_blink_duration: float = 0.09,
        max_blink_duration: float = 0.65,
        min_closed_frames: int = 2,
    ):
        self.close_threshold_ratio = close_threshold_ratio
        self.reopen_threshold_ratio = reopen_threshold_ratio
        self.min_blink_duration = min_blink_duration
        self.max_blink_duration = max_blink_duration
        self.min_closed_frames = min_closed_frames

        self.blink_count: int = 0
        self.last_blink_time: float = 0.0
        self.baseline_openness: float = 0.0
        self._is_closed: bool = False
        self._closed_start_time: float = 0.0
        self._consecutive_closed_frames: int = 0
        self._recent_blink_until: float = 0.0
        self._openness_history: collections.deque[float] = collections.deque(maxlen=3)

    def reset(self) -> None:
        self.blink_count = 0
        self.last_blink_time = 0.0
        self.baseline_openness = 0.0
        self._is_closed = False
        self._closed_start_time = 0.0
        self._consecutive_closed_frames = 0
        self._recent_blink_until = 0.0
        self._openness_history.clear()

    def update(
        self,
        frame: np.ndarray,
        landmarks: np.ndarray,
        now: float | None = None,
    ) -> BlinkState:
        if now is None:
            now = time.monotonic()

        raw_openness = calculate_eye_openness(frame, landmarks)
        if raw_openness <= 0.0:
            return BlinkState(
                is_blinking=(now < self._recent_blink_until),
                blink_count=self.blink_count,
                eye_openness=0.0,
                baseline_openness=self.baseline_openness,
                is_closed=self._is_closed,
                last_blink_time=self.last_blink_time,
            )

        openness = raw_openness

        # Baseline initialization and smooth tracking
        if self.baseline_openness <= 0.0:
            self.baseline_openness = openness
        elif not self._is_closed:
            if openness > self.baseline_openness:
                self.baseline_openness = 0.90 * self.baseline_openness + 0.10 * openness
            elif openness >= self.baseline_openness * self.reopen_threshold_ratio:
                self.baseline_openness = 0.97 * self.baseline_openness + 0.03 * openness

        close_th = self.baseline_openness * self.close_threshold_ratio
        reopen_th = self.baseline_openness * self.reopen_threshold_ratio

        if not self._is_closed:
            if openness < close_th and self.baseline_openness > 3.5:
                if self._consecutive_closed_frames == 0:
                    self._closed_start_time = now
                self._consecutive_closed_frames += 1
                if self._consecutive_closed_frames >= self.min_closed_frames:
                    self._is_closed = True
            else:
                self._consecutive_closed_frames = 0
        else:
            duration = now - self._closed_start_time
            if openness >= reopen_th:
                if self.min_blink_duration <= duration <= self.max_blink_duration:
                    self.blink_count += 1
                    self.last_blink_time = now
                    self._recent_blink_until = now + 0.60
                self._is_closed = False
                self._consecutive_closed_frames = 0
            elif duration > self.max_blink_duration:
                # Kept eyes closed longer than normal blink
                self._is_closed = False
                self._consecutive_closed_frames = 0

        is_blinking = now < self._recent_blink_until
        return BlinkState(
            is_blinking=is_blinking,
            blink_count=self.blink_count,
            eye_openness=openness,
            baseline_openness=self.baseline_openness,
            is_closed=self._is_closed,
            last_blink_time=self.last_blink_time,
        )


def check_teeth(
    frame: np.ndarray,
    landmarks: np.ndarray,
    min_pixels: int = 6,
    min_ratio: float = 0.025,
) -> tuple[bool, int, float]:
    """Detect presence of visible teeth between upper and lower lips.

    Crops the central inter-labial region between the mouth corners.
    Teeth enamel presents with low color saturation (white/ivory) and elevated
    luminance compared to reddish/pink lip tissue and dark shadows.
    """
    if frame is None or frame.size == 0:
        return False, 0, 0.0

    pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    m_right, m_left = pts[3], pts[4]
    mouth_w = float(np.hypot(*(m_left - m_right)))
    if mouth_w < 10.0:
        return False, 0, 0.0

    cx = float((m_right[0] + m_left[0]) / 2.0)
    cy = float((m_right[1] + m_left[1]) / 2.0)

    # Focus on central 55% horizontal and 35% vertical span between mouth corners
    w = max(10, int(0.55 * mouth_w))
    h = max(6, int(0.35 * mouth_w))
    fh, fw = frame.shape[:2]

    x1 = max(0, int(round(cx - w / 2.0)))
    y1 = max(0, int(round(cy - h / 2.0)))
    x2 = min(fw, x1 + w)
    y2 = min(fh, y1 + h)

    if x2 - x1 < 6 or y2 - y1 < 4:
        return False, 0, 0.0

    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    b = crop[:, :, 0].astype(np.float32)
    g = crop[:, :, 1].astype(np.float32)
    r = crop[:, :, 2].astype(np.float32)

    # Teeth: low color saturation (white/ivory), moderate-to-high brightness, balanced RGB
    teeth_mask = (s <= 75) & (v >= 95) & (np.abs(r - b) < 35) & (np.abs(r - g) < 25)
    pixel_count = int(np.sum(teeth_mask))
    total_pixels = crop.shape[0] * crop.shape[1]
    ratio = float(pixel_count / total_pixels) if total_pixels > 0 else 0.0

    is_teeth = (pixel_count >= min_pixels) and (ratio >= min_ratio)
    return is_teeth, pixel_count, ratio


def check_smile(
    landmarks: np.ndarray,
    min_ratio: float = 0.88,
    frame: np.ndarray | None = None,
) -> tuple[bool, float]:
    """Calculate mouth-to-eye width ratio and teeth exposure to detect smiling.

    When smiling, the zygomaticus major muscle contracts, significantly widening
    the mouth relative to inter-ocular distance. A little smile with teeth will also
    expose white enamel pixels between the lips.
    """
    pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
    eye_dist = float(np.hypot(*(pts[1] - pts[0])))
    if eye_dist < 8.0:
        return False, 0.0
    mouth_w = float(np.hypot(*(pts[4] - pts[3])))
    ratio = float(mouth_w / eye_dist)

    if frame is not None:
        has_teeth, _, _ = check_teeth(frame, landmarks)
        if has_teeth and ratio >= 0.74:
            return True, ratio

    return ratio >= min_ratio, ratio


class SmileDetector:
    """Detects deliberate human smiles using dynamic mouth width expansion and teeth detection."""

    def __init__(
        self,
        expansion_threshold: float = 1.05,
        min_absolute_ratio: float = 0.85,
    ):
        self.expansion_threshold = expansion_threshold
        self.min_absolute_ratio = min_absolute_ratio
        self.baseline_ratio: float = 0.0
        self.is_smiling: bool = False
        self.teeth_detected: bool = False

    def reset(self) -> None:
        self.baseline_ratio = 0.0
        self.is_smiling = False
        self.teeth_detected = False

    def record_baseline(self, landmarks: np.ndarray) -> None:
        """Record neutral resting mouth ratio during neutral face holds."""
        pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
        eye_dist = float(np.hypot(*(pts[1] - pts[0])))
        if eye_dist < 8.0:
            return
        mouth_w = float(np.hypot(*(pts[4] - pts[3])))
        ratio = float(mouth_w / eye_dist)
        if self.baseline_ratio <= 0.0:
            self.baseline_ratio = ratio
        else:
            self.baseline_ratio = 0.90 * self.baseline_ratio + 0.10 * ratio

    def update(
        self,
        landmarks: np.ndarray,
        frame: np.ndarray | None = None,
    ) -> tuple[bool, float]:
        pts = np.asarray(landmarks, dtype=np.float64).reshape(5, 2)
        eye_dist = float(np.hypot(*(pts[1] - pts[0])))
        if eye_dist < 8.0:
            return False, 0.0
        mouth_w = float(np.hypot(*(pts[4] - pts[3])))
        ratio = float(mouth_w / eye_dist)

        if self.baseline_ratio <= 0.0:
            self.baseline_ratio = ratio
        elif not self.is_smiling:
            # Smoothly adapt resting baseline only on very minor resting drift (<3%)
            if ratio < self.baseline_ratio * 1.03:
                self.baseline_ratio = 0.95 * self.baseline_ratio + 0.05 * ratio

        # Check for visible teeth if video frame is provided
        self.teeth_detected = False
        if frame is not None:
            has_teeth, _, _ = check_teeth(frame, landmarks)
            self.teeth_detected = has_teeth

        # Smile Detection Logic:
        # 1. Little smile with visible teeth:
        #    Even a subtle mouth opening with teeth exposure confirms a smile!
        if self.teeth_detected and ratio >= max(0.68, self.baseline_ratio * 0.98):
            is_smile = True
        # 2. Dynamic horizontal expansion (e.g. >= 5% widening over neutral baseline):
        elif ratio >= self.baseline_ratio * self.expansion_threshold:
            is_smile = True
        # 3. Absolute threshold for clear smiles:
        elif ratio >= self.min_absolute_ratio:
            is_smile = True
        else:
            is_smile = False

        self.is_smiling = is_smile
        return is_smile, ratio


@dataclass
class PoseRecord:
    pitch: float
    yaw: float
    roll: float


class LivenessTracker:
    """Tracks head pose and eye blinks to detect human liveness.

    A living human displays small head oscillations and eye blinks.
    An inanimate 2D photo remains completely motionless without natural blinks.
    """

    def __init__(
        self,
        window_size: int = 5,
        min_pose_variance: float = 0.2,
        blink_enabled: bool = True,
        blink_close_ratio: float = 0.62,
        blink_min_duration: float = 0.08,
        blink_min_frames: int = 2,
    ):
        self.window_size = window_size
        self.min_pose_variance = min_pose_variance
        self.blink_enabled = blink_enabled
        self.blink_detector = BlinkDetector(
            close_threshold_ratio=blink_close_ratio,
            min_blink_duration=blink_min_duration,
            min_closed_frames=blink_min_frames,
        )
        self._history: collections.deque[PoseRecord] = collections.deque(maxlen=window_size)
        self._consecutive_static_ticks = 0

    def reset(self) -> None:
        self._history.clear()
        self._consecutive_static_ticks = 0
        self.blink_detector.reset()

    def add_pose(self, pitch: float, yaw: float, roll: float) -> None:
        self._history.append(PoseRecord(pitch, yaw, roll))

    def update_eyes(
        self,
        frame: np.ndarray,
        landmarks: np.ndarray,
        now: float | None = None,
    ) -> BlinkState:
        return self.blink_detector.update(frame, landmarks, now=now)

    def evaluate(self, now: float | None = None) -> tuple[bool, str]:
        """Evaluate whether recent observations reflect a live human face.

        Returns: (is_live, reason)
        """
        if now is None:
            now = time.monotonic()

        # If a blink occurred in the last 6.0 seconds, conclusively verify live human
        if self.blink_enabled and self.blink_detector.last_blink_time > 0.0:
            if (now - self.blink_detector.last_blink_time) < 6.0:
                return True, f"live_human_blink_verified (blinks={self.blink_detector.blink_count})"

        # Until we have enough samples, grant benefit of the doubt
        if len(self._history) < self.window_size:
            return True, "building_history"

        pitches = [p.pitch for p in self._history]
        yaws = [p.yaw for p in self._history]
        rolls = [p.roll for p in self._history]

        var_pitch = float(np.std(pitches))
        var_yaw = float(np.std(yaws))
        var_roll = float(np.std(rolls))
        total_var = var_pitch + var_yaw + var_roll

        if total_var < self.min_pose_variance:
            self._consecutive_static_ticks += 1
            return False, f"static_pose_detected (variance={total_var:.4f} < {self.min_pose_variance})"

        self._consecutive_static_ticks = 0
        return True, f"live_pose (variance={total_var:.4f})"
