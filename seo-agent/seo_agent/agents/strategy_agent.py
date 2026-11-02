"""SEO Strategy Agent: intent analysis and new / improve / skip decision."""
from __future__ import annotations

from typing import Any

from .. import content, dataforseo, research
from ..config import Config


def serp_evidence(cfg: Config, kw: dict[str, Any]) -> dict[str, Any]:
    if research.measured_difficulty(cfg) and dataforseo.available():
        return dataforseo.serp_top10(cfg, kw["keyword"])
    return {"keyword": kw["keyword"], "organic": [], "questions": [],
            "note": "No live SERP data in low-cost mode; plan from general knowledge and our site only."}


def decide(cfg: Config, kw: dict[str, Any], pages, facts: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    serp = serp_evidence(cfg, kw)
    site_pages = [{"path": p.path, "title": p.title, "h1": p.h1[:1], "h2": p.h2[:8]} for p in pages]
    plan = content.plan(cfg, kw, serp, site_pages, facts)
    plan["intent"] = (plan.get("intent") or kw.get("intent") or "").lower()
    return plan, serp
