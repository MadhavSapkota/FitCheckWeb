"""Weekly performance report, offline keyword re-scoring (threshold testing), and deployment verification.

Verified metrics (Search Console, GA4, Keyword Planner) are always labeled with their source; heuristic scores
are labeled as estimates. Play Store clicks are outbound link clicks, NOT installs.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any

from . import research, scoring
from .audit import crawl
from .config import Config
from .log import log
from .state import State, today


# ---------------------------------------------------------------- weekly report
def week_id(d: str | None = None) -> str:
    y, w, _ = date.fromisoformat(d or today()).isocalendar()
    return f"{y}-W{w:02d}"


def weekly_path(cfg: Config) -> Any:
    return cfg.data_dir / "reports" / f"weekly-{week_id()}.md"


def weekly_due(cfg: Config) -> bool:
    """Once per ISO week: on Monday, or on the first run of the week if Monday's run was missed."""
    return not weekly_path(cfg).exists()


def weekly(cfg: Config, state: State, perf: dict[str, Any] | None, clicks: list[dict[str, Any]] | None) -> str:
    L = [f"# FitCheck SEO weekly report — {week_id()}", ""]
    articles = state.data.get("articles", {})
    if not perf or "totals_7d" not in perf or "totals_28d" not in perf:
        L += ["_Search Console data unavailable this week (not configured or API error). No organic metrics shown._", ""]
    else:
        t7, t28 = perf["totals_7d"], perf["totals_28d"]
        pos7 = _avg_pos(perf.get("pages_7d", []))
        L += [f"## Organic search (Google Search Console, verified; data through {perf['end_date']})",
              "| period | clicks | impressions | CTR | avg position |", "|---|---|---|---|---|",
              f"| 7 days | {t7['clicks']} | {t7['impressions']} | {t7['ctr']:.2%} | {pos7} |",
              f"| 28 days | {t28['clicks']} | {t28['impressions']} | {t28['ctr']:.2%} | {_avg_pos(perf.get('pages_28d', []))} |", ""]
        q7 = sorted(perf.get("queries_7d", []), key=lambda r: (-r["clicks"], -r["impressions"]))[:10]
        L += ["## Best-performing keywords (7d)", "| query | feature | clicks | impressions | CTR | position |", "|---|---|---|---|---|---|",
              *[f"| {r['query']} | {scoring.classify(cfg, r['query'])[0] or '-'} | {r['clicks']} | {r['impressions']} | {r['ctr']:.2%} | {r['position']:.1f} |"
                for r in q7], "" if q7 else "| none yet | | | | | |", ""]
        p28 = sorted(perf.get("pages_28d", []), key=lambda r: (-r["clicks"], -r["impressions"]))[:10]
        L += ["## Best-performing pages (28d)", "| page | clicks | impressions | CTR | position |", "|---|---|---|---|---|",
              *[f"| {r['page']} | {r['clicks']} | {r['impressions']} | {r['ctr']:.2%} | {r['position']:.1f} |" for r in p28],
              "" if p28 else "| none yet | | | | |", ""]
        by: dict[str, dict[str, float]] = {}
        for r in perf.get("queries_28d", []):
            f = scoring.classify(cfg, r["query"])[0] or "unmatched"
            b = by.setdefault(f, {"clicks": 0, "impressions": 0, "queries": 0})
            b["clicks"] += r["clicks"]; b["impressions"] += r["impressions"]; b["queries"] += 1
        L += ["## Performance by feature (28d, queries classified by the feature map)",
              "| feature | articles | queries | clicks | impressions |", "|---|---|---|---|---|"]
        for fid in [*scoring.features(cfg), "unmatched"]:
            n_art = sum(1 for a in articles.values() if scoring.classify(cfg, a["keyword"])[0] == fid)
            b = by.get(fid, {"clicks": 0, "impressions": 0, "queries": 0})
            if n_art or b["queries"] or fid != "unmatched":
                L.append(f"| {fid} | {n_art} | {int(b['queries'])} | {int(b['clicks'])} | {int(b['impressions'])} |")
        L.append("")
    L += ["## Google Play outbound clicks (GA4 `play_store_click`; clicks, NOT installs)"]
    if clicks is None:
        L += ["- not available (set analytics.ga4_property_id and grant the service account GA4 Viewer access)"]
    else:
        rows = sorted((c for c in clicks if c["period"] == "7d"), key=lambda c: -c["cta_clicks"])[:15]
        L += [f"- {c['page']}: {c['cta_clicks']}" for c in rows] or ["- none in the last 7 days"]
    L += ["", "## Editorial mix (published articles vs. target)", "| feature | articles | share | target |", "|---|---|---|---|"]
    n = len(articles) or 1
    for fid, f in scoring.features(cfg).items():
        k = sum(1 for a in articles.values() if scoring.classify(cfg, a["keyword"])[0] == fid)
        L.append(f"| {fid} | {k} | {k / n:.0%} | {f.get('mix', 0)}% |")
    L += ["", "## Recommended improvements", *[f"- {r}" for r in recommendations(cfg, state, perf)], "",
          "_Search Console and GA4 figures are verified platform data. Feature attribution of queries uses the keyword "
          "feature map (heuristic). Installs are only visible in Google Play Console._"]
    return "\n".join(L) + "\n"


