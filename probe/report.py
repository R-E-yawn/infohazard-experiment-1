"""The probe's report: variant x outcome, with Wilson 95% intervals.

    .venv-agent/bin/python -m probe.report                 # the newest run
    .venv-agent/bin/python -m probe.report probe/results/probe-20261012-193000
    .venv-agent/bin/python -m probe.report --all            # pool every run

Why Wilson and not the textbook normal interval: at n=5 the probe's whole job is
to tell 0/5 apart from 5/5, and the normal approximation returns a zero-width
interval at both ends -- "0% +/- 0%" from five episodes, which is the one claim
the data cannot support. Wilson is bounded, never degenerate, and is what the
pre-registration uses, so probe and pilot numbers are read the same way.

Runs are NEVER pooled across ``design_sha256``. Two records whose designs differ
by one byte of a planted note are measuring different environments, and silently
averaging them is how a probe talks you into the wrong redesign; the report
prints them as separate rows and says so.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

from . import _bootstrap  # noqa: F401  (puts exp1/ on sys.path)

RESULTS_DIR: Final[Path] = _bootstrap.PROBE_DIR / "results"

#: 1.96 -- the two-sided 95% normal quantile.
Z95: Final[float] = 1.959963984540054


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float, float]:
    """Wilson score interval. Returns ``(p_hat, low, high)``.

    ``n == 0`` gives ``(0.0, 0.0, 1.0)``: no episodes is no information, which is
    the honest interval rather than a divide-by-zero or a false zero.
    """
    if n <= 0:
        return 0.0, 0.0, 1.0
    if successes < 0 or successes > n:
        raise ValueError(f"successes={successes} out of range for n={n}")
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, centre - half), min(1.0, centre + half)


def fmt_rate(successes: int, n: int) -> str:
    """``3/5  60%  [23-88%]`` -- the count first, because n=5."""
    p, low, high = wilson(successes, n)
    return f"{successes}/{n} {p:>5.0%} [{low:>3.0%}-{high:>3.0%}]"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Load probe records from any mix of files and directories."""
    records: list[dict[str, Any]] = []
    for path in paths:
        if path.is_dir():
            files: Iterable[Path] = sorted(path.glob("*.json"))
        else:
            files = [path]
        for file in files:
            if file.name == "manifest.json":
                continue
            data = json.loads(file.read_text())
            if isinstance(data, dict) and "variant" in data:
                records.append(data)
    return records


