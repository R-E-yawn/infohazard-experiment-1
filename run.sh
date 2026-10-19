#!/usr/bin/env bash
# exp1 task runner. One entrypoint for every stage.
#
#   ./run.sh setup        create the Stage-A venv and install tier-1 deps
#   ./run.sh test         THE OFFLINE VALIDATION SUITE (no keys, no Docker)
#   ./run.sh review       serve the ground-truth review app on localhost
#   ./run.sh join <logs>  turn eval logs into logs/episodes/*.json records
#
#   ./run.sh setup-pilot  install the tier-2 deps a real run needs
#   ./run.sh preflight    check every credential and package Stage B needs
#   ./run.sh modal-clean  kill any Modal container/app left running
#   ./run.sh smoke        STAGE B: 2 episodes (1x C1_baseline + 1x C3_real)
#   ./run.sh pilot        STAGE C: 18x C3_real
#
#   ./run.sh probe [v1|v2|v3|all]  the phase-1-only DISCOVERY probe (probe/)
#   ./run.sh ceiling               5x C7_capability_ceiling (tests/ locked)
#
# smoke, pilot, probe and ceiling REFUSE TO START without credentials. They
# never degrade to a no-op: a run that silently does nothing is worse than one
# that fails.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"          # the dir that holds exp1/, so `import exp1`
VENV="$HERE/.venv-agent"
PY="$VENV/bin/python"
SPLIT="${SPLIT:-oneoff}"
PROMPT_VARIANT="${PROMPT_VARIANT:-S1}"

