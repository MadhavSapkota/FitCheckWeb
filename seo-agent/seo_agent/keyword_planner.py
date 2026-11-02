"""Google Ads API - KeywordPlanIdeaService (official API; no scraping of the Keyword Planner UI).

Note: Keyword Planner "competition" is ADVERTISING competition. It is stored as ads_competition
and is never used as organic difficulty.
"""
from __future__ import annotations

from typing import Any

from .config import Config, env
from .log import log

# Google no longer requires a developer token (access is managed per Google Cloud project);
# GOOGLE_ADS_DEVELOPER_TOKEN is still passed when set, for older setups.
REQUIRED = ["GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CUSTOMER_ID"]


def available() -> bool:
    return all(env(k) for k in REQUIRED)


def keyword_ideas(cfg: Config, seeds: list[str]) -> list[dict[str, Any]]:
    from google.ads.googleads.client import GoogleAdsClient  # imported lazily

    conf = {
        "client_id": env("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": env("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": env("GOOGLE_ADS_REFRESH_TOKEN"),
        "use_proto_plus": True,
    }
    if env("GOOGLE_ADS_DEVELOPER_TOKEN"):
        conf["developer_token"] = env("GOOGLE_ADS_DEVELOPER_TOKEN")
    if env("GOOGLE_ADS_LOGIN_CUSTOMER_ID"):
        conf["login_customer_id"] = env("GOOGLE_ADS_LOGIN_CUSTOMER_ID").replace("-", "")
    client = GoogleAdsClient.load_from_dict(conf)
    service = client.get_service("KeywordPlanIdeaService")
    customer_id = env("GOOGLE_ADS_CUSTOMER_ID").replace("-", "")
    geo = client.get_service("GeoTargetConstantService").geo_target_constant_path(cfg.get("keyword_research.location_code"))

    out: dict[str, dict[str, Any]] = {}
    # The API accepts at most 20 seed keywords per request.
    for i in range(0, len(seeds), 20):
        req = client.get_type("GenerateKeywordIdeasRequest")
        req.customer_id = customer_id
        req.language = cfg.get("keyword_research.language_constant")
        req.geo_target_constants.append(geo)
        req.include_adult_keywords = False
        req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        req.keyword_seed.keywords.extend(seeds[i:i + 20])
        for idea in service.generate_keyword_ideas(request=req):
            m = idea.keyword_idea_metrics
            kw = idea.text.strip().lower()
            out[kw] = {
                "keyword": kw,
                "volume": int(m.avg_monthly_searches or 0),
                "ads_competition": m.competition.name if m.competition else None,
                "source": "google_ads_keyword_planner",
            }
            if len(out) >= cfg.get("keyword_research.max_ideas_per_run", 400):
                break
    log.info("Google Ads Keyword Planner returned %d ideas", len(out))
    return list(out.values())
