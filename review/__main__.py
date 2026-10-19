"""Entry point.

Works three ways, because the thing that must never happen is the reviewer
failing to start the app:

    python -m exp1.review serve                     # from exp1's parent dir
    python exp1/review/__main__.py serve            # by path
    python -m review serve                          # from inside exp1/
"""

import sys

if __package__ in (None, ""):
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from exp1.review.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
