"""Keyword discovery, filtering, and selection."""
from __future__ import annotations

from typing import Any

from . import dataforseo, keyword_planner
from .audit import STOP, Page, coverage_score, tokens
from .config import Config
from .log import log
from .state import State


class NoProvider(RuntimeError):
    pass


def discover(cfg: Config, seeds: list[str] | None = None) -> list[dict[str, Any]]:
    seeds = seeds or list(cfg.get("keyword_research.seed_keywords", []))
    if cfg.get("keyword_research.source") == "google_ads_keyword_planner" and keyword_planner.available():
        try:
            return keyword_planner.keyword_ideas(cfg, seeds)
        except Exception as e:  # noqa: BLE001 - e.g. developer token still on Test access
            log.error("Google Ads Keyword Planner failed: %s", str(e)[:300])
            if not cfg.get("keyword_research.fallback_source"):
                raise NoProvider(f"Google Ads Keyword Planner unavailable ({type(e).__name__}); "
                                 "check developer token access level") from e
    elif cfg.get("keyword_research.source") == "google_ads_keyword_planner":
        log.warning("Google Ads credentials not configured")
    if "dataforseo_labs" in (cfg.get("keyword_research.fallback_source"), cfg.get("keyword_research.source")):
        if dataforseo.available():
            log.warning("Using ALTERNATIVE provider DataForSEO Labs for keyword volumes (not Google Ads data)")
            return dataforseo.keyword_ideas_fallback(cfg, seeds)
    raise NoProvider("No keyword volume provider available; metrics are never fabricated, so nothing is published")


def relevant(cfg: Config, kw: str) -> bool:
    low = kw.lower()
    if any(b in low for b in cfg.get("keyword_research.blocked_terms", [])):
        return False
    toks = set(tokens(low))
    toks |= {t[:-1] for t in toks if t.endswith("s") and len(t) > 3}  # simple plural match: colors -> color
    terms = set(cfg.get("keyword_research.relevance_terms", []))
    if not toks & terms:
        return False
    # skip navigational queries for other brands/apps (heuristic: 'app' + a capitalized brand is unknowable;
    # keep it simple - skip explicit competitor/download patterns)
    return not any(x in low for x in ("login", "sign in", "customer service", "near me", " jobs", "salary"))


def relevance_score(cfg: Config, kw: str) -> float:
    toks = {t[:-1] if t.endswith("s") and len(t) > 3 else t for t in tokens(kw)} - STOP
    core = {"outfit", "fit", "style", "stylist", "fashion", "makeup", "hair", "hairstyle", "color", "ai", "wear"}
    return len(toks & core) / max(1, len(toks))


def measured_difficulty(cfg: Config) -> bool:
    return cfg.get("keyword_research.organic_difficulty_source") == "dataforseo"


INFO_WORDS = ("how", "what", "which", "why", "when", "can", "should", "ideas", "tips", "guide", "ways", "does", "to wear", "with")
COMMERCIAL_WORDS = ("best", "app", "apps", "vs", "review", "reviews", "tool", "free", "top", "alternative")


def heuristic_intent(kw: str) -> str:
    """Rule-based intent used only in free mode (no intent API). Labeled as heuristic in state."""
    t = f" {kw.lower()} "
    if any(f" {w} " in t for w in ("buy", "price", "coupon", "discount", "near me", "download")):
        return "transactional"
    if any(f" {w} " in t for w in COMMERCIAL_WORDS):
        return "commercial"
    return "informational"


