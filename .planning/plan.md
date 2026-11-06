# Implementation Plan

- [ ] **Phase 1: Dependencies & Configuration Fixes**
  - [ ] Add `bleak`, `pytest`, and `pytest-asyncio` to `requirements.txt`.
  - [ ] Install essential testing and core packages into `.venv`.
  - [ ] Verification: Test imports of core modules in Python.

- [ ] **Phase 2: Face Enrollment Tooling**
  - [ ] Create `enroll.py` (CLI interactive enrollment utility using OpenCV camera capture & `FaceRecognizer.enroll()`).
  - [ ] Add `/api/enroll` endpoint to `orbit/dashboard/server.py` and UI trigger in `orbit/dashboard/static/index.html`.
  - [ ] Verification: Test `enroll.py --help` and verify dashboard route registration.

- [ ] **Phase 3: Automated Test Suite**
  - [ ] Create `tests/conftest.py` with shared fixtures (mock config, temp database, event bus).
  - [ ] Create `tests/test_event_bus.py` (publish/subscribe, wildcard, async dispatch).
  - [ ] Create `tests/test_presence.py` (presence states: PRESENT, AWAY, INTRUDER, timeouts).
  - [ ] Create `tests/test_modes.py` (mode transitions: Work, Meeting, Focus, Off).
  - [ ] Create `tests/test_crypto.py` (AES-256-GCM encryption/decryption, key derivation, pairing QR).
  - [ ] Create `tests/test_db.py` (SQLite WAL initialization, event repo, stats repo, intruder repo).
  - [ ] Create `tests/test_security.py` (intruder detection logic, approval timeout and resolution).
  - [ ] Verification: Run `pytest` across all test files.

- [ ] **Phase 4: Version Control & Final Verification**
  - [ ] Initialize git repo (`git init`).
  - [ ] Check `.gitignore` covers `.venv/`, `__pycache__/`, `*.db`, `*.mp4`, `snapshots/`.
  - [ ] Perform full pre-completion verification and update progress.md.
