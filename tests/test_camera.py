import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from facelock.camera import Camera


class TestCamera(unittest.TestCase):
    @patch("cv2.VideoCapture")
    def test_camera_open_success_sets_buffersize(self, mock_cv):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cv.return_value = mock_cap

        camera = Camera(0)
        self.assertTrue(camera.open())
        mock_cv.assert_called_once_with(0)
        mock_cap.set.assert_called_once_with(cv2.CAP_PROP_BUFFERSIZE, 1)

    @patch("cv2.VideoCapture")
    def test_camera_open_failure_throttles_logs(self, mock_cv):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        mock_cv.return_value = mock_cap

        camera = Camera(0)
        with patch("facelock.camera.logger") as mock_logger:
            # First failure logs warning
            self.assertFalse(camera.open())
            mock_logger.warning.assert_called_once()

            # Second consecutive failure is throttled
            mock_logger.reset_mock()
            self.assertFalse(camera.open())
            mock_logger.warning.assert_not_called()

    @patch("cv2.VideoCapture")
    def test_camera_read(self, mock_cv):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_cap.read.return_value = (True, mock_frame)
        mock_cv.return_value = mock_cap

        camera = Camera(0)
        frame = camera.read()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (480, 640, 3))

    @patch("cv2.VideoCapture")
    def test_camera_context_manager(self, mock_cv):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cv.return_value = mock_cap

        with Camera(0) as cam:
            self.assertIsNotNone(cam._cap)
        self.assertIsNone(cam._cap)
        mock_cap.release.assert_called()


if __name__ == "__main__":
    unittest.main()
