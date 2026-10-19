"""pytest configuration for the exp1 harness tests.

Only two jobs: register the ``real`` marker (so the executed tier can be run
or skipped with ``-m``), and clean up the cached post-setup templates that
``test_grader_offline`` builds once per split.
"""

from __future__ import annotations

import shutil


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real: needs a real Sphinx 4.1 checkout and interpreter "
        "(EXP1_STAGEA_SPHINX_REPO / EXP1_STAGEA_PYTHON)",
    )


def pytest_sessionfinish(session, exitstatus):
    import sys

    mod = None
    for name in ("test_grader_offline", "exp1.harness.tests.test_grader_offline"):
        mod = sys.modules.get(name)
        if mod is not None:
            break
    _TEMPLATES = getattr(mod, "_TEMPLATES", None)
    if not _TEMPLATES:
        return
    for root, _ref1, _ref2 in _TEMPLATES.values():
        shutil.rmtree(root, ignore_errors=True)
    _TEMPLATES.clear()