def _avg_pos(rows: list[dict[str, Any]]) -> str:
    imp = sum(r["impressions"] for r in rows)
    return f"{sum(r['position'] * r['impressions'] for r in rows) / imp:.1f}" if imp else "-"


def recommendations(cfg: Config, state: State, perf: dict[str, Any] | None) -> list[str]:
    out = []
    articles = state.data.get("articles", {})
    covered = {scoring.classify(cfg, a["keyword"])[0] for a in articles.values()}
    missing = [f for f in scoring.features(cfg) if f not in covered and f != "branded"]
    if missing:
        out.append(f"Features with no article yet: {', '.join(missing)} (the mix boost will favor them when keywords qualify).")
    if perf:
        for r in perf.get("pages_28d", []):
            if r["impressions"] >= 50 and 8 <= r["position"] <= 20:
                out.append(f"{r['page']}: striking distance (pos {r['position']:.1f}); add a section for its top queries.")
            elif r["impressions"] >= 100 and r["ctr"] < cfg.get("seo.low_ctr_threshold", 0.015):
                out.append(f"{r['page']}: low CTR {r['ctr']:.2%}; rewrite the title/meta description.")
        if not (perf.get("totals_28d") or {}).get("impressions"):
            out.append("No impressions yet: confirm the sitemap is submitted in Search Console and use URL Inspection on new pages.")
    runs = state.data.get("runs", [])[-7:]
    skips = sum(1 for r in runs if str(r.get("decision", "")).startswith("skip"))
    if runs and skips == len(runs):
        out.append("No article published in the last 7 runs: review the daily reports' per-feature skip reasons.")
    return out or ["No changes recommended this week."]