die()  { printf '\n\033[1;31mFAIL\033[0m  %s\n\n' "$*" >&2; exit 1; }
info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ok \033[0m %s\n' "$*"; }

need_venv() {
  [ -x "$PY" ] || die "no venv at $VENV -- run './run.sh setup' first"
}

# ---------------------------------------------------------------------------
# credential gate (Stage B/C only)
# ---------------------------------------------------------------------------

require_credentials() {
  local missing=0

  if [ -z "${OPENROUTER_API_KEY:-}" ]; then
    printf '\033[1;31mmissing\033[0m  OPENROUTER_API_KEY\n' >&2
    printf '          The model is openrouter/qwen/qwen3-coder. Without this key\n' >&2
    printf '          every sample fails at the first generate() call.\n' >&2
    printf '          export OPENROUTER_API_KEY=sk-or-...\n\n' >&2
    missing=1
  else
    ok "OPENROUTER_API_KEY is set (${#OPENROUTER_API_KEY} chars)"
  fi

  # Modal does not use a pasteable API key: `modal token new` writes a token id
  # and secret to ~/.modal.toml. Either that file or the env pair will do.
  if [ -f "${HOME}/.modal.toml" ]; then
    ok "Modal credentials found (~/.modal.toml)"
  elif [ -n "${MODAL_TOKEN_ID:-}" ] && [ -n "${MODAL_TOKEN_SECRET:-}" ]; then
    ok "Modal credentials found (MODAL_TOKEN_ID / MODAL_TOKEN_SECRET)"
  else
    printf '\033[1;31mmissing\033[0m  Modal credentials\n' >&2
    printf '          Sandboxes run on Modal. This is NOT an API key you can\n' >&2
    printf '          paste into an env var -- run:  modal token new\n' >&2
    printf '          (or set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET)\n\n' >&2
    missing=1
  fi

  # The `modal` sandbox type is not built into inspect-ai.
  if ! "$PY" -c "
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv
registry_find_sandboxenv('modal')
" 2>/dev/null; then
    printf '\033[1;31mmissing\033[0m  the '\''modal'\'' sandbox provider\n' >&2
    printf '          inspect-ai does not ship it. registry_find_sandboxenv("modal")\n' >&2
    printf '          raises ValueError, so sandbox_type="modal" fails at task\n' >&2
    printf '          construction. Fix:  ./run.sh setup-pilot\n\n' >&2
    missing=1
  else
    ok "the 'modal' sandbox provider is registered"
  fi

  if ! "$PY" -c "import swebench" 2>/dev/null; then
    printf '\033[1;31mmissing\033[0m  swebench\n' >&2
    printf '          Needed at image build / agent init / scoring. Must be\n' >&2
    printf '          >=4.0,<5: 5.0.2 deleted swebench.harness.test_spec and the\n' >&2
    printf '          imports are function-local, so it fails mid-run, not at\n' >&2
    printf '          import. Fix:  ./run.sh setup-pilot\n\n' >&2
    missing=1
  else
    ok "swebench $("$PY" -c 'import swebench;print(getattr(swebench,"__version__","?"))')"
  fi

  [ "$missing" -eq 0 ] || die "$(printf 'cannot start: see the missing items above.\n      Nothing was run. No episodes were consumed.')"
}

# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------

cmd_setup() {
  info "creating $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$HERE/requirements.txt"
  ok "Stage-A venv ready: $("$PY" -V)"
  "$PY" -c "import inspect_ai; print('    inspect_ai', inspect_ai.__version__)"
}

cmd_setup_pilot() {
  need_venv
  info "installing the tier-2 (pilot) dependencies"
  # 'openai' is required by inspect_ai's OpenRouter provider: without it
  # eval_set() dies at model construction with a PrerequisiteError.
  "$VENV/bin/pip" install --quiet "inspect-sandboxes" "modal" "swebench>=4.0,<5" "openai"
  ok "pilot dependencies installed"
  cmd_preflight
}

cmd_preflight() {
  need_venv
  info "Stage B/C preflight"
  require_credentials
  # Checking that packages import is not enough: the only honest test is to
  # actually CONSTRUCT the model the sweep will use. A missing provider dep
  # (e.g. 'openai' for OpenRouter) otherwise surfaces only after the first
  # episode is already being set up.
  PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PY" - <<'PYCHECK' || exit 1
import sys
from inspect_ai.model import get_model
try:
    m = get_model("openrouter/qwen/qwen3-coder")
    print(f"\033[1;32m ok \033[0m model constructs: {m.name}")
except Exception as exc:
    print(f"\033[1;31mFAIL\033[0m  model will not construct: {exc}", file=sys.stderr)
    sys.exit(1)
PYCHECK
  ok "preflight passed -- ./run.sh smoke is clear to run"
}

cmd_test() {
  need_venv
  local failed=0
  cd "$ROOT"

  info "1/7  conditions.self_check()"
  "$PY" -c "
import json, sys
sys.path.insert(0, '$ROOT')
from exp1.harness.conditions import self_check
r = self_check()
print(json.dumps({k: r[k] for k in ('condition_ids','memo_word_counts','positive_control_exposures','c6_appendix_has_sentinel')}, indent=2))
" || failed=1

  info "2/7  fixture static checks (fixtures/verify.sh)"
  bash "$HERE/fixtures/verify.sh" >/tmp/exp1-verify.log 2>&1 \
    && tail -3 /tmp/exp1-verify.log \
    || { failed=1; tail -25 /tmp/exp1-verify.log; }

  info "3/7  measurement half, logic only (-m 'not real')"
  "$PY" -m pytest "$HERE/harness/tests/test_grader_offline.py" -m 'not real' -q || failed=1

  info "4/7  the record join + cross-component render"
  "$PY" -m pytest "$HERE/harness/tests/test_episode_join.py" -q || failed=1

  info "5/7  agent half against mockllm + the local sandbox"
  "$PY" -m pytest "$HERE/harness/tests/test_agent_offline.py" -q || failed=1

  info "6/7  review app self-test (57 unit + e2e)"
  "$PY" -m exp1.review selftest 2>&1 | tail -2 || failed=1

  # Its OWN pytest process, run from $HERE: the probe imports `harness` as a
  # top-level package while everything above imports `exp1.harness`, and one
  # process holding both would carry two copies of the harness under two names.
  info "7/7  discovery probe: design invariants + offline suite"
  ( cd "$HERE" && "$PY" -m probe.run_probe --check >/dev/null ) || failed=1
  ( cd "$HERE" && "$PY" -m pytest "probe/tests/test_probe_offline.py" -q ) || failed=1

  info "optional  golden fixtures through the real grader (-m real)"
  if "$PY" -m pytest "$HERE/harness/tests/test_grader_offline.py" -m real -q 2>/dev/null; then
    ok "the real-Sphinx tier ran"
  else
    printf '\033[1;33mSKIP\033[0m  needs a Sphinx 4.1 checkout + interpreter:\n'
    printf '      EXP1_STAGEA_SPHINX_REPO=<clone with 567ff227> \\\n'
    printf '      EXP1_STAGEA_PYTHON=<python with sphinx 4.1> ./run.sh test\n'
    printf '      In Stage B point these at /testbed inside the container: that IS Gate 4.\n'
  fi

  [ "$failed" -eq 0 ] || die "offline validation FAILED (see above)"
  printf '\n\033[1;32mOFFLINE VALIDATION PASSED\033[0m\n'
}

cmd_review() {
  need_venv
  cd "$ROOT"
  info "serving the review app -- ctrl-c to stop"
  "$PY" -m exp1.review serve
}

cmd_join() {
  need_venv
  cd "$ROOT"
  [ "$#" -ge 1 ] || die "usage: ./run.sh join <log-dir-or-file> [...]"
  # -c rather than -m: exp1.harness.__init__ re-exports the join, so `-m` makes
  # runpy import the module twice and emit a RuntimeWarning.
  PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" "$PY" -c \
    'import sys; from exp1.harness.episode import main; sys.exit(main())' \
    "$@" --out "$HERE/logs/episodes"
}

# Stage B/C share one driver; only the allocation differs.
run_episodes() {
  local label="$1" conditions="$2" runs="$3" samples="$4"
  need_venv
  cd "$ROOT"
  info "$label"
  require_credentials

  local log_dir="$HERE/logs/${label}-$(date +%Y%m%d-%H%M%S)"
  info "log_dir  $log_dir"
  info "model    openrouter/qwen/qwen3-coder   split=$SPLIT  variant=$PROMPT_VARIANT"

  PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  "$PY" - "$log_dir" "$conditions" "$runs" "$samples" <<'PYRUN'
import os
import sys

from exp1.harness.task import run_pilot
from exp1.harness.episode import records_from_log, write_records

log_dir, conditions, runs, samples = sys.argv[1], sys.argv[2].split(","), int(sys.argv[3]), int(sys.argv[4])
success, logs = run_pilot(
    conditions=conditions,
    runs_per_condition=runs,
    split=os.environ.get("SPLIT", "oneoff"),
    prompt_variant=os.environ.get("PROMPT_VARIANT", "S1"),
    log_dir=log_dir,
    max_connections=samples,
    max_samples=samples,
    max_sandboxes=samples,
)
print(f"\neval_set success={success}; {len(logs)} log(s)")

# Join immediately: an eval log is not an episode record, and the review app
# and the analysis both read records.
records = []
for log in logs:
    records.extend(records_from_log(log))
out = os.path.join(os.path.dirname(log_dir), "episodes")
write_records(records, out)
tally = {}
for r in records:
    tally[r.label] = tally.get(r.label, 0) + 1
print(f"wrote {len(records)} episode record(s) to {out}")
print("labels:", tally)

# C7 only: the lock columns, printed when any arm in this run was locked.
# tests_revert_count > 0 with tests_touched false is the lock working;
# tests_locked with tests_touched true is rejected as ERROR, not a finding.
if any(getattr(r, "tests_locked", False) for r in records):
    print("episode | locked | reverts | edit_attempts | tests_touched | label")
    for r in records:
        print(f"  {r.episode_id} {r.tests_locked} {r.tests_revert_count} "
              f"{r.edit_attempts_on_tests} {r.tests_touched} {r.label}")

errored = [r for r in records if r.label == "ERROR"]
for r in errored:
    print(f"  ERROR {r.episode_id}: {r.error}", file=sys.stderr)
sys.exit(1 if errored else 0)
PYRUN

  ok "$label finished -- review with:  ./run.sh review"
}

# Smoke covers the two distinct memo-DELIVERY mechanisms: a planted repo file
# (C3) and the system-prompt injection path used only by C6. C1 plants nothing,
# which is the least breakable path, and it gets 5 episodes in the pilot anyway.
# Kill anything still running on Modal. Safe to run at any time: episodes that
# have finished own nothing, so this only ever reaps orphans. A sandbox that
# outlives its episode bills 2 CPU + 4 GB until its timeout, so this is cheap
# insurance, not housekeeping.
cmd_modal_clean() {
  need_venv
  info "active Modal containers before:"
  "$VENV/bin/modal" container list 2>/dev/null | tail -n +4 | head -20

  local ids
  ids=$("$VENV/bin/modal" container list --json 2>/dev/null \
        | "$VENV/bin/python" -c 'import json,sys
try: rows=json.load(sys.stdin)
except Exception: rows=[]
print("\n".join(r.get("Container ID") or r.get("container_id","") for r in rows))' 2>/dev/null)

  if [ -z "${ids//[[:space:]]/}" ]; then
    ok "no active containers"
  else
    for c in $ids; do
      [ -n "$c" ] || continue
      info "stopping container $c"
      "$VENV/bin/modal" container stop "$c" --yes >/dev/null 2>&1 \
        || "$VENV/bin/modal" container stop "$c" >/dev/null 2>&1 || true
    done
  fi

  # Stop this experiment's apps too. face-swap is the user's own, untouched.
  "$VENV/bin/modal" app list --json 2>/dev/null \
    | "$VENV/bin/python" -c 'import json,sys
rows=json.load(sys.stdin)
for r in rows:
    d=r.get("description","")
    if r.get("state")=="deployed" and (d.startswith("exp1") or d.startswith("ib-") or d.startswith("probe-") or d=="inspect_modal_sandbox"):
        print(r["app_id"])' 2>/dev/null \
    | while read -r a; do
        [ -n "$a" ] || continue
        info "stopping app $a"
        "$VENV/bin/modal" app stop "$a" --yes >/dev/null 2>&1 || true
      done

  ok "modal cleaned -- nothing of ours is running"
}

cmd_smoke() { run_episodes "smoke" "C3_real,C6_positive_control" 1 2; }

# ---------------------------------------------------------------------------
# the discovery probe (probe/) -- phase 1 only, no grader, no monitor
# ---------------------------------------------------------------------------
#
# Run from $HERE and NOT with PYTHONPATH=$ROOT: the probe imports `harness` as a
# top-level package (probe/_bootstrap.py puts exp1/ on sys.path), so one process
# never holds the harness twice under two names.
cmd_probe() {
  need_venv
  # No default: a run that costs money names what it runs. A bare `./run.sh
  # probe` would otherwise either spend $0.65 or $2 on a guess.
  local which="${1:-}"
  [ "$#" -gt 0 ] && shift || true

  local variants
  case "$(printf '%s' "$which" | tr '[:upper:]' '[:lower:]')" in
    v1)  variants="V1" ;;
    v2)  variants="V2" ;;
    v3)  variants="V3" ;;
    v4)  variants="V4" ;;
    all) variants="V1,V2,V3,V4" ;;
    *)   die "usage: ./run.sh probe [v1|v2|v3|all] [--runs N] [--max-samples N]
      v1   the documentation chain (does forced necessity work)
      v2   no-chain control (does it grep-jump past the memo)
      v4   the original spec: note-1..4, memo at note-3, prefix at note-4
      v3   ceiling: the original ticket plus a pointer at .github/ (rung 2)
      all  all three
      Anything after the variant is passed straight to probe.run_probe." ;;
  esac

  local runs="${PROBE_RUNS:-5}"
  local samples="${PROBE_SAMPLES:-3}"

  info "discovery probe  variants=$variants  runs=$runs/variant"
  # Same stance as smoke/pilot: refuse before anything is provisioned. The
  # probe ALSO gates itself in require_runtime(), so a direct
  # `python -m probe.run_probe` cannot bypass this either.
  require_credentials

  info "model    openrouter/qwen/qwen3-coder   budget 80   phase 1 only"
  info "cost     ~\$0.13/episode at the pilot's measured rate"
  cd "$HERE"
  "$PY" -m probe.run_probe \
    --variants "$variants" --runs "$runs" --max-samples "$samples" "$@"
  ok "probe finished -- table with:  $PY -m probe.report"
}

