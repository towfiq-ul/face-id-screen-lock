"""Profile management for FaceLock: support up to MAX_PROFILES (2) named faces.

Handles:
- Storage under XDG data directory (faces/<name>.npy + profiles.json).
- Name collision validation ("faces exists with name").
- Biometric duplicate validation (rejecting faces already registered under an existing name).
- Default naming: unknown_1, unknown_2, etc.
- Migration from legacy single known_face.npy file.
- Combined embeddings generation for the background monitor and PAM biometric engine.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

import numpy as np

from facelock import config as cfg

if TYPE_CHECKING:
    from facelock.face_engine import FaceEngine

logger = logging.getLogger(__name__)

MAX_PROFILES: int = 2
PROFILES_DIR: Path = cfg.DATA_DIR / "faces"
PROFILES_META_PATH: Path = cfg.DATA_DIR / "profiles.json"


class FaceProfileError(Exception):
    """Base error for face profile operations."""


class MaxProfilesError(FaceProfileError):
    """Raised when attempting to enroll more than MAX_PROFILES."""


class ProfileNameExistsError(FaceProfileError):
    """Raised when a profile name already exists."""


class FaceAlreadyExistsError(FaceProfileError):
    """Raised when a face biometrically matches an already enrolled profile."""


@dataclass
class ProfileMeta:
    name: str
    filename: str
    created_at: float
    vector_count: int


def _sanitize_filename(name: str) -> str:
    """Convert profile name to a safe filename."""
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[-\s]+", "_", s) or "profile"


def get_profiles_dir() -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    try:
        PROFILES_DIR.chmod(0o700)
    except OSError:
        pass
    return PROFILES_DIR


def _ensure_migrated() -> None:
    """Migrate legacy known_face.npy to profiles.json + faces/unknown_1.npy if needed."""
    if PROFILES_META_PATH.exists():
        return

    get_profiles_dir()
    if cfg.KNOWN_FACE_PATH.exists():
        try:
            legacy_data = np.load(cfg.KNOWN_FACE_PATH, allow_pickle=False)
            if isinstance(legacy_data, np.ndarray) and len(legacy_data) > 0:
                name = "unknown_1"
                fname = "unknown_1.npy"
                dest = PROFILES_DIR / fname
                np.save(dest, legacy_data)
                try:
                    dest.chmod(0o600)
                except OSError:
                    pass

                meta = {
                    "profiles": [
                        {
                            "name": name,
                            "filename": fname,
                            "created_at": time.time(),
                            "vector_count": len(legacy_data),
                        }
                    ]
                }
                with PROFILES_META_PATH.open("w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                try:
                    PROFILES_META_PATH.chmod(0o600)
                except OSError:
                    pass
                logger.info("Migrated legacy face profile to %s", dest)
                return
        except Exception as e:
            logger.warning("Could not migrate legacy known_face.npy: %s", e)

    # Initialize empty metadata file
    try:
        with PROFILES_META_PATH.open("w", encoding="utf-8") as f:
            json.dump({"profiles": []}, f, indent=2)
        PROFILES_META_PATH.chmod(0o600)
    except Exception:
        pass


def _read_meta() -> list[ProfileMeta]:
    _ensure_migrated()
    if not PROFILES_META_PATH.exists():
        return []
    try:
        with PROFILES_META_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return [ProfileMeta(**p) for p in data.get("profiles", [])]
    except Exception as e:
        logger.warning("Failed to parse %s: %s", PROFILES_META_PATH, e)
        return []


def _write_meta(profiles: list[ProfileMeta]) -> None:
    cfg.ensure_dirs()
    get_profiles_dir()
    with PROFILES_META_PATH.open("w", encoding="utf-8") as f:
        json.dump({"profiles": [asdict(p) for p in profiles]}, f, indent=2)
    try:
        PROFILES_META_PATH.chmod(0o600)
    except OSError:
        pass


def list_profiles() -> dict[str, np.ndarray]:
    """Return dictionary mapping profile_name -> embeddings array (shape: N, 136)."""
    meta_list = _read_meta()
    results: dict[str, np.ndarray] = {}
    changed = False

    for meta in meta_list:
        file_path = PROFILES_DIR / meta.filename
        if file_path.exists():
            try:
                arr = np.load(file_path, allow_pickle=False)
                results[meta.name] = arr
            except Exception as e:
                logger.warning("Error loading profile %s from %s: %s", meta.name, file_path, e)
        else:
            changed = True

    if changed:
        # Prune missing profiles
        valid_meta = [p for p in meta_list if p.name in results]
        _write_meta(valid_meta)

    return results


def get_profile_names() -> list[str]:
    """Return list of enrolled profile names."""
    return [p.name for p in _read_meta()]


def get_profile_count() -> int:
    return len(_read_meta())


def next_unknown_name(existing_names: Iterable[str] | None = None) -> str:
    """Generate default sequential unknown name: unknown_1, unknown_2, etc."""
    if existing_names is None:
        names = set(get_profile_names())
    else:
        names = set(existing_names)

    idx = 1
    while f"unknown_{idx}" in names:
        idx += 1
    return f"unknown_{idx}"


def get_combined_embeddings() -> np.ndarray | None:
    """Return combined embeddings array of all enrolled profiles, or None if none enrolled.

    Also updates cfg.KNOWN_FACE_PATH for daemon/PAM backwards compatibility.
    """
    profiles = list_profiles()
    if not profiles:
        if cfg.KNOWN_FACE_PATH.exists():
            try:
                cfg.KNOWN_FACE_PATH.unlink()
            except Exception:
                pass
        return None

    arrays = list(profiles.values())
    combined = np.concatenate(arrays, axis=0) if len(arrays) > 1 else arrays[0]

    # Sync to KNOWN_FACE_PATH with secure permissions
    try:
        cfg.ensure_dirs()
        np.save(cfg.KNOWN_FACE_PATH, combined)
        try:
            cfg.KNOWN_FACE_PATH.chmod(0o600)
        except OSError:
            pass
    except Exception as e:
        logger.warning("Failed to sync combined embeddings to %s: %s", cfg.KNOWN_FACE_PATH, e)

    return combined


def check_face_matches_existing(
    embedding_or_embeddings: np.ndarray | list[np.ndarray],
    engine: FaceEngine | None = None,
) -> tuple[bool, str | None, float]:
    """Check if probe embeddings biometrically match an already enrolled face profile.

    Returns:
        (is_match, matched_profile_name, highest_score)
    """
    profiles = list_profiles()
    if not profiles:
        return False, None, 0.0

    if engine is None:
        from facelock.face_engine import FaceEngine
        config = cfg.Config.load()
        engine = FaceEngine(config)

    if isinstance(embedding_or_embeddings, list):
        probe_arr = np.stack(embedding_or_embeddings)
    else:
        probe_arr = np.asarray(embedding_or_embeddings)

    if probe_arr.ndim == 1:
        probe_arr = probe_arr.reshape(1, -1)

    best_match_name: str | None = None
    best_score: float = -1.0

    for name, known in profiles.items():
        for probe in probe_arr:
            res = engine.match_detailed(probe, known)
            if res.fused_score > best_score:
                best_score = res.fused_score
            if res.matched:
                best_match_name = name
                return True, best_match_name, res.fused_score

    return False, best_match_name, best_score


def save_profile(
    name: str | None,
    embeddings: list[np.ndarray] | np.ndarray,
    engine: FaceEngine | None = None,
    allow_face_duplicate: bool = False,
) -> str:
    """Validate and save a new face profile.

    Enforces:
    - Maximum 2 face profiles.
    - Name collision check (case-insensitive).
    - Biometric face duplicate check (warns if face already belongs to another name).
    - Auto-assignment to unknown_1, unknown_2 if name is blank/None.

    Returns:
        The final assigned profile name.
    """
    _ensure_migrated()
    current_profiles = _read_meta()
    existing_names = [p.name for p in current_profiles]

    # 1. Enforce max 2 profiles
    if len(current_profiles) >= MAX_PROFILES:
        names_str = ", ".join(f"'{n}'" for n in existing_names)
        raise MaxProfilesError(
            f"Maximum profile limit reached ({MAX_PROFILES} faces).\n"
            f"Existing face profiles with names: {names_str}.\n"
            f"Please delete an existing profile first."
        )

    # 2. Resolve name
    clean_name = (name or "").strip()
    if not clean_name:
        clean_name = next_unknown_name(existing_names)

    # 3. Check for name collision (case-insensitive)
    for existing in existing_names:
        if existing.lower() == clean_name.lower():
            raise ProfileNameExistsError(
                f"A face profile already exists with name '{existing}'."
            )

    # 4. Check for biometric duplicate (is this face already enrolled?)
    arr = np.stack(embeddings) if isinstance(embeddings, list) else np.asarray(embeddings)
    if not allow_face_duplicate and len(current_profiles) > 0:
        is_dup, matched_name, score = check_face_matches_existing(arr, engine=engine)
        if is_dup and matched_name:
            raise FaceAlreadyExistsError(
                f"This face is already enrolled under profile '{matched_name}' (match score: {score:.2f})."
            )

    # 5. Save to faces/<filename>.npy
    get_profiles_dir()
    safe_base = _sanitize_filename(clean_name)
    fname = f"{safe_base}.npy"
    # Ensure unique filename
    counter = 1
    while (PROFILES_DIR / fname).exists():
        fname = f"{safe_base}_{counter}.npy"
        counter += 1

    dest = PROFILES_DIR / fname
    np.save(dest, arr)
    try:
        dest.chmod(0o600)
    except OSError:
        pass

    # 6. Update metadata
    current_profiles.append(
        ProfileMeta(
            name=clean_name,
            filename=fname,
            created_at=time.time(),
            vector_count=len(arr),
        )
    )
    _write_meta(current_profiles)

    # 7. Update combined embeddings cache for monitor & PAM
    get_combined_embeddings()

    logger.info("Saved profile '%s' with %d vectors to %s", clean_name, len(arr), dest)
    return clean_name


def delete_profile(name: str) -> bool:
    """Delete profile by name and update metadata & combined embeddings."""
    _ensure_migrated()
    current_profiles = _read_meta()
    target = None
    remaining = []

    for p in current_profiles:
        if p.name.lower() == name.lower():
            target = p
        else:
            remaining.append(p)

    if target is None:
        return False

    # Remove file
    fpath = PROFILES_DIR / target.filename
    if fpath.exists():
        try:
            fpath.unlink()
        except Exception as e:
            logger.warning("Could not delete %s: %s", fpath, e)

    _write_meta(remaining)
    get_combined_embeddings()
    logger.info("Deleted profile '%s'", target.name)
    return True


def delete_all_profiles() -> int:
    """Delete all enrolled profiles and clean up storage and cache."""
    _ensure_migrated()
    current_profiles = _read_meta()
    count = len(current_profiles)
    for p in current_profiles:
        fpath = PROFILES_DIR / p.filename
        if fpath.exists():
            try:
                fpath.unlink()
            except Exception:
                pass
    _write_meta([])
    get_combined_embeddings()
    logger.info("Deleted all %d profile(s)", count)
    return count


def cli_main() -> None:
    """CLI helper to list and delete face profiles."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage FaceLock face profiles")
    parser.add_argument("name", nargs="?", default=None, help="Name of profile to delete")
    parser.add_argument("--list", "-l", action="store_true", help="List enrolled profiles")
    parser.add_argument("--all", "-a", action="store_true", help="Delete all enrolled profiles")
    args = parser.parse_args()

    names = get_profile_names()

    if args.list:
        if not names:
            print("\nNo face profiles enrolled (0/2).\n")
        else:
            print(f"\nEnrolled face profiles ({len(names)}/{MAX_PROFILES}):")
            for idx, n in enumerate(names, start=1):
                print(f"  [{idx}] {n}")
            print()
        return

    if args.all:
        if not names:
            print("\nNo face profiles enrolled.\n")
            return
        confirm = input(f"Are you sure you want to delete ALL {len(names)} profile(s)? [y/N]: ").strip().lower()
        if confirm == "y":
            cnt = delete_all_profiles()
            print(f"✓ Successfully deleted all {cnt} face profile(s).\n")
        else:
            print("Canceled.\n")
        return

    if args.name:
        if delete_profile(args.name):
            print(f"✓ Face profile '{args.name}' successfully deleted.")
        else:
            print(f"❌ Face profile '{args.name}' not found. Available profiles: {names}")
        return

    # Interactive deletion menu
    if not names:
        print("\nNo face profiles enrolled (0/2).\n")
        return

    print(f"\nEnrolled Face Profiles ({len(names)}/{MAX_PROFILES}):")
    for idx, n in enumerate(names, start=1):
        print(f"  [{idx}] {n}")
    print("  [A] Delete ALL profiles")
    print("  [Q] Cancel / Quit")

    try:
        choice = input("\nEnter profile number, name, 'A' (all), or 'Q' (quit): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCanceled.\n")
        return

    if not choice or choice.lower() in ("q", "quit"):
        print("Canceled.\n")
        return

    if choice.lower() == "a":
        confirm = input(f"Are you sure you want to delete ALL {len(names)} profiles? [y/N]: ").strip().lower()
        if confirm == "y":
            cnt = delete_all_profiles()
            print(f"✓ Successfully deleted {cnt} face profile(s).\n")
        else:
            print("Canceled.\n")
        return

    target_name = None
    if choice.isdigit():
        num = int(choice)
        if 1 <= num <= len(names):
            target_name = names[num - 1]
    else:
        for n in names:
            if n.lower() == choice.lower():
                target_name = n
                break

    if target_name:
        if delete_profile(target_name):
            print(f"✓ Face profile '{target_name}' successfully deleted.\n")
        else:
            print(f"❌ Failed to delete face profile '{target_name}'.\n")
    else:
        print(f"❌ Invalid selection '{choice}'. Available: {names}\n")


if __name__ == "__main__":
    cli_main()
