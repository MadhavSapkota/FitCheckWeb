"""Persistent JSON state: keyword history, coverage, articles, decisions. Committed to the repo."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT: dict[str, Any] = {"version": 1, "keywords": {}, "articles": {}, "runs": [], "page_updates": []}


class State:
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            for k, v in DEFAULT.items():
                self.data.setdefault(k, v if not isinstance(v, (dict, list)) else type(v)())
        else:
            self.data = json.loads(json.dumps(DEFAULT))

    # keywords --------------------------------------------------------------
    def record_keyword(self, kw: str, metrics: dict[str, Any], decision: str) -> None:
        """Stores a COMPACT record (see LATEST_KEYS). History is kept only for important decisions (published,
        candidate, duplicate, quality-gate/planner results) and only when something changed; routine rejections
        (low volume, low relevance, ...) keep just their latest metrics, so daily runs add almost nothing."""
        entry = self.data["keywords"].setdefault(kw, {})
        latest = compact(metrics)
        changed = entry.get("decision") != decision or entry.get("latest") != latest
        entry["latest"] = latest
        entry["decision"] = decision
        entry["feature"] = metrics.get("feature") or entry.get("feature")
        if decision.startswith("published:"):
            entry["article"] = {"slug": decision.split(":", 1)[1], "published": today()}
        if changed or "updated" not in entry:
            entry["updated"] = today()
        if routine(decision):
            entry.pop("history", None)
        elif changed or not entry.get("history"):
            entry.setdefault("history", []).append(
                {"date": today(), "decision": decision, **{k: latest.get(k) for k in HISTORY_KEYS}})
            entry["history"] = entry["history"][-MAX_HISTORY:]

    def used_keywords(self) -> set[str]:
        used = set()
        for a in self.data["articles"].values():
            used.add(a["keyword"].lower())
            used.update(k.lower() for k in a.get("secondary_keywords", []))
        return used

    def rejected_recently(self, kw: str, days: int = 30) -> bool:
        e = self.data["keywords"].get(kw)
        if not e or not str(e.get("decision", "")).startswith("rejected_by_quality_gate"):
            return False
        last = e.get("updated") or (e.get("history") or [{}])[-1].get("date")
        if not last:
            return False
        return (date.fromisoformat(today()) - date.fromisoformat(last)).days < days

    def prune(self, keep_days: int | None = None) -> int:
        """Compacts every keyword record and drops ROUTINE rejections not updated for `keep_days`.
        Published, shortlisted, duplicate and quality-gate records are never dropped."""
        keep_days = PRUNE_DAYS if keep_days is None else keep_days
        removed = 0
        cutoff = date.fromisoformat(today())
        for kw in list(self.data["keywords"]):
            e = self.data["keywords"][kw]
            e["latest"] = compact(e.get("latest") or {})
            hist = e.get("history") or []
            e.setdefault("updated", hist[-1]["date"] if hist and hist[-1].get("date") else today())
            dec = str(e.get("decision", ""))
            if routine(dec):
                e.pop("history", None)
                if (cutoff - date.fromisoformat(e["updated"])).days > keep_days:
                    del self.data["keywords"][kw]
                    removed += 1
            else:
                e["history"] = [{k: h.get(k) for k in ("date", "decision", *HISTORY_KEYS)} for h in hist][-MAX_HISTORY:]
                if not e["history"]:
                    e.pop("history")
        return removed

    # articles --------------------------------------------------------------
    def add_article(self, slug: str, info: dict[str, Any]) -> None:
        self.data["articles"][slug] = info

    def published_today(self) -> int:
        return sum(1 for a in self.data["articles"].values() if a.get("published") == today())

    def updates_today(self) -> int:
        return sum(1 for u in self.data["page_updates"] if u.get("date") == today())

    def add_run(self, summary: dict[str, Any]) -> None:
        self.data["runs"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **summary})
        self.data["runs"] = self.data["runs"][-120:]

    def save(self) -> None:
        """Pruned, compact JSON: one line per keyword record, so a daily run only changes the lines that changed."""
        self.prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(dumps(self.data), encoding="utf-8")
        os.replace(tmp, self.path)


# Compact keyword records ------------------------------------------------------------------------------------------
# Everything the agent reads back (re-tests, quality-gate cooldown, offline rescore, reports). Long text evidence is
# recomputed every run and is kept in the daily report instead.
LATEST_KEYS = ("keyword", "volume", "source", "ads_competition", "difficulty", "intent", "intent_type", "feature",
               "score", "score_total", "gsc_impressions_28d", "gsc_position")
HISTORY_KEYS = ("volume", "feature", "score_total", "gsc_impressions_28d", "gsc_position")
MAX_HISTORY = 10
PRUNE_DAYS = 90
# Rejections decided only by keyword data (re-evaluated from fresh data every run). Everything else is "important".
ROUTINE_PREFIXES = ("rejected_low_volume", "rejected_low_feature_relevance", "rejected_low_score",
                    "rejected_low_opportunity_estimate", "rejected_head_term", "rejected_irrelevant",
                    "rejected_volume_unverified", "rejected_intent", "rejected_difficulty", "rejected_no_organic")


def routine(decision: str) -> bool:
    return str(decision).startswith(ROUTINE_PREFIXES)


def compact(metrics: dict[str, Any]) -> dict[str, Any]:
    # volume is kept even when null: null means "unverified", which is meaningful and must never look like data
    return {k: metrics[k] for k in LATEST_KEYS if metrics.get(k) is not None or (k == "volume" and k in metrics)}


def dumps(data: dict[str, Any]) -> str:
    """Pretty JSON for everything except `keywords`, which is written one record per line (valid JSON)."""
    rest = {k: v for k, v in data.items() if k != "keywords"}
    rest["keywords"] = "__KEYWORDS__"
    body = json.dumps(rest, indent=2, sort_keys=True, ensure_ascii=False)
    lines = [f"    {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
             for k, v in sorted(data.get("keywords", {}).items())]
    kw = "{\n" + ",\n".join(lines) + "\n  }" if lines else "{}"
    return body.replace('"__KEYWORDS__"', kw, 1) + "\n"


def today() -> str:
    return os.environ.get("SEO_AGENT_TODAY") or datetime.now(timezone.utc).date().isoformat()
