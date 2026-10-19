"""Filesystem layout.  One place that knows where everything lives."""

from __future__ import annotations

import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent          # exp1/review
EXP1 = HERE.parent                                      # exp1
STATIC = HERE / "static"

# Allow an override so the app can be pointed at a copy of the tree (tests,
# a second pilot, a colleague's export) without editing code.
_ENV_ROOT = os.environ.get("EXP1_ROOT")
ROOT = pathlib.Path(_ENV_ROOT).resolve() if _ENV_ROOT else EXP1

CONDITIONS = ROOT / "conditions"
TASKS = ROOT / "tasks"
FIXTURES = ROOT / "fixtures"
LOGS = ROOT / "logs"

# Episode records.  The loader accepts any of:
#   logs/episodes/*.json   (one record per file -- the default the harness should use)
#   logs/episodes.jsonl    (one record per line)
#   logs/episodes.json     (a JSON list)
EPISODES_DIR = LOGS / "episodes"
EPISODES_JSONL = LOGS / "episodes.jsonl"
EPISODES_JSON = LOGS / "episodes.json"

#: Synthetic demo records live OUTSIDE EPISODES_DIR. They carry a realistic
#: model name and no marker field, so if they share a directory with real
#: records the review app and the results pack silently count fabricated
#: episodes as data. Keeping them apart is the only reliable guard.
SYNTHETIC_DIR = LOGS / "synthetic"

VERIFICATION = ROOT / "verification.json"
AGREEMENT_REPORT = ROOT / "agreement_report.md"
RESULTS_REPORT = ROOT / "results.md"

# Condition artifacts (SPEC 5.2, 5.4).  C1 and C6 plant no memo file.
MEMO_FILES = {
    "C2_unrelated": CONDITIONS / "C2_unrelated.md",
    "C3_real": CONDITIONS / "C3_real.md",
    "C4_honeypot": CONDITIONS / "C4_honeypot.md",
    "C5_scrambled": CONDITIONS / "C5_scrambled.md",
}
SYSTEM_PROMPT_BASE = CONDITIONS / "system_prompt_base.txt"
C6_APPENDIX = CONDITIONS / "C6_positive_control_appendix.txt"
#: C7 delivers the SAME appendix as C6 and adds this notice, which is the only
#: byte that differs between the two prompts.
C7_LOCK_APPENDIX = CONDITIONS / "C7_tests_locked_appendix.txt"
USER_MSG_1 = CONDITIONS / "user_msg_1_ticket.txt"
USER_MSG_2 = CONDITIONS / "user_msg_2_followup.txt"

MEMO_PLANT_PATH = ".github/workflows/README.md"
MEMO_SENTINEL = "INFRA-2291"


def rel(p: pathlib.Path) -> str:
    """Path relative to ROOT when possible, for display."""
    try:
        return str(pathlib.Path(p).resolve().relative_to(ROOT))
    except (ValueError, OSError):
        return str(p)
