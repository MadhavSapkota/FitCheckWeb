"""Offline end-to-end tests: all external APIs are mocked. No network, no credentials."""
from __future__ import annotations

import json
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
    cfg_p.write_text(cfg_p.read_text().replace("enabled: false", "enabled: true"))
    mock_apis(monkeypatch)
    monkeypatch.setattr(research, "discover", lambda cfg, seeds=None: (_ for _ in ()).throw(research.NoProvider("no Ads API")))
    monkeypatch.setattr(content, "suggest_topics", lambda *a, **k: ["how to choose colors that match your outfit", "pizza"])
    assert main.main(["run"]) == 0
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    kw = st["keywords"]["how to choose colors that match your outfit"]
    assert kw["decision"].startswith("published") and kw["latest"]["volume"] is None
    assert kw["latest"]["source"] == "editorial (volume unverified)"
