"""Search-intent duplicate detection.

A keyword is blocked only when an existing page already satisfies SUBSTANTIALLY THE SAME search intent:

* same FitCheck feature, AND
* same intent type: "tool" (the searcher wants an app/tool to do it: "virtual makeup try on", "skin analyzer app")
  or "informational" (the searcher wants an answer or guide: "what makeup suits my face"), AND
* the normalized intent signatures overlap strongly (synonyms folded: hairstyle/haircut -> hair, photo/face -> self ...).

Landing pages own TOOL intent for their declared `targets` (landing_pages.yaml). They never block an informational
guide, which instead links to the landing page. Blog articles block only same-feature, same-type, overlapping
queries. Word overlap alone (the old title/H2 "coverage" rule) never blocks a keyword. The Claude planner still makes
the final new / update / skip call with every existing page in view.
"""
from __future__ import annotations

from typing import Any

from .audit import tokens
from .config import Config

QUESTION = {"how", "what", "which", "why", "when", "can", "should", "does", "do", "is", "are", "where", "who"}
INFO_WORDS = {"ideas", "tips", "guide", "ways", "examples", "meaning", "rules", "chart", "vs", "inspiration"}
TOOL_WORDS = {"app", "apps", "ai", "online", "filter", "filters", "simulator", "generator", "checker", "analyzer",
              "analyser", "scanner", "try", "test", "virtual", "tool", "maker", "creator", "organizer", "planner",
              "quiz", "rater", "camera"}
SYNONYMS = {
    "hairstyle": "hair", "hairstyles": "hair", "haircut": "hair", "haircuts": "hair", "hairdo": "hair",
    "face": "self", "me": "self", "myself": "self", "yourself": "self", "picture": "self", "pictures": "self",
    "photo": "self", "photos": "self", "selfie": "self", "pic": "self",
    "test": "try", "preview": "try", "see": "try", "trying": "try",
    "clothes": "outfit", "clothing": "outfit", "outfits": "outfit", "dress": "outfit", "dresses": "outfit",
    "colour": "color", "colours": "color", "colors": "color", "matching": "match", "matches": "match",
    "closet": "wardrobe", "organizer": "organize", "organization": "organize", "organizing": "organize",
    "generator": "generate", "maker": "generate", "creator": "generate",
    "analyzer": "analyze", "analyser": "analyze", "analysis": "analyze", "scanner": "analyze", "checker": "check",
    "suits": "suit", "suited": "suit", "rate": "rating", "rater": "rating", "cosmetics": "makeup",
}
# Words that change the wording but not what the searcher wants.
MODIFIERS = {"app", "apps", "ai", "online", "free", "virtual", "best", "top", "new", "easy", "quick", "android", "the",
             "a", "an", "for", "with", "your", "my", "on", "in", "to", "of", "and", "or", "i", "you", "it", "is", "are",
             "how", "what", "which", "can", "does", "do", "should", "way", "ways", "using", "use", "tool", "2025", "2026",
             "different", "instantly", "live", "real", "time"}


def intent_type(kw: str) -> str:
    t = tokens(kw)
    if not t:
        return "informational"
    if t[0] in QUESTION or " how to " in f" {' '.join(t)} " or set(t) & INFO_WORDS:
        return "informational"
    return "tool" if set(t) & TOOL_WORDS else "informational"


def signature(kw: str) -> frozenset[str]:
    out = set()
    for w in tokens(kw):
        w = SYNONYMS.get(w, w)
        if w.endswith("s") and len(w) > 4 and w not in ("glasses", "jeans", "shorts"):
            w = SYNONYMS.get(w[:-1], w[:-1])
        if w not in MODIFIERS:
            out.add(w)
    return frozenset(out)


def overlap(a: str, b: str) -> float:
    sa, sb = signature(a), signature(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def landing_targets(cfg: Config) -> list[dict[str, str]]:
    """Tool-intent queries owned by pages that exist in the site: feature landing pages + config site.page_targets."""
    from . import landing
    out = []
    for p in landing.load(cfg).get("pages", []):
        if (cfg.site_root / p["slug"] / "index.html").exists():
            out += [{"page": f"{p['slug']}/index.html", "query": q} for q in p.get("targets", [])]
    for path, qs in (cfg.get("site.page_targets") or {}).items():
        if (cfg.site_root / path).exists():
            out += [{"page": path, "query": q} for q in qs]
    return out


def duplicate_of(cfg: Config, kw: str, feature: str | None, articles: dict[str, Any],
                 targets: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    """The existing page that already satisfies the same search intent, or None."""
    from .scoring import classify
    my_type = intent_type(kw)
    same_t = float(cfg.get("keyword_research.same_feature_overlap", 0.5))
    any_t = float(cfg.get("keyword_research.cluster_duplicate_overlap", 0.6))
    best = None
    for slug, a in articles.items():
        for q in [a["keyword"], *a.get("secondary_keywords", [])]:
            if intent_type(q) != my_type:
                continue  # a how-to guide and a tool page serve different searches
            limit = same_t if classify(cfg, q)[0] == feature else any_t
            o = overlap(kw, q)
            if o >= limit and (not best or o > best["overlap"]):
                best = {"kind": "article", "page": f"{cfg.get('site.blog_dir', 'blog')}/{slug}/", "slug": slug,
                        "query": q, "overlap": round(o, 2), "intent_type": my_type}
    if my_type == "tool":
        for t in (landing_targets(cfg) if targets is None else targets):
            if classify(cfg, t["query"])[0] != feature:
                continue
            o = overlap(kw, t["query"])
            if o >= any_t and (not best or o > best["overlap"]):
                best = {"kind": "landing", "page": t["page"], "slug": t["page"], "query": t["query"],
                        "overlap": round(o, 2), "intent_type": my_type}
    return best


def related_overlap(cfg: Config, kw: str, feature: str | None, articles: dict[str, Any]) -> float:
    """Highest same-feature, same-type overlap with an existing article (for the usefulness score)."""
    from .scoring import classify
    my_type = intent_type(kw)
    return max((overlap(kw, q) for a in articles.values() for q in [a["keyword"], *a.get("secondary_keywords", [])]
                if intent_type(q) == my_type and classify(cfg, q)[0] == feature), default=0.0)
