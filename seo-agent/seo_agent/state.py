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
        entry = self.data["keywords"].setdefault(kw, {"history": []})
        entry["latest"] = metrics
        entry["decision"] = decision
        entry["feature"] = metrics.get("feature") or entry.get("feature")
        if decision.startswith("published:"):
            entry["article"] = {"slug": decision.split(":", 1)[1], "published": today()}
        entry["history"].append({"date": today(), "decision": decision,
                                 **{k: metrics.get(k) for k in ("volume", "difficulty", "intent", "source", "feature", "score",
                                                                "score_total", "gsc_impressions_28d", "gsc_position")}})
        entry["history"] = entry["history"][-30:]

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
        last = e["history"][-1]["date"]
        return (date.fromisoformat(today()) - date.fromisoformat(last)).days < days

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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


def today() -> str:
    return os.environ.get("SEO_AGENT_TODAY") or datetime.now(timezone.utc).date().isoformat()
