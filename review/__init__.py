"""exp1.review -- the ground-truth review app.

A local, stdlib-only server that lets the researcher personally verify every
number before it leaves the project.  Three layers:

  Layer 1  conditions view   -- pre-run check that the conditions vary ONLY the memo
  Layer 2  results table      -- auto count vs human-verified count, per cell
  Layer 3  episode page       -- evidence first, automated labels revealed last

Entry point::

    python -m exp1.review serve

Reads episode records in the shape frozen in SPEC.md 6.7 (see records.py).
Writes exp1/verification.json, exp1/agreement_report.md, exp1/results.md.

No third-party dependencies.  No build step.
"""

__version__ = "1.0.0"

VERIFICATION_SCHEMA = "exp1.review.verification/1"
