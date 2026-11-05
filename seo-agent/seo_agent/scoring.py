"""Five-component keyword scoring.

A transparent HEURISTIC for ranking topics. It is NOT a Google ranking formula and NOT keyword difficulty.
Each component is 0-100 and carries the evidence it was computed from:

  feature_relevance     how directly the query maps to a real FitCheck feature (config `features:`)
  ranking_opportunity   long-tail length, question format, head-term penalty, Search Console position,
                        measured organic KD (only when the paid DataForSEO source is enabled)
  search_demand         verified Keyword Planner volume (log scale); unverified volume scores 0 (never invented)
  conversion_potential  the feature's base app-download potential + app-intent words in the query
  content_usefulness    whether we can add something new: existing coverage, existing articles, app support

total = sum(weight_i * component_i) using `scoring.weights`.
"""
from __future__ import annotations

import math
from typing import Any

from . import intent
from .audit import Page, coverage_score, tokens
from .config import Config

QUESTION = ("how", "what", "which", "why", "when", "can", "should", "does", "is", "are", "do", "where", "who")
# Words that signal the searcher wants a tool they can use right now (the app), not just reading material.
APP_INTENT = ("app", "apps", "ai", "try on", "online", "free", "checker", "analyzer", "analyser", "analysis", "scanner",
              "simulator", "filter", "generator", "rate my", "on my face", "for me", "suits me", "suit me", "virtual",
              "tool", "planner", "organizer", "test", "quiz", "my face", "my skin", "my hair", "my outfit")
# Words that signal browsing/inspiration (useful traffic, but less likely to install an app).
BROWSE = ("ideas", "inspiration", "inspo", "pictures", "photos", "images", "meaning", "definition", "history", "diy",
          "costume", "party", "theme")

DEFAULT_WEIGHTS = {"feature_relevance": 0.30, "ranking_opportunity": 0.25, "search_demand": 0.15,
                   "conversion_potential": 0.20, "content_usefulness": 0.10}


def _padded(text: str) -> str:
    return " " + " ".join(tokens(text)) + " "


def _has(text: str, phrase: str) -> bool:
    return _padded(phrase) in _padded(text)


def features(cfg: Config) -> dict[str, dict[str, Any]]:
    return cfg.get("features") or {}


def classify(cfg: Config, kw: str) -> tuple[str | None, int, str]:
    """(feature id, relevance 0-100, evidence). Highest relevance wins; ties go to the feature listed first."""
    toks = set(tokens(kw))
    toks |= {t[:-1] for t in toks if t.endswith("s") and len(t) > 3}  # plural -> singular
    best: tuple[str | None, int, str] = (None, 0, "no FitCheck feature matched")
    for fid, f in features(cfg).items():
        cap = int(f.get("relevance_cap", 100))
        phrase = next((p for p in f.get("phrases", []) if _has(kw, p)), None)
        if phrase:
            r, why = 95, f"phrase '{phrase}'"
        else:
            hits = sorted(toks & {str(t).lower() for t in f.get("terms", [])})
            r, why = (min(85, 55 + 15 * (len(hits) - 1)), f"terms {hits}") if hits else (0, "")
        r = min(r, cap)
        if r > best[1]:
            best = (fid, r, f"{f.get('label', fid)}: {why}" + (f" (capped {cap})" if r == cap and cap < 95 else ""))
    return best


def ranking_opportunity(cfg: Config, i: dict[str, Any], feature: str | None) -> tuple[int, list[str]]:
    t = tokens(i["keyword"])
    n = len(t)
    score = {1: 5, 2: 15, 3: 35, 4: 50}.get(n, 65 if n >= 5 else 5)
    why = [f"{n}-word query"]
    if t[:1] and t[0] in QUESTION:
        score += 15; why.append("question format")
    v = i.get("volume")
    if v:
        if v > 50000:
            score -= 35; why.append("head term >50k/mo (very competitive)")
        elif v > 10000:
            score -= 20; why.append("broad term >10k/mo")
        elif v > 5000:
            score -= 10; why.append("term >5k/mo")
    pos = i.get("gsc_position")
    if pos is not None and (i.get("gsc_impressions_28d") or 0) >= 10:
        bonus = 30 if pos <= 10 else 20 if pos <= 30 else 10
        score += bonus; why.append(f"Search Console: site already shows at ~{pos}")
    if i.get("difficulty") is not None:
        kd = i["difficulty"]
        score += 20 if kd <= 15 else 5 if kd <= cfg.get("keyword_research.maximum_organic_difficulty", 25) else -40
        why.append(f"measured organic KD {kd} (DataForSEO)")
    else:
        why.append("organic difficulty not measured (estimate)")
    if feature == "branded":
        score += 30; why.append("own brand query")
    return max(0, min(100, score)), why


def search_demand(i: dict[str, Any]) -> tuple[int, str]:
    v = i.get("volume")
    if v:
        return max(0, min(100, round(20 * math.log10(v)))), f"verified {v}/mo ({i.get('source', 'unknown source')})"
    imp = i.get("gsc_impressions_28d") or 0
    if imp:
        return min(40, int(imp)), f"volume unverified; {imp} Search Console impressions (28d)"
    return 0, "volume unverified (scored 0, never estimated)"


