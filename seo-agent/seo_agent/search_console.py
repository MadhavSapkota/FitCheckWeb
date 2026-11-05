"""Google Search Console (official Search Analytics API) - feedback loop over 7 and 28 days."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from .config import Config, env
from .http import with_backoff
from .log import log

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def available() -> bool:
    return bool(env("GSC_SERVICE_ACCOUNT_JSON"))


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(env("GSC_SERVICE_ACCOUNT_JSON"))
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


@with_backoff(attempts=3)
def _query(svc, prop: str, days: int, dims: list[str], end: date) -> list[dict[str, Any]]:
    start = end - timedelta(days=days - 1)
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": dims, "rowLimit": 1000}
    rows = svc.searchanalytics().query(siteUrl=prop, body=body).execute().get("rows", [])
    return [{**dict(zip(dims, r["keys"])), "clicks": r["clicks"], "impressions": r["impressions"],
             "ctr": r["ctr"], "position": r["position"]} for r in rows]


def performance(cfg: Config) -> dict[str, Any]:
    """Returns page and query performance for the last 7 and 28 days (GSC data lags ~2-3 days)."""
    svc = _service()
    prop = cfg.get("seo.search_console_property")
    end = date.today() - timedelta(days=3)
    out: dict[str, Any] = {"end_date": end.isoformat()}
    for days in (7, 28):
        out[f"pages_{days}d"] = _query(svc, prop, days, ["page"], end)
        out[f"queries_{days}d"] = _query(svc, prop, days, ["query"], end)
        out[f"page_queries_{days}d"] = _query(svc, prop, days, ["page", "query"], end)
        tot_c = sum(r["clicks"] for r in out[f"pages_{days}d"])
        tot_i = sum(r["impressions"] for r in out[f"pages_{days}d"])
        out[f"totals_{days}d"] = {"clicks": tot_c, "impressions": tot_i, "ctr": (tot_c / tot_i) if tot_i else 0.0}
    log.info("Search Console: 28d clicks=%s impressions=%s", out["totals_28d"]["clicks"], out["totals_28d"]["impressions"])
    return out


def improvement_opportunities(cfg: Config, perf: dict[str, Any]) -> list[dict[str, Any]]:
    """Pages with many impressions but low CTR, or ranking on page 2 (positions 8-20)."""
    min_imp = cfg.get("seo.min_impressions_for_improvement", 100)
    low_ctr = cfg.get("seo.low_ctr_threshold", 0.015)
    opps = []
    for r in perf.get("pages_28d", []):
        if r["impressions"] < min_imp:
            continue
        reason = None
        if r["ctr"] < low_ctr:
            reason = "low_ctr"
        elif 8 <= r["position"] <= 20:
            reason = "striking_distance"
        if reason:
            queries = sorted((q for q in perf.get("page_queries_28d", []) if q["page"] == r["page"]),
                             key=lambda q: -q["impressions"])[:10]
            opps.append({**r, "reason": reason, "top_queries": queries})
    return sorted(opps, key=lambda o: -o["impressions"])
