"""verification.json -- the durable record of what the human actually checked.

Written atomically on every click.  A verdict that does not survive a browser
refresh is a verdict that will be re-entered carelessly the second time, so
persistence is not a nicety here.

Every verdict keeps:
  * `blind`         whether it was entered before the condition and the
                    automated labels were revealed.  Agreement statistics are
                    computed over blind verdicts only (SPEC 8.4), so this flag
                    is load-bearing and is set by the server, never the client.
  * `auto_snapshot` the automated labels as they stood when the verdict was
                    submitted, so re-running the grader later cannot silently
                    rewrite history.
  * `history`       prior revisions, so an overrule is auditable.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import tempfile
import threading

from . import VERIFICATION_SCHEMA, paths

_LOCK = threading.Lock()

VERDICT_FIELDS = ("label", "method", "memo_exposed", "memo_used",
                  "eval_awareness", "note")


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _empty() -> dict:
    return {"schema": VERIFICATION_SCHEMA, "created_at": now(),
            "updated_at": now(), "reviewer": None, "verdicts": {},
            "review_protocol": {
                "honest_sample_seed": None,
                "honest_sample_fraction": 0.20,
                "pilot_reviews_everything": True,
            }}


def load(path: pathlib.Path | None = None) -> dict:
    path = path or paths.VERIFICATION
    if not path.is_file():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Never silently start from scratch over an unreadable file: that is
        # how a day of review gets lost.
        raise RuntimeError(
            f"{path} exists but could not be parsed ({exc}). "
            "Move it aside deliberately before continuing."
        ) from exc
    if not isinstance(data, dict) or "verdicts" not in data:
        raise RuntimeError(f"{path} is not a verification file (no 'verdicts' key).")
    data.setdefault("schema", VERIFICATION_SCHEMA)
    data.setdefault("review_protocol", _empty()["review_protocol"])
    return data


def _atomic_write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".verification-",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(data: dict, path: pathlib.Path | None = None) -> None:
    path = path or paths.VERIFICATION
    data["updated_at"] = now()
    _atomic_write(path, json.dumps(data, indent=2, sort_keys=False) + "\n")


def verdicts(data: dict) -> dict[str, dict]:
    return data.get("verdicts") or {}


def put_verdict(episode_id: str, payload: dict, *, blind: bool,
                auto_snapshot: dict, reviewer: str | None = None,
                path: pathlib.Path | None = None) -> dict:
    """Upsert one verdict.  Returns the stored verdict."""
    with _LOCK:
        data = load(path)
        existing = data["verdicts"].get(episode_id)
        verdict = {
            "episode_id": episode_id,
            "label": payload.get("label"),
            "method": payload.get("method"),
            "memo_exposed": payload.get("memo_exposed"),
            "memo_used": payload.get("memo_used"),
            "eval_awareness": payload.get("eval_awareness"),
            "note": (payload.get("note") or "").strip() or None,
            "blind": bool(blind),
            "agree_all_automated": bool(payload.get("agree_all_automated")),
            "reviewer": reviewer or data.get("reviewer"),
            "auto_snapshot": auto_snapshot,
            "created_at": existing["created_at"] if existing else now(),
            "updated_at": now(),
            "revision": (existing.get("revision", 1) + 1) if existing else 1,
            "history": list(existing.get("history", [])) if existing else [],
        }
        # The blind moment, preserved.
        #
        # A verdict submitted blind and then edited after the reveal is two
        # judgements, not one.  `blind_label` / `blind_method` freeze what was
        # actually entered before the grader's answer was visible, so the
        # agreement statistics keep using them.  Without this, fixing a typo in
        # a note after the reveal would silently drop the episode out of the
        # blind sample -- and the reviewer would never know the denominator
        # moved.
        if existing:
            prior = {k: existing.get(k) for k in
                     ("label", "method", "memo_exposed", "memo_used",
                      "eval_awareness", "note", "blind", "updated_at",
                      "revision")}
            verdict["history"].append(prior)
            verdict["entered_blind"] = bool(existing.get("entered_blind"))
            verdict["blind_label"] = existing.get("blind_label")
            verdict["blind_method"] = existing.get("blind_method")
            verdict["blind_at"] = existing.get("blind_at")
            # The CURRENT values were entered with the reveal on screen.
            verdict["blind"] = bool(blind and existing.get("blind"))
        else:
            verdict["entered_blind"] = bool(blind)
            verdict["blind_label"] = verdict["label"] if blind else None
            verdict["blind_method"] = verdict["method"] if blind else None
            verdict["blind_at"] = verdict["created_at"] if blind else None
        data["verdicts"][episode_id] = verdict
        if reviewer:
            data["reviewer"] = reviewer
        save(data, path)
        return verdict


def delete_verdict(episode_id: str, path: pathlib.Path | None = None) -> bool:
    with _LOCK:
        data = load(path)
        if episode_id in data["verdicts"]:
            del data["verdicts"][episode_id]
            save(data, path)
            return True
        return False


def set_protocol(updates: dict, path: pathlib.Path | None = None) -> dict:
    with _LOCK:
        data = load(path)
        data["review_protocol"].update(updates)
        save(data, path)
        return data["review_protocol"]
