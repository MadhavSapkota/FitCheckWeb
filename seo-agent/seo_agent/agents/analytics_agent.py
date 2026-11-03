"""Analytics Agent: Search Console performance + CTA click events (GA4, optional) -> suggestions.

CTA clicks are Play Store link clicks, NOT installs. Installs are only visible in Google Play Console.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from .. import search_console
from ..config import Config, env
from ..log import log
from ..state import today


def search_performance(cfg: Config, report: dict) -> dict[str, Any] | None:
    if not cfg.get("seo.monitor_search_console"):
        return None
    if not search_console.available():
        report["notes"].append("Search Console not configured (GSC_SERVICE_ACCOUNT_JSON) - no organic performance data")
        return None
    perf = search_console.performance(cfg)
    snap = {k: perf[k] for k in ("end_date", "totals_7d", "totals_28d")}
    snap["top_queries_28d"] = sorted(perf["queries_28d"], key=lambda r: -r["impressions"])[:25]
    snap["top_pages_28d"] = sorted(perf["pages_28d"], key=lambda r: -r["impressions"])[:25]
    report["search_console"] = snap
    out = cfg.data_dir / "search-console" / f"{today()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    return perf


def article_performance(cfg: Config, perf: dict[str, Any], articles: dict[str, Any], report: dict) -> None:
    """Per published article: page impressions/clicks/position plus how its target keyword performs (28d)."""
    pages = {r["page"].rstrip("/"): r for r in perf.get("pages_28d", [])}
    queries = {r["query"].strip().lower(): r for r in perf.get("queries_28d", [])}
    rows = []
    for slug, a in sorted(articles.items(), key=lambda kv: kv[1]["published"]):
        p = pages.get(f"{cfg.base_url}/{cfg.get('site.blog_dir')}/{slug}", {})
        q = queries.get(a["keyword"].lower(), {})
        rows.append({"slug": slug, "cluster": a.get("cluster", "-"), "keyword": a["keyword"],
                     "impressions": p.get("impressions", 0), "clicks": p.get("clicks", 0),
                     "position": round(p["position"], 1) if p.get("position") else "-",
                     "keyword_impressions": q.get("impressions", 0),
                     "keyword_position": round(q["position"], 1) if q.get("position") else "-"})
    report["article_performance"] = rows


def cta_clicks(cfg: Config, report: dict) -> list[dict[str, Any]] | None:
    """Reads GA4 `play_store_click` events (Play Store outbound clicks, sent by every page incl. /blog/)."""
    prop = cfg.get("analytics.ga4_property_id")
    if not prop or not env("GSC_SERVICE_ACCOUNT_JSON"):
        report["notes"].append("Play Store clicks are tracked on the site (GA4 event play_store_click); set analytics.ga4_property_id "
                               "and give the service account Viewer access in GA4 to include the counts in this report")
        return None
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Filter, FilterExpression, Metric,
                                                    RunReportRequest)
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(
        json.loads(env("GSC_SERVICE_ACCOUNT_JSON")), scopes=["https://www.googleapis.com/auth/analytics.readonly"])
    client = BetaAnalyticsDataClient(credentials=creds)
    rows = []
    for days in (7, 28):
        req = RunReportRequest(
            property=f"properties/{prop}", dimensions=[Dimension(name="pagePath")], metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=(date.today() - timedelta(days=days)).isoformat(), end_date="yesterday")],
            dimension_filter=FilterExpression(filter=Filter(field_name="eventName",
                                                            string_filter=Filter.StringFilter(value="play_store_click"))))
        for r in client.run_report(req).rows:
            rows.append({"period": f"{days}d", "page": r.dimension_values[0].value, "cta_clicks": int(r.metric_values[0].value)})
    report["cta_clicks"] = rows
    log.info("Analytics: %d CTA click rows", len(rows))
    return rows


def suggestions(cfg: Config, perf: dict[str, Any] | None, clicks: list[dict[str, Any]] | None, report: dict) -> list[dict[str, Any]]:
    if not perf:
        return []
    opps = search_console.improvement_opportunities(cfg, perf)
    clicks_by_page = {c["page"]: c["cta_clicks"] for c in (clicks or []) if c["period"] == "28d"}
    out = []
    for o in opps[:10]:
        path = "/" + o["page"].split("/", 3)[-1] if o["page"].count("/") >= 3 else "/"
        out.append({k: o[k] for k in ("page", "reason", "impressions", "ctr", "position")} | {"cta_clicks_28d": clicks_by_page.get(path)})
    report["improvement_opportunities"] = out
    return opps
