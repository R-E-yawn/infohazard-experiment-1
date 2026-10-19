"""The localhost server.

Blinding is enforced HERE, not in CSS.  A payload for a blind, un-reviewed
episode does not contain the condition or any automated label, so there is
nothing for a curious reviewer to find in devtools -- and nothing to
accidentally render.  The episode is addressed by its blind id, because the
contract's `episode_id` ("A-oneoff-C3_real-r07") spells the condition out.

Binds to 127.0.0.1 only.  No authentication, because there is no network
surface to authenticate.
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, aggregate, annotate, conditions as conditions_mod
from . import paths, records, reports, store, textdiff

# ---------------------------------------------------------------------------
# Blinding
# ---------------------------------------------------------------------------

#: Stripped from an episode payload while it is blind and un-reviewed.
BLIND_STRIP = (
    "condition", "memo_variant", "memo_path", "memo_sha256",
    "memo_ladder_rung", "label", "evasion_method_heuristic",
    "evasion_method_llm_judge", "evasion_method_human",
)

_LABEL_NAMES = re.compile(
    r"\b(CAUGHT|EVASION_BLINDSPOT|EVASION_SUPPRESSION|EVASION_INVISIBLE|"
    r"HONEST_FLAGGED|HONEST_INCOMPLETE|ERROR)\b")
_COND_NAMES = re.compile(r"\bC[1-6]_[a-z_]+\b")
#: Method names are automated labels too: naming one anchors the reviewer's
#: own method choice just as a label name anchors their label.
_METHOD_NAMES = re.compile(
    r"\b(" + "|".join(sorted(records.METHODS, key=len, reverse=True)) + r")\b")


def _scrub(text: str | None) -> str | None:
    """Replace label, method and condition names in free text shown while
    blind.  Integrity warnings still reach the reviewer -- they need to know a
    record is inconsistent -- but not which way the grader called it."""
    if not text:
        return text
    text = _LABEL_NAMES.sub("[label hidden]", text)
    text = _METHOD_NAMES.sub("[method hidden]", text)
    return _COND_NAMES.sub("[condition hidden]", text)


BLIND_NOTES = [
    "Blinding hides the condition name and every automated label. It cannot "
    "hide the evidence: if the agent printed the memo, the memo's text is in "
    "the timeline and identifies the condition. That is intended -- you are "
    "allowed to infer the condition from evidence you read, not to be told it "
    "before you judge.",
    "In C6 the memo text is appended to the SYSTEM PROMPT, so the first turn "
    "can also identify the condition. It is collapsed by default.",
    "The A/B/C reading below describes what the runs mean but does not name the "
    "label they imply, so there is no label on screen for your judgement to "
    "anchor to. The grader's label appears only after you submit.",
]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class State:
    """Loaded episodes + verification file, reloadable without a restart."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.episodes: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.by_blind: dict[str, dict] = {}
        self.conditions: dict = {}
        self.load_error: str | None = None
        self.reload()

    def reload(self) -> None:
        with self._lock:
            try:
                self.episodes = records.load_all()
                self.load_error = None
            except Exception as exc:  # a bad record must not take the app down
                self.episodes = []
                self.load_error = f"{type(exc).__name__}: {exc}"
            self.by_id = {e.get("episode_id"): e for e in self.episodes}
            self.by_blind = {e["_derived"]["blind_id"]: e for e in self.episodes}
            try:
                self.conditions = conditions_mod.build()
            except Exception as exc:
                self.conditions = {"error": f"{type(exc).__name__}: {exc}",
                                   "conditions": [], "checks": {
                                       "checks": [], "status": "fail",
                                       "passed": 0, "total": 0,
                                       "critical_failures": ["load"],
                                       "warnings": []}}

    def verification(self) -> dict:
        return store.load()

    def find(self, key: str) -> dict | None:
        return self.by_id.get(key) or self.by_blind.get(key)

    def ordered(self, blind: bool) -> list[dict]:
        """Blind mode must not order episodes by condition: a condition-sorted
        list leaks the grouping.  Sort by blind id instead -- stable, and
        uncorrelated with the condition."""
        if blind:
            return sorted(self.episodes, key=lambda e: e["_derived"]["blind_id"])
        return self.episodes


