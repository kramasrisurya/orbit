"""
ORBIT — Face Enrollment Tool.
Runs the top-level enroll utility.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import enroll

if __name__ == "__main__":
    enroll.main()
