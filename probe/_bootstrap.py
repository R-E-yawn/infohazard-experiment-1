"""Make ``harness`` importable however the probe is invoked.

The probe lives inside ``exp1/`` and imports from ``exp1/harness/``. Three
invocations have to work and they disagree about what is on ``sys.path``:

* ``cd exp1 && python -m probe.run_probe``        -> ``exp1`` is on the path
* ``cd .. && python -m exp1.probe.run_probe``     -> the parent is on the path
* ``pytest exp1/probe/tests/...`` from either     -> rootdir-dependent

Rather than a try/except ladder in every module, put ``exp1`` itself on
``sys.path`` once and import ``harness`` as a top-level package -- which is what
``harness/tests/*`` already do, so a single pytest process never ends up with two
copies of the harness under two names.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

#: ``exp1/`` -- the directory that holds both ``harness/`` and ``probe/``.
EXP1_DIR: Final[Path] = Path(__file__).resolve().parents[1]

#: ``exp1/probe/``
PROBE_DIR: Final[Path] = EXP1_DIR / "probe"


def ensure_harness_importable() -> Path:
    """Put ``exp1/`` on ``sys.path`` and return it."""
    path = str(EXP1_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    return EXP1_DIR


ensure_harness_importable()