def enrich(cfg: Config, ideas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds ORGANIC difficulty (DataForSEO KD) and intent. Ads competition is never used for this."""
    if not measured_difficulty(cfg):
        for i in ideas:
            i["difficulty"] = None
            i["difficulty_note"] = "not measured (free mode: long-tail rule applied instead)"
            i["intent"] = i.get("intent") or heuristic_intent(i["keyword"])
        return ideas
    if not dataforseo.available():
        raise NoProvider("DataForSEO credentials missing: organic difficulty is required and is never guessed")
    need_kd = [i["keyword"] for i in ideas if i.get("difficulty") is None]
    if need_kd:
        kd = dataforseo.keyword_difficulty(cfg, need_kd)
        for i in ideas:
            if i.get("difficulty") is None:
                i["difficulty"] = kd.get(i["keyword"])
    need_int = [i["keyword"] for i in ideas if not i.get("intent")]
    if need_int:
        intents = dataforseo.search_intent(cfg, need_int)
        for i in ideas:
            i["intent"] = i.get("intent") or intents.get(i["keyword"])
    return ideas


def cluster_of(cfg: Config, kw: str) -> str:
    """Topic cluster (pillar) a keyword belongs to, from keyword_research.topic_clusters. First match wins."""
    toks = set(tokens(kw))
    for name, terms in (cfg.get("keyword_research.topic_clusters") or {}).items():
        if toks & {t.lower() for t in terms}:
            return name
    return "general-style"


def cluster_duplicate(cfg: Config, i: dict[str, Any], articles: dict[str, Any]) -> str | None:
    """Slug of a published article in the same cluster whose target query is near-identical (token Jaccard)."""
    mine = set(tokens(i["keyword"])) - STOP
    limit = cfg.get("keyword_research.cluster_duplicate_overlap", 0.6)
    for slug, a in articles.items():
        if a.get("cluster", cluster_of(cfg, a["keyword"])) != i.get("cluster"):
            continue
        for other in [a["keyword"], *a.get("secondary_keywords", [])]:
            o = set(tokens(other)) - STOP
            if mine and o and len(mine & o) / len(mine | o) >= limit:
                return slug
    return None


def order_by_cluster(cands: list[dict[str, Any]], articles: dict[str, Any]) -> list[dict[str, Any]]:
    """Best opportunity first; on ties prefer clusters that already have articles (build topical depth with
    supporting long-tail pages), then clusters with none."""
    have: dict[str, int] = {}
    for a in articles.values():
        have[a.get("cluster", "")] = have.get(a.get("cluster", ""), 0) + 1
    return sorted(cands, key=lambda i: (-(i.get("opportunity_estimate") or 0), -min(have.get(i.get("cluster"), 0), 1),
                                        -(i.get("volume") or 0)))


def is_editorial(cfg: Config, i: dict[str, Any]) -> bool:
    return bool(cfg.get("keyword_research.unverified_topics.enabled")) and str(i.get("source", "")).startswith("editorial")


def shortlist(cfg: Config, ideas: list[dict[str, Any]], pages: list[Page], state: State) -> list[dict[str, Any]]:
    min_vol = cfg.get("keyword_research.minimum_monthly_searches", 100)
    min_gsc = cfg.get("keyword_research.min_gsc_impressions_if_volume_unverified", 30)
    min_opp = cfg.get("keyword_research.min_opportunity_estimate", 50)
    min_opp_editorial = cfg.get("keyword_research.unverified_topics.min_opportunity_estimate", 40)
    max_kd = cfg.get("keyword_research.maximum_organic_difficulty", 25)
    intents = set(cfg.get("keyword_research.allowed_intents", ["informational", "commercial"]))
    cov_thr = cfg.get("content.coverage_threshold", 0.6)
    used = state.used_keywords()
    out = []
    for i in ideas:
        kw = i["keyword"]
        vol = i.get("volume")
        reason = None
        if not relevant(cfg, kw):
            reason = "rejected_irrelevant"
        elif vol is not None and vol < min_vol:
            reason = "rejected_low_volume"
        elif vol is None and i.get("gsc_impressions_28d", 0) < min_gsc and not is_editorial(cfg, i):
            reason = "rejected_volume_unverified_and_little_search_console_evidence"
        elif measured_difficulty(cfg) and i.get("difficulty") is None:
            reason = "rejected_no_organic_difficulty_data"
        elif measured_difficulty(cfg) and i["difficulty"] > max_kd:
            reason = "rejected_difficulty"
        elif i.get("intent") not in intents:
            reason = "rejected_intent"
        elif i.get("opportunity_estimate", 0) < (min_opp_editorial if is_editorial(cfg, i) else min_opp):
            reason = "rejected_low_opportunity_estimate"
        elif kw in used:
            reason = "rejected_already_targeted"
        elif state.rejected_recently(kw):
            reason = "rejected_recently_failed_quality_gate"
        else:
            cov, page = coverage_score(kw, pages)
            i["coverage"], i["covering_page"] = round(cov, 2), page
            if cov >= cov_thr:
                reason = "covered_by_existing_page"
        i["relevance"] = round(relevance_score(cfg, kw), 2)
        state.record_keyword(kw, i, reason or "candidate")
        if reason is None or reason == "covered_by_existing_page":
            i["decision"] = reason or "candidate"
            out.append(i)
    out.sort(key=lambda i: (-(i["decision"] == "candidate"), -i.get("opportunity_estimate", 0), -(i.get("volume") or 0)))
    log.info("Shortlisted %d qualifying keywords (of %d ideas)", len(out), len(ideas))
    return out
