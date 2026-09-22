from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from facelock import profiles


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        self.mock_data_dir = self.tmp_path / "data"
        self.mock_faces_dir = self.mock_data_dir / "faces"
        self.mock_meta_path = self.mock_data_dir / "profiles.json"
        self.mock_known_face = self.mock_data_dir / "known_face.npy"

        self.patches = [
            patch.object(profiles.cfg, "DATA_DIR", self.mock_data_dir),
            patch.object(profiles, "PROFILES_DIR", self.mock_faces_dir),
            patch.object(profiles, "PROFILES_META_PATH", self.mock_meta_path),
            patch.object(profiles.cfg, "KNOWN_FACE_PATH", self.mock_known_face),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp_dir.cleanup()

    def test_empty_profiles(self):
        self.assertEqual(profiles.list_profiles(), {})
        self.assertEqual(profiles.get_profile_count(), 0)
        self.assertEqual(profiles.get_profile_names(), [])
        self.assertIsNone(profiles.get_combined_embeddings())
        self.assertEqual(profiles.next_unknown_name(), "unknown_1")

    def test_save_profile_auto_name(self):
        dummy1 = np.random.randn(7, 136).astype(np.float32)
        saved_name = profiles.save_profile(None, dummy1, allow_face_duplicate=True)
        self.assertEqual(saved_name, "unknown_1")
        self.assertEqual(profiles.get_profile_count(), 1)
        self.assertIn("unknown_1", profiles.get_profile_names())

        # Next default should be unknown_2
        self.assertEqual(profiles.next_unknown_name(), "unknown_2")

        dummy2 = np.random.randn(7, 136).astype(np.float32)
        saved_name2 = profiles.save_profile("", dummy2, allow_face_duplicate=True)
        self.assertEqual(saved_name2, "unknown_2")
        self.assertEqual(profiles.get_profile_count(), 2)

    def test_save_profile_custom_name(self):
        dummy = np.random.randn(7, 136).astype(np.float32)
        saved_name = profiles.save_profile("Towfiq", dummy, allow_face_duplicate=True)
        self.assertEqual(saved_name, "Towfiq")
        self.assertEqual(profiles.get_profile_count(), 1)
        self.assertIn("Towfiq", profiles.get_profile_names())

    def test_name_collision_error(self):
        dummy1 = np.random.randn(7, 136).astype(np.float32)
        profiles.save_profile("Alice", dummy1, allow_face_duplicate=True)

        dummy2 = np.random.randn(7, 136).astype(np.float32)
        with self.assertRaises(profiles.ProfileNameExistsError) as ctx:
            profiles.save_profile("alice", dummy2, allow_face_duplicate=True)  # case-insensitive
        self.assertIn("already exists with name 'Alice'", str(ctx.exception))

    def test_max_two_profiles_error(self):
        dummy1 = np.random.randn(7, 136).astype(np.float32)
        dummy2 = np.random.randn(7, 136).astype(np.float32)
        dummy3 = np.random.randn(7, 136).astype(np.float32)

        profiles.save_profile("UserOne", dummy1, allow_face_duplicate=True)
        profiles.save_profile("UserTwo", dummy2, allow_face_duplicate=True)

        with self.assertRaises(profiles.MaxProfilesError) as ctx:
            profiles.save_profile("UserThree", dummy3, allow_face_duplicate=True)
        self.assertIn("Maximum profile limit reached (2 faces)", str(ctx.exception))
        self.assertIn("'UserOne'", str(ctx.exception))
        self.assertIn("'UserTwo'", str(ctx.exception))

    def test_biometric_face_already_exists_error(self):
        mock_engine = MagicMock()
        match_res = MagicMock()
        match_res.matched = True
        match_res.fused_score = 0.88
        mock_engine.match_detailed.return_value = match_res

        dummy1 = np.random.randn(7, 136).astype(np.float32)
        profiles.save_profile("Owner", dummy1, allow_face_duplicate=True)

        dummy2 = np.random.randn(7, 136).astype(np.float32)
        with self.assertRaises(profiles.FaceAlreadyExistsError) as ctx:
            profiles.save_profile("NewName", dummy2, engine=mock_engine, allow_face_duplicate=False)
        self.assertIn("already enrolled under profile 'Owner'", str(ctx.exception))

    def test_delete_profile(self):
        dummy1 = np.random.randn(7, 136).astype(np.float32)
        dummy2 = np.random.randn(7, 136).astype(np.float32)

        profiles.save_profile("UserA", dummy1, allow_face_duplicate=True)
        profiles.save_profile("UserB", dummy2, allow_face_duplicate=True)
        self.assertEqual(profiles.get_profile_count(), 2)

        # Delete UserA
        deleted = profiles.delete_profile("UserA")
        self.assertTrue(deleted)
        self.assertEqual(profiles.get_profile_count(), 1)
        self.assertNotIn("UserA", profiles.get_profile_names())
        self.assertIn("UserB", profiles.get_profile_names())

        # Now we can save another profile
        dummy3 = np.random.randn(7, 136).astype(np.float32)
        saved = profiles.save_profile("UserC", dummy3, allow_face_duplicate=True)
        self.assertEqual(saved, "UserC")
        self.assertEqual(profiles.get_profile_count(), 2)

    def test_legacy_migration(self):
        self.mock_data_dir.mkdir(parents=True, exist_ok=True)
        legacy_data = np.random.randn(7, 136).astype(np.float32)
        np.save(self.mock_known_face, legacy_data)

        # list_profiles should auto-migrate to unknown_1
        p = profiles.list_profiles()
        self.assertIn("unknown_1", p)
        self.assertEqual(p["unknown_1"].shape, (7, 136))
        self.assertEqual(profiles.get_profile_count(), 1)

    def test_file_permissions_hardened(self):
        dummy = np.random.randn(7, 136).astype(np.float32)
        saved = profiles.save_profile("SecureUser", dummy, allow_face_duplicate=True)
        self.assertEqual(saved, "SecureUser")

        # Check directory permissions (0o700)
        dir_stat = self.mock_faces_dir.stat().st_mode & 0o777
        self.assertEqual(dir_stat, 0o700)

        # Check metadata file permissions (0o600)
        meta_stat = self.mock_meta_path.stat().st_mode & 0o777
        self.assertEqual(meta_stat, 0o600)

        # Check profile vector file permissions (0o600)
        profile_file = self.mock_faces_dir / "secureuser.npy"
        file_stat = profile_file.stat().st_mode & 0o777
        self.assertEqual(file_stat, 0o600)
