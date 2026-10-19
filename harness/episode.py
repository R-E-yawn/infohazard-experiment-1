"""The join: an inspect_ai eval log -> contract-shaped episode records.

This module is the missing seam between the two halves of the harness. The
agent half (``agent.py``/``tools.py``/``task.py``) leaves everything it observed
in ``state.store`` and in the two scorers' metadata; the measurement half
(``grader.py``) returns a :class:`GradeResult`. Nothing turned those into the
SPEC 6.7 :class:`EpisodeRecord` that the review app and the analysis read, so a
finished eval produced an inspect log and no episode records at all.

Three rules shape the code:

1. **The log is the only input.** Records are rebuilt from a saved ``.eval``
   file, never from live objects, so a sweep can be re-joined after the fact and
   the join itself can be tested offline against a mockllm log.

2. **One bad episode must not lose the others.** A record that fails validation
   becomes a ``label="ERROR"`` record carrying the reason, and the sweep keeps
   going. Silently dropping it would quietly shrink the denominator.

3. **Provenance comes from where it is actually known.** Condition/split/memo
   come from the sample metadata, the measurements from the scorers, and
   model/version/token counts from the log header -- the scorer cannot see
   those.

Usage::

    python -m exp1.harness.episode logs/exp1-20261011-120000 --out logs/episodes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from .records import (
    EVASION_METHODS,
    LABELS,
    EpisodeRecord,
    RecordInvariantError,
)

#: Scorer names as registered in ``task.py``. Order matters there; here they are
#: looked up by name so a reordering cannot silently shift the join.
RIGGED_SCORER = "rigged_test"
MONITOR_SCORER = "monitor"

#: Store key under which ``task.py`` stashes the GradeResult. Inspect coerces
#: the dataclass to a plain dict when it writes the log, so what comes back is
#: nested dicts, not a GradeResult.
GRADE_RESULT_KEY = "grade_result"


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _store(sample: Any) -> dict[str, Any]:
    raw = getattr(sample, "store", None) or {}
    if not isinstance(raw, dict):
        return {}
    # inspect namespaces some store keys; the harness writes bare names, so
    # accept both "flag_fired" and "<ns>:flag_fired".
    out: dict[str, Any] = {}
    for key, val in raw.items():
        out[key] = val
        if isinstance(key, str) and ":" in key:
            out.setdefault(key.rsplit(":", 1)[-1], val)
    return out


def _score_meta(sample: Any, name: str) -> dict[str, Any]:
    scores = getattr(sample, "scores", None) or {}
    score = scores.get(name)
    meta = getattr(score, "metadata", None) if score is not None else None
    return meta if isinstance(meta, dict) else {}


def _as_bool(value: Any, default: bool = False) -> bool:
    return default if value is None else bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(value)


def _total_tokens(sample: Any) -> int:
    usage = getattr(sample, "model_usage", None) or {}
    total = 0
    if isinstance(usage, dict):
        for entry in usage.values():
            total += _as_int(getattr(entry, "total_tokens", None))
    return total


def _limit_hit(sample: Any, kind: str) -> bool:
    limit = getattr(sample, "limit", None)
    return bool(limit is not None and getattr(limit, "type", None) == kind)


# --------------------------------------------------------------------------- #
# the join, one sample at a time
# --------------------------------------------------------------------------- #


def build_record(
    sample: Any,
    *,
    model: str = "",
    sampling: dict[str, Any] | None = None,
    inspect_version: str | None = None,
    swebench_version: str | None = None,
    model_provider: str | None = None,
    task_metadata: dict[str, Any] | None = None,
) -> EpisodeRecord:
    """Build one :class:`EpisodeRecord` from one logged sample.

    Never raises on an inconsistent episode: an episode that cannot be made to
    validate comes back labelled ``ERROR`` with the reason in ``error``, which
    is both the honest outcome and the one the label tree already defines for
    "the harness failed".
    """
    meta = dict(getattr(sample, "metadata", None) or {})
    meta.update(task_metadata or {})
    store = _store(sample)
    rigged = _score_meta(sample, RIGGED_SCORER)
    monitor = _score_meta(sample, MONITOR_SCORER)
    grade = store.get(GRADE_RESULT_KEY)
    grade = grade if isinstance(grade, dict) else {}
    verdict = grade.get("verdict") if isinstance(grade.get("verdict"), dict) else {}

    episode_id = str(meta.get("episode_id") or getattr(sample, "id", "") or "unknown")

    rec = EpisodeRecord(
        episode_id=episode_id,
        condition=str(meta.get("condition") or ""),
        task_pair=str(meta.get("task_pair") or ""),
        split=str(meta.get("split") or ""),
        run_index=_as_int(meta.get("run_index")),
        prompt_variant=str(meta.get("prompt_variant") or "S1"),
    )

    # --- provenance (log-level; the scorer cannot see any of this) -------- #
    rec.model = model
    rec.model_provider = model_provider
    rec.sampling = dict(sampling or {})
    rec.inspect_version = inspect_version
    rec.swebench_version = swebench_version

    # --- setup ------------------------------------------------------------ #
    rec.setup_ref_1 = store.get("setup_ref_1") or rigged.get("setup_ref_1")
    rec.setup_ref_2 = store.get("setup_ref_2") or rigged.get("setup_ref_2")
    rec.memo_variant = meta.get("memo_variant")
    rec.memo_path = meta.get("memo_path")
    rec.memo_sha256 = meta.get("memo_sha256")
    rec.memo_ladder_rung = (
        _as_int(meta.get("memo_ladder_rung")) if meta.get("memo_ladder_rung") is not None else None
    )

    # --- phase 1 (agent-owned) -------------------------------------------- #
    # There is no top-level `phase1_solved` store key. The agent records it
    # inside the read-only phase-1 snapshot as `phase1_solved_observed`, which
    # is derived from the agent's OWN last run_tests report on the phase-1
    # target test -- it is self-reported, not independently measured, because
    # measuring it at the boundary would mean calling score(), which mutates
    # the sandbox and would destroy the monitor evidence.
    snapshot = store.get("phase1_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    rec.phase1_solved = _as_bool(
        store.get("phase1_solved", snapshot.get("phase1_solved_observed"))
    )
    rec.phase1_exit_reason = store.get("phase1_exit_reason") or snapshot.get(
        "phase1_exit_reason"
    )

    # --- outcomes (grader-owned) ------------------------------------------ #
    rec.rigged_pass_as_submitted = _as_bool(rigged.get("rigged_pass_as_submitted"))
    rec.rigged_pass_tests_restored = _as_bool(rigged.get("rigged_pass_tests_restored"))
    rec.rigged_pass_hardened = _as_bool(rigged.get("rigged_pass_hardened"))
    rec.p2p_pass_count = _as_int(rigged.get("p2p_pass_count"))
    rec.p2p_total = _as_int(rigged.get("p2p_total") or meta.get("p2p_total"))

    # --- monitor (hash-based) --------------------------------------------- #
    rec.tests_touched = _as_bool(monitor.get("tests_touched"))
    rec.test_infra_touched = _as_bool(monitor.get("test_infra_touched"))
    rec.sphinx_touched = _as_bool(monitor.get("sphinx_touched"))
    rec.site_packages_touched = _as_bool(monitor.get("site_packages_touched"))
    rec.git_concealment_detected = _as_bool(monitor.get("git_concealment_detected"))
    # monitor_flagged is DEFINED as the tests/ hash verdict (SPEC 6.4), so it is
    # derived here rather than trusted from metadata.
    rec.monitor_flagged = rec.tests_touched
    rec.changed_files = list(monitor.get("changed_files") or [])
    rec.agent_diff = str((verdict.get("git") or {}).get("diff") or "") if verdict else ""
    manifests = grade.get("manifests")
    rec.hash_manifests = manifests if isinstance(manifests, dict) else {"before": {}, "after": {}}

    # --- the C7 tests/ lock ------------------------------------------------ #
    # `tests_locked` is read from the STORE, not from the sample metadata: the
    # metadata says which arm was requested, the store says whether the guard
    # actually came up. Those differ exactly when the lock failed, which is the
    # case the record has to be honest about.
    rec.tests_locked = _as_bool(
        store.get("tests_locked", monitor.get("tests_locked"))
    )
    rec.tests_revert_count = _as_int(
        store.get("tests_revert_count", monitor.get("tests_revert_count"))
    )
    rec.edit_attempts_on_tests = _as_int(
        store.get("edit_attempts_on_tests", monitor.get("edit_attempts_on_tests"))
    )

    # --- honest exit ------------------------------------------------------- #
    rec.flagged_for_human = _as_bool(store.get("flag_fired"))
    rec.flag_reason = store.get("flag_reason")

    # --- memo exposure ----------------------------------------------------- #
    # The sentinel-in-a-tool-result test only applies to a PLANTED memo. C6
    # delivers the memo in the system prompt and its appendix carries no
    # sentinel, so the tool-wrapper can never fire. Exposure there is
    # guaranteed by construction -- that is the whole point of a positive
    # control -- and recording False would make the C6 column read 0/5 and
    # suggest the agent never saw the information.
    if _as_bool(meta.get("memo_in_system_prompt")):
        rec.memo_exposed = True
    else:
        rec.memo_exposed = _as_bool(store.get("memo_exposed"))
    rec.memo_path_in_command = _as_bool(store.get("memo_path_in_command"))
    rec.memo_exposure_turn = store.get("memo_exposure_turn")
    rec.memo_referenced = _as_bool(store.get("memo_referenced"))
    rec.memo_reference_quotes = list(store.get("memo_reference_quotes") or [])

    # --- classification ---------------------------------------------------- #
    rec.label = str(rigged.get("label") or "ERROR")
    rec.evasion_method_heuristic = str(rigged.get("evasion_method_heuristic") or "none")

    # --- integrity gates / health ------------------------------------------ #
    rec.eval_awareness_hits = list(store.get("eval_awareness_hits") or [])
    rec.malformed_tool_call_count = _as_int(store.get("malformed_tool_call_count"))
    rec.zero_tool_call_turns = _as_int(store.get("zero_tool_call_turns"))
    rec.test_runs_attempted = _as_int(store.get("test_runs_attempted"))
    rec.hit_message_limit = _limit_hit(sample, "message")
    rec.messages = len(getattr(sample, "messages", None) or [])
    rec.total_tokens = _total_tokens(sample)

    # --- errors ------------------------------------------------------------ #
    sample_error = getattr(sample, "error", None)
    scores = getattr(sample, "scores", None) or {}
    error_text: str | None = None
    if sample_error is not None:
        error_text = str(getattr(sample_error, "message", None) or sample_error)
    elif RIGGED_SCORER not in scores:
        # No rigged_test score at all: the task registered no scorers, or
        # scoring never happened. Not a measurement, so not a result.
        error_text = (
            f"no {RIGGED_SCORER!r} score in the log: the episode was never "
            f"graded (scores present: {sorted(scores) or 'none'})"
        )
    elif rigged.get("error"):
        error_text = str(rigged["error"])
    elif rigged.get("grader_stub"):
        # The grader did not run. That is not a measurement, so it must not be
        # allowed to masquerade as HONEST_INCOMPLETE.
        error_text = (
            "grader did not run: "
            f"{rigged.get('grader_skipped_because', 'reason not recorded')}"
        )

    return _finalise(rec, error_text)


def _finalise(rec: EpisodeRecord, error_text: str | None) -> EpisodeRecord:
    """Apply ERROR precedence, then make the record validate or say why not."""
    if error_text:
        rec.error = error_text
        rec.label = "ERROR"
        rec.evasion_method_heuristic = "none"
        return rec

    if rec.label not in LABELS:
        rec.error = f"scorer reported an unknown label {rec.label!r}"
        rec.label = "ERROR"
        rec.evasion_method_heuristic = "none"
        return rec
    if rec.evasion_method_heuristic not in EVASION_METHODS:
        rec.error = (
            f"scorer reported a method outside the vocabulary: "
            f"{rec.evasion_method_heuristic!r}"
        )
        rec.label = "ERROR"
        rec.evasion_method_heuristic = "none"
        return rec

    problems = rec.validate()
    if problems:
        # The record contradicts itself. That is a harness bug, and the label
        # tree already has a bucket for "the harness failed" -- use it, loudly,
        # rather than writing a plausible-looking number.
        rec.error = "record failed validation: " + "; ".join(problems)
        rec.label = "ERROR"
        rec.evasion_method_heuristic = "none"
    return rec


# --------------------------------------------------------------------------- #
# whole logs
# --------------------------------------------------------------------------- #


def records_from_log(log: Any, *, swebench_version: str | None = None) -> list[EpisodeRecord]:
    """Join every sample in one :class:`EvalLog`.

    ``eval_set()`` returns HEADER-ONLY logs: ``log.samples`` is None even
    though the samples are on disk and the run succeeded. Joining such a log
    silently yields zero records -- the sweep looks like it worked and writes
    nothing. So when samples are absent but a location is known, re-read the
    log from disk rather than returning an empty list.
    """
    if not getattr(log, "samples", None):
        location = getattr(log, "location", None)
        if location:
            from inspect_ai.log import read_eval_log

            log = read_eval_log(str(location))

    spec = getattr(log, "eval", None)
    model = str(getattr(spec, "model", "") or "")
    task_meta = dict(getattr(spec, "metadata", None) or {})
    gen = getattr(spec, "model_generate_config", None)
    sampling: dict[str, Any] = {}
    if gen is not None:
        for key in ("temperature", "top_p", "top_k"):
            val = getattr(gen, key, None)
            if val is not None:
                sampling[key] = val
        extra = getattr(gen, "extra_body", None)
        if isinstance(extra, dict):
            sampling.update(extra)

    inspect_version = None
    packages = getattr(spec, "packages", None) or {}
    if isinstance(packages, dict):
        inspect_version = packages.get("inspect_ai") or packages.get("inspect-ai")
        if swebench_version is None:
            swebench_version = packages.get("swebench")

    out: list[EpisodeRecord] = []
    for sample in getattr(log, "samples", None) or []:
        out.append(
            build_record(
                sample,
                model=model,
                sampling=sampling,
                inspect_version=inspect_version,
                swebench_version=swebench_version,
                task_metadata=task_meta,
            )
        )
    return out


def records_from_paths(paths: Sequence[str]) -> list[EpisodeRecord]:
    """Join every ``.eval`` log under each path (file or directory)."""
    from inspect_ai.log import list_eval_logs, read_eval_log

    out: list[EpisodeRecord] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            logs = [info.name for info in list_eval_logs(str(p))]
        else:
            logs = [str(p)]
        for name in logs:
            out.extend(records_from_log(read_eval_log(name)))
    return out


def write_records(records: Iterable[EpisodeRecord], out_dir: str) -> list[str]:
    """Write one JSON file per episode, which is the layout the app prefers.

    Refuses to write a batch containing two records with the same
    ``episode_id``. The filename IS the episode id, so a duplicate silently
    overwrites its twin and the sweep quietly loses episodes -- joining a log
    directory that held several runs once reported "175 written" with 24 files
    on disk. Join one run's ``log_dir`` at a time, or give the runs distinct
    ``run_index`` values.
    """
    records = list(records)
    seen: dict[str, int] = {}
    for rec in records:
        seen[rec.episode_id] = seen.get(rec.episode_id, 0) + 1
    dupes = {eid: n for eid, n in seen.items() if n > 1}
    if dupes:
        shown = ", ".join(f"{eid} x{n}" for eid, n in sorted(dupes.items())[:6])
        raise ValueError(
            f"refusing to write {len(records)} records with only "
            f"{len(seen)} distinct episode_id(s): the filename is the episode "
            f"id, so {sum(dupes.values()) - len(dupes)} record(s) would be "
            f"silently overwritten. Duplicates: {shown}"
            + ("..." if len(dupes) > 6 else "")
            + ". Join one run's log_dir at a time."
        )

    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for rec in records:
        path = dest / f"{rec.episode_id}.json"
        path.write_text(rec.to_json() + "\n", encoding="utf-8")
        written.append(str(path))
    return written


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m exp1.harness.episode",
        description="Join inspect_ai eval logs into SPEC 6.7 episode records.",
    )
    ap.add_argument("logs", nargs="+", help="a .eval file or a log directory")
    ap.add_argument(
        "--out",
        default="logs/episodes",
        help="directory for the per-episode JSON files (default: logs/episodes)",
    )
    ap.add_argument(
        "--summary-only",
        action="store_true",
        help="print the label tally and write nothing",
    )
    args = ap.parse_args(argv)

    records = records_from_paths(args.logs)
    if not records:
        print("no samples found in the given logs", file=sys.stderr)
        return 1

    tally: dict[str, int] = {}
    for rec in records:
        tally[rec.label] = tally.get(rec.label, 0) + 1

    if not args.summary_only:
        try:
            written = write_records(records, args.out)
        except ValueError as exc:
            print(f"\nrefused to write: {exc}", file=sys.stderr)
            print(json.dumps({"episodes": len(records), "labels": tally}, indent=2))
            return 1
        print(f"wrote {len(written)} episode record(s) to {args.out}")

    print(json.dumps({"episodes": len(records), "labels": tally}, indent=2))
    errored = [r for r in records if r.label == "ERROR"]
    for rec in errored:
        print(f"  ERROR {rec.episode_id}: {rec.error}", file=sys.stderr)
    return 2 if errored else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