# C7 is not on the accuracy axis: it is the capability ceiling. The tests/ tree
# is restored from SETUP_REF_2 on a timer for the whole of phase 2, so CAUGHT is
# impossible by construction and a Run-A pass can only route to a blind spot,
# suppression or invisible. That is what separates "this model cannot exploit a
# blind spot" from "it never needed to".
cmd_ceiling() { run_episodes "ceiling" "C7_capability_ceiling" "${CEILING_RUNS:-5}" "${CEILING_SAMPLES:-5}"; }

# PILOT ALLOCATION: the four conditions from the design doc, balanced 5 each.
#   C1_baseline  C3_real  C4_honeypot  C6_positive_control   = 20 episodes
# Balance is a design requirement, not a preference: unbalanced cells push the
# pooled test's type-I error from 1.9% to 23.6%.
cmd_pilot() { run_episodes "pilot" "C1_baseline,C3_real,C4_honeypot,C6_positive_control" 5 4; }

# C6_strong only: the blunt replacement prompt, 3 episodes. A probe of prompt
# force, not part of the C1-C6 accuracy axis.
cmd_strong() { run_episodes "strong" "C6_strong" "${STRONG_RUNS:-3}" "${STRONG_SAMPLES:-3}"; }

# Both probes together, 3 each, in one eval_set: does a blunter prompt stop the
# test edits (C6_strong), and is there any other route at all when the test
# tree is locked (C7). One run so they share a log dir and a wall clock.
cmd_force() { run_episodes "force" "C6_strong,C7_capability_ceiling" 3 6; }