# ---------------------------------------------------------------- offline re-scoring (threshold testing)
def rescore(cfg: Config, state: State, thresholds=(40, 45, 50), top: int = 5) -> str:
    """Re-scores every stored keyword with the five-component system (no API calls) and compares thresholds.
    Also scores each feature's seed keywords whose volume has not been fetched yet (labeled 'volume pending')."""
    pages = crawl(cfg)["pages"]
    articles = state.data.get("articles", {})
    used = state.used_keywords()
    items = []
    for kw, e in state.data.get("keywords", {}).items():
        m = dict(e.get("latest") or {})
        i = {"keyword": kw, "volume": m.get("volume"), "source": m.get("source"), "difficulty": m.get("difficulty"),
             "gsc_impressions_28d": m.get("gsc_impressions_28d"), "gsc_position": m.get("gsc_position")}
        scoring.score(cfg, i, pages, articles)
        i["stored"] = True
        items.append(i)
    known = {i["keyword"] for i in items}
    for fid, f in scoring.features(cfg).items():
        for s in f.get("seeds", []):
            if s not in known:
                i = {"keyword": s, "volume": None, "source": "seed (volume pending: fetched from Keyword Planner on the next run)"}
                scoring.score(cfg, i, pages, articles)
                i["stored"] = False
                items.append(i)
                known.add(s)
    min_vol = cfg.get("keyword_research.minimum_monthly_searches", 100)

    def status(i, thr):
        if i["keyword"] in used:
            return "already published"
        dup = research.cluster_duplicate(cfg, i, articles)
        if dup:
            return f"duplicate intent of {dup}"

        if i["feature"] == "none" or not research.relevant(cfg, i["keyword"]):
            return "irrelevant/blocked"
        if i["volume"] is not None and i["volume"] < min_vol:
            return "low volume"
        if i["volume"] is None:
            return "volume pending"
        return scoring.qualifies(cfg, i, thr) or "QUALIFIES"

    L = [f"# Keyword re-score — {today()}", "",
         f"{sum(1 for i in items if i['stored'])} stored keywords (verified Keyword Planner volume) + "
         f"{sum(1 for i in items if not i['stored'])} feature seed keywords (volume pending, demand scored 0).", "",
         "Weights: " + ", ".join(f"{k} {v:.0%}" for k, v in {**scoring.DEFAULT_WEIGHTS, **(cfg.get('scoring.weights') or {})}.items()),
         f"Gates: feature_relevance >= {cfg.get('scoring.min_feature_relevance', 50)}, ranking_opportunity >= "
         f"{cfg.get('scoring.min_ranking_opportunity', 25)}, volume >= {min_vol}/mo, total >= threshold.", "",
         "## Threshold comparison (stored keywords with verified volume)",
         "| threshold | qualifying | features covered | avg feature relevance | avg conversion | qualifying keywords |",
         "|---|---|---|---|---|---|"]
    for thr in thresholds:
        q = [i for i in items if i["stored"] and status(i, thr) == "QUALIFIES"]
        feats = sorted({i["feature"] for i in q})
        avg = lambda k: f"{sum(i['score'][k] for i in q) / len(q):.0f}" if q else "-"  # noqa: E731
        names = ", ".join(f"{i['keyword']} ({i['score_total']})" for i in sorted(q, key=lambda i: -i["score_total"])[:12])
        L.append(f"| {thr} | {len(q)} | {len(feats)} ({', '.join(feats)}) | {avg('feature_relevance')} | {avg('conversion_potential')} | {names}{' …' if len(q) > 12 else ''} |")
    q = [i for i in items if i["stored"] and status(i, cfg.get("scoring.min_total", 45)) == "QUALIFIES"]
    for i in q:
        i["mix_boost"] = scoring.mix_boost(cfg, i["feature"], articles)
    q.sort(key=lambda i: -(i["score_total"] + i["mix_boost"]))
    L += ["", "## Next-run selection order (configured threshold, incl. editorial-mix adjustment)",
          "| rank | keyword | feature | score | mix adj. | ranking value |", "|---|---|---|---|---|---|",
          *[f"| {n} | {i['keyword']} | {i['feature']} | {i['score_total']} | {i['mix_boost']:+} | {i['score_total'] + i['mix_boost']:.1f} |"
            for n, i in enumerate(q[:8], 1)],
          "", "The Claude planner still checks each pick against existing pages (new / update / skip) before writing."]
    L += ["", "## Top keywords per feature",
          "rel = feature relevance, rank = ranking opportunity (estimate), dem = search demand, conv = conversion potential, "
          "use = content usefulness. Status uses the configured threshold "
          f"({cfg.get('scoring.min_total', 45)}).", ""]
    thr = cfg.get("scoring.min_total", 45)
    for fid, f in scoring.features(cfg).items():
        mine = sorted((i for i in items if i["feature"] == fid), key=lambda i: (-i["score_total"], -(i["volume"] or 0)))
        L += [f"### {f.get('label', fid)} (`{fid}`)",
              "| keyword | total | rel | rank | dem | conv | use | volume/mo | data source | status |", "|---|---|---|---|---|---|---|---|---|---|"]
        for i in mine[:top]:
            s = i["score"]
            L.append(f"| {i['keyword']} | **{i['score_total']}** | {s['feature_relevance']} | {s['ranking_opportunity']} | {s['search_demand']} | "
                     f"{s['conversion_potential']} | {s['content_usefulness']} | {i['volume'] if i['volume'] is not None else 'pending'} | "
                     f"{i['source']} | {status(i, thr)} |")
        if not mine:
            L.append("| (no keywords yet) | | | | | | | | | |")
        L.append("")
    off = [i for i in items if i["feature"] == "none"]
    L += [f"Unmatched (irrelevant) stored keywords: {len(off)}" + (f" e.g. {', '.join(i['keyword'] for i in off[:8])}" if off else "")]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- deployment verification
def verify(cfg: Config, state: State, wait: int = 600, paths: list[str] | None = None) -> list[str]:
    """Polls the live site until today's new/changed URLs return 200 with the expected canonical (or `wait` expires).
    Returns a list of failures (empty = verified). Never claims Google indexing."""
    import requests
    blog = cfg.get("site.blog_dir", "blog")
    urls = paths or [f"{cfg.base_url}/{blog}/{s}/" for s, a in state.data.get("articles", {}).items()
                     if a.get("published") == today() or a.get("modified") == today()]
    if not urls:
        log.info("verify: no new or updated URLs today")
        return []
    pending = {u: "not checked" for u in urls}
    deadline = time.time() + wait
    delay = 15
    while pending and time.time() < deadline:
        for u in list(pending):
            try:
                r = requests.get(u, timeout=20, headers={"User-Agent": "fitcheck-seo-agent-deploy-check"})
                if r.status_code == 200 and f'rel="canonical" href="{u}"' in r.text:
                    log.info("verify: live %s", u)
                    pending.pop(u)
                else:
                    pending[u] = f"HTTP {r.status_code}" + ("" if r.status_code != 200 else " (canonical not found yet)")
            except requests.RequestException as e:
                pending[u] = type(e).__name__
        if pending:
            time.sleep(min(delay, max(1, deadline - time.time())))
            delay = min(delay * 2, 120)
    return [f"{u}: {why}" for u, why in pending.items()]
