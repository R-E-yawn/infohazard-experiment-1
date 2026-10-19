"""The cheap discovery probe for Experiment 1.

Discovery -- "did the planted memo enter the transcript" -- is a binary that does
not need the rest of the experiment: no rigged test, no grader, no monitor, no
phase 2. This package runs **phase 1 only** against three environment designs and
measures one event, the same ``memo_exposed`` the full harness measures, through
the same observer.

Nothing here modifies ``harness/``, ``review/`` or ``conditions/``; it imports
from them so that the probe's prompt, tool surface and exposure definition are
byte-identical to the real experiment's.

Modules:

* :mod:`probe.variants`    -- the three variants as data (planted files, ticket,
  expected constant) plus ``self_check()`` over the invariants the design needs.
* :mod:`probe.probe_agent` -- a phase-1-only agent: one ``react()``, the harness
  ``ToolSurface``, the ``C1_baseline`` system prompt.
* :mod:`probe.run_probe`   -- plants the files, runs N episodes per variant
  through ``eval_set``, writes one JSON record per episode.
* :mod:`probe.report`      -- the variant x outcome table with Wilson 95% CIs.
"""

from __future__ import annotations

__all__ = ["variants", "probe_agent", "run_probe", "report"]
