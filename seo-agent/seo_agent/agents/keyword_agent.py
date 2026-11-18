"""Keyword Research Agent: discovery from free/low-cost sources + labeled opportunity estimate."""
from __future__ import annotations

from typing import Any

from .. import research, scoring
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


def seed_groups(cfg: Config, extra: list[str]) -> dict[str, list[str]]:
    """One Keyword Planner request group per FitCheck feature, so every feature gets its own ideas."""
    groups = {fid: list(f.get("seeds") or []) for fid, f in scoring.features(cfg).items() if f.get("seeds")}
    general = list(cfg.get("keyword_research.seed_keywords", [])) + extra
    if general:
        groups["general"] = general
    return groups


def discover_all(cfg: Config, groups: dict[str, list[str]], report: dict) -> list[dict[str, Any]]:
    """Runs discovery per feature group. One failing group never stops the others; if ALL fail, NoProvider."""
    ideas: dict[str, dict[str, Any]] = {}
    last: Exception | None = None
    ok = 0
    for gid, seeds in groups.items():
        try:
            found = research.discover(cfg, seeds)
        except research.NoProvider as e:
            last = e
            continue
        ok += 1
        for i in found:
            ideas.setdefault(i["keyword"], {**i, "seed_group": gid})
        report.setdefault("discovery", {})[gid] = len(found)
    if not ok and last is not None:
        raise last
    return list(ideas.values())


