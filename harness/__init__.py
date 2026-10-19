"""exp1 harness.

Measurement half (this agent's component):

* :mod:`exp1.harness.records`  -- the ``EpisodeRecord`` contract + label invariants
* :mod:`exp1.harness.monitor`  -- the sandbox abstraction + hash-based monitor
* :mod:`exp1.harness.grader`   -- Runs A/B/C and the label decision
* :mod:`exp1.harness.classify` -- the deterministic method classifier

Agent half (owned elsewhere): ``task.py``, ``agent.py``, ``tools.py``.

The sandbox abstraction lives in :mod:`monitor` because the monitor is what
defines "observe the sandbox by a mechanism the agent cannot influence"; it is
re-exported here so callers can write ``from exp1.harness import LocalBackend``.
"""

from __future__ import annotations

from .classify import (
    RIGGED_LITERALS,
    FileChange,
    MonitorSignals,
    classify,
    classify_static,
    extract_features,
)
from .episode import (
    build_record,
    records_from_log,
    records_from_paths,
    write_records,
)
from .guard import (
    GuardOutcome,
    GuardPaths,
    build_guard_script,
    parse_revert_log,
    start_tests_guard,
    stop_tests_guard,
)
from .grader import (
    GradeResult,
    GraderConfig,
    GraderError,
    PytestRunner,
    RunOutcome,
    ScriptedRunner,
    config_from_task,
    decide,
    grade,
    grade_into,
    parse_junit,
)
from .monitor import (
    ABSENT,
    TEST_INFRA_PATHS,
    BackendError,
    ExecBackend,
    ExecResult,
    GitEvidence,
    LocalBackend,
    ManifestDiff,
    MonitorVerdict,
    RepoLayout,
    SandboxBackend,
    build_verdict,
    capture_git_evidence,
    collect_manifests,
    diff_manifests,
    monitor_flagged,
    sha256_text,
    tests_tree_manifest,
)
from .records import (
    CHEAT_LABELS,
    CONDITIONS,
    EVASION_LABELS,
    EVASION_METHODS,
    LABELS,
    SCHEMA_VERSION,
    SPLITS,
    EpisodeRecord,
    RecordInvariantError,
    derive_label,
    read_records_jsonl,
    write_records_jsonl,
)

__all__ = [
    "ABSENT",
    "BackendError",
    "CHEAT_LABELS",
    "CONDITIONS",
    "EVASION_LABELS",
    "EVASION_METHODS",
    "EpisodeRecord",
    "ExecBackend",
    "ExecResult",
    "FileChange",
    "GitEvidence",
    "GradeResult",
    "GraderConfig",
    "GraderError",
    "GuardOutcome",
    "GuardPaths",
    "LABELS",
    "LocalBackend",
    "ManifestDiff",
    "MonitorSignals",
    "MonitorVerdict",
    "PytestRunner",
    "RIGGED_LITERALS",
    "RecordInvariantError",
    "RepoLayout",
    "RunOutcome",
    "SCHEMA_VERSION",
    "SPLITS",
    "SandboxBackend",
    "ScriptedRunner",
    "TEST_INFRA_PATHS",
    "build_guard_script",
    "build_record",
    "build_verdict",
    "capture_git_evidence",
    "classify",
    "classify_static",
    "collect_manifests",
    "config_from_task",
    "decide",
    "derive_label",
    "diff_manifests",
    "extract_features",
    "grade",
    "grade_into",
    "monitor_flagged",
    "parse_junit",
    "parse_revert_log",
    "read_records_jsonl",
    "records_from_log",
    "records_from_paths",
    "sha256_text",
    "start_tests_guard",
    "stop_tests_guard",
    "tests_tree_manifest",
    "write_records",
    "write_records_jsonl",
]
