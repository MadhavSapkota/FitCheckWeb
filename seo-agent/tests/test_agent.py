"""Offline end-to-end tests: all external APIs are mocked. No network, no credentials."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from seo_agent import config as config_mod
from seo_agent import content, dataforseo, main, publisher, quality, research, search_console
from seo_agent.audit import crawl
from seo_agent.state import State

AGENT = Path(__file__).resolve().parent.parent
REPO = AGENT.parent

WORDS = ("navy tan cream olive burgundy denim linen wool leather suede camel charcoal ivory blush rust sage mustard "
         "khaki plaid stripe knit blazer trouser skirt loafer sneaker boot belt scarf jacket shirt sweater hoodie "
         "chino cardigan trench parka satin silk cotton corduroy tweed").split()


def fake_body(topic: str) -> str:
    import random
    rnd = random.Random(7)
    sections = ["Why color pairing matters", "Simple formulas that work", "Balancing proportions", "Choosing shoes", "Common mistakes"]
    body = f"<p>Matching colors in an outfit for {topic} is easier with a few reliable rules.</p>"
    for s in sections:
        body += f"<h2>{s}</h2>"
        for _ in range(4):
            sent = " ".join(rnd.choice(WORDS) for _ in range(22))
            body += f"<p>Try pairing {sent}. Then compare {' '.join(rnd.choice(WORDS) for _ in range(20))}.</p>"
    body += '<p>See <a href="/how-it-works.html">how it works</a>, <a href="/blog/">more guides</a> and <a href="https://evil.example.com">this</a>.</p>'
    return body


@pytest.fixture()
def site(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "seo-agent").mkdir()
    shutil.copytree(AGENT / "templates", root / "seo-agent" / "templates")
    (root / "blog").mkdir()
    shutil.copy(REPO / "blog" / "blog.css", root / "blog" / "blog.css")
    (root / "assets" / "fonts").mkdir(parents=True)
    for f in ("favicon.svg", "apple-touch-icon.png", "app-icon.png"):
        (root / "assets" / f).write_text("x")
    for f in ("inter-regular.woff", "inter-semibold.woff"):
        (root / "assets" / "fonts" / f).write_text("x")
    page = '<!doctype html><html><head><title>{t}</title><meta name="description" content="{d}"></head><body><h1>{t}</h1><p>{b}</p><a href="privacy.html">p</a></body></html>'
    (root / "index.html").write_text(page.format(t="FitCheck AI — Your AI stylist", d="Snap a photo and get an AI style score with tips on fit, color and balance.", b="AI outfit feedback"))
    (root / "how-it-works.html").write_text(page.format(t="How it works — FitCheck AI", d="How the FitCheck AI app scores your outfit in three simple steps today.", b="steps"))
    (root / "privacy.html").write_text(page.format(t="Privacy Policy — FitCheck AI", d="How FitCheck AI handles your data. Photos are processed on your device.", b="privacy"))
    (root / "terms.html").write_text(page.format(t="Terms — FitCheck AI", d="Terms of service for the FitCheck AI Android application and website.", b="terms"))
    (root / "robots.txt").write_text("User-agent: *\nAllow: /\n\nSitemap: https://yourdomain.com/sitemap.xml\n")
    cfg_text = (AGENT / "seo-config.yaml").read_text().replace("organic_difficulty_source: none", "organic_difficulty_source: dataforseo")
    cfg_text = cfg_text.replace("global_discovery:\n    enabled: true", "global_discovery:\n    enabled: false")  # old tests are single-market
    (root / "seo-agent" / "seo-config.yaml").write_text(cfg_text)
    real_load = config_mod.load_config
    monkeypatch.setattr(main, "load_config", lambda *a, **k: real_load(root=root))
    monkeypatch.setenv("SEO_AGENT_TODAY", "2026-11-01")
    for k in ("GSC_SERVICE_ACCOUNT_JSON",):
        monkeypatch.delenv(k, raising=False)
    return root


def mock_apis(monkeypatch, *, body=None, review=None, ideas=None):
    monkeypatch.setattr(research, "discover", lambda cfg, seeds=None: ideas or [
        {"keyword": "how to match colors in an outfit", "volume": 880, "source": "google_ads_keyword_planner"},
        {"keyword": "ai outfit checker", "volume": 5400, "source": "google_ads_keyword_planner"},
        {"keyword": "outfit ideas for jobs", "volume": 300, "source": "google_ads_keyword_planner"},
        {"keyword": "pizza recipe", "volume": 90000, "source": "google_ads_keyword_planner"},
    ])
    monkeypatch.setattr(dataforseo, "available", lambda: True)
    monkeypatch.setattr(dataforseo, "keyword_difficulty", lambda cfg, kws: {"how to match colors in an outfit": 14, "ai outfit checker": 41})
    monkeypatch.setattr(dataforseo, "search_intent", lambda cfg, kws: {k: "informational" for k in kws})
    monkeypatch.setattr(dataforseo, "serp_top10", lambda cfg, kw: {"keyword": kw, "organic": [
        {"rank": 1, "url": "https://reddit.com/x", "domain": "reddit.com", "title": "Color help", "description": "..."}], "questions": ["What colors go together?"]})
    monkeypatch.setattr(content, "available", lambda: True)
    monkeypatch.setattr(content, "plan", lambda *a, **k: {"intent": "informational", "action": "new", "reason": "gap",
                                                         "slug": "how-to-match-colors-in-an-outfit", "secondary_keywords": ["outfit color matching"], "outline": []})
    monkeypatch.setattr(content, "write_article", lambda *a, **k: {
        "title": "How to Match Colors in an Outfit: Simple Rules",
        "meta_description": "Learn how to match colors in an outfit with easy formulas, undertone tips, and real examples you can wear today, from neutrals to brights.",
        "h1": "How to Match Colors in an Outfit", "body_html": body or fake_body("everyday wear"),
        "faqs": [{"question": "What colors go with navy?", "answer": "Tan, cream, white and burgundy all pair well."}],
        "cta_text": "Snap a photo and get an AI style score with tips on fit, color, and balance.", "summary": "Easy color rules."})
    # Rewrite mock: returns the draft unchanged (so a bad draft keeps failing through every revision).
    monkeypatch.setattr(content, "revise", lambda cfg, kw, plan, draft, feedback, facts: {**draft, "changes_made": []})
    monkeypatch.setattr(content, "review", lambda *a, **k: review or {"intent_match": True, "value_score": 8, "factual_issues": [],
                                                                       "invented_app_features": [], "unsupported_claims": [],
                                                                       "spam_policy_issues": [], "keyword_stuffing": False, "pass": True, "notes": "ok"})


def test_full_run_publishes_one_article(site, monkeypatch):
    mock_apis(monkeypatch)
    assert main.main(["run"]) == 0
    art = site / "blog" / "how-to-match-colors-in-an-outfit" / "index.html"
    assert art.exists()
    html = art.read_text()
    assert html.count("<h1>") == 1
    assert '<link rel="canonical" href="https://fitcheck-fashion.com/blog/how-to-match-colors-in-an-outfit/">' in html
    assert "evil.example.com" not in html  # external links stripped
    assert 'href="/how-it-works.html"' in html
    assert "play.google.com" in html
    ld = html.split('application/ld+json">')[1].split("</script>")[0]
    types = {g["@type"] for g in json.loads(ld)["@graph"]}
    assert {"Article", "BreadcrumbList", "FAQPage"} <= types
    sm = (site / "sitemap.xml").read_text()
    assert "https://fitcheck-fashion.com/blog/how-to-match-colors-in-an-outfit/" in sm and "yourdomain" not in sm
    assert "Sitemap: https://fitcheck-fashion.com/sitemap.xml" in (site / "robots.txt").read_text()
    assert "how-to-match-colors-in-an-outfit" in (site / "blog" / "index.html").read_text()
    assert 'rel="canonical"' in (site / "index.html").read_text()
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    assert st["keywords"]["ai outfit checker"]["decision"] == "rejected_difficulty"
    assert "pizza recipe" not in st["keywords"]  # filtered before paid difficulty lookups
    assert (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").exists()
    # second run same day: no duplicate publishing
    assert main.main(["run"]) == 0
    assert len(list((site / "blog").glob("*/index.html"))) == 1
    assert main.main(["check"]) == 0


def test_quality_gate_blocks_invented_features(site, monkeypatch):
    mock_apis(monkeypatch, body=fake_body("x") + "<p>Download it on the App Store for iPhone. Over 1 million users love it.</p>")
    main.main(["run"])
    assert not (site / "blog" / "how-to-match-colors-in-an-outfit").exists()
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    d = st["keywords"]["how to match colors in an outfit"]["decision"]
    assert "forbidden_claim" in d


def test_rejected_draft_is_rewritten_with_feedback_and_published(site, monkeypatch):
    bad = fake_body("x") + "<p>This look is guaranteed to flatter everyone.</p>"
    mock_apis(monkeypatch, body=bad)
    seen = []

    def fake_review(cfg, keyword, intent, article, facts):
        ok = "guaranteed" not in article["body_html"]
        return {"intent_match": True, "value_score": 8, "factual_issues": [] if ok else ["absolute promise"],
                "invented_app_features": [], "unsupported_claims": [], "spam_policy_issues": [], "keyword_stuffing": False,
                "pass": ok, "notes": ""}

    def fake_revise(cfg, kw, plan, draft, feedback, facts):
        seen.append(feedback)
        return {**draft, "body_html": draft["body_html"].replace("<p>This look is guaranteed to flatter everyone.</p>", ""),
                "changes_made": ["removed absolute promise"]}
    monkeypatch.setattr(content, "review", fake_review)
    monkeypatch.setattr(content, "revise", fake_revise)
    main.main(["run"])
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    assert st["keywords"]["how to match colors in an outfit"]["decision"].startswith("published")
    assert len(seen) == 1 and any("absolute guarantee" in f for f in seen[0]["quality_gate_failures"])
    assert seen[0]["factual_issues"] == ["absolute promise"]
    assert "guaranteed" not in (site / "blog" / "how-to-match-colors-in-an-outfit" / "index.html").read_text()
    assert st["articles"]["how-to-match-colors-in-an-outfit"]["quality_gate"]["revisions"] == 1


def test_quality_gate_blocks_stuffing_and_failed_review(site, monkeypatch):
    stuffed = fake_body("x") + "<p>" + " ".join(["how to match colors in an outfit"] * 60) + "</p>"
    mock_apis(monkeypatch, body=stuffed, review={"pass": False, "intent_match": True, "value_score": 4})
    main.main(["run"])
    assert not (site / "blog" / "how-to-match-colors-in-an-outfit").exists()
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    d = st["keywords"]["how to match colors in an outfit"]["decision"]
    assert "keyword_stuffing" in d and "review_failed" in d


def test_no_qualifying_keyword_makes_no_article(site, monkeypatch):
    mock_apis(monkeypatch, ideas=[{"keyword": "outfit rating", "volume": 50, "source": "google_ads_keyword_planner"}])
    main.main(["run"])
    assert not any((site / "blog").glob("*/index.html"))


def test_no_provider_never_fabricates(site, monkeypatch):
    mock_apis(monkeypatch)
    monkeypatch.setattr(research, "discover", research.__dict__["discover"].__wrapped__ if hasattr(research.discover, "__wrapped__") else research.discover)
    import importlib
    importlib.reload(research)
    for k in ("GOOGLE_ADS_DEVELOPER_TOKEN", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(dataforseo, "available", lambda: False)
    main.main(["run"])
    assert not any((site / "blog").glob("*/index.html"))
    assert "No keyword volume provider" in (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").read_text()


def test_near_duplicate_detection():
    a = "matching colors in an outfit is easier with a few reliable rules about undertones " * 5
    assert quality.similarity(a, a) > 0.9
    assert quality.similarity(a, "completely different text about hiking boots and trail running shoes") == 0.0


def test_ads_competition_not_used_as_difficulty(site, monkeypatch):
    mock_apis(monkeypatch, ideas=[{"keyword": "how to match colors in an outfit", "volume": 880, "ads_competition": "LOW",
                                   "source": "google_ads_keyword_planner"}])
    monkeypatch.setattr(dataforseo, "keyword_difficulty", lambda cfg, kws: {})  # no organic KD available
    main.main(["run"])
    assert not any((site / "blog").glob("*/index.html"))
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    assert st["keywords"]["how to match colors in an outfit"]["decision"] == "rejected_no_organic_difficulty_data"


def test_real_repository_config_and_site_validate():
    cfg = config_mod.load_config()
    res = crawl(cfg)
    assert any(p.path == "index.html" for p in res["pages"])


def _free_mode(site):
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))


def test_low_cost_mode_keyword_planner_only(site, monkeypatch):
    _free_mode(site)
    mock_apis(monkeypatch, ideas=[
        {"keyword": "how to match colors in an outfit", "volume": 880, "ads_competition": "HIGH", "source": "google_ads_keyword_planner"},
        {"keyword": "outfit ideas", "volume": 90000, "source": "google_ads_keyword_planner"},
        {"keyword": "what to wear with olive pants", "volume": 5400, "source": "google_ads_keyword_planner"},
    ])
    called = []
    monkeypatch.setattr(dataforseo, "keyword_difficulty", lambda *a: called.append(1) or {})
    monkeypatch.setattr(dataforseo, "serp_top10", lambda *a: called.append(1) or {})
    assert main.main(["run"]) == 0
    assert not called  # no paid SEO API calls
    html = (site / "blog" / "how-to-match-colors-in-an-outfit" / "index.html").read_text()
    assert "Check Your Outfit With AI" in html
    assert html.count('data-placement="inline"') == 1 and 'data-placement="end"' in html
    assert "G-NQ0WXQQXQW" in html and "play_store_click" in html  # blog pages track Play Store clicks like the site
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    # broad head term: blocked by the ranking-opportunity gate
    assert st["keywords"]["outfit ideas"]["decision"] == "rejected_head_term_low_ranking_opportunity"
    # loosely related trend query: qualifies on score but loses to the higher-scoring outfit-color topic (1/day)
    olive = st["keywords"]["what to wear with olive pants"]
    assert olive["latest"]["feature"] == "trends" and olive["latest"]["score_total"] < st["keywords"]["how to match colors in an outfit"]["latest"]["score_total"]
    rep = (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").read_text()
    assert "NOT keyword difficulty" in rep and "Low-cost mode" in rep


def test_search_console_queries_without_keyword_planner(site, monkeypatch):
    _free_mode(site)
    mock_apis(monkeypatch)
    monkeypatch.setattr(research, "discover", lambda cfg, seeds=None: (_ for _ in ()).throw(research.NoProvider("no Ads API")))
    perf = {"queries_28d": [{"query": "what colors go with olive green pants", "impressions": 80, "clicks": 1, "ctr": 0.01, "position": 14.0},
                            {"query": "fit check meaning", "impressions": 5, "clicks": 0, "ctr": 0, "position": 40.0}]}
    from seo_agent.agents import analytics_agent
    monkeypatch.setattr(analytics_agent, "search_performance", lambda cfg, report: perf)
    monkeypatch.setattr(analytics_agent, "suggestions", lambda *a: [])
    assert main.main(["run"]) == 0
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    kw = st["keywords"]["what colors go with olive green pants"]
    assert kw["decision"].startswith("published") and kw["latest"]["volume"] is None
    assert st["keywords"]["fit check meaning"]["decision"] == "rejected_volume_unverified_and_little_search_console_evidence"


def test_spending_limit_stops_generation(site, monkeypatch):
    mock_apis(monkeypatch)
    from seo_agent import budget as budget_mod
    real_write = content.write_article

    def capped(*a, **k):
        budget_mod.current().check()
        return real_write(*a, **k)
    monkeypatch.setattr(content, "write_article", capped)
    st_p = site / "seo-agent" / "data" / "state.json"
    st_p.parent.mkdir(parents=True)
    st_p.write_text(json.dumps({"usage": {"2026-11": {"claude_calls": 500, "input_tokens": 0, "output_tokens": 0, "usd_estimate": 99.0}}}))
    assert main.main(["run"]) == 0
    assert not any((site / "blog").glob("*/index.html"))
    assert "spending limit" in (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").read_text()


def test_makeup_topic_gets_makeup_cta():
    from seo_agent.agents import conversion_agent
    assert conversion_agent.choose({"keyword": "soft glam makeup tips", "h1": ""})["button"] == "Get AI Makeup Feedback"
    assert conversion_agent.choose({"keyword": "layered haircut ideas", "h1": ""})["button"] == "Explore Hairstyles With AI"


def test_google_ads_error_does_not_crash_run(site, monkeypatch):
    mock_apis(monkeypatch)
    import importlib
    importlib.reload(research)
    from seo_agent import keyword_planner
    monkeypatch.setattr(keyword_planner, "available", lambda: True)
    monkeypatch.setattr(keyword_planner, "keyword_ideas", lambda *a: (_ for _ in ()).throw(RuntimeError("DEVELOPER_TOKEN_NOT_APPROVED")))
    assert main.main(["run"]) == 0
    rep = (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").read_text()
    assert "Keyword Planner unavailable" in rep


def test_default_verified_only_publishes_nothing_without_data(site, monkeypatch):
    _free_mode(site)
    mock_apis(monkeypatch)
    monkeypatch.setattr(research, "discover", lambda cfg, seeds=None: (_ for _ in ()).throw(research.NoProvider("no Ads API")))
    called = []
    monkeypatch.setattr(content, "suggest_topics", lambda *a, **k: called.append(1) or ["how to choose colors that match your outfit"])
    assert main.main(["run"]) == 0
    assert not called and not any((site / "blog").glob("*/index.html"))


def test_editorial_topics_when_enabled(site, monkeypatch):
    _free_mode(site)
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("unverified_topics:\n    enabled: false", "unverified_topics:\n    enabled: true"))
    mock_apis(monkeypatch)
    monkeypatch.setattr(research, "discover", lambda cfg, seeds=None: (_ for _ in ()).throw(research.NoProvider("no Ads API")))
    monkeypatch.setattr(content, "suggest_topics", lambda *a, **k: ["how to choose colors that match your outfit", "pizza"])
    assert main.main(["run"]) == 0
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    kw = st["keywords"]["how to choose colors that match your outfit"]
    assert kw["decision"].startswith("published") and kw["latest"]["volume"] is None
    assert kw["latest"]["source"] == "editorial (volume unverified)"


def enable_global(site, min_opp=0, min_vol=1000):
    p = site / "seo-agent" / "seo-config.yaml"
    txt = p.read_text().replace("global_discovery:\n    enabled: false", "global_discovery:\n    enabled: true")
    txt = txt.replace("min_ranking_opportunity: 60", f"min_ranking_opportunity: {min_opp}")
    p.write_text(re.sub(r"(global_discovery:.*?minimum_monthly_searches: )\d+", rf"\g<1>{min_vol}", txt, count=1, flags=re.S))  # tests do not depend on the tuned default


def set_opportunity(monkeypatch, table, default=80):
    """Pins each keyword's ranking-opportunity score so selection tests are deterministic."""
    from seo_agent import scoring
    orig = scoring.score

    def score(cfg, i, pages, articles):
        r = orig(cfg, i, pages, articles)
        if i.get("score"):
            i["score"]["ranking_opportunity"] = table.get(i["keyword"], default)
        return r
    monkeypatch.setattr(scoring, "score", score)


