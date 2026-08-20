import sys
from pathlib import Path

ETA_DIR = Path(__file__).resolve().parent / "bot" / "vendor" / "eta"
sys.path.insert(0, str(ETA_DIR))
