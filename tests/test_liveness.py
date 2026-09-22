import unittest
import cv2
import numpy as np

from facelock.liveness import (
    BlinkDetector,
    LivenessTracker,
    SmileDetector,
    analyze_facial_pose,
    calculate_eye_openness,
    check_3d_cranial_consistency,
    check_smile,
    check_teeth,
    check_texture_liveness,
    estimate_head_pose,
)


class TestLiveness(unittest.TestCase):
    def test_estimate_head_pose_valid(self):
        # 5 landmarks: right_eye, left_eye, nose, right_mouth, left_mouth
        landmarks = np.array(
            [
                [280.0, 200.0],
                [360.0, 200.0],
                [320.0, 240.0],
                [290.0, 280.0],
                [350.0, 280.0],
            ],
            dtype=np.float64,
        )
        pose = estimate_head_pose(landmarks, (480, 640))
        self.assertIsNotNone(pose)
        self.assertEqual(len(pose), 3)
        pitch, yaw, roll = pose
        self.assertIsInstance(pitch, float)
        self.assertIsInstance(yaw, float)
        self.assertIsInstance(roll, float)

    def test_estimate_head_pose_flattened_input(self):
        # 10 element 1D array
        landmarks_1d = np.array(
            [280.0, 200.0, 360.0, 200.0, 320.0, 240.0, 290.0, 280.0, 350.0, 280.0],
            dtype=np.float32,
        )
        pose = estimate_head_pose(landmarks_1d, (480, 640))
        self.assertIsNotNone(pose)

    def test_estimate_head_pose_degenerate(self):
        # All zeros / degenerate points
        landmarks = np.zeros((5, 2), dtype=np.float64)
        pose = estimate_head_pose(landmarks, (480, 640))
        # solvePnP may fail or produce degenerate result; should not raise unhandled exception
        if pose is not None:
            self.assertEqual(len(pose), 3)

    def test_liveness_tracker_lifecycle(self):
        tracker = LivenessTracker(window_size=4, min_pose_variance=0.3)

        # 1. Warm-up phase (< window_size) grants tentative pass
        tracker.add_pose(1.0, 2.0, 0.0)
        is_live, reason = tracker.evaluate()
        self.assertTrue(is_live)
        self.assertEqual(reason, "building_history")

        # 2. Static sequence (no micro-movement) -> spoof flagged
        tracker.add_pose(1.001, 2.001, 0.0)
        tracker.add_pose(1.000, 2.000, 0.0)
        tracker.add_pose(1.002, 2.001, 0.0)

        is_live, reason = tracker.evaluate()
        self.assertFalse(is_live)
        self.assertIn("static_pose_detected", reason)

        # 3. Dynamic sequence (natural human micro-drift) -> live pass
        tracker.add_pose(2.5, 3.2, 0.5)
        tracker.add_pose(3.8, 1.1, -0.2)
        is_live, reason = tracker.evaluate()
        self.assertTrue(is_live)
        self.assertIn("live_pose", reason)

        # 4. Reset
        tracker.reset()
        is_live, reason = tracker.evaluate()
        self.assertTrue(is_live)
        self.assertEqual(reason, "building_history")

    def test_check_texture_liveness_textured_vs_flat(self):
        # High-frequency noise texture
        noise_frame = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        box = np.array([20, 20, 80, 80], dtype=np.float32)
        is_live, score = check_texture_liveness(noise_frame, box, min_laplacian_var=20.0)
        self.assertTrue(is_live)
        self.assertGreater(score, 20.0)

        # Flat solid surface (e.g. blank paper)
        flat_frame = np.full((200, 200, 3), 128, dtype=np.uint8)
        is_live, score = check_texture_liveness(flat_frame, box, min_laplacian_var=20.0)
        self.assertFalse(is_live)
        self.assertEqual(score, 0.0)

    def test_check_texture_liveness_out_of_bounds(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        box = np.array([-50, -50, 20, 20], dtype=np.float32)
        is_live, score = check_texture_liveness(frame, box)
        self.assertFalse(is_live)
        self.assertEqual(score, 0.0)

    def test_check_texture_liveness_low_light_scaling(self):
        # Create a textured patch then scale down to low-light
        base_texture = np.random.randint(40, 200, (120, 120, 3), dtype=np.uint8)
        box = np.array([10, 10, 80, 80], dtype=np.float32)

        # Standard lighting
        is_live_std, score_std = check_texture_liveness(base_texture, box, min_laplacian_var=10.0)
        self.assertTrue(is_live_std)

        # Severe low light (dimmed to 20% luminance)
        dimmed = (base_texture.astype(np.float32) * 0.2).astype(np.uint8)
        is_live_dim, score_dim = check_texture_liveness(dimmed, box, min_laplacian_var=10.0)
        # Should not falsely reject as spoof because threshold adaptively scales with lighting
        self.assertTrue(is_live_dim)

        # Completely flat dark frame should still be rejected
        flat_dark = np.full((120, 120, 3), 15, dtype=np.uint8)
        is_live_flat, score_flat = check_texture_liveness(flat_dark, box, min_laplacian_var=10.0)
        self.assertFalse(is_live_flat)
        self.assertEqual(score_flat, 0.0)

    def test_analyze_facial_pose_center(self):
        # Eyes at (280, 200) and (360, 200) -> eye midpoint (320, 200), inter-eye dist 80
        # Mouth at (290, 280) and (350, 280) -> mouth mid y = 280, face_h = 80
        # Nose at (320, 240) -> h_offset = 0, v_ratio = (240 - 200)/80 = 0.5
        landmarks = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 240.0],
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        h_off, v_rat, direction = analyze_facial_pose(landmarks, mirrored=True)
        self.assertAlmostEqual(h_off, 0.0, places=2)
        self.assertAlmostEqual(v_rat, 0.5, places=2)
        self.assertEqual(direction, "CENTER")

    def test_analyze_facial_pose_right_and_left(self):
        # Nose shifted right on screen (mirrored: user turned right)
        landmarks_right = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [340.0, 240.0],  # nose x=340, mid=320 -> +20/80 = +0.25
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        _, _, dir_mirrored = analyze_facial_pose(landmarks_right, mirrored=True)
        self.assertEqual(dir_mirrored, "RIGHT")

        # In non-mirrored, h_offset > 0.12 corresponds to LEFT
        _, _, dir_unmirrored = analyze_facial_pose(landmarks_right, mirrored=False)
        self.assertEqual(dir_unmirrored, "LEFT")

        # Nose shifted left on screen
        landmarks_left = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [300.0, 240.0],  # nose x=300, mid=320 -> -20/80 = -0.25
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        _, _, dir_left_mirrored = analyze_facial_pose(landmarks_left, mirrored=True)
        self.assertEqual(dir_left_mirrored, "LEFT")

    def test_analyze_facial_pose_up_and_down(self):
        # Natural straight face with slight resting variation: nose at y=235 -> (235-200)/80 = 0.4375 -> CENTER
        landmarks_straight = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 235.0],
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        _, _, dir_straight = analyze_facial_pose(landmarks_straight, mirrored=True)
        self.assertEqual(dir_straight, "CENTER")

        # Chin tilt up: nose at y=225 -> (225-200)/80 = 0.3125 (< 0.38)
        landmarks_up = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 225.0],
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        _, _, dir_up = analyze_facial_pose(landmarks_up, mirrored=True)
        self.assertEqual(dir_up, "UP")

        # Nose shifted down towards mouth line (v_ratio > 0.60)
        landmarks_down = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 260.0],  # (260-200)/80 = 0.75
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        _, _, dir_down = analyze_facial_pose(landmarks_down, mirrored=True)
        self.assertEqual(dir_down, "DOWN")

    def test_analyze_facial_pose_with_3d_pose_fusion(self):
        # Neutral 2D landmarks (v_ratio = 0.5)
        landmarks_center = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 240.0],
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        # 3D pose indicates upward tilt (pitch = 7.5 deg)
        _, _, dir_up = analyze_facial_pose(landmarks_center, mirrored=True, pose=(7.5, 0.0, 0.0))
        self.assertEqual(dir_up, "UP")

        # 3D pose in natural straight gaze towards screen (-5.0 deg) -> remains CENTER
        _, _, dir_center = analyze_facial_pose(landmarks_center, mirrored=True, pose=(-5.0, 0.0, 0.0))
        self.assertEqual(dir_center, "CENTER")

        # 3D pose indicates intentional downward tilt (pitch = -12.0 deg)
        _, _, dir_down = analyze_facial_pose(landmarks_center, mirrored=True, pose=(-12.0, 0.0, 0.0))
        self.assertEqual(dir_down, "DOWN")

    def test_estimate_head_pose_mirrored(self):
        landmarks = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 240.0],
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        pose_norm = estimate_head_pose(landmarks, (480, 640), mirrored=False)
        # Flip landmarks horizontally: x -> 640 - x
        landmarks_mirr = landmarks.copy()
        landmarks_mirr[:, 0] = 640 - landmarks_mirr[:, 0]
        pose_mirr = estimate_head_pose(landmarks_mirr, (480, 640), mirrored=True)

        self.assertIsNotNone(pose_norm)
        self.assertIsNotNone(pose_mirr)
        # Pitch should match closely
        self.assertAlmostEqual(pose_norm[0], pose_mirr[0], delta=1.0)

    def test_calculate_eye_openness_open_vs_closed(self):
        landmarks = np.array([
            [70.0, 70.0],
            [130.0, 70.0],
            [100.0, 110.0],
            [80.0, 140.0],
            [120.0, 140.0],
        ])

        # Open eye frame: dark pupils, light sclera, distinct horizontal eyelid boundaries
        open_frame = np.full((200, 200, 3), 170, dtype=np.uint8)
        for ex, ey in [(70, 70), (130, 70)]:
            cv2.circle(open_frame, (ex, ey), 6, (20, 20, 20), -1)
            cv2.line(open_frame, (ex - 10, ey - 4), (ex + 10, ey - 4), (50, 50, 50), 2)
            cv2.line(open_frame, (ex - 10, ey + 4), (ex + 10, ey + 4), (50, 50, 50), 2)

        # Closed eye frame: smooth skin with faint single line
        closed_frame = np.full((200, 200, 3), 170, dtype=np.uint8)
        for ex, ey in [(70, 70), (130, 70)]:
            cv2.line(closed_frame, (ex - 8, ey), (ex + 8, ey), (150, 150, 150), 1)

        open_score = calculate_eye_openness(open_frame, landmarks)
        closed_score = calculate_eye_openness(closed_frame, landmarks)

        self.assertGreater(open_score, 50.0)
        self.assertLess(closed_score, 20.0)
        self.assertGreater(open_score, closed_score * 3.0)

    def test_calculate_eye_openness_degenerate(self):
        # Extremely close or zero distance landmarks
        landmarks_zero = np.zeros((5, 2), dtype=np.float64)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        score = calculate_eye_openness(frame, landmarks_zero)
        self.assertEqual(score, 0.0)

    def test_blink_detector_full_cycle(self):
        detector = BlinkDetector(min_blink_duration=0.05, max_blink_duration=0.80)
        landmarks = np.array([[70.0, 70.0], [130.0, 70.0], [100.0, 110.0], [80.0, 140.0], [120.0, 140.0]])

        open_frame = np.full((200, 200, 3), 170, dtype=np.uint8)
        for ex, ey in [(70, 70), (130, 70)]:
            cv2.circle(open_frame, (ex, ey), 6, (20, 20, 20), -1)
            cv2.line(open_frame, (ex - 10, ey - 4), (ex + 10, ey - 4), (50, 50, 50), 2)
            cv2.line(open_frame, (ex - 10, ey + 4), (ex + 10, ey + 4), (50, 50, 50), 2)

        closed_frame = np.full((200, 200, 3), 170, dtype=np.uint8)
        for ex, ey in [(70, 70), (130, 70)]:
            cv2.line(closed_frame, (ex - 8, ey), (ex + 8, ey), (150, 150, 150), 1)

        # 1. Feed open frames to establish baseline
        for t in [0.0, 0.1, 0.2]:
            state = detector.update(open_frame, landmarks, now=t)
            self.assertFalse(state.is_blinking)
            self.assertEqual(state.blink_count, 0)
        self.assertGreater(detector.baseline_openness, 50.0)

        # 2. Eye closure starts at t = 1.0 (frame 1: debounce)
        state = detector.update(closed_frame, landmarks, now=1.0)
        self.assertFalse(state.is_blinking)

        # Eye stays closed at t = 1.15 (frame 2: confirmed closed, duration 150ms)
        state = detector.update(closed_frame, landmarks, now=1.15)
        self.assertTrue(state.is_closed)
        self.assertFalse(state.is_blinking)

        # 3. Eye reopens at t = 1.25 (duration 250ms -> valid blink!)
        state = detector.update(open_frame, landmarks, now=1.25)
        self.assertFalse(state.is_closed)
        self.assertTrue(state.is_blinking)
        self.assertEqual(state.blink_count, 1)
        self.assertEqual(detector.last_blink_time, 1.25)

    def test_blink_detector_long_closure_not_counted(self):
        detector = BlinkDetector(min_blink_duration=0.05, max_blink_duration=0.80)
        landmarks = np.array([[70.0, 70.0], [130.0, 70.0], [100.0, 110.0], [80.0, 140.0], [120.0, 140.0]])

        open_frame = np.full((200, 200, 3), 170, dtype=np.uint8)
        for ex, ey in [(70, 70), (130, 70)]:
            cv2.circle(open_frame, (ex, ey), 6, (20, 20, 20), -1)

        closed_frame = np.full((200, 200, 3), 170, dtype=np.uint8)

        # Establish baseline
        detector.update(open_frame, landmarks, now=0.0)
        detector.update(open_frame, landmarks, now=0.1)

        # Close eyes at t = 1.0
        detector.update(closed_frame, landmarks, now=1.0)

        # Remains closed until t = 3.0 (2.0s duration > 0.80s max_blink_duration)
        detector.update(closed_frame, landmarks, now=3.0)

        # Reopen at t = 3.1
        state = detector.update(open_frame, landmarks, now=3.1)
        self.assertFalse(state.is_blinking)
        self.assertEqual(state.blink_count, 0)

    def test_liveness_tracker_with_blinks(self):
        tracker = LivenessTracker(window_size=3, min_pose_variance=0.3, blink_enabled=True)
        landmarks = np.array([[70.0, 70.0], [130.0, 70.0], [100.0, 110.0], [80.0, 140.0], [120.0, 140.0]])

        open_frame = np.full((200, 200, 3), 170, dtype=np.uint8)
        for ex, ey in [(70, 70), (130, 70)]:
            cv2.circle(open_frame, (ex, ey), 6, (20, 20, 20), -1)
            cv2.line(open_frame, (ex - 10, ey - 4), (ex + 10, ey - 4), (50, 50, 50), 2)
            cv2.line(open_frame, (ex - 10, ey + 4), (ex + 10, ey + 4), (50, 50, 50), 2)

        closed_frame = np.full((200, 200, 3), 170, dtype=np.uint8)
        for ex, ey in [(70, 70), (130, 70)]:
            cv2.line(closed_frame, (ex - 8, ey), (ex + 8, ey), (150, 150, 150), 1)

        # Add static pose history (variance ~ 0)
        tracker.add_pose(1.000, 2.000, 0.0)
        tracker.add_pose(1.001, 2.000, 0.0)
        tracker.add_pose(1.000, 2.001, 0.0)

        # Without blinks: static pose detected
        is_live, reason = tracker.evaluate(now=0.5)
        self.assertFalse(is_live)
        self.assertIn("static_pose_detected", reason)

        # Perform an eye blink cycle (2 closed frames for temporal debounce)
        tracker.update_eyes(open_frame, landmarks, now=0.0)
        tracker.update_eyes(closed_frame, landmarks, now=1.0)
        tracker.update_eyes(closed_frame, landmarks, now=1.1)
        tracker.update_eyes(open_frame, landmarks, now=1.2)

        # Now evaluate within 6s of the blink (e.g. t = 2.0)
        is_live, reason = tracker.evaluate(now=2.0)
        self.assertTrue(is_live)
        self.assertIn("live_human_blink_verified", reason)

        # After 7s (t = 8.5), blink has expired, falls back to static pose check
        is_live, reason = tracker.evaluate(now=8.5)
        self.assertFalse(is_live)
        self.assertIn("static_pose_detected", reason)

    def test_check_3d_cranial_consistency(self):
        landmarks = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 240.0],
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        is_valid, err = check_3d_cranial_consistency(landmarks, (480, 640))
        self.assertTrue(is_valid)
        self.assertLess(err, 4.0)

        # Mirrored mode test
        w = 640
        mirrored_lm = landmarks.copy()
        mirrored_lm[:, 0] = w - mirrored_lm[:, 0]
        is_valid_m, err_m = check_3d_cranial_consistency(mirrored_lm, (480, 640), mirrored=True)
        self.assertTrue(is_valid_m)
        self.assertLess(err_m, 4.0)

        # Degenerate/zeros and NaNs
        is_valid_zero, err_zero = check_3d_cranial_consistency(np.zeros((5, 2)), (480, 640))
        self.assertFalse(is_valid_zero)

        nan_lm = landmarks.copy()
        nan_lm[0, 0] = np.nan
        is_valid_nan, _ = check_3d_cranial_consistency(nan_lm, (480, 640))
        self.assertFalse(is_valid_nan)

    def test_check_smile_and_detector(self):
        neutral_lm = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 240.0],
            [290.0, 280.0],
            [350.0, 280.0],
        ])
        # Smile widens mouth corners outward
        smile_lm = np.array([
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 240.0],
            [275.0, 274.0],
            [365.0, 274.0],
        ])

        is_smile_n, ratio_n = check_smile(neutral_lm)
        is_smile_s, ratio_s = check_smile(smile_lm)

        self.assertFalse(is_smile_n)
        self.assertTrue(is_smile_s)
        self.assertGreater(ratio_s, ratio_n * 1.20)

        detector = SmileDetector(expansion_threshold=1.10)
        # 1. Establish baseline on neutral face
        s_flag, _ = detector.update(neutral_lm)
        self.assertFalse(s_flag)

        # 2. Smile face
        s_flag, _ = detector.update(smile_lm)
        self.assertTrue(s_flag)

    def test_check_teeth_and_little_smile(self):
        # Create a blank 400x500 image with a face
        frame = np.full((400, 500, 3), [120, 140, 200], dtype=np.uint8)  # skin tone
        landmarks = np.array([
            [200.0, 150.0],  # right eye
            [280.0, 150.0],  # left eye
            [240.0, 190.0],  # nose
            [210.0, 230.0],  # right mouth corner
            [270.0, 230.0],  # left mouth corner
        ])

        # Without teeth (reddish closed lips in mouth area)
        frame[225:235, 220:260] = [80, 90, 180]  # reddish lips
        has_teeth_closed, _, _ = check_teeth(frame, landmarks)
        self.assertFalse(has_teeth_closed)

        # With teeth: draw small white/ivory teeth patch between lips
        frame_teeth = frame.copy()
        frame_teeth[227:233, 230:250] = [190, 200, 210]  # ivory enamel
        has_teeth_open, count, ratio = check_teeth(frame_teeth, landmarks)
        self.assertTrue(has_teeth_open)
        self.assertGreater(count, 5)
        self.assertGreater(ratio, 0.02)

        # check_smile with frame showing teeth confirms smile even on slight ratio
        is_smile_with_teeth, r = check_smile(landmarks, frame=frame_teeth)
        self.assertTrue(is_smile_with_teeth)

        # SmileDetector with frame detects little smile with teeth
        detector = SmileDetector()
        detector.record_baseline(landmarks)
        s_flag, _ = detector.update(landmarks, frame=frame_teeth)
        self.assertTrue(s_flag)
        self.assertTrue(detector.teeth_detected)

    def test_little_smile_expansion_and_reset(self):
        # Baseline neutral face
        neutral_lm = np.array([
            [200.0, 150.0],
            [280.0, 150.0],
            [240.0, 190.0],
            [210.0, 230.0],
            [270.0, 230.0],  # mouth_w = 60, ratio = 60/80 = 0.75
        ])
        # Subtle 5.5% expansion (little smile: mouth_w = 63.5, ratio = ~0.794)
        subtle_smile_lm = np.array([
            [200.0, 150.0],
            [280.0, 150.0],
            [240.0, 190.0],
            [208.2, 229.0],
            [271.8, 229.0],
        ])

        detector = SmileDetector(expansion_threshold=1.05)
        detector.record_baseline(neutral_lm)
        s_flag, _ = detector.update(subtle_smile_lm)
        self.assertTrue(s_flag)

        detector.reset()
        self.assertEqual(detector.baseline_ratio, 0.0)
        self.assertFalse(detector.is_smiling)
        self.assertFalse(detector.teeth_detected)


if __name__ == "__main__":
    unittest.main()
