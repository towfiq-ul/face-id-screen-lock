# facelock

A webcam-based auto-lock daemon for Linux. It watches your webcam and locks
the screen if the enrolled ("known") face hasn't been seen for a
configurable amount of time (default 60s).

Auto-*unlock* (recognizing your face at the lock screen and logging you back
in) is intentionally **not** implemented here — that's handled by
[Howdy](https://github.com/boltgolt/howdy), a mature project that already
integrates face recognition into PAM safely. This repo only builds the half
Howdy doesn't: continuously watching the webcam while the session is
unlocked and triggering the lock when the known face disappears.

Tested on Ubuntu 24.04, GNOME on X11, GDM.

## How it works

- Face detection/recognition uses OpenCV's bundled YuNet (detector) and
  SFace (recognizer) ONNX models — no `dlib`/`cmake` build step required.
- `facelock-enroll` captures a handful of frames of your face and stores
  their embeddings at `~/.local/share/facelock/known_face.npy`.
- `facelock-monitor` polls the webcam every `check_interval_seconds`. While
  the session is unlocked, if the known face isn't detected for
  `unknown_face_timeout_seconds`, it calls `loginctl lock-session`. While
  the session is already locked, it releases the camera and just polls
  `LockedHint` — so it never fights Howdy for the camera during an unlock
  attempt.

## Setup

```bash
make venv     # creates .venv, installs this package into it
make enroll   # capture your face (look at the camera, turn your head slightly between shots)
make run      # run the monitor in the foreground to try it out
```

Config lives at `~/.config/facelock/config.yaml` (created with defaults on
first run of anything that loads it):

```yaml
camera_index: 0
check_interval_seconds: 2.0
unknown_face_timeout_seconds: 60.0
match_threshold: 0.363
detection_score_threshold: 0.9
enroll_frame_count: 8
```

## Running as a service

```bash
make service-install    # installs + enables the systemd --user unit
make service-logs       # follow its logs
make service-uninstall  # stop + remove it
```

## System-wide install (standard FHS paths)

`Makefile`/`make venv` above is the lightweight, repo-local dev setup. For a
proper system install that puts things where Linux conventionally expects
them:

```bash
sudo ./install.sh
```

This installs to:

- `/opt/facelock/venv` — self-contained venv + the installed package (`/opt`
  is the standard location for a self-contained third-party application)
- `/usr/local/bin/facelock-enroll`, `/usr/local/bin/facelock-monitor` —
  symlinks onto `PATH` (standard location for locally-installed software not
  managed by the distro's package manager)
- `~/.config/systemd/user/facelock-monitor.service` — the per-user service
  unit

It also asks whether to enroll your face right away, then enables (and
starts, if a face is already enrolled) the service. It writes an uninstaller
to `/opt/facelock/uninstall.sh` reflecting exactly what it installed —
remove everything with:

```bash
sudo /opt/facelock/uninstall.sh
```

The uninstaller leaves your enrolled face/config
(`~/.local/share/facelock/`, `~/.config/facelock/`) in place; it prints how
to remove those too if you want a fully clean uninstall.

## Real auto-unlock (Howdy)

To get real face-unlock at the lock screen, install
[Howdy](https://github.com/boltgolt/howdy) separately and enroll with
`sudo howdy add`. On Ubuntu 24.04 the official PPA's installer is currently
broken (blocked by pip's "externally-managed-environment" restriction) — use
the patched PPA from Panda Jim / UbuntuHandbook instead. Howdy's installer
edits `/etc/pam.d/gdm-password` itself; this repo never touches system PAM
files.

**Limitation:** like Howdy itself, this has no liveness/anti-spoofing check
— a photo could plausibly fool the recognizer. Treat this as a convenience
deterrent, not a real security boundary.

## Scope

Linux only for now (single enrolled face). Multi-face and other platforms
(Windows/macOS) are future work; the OS-specific piece is isolated behind
`facelock/platform/base.py` so those can be added without touching the face
recognition or monitor logic.
