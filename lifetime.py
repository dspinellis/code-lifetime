#!/usr/bin/env python3
"""Compatibility wrapper for the packaged git_hot implementation."""

import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent / "src"
if src_dir.is_dir():
    sys.path.insert(0, str(src_dir))

from git_hot import lifetime as _implementation  # noqa: E402

if __name__ == "__main__":
    sys.exit(_implementation.main())

sys.modules[__name__] = _implementation
