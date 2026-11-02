"""Keyword Research Agent: discovery from free/low-cost sources + labeled opportunity estimate."""
from __future__ import annotations

from typing import Any

from .. import research
from ..audit import Page, tokens
from ..config import Config, load_app_facts
from ..log import log
from ..state import State

QUESTION = ("how", "what", "which", "why", "when", "can", "should", "does", "is", "are", "ideas", "tips", "guide")


def gsc_query_ideas(cfg: Config, perf: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Real queries Google already shows the site for (free evidence of demand and reachability)."""
    out: dict[str, dict[str, Any]] = {}
    if not perf:
        return out
    for r in perf.get("queries_28d", []):
        q = r["query"].strip().lower()
        out[q] = {"gsc_impressions_28d": r["impressions"], "gsc_clicks_28d": r["clicks"], "gsc_position": round(r["position"], 1)}
    return out


def opportunity_estimate(cfg: Config, i: dict[str, Any]) -> tuple[int, list[str]]:
    """HEURISTIC 0-100 'opportunity estimate'. It is NOT keyword difficulty and is labeled as such everywhere.
    Evidence used: phrase length (long-tail), question format, verified volume band, relevance,
    and Search Console evidence that Google already ranks the site near page 1-3 for the query."""
    score, why = 0, []
    n = len(tokens(i["keyword"]))
    if n >= 5:
        score += 25; why.append("5+ word long-tail")
    elif n == 4:
        score += 20; why.append("4-word long-tail")
    elif n == 3:
        score += 8; why.append("3-word phrase")
    if tokens(i["keyword"])[:1] and tokens(i["keyword"])[0] in QUESTION:
        score += 10; why.append("question/how-to format")
    v = i.get("volume")
    if v is not None:
        if 100 <= v <= 1000:
            score += 20; why.append("verified volume 100-1,000 (modest competition likely)")
        elif 1000 < v <= 5000:
            score += 10; why.append("verified volume 1k-5k")
    pos = i.get("gsc_position")
    if pos is not None and i.get("gsc_impressions_28d", 0) >= 10:
        if pos <= 30:
            score += 30; why.append(f"site already ranks ~{pos} in Google (Search Console)")
        else:
            score += 10; why.append(f"site shows in Google at ~{pos} (Search Console)")
    score += round(15 * research.relevance_score(cfg, i["keyword"]))
    if i.get("difficulty") is not None:  # measured KD when the paid source is enabled
        score += 15 if i["difficulty"] <= 15 else 5 if i["difficulty"] <= cfg.get("keyword_research.maximum_organic_difficulty", 25) else -50
        why.append(f"measured organic KD {i['difficulty']}")
    return max(0, min(100, score)), why


def run(cfg: Config, state: State, pages: list[Page], perf: dict[str, Any] | None, report: dict) -> list[dict[str, Any]]:
    gsc = gsc_query_ideas(cfg, perf)
    seeds = list(cfg.get("keyword_research.seed_keywords", []))
    seeds += [q for q, m in sorted(gsc.items(), key=lambda kv: -kv[1]["gsc_impressions_28d"]) if research.relevant(cfg, q)][:20]
    ideas: dict[str, dict[str, Any]] = {}
    try:
        for i in research.discover(cfg, seeds):
            ideas[i["keyword"]] = i
    except research.NoProvider as e:
        editorial = cfg.get("keyword_research.unverified_topics.enabled", False)
        if not gsc and not editorial:
            raise
        report["notes"].append(f"{e}. Using {'Search Console queries' if gsc else 'editorial topics'} (volume unverified).")
        if not gsc and editorial:
            from .. import content
            titles = [p.title for p in pages]
            try:
                topics = content.suggest_topics(cfg, seeds, titles, load_app_facts())
            except Exception as err:  # noqa: BLE001 - never crash the daily run
                report["notes"].append(f"editorial topic suggestion failed: {str(err)[:200]}")
                topics = []
            if not topics:
                raise research.NoProvider("no verified keyword data and no editorial topics available")
            for q in topics:
                ideas.setdefault(q, {"keyword": q, "volume": None, "source": "editorial (volume unverified)"})
    for q, m in gsc.items():
        ideas.setdefault(q, {"keyword": q, "volume": None, "source": "search_console (volume unverified)"}).update(m)
    found = [i for i in ideas.values() if research.relevant(cfg, i["keyword"])]
    found = research.enrich(cfg, found)
    for i in found:
        i["opportunity_estimate"], i["opportunity_evidence"] = opportunity_estimate(cfg, i)
    short = research.shortlist(cfg, found, pages, state)
    log.info("Keyword agent: %d ideas, %d relevant, %d shortlisted", len(ideas), len(found), len(short))
    return short