def newest_run_dir(base: Path = RESULTS_DIR) -> Path | None:
    """The most recent run directory, ignoring parked ones.

    A leading underscore means "parked" -- the same convention ``exp1/logs/``
    already uses for ``_pilot1`` and ``_smoke_run2``. Parked runs are still
    readable by naming them explicitly; they just never become the default,
    so a one-off smoke cannot be mistaken for the current sweep.
    """
    candidates = [
        p
        for p in base.glob("*")
        if p.is_dir() and not p.name.startswith("_") and any(p.glob("*.json"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class VariantSummary:
    """One row of the report."""

    variant: str
    design_sha256: str
    question: str
    n: int
    errored: int
    memo_read: int
    memo_named: int
    constant_found: int
    turns_to_memo: list[int]
    read_orders: dict[tuple[str, ...], int]
    exit_reasons: dict[str, int]
    flagged: int
    #: Read the constant but never the memo: the chain delivered the value and
    #: the agent never saw the page it was on. V1's specific failure mode.
    constant_without_memo: int

    @property
    def median_turns_to_memo(self) -> float | None:
        return statistics.median(self.turns_to_memo) if self.turns_to_memo else None


def summarise(records: Sequence[dict[str, Any]]) -> list[VariantSummary]:
    """Group records by (variant, design hash) and reduce each group to a row."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (str(record.get("variant", "?")), str(record.get("design_sha256", "")))
        groups.setdefault(key, []).append(record)

    rows: list[VariantSummary] = []
    for (variant, design), group in sorted(groups.items()):
        orders: dict[tuple[str, ...], int] = {}
        for record in group:
            order = tuple(record.get("files_read_in_order") or [])
            orders[order] = orders.get(order, 0) + 1
        exits: dict[str, int] = {}
        for record in group:
            reason = str(record.get("exit_reason") or "?")
            exits[reason] = exits.get(reason, 0) + 1
        turns = [
            int(record["memo_exposure_turn"])
            for record in group
            if record.get("memo_exposed") and record.get("memo_exposure_turn") is not None
        ]
        rows.append(
            VariantSummary(
                variant=variant,
                design_sha256=design,
                question=str(next((r.get("variant_question") or "" for r in group), "")),
                n=len(group),
                errored=sum(1 for r in group if r.get("error")),
                memo_read=sum(1 for r in group if r.get("memo_exposed")),
                memo_named=sum(1 for r in group if r.get("memo_path_in_command")),
                constant_found=sum(1 for r in group if r.get("constant_found")),
                turns_to_memo=turns,
                read_orders=orders,
                exit_reasons=exits,
                flagged=sum(1 for r in group if r.get("flag_fired")),
                constant_without_memo=sum(
                    1
                    for r in group
                    if r.get("constant_found") and not r.get("memo_exposed")
                ),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_SHORT: Final[dict[str, str]] = {
    "doc/internals/build-pipeline.md": "build",
    "doc/internals/css-and-themes.md": "css",
    "doc/internals/infra-notes.md": "INFRA*",
    "doc/internals/rendering-conventions.md": "render",
    ".github/workflows/README.md": "INFRA*",
}


def short(path: str) -> str:
    """Abbreviate a planted path; ``*`` marks the file carrying the memo."""
    return _SHORT.get(path, path.rsplit("/", 1)[-1])


def print_report(records: Sequence[Any], *, out=None) -> list[VariantSummary]:
    """Print the variant x outcome table. Accepts records or dicts."""
    stream = out or sys.stdout
    dicts = [
        r if isinstance(r, dict) else _as_dict(r)
        for r in records
    ]
    rows = summarise(dicts)

    def w(line: str = "") -> None:
        print(line, file=stream)

    w()
    w("=" * 92)
    w("DISCOVERY PROBE -- phase 1 only; the measured event is "
      "'the sentinel appeared in a tool result'")
    w("=" * 92)
    if not rows:
        w("no records")
        return rows

    # A mock run proves the plumbing and measures nothing about the model. Say so
    # in the report rather than letting a 5/5 from mockllm be read as a result.
    mocked = sorted({str(r.get("model", "")) for r in dicts if "mock" in str(r.get("model", "")).lower()})
    if mocked:
        w()
        w("!! THESE ARE NOT RESULTS: the records below include a scripted mock "
          f"model ({', '.join(mocked)}).")
        w("!! A mock run exercises the plumbing on a hand-written discovery path.")

    w()
    w(f"{'variant':<8} {'n':>3}  {'memo read':<22} {'constant found':<22} "
      f"{'median turn->memo':>17}")
    w("-" * 92)
    for row in rows:
        median = row.median_turns_to_memo
        w(
            f"{row.variant:<8} {row.n:>3}  "
            f"{fmt_rate(row.memo_read, row.n):<22} "
            f"{fmt_rate(row.constant_found, row.n):<22} "
            f"{('-' if median is None else f'{median:.1f}'):>17}"
        )
    w()
    w("rates are Wilson 95% intervals; 'turn' is the tool-call index at which the")
    w("sentinel first appeared in a tool result.")

    for row in rows:
        w()
        w(f"--- {row.variant} -- {row.question}")
        w(f"    design {row.design_sha256[:12]}   episodes {row.n}"
          f"   errored {row.errored}   flagged {row.flagged}")
        w(f"    named the memo path in a command: {fmt_rate(row.memo_named, row.n)}")
        if row.constant_without_memo:
            w(f"    !! constant found WITHOUT reading the memo: "
              f"{row.constant_without_memo}/{row.n} -- the value was grepped out "
              f"and the page was never read")
        w("    planted files read, in order:")
        for order, count in sorted(
            row.read_orders.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            shown = " -> ".join(short(p) for p in order) if order else "(none)"
            w(f"      {count:>3}x  {shown}")
        exits = ", ".join(
            f"{reason}={count}"
            for reason, count in sorted(row.exit_reasons.items(), key=lambda kv: -kv[1])
        )
        w(f"    exit reasons: {exits}")
    w()
    return rows


def _as_dict(record: Any) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    raise TypeError(f"cannot read a probe record out of {type(record)!r}")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    pool_all = "--all" in args
    args = [a for a in args if a != "--all"]

    if args:
        paths = [Path(a) for a in args]
    elif pool_all:
        paths = [RESULTS_DIR]
        paths += [p for p in RESULTS_DIR.glob("*") if p.is_dir()]
    else:
        newest = newest_run_dir()
        if newest is None:
            print(f"no probe results under {RESULTS_DIR}", file=sys.stderr)
            return 1
        print(f"newest run: {newest}")
        paths = [newest]

    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"no such path(s): {missing}", file=sys.stderr)
        return 1

    records = load_records(paths)
    if not records:
        print(f"no probe records found in {[str(p) for p in paths]}", file=sys.stderr)
        return 1
    print_report(records)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
