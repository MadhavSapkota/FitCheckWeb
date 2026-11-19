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
    report["_market_keys"] = (set(ideas), {i["keyword"] for i in found})  # consumed by run_global (unique counts across markets)
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
    """Searches every configured market, pools the qualifying keywords and returns the PREFERRED ones, highest volume first.

    Eligible = Keyword Planner volume >= minimum_monthly_searches AND Google Ads competition in allowed_ads_competition
    (unknown competition is NOT eligible) AND (english_only) an ASCII keyword. Preferred = eligible AND heuristic ranking
    opportunity >= min_ranking_opportunity: only these are returned, so a hard head term is never auto-selected. Eligible
    keywords below the threshold are still listed in report["global"]["keywords"] with their status. The same keyword seen
    in several markets is kept once (highest-volume market). Relevance, intent, duplicate and cooldown checks are the normal
    ones (inside run()). One market failing never stops the others; Budget limits still stop everything."""
    from ..budget import BudgetExceeded
    g = cfg.get("keyword_research.global_discovery") or {}
    kr = cfg.raw["keyword_research"]
    primary = {k: kr.get(k) for k in ("location", "location_code", "minimum_monthly_searches")}
    min_vol = int(g.get("minimum_monthly_searches", 1000))
    min_opp = g.get("min_ranking_opportunity")
    allowed = {str(c).upper() for c in g.get("allowed_ads_competition", ["LOW"])}
    english_only = bool(g.get("english_only", True))
    pool: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    totals: dict[str, Any] = {"discovered": 0, "relevant": 0, "qualifying": 0, "duplicates": 0, "dup_landing": 0, "dup_article": 0, "reasons": {}}
    last: Exception | None = None
    ok = 0
    first_summary = None
    uniq_found: set[str] = set()
    uniq_relevant: set[str] = set()
    try:
        for m in g.get("markets", []):
            kr.update(location=m["location"], location_code=m["location_code"], minimum_monthly_searches=min_vol)
            row = {"market": m["location"], "name": m["name"], "counts": {}, "reasons": {}, "qualifying": 0, "eligible": 0,
                   "preferred": 0, "global_rejections": {"ads_competition_not_allowed": 0, "non_english": 0, "ranking_opportunity_below_min": 0},
                   "error": None}
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
            keys = report.pop("_market_keys", None)
            if keys:
                uniq_found |= keys[0]
                uniq_relevant |= keys[1]
            counts = dict(report.get("selection_counts") or {})  # complete per-market counts, kept before the next market overwrites them
            row["counts"] = {k: v for k, v in counts.items() if k != "reasons"}
            row["reasons"] = dict(counts.get("reasons") or {})
            row["qualifying"] = len(short)
            for k in ("discovered", "relevant", "qualifying", "duplicates", "dup_landing", "dup_article"):
                totals[k] += counts.get(k, 0)
            for r, n in row["reasons"].items():
                totals["reasons"][r] = totals["reasons"].get(r, 0) + n
            if first_summary is None:
                first_summary = report.get("feature_summary")
            for i in short:
                comp = str(i.get("ads_competition") or "").upper()
                if (i.get("volume") or 0) < min_vol:
                    continue
                if comp not in allowed:
                    row["global_rejections"]["ads_competition_not_allowed"] += 1
                    continue
                if english_only and not i["keyword"].isascii():
                    row["global_rejections"]["non_english"] += 1
                    continue
                opp = (i.get("score") or {}).get("ranking_opportunity")
                below = min_opp is not None and (opp is None or opp < min_opp)
                if below:
                    row["global_rejections"]["ranking_opportunity_below_min"] += 1
                i["market"], i["market_name"], i["below_opportunity"] = m["location"], m["name"], below
                row["eligible"] += 1
                row["preferred"] += 0 if below else 1
                prev = pool.get(i["keyword"])
                seen = (prev or {}).get("also_seen", [])
                seen.append({"market": m["location"], "volume": i["volume"], "competition": comp})  # country-level metrics are kept, never summed
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
        report["notes"].append("'Keywords by feature' covers the first market (United States) only; every market's counts are in the global tables.")
    report["selection_counts"] = totals  # per-market pairs summed: the SAME keyword in 10 markets counts 10 times (see "unique" below)
    failed = [r for r in rows if r["error"]]
    if failed:
        report["notes"].append(f"WARNING: {len(failed)} of {len(rows)} markets failed and were NOT searched: "
                               + ", ".join(f"{r['name']} ({r['error']})" for r in failed))
    # strongest first: the five-component score already weighs demand, ranking opportunity, relevance, conversion and usefulness
    everything = sorted(pool.values(), key=lambda i: (-(i.get("score_total") or 0), -(i["volume"] or 0)))
    ranked = [i for i in everything if not i["below_opportunity"]]
    sc = lambda i, k: (i.get("score") or {}).get(k)  # noqa: E731
    report["global"] = {
        "min_volume": min_vol, "competition": sorted(allowed), "min_ranking_opportunity": min_opp, "markets": rows,
        "eligible_keywords": len(everything), "preferred_keywords": len(ranked),
        "unique": {"discovered": len(uniq_found), "relevant": len(uniq_relevant), "markets_ok": ok, "markets_failed": len(failed)},
        "keywords": [{"keyword": i["keyword"], "market": i["market_name"], "volume": i["volume"], "competition": i.get("ads_competition"),
                      "relevance": sc(i, "feature_relevance"), "ranking_opportunity": sc(i, "ranking_opportunity"),
                      "conversion": sc(i, "conversion_potential"), "score": i.get("score_total"),
                      "also_seen": ", ".join(f"{s['market']} {s['volume']:,} ({s.get('competition') or '?'})" for s in i["also_seen"]),
                      "status": (f"below_ranking_opportunity (<{min_opp}): not selected" if i["below_opportunity"] else "queued")}
                     for i in everything]}
    log.info("Global discovery: %d markets, %d eligible keywords (%d preferred, ranking opportunity >= %s)",
             len(rows), len(everything), len(ranked), min_opp)
    return ranked


def set_status(report: dict, keyword: str, status: str) -> None:
    for k in (report.get("global") or {}).get("keywords", []):
        if k["keyword"] == keyword:
            k["status"] = status


def selection_reason(cfg: Config, kw: dict[str, Any], n_markets: int) -> str:
    also = [f"{s['market']} {s['volume']:,} ({s.get('competition') or '?'})" for s in kw.get("also_seen", []) if s["market"] != kw.get("market")]
    return (f"Strongest eligible keyword across {n_markets} markets: {kw['volume']:,} searches/month in "
            f"{kw.get('market_name') or kw.get('market')}, Google Ads competition {kw.get('ads_competition')}, "
            f"ranking opportunity {(kw.get('score') or {}).get('ranking_opportunity')} (>= {cfg.get('keyword_research.global_discovery.min_ranking_opportunity')} required), "
            f"relevance {(kw.get('score') or {}).get('feature_relevance')}, score {kw.get('score_total')}; "
            "the highest-scoring keyword (demand, ranking opportunity, relevance, conversion, usefulness) that met the volume, LOW Ads-competition and ranking-opportunity requirements and passed relevance, duplicate, planner and quality checks. Volumes are per country, never summed; Ads competition is advertising competition, not organic SEO difficulty."
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
