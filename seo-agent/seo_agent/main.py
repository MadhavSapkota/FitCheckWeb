"""Daily SEO agent orchestrator.

Usage:
  python -m seo_agent.main run [--dry-run]     # full daily pipeline
  python -m seo_agent.main check               # site validation only ("build test"); exit 1 on errors
  python -m seo_agent.main rescore             # offline: re-score stored keywords, compare thresholds 40/45/50
  python -m seo_agent.main weekly [--dry-run]  # weekly performance report (also runs automatically once a week)
  python -m seo_agent.main verify [--wait N]   # after deploy: today's new URLs return 200 with the right canonical
  python -m seo_agent.main landing             # render feature landing pages from landing_pages.yaml
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from typing import Any

from . import budget, content, publisher, quality, reports, research
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


# Gate failures a rewrite cannot fix (keyword data, not article content).
NOT_REVISABLE = ("volume_", "opportunity_estimate", "organic_difficulty", "intent_not_allowed", "bad_slug")


def draft_until_pass(cfg, kw, plan, slug, a, articles, pages, facts, attempt) -> tuple[dict, dict]:
    """Review -> quality gate -> (rewrite with the exact feedback -> review again), up to N revisions."""
    max_rev = int(cfg.get("content.max_revisions", 3))
    rounds = []
    for n in range(max_rev + 1):
        rev = writer_agent.review(cfg, a, facts)
        html_ = publisher.render_article(cfg, a, publisher.pick_related(cfg, {**articles, slug: a}, slug))
        gate = quality.check(cfg, kw=kw, intent=plan["intent"], article=a, rendered_html=html_, url=publisher.article_url(cfg, slug),
                             slug=slug, review=rev, existing=pages)
        rounds.append({"round": n, "passed": gate["passed"], "failures": gate["failures"], "changes_made": a.get("revision_changes", [])})
        save_draft(cfg, slug, n, a, gate, rev)
        if gate["passed"] or n == max_rev or any(f.startswith(NOT_REVISABLE) for f in gate["failures"]):
            break
        feedback = {"quality_gate_failures": gate["failures"], "reviewer_notes": rev.get("notes"),
                    **{k: rev.get(k) for k in ("factual_issues", "invented_app_features", "unsupported_claims", "spam_policy_issues")}}
        a = writer_agent.revise(cfg, kw, plan, a, feedback, facts)
    if gate["passed"] and POLISH_RE.search(str(rev.get("notes") or "")):
        # Passed, but the reviewer suggested small fixes (typos, wording). One polish rewrite; it must pass the full
        # review + quality gate again, otherwise the already-passing draft is kept unchanged.
        try:
            b = writer_agent.revise(cfg, kw, plan, a, {"reviewer_suggestions_to_apply": rev.get("notes"),
                                                      "instruction": "Apply only these small fixes; keep everything else."}, facts)
            rev2 = writer_agent.review(cfg, b, facts)
            html2 = publisher.render_article(cfg, b, publisher.pick_related(cfg, {**articles, slug: b}, slug))
            gate2 = quality.check(cfg, kw=kw, intent=plan["intent"], article=b, rendered_html=html2,
                                  url=publisher.article_url(cfg, slug), slug=slug, review=rev2, existing=pages)
            rounds.append({"round": "polish", "passed": gate2["passed"], "failures": gate2["failures"],
                           "changes_made": b.get("revision_changes", [])})
            save_draft(cfg, slug, len(rounds) - 1, b, gate2, rev2)
            if gate2["passed"]:
                a, gate, rev = b, gate2, rev2
        except BudgetExceeded:
            pass  # keep the passing draft
    attempt["rounds"], attempt["quality_gate"], attempt["review_notes"] = rounds, gate, rev.get("notes")
    a.pop("revision_changes", None)
    return a, gate


POLISH_RE = re.compile(r"\b(typo|misspell|grammar|consider|suggest|reword|minor|should say|fix)", re.I)


def save_draft(cfg, slug: str, n: int, a: dict, gate: dict, rev: dict) -> None:
    """Keeps every draft + its verdict (data/drafts/) so rejected articles can be inspected or re-tested."""
    p = cfg.data_dir / "drafts" / f"{today()}-{slug}-r{n}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"article": a, "gate": gate, "review": rev}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def new_article(cfg, state: State, facts: dict, pages, perf, dry: bool, report: dict, force_keyword: str | None = None) -> None:
    limit = cfg.get("publishing.max_new_articles_per_day", 1)
    if state.published_today() >= limit and not force_keyword:
        report["notes"].append("Daily new-article limit already reached")
        return
    if not research.measured_difficulty(cfg):
        report["notes"].append("Low-cost mode: organic difficulty NOT measured; a labeled opportunity estimate is used instead")
    if not content.available():
        report["notes"].append("ANTHROPIC_API_KEY missing - content generation skipped")
        return
    prev = state.data["keywords"].pop(force_keyword, None) if force_keyword else None  # re-test a rejected keyword
    short = keyword_agent.run(cfg, state, pages, perf, report)
    if force_keyword:
        short = [i for i in short if i["keyword"] == force_keyword] or \
            ([{**prev["latest"], "keyword": force_keyword}] if prev and prev.get("latest") else [])
        for i in short:
            i["decision"] = "candidate"
        report["notes"].append(f"Manual re-test of keyword '{force_keyword}'")
    for i in short:
        i["cluster"] = i.get("feature") or research.cluster_of(cfg, i["keyword"])
    articles = state.data["articles"]
    for i in short:  # topic clusters: no second article on a near-identical query in the same cluster
        if i["decision"] == "candidate" and not force_keyword:
            dup = research.cluster_duplicate(cfg, i, articles)
            if dup:
                i["decision"] = f"duplicate_in_cluster:{dup}"
                state.record_keyword(i["keyword"], i, i["decision"])
    report["shortlist"] = [{k: i.get(k) for k in ("keyword", "volume", "difficulty", "opportunity_estimate", "gsc_impressions_28d",
                                                  "intent", "cluster", "feature", "score", "score_total", "decision",
                                                  "covering_page", "source")} for i in short[:20]]
    candidates = research.order_by_cluster([i for i in short if i["decision"] == "candidate"], articles, cfg)
    if not candidates:
        report["decision"] = ("skip: no keyword met the feature-relevance, score, volume, intent and duplicate checks "
                              "(see 'Keywords by feature' for reasons)")
        return
    published, clusters_today, failed_features = [], set(), set()
    tried = 0
    for kw in candidates:
        if tried >= cfg.get("keyword_research.max_candidates_per_run", 3):
            break
        if state.published_today() + (len(published) if dry else 0) >= limit and not force_keyword:
            break  # dry runs save nothing, so count their would-be publishes toward the daily limit too
        if kw["cluster"] in clusters_today:
            continue  # spread daily articles across clusters
        if kw["cluster"] in failed_features:
            continue  # a same-feature draft already failed this run; try a different feature instead
        tried += 1
        if published:
            pages = crawl(cfg)["pages"]  # include today's earlier article in duplicate checks
        plan, serp = strategy_agent.decide(cfg, kw, pages, facts)
        attempt = {"keyword": kw["keyword"], "feature": kw.get("feature"), "volume": kw.get("volume"),
                   "score_total": kw.get("score_total"), "score": kw.get("score"), "mix_boost": kw.get("mix_boost"),
                   "evidence": kw.get("score_evidence"), "plan_action": plan.get("action"), "plan_reason": plan.get("reason")}
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
        from .agents import conversion_agent
        land = conversion_agent.landing_link(cfg, {"keyword": kw["keyword"], "feature": kw.get("feature")})
        links = ([land] if land else []) + \
                [{"href": "/", "title": "FitCheck AI home"}, {"href": "/how-it-works.html", "title": "How FitCheck AI works"}] + \
                [{"href": f"/{cfg.get('site.blog_dir')}/{s}/", "title": a["h1"]} for s, a in articles.items()]
        a = writer_agent.write(cfg, kw, plan, serp, slug, links, facts)
        a["cluster"] = kw["cluster"]
        a["feature"] = kw.get("feature")
        a, gate = draft_until_pass(cfg, kw, plan, slug, a, articles, pages, facts, attempt)
        if not gate["passed"]:
            state.record_keyword(kw["keyword"], kw, f"rejected_by_quality_gate: {'; '.join(gate['failures'])[:300]}")
            failed_features.add(kw["cluster"])
            continue
        if dry:
            published.append(f"[dry-run] would publish /{cfg.get('site.blog_dir')}/{slug}/")
            clusters_today.add(kw["cluster"])
            continue
        a["quality_gate"] = {k: gate[k] for k in ("word_count", "keyword_density", "warnings")} | \
            {"revisions": sum(1 for r in attempt["rounds"] if r["round"] not in (0, "polish")),
             "polished": any(r["round"] == "polish" and r["passed"] for r in attempt["rounds"])}
        editor_agent.publish(cfg, a, articles)
        state.record_keyword(kw["keyword"], kw, f"published:{slug}")
        published.append(f"published /{cfg.get('site.blog_dir')}/{slug}/ for '{kw['keyword']}' (feature {kw.get('feature')}, "
                         f"score {kw.get('score_total')}) after {a['quality_gate']['revisions']} revision(s)"
                         + (" + polish" if a["quality_gate"]["polished"] else ""))
        report["published_urls"] = report.get("published_urls", []) + [publisher.article_url(cfg, slug)]
        report["changes"].append(f"new article blog/{slug}/index.html")
        clusters_today.add(kw["cluster"])
    report["decision"] = "; ".join(published) if published else "skip: no candidate passed planning + quality gate today"


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
    if report.get("discovery"):
        lines += ["## Keyword discovery (Keyword Planner ideas per feature seed group)",
                  ", ".join(f"{g}: {n}" for g, n in report["discovery"].items()), ""]
    if report.get("selection_counts"):
        c = report["selection_counts"]
        lines += ["## Selection summary",
                  f"- discovered: {c['discovered']} ideas; relevant to a FitCheck feature: {c['relevant']}",
                  f"- passed scoring requirements (candidates): {c['qualifying']}",
                  f"- rejected as duplicate intent: {c['duplicates']} (landing page: {c['dup_landing']}, existing article: {c['dup_article']})",
                  "- other rejections: " + ", ".join(f"{k} {v}" for k, v in c["reasons"].items()), ""]
    if report.get("feature_summary"):
        lines += ["## Keywords by feature", "| feature | relevant ideas | qualifying | best keyword (score*) | most common skip reason |",
                  "|---|---|---|---|---|",
                  *[f"| {r['feature']} | {r['ideas']} | {r['qualifying']} | {r['best']} ({r['best_total']}) | {r['top_skip_reason']} |"
                    for r in report["feature_summary"]], ""]
    if report.get("shortlist"):
        def comp(k, name):
            return (k.get("score") or {}).get(name, "-")
        lines += ["## Keyword shortlist",
                  "| keyword | feature | score* | relevance | ranking opp. | demand | conversion | usefulness | volume | GSC impr. 28d | intent | decision |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|",
                  *[f"| {k['keyword']} | {k.get('feature') or '-'} | {k.get('score_total', k.get('opportunity_estimate'))} | {comp(k, 'feature_relevance')} | "
                    f"{comp(k, 'ranking_opportunity')} | {comp(k, 'search_demand')} | {comp(k, 'conversion_potential')} | {comp(k, 'content_usefulness')} | "
                    f"{k['volume'] if k['volume'] is not None else 'unverified'} | {k.get('gsc_impressions_28d') or '-'} | {k['intent']} | {k['decision']} |"
                    for k in report["shortlist"]],
                  "", "*Score = five-component heuristic (opportunity estimate), NOT keyword difficulty or a Google ranking formula. "
                  "Volume = Google Ads Keyword Planner (verified) unless marked unverified.", ""]
    if report.get("published_urls"):
        lines += ["## Published URLs", *[f"- {u} (deployment is verified by the workflow's 'Verify deployment' step; "
                                         "indexing is NOT verified)" for u in report["published_urls"]], ""]
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
    if report.get("article_performance"):
        lines += ["## Article & keyword performance (Search Console, 28d)", "| article | cluster | target keyword | impressions | clicks | avg pos | keyword impr. | keyword pos |", "|---|---|---|---|---|---|---|---|",
                  *[f"| {r['slug']} | {r['cluster']} | {r['keyword']} | {r['impressions']} | {r['clicks']} | {r['position']} | {r['keyword_impressions']} | {r['keyword_position']} |"
                    for r in report["article_performance"]], ""]
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


def run(dry: bool, force_keyword: str | None = None) -> int:
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
            new_article(cfg, state, facts, crawl(cfg)["pages"], perf, dry, report, force_keyword)
            if perf:
                analytics_agent.article_performance(cfg, perf, state.data["articles"], report)
            if reports.weekly_due(cfg):
                try:  # reporting must never block publishing
                    text = reports.weekly(cfg, state, perf, clicks)
                    if dry:
                        print(text)
                    else:
                        reports.weekly_path(cfg).parent.mkdir(parents=True, exist_ok=True)
                        reports.weekly_path(cfg).write_text(text, encoding="utf-8")
                        report["changes"].append(f"weekly report {reports.weekly_path(cfg).name}")
                except Exception as e:  # noqa: BLE001
                    report["notes"].append(f"weekly report failed: {type(e).__name__}: {str(e)[:200]}")
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
    ap.add_argument("command", choices=["run", "check", "rescore", "weekly", "verify", "landing"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keyword", help="re-test one keyword (bypasses the 30-day rejection cooldown)")
    ap.add_argument("--wait", type=int, default=600, help="verify: seconds to wait for the deployment")
    ap.add_argument("--out", help="rescore: also write the report to this file")
    args = ap.parse_args(argv)
    if args.command in ("rescore", "weekly", "verify", "landing"):
        setup_logging()
        cfg = load_config()
        state = State(cfg.data_dir / "state.json")
        if args.command == "rescore":
            text = reports.rescore(cfg, state)
            print(text)
            if args.out:
                from pathlib import Path
                Path(args.out).write_text(text, encoding="utf-8")
            return 0
        if args.command == "landing":
            from . import landing
            for p in landing.render_all(cfg):
                print("wrote", p.relative_to(cfg.site_root))
            return 0
        if args.command == "weekly":
            perf = clicks = None
            rep: dict[str, Any] = {"notes": [], "errors": []}
            try:
                perf = analytics_agent.search_performance(cfg, rep)
                clicks = analytics_agent.cta_clicks(cfg, rep)
            except Exception as e:  # noqa: BLE001
                print("analytics unavailable:", e)
            text = reports.weekly(cfg, state, perf, clicks)
            print(text)
            if not args.dry_run:
                reports.weekly_path(cfg).parent.mkdir(parents=True, exist_ok=True)
                reports.weekly_path(cfg).write_text(text, encoding="utf-8")
            return 0
        fails = reports.verify(cfg, state, args.wait)
        for f in fails:
            print("NOT LIVE", f)
        print("deployment verification:", "FAILED" if fails else "OK")
        return 1 if fails else 0
    if args.command == "check":
        setup_logging()
        errs = validate_site(load_config())
        for e in errs:
            print("ERROR", e)
        print("site validation:", "FAILED" if errs else "OK")
        return 1 if errs else 0
    return run(args.dry_run, (args.keyword or "").strip().lower() or None)


if __name__ == "__main__":
    sys.exit(main())