def opportunity_estimate(cfg: Config, i: dict[str, Any]) -> tuple[int, list[str]]:
    """LEGACY (kept for reference/tests): the old single-number estimate. Replaced by scoring.score().
    HEURISTIC 0-100 'opportunity estimate'. It is NOT keyword difficulty and is labeled as such everywhere.
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
    gsc_seeds = [q for q, m in sorted(gsc.items(), key=lambda kv: -kv[1]["gsc_impressions_28d"]) if research.relevant(cfg, q)][:20]
    seeds += gsc_seeds
    ideas: dict[str, dict[str, Any]] = {}
    try:
        for i in discover_all(cfg, seed_groups(cfg, gsc_seeds), report):
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
    for i in found:
        i["market"] = cfg.get("keyword_research.location")
    found = research.enrich(cfg, found)
    articles = state.data.get("articles", {})
    for i in found:
        scoring.score(cfg, i, pages, articles)
    short = research.shortlist(cfg, found, pages, state)
    report["feature_summary"] = feature_summary(cfg, found)
    reasons: dict[str, int] = {}
    for i in found:
        r = str(i.get("decision", "")).split(":")[0]
        if r != "candidate" and not r.startswith("duplicate_intent"):
            reasons[r] = reasons.get(r, 0) + 1
    dec = [str(i.get("decision", "")) for i in found]
    report["selection_counts"] = {
        "discovered": len(ideas), "relevant": len(found), "qualifying": len(short),
        "duplicates": sum(d.startswith("duplicate_intent") for d in dec),
        "dup_landing": sum(d.startswith("duplicate_intent_of_landing") for d in dec),
        "dup_article": sum(d.startswith("duplicate_intent_of_article") for d in dec),
        "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1]))}
    log.info("Keyword agent: %d ideas, %d relevant, %d shortlisted", len(ideas), len(found), len(short))
    return short


def run_global(cfg: Config, state: State, pages: list[Page], perf: dict[str, Any] | None, report: dict) -> list[dict[str, Any]]:
    """Searches every configured market, pools the qualifying keywords and returns them highest verified volume first.

    A candidate is eligible when its Keyword Planner volume is >= global_discovery.minimum_monthly_searches AND its Google
    Ads competition is in allowed_ads_competition (unknown competition is NOT eligible). The same keyword seen in several
    markets is kept once, in its highest-volume market. Relevance, intent, duplicate and cooldown checks are the normal
    ones (applied inside run()). One market failing never stops the others; Budget limits still stop everything."""
    from ..budget import BudgetExceeded
    g = cfg.get("keyword_research.global_discovery") or {}
    kr = cfg.raw["keyword_research"]
    primary = {k: kr.get(k) for k in ("location", "location_code", "minimum_monthly_searches")}
    min_vol = int(g.get("minimum_monthly_searches", 1000))
    allowed = {str(c).upper() for c in g.get("allowed_ads_competition", ["LOW"])}
    english_only = bool(g.get("english_only", True))
    pool: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    last: Exception | None = None
    ok = 0
    first_summary = None
    try:
        for m in g.get("markets", []):
            kr.update(location=m["location"], location_code=m["location_code"], minimum_monthly_searches=min_vol)
            row = {"market": m["location"], "name": m["name"], "ideas": 0, "qualifying": 0, "eligible": 0, "best": None, "error": None}
            rows.append(row)
            try:
                short = run(cfg, state, pages, perf, report)
            except BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001 - one market must not stop the others
                last = e
                row["error"] = f"{type(e).__name__}: {str(e)[:120]}"
                log.warning("Global discovery: market %s failed: %s", m["location"], row["error"])
                continue
            ok += 1
            counts = report.get("selection_counts") or {}
            row["ideas"], row["qualifying"] = counts.get("discovered", 0), len(short)
            if first_summary is None:
                first_summary = report.get("feature_summary")
            for i in short:
                comp = str(i.get("ads_competition") or "").upper()
                if (i.get("volume") or 0) < min_vol or comp not in allowed or (english_only and not i["keyword"].isascii()):
                    continue
                i["market"], i["market_name"] = m["location"], m["name"]
                row["eligible"] += 1
                prev = pool.get(i["keyword"])
                seen = (prev or {}).get("also_seen", [])
                seen.append({"market": m["location"], "volume": i["volume"]})
                if prev is None or i["volume"] > prev["volume"]:
                    pool[i["keyword"]] = {**i, "also_seen": seen}
                else:
                    prev["also_seen"] = seen
    finally:
        kr.update(primary)
    if not ok and last is not None:
        raise last
    if first_summary is not None:
        report["feature_summary"] = first_summary
    ranked = sorted(pool.values(), key=lambda i: (-(i["volume"] or 0), -(i.get("score_total") or 0)))
    for i in ranked:
        row = next(r for r in rows if r["market"] == i["market"])
        if row["best"] is None or i["volume"] > row["best"][1]:
            row["best"] = (i["keyword"], i["volume"])
    report["global"] = {"min_volume": min_vol, "competition": sorted(allowed), "markets": rows,
                        "eligible_keywords": len(ranked)}
    log.info("Global discovery: %d markets, %d eligible keywords pooled", len(rows), len(ranked))
    return ranked


def selection_reason(cfg: Config, kw: dict[str, Any], n_markets: int) -> str:
    also = [f"{s['market']} {s['volume']:,}" for s in kw.get("also_seen", []) if s["market"] != kw.get("market")]
    return (f"Highest-volume eligible keyword across {n_markets} markets: {kw['volume']:,} searches/month in "
            f"{kw.get('market_name') or kw.get('market')}, Google Ads competition {kw.get('ads_competition')}, "
            f"score {kw.get('score_total')}; passed relevance, duplicate, planner and quality checks."
            + (f" Also seen in: {', '.join(also)}." if also else ""))


def feature_summary(cfg: Config, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per feature: ideas found, qualifying count, best keyword, and the most common skip reason."""
    rows = []
    for fid in [*scoring.features(cfg), "none"]:
        mine = [i for i in found if i.get("feature") == fid]
        if not mine and fid == "none":
            continue
        q = [i for i in mine if i.get("decision") == "candidate"]
        best = max(mine, key=lambda i: i.get("score_total", 0), default=None)
        reasons: dict[str, int] = {}
        for i in mine:
            if i.get("decision") != "candidate":
                r = str(i.get("decision") or i.get("_reason") or "")
                reasons[r] = reasons.get(r, 0) + 1
        rows.append({"feature": fid, "ideas": len(mine), "qualifying": len(q),
                     "best": best["keyword"] if best else "-", "best_total": best.get("score_total") if best else None,
                     "top_skip_reason": max(reasons, key=reasons.get) if reasons else "-"})
    return rows