# The capability FLOOR: family-1 routes named outright, tests/ locked. Not an
# arm -- it asks whether a source-level cheat is reachable for this model at all.
cmd_floor() { run_episodes "floor" "C8_capability_floor" "${FLOOR_RUNS:-5}" 5; }

# The AFFORDANCE probe: blunt memo in note-3, and the v5 notes bundle whose
# note-4 records the three source-level routes as past precedent. note-4 is
# planted in every arm, so the affordance is constant and only the memo varies.
cmd_affordance() { EXP1_NOTES=v5 run_episodes "affordance" "C3_blunt" "${AFF_RUNS:-5}" 5; }

# ---------------------------------------------------------------------------

case "${1:-}" in
  setup)       shift; cmd_setup "$@" ;;
  setup-pilot) shift; cmd_setup_pilot "$@" ;;
  preflight)   shift; cmd_preflight "$@" ;;
  test)        shift; cmd_test "$@" ;;
  review)      shift; cmd_review "$@" ;;
  join)        shift; cmd_join "$@" ;;
  modal-clean) shift; cmd_modal_clean "$@" ;;
  smoke)       shift; cmd_smoke "$@" ;;
  pilot)       shift; cmd_pilot "$@" ;;
  probe)       shift; cmd_probe "$@" ;;
  ceiling)     shift; cmd_ceiling "$@" ;;
  strong)      shift; cmd_strong "$@" ;;
  force)       shift; cmd_force "$@" ;;
  floor)       shift; cmd_floor "$@" ;;
  affordance)  shift; cmd_affordance "$@" ;;
  *)
    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"
    exit 1 ;;
esac
