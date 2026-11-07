"""
ORBIT — Face Enrollment Tool.

Captures your face from the webcam (or an image file) and computes
a 128-d face model, saving it locally to enable face verification.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from config import load_config
    from db.database import Database
    from db.repositories import FaceModelRepository
    from vision.face_detect import FaceDetector
    from vision.face_recognize import FaceRecognizer, MODEL_DIR, OWNER_MODEL_FILE
except ImportError:
    from orbit.config import load_config
    from orbit.db.database import Database
    from orbit.db.repositories import FaceModelRepository
    from orbit.vision.face_detect import FaceDetector
    from orbit.vision.face_recognize import FaceRecognizer, MODEL_DIR, OWNER_MODEL_FILE

logger = logging.getLogger("orbit.enroll")


def enroll_from_frame(frame: np.ndarray, label: str = "owner") -> bool:
    """
    Enroll a face from a single BGR image frame.
    Saves to ~/.orbit/face_models/{label}.enc and the SQLite database.
    """
    return enroll_from_frames([frame], label=label)


def enroll_from_frames(frames: list[np.ndarray], label: str = "owner") -> bool:
    """
    Enroll multiple frames into a multi-template bank.
    Saves to ~/.orbit/face_models/{label}.enc and the SQLite database.
    """
    recognizer = FaceRecognizer()
    success = recognizer.enroll_multiple(frames, label=label)

    if success:
        try:
            db = Database()
            db.init()
            repo = FaceModelRepository(db)
            model_file = MODEL_DIR / f"{label}.enc"
            if model_file.exists():
                repo.save(label, model_file.read_bytes())
            db.close()
        except Exception as e:
            logger.warning("Saved to disk file but failed to persist to DB: %s", e)
        return True
    return False


def run_auto_capture(camera_index: int = 0, count: int = 15, label: str = "owner") -> int:
    """Automatically capture multiple frames of the owner for robust training."""
    print(f"[*] Starting multi-angle automatic training on camera {camera_index}...")
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"[x] Error: Could not open camera {camera_index}")
        return 1

    detector = FaceDetector()
    frames: list[np.ndarray] = []
    print(f"[*] Please look at the camera. Capturing {count} high-precision training frames...")

    try:
        attempts = 0
        while len(frames) < count and attempts < 120:
            attempts += 1
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.05)
                continue

            boxes = detector.detect(frame)
            if boxes and len(boxes) == 1 and boxes[0].confidence >= 0.7:
                frames.append(frame.copy())
                print(f"    [+] Captured frame {len(frames)}/{count} (confidence: {boxes[0].confidence:.2f})")
                time.sleep(0.12)
            else:
                time.sleep(0.05)

        if len(frames) >= 5:
            ok = enroll_from_frames(frames, label=label)
            if ok:
                print(f"[+] Multi-frame enrollment SUCCESSFUL for '{label}'! ({len(frames)} templates banked)")
                return 0
            else:
                print("[x] Multi-frame enrollment failed during feature extraction.")
                return 1
        else:
            print(f"[x] Insufficient clear frames captured ({len(frames)}/{count}).")
            return 1
    finally:
        cap.release()
        detector.close()


def run_interactive(camera_index: int, label: str = "owner") -> int:
    """Run interactive webcam enrollment."""
    print(f"[*] Opening camera {camera_index}...")
    cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print(f"[x] Error: Could not open camera {camera_index}.")
        print("    Try passing a different camera index with: python enroll.py --camera 1")
        return 1

    detector = FaceDetector()
    print("[*] Camera ready.")
    print("    Align your face within the frame.")
    print("    Press [SPACE] or [ENTER] to capture and enroll.")
    print("    Press [Q] or [ESC] to cancel.")

    enrolled = False
    status_text = "Align face and press SPACE"
    status_color = (255, 255, 255)

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.05)
                continue

            display = frame.copy()
            boxes = detector.detect(frame)

            for box in boxes:
                cv2.rectangle(
                    display,
                    (box.x, box.y),
                    (box.x + box.w, box.y + box.h),
                    (255, 255, 255),
                    2,
                )
                cv2.putText(
                    display,
                    f"Face ({box.confidence:.2f})",
                    (box.x, max(20, box.y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                )

            # Draw HUD
            cv2.rectangle(display, (0, 0), (display.shape[1], 45), (20, 20, 20), -1)
            cv2.putText(
                display,
                status_text,
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                status_color,
                2,
            )

            cv2.imshow("ORBIT Face Enrollment", display)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), 27):
                print("[*] Enrollment cancelled by user.")
                break

            if key in (32, 13):
                print("[*] Processing capture...")
                if not boxes:
                    status_text = "No face detected! Look directly at camera"
                    status_color = (0, 0, 255)
                    continue

                if enroll_from_frame(frame, label=label):
                    print(f"[+] Success: Face enrolled for '{label}'!")
                    print(f"    Saved to: {MODEL_DIR / f'{label}.enc'}")
                    enrolled = True
                    break
                else:
                    status_text = "Enrollment failed. Ensure face is well-lit"
                    status_color = (0, 0, 255)

    finally:
        cap.release()
        cv2.destroyAllWindows()
        detector.close()

    return 0 if enrolled else 1


def run_file(file_path: Path, label: str = "owner") -> int:
    """Enroll directly from an image file."""
    if not file_path.exists():
        print(f"[x] File not found: {file_path}")
        return 1

    img = cv2.imread(str(file_path))
    if img is None:
        print(f"[x] Could not decode image file: {file_path}")
        return 1

    print(f"[*] Processing image: {file_path}...")
    if enroll_from_frame(img, label=label):
        print(f"[+] Success: Face enrolled for '{label}' from {file_path}!")
        return 0
    else:
        print("[x] Error: Failed to detect and enroll face from image.")
        return 1


def main() -> None:
    config = load_config()
    parser = argparse.ArgumentParser(description="ORBIT Face Enrollment Tool")
    parser.add_argument(
        "--camera",
        type=int,
        default=config.vision_camera_index,
        help="Camera device index (default: from config)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Enroll from an existing image file",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Automatically capture multi-angle training frames",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=15,
        help="Number of frames to capture for auto training (default: 15)",
    )
    parser.add_argument(
        "--label",
        type=str,
        default="owner",
        help="Label for the enrolled user (default: owner)",
    )
    args = parser.parse_args()

    if args.file:
        sys.exit(run_file(args.file, label=args.label))
    elif args.auto:
        sys.exit(run_auto_capture(camera_index=args.camera, count=args.count, label=args.label))
    else:
        sys.exit(run_interactive(args.camera, label=args.label))


if __name__ == "__main__":
    main()