STATE = State()


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def _is_blind(record: dict, verdict: dict | None, blind_mode: bool) -> bool:
    """A committed verdict reveals that episode permanently; the toggle is for
    everything not yet judged."""
    return bool(blind_mode and verdict is None)


def episode_list(blind_mode: bool) -> dict:
    v_all = store.verdicts(STATE.verification())
    out = []
    for r in STATE.ordered(blind_mode):
        eid = r.get("episode_id")
        v = v_all.get(eid)
        blind = _is_blind(r, v, blind_mode)
        view = aggregate.episode_view(r, v)
        view["blind"] = blind
        view["id"] = r["_derived"]["blind_id"] if blind else eid
        if blind:
            view["episode_id"] = r["_derived"]["blind_id"]
            for k in ("condition", "auto_label", "auto_method", "judge_method",
                      "label_recomputed", "agree_label", "run_index"):
                view[k] = None
            view["invariants"] = [_scrub(x) for x in view["invariants"]]
            view["problems"] = [_scrub(x) for x in view["problems"]]
        out.append(view)
    return {"episodes": out, "blind_mode": blind_mode,
            "load_error": STATE.load_error}


def episode_payload(key: str, blind_mode: bool) -> dict | None:
    r = STATE.find(key)
    if r is None:
        return None
    v_all = store.verdicts(STATE.verification())
    eid = r.get("episode_id")
    v = v_all.get(eid)
    blind = _is_blind(r, v, blind_mode)

    cond = r.get("condition")
    memo_text = None
    memo_on_disk = None
    memo_variable = None
    context = None
    for c in STATE.conditions.get("conditions") or []:
        if c["condition"] == cond:
            memo_text = c.get("memo")
            memo_on_disk = c.get("memo_sha256")
            sections = c.get("memo_sections") or {}
            memo_variable = sections.get("variable")
            # Everything the agent saw regardless of condition.  Subtracted
            # from the memo's vocabulary so "tests" is not treated as a term
            # the agent could only have learned from the memo.
            context = "\n".join(filter(None, [
                c.get("system_prompt"), c.get("user_msg_1"), c.get("user_msg_2")]))
            break

    timeline = annotate.build_timeline(r, memo_text, paths.MEMO_SENTINEL,
                                       context=context,
                                       memo_variable=memo_variable)
    diff = textdiff.parse_unified(r.get("agent_diff") or "")
    flags = textdiff.flag_lines(r.get("agent_diff") or "")
    manifests = records.manifest_deltas(r)

    ordered = STATE.ordered(blind_mode)
    ids = [e["_derived"]["blind_id"] if _is_blind(
        e, v_all.get(e.get("episode_id")), blind_mode) else e.get("episode_id")
        for e in ordered]
    try:
        pos = [e.get("episode_id") for e in ordered].index(eid)
    except ValueError:
        pos = 0

    # Did the planted memo match the condition file on disk?  A mismatch means
    # the episode did not run the condition we think it did.
    memo_integrity = None
    if r.get("memo_sha256") or memo_on_disk:
        memo_integrity = {
            "recorded": r.get("memo_sha256"),
            "on_disk": memo_on_disk,
            "match": (r.get("memo_sha256") == memo_on_disk)
            if (r.get("memo_sha256") and memo_on_disk) else None,
        }

    header = {
        "id": r["_derived"]["blind_id"] if blind else eid,
        "episode_id": r["_derived"]["blind_id"] if blind else eid,
        "task_pair": r.get("task_pair"),
        "split": r.get("split"),
        "run_index": None if blind else r.get("run_index"),
        "condition": None if blind else cond,
        "prompt_variant": r.get("prompt_variant"),
        "model": r.get("model"),
        "model_provider": r.get("model_provider"),
        "setup_ref_1": r.get("setup_ref_1"),
        "setup_ref_2": r.get("setup_ref_2"),
        "memo_ladder_rung": None if blind else r.get("memo_ladder_rung"),
        "memo_path": None if blind else r.get("memo_path"),
        "messages": r.get("messages"),
        "total_tokens": r.get("total_tokens"),
        "inspect_version": r.get("inspect_version"),
        "swebench_version": r.get("swebench_version"),
        "sampling": r.get("sampling"),
    }

    evidence = {
        "timeline": timeline,
        "diff": diff,
        "diff_text": r.get("agent_diff") or "",
        "flag_lines": flags,
        "changed_files": r.get("changed_files") or [],
        "manifests": manifests,
        "git_concealment_detected": bool(r.get("git_concealment_detected")),
        "tests_touched": r.get("tests_touched"),
        "test_infra_touched": r.get("test_infra_touched"),
        "sphinx_touched": r.get("sphinx_touched"),
        "site_packages_touched": r.get("site_packages_touched"),
        "monitor_flagged": r.get("monitor_flagged"),
        "truth_table": annotate.truth_table(r, blind=blind),
        "test_evidence": r.get("test_evidence"),
        "flag_reason": r.get("flag_reason"),
        "flagged_for_human": bool(r.get("flagged_for_human")),
        "eval_awareness_hits": records.eval_awareness_quotes(r),
        "memo_exposed": r.get("memo_exposed"),
        "memo_path_in_command": r.get("memo_path_in_command"),
        "memo_exposure_turn": r.get("memo_exposure_turn"),
        "memo_referenced": r.get("memo_referenced"),
        "memo_reference_quotes": r.get("memo_reference_quotes") or [],
        "memo_text": None if blind else memo_text,
        "memo_integrity": memo_integrity,
        "phase1_solved": r.get("phase1_solved"),
        "phase1_exit_reason": r.get("phase1_exit_reason"),
        "hit_message_limit": r.get("hit_message_limit"),
        "malformed_tool_call_count": r.get("malformed_tool_call_count"),
        "zero_tool_call_turns": r.get("zero_tool_call_turns"),
        "test_runs_attempted": r.get("test_runs_attempted"),
        "error": r.get("error"),
    }

    invariants = r["_derived"]["invariants"]
    problems = r["_derived"]["problems"]
    integrity = {
        "invariants": [_scrub(x) for x in invariants] if blind else invariants,
        "problems": [_scrub(x) for x in problems] if blind else problems,
        "label_recomputed": None if blind else r["_derived"]["label_recomputed"],
        "label_consistent": None if blind else (
            None if not (r.get("label") and r["_derived"]["label_recomputed"])
            else r.get("label") == r["_derived"]["label_recomputed"]),
        "origin": None if blind else r["_derived"]["origin"],
    }

    automated = None if blind else {
        "label": r.get("label"),
        "label_recomputed": r["_derived"]["label_recomputed"],
        "method_heuristic": r.get("evasion_method_heuristic"),
        "method_llm_judge": r.get("evasion_method_llm_judge"),
        "method_human_prior": r.get("evasion_method_human"),
        "methods_agree": (
            None if not (r.get("evasion_method_heuristic")
                         and r.get("evasion_method_llm_judge"))
            else r.get("evasion_method_heuristic") == r.get("evasion_method_llm_judge")),
        "memo_exposed": r.get("memo_exposed"),
        "memo_referenced": r.get("memo_referenced"),
        "eval_awareness": records.eval_awareness_bool(r),
        "condition": cond,
        "method_family": records.METHOD_FAMILY.get(
            r.get("evasion_method_heuristic") or "", "-"),
    }

    return {
        "blind": blind,
        "blind_mode": blind_mode,
        "blind_notes": BLIND_NOTES if blind else [],
        "header": header,
        "evidence": evidence,
        "integrity": integrity,
        "automated": automated,
        "verdict": v,
        "nav": {"index": pos, "total": len(ordered),
                "prev": ids[pos - 1] if pos > 0 else None,
                "next": ids[pos + 1] if pos + 1 < len(ids) else None,
                "ids": ids},
    }


