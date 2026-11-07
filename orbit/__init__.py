import sys
from pathlib import Path

_orbit_dir = str(Path(__file__).parent.resolve())
if _orbit_dir not in sys.path:
    sys.path.insert(0, _orbit_dir)
