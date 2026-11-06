# Implementation Plan

- [x] **Phase 1: Dependencies & Configuration Fixes**
  - [x] Add `bleak`, `pytest`, and `pytest-asyncio` to `requirements.txt`.
  - [x] Install essential testing and core packages into `.venv`.
  - [x] Verification: Test imports of core modules in Python.

- [x] **Phase 2: Face Enrollment Tooling**
  - [x] Create `enroll.py` (CLI interactive enrollment utility using OpenCV camera capture & `FaceRecognizer.enroll()`).
  - [x] Add `/api/enroll` endpoint to `orbit/dashboard/server.py` and UI trigger in `orbit/dashboard/static/index.html`.
  - [x] Verification: Test `enroll.py --help` and verify dashboard route registration.

- [x] **Phase 3: Automated Test Suite**
  - [x] Create `tests/conftest.py` with shared fixtures (mock config, temp database, event bus).
  - [x] Create `tests/test_event_bus.py` (publish/subscribe, wildcard, async dispatch).
  - [x] Create `tests/test_presence.py` (presence states: PRESENT, AWAY, INTRUDER, timeouts).
  - [x] Create `tests/test_modes.py` (mode transitions: Work, Meeting, Focus, Off).
  - [x] Create `tests/test_crypto.py` (AES-256-GCM encryption/decryption, key derivation, pairing QR).
  - [x] Create `tests/test_db.py` (SQLite WAL initialization, event repo, stats repo, intruder repo).
  - [x] Create `tests/test_security.py` (intruder detection logic, approval timeout and resolution).
  - [x] Verification: Run `pytest` across all test files (33/33 passed).

- [x] **Phase 4: Version Control & Final Verification**
  - [x] Initialize git repo (`git init`).
  - [x] Check `.gitignore` covers `.venv/`, `__pycache__/`, `*.db`, `*.mp4`, `snapshots/`, `.pytest_cache/`.
  - [x] Initialized Git repository and created initial commit.