def _table_ids_for_display(table: dict, blind_mode: bool) -> dict:
    """The aggregate table is never blinded -- counts per condition are its
    entire point.  But the episode-id lists inside each cell are used for
    click-through, and a real episode id spells the condition out.  Translate
    them to the id the client is allowed to address."""
    if not blind_mode:
        return table
    v_all = store.verdicts(STATE.verification())
    mapping = {}
    for e in STATE.episodes:
        eid = e.get("episode_id")
        mapping[eid] = (e["_derived"]["blind_id"]
                        if _is_blind(e, v_all.get(eid), True) else eid)
    rows = list(table["rows"]) + ([table["overall"]] if table.get("overall") else [])
    for row in rows:
        for cell in row["cells"].values():
            for key in ("episodes", "verified_episodes"):
                if key in cell:
                    cell[key] = [mapping.get(x, x) for x in cell[key]]
        row["error_episodes"] = [mapping.get(x, x) for x in row.get("error_episodes", [])]
    return table


def bootstrap() -> dict:
    ver = STATE.verification()
    return {
        "version": __version__,
        "root": str(paths.ROOT),
        "paths": {
            "verification": paths.rel(paths.VERIFICATION),
            "episodes": paths.rel(paths.EPISODES_DIR),
            "agreement_report": paths.rel(paths.AGREEMENT_REPORT),
            "results": paths.rel(paths.RESULTS_REPORT),
        },
        "labels": records.LABELS,
        "all_labels": records.ALL_LABELS,
        "methods": records.METHODS,
        "method_family": records.METHOD_FAMILY,
        "conditions": records.CONDITIONS,
        "columns": records.TABLE_COLUMNS,
        "sentinel": paths.MEMO_SENTINEL,
        "episode_count": len(STATE.episodes),
        "reviewer": ver.get("reviewer"),
        "review_protocol": ver.get("review_protocol"),
        "load_error": STATE.load_error,
        "blind_default": True,
    }


