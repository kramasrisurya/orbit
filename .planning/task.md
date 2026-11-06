# Task: Complete and Harden the ORBIT System

## Objective
Transition ORBIT from an unconfigured reference prototype to a tested, deployable, and verified local ambient awareness system by:
1. Adding the missing Face Enrollment CLI script (`enroll.py`) and Dashboard Enrollment endpoint.
2. Resolving dependency definitions (adding `bleak` to `requirements.txt`).
3. Initializing Git version control with proper gitignore rules.
4. Implementing a comprehensive automated test suite (`pytest`) covering the Event Bus, Presence state machine, Modes, Security/Intruder, Crypto/AES-GCM, and Database Repositories.
5. Verifying the entire Python test suite passes cleanly with zero errors.

## Constraints
- Python 3.13 on Windows.
- Keep all local-first privacy invariants intact (no telemetry, local SQLite WAL, thread-safe EventBus).
- Ensure graceful fallbacks when hardware devices (webcam, BLE dongle) or native C libraries (dlib) are absent during testing through clean mocking / modular unit testing.

## Acceptance Criteria
- [ ] `requirements.txt` includes all required dependencies including `bleak` and testing tools (`pytest`, `pytest-asyncio`).
- [ ] `enroll.py` command-line helper is created, functional, and documented.
- [ ] Face enrollment API endpoint is available on the Dashboard server.
- [ ] Automated test suite created in `tests/` covering core modules: `core/event_bus`, `core/presence`, `core/modes`, `security`, `crypto`, `db`.
- [ ] Git repository initialized with atomic initial commit.
- [ ] All tests execute and pass cleanly.