def conversion_potential(cfg: Config, kw: str, feature: str | None) -> tuple[int, list[str]]:
    f = features(cfg).get(feature or "", {})
    score = int(f.get("conversion", 20))
    why = [f"feature base {score}"]
    hits = [w for w in APP_INTENT if _has(kw, w)]
    if hits:
        score += min(20, 8 * len(hits)); why.append(f"app-intent words {hits}")
    browse = [w for w in BROWSE if _has(kw, w)]
    if browse:
        score -= 10; why.append(f"browsing words {browse}")
    return max(0, min(100, score)), why


def content_usefulness(cfg: Config, kw: str, feature: str | None, pages: list[Page],
                       articles: dict[str, Any]) -> tuple[int, list[str], float, str | None]:
    score, why = 55, []
    if feature and feature in features(cfg):
        score += 15; why.append("FitCheck has a matching feature to demonstrate")
    t = tokens(kw)
    if t[:1] and t[0] in QUESTION:
        score += 10; why.append("clear problem to solve")
    same = [s for s, a in articles.items() if feature and classify(cfg, a["keyword"])[0] == feature]
    if feature and not same:
        score += 15; why.append("no article on this feature yet")
    # Same-feature, same-intent-type articles that partly answer this already reduce the added value.
    rel = intent.related_overlap(cfg, kw, feature, articles)
    if rel >= 0.3:
        score -= 20; why.append(f"partly answered by an existing {intent.intent_type(kw)} article (overlap {rel:.2f})")
    cov, page = coverage_score(kw, pages)  # informational only: shared words never block a keyword
    return max(0, min(100, score)), why, cov, page


def score(cfg: Config, i: dict[str, Any], pages: list[Page], articles: dict[str, Any]) -> dict[str, Any]:
    """Adds feature, the five components, total, and evidence to keyword idea `i` (in place) and returns it."""
    kw = i["keyword"]
    feature, rel, rel_why = classify(cfg, kw)
    ro, ro_why = ranking_opportunity(cfg, i, feature)
    sd, sd_why = search_demand(i)
    cp, cp_why = conversion_potential(cfg, kw, feature)
    cu, cu_why, cov, page = content_usefulness(cfg, kw, feature, pages, articles)
    comps = {"feature_relevance": rel, "ranking_opportunity": ro, "search_demand": sd,
             "conversion_potential": cp, "content_usefulness": cu}
    w = {**DEFAULT_WEIGHTS, **(cfg.get("scoring.weights") or {})}
    total = round(sum(w[k] * v for k, v in comps.items()), 1)
    i.update({
        "feature": feature or "none", "cluster": feature or "general-style",
        "score": comps, "score_total": total,
        "opportunity_estimate": total,  # kept for older reports/state readers
        "score_evidence": {"feature_relevance": rel_why, "ranking_opportunity": ro_why, "search_demand": sd_why,
                           "conversion_potential": cp_why, "content_usefulness": cu_why},
        "opportunity_evidence": ro_why,
        "intent_type": intent.intent_type(kw),
        "coverage": round(cov, 2), "covering_page": page,  # word overlap, informational only
        "data_sources": sorted({str(i.get("source") or "none")} | ({"search_console"} if i.get("gsc_impressions_28d") else set())),
    })
    return i


def qualifies(cfg: Config, i: dict[str, Any], min_total: float | None = None) -> str | None:
    """None when the scores qualify, otherwise the rejection reason."""
    s = i["score"]
    if s["feature_relevance"] < cfg.get("scoring.min_feature_relevance", 50):
        return "rejected_low_feature_relevance"
    if s["ranking_opportunity"] < cfg.get("scoring.min_ranking_opportunity", 25):
        return "rejected_head_term_low_ranking_opportunity"
    thr = cfg.get("scoring.min_total", 45) if min_total is None else min_total
    f = features(cfg).get(i.get("feature") or "", {})
    thr = max(thr, float(f.get("min_total", 0)))  # optional stricter per-feature bar (e.g. low-conversion trends)
    if i["score_total"] < thr:
        return "rejected_low_score"
    return None


def mix_boost(cfg: Config, feature: str, articles: dict[str, Any]) -> float:
    """Editorial-mix adjustment: up to +mix_boost_max for features below their target share, down to
    -mix_penalty_max for features already well above it, so every feature gets coverage over time."""
    f = features(cfg).get(feature)
    if not f:
        return 0.0
    target = float(f.get("mix", 0)) / 100
    n = len(articles)
    have = sum(1 for a in articles.values() if classify(cfg, a["keyword"])[0] == feature)
    share = have / n if n else 0.0
    gap = target - share
    return round(max(-float(cfg.get("scoring.mix_penalty_max", 10)), min(float(cfg.get("scoring.mix_boost_max", 5)), gap * 50)), 1)
