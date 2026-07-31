"""Test suite.

Importing this package puts ``src/`` on ``sys.path`` so that ``python -m
unittest`` works from a clean checkout without an install step. Installing
the package (``pip install -e .``) also works and takes precedence.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
