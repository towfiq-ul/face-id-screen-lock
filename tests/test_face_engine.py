import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from facelock.config import Config
from facelock.face_engine import (
    FaceEngine,
    _is_valid_model,
    cranial_structure_similarity,
    enhance_low_light,
    extract_cranial_structure,
    score_to_match_percentage,
)


class TestFaceEngine(unittest.TestCase):
    def test_is_valid_model(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "test_model.onnx"
            self.assertFalse(_is_valid_model(file_path))

            # 0 bytes file
            file_path.touch()
            self.assertFalse(_is_valid_model(file_path, min_size_bytes=100))

            # write enough bytes
            file_path.write_bytes(b"x" * 200)
            self.assertTrue(_is_valid_model(file_path, min_size_bytes=100))

    @patch("cv2.FaceRecognizerSF.create")
    @patch("cv2.FaceDetectorYN.create")
    @patch("facelock.face_engine.ensure_models")
    def test_matches_any_above_threshold(self, mock_ensure, mock_det, mock_rec):
        mock_recognizer = MagicMock()
        mock_rec.return_value = mock_recognizer
        # Return cosine match score of 0.8
        mock_recognizer.match.return_value = 0.8

        cfg = Config(match_threshold=0.363, min_match_percent=92.0)
        engine = FaceEngine(cfg)

        emb = np.zeros((1, 128), dtype=np.float32)
        known = np.zeros((3, 128), dtype=np.float32)

        matched, match_pct = engine.matches_any(emb, known)
        self.assertTrue(matched)
        self.assertGreaterEqual(match_pct, 92.0)

    @patch("cv2.FaceRecognizerSF.create")
    @patch("cv2.FaceDetectorYN.create")
    @patch("facelock.face_engine.ensure_models")
    def test_matches_any_below_threshold(self, mock_ensure, mock_det, mock_rec):
        mock_recognizer = MagicMock()
        mock_rec.return_value = mock_recognizer
        mock_recognizer.match.return_value = 0.2

        cfg = Config(match_threshold=0.363, min_match_percent=92.0)
        engine = FaceEngine(cfg)

        emb = np.zeros((1, 128), dtype=np.float32)
        known = np.zeros((3, 128), dtype=np.float32)

        matched, match_pct = engine.matches_any(emb, known)
        self.assertFalse(matched)
        self.assertLess(match_pct, 92.0)

    def test_cranial_structure_healthy_vs_skinny_invariance(self):
        # Base face
        face_normal = np.array([[280.0, 200.0], [360.0, 200.0], [320.0, 240.0], [290.0, 280.0], [350.0, 280.0]])
        # Same skull but skinny face (slight landmark jitter due to leaner cheeks / shadows)
        face_skinny = np.array([[281.0, 200.5], [359.2, 199.5], [320.3, 240.8], [290.5, 279.6], [349.5, 280.2]])
        # Different person: narrow eye distance, elongated nose
        face_other = np.array([[295.0, 200.0], [345.0, 200.0], [320.0, 255.0], [290.0, 290.0], [350.0, 290.0]])

        v_norm = extract_cranial_structure(face_normal)
        v_skinny = extract_cranial_structure(face_skinny)
        v_other = extract_cranial_structure(face_other)

        self.assertEqual(len(v_norm), 8)
        self.assertEqual(len(v_skinny), 8)

        sim_same, d_same = cranial_structure_similarity(v_norm, v_skinny)
        sim_other, d_other = cranial_structure_similarity(v_norm, v_other)

        # Same individual (healthy vs skinny) retains cranial invariance (>0.85 similarity)
        self.assertGreater(sim_same, 0.85)
        # Different individual has distinctly different bone structure (<0.35 similarity)
        self.assertLess(sim_other, 0.35)
        self.assertGreater(sim_same, sim_other * 2.0)

    @patch("cv2.FaceRecognizerSF.create")
    @patch("cv2.FaceDetectorYN.create")
    @patch("facelock.face_engine.ensure_models")
    def test_match_detailed_with_cranial_structure_boost(self, mock_ensure, mock_det, mock_rec):
        mock_recognizer = MagicMock()
        mock_rec.return_value = mock_recognizer
        # Deep score is 0.33 (slightly below threshold 0.363 due to facial weight loss)
        mock_recognizer.match.return_value = 0.33

        cfg = Config(match_threshold=0.363, structural_match_enabled=True)
        engine = FaceEngine(cfg)

        face_normal = np.array([[280.0, 200.0], [360.0, 200.0], [320.0, 240.0], [290.0, 280.0], [350.0, 280.0]])
        face_skinny = np.array([[281.0, 200.5], [359.2, 199.5], [320.3, 240.8], [290.5, 279.6], [349.5, 280.2]])

        v_normal = extract_cranial_structure(face_normal)
        v_skinny = extract_cranial_structure(face_skinny)

        emb_probe = np.concatenate([np.zeros(128, dtype=np.float32), v_skinny])
        known_template = np.concatenate([np.zeros(128, dtype=np.float32), v_normal]).reshape(1, -1)

        res = engine.match_detailed(emb_probe, known_template)
        # Because bone structure matches (>0.72), the match succeeds despite the slight CNN drop!
        self.assertTrue(res.matched)
        self.assertTrue(res.cranial_verified)
        self.assertGreater(res.structure_score, 0.85)
        self.assertGreater(res.fused_score, 0.363)

    def test_enhance_low_light(self):
        # Empty / None frame
        enhanced, is_low, lum = enhance_low_light(None)
        self.assertIsNone(enhanced)
        self.assertFalse(is_low)

        # Bright frame (mean lum > 55)
        bright_frame = np.full((100, 100, 3), 120, dtype=np.uint8)
        enhanced, is_low, lum = enhance_low_light(bright_frame)
        self.assertFalse(is_low)
        self.assertGreater(lum, 55.0)

        # Low-light frame (mean lum < 55)
        dark_frame = np.full((100, 100, 3), 20, dtype=np.uint8)
        enhanced, is_low, lum = enhance_low_light(dark_frame)
        self.assertTrue(is_low)
        self.assertEqual(enhanced.shape, dark_frame.shape)

    @patch("cv2.FaceRecognizerSF.create")
    @patch("cv2.FaceDetectorYN.create")
    @patch("facelock.face_engine.ensure_models")
    def test_best_face_low_light_boost(self, mock_ensure, mock_det, mock_rec):
        mock_detector = MagicMock()
        mock_det.return_value = mock_detector

        mock_face = np.array([[10, 10, 50, 50, 20, 20, 40, 20, 30, 30, 22, 40, 38, 40, 0.72]], dtype=np.float32)
        # First call on raw frame returns None, second call on enhanced frame returns face
        mock_detector.detect.side_effect = [(0, None), (0, mock_face)]

        cfg = Config(detection_score_threshold=0.90)
        engine = FaceEngine(cfg)

        dark_frame = np.full((100, 100, 3), 20, dtype=np.uint8)
        face = engine.best_face(dark_frame, allow_low_light_boost=True)
        self.assertIsNotNone(face)
        self.assertEqual(face[14], 0.72)

    def test_score_to_match_percentage_calibration(self):
        # 1. Negative or near-zero cosine (noise / totally unrelated)
        self.assertEqual(score_to_match_percentage(0.0), 0.0)
        self.assertLess(score_to_match_percentage(0.05), 40.0)

        # 2. Impostor face (0.20 - 0.30 cosine) -> strictly below 92%
        impostor_pct = score_to_match_percentage(0.25)
        self.assertLess(impostor_pct, 92.0)
        self.assertGreaterEqual(impostor_pct, 50.0)

        # 3. Genuine face meeting baseline threshold (0.363 + cranial verification) -> >= 92%
        valid_pct = score_to_match_percentage(0.363, struct_score=0.85, cranial_verified=True)
        self.assertGreaterEqual(valid_pct, 92.0)

        # 4. Strong genuine face (0.60 - 0.80) -> high 90s%
        high_pct = score_to_match_percentage(0.65, struct_score=0.88, cranial_verified=True)
        self.assertGreaterEqual(high_pct, 95.0)

    @patch("cv2.FaceRecognizerSF.create")
    @patch("cv2.FaceDetectorYN.create")
    @patch("facelock.face_engine.ensure_models")
    def test_valid_face_92_percent_threshold(self, mock_ensure, mock_det, mock_rec):
        mock_rec.return_value.match.return_value = 0.50  # genuine face
        cfg = Config(min_match_percent=92.0)
        engine = FaceEngine(cfg)

        emb = np.zeros((1, 128), dtype=np.float32)
        known = np.zeros((1, 128), dtype=np.float32)

        res = engine.match_detailed(emb, known)
        self.assertTrue(res.matched)
        self.assertGreaterEqual(res.match_percent, 92.0)

        # Now test with impostor score (e.g. 0.20 cosine)
        mock_rec.return_value.match.return_value = 0.20
        res_impostor = engine.match_detailed(emb, known)
        self.assertFalse(res_impostor.matched)
        self.assertLess(res_impostor.match_percent, 92.0)


if __name__ == "__main__":
    unittest.main()

