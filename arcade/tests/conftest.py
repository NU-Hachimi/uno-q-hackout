import sys
from pathlib import Path

import pytest

# The game modules live in python/ and import each other as top-level modules, as on the board.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))


@pytest.fixture(autouse=True)
def empty_world():
    """Every test starts with nothing in the engine's world (tests/arena.py)."""
    from arena import W
    W.clear()
    yield
