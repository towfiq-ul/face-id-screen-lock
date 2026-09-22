import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from facelock.config import Config
from facelock.liveness import LivenessTracker
from facelock.monitor import _verify_frame


class TestMonitor(unittest.TestCase):
    def setUp(self):
        self.config = Config(liveness_enabled=False)
        self.engine = MagicMock()
        self.liveness_tracker = MagicMock(spec=LivenessTracker)
        self.known_embeddings = np.ones((1, 128), dtype=np.float32)

    def test_verify_frame_no_face(self):
        self.engine.best_face.return_value = None
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        result = _verify_frame(frame, self.engine, self.known_embeddings, self.config, self.liveness_tracker)
        self.assertFalse(result)
        self.liveness_tracker.reset.assert_called_once()

    def test_verify_frame_matched_face(self):
        fake_face = np.zeros(15, dtype=np.float32)
        fake_emb = np.ones((1, 128), dtype=np.float32)
        self.engine.best_face.return_value = fake_face
        self.engine.embed.return_value = fake_emb
        self.engine.matches_any.return_value = (True, 0.85)

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        result = _verify_frame(frame, self.engine, self.known_embeddings, self.config, self.liveness_tracker)
        self.assertTrue(result)

    def test_verify_frame_unmatched_face(self):
        fake_face = np.zeros(15, dtype=np.float32)
        fake_emb = np.ones((1, 128), dtype=np.float32)
        self.engine.best_face.return_value = fake_face
        self.engine.embed.return_value = fake_emb
        self.engine.matches_any.return_value = (False, 0.20)

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        result = _verify_frame(frame, self.engine, self.known_embeddings, self.config, self.liveness_tracker)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