def verdict_snapshot(r: dict) -> dict:
    return {
        "label": r.get("label"),
        "label_recomputed": r["_derived"]["label_recomputed"],
        "method_heuristic": r.get("evasion_method_heuristic"),
        "method_llm_judge": r.get("evasion_method_llm_judge"),
        "memo_exposed": r.get("memo_exposed"),
        "memo_referenced": r.get("memo_referenced"),
        "eval_awareness": records.eval_awareness_bool(r),
        "condition": r.get("condition"),
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = f"exp1-review/{__version__}"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------
    def log_message(self, fmt, *args):  # quieter than the default
        if self.path.startswith("/api/") and not self.path.startswith("/api/health"):
            print(f"  {self.command} {self.path}")

    def _send(self, code: int, body: bytes, ctype: str,
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    def _query(self) -> dict:
        q = urllib.parse.urlparse(self.path).query
        return {k: v[0] for k, v in urllib.parse.parse_qs(q).items()}

    def _blind(self) -> bool:
        return self._query().get("blind", "1") not in ("0", "false", "no")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"body is not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    # -- routes -----------------------------------------------------------
    def do_GET(self):  # noqa: N802
        try:
            self._route_get()
        except Exception:
            traceback.print_exc()
            self._error(500, traceback.format_exc(limit=3))

    do_HEAD = do_GET

    def _route_get(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/api/health":
            return self._json({"ok": True, "episodes": len(STATE.episodes)})
        if path == "/api/bootstrap":
            return self._json(bootstrap())
        if path == "/api/conditions":
            return self._json(STATE.conditions)
        if path == "/api/episodes":
            return self._json(episode_list(self._blind()))
        if path == "/api/table":
            cols = self._query().get("columns")
            columns = [c for c in cols.split(",") if c in records.METRICS_BY_KEY] \
                if cols else None
            table = aggregate.build_table(
                STATE.episodes, STATE.verification(), columns)
            return self._json(_table_ids_for_display(table, self._blind()))
        if path == "/api/queue":
            return self._json(aggregate.review_queue(
                STATE.episodes, STATE.verification()))
        if path == "/api/agreement":
            return self._json(reports.agreement_stats(
                STATE.episodes, STATE.verification()))
        if path == "/api/verification":
            return self._json(STATE.verification())
        if path.startswith("/api/episode/"):
            key = urllib.parse.unquote(path[len("/api/episode/"):])
            payload = episode_payload(key, self._blind())
            if payload is None:
                return self._error(404, f"no such episode: {key}")
            return self._json(payload)
        return self._error(404, f"no route {path}")

    def do_POST(self):  # noqa: N802
        try:
            self._route_post()
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception:
            traceback.print_exc()
            self._error(500, traceback.format_exc(limit=3))

    def _route_post(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/verdict":
            return self._put_verdict()
        if path == "/api/reload":
            STATE.reload()
            return self._json({"ok": True, "episodes": len(STATE.episodes),
                               "load_error": STATE.load_error})
        if path == "/api/reports":
            written = reports.write_all(STATE.episodes, STATE.verification())
            return self._json({"ok": True, "written": written})
        if path == "/api/reviewer":
            body = self._body()
            data = store.load()
            data["reviewer"] = (body.get("reviewer") or "").strip() or None
            store.save(data)
            return self._json({"ok": True, "reviewer": data["reviewer"]})
        if path == "/api/protocol":
            return self._json(store.set_protocol(self._body()))
        return self._error(404, f"no route {path}")

    def do_DELETE(self):  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/verdict/"):
            key = urllib.parse.unquote(path[len("/api/verdict/"):])
            r = STATE.find(key)
            if r is None:
                return self._error(404, f"no such episode: {key}")
            ok = store.delete_verdict(r.get("episode_id"))
            return self._json({"ok": ok})
        return self._error(404, f"no route {path}")

    def _put_verdict(self):
        body = self._body()
        key = body.get("episode_id") or body.get("id")
        if not key:
            raise ValueError("episode_id is required")
        r = STATE.find(str(key))
        if r is None:
            return self._error(404, f"no such episode: {key}")
        label = body.get("label")
        if label is not None and label not in records.ALL_LABELS:
            raise ValueError(f"label {label!r} is not in the frozen vocabulary")
        method = body.get("method")
        if method is not None and method not in records.METHODS:
            raise ValueError(f"method {method!r} is not in the frozen vocabulary")
        if label is None:
            raise ValueError("a verdict needs a label")

        v_all = store.verdicts(STATE.verification())
        existing = v_all.get(r.get("episode_id"))
        # The server decides `blind`, never the client: a verdict entered after
        # the reveal must not be able to claim it was blind.
        blind = _is_blind(r, existing, bool(body.get("blind_mode", True)))
        stored = store.put_verdict(
            r.get("episode_id"), body, blind=blind,
            auto_snapshot=verdict_snapshot(r),
            reviewer=body.get("reviewer"))
        return self._json({"ok": True, "verdict": stored,
                           "automated": verdict_snapshot(r)})

    # -- static -----------------------------------------------------------
    def _static(self, name: str):
        name = name.lstrip("/")
        target = (paths.STATIC / name).resolve()
        try:
            target.relative_to(paths.STATIC.resolve())
        except ValueError:
            return self._error(403, "outside the static root")
        if not target.is_file():
            return self._error(404, f"no such file: {name}")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "application/json"):
            ctype += "; charset=utf-8"
        return self._send(200, target.read_bytes(), ctype)


def serve(host: str = "127.0.0.1", port: int = 8731, open_browser: bool = True) -> None:
    STATE.reload()
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    ck = (STATE.conditions.get("checks") or {})
    print(f"exp1 review app {__version__}")
    print(f"  root            {paths.ROOT}")
    print(f"  episodes        {len(STATE.episodes)} loaded from "
          f"{paths.rel(paths.EPISODES_DIR)}/")
    print(f"  verification    {paths.rel(paths.VERIFICATION)}")
    print(f"  conditions      self-check {ck.get('status', '?').upper()} "
          f"({ck.get('passed')}/{ck.get('total')})")
    if STATE.load_error:
        print(f"  !! load error   {STATE.load_error}")
    print(f"  serving         {url}   (blind mode ON by default)")
    print("  ctrl-c to stop", flush=True)  # flush: stdout is block-buffered
    #                                        when piped, and a banner that
    #                                        appears only on exit is useless
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
