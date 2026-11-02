"""Daily SEO agent orchestrator.

Usage:
  python -m seo_agent.main run [--dry-run]     # full daily pipeline
  python -m seo_agent.main check               # site validation only ("build test"); exit 1 on errors
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from typing import Any

from . import budget, content, publisher, quality, research
from .agents import analytics_agent, editor_agent, keyword_agent, strategy_agent, writer_agent
from .budget import Budget, BudgetExceeded
from .audit import broken_links, crawl
from .config import load_app_facts, load_config
from .log import setup_logging
from .state import State, today


# ---------------------------------------------------------------- validation ("build")
def validate_site(cfg) -> list[str]:
    """Static site has no build step; this is the build test: every page parses, has a title,
    no broken internal links, and generated articles have exactly one H1 and valid JSON-LD."""
    errors = []
    result = crawl(cfg)
    for p in result["pages"]:
        if not p.title:
            errors.append(f"{p.path}: missing <title>")
        bl = broken_links(cfg, p)
        if bl:
            errors.append(f"{p.path}: broken internal links {bl[:5]}")
        if p.path.startswith(cfg.get("site.blog_dir") + "/"):
            if len(p.h1) != 1:
                errors.append(f"{p.path}: expected one <h1>, found {len(p.h1)}")
            raw = (cfg.site_root / p.path).read_text(encoding="utf-8")
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, flags=re.S):
                try:
                    json.loads(block)
                except json.JSONDecodeError as e:
                    errors.append(f"{p.path}: invalid JSON-LD ({e})")
    sm = cfg.site_root / "sitemap.xml"
    if sm.exists():
        try:
            import xml.etree.ElementTree as ET
            ET.parse(sm)
        except Exception as e:  # noqa: BLE001
            errors.append(f"sitemap.xml: invalid XML ({e})")
    return errors


# ---------------------------------------------------------------- steps
def improve_existing(cfg, state: State, facts: dict, opps: list, dry: bool, report: dict) -> None:
    """Improve OUR generated articles that underperform in Search Console. Max once per 28 days per page,
    and only when the change is substantive (never date-only freshness edits)."""
    if not cfg.get("publishing.update_existing_pages") or not content.available():
        return
    articles = state.data["articles"]
    blog_prefix = f"{cfg.base_url}/{cfg.get('site.blog_dir')}/"
    for o in opps:
        if state.updates_today() >= cfg.get("publishing.max_page_updates_per_day", 2):
            break
        if not o["page"].startswith(blog_prefix):
            continue  # hand-built pages: recommendations only (layout is never rewritten)
        slug = o["page"][len(blog_prefix):].strip("/")
        a = articles.get(slug)
        if not a or (a.get("last_improved") and state_days_since(a["last_improved"]) < 28):
            continue
        src = json.loads(publisher.source_path(cfg, slug).read_text(encoding="utf-8"))
        imp = content.improve(cfg, src, o, facts)
        if not imp.get("substantive") or not (imp.get("new_section_html") or imp.get("new_faqs")):
            report["notes"].append(f"{slug}: improvement judged non-substantive; left unchanged")
            continue
        cand = dict(src)
        cand["title"] = imp.get("title") or src["title"]
        cand["meta_description"] = imp.get("meta_description") or src["meta_description"]
        cand["body_html"] = src["body_html"] + "\n" + (imp.get("new_section_html") or "")
        cand["faqs"] = (src.get("faqs") or []) + (imp.get("new_faqs") or [])
        cand["modified"] = today()
        rev = writer_agent.review(cfg, cand, facts)
        html_ = publisher.render_article(cfg, cand, publisher.pick_related(cfg, {**articles, slug: cand}, slug))
        gate = quality.check(cfg, kw=src["metrics"], intent=src["intent"], article=cand, rendered_html=html_,
                             url=publisher.article_url(cfg, slug), slug=slug, review=rev, existing=crawl(cfg)["pages"],
                             skip_pages=(f"{cfg.get('site.blog_dir')}/{slug}/index.html",))
        if not gate["passed"]:
            report["notes"].append(f"{slug}: improvement rejected by quality gate: {gate['failures']}")
            continue
        if dry:
            report["changes"].append(f"[dry-run] would improve {slug}")
            continue
        cand["last_improved"] = today()
        cand.setdefault("changelog", []).append({"date": today(), "change": imp.get("change_summary"), "reason": o["reason"]})
        editor_agent.publish(cfg, cand, articles)
        state.data["page_updates"].append({"date": today(), "page": slug, "change": imp.get("change_summary")})
        report["changes"].append(f"improved {slug}: {imp.get('change_summary')}")


def state_days_since(iso: str) -> int:
    from datetime import date
    return (date.fromisoformat(today()) - date.fromisoformat(iso)).days


def new_article(cfg, state: State, facts: dict, pages, perf, dry: bool, report: dict) -> None:
    if state.published_today() >= cfg.get("publishing.max_new_articles_per_day", 1):
        report["notes"].append("Daily new-article limit already reached")
        return
    if not research.measured_difficulty(cfg):
        report["notes"].append("Low-cost mode: organic difficulty NOT measured; a labeled opportunity estimate is used instead")
    if not content.available():
        report["notes"].append("ANTHROPIC_API_KEY missing - content generation skipped")
        return
    short = keyword_agent.run(cfg, state, pages, perf, report)
    report["shortlist"] = [{k: i.get(k) for k in ("keyword", "volume", "difficulty", "opportunity_estimate", "gsc_impressions_28d",
                                                  "intent", "decision", "covering_page", "source")} for i in short[:15]]
    candidates = [i for i in short if i["decision"] == "candidate"]
    if not candidates:
        report["decision"] = "skip: no keyword met the volume/evidence, opportunity, intent, relevance and coverage criteria"
        return
    articles = state.data["articles"]
    for kw in candidates[: cfg.get("keyword_research.max_candidates_per_run", 3)]:
        plan, serp = strategy_agent.decide(cfg, kw, pages, facts)
        attempt = {"keyword": kw["keyword"], "volume": kw.get("volume"), "opportunity_estimate": kw.get("opportunity_estimate"),
                   "evidence": kw.get("opportunity_evidence"), "plan_action": plan.get("action"), "plan_reason": plan.get("reason")}
        report["attempts"].append(attempt)
        if plan.get("action") != "new":
            state.record_keyword(kw["keyword"], kw, f"planner_{plan.get('action')}: {str(plan.get('reason', ''))[:120]}")
            continue
        if plan["intent"] not in cfg.get("keyword_research.allowed_intents"):
            state.record_keyword(kw["keyword"], kw, f"rejected_intent_after_planning:{plan['intent']}")
            continue
        slug = re.sub(r"[^a-z0-9-]+", "-", (plan.get("slug") or kw["keyword"]).lower()).strip("-")[:70]
        if slug in articles or publisher.article_path(cfg, slug).exists():
            slug = f"{slug}-guide"
        links = [{"href": "/", "title": "FitCheck AI home"}, {"href": "/how-it-works.html", "title": "How FitCheck AI works"}] + \
                [{"href": f"/{cfg.get('site.blog_dir')}/{s}/", "title": a["h1"]} for s, a in articles.items()]
        a = writer_agent.write(cfg, kw, plan, serp, slug, links, facts)
        rev = writer_agent.review(cfg, a, facts)
        html_ = publisher.render_article(cfg, a, publisher.pick_related(cfg, {**articles, slug: a}, slug))
        gate = quality.check(cfg, kw=kw, intent=plan["intent"], article=a, rendered_html=html_, url=publisher.article_url(cfg, slug),
                             slug=slug, review=rev, existing=pages)
        attempt["quality_gate"], attempt["review_notes"] = gate, rev.get("notes")
        if not gate["passed"]:
            state.record_keyword(kw["keyword"], kw, f"rejected_by_quality_gate: {'; '.join(gate['failures'])[:300]}")
            continue
        if dry:
            report["decision"] = f"[dry-run] would publish /{cfg.get('site.blog_dir')}/{slug}/"
            return
        a["quality_gate"] = {k: gate[k] for k in ("word_count", "keyword_density", "warnings")}
        editor_agent.publish(cfg, a, articles)
        state.record_keyword(kw["keyword"], kw, f"published:{slug}")
        report["decision"] = f"published /{cfg.get('site.blog_dir')}/{slug}/ for '{kw['keyword']}'"
        report["changes"].append(f"new article blog/{slug}/index.html")
        return
    report["decision"] = "skip: no candidate passed planning + quality gate today"


def write_report(cfg, report: dict, dry: bool) -> None:
    lines = [f"# SEO agent report — {today()}", "", f"**Decision:** {report.get('decision', 'n/a')}", ""]
    if report["errors"]:
        lines += ["## Errors", *[f"- {e}" for e in report["errors"]], ""]
    if report["changes"]:
        lines += ["## Changes", *[f"- {c}" for c in report["changes"]], ""]
    if report["notes"]:
        lines += ["## Notes", *[f"- {n}" for n in report["notes"]], ""]
    if report.get("site_issues") or report.get("page_issues"):
        lines += ["## Audit findings", *[f"- site: {i}" for i in report.get("site_issues", [])],
                  *[f"- {p}: {', '.join(v)}" for p, v in report.get("page_issues", {}).items()], ""]
    if report.get("shortlist"):
        lines += ["## Keyword shortlist", "| keyword | volume | opportunity estimate* | GSC impr. 28d | intent | decision |", "|---|---|---|---|---|---|",
                  *[f"| {k['keyword']} | {k['volume'] if k['volume'] is not None else 'unverified'} | {k['opportunity_estimate']} | {k.get('gsc_impressions_28d') or '-'} | {k['intent']} | {k['decision']} |" for k in report["shortlist"]],
                  "", "*Opportunity estimate = labeled heuristic from available evidence, NOT keyword difficulty.", ""]
    if report["attempts"]:
        lines += ["## Attempts", "```json", json.dumps(report["attempts"], indent=2)[:12000], "```", ""]
    if report.get("search_console"):
        sc = report["search_console"]
        lines += ["## Search Console (data through %s)" % sc["end_date"],
                  f"- 7d: clicks {sc['totals_7d']['clicks']}, impressions {sc['totals_7d']['impressions']}, CTR {sc['totals_7d']['ctr']:.2%}",
                  f"- 28d: clicks {sc['totals_28d']['clicks']}, impressions {sc['totals_28d']['impressions']}, CTR {sc['totals_28d']['ctr']:.2%}", ""]
        if report.get("improvement_opportunities"):
            lines += ["Improvement opportunities:", *[f"- {o['page']} ({o['reason']}, {o['impressions']} impr, CTR {o['ctr']:.2%}, pos {o['position']:.1f})"
                                                       for o in report["improvement_opportunities"]], ""]
    if report.get("cta_clicks") is not None:
        lines += ["## CTA clicks (Play Store link clicks - NOT installs)", *([f"- {c['period']} {c['page']}: {c['cta_clicks']}" for c in report["cta_clicks"]] or ["- none"]), ""]
    if report.get("usage"):
        u = report["usage"]
        lines += ["## API usage", f"- Claude calls this run: {u['calls_this_run']}; month {u['month']}: {u['claude_calls']} calls, ~${u['usd_estimate']:.2f} (estimate)", ""]
    lines += ["_CTA clicks are Play Store link clicks, not confirmed installs (see Google Play Console for installs). Sitemap submission does not guarantee indexing._"]
    text = "\n".join(lines) + "\n"
    path = cfg.data_dir / "reports" / f"{today()}.md"
    if dry:
        print(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(dry: bool) -> int:
    cfg = load_config()
    setup_logging(None if dry else str(cfg.data_dir / "logs" / f"{today()}.log"))
    state = State(cfg.data_dir / "state.json")
    facts = load_app_facts()
    bud = Budget(cfg, state.data)
    budget.set_current(bud)
    report: dict[str, Any] = {"changes": [], "notes": [], "errors": [], "attempts": []}
    try:
        audit = crawl(cfg)
        report["site_issues"] = audit["site_issues"]
        report["page_issues"] = {p.path: p.issues for p in audit["pages"] if p.issues}
        if not dry:
            editor_agent.site_basics(cfg, state, audit, report)
        perf, clicks, opps = None, None, []
        try:
            perf = analytics_agent.search_performance(cfg, report)
            try:
                clicks = analytics_agent.cta_clicks(cfg, report)
            except Exception as e:  # noqa: BLE001
                report["errors"].append(f"analytics (CTA clicks): {e}")
            opps = analytics_agent.suggestions(cfg, perf, clicks, report)
        except Exception as e:  # noqa: BLE001 - feedback loop must not block the run
            report["errors"].append(f"search console: {e}")
        try:
            improve_existing(cfg, state, facts, opps, dry, report)
            new_article(cfg, state, facts, crawl(cfg)["pages"], perf, dry, report)
        except research.NoProvider as e:
            report["decision"] = f"skip: {e}"
        except BudgetExceeded as e:
            report["decision"] = f"skip: spending limit - {e}"
        if not dry:
            editor_agent.finalize(cfg, state.data["articles"], report)
            report["errors"] += validate_site(cfg)
    except Exception as e:  # noqa: BLE001
        report["errors"].append(f"fatal: {e}")
        report["errors"].append(traceback.format_exc()[-1500:])
    finally:
        budget.set_current(None)
    report.setdefault("decision", "no new article")
    report["usage"] = bud.summary()
    if not dry:
        state.add_run({"decision": report["decision"], "changes": len(report["changes"]), "errors": len(report["errors"]),
                       "claude_calls": bud.calls_this_run})
        state.save()
    write_report(cfg, report, dry)
    return 2 if any(e.startswith("fatal") or ": broken internal links" in e or "invalid" in e or "expected one <h1>" in e
                    for e in report["errors"]) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "check"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.command == "check":
        setup_logging()
        errs = validate_site(load_config())
        for e in errs:
            print("ERROR", e)
        print("site validation:", "FAILED" if errs else "OK")
        return 1 if errs else 0
    return run(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