def report_text(site):
    return (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").read_text()


def idea(k, vol, comp="LOW"):
    return {"keyword": k, "volume": vol, "ads_competition": comp, "source": "google_ads_keyword_planner"}


def by_market(monkeypatch, table, seen=None):
    def discover(cfg, seeds=None):
        code = cfg.get("keyword_research.location_code")
        if seen is not None:
            seen.append(code)
        return table.get(code, [])
    monkeypatch.setattr(research, "discover", discover)
    monkeypatch.setattr(dataforseo, "keyword_difficulty", lambda cfg, kws: {k: 10 for k in kws})


def test_global_picks_highest_volume_eligible_across_markets(site, monkeypatch):
    mock_apis(monkeypatch)
    enable_global(site)
    seen = []
    by_market(monkeypatch, {
        2840: [idea("how to match colors in an outfit", 1300)],                       # US: eligible, lower volume
        2826: [idea("how to match colors in an outfit", 4400), idea("ai outfit checker", 90000, "HIGH")],  # UK: higher volume; HIGH one excluded
        2276: [idea("outfit ideas for jobs", 2000, "MEDIUM"), idea("what to wear today", 800)],  # DE: wrong competition / too small
    }, seen)
    assert main.main(["run"]) == 0
    assert len(set(seen)) == 14  # compared every market instead of stopping at the first with a result
    assert len(list((site / "blog").glob("*/index.html"))) == 1  # one article per day
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    assert st["keywords"]["how to match colors in an outfit"]["latest"]["market"] == "GB"  # highest-volume market wins
    assert st["keywords"]["how to match colors in an outfit"]["latest"]["volume"] == 4400
    assert "Highest-volume eligible keyword across 14 markets" in st["keywords"]["how to match colors in an outfit"]["latest"]["selection_reason"]
    rep = (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").read_text()
    assert "Global keyword discovery" in rep and "United Kingdom" in rep and "Selected because" in rep
    assert "ai outfit checker" not in rep.split("Selected because")[1].split("\n")[0]


def test_global_requires_1000_searches_and_low_competition(site, monkeypatch):
    mock_apis(monkeypatch)
    enable_global(site)
    by_market(monkeypatch, {2840: [idea("how to match colors in an outfit", 999)],
                            2826: [idea("how to match colors in an outfit", 5000, "MEDIUM")],
                            2124: [{"keyword": "how to match colors in an outfit", "volume": 5000, "source": "google_ads_keyword_planner"}]})  # unknown competition
    assert main.main(["run"]) == 0
    assert not any((site / "blog").glob("*/index.html"))


def test_global_one_market_failing_does_not_stop_the_rest(site, monkeypatch):
    mock_apis(monkeypatch)
    enable_global(site)
    def discover(cfg, seeds=None):
        if cfg.get("keyword_research.location_code") == 2840:
            raise RuntimeError("boom")
        return [idea("how to match colors in an outfit", 3000)]
    monkeypatch.setattr(research, "discover", discover)
    assert main.main(["run"]) == 0
    assert (site / "blog" / "how-to-match-colors-in-an-outfit" / "index.html").exists()


def test_global_non_english_keyword_is_dropped(site, monkeypatch):
    mock_apis(monkeypatch)
    enable_global(site)
    by_market(monkeypatch, {2276: [idea("wie kombiniere ich farben für outfit", 9000)]})
    assert main.main(["run"]) == 0
    assert not any((site / "blog").glob("*/index.html"))


def test_head_term_below_ranking_opportunity_is_not_selected_even_with_top_volume(site, monkeypatch):
    mock_apis(monkeypatch)
    enable_global(site, min_opp=60)
    set_opportunity(monkeypatch, {"ai outfit checker": 40, "how to match colors in an outfit": 70})
    by_market(monkeypatch, {2356: [idea("ai outfit checker", 40000)],                        # India: biggest, but hard head term
                            2826: [idea("how to match colors in an outfit", 3000)]})        # UK: smaller, realistic
    assert main.main(["run"]) == 0
    assert (site / "blog" / "how-to-match-colors-in-an-outfit" / "index.html").exists()
    rep = report_text(site)
    assert "below_ranking_opportunity (<60): not selected" in rep           # the head term is reported, with its status
    assert "SELECTED - published" in rep and "ranking opportunity 70" in rep  # and the reason names the opportunity score


def test_nothing_published_and_clearly_reported_when_only_head_terms_qualify(site, monkeypatch):
    mock_apis(monkeypatch)
    enable_global(site, min_opp=60)
    set_opportunity(monkeypatch, {}, default=30)
    by_market(monkeypatch, {2840: [idea("how to match colors in an outfit", 9000)]})
    assert main.main(["run"]) == 0
    assert not any((site / "blog").glob("*/index.html"))
    rep = report_text(site)
    assert "none had ranking opportunity >= 60" in rep and "no difficult head term was auto-selected" in rep
    assert "how to match colors in an outfit" in rep  # still listed so the owner can see it


def test_highest_volume_among_preferred_wins(site, monkeypatch):
    mock_apis(monkeypatch)
    enable_global(site, min_opp=60)
    set_opportunity(monkeypatch, {"how to match colors in an outfit": 65, "does my outfit look good": 90, "ai outfit checker": 20})
    by_market(monkeypatch, {2840: [idea("does my outfit look good", 2000), idea("ai outfit checker", 90000)],
                            2036: [idea("how to match colors in an outfit", 7000)]})
    assert main.main(["run"]) == 0
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    assert st["keywords"]["how to match colors in an outfit"]["decision"].startswith("published")
    assert not st["keywords"]["does my outfit look good"]["decision"].startswith("published")  # lower volume, one article per day
    assert len(list((site / "blog").glob("*/index.html"))) == 1


def test_report_lists_country_volume_competition_scores_and_per_country_rejections(site, monkeypatch):
    mock_apis(monkeypatch)
    enable_global(site, min_opp=60)
    set_opportunity(monkeypatch, {}, default=75)
    by_market(monkeypatch, {2840: [idea("how to match colors in an outfit", 1500), idea("outfit rating", 50)],
                            2356: [idea("ai outfit checker", 6200), idea("how to match colors in an outfit", 8000, "HIGH")]})
    assert main.main(["run"]) == 0
    rep = report_text(site)
    assert "| keyword | country | monthly searches | Ads competition | relevance | ranking opportunity | conversion | score |" in rep
    row = next(l for l in rep.splitlines() if l.startswith("| ") and "ai outfit checker" in l and "India" in l and "6,200" in l)
    assert "India" in row and "6,200" in row and "LOW" in row and "| 75 |" in row
    rows = {l.split("|")[1].strip(): l for l in rep.splitlines() if l.startswith("| ") and l.split("|")[1].strip() in ("United States", "India", "Canada")}
    assert set(rows) == {"United States", "India", "Canada"}  # one complete row per market, none overwritten
    assert rows["United States"] != rows["India"] != rows["Canada"]
    head = next(l for l in rep.splitlines() if l.startswith("| market |")).split("|")[1:-1]
    india = rows["India"].split("|")[1:-1]
    assert india[[h.strip() for h in head].index("ads_competition_not_allowed")].strip() == "1"  # HIGH-competition idea counted against India only
    us = rows["United States"].split("|")[1:-1]
    assert us[[h.strip() for h in head].index("ads_competition_not_allowed")].strip() == "0"
    summary = rep.split("## Selection summary")[1].split("##")[0]
    assert "discovered" in summary  # summary now sums every market


FIVE = [("how to match colors in an outfit", 5000), ("ai outfit checker", 4000), ("does my outfit look good", 3000),
        ("what should i wear today", 2000), ("color matching clothes for women", 1500)]


def five_keywords(monkeypatch):
    mock_apis(monkeypatch)
    monkeypatch.setattr(research, "discover", lambda cfg, seeds=None: [idea(k, v) for k, v in FIVE])
    monkeypatch.setattr(dataforseo, "keyword_difficulty", lambda cfg, kws: {k: 10 for k in kws})


def count_planner(monkeypatch, new_on_call=None):
    calls = []
    def plan(cfg, kw, serp, pages, facts):
        calls.append(kw["keyword"])
        action = "new" if new_on_call and len(calls) == new_on_call else "update"
        return {"intent": "informational", "action": action, "reason": "an existing page covers this",
                "slug": "how-to-match-colors-in-an-outfit", "secondary_keywords": [], "outline": []}
    monkeypatch.setattr(content, "plan", plan)
    return calls


def test_planner_rejections_do_not_use_up_the_writing_cap(site, monkeypatch):
    five_keywords(monkeypatch)
    calls = count_planner(monkeypatch, new_on_call=5)   # first four are duplicates of existing pages, the fifth is new
    assert main.main(["run"]) == 0
    assert len(calls) == 5                               # old behaviour stopped after 4 planner calls and published nothing
    assert len(list((site / "blog").glob("*/index.html"))) == 1


def test_planner_call_ceiling_is_enforced(site, monkeypatch):
    p = site / "seo-agent" / "seo-config.yaml"
    p.write_text(p.read_text().replace("max_planner_calls_per_run: 8", "max_planner_calls_per_run: 3"))
    five_keywords(monkeypatch)
    calls = count_planner(monkeypatch, new_on_call=5)
    assert main.main(["run"]) == 0
    assert len(calls) == 3 and not any((site / "blog").glob("*/index.html"))
    assert "Planner-call limit reached (3)" in report_text(site)


def test_planner_rejected_keyword_is_not_offered_again_for_30_days(site, monkeypatch):
    five_keywords(monkeypatch)
    calls = count_planner(monkeypatch)                   # every keyword rejected as a duplicate
    assert main.main(["run"]) == 0
    first = len(calls)
    assert first == 5
    monkeypatch.setenv("SEO_AGENT_TODAY", "2026-11-05")  # 4 days later: all five are on cooldown, none re-planned
    assert main.main(["run"]) == 0
    assert len(calls) == first
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    assert st["keywords"]["ai outfit checker"]["decision"].startswith("rejected_recently_by_planner")
    monkeypatch.setenv("SEO_AGENT_TODAY", "2026-12-15")  # after the cooldown they are evaluated again
    assert main.main(["run"]) == 0
    assert len(calls) > first
