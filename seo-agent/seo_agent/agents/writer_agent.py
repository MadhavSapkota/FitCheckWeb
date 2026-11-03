"""Content Writer Agent: drafts the guide, then a separate reviewer call checks it."""
from __future__ import annotations

from typing import Any

from .. import content
from ..config import Config
from ..state import today


def write(cfg: Config, kw: dict[str, Any], plan: dict[str, Any], serp: dict[str, Any], slug: str,
          links: list[dict[str, str]], facts: dict) -> dict[str, Any]:
    d = content.write_article(cfg, kw, plan, serp, links, facts)
    return {"slug": slug, "keyword": kw["keyword"], "secondary_keywords": plan.get("secondary_keywords", [])[:8],
            "intent": plan["intent"],
            "metrics": {k: kw.get(k) for k in ("keyword", "volume", "difficulty", "intent", "source",
                                               "opportunity_estimate", "opportunity_evidence", "gsc_impressions_28d", "gsc_position")},
            "title": d["title"].strip(), "meta_description": d["meta_description"].strip(), "h1": d["h1"].strip(),
            "body_html": d["body_html"], "faqs": d.get("faqs", [])[:6], "cta_text": d.get("cta_text", ""),
            "summary": d.get("summary", ""), "published": today(), "modified": today(),
            "serp_snapshot": serp.get("organic", [])}


def revise(cfg: Config, kw: dict[str, Any], plan: dict[str, Any], a: dict[str, Any], feedback: dict[str, Any],
           facts: dict) -> dict[str, Any]:
    fields = ("title", "meta_description", "h1", "body_html", "faqs", "cta_text", "summary")
    d = content.revise(cfg, kw, plan, {k: a.get(k) for k in fields}, feedback, facts)
    out = dict(a)
    for k in fields:
        if d.get(k):
            out[k] = d[k].strip() if isinstance(d[k], str) else d[k]
    out["faqs"] = (out.get("faqs") or [])[:6]
    out["revision_changes"] = d.get("changes_made", [])
    return out


def review(cfg: Config, a: dict[str, Any], facts: dict) -> dict[str, Any]:
    return content.review(cfg, a["keyword"], a["intent"],
                          {k: a[k] for k in ("title", "meta_description", "h1", "body_html", "faqs", "cta_text")}, facts)
