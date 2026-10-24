import sys
from pathlib import Path

# The game modules live in python/ and import each other as top-level modules, as on the board.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
