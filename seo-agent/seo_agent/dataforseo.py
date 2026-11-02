"""DataForSEO: organic keyword difficulty, search intent, top-10 SERP, and (labeled) fallback ideas."""
from __future__ import annotations

from typing import Any

from .config import Config, env
from .http import post_json
from .log import log

API = "https://api.dataforseo.com/v3"


def available() -> bool:
    return bool(env("DATAFORSEO_LOGIN") and env("DATAFORSEO_PASSWORD"))


def _call(path: str, payload: list[dict]) -> list[dict]:
    data = post_json(f"{API}/{path}", payload, auth=(env("DATAFORSEO_LOGIN"), env("DATAFORSEO_PASSWORD")))
    if data.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO {path}: {data.get('status_code')} {data.get('status_message')}")
    task = (data.get("tasks") or [{}])[0]
    if task.get("status_code") != 20000:
        raise RuntimeError(f"DataForSEO task {path}: {task.get('status_code')} {task.get('status_message')}")
    return task.get("result") or []


def _loc(cfg: Config) -> dict:
    return {"location_code": cfg.get("keyword_research.location_code"), "language_code": cfg.get("keyword_research.language")}


def keyword_difficulty(cfg: Config, keywords: list[str]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for i in range(0, len(keywords), 1000):
        res = _call("dataforseo_labs/google/bulk_keyword_difficulty/live", [{"keywords": keywords[i:i + 1000], **_loc(cfg)}])
        for item in (res[0].get("items") if res else None) or []:
            out[item["keyword"].lower()] = item.get("keyword_difficulty")
    return out


def search_intent(cfg: Config, keywords: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(keywords), 1000):
        res = _call("dataforseo_labs/google/search_intent/live",
                    [{"keywords": keywords[i:i + 1000], "language_code": cfg.get("keyword_research.language")}])
        for item in (res[0].get("items") if res else None) or []:
            intent = (item.get("keyword_intent") or {}).get("label")
            if intent:
                out[item["keyword"].lower()] = intent
    return out


def serp_top10(cfg: Config, keyword: str) -> dict[str, Any]:
    res = _call("serp/google/organic/live/advanced", [{"keyword": keyword, "depth": 10, **_loc(cfg)}])
    items = (res[0].get("items") if res else None) or []
    organic, questions = [], []
    for it in items:
        if it.get("type") == "organic" and len(organic) < 10:
            organic.append({"rank": it.get("rank_group"), "url": it.get("url"), "domain": it.get("domain"),
                            "title": it.get("title"), "description": it.get("description")})
        elif it.get("type") == "people_also_ask":
            for q in it.get("items") or []:
                if q.get("title"):
                    questions.append(q["title"])
    return {"keyword": keyword, "organic": organic, "questions": questions[:8]}


def keyword_ideas_fallback(cfg: Config, seeds: list[str]) -> list[dict[str, Any]]:
    """ALTERNATIVE PROVIDER (clearly labeled): DataForSEO Labs keyword ideas.

    Limitation: volumes are DataForSEO's estimates (clickstream + Google Ads derived), not values returned
    by your own Google Ads account, and may differ from Keyword Planner.
    """
    res = _call("dataforseo_labs/google/keyword_ideas/live",
                [{"keywords": seeds[:200], "limit": cfg.get("keyword_research.max_ideas_per_run", 400),
                  "include_serp_info": False, **_loc(cfg)}])
    out = []
    for item in (res[0].get("items") if res else None) or []:
        info = item.get("keyword_info") or {}
        props = item.get("keyword_properties") or {}
        intent = (item.get("search_intent_info") or {}).get("main_intent")
        out.append({"keyword": item["keyword"].lower(), "volume": int(info.get("search_volume") or 0),
                    "difficulty": props.get("keyword_difficulty"), "intent": intent,
                    "source": "dataforseo_labs (alternative to Google Ads Keyword Planner)"})
    log.info("DataForSEO Labs (fallback) returned %d ideas", len(out))
    return out
