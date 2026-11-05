"""Five-component scoring, feature classification, duplicate prevention, health rules, retries, landing pages."""
from __future__ import annotations

import json
import re

import pytest

from seo_agent import config as config_mod
from seo_agent import http, landing, main, publisher, quality, reports, research, scoring
from seo_agent.state import State

from test_agent import fake_body, mock_apis, site  # noqa: F401  (fixture re-export)


@pytest.fixture(scope="module")
def cfg():
    return config_mod.load_config()


@pytest.mark.parametrize("kw,feature", [
    ("rate my outfit", "outfit-checker"),
    ("does my outfit look good", "outfit-checker"),
    ("what makeup suits my face", "makeup-assistant"),
    ("virtual makeup try on", "makeup-try-on"),
    ("lipstick try on", "makeup-try-on"),
    ("what hairstyle suits me", "hairstyle-recommendations"),
    ("try hairstyles on my face", "hairstyle-try-on"),
    ("hair porosity test", "hair-analysis"),
    ("skin analysis app", "skin-analysis"),
    ("digital wardrobe app", "wardrobe"),
    ("virtual try on clothes", "outfit-try-on"),
    ("ai outfit generator", "fashion-generator"),
    ("old money outfit ideas", "trends"),
    ("fitcheck app", "branded"),
    ("hair style try on app", "hairstyle-try-on"),
])
def test_every_feature_is_classified(cfg, kw, feature):
    assert scoring.classify(cfg, kw)[0] == feature


def test_makeup_assistant_and_try_on_are_separate_clusters(cfg):
    assert research.cluster_of(cfg, "makeup for my skin tone") == "makeup-assistant"
    assert research.cluster_of(cfg, "try makeup on my face") == "makeup-try-on"
    f = cfg.get("features")
    assert f["makeup-assistant"]["landing"] == f["makeup-try-on"]["landing"]  # shared page, separate tracking


def test_irrelevant_keyword_never_qualifies_even_if_easy(cfg):
    i = scoring.score(cfg, {"keyword": "how to make sourdough bread at home easily", "volume": 500,
                            "source": "google_ads_keyword_planner"}, [], {})
    assert i["score"]["feature_relevance"] == 0
    assert scoring.qualifies(cfg, i, 0) == "rejected_low_feature_relevance"
    assert not research.relevant(cfg, "how to make sourdough bread at home easily")


def test_score_components_and_weights(cfg):
    i = scoring.score(cfg, {"keyword": "virtual makeup try on", "volume": 1000, "source": "google_ads_keyword_planner"}, [], {})
    s = i["score"]
    assert set(s) == {"feature_relevance", "ranking_opportunity", "search_demand", "conversion_potential", "content_usefulness"}
    assert all(0 <= v <= 100 for v in s.values())
    assert s["search_demand"] == 60  # 20 * log10(1000)
    expect = round(.30 * s["feature_relevance"] + .25 * s["ranking_opportunity"] + .15 * s["search_demand"]
                   + .20 * s["conversion_potential"] + .10 * s["content_usefulness"], 1)
    assert i["score_total"] == expect
    assert "verified 1000/mo" in i["score_evidence"]["search_demand"]


def test_unverified_volume_is_never_invented(cfg):
    i = scoring.score(cfg, {"keyword": "skin analysis app", "volume": None, "source": "editorial"}, [], {})
    assert i["score"]["search_demand"] == 0 and "unverified" in i["score_evidence"]["search_demand"]


def test_app_feature_query_outscores_generic_trend(cfg):
    app = scoring.score(cfg, {"keyword": "try on hairstyles with your picture for free", "volume": 2900}, [], {})
    trend = scoring.score(cfg, {"keyword": "21st birthday outfit ideas", "volume": 590}, [], {})
    assert app["score_total"] > trend["score_total"]
    assert app["score"]["conversion_potential"] > trend["score"]["conversion_potential"]


def test_head_terms_are_gated(cfg):
    i = scoring.score(cfg, {"keyword": "outfit ideas", "volume": 165000}, [], {})
    assert scoring.qualifies(cfg, i) == "rejected_head_term_low_ranking_opportunity"


def test_duplicate_intent_blocked_across_and_within_features(cfg):
    arts = {"try-hairstyles-on-your-face": {"keyword": "try hairstyles on my face", "secondary_keywords": []}}
    same = {"keyword": "try hairstyle on your face", "feature": "hairstyle-try-on"}
    assert research.cluster_duplicate(cfg, same, arts) == "try-hairstyles-on-your-face"
    different = {"keyword": "lipstick try on", "feature": "makeup-try-on"}
    assert research.cluster_duplicate(cfg, different, arts) is None


# ---------------------------------------------------------------- intent differentiation
from seo_agent import intent  # noqa: E402

HAIR_ARTICLE = {"try-hairstyles-on-your-face": {"keyword": "try hairstyles on my face", "secondary_keywords": []}}
LANDING = [{"page": "ai-makeup-assistant/index.html", "query": q} for q in
           ("ai makeup assistant", "virtual makeup try on", "makeup try on app")] + \
          [{"page": "ai-skin-analysis/index.html", "query": "skin analyzer app"}]


@pytest.mark.parametrize("kw,expected", [
    ("what makeup suits my face", "informational"), ("how to find your skin undertone", "informational"),
    ("capsule wardrobe ideas", "informational"), ("virtual makeup try on", "tool"), ("skin analyzer app", "tool"),
    ("try hairstyles on my face", "tool"), ("haircut filter", "tool"),
])
def test_intent_type(kw, expected):
    assert intent.intent_type(kw) == expected


def test_landing_page_does_not_block_informational_guide(cfg):
    for kw in ("what makeup suits my face", "makeup for my skin tone", "how to find your skin undertone",
               "best makeup for my face shape"):
        feat = scoring.classify(cfg, kw)[0]
        assert intent.duplicate_of(cfg, kw, feat, {}, LANDING) is None, kw


def test_landing_page_blocks_same_tool_intent(cfg):
    d = intent.duplicate_of(cfg, "virtual makeup try-on app", "makeup-try-on", {}, LANDING)
    assert d and d["kind"] == "landing" and d["page"] == "ai-makeup-assistant/index.html"
    assert intent.duplicate_of(cfg, "ai skin analyzer", "skin-analysis", {}, LANDING)["kind"] == "landing"


def test_landing_page_only_blocks_its_own_feature(cfg):
    # shares "virtual" + "try on" with the makeup page, but it is outfit try-on
    assert intent.duplicate_of(cfg, "virtual try on clothes", "outfit-try-on", {}, LANDING) is None


def test_existing_blog_blocks_only_same_intent(cfg):
    for kw in ("try on hairstyles with your picture for free", "test hairstyles on my face free", "virtual hair try on",
               "hairstyle try on app"):
        d = intent.duplicate_of(cfg, kw, scoring.classify(cfg, kw)[0], HAIR_ARTICLE, [])
        assert d and d["slug"] == "try-hairstyles-on-your-face", kw
    for kw in ("what hairstyle suits me", "haircut for round face", "what is my hair type", "virtual makeup try on",
               "try on clothes online"):
        assert intent.duplicate_of(cfg, kw, scoring.classify(cfg, kw)[0], HAIR_ARTICLE, []) is None, kw


def test_shared_words_alone_do_not_lower_or_block(cfg):
    i = scoring.score(cfg, {"keyword": "what makeup suits my face", "volume": 480}, [], HAIR_ARTICLE)
    assert not any("partly answered" in w for w in i["score_evidence"]["content_usefulness"])


def test_shortlist_reports_landing_duplicate_reason(site, monkeypatch):
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))
    import shutil
    shutil.copy(config_mod.load_config().agent_dir / "landing_pages.yaml", site / "seo-agent" / "landing_pages.yaml")
    (site / "ai-makeup-assistant").mkdir()
    (site / "ai-makeup-assistant" / "index.html").write_text(
        '<!doctype html><html><head><title>AI Makeup Assistant &amp; Try-On</title></head><body><h1>x</h1></body></html>')
    mock_apis(monkeypatch, ideas=[
        {"keyword": "virtual makeup try on app", "volume": 1300, "source": "google_ads_keyword_planner"},
        {"keyword": "what makeup suits my face", "volume": 1000, "source": "google_ads_keyword_planner"}])
    main.main(["run"])
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    assert st["keywords"]["virtual makeup try on app"]["decision"] == "duplicate_intent_of_landing:ai-makeup-assistant/index.html"
    assert st["keywords"]["what makeup suits my face"]["decision"].startswith("published:")
    html = next((site / "blog").glob("*/index.html")).read_text()
    assert 'href="/ai-makeup-assistant/"' in html  # links its feature landing page
    assert html.count('data-cta="play-store"') >= 2 and "Get AI Makeup Feedback" in html  # header + feature CTA


def test_mix_boost_favors_uncovered_features(cfg):
    arts = {"a": {"keyword": "try hairstyles on my face"}}
    assert scoring.mix_boost(cfg, "skin-analysis", arts) > scoring.mix_boost(cfg, "hairstyle-try-on", arts)


def test_health_rules_in_quality_gate():
    bad = ["This app can detect skin cancer early.", "It cures acne in a week.", "Clinically proven results.",
           "Our skin scanner is 98% accurate."]
    for s in bad:
        assert any(re.search(p, s, flags=re.I) for p, _ in quality.FORBIDDEN), s
    ok = "Preview lipstick live with your camera before you commit."
    assert not any(re.search(p, ok, flags=re.I) for p, _ in quality.FORBIDDEN)


def test_questions_and_denials_are_not_claims_but_answers_are_checked():
    ok = ("Can the app detect skin conditions? No. FitCheck does not diagnose or detect skin conditions. "
          "It is not a substitute for a dermatologist. FitCheck does not give size recommendations.")
    assert not [l for p, l in quality.FORBIDDEN if re.search(p, quality.claim_text(ok), flags=re.I)]
    bad = "Can the app detect skin conditions? Yes, it can detect melanoma early. It gives size recommendations too."
    hits = {l for p, l in quality.FORBIDDEN if re.search(p, quality.claim_text(bad), flags=re.I)}
    assert "medical detection claim" in hits and "claims size recommendations" in hits


def test_unverified_photo_storage_claims_blocked():
    for s in ("Your photos are never stored.", "Saved looks stay on your device.", "Images are deleted after 24 hours.",
              "Photos never leave your phone.", "Your selfies are encrypted."):
        assert any(label == "unverified photo storage claim" and re.search(p, s, flags=re.I)
                   for p, label in quality.FORBIDDEN), s
    for s in ("Upload a clear photo in natural light.", "Outfit scoring runs on your device.",
              "Save your favorite looks to your digital closet."):
        assert not any(label == "unverified photo storage claim" and re.search(p, s, flags=re.I)
                       for p, label in quality.FORBIDDEN), s


def test_landing_pages_make_no_storage_claims(cfg):
    text = (cfg.agent_dir / "landing_pages.yaml").read_text()
    for pat in (r"stays? on (your|the) device", r"does not store", r"private to you", r"never (stored|uploaded)"):
        assert not re.search(pat, text, flags=re.I), pat


def test_required_disclaimers_are_not_flagged_as_claims():
    ok = ("AI feedback is not medical advice. See a dermatologist or doctor for any skin concern. "
          "The app does not diagnose skin conditions.")
    assert not any(re.search(p, quality.claim_text(ok), flags=re.I) for p, _ in quality.FORBIDDEN)
    bad = "See a dermatologist if you like, but this app can detect melanoma and diagnoses acne."
    assert any(re.search(p, quality.claim_text(bad), flags=re.I) for p, _ in quality.FORBIDDEN)


def test_reviewer_no_issue_and_minor_entries_ignored_only_when_passed():
    passed = {"pass": True, "value_score": 8, "unsupported_claims": ["No medical claims found."],
              "factual_issues": ["Minor: wording could be tighter."]}
    assert quality.real_issues(passed, "unsupported_claims") == [] and quality.real_issues(passed, "factual_issues") == []
    failed = {**passed, "pass": False}
    assert quality.real_issues(failed, "factual_issues") == ["Minor: wording could be tighter."]
    real = {**passed, "factual_issues": ["The vein test claim is stated as fact."]}
    assert quality.real_issues(real, "factual_issues")


def test_skin_article_requires_not_medical_advice_note(site, monkeypatch):
    mock_apis(monkeypatch, ideas=[{"keyword": "what is my skin undertone and how to find it", "volume": 880,
                                   "source": "google_ads_keyword_planner"}])
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))
    main.main(["run"])
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    k = st["keywords"]["what is my skin undertone and how to find it"]
    assert k["feature"] == "skin-analysis"
    assert "health_topic_missing_not_medical_advice_note" in k["decision"]
    assert not any((site / "blog").glob("*/index.html"))


def test_one_article_per_day_and_feature_cta(site, monkeypatch):
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))
    mock_apis(monkeypatch, ideas=[
        {"keyword": "how to match colors in an outfit", "volume": 880, "source": "google_ads_keyword_planner"},
        {"keyword": "what colors go together in an outfit for work", "volume": 390, "source": "google_ads_keyword_planner"},
    ])
    assert main.main(["run"]) == 0
    pages = list((site / "blog").glob("*/index.html"))
    assert len(pages) == 1
    html = pages[0].read_text()
    assert "Check Your Outfit With AI" in html
    rep = (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").read_text()
    assert "## Keywords by feature" in rep and "relevance | ranking opp." in rep
    assert (site / "seo-agent" / "data" / "reports" / "weekly-2026-W44.md").exists()


def test_faq_heading_not_duplicated(cfg):
    a = {"slug": "x-y", "keyword": "what is my skin tone", "title": "What Is My Skin Tone? A Guide", "h1": "What Is My Skin Tone",
         "meta_description": "m" * 140, "published": "2026-11-05", "modified": "2026-11-05",
         "body_html": "<p>Intro.</p><h2>Depth</h2><p>a</p><h2>Frequently asked questions</h2><p>Common follow-ups.</p>",
         "faqs": [{"question": "Q?", "answer": "A."}]}
    html = publisher.render_article(cfg, a, [])
    assert html.lower().count("frequently asked questions</h2>") == 1 and "Common follow-ups" not in html
    assert "<h2>Depth</h2>" in html


def test_polish_applies_reviewer_suggestions_only_if_still_passing(site, monkeypatch):
    from seo_agent import content
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))
    body = fake_body("x") + "<p>Try a emerald green scarf near your face.</p>"
    mock_apis(monkeypatch, body=body)

    def review(cfg, keyword, intent, article, facts):
        typo = "a emerald" in article["body_html"]
        return {"intent_match": True, "value_score": 8, "factual_issues": [], "invented_app_features": [],
                "unsupported_claims": [], "spam_policy_issues": [], "keyword_stuffing": False, "pass": True,
                "notes": "Minor: fix the typo 'a emerald' -> 'an emerald'." if typo else "Good."}
    monkeypatch.setattr(content, "review", review)
    monkeypatch.setattr(content, "revise", lambda cfg, kw, plan, draft, fb, facts: {
        **draft, "body_html": draft["body_html"].replace("a emerald", "an emerald"), "changes_made": ["typo"]})
    assert main.main(["run"]) == 0
    html = (site / "blog" / "how-to-match-colors-in-an-outfit" / "index.html").read_text()
    assert "an emerald" in html and "a emerald" not in html
    st = json.loads((site / "seo-agent" / "data" / "state.json").read_text())
    assert st["articles"]["how-to-match-colors-in-an-outfit"]["quality_gate"]["polished"] is True


def test_failed_polish_keeps_the_passing_draft(site, monkeypatch):
    from seo_agent import content
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))
    mock_apis(monkeypatch)
    monkeypatch.setattr(content, "review", lambda cfg, keyword, intent, article, facts: {
        "intent_match": True, "value_score": 8, "factual_issues": [], "invented_app_features": [], "unsupported_claims": [],
        "spam_policy_issues": [], "keyword_stuffing": False, "pass": "guaranteed" not in article["body_html"],
        "notes": "Consider tightening the intro."})
    monkeypatch.setattr(content, "revise", lambda cfg, kw, plan, draft, fb, facts: {
        **draft, "body_html": draft["body_html"] + "<p>Results guaranteed.</p>", "changes_made": []})
    assert main.main(["run"]) == 0
    html = (site / "blog" / "how-to-match-colors-in-an-outfit" / "index.html").read_text()
    assert "guaranteed" not in html.lower()


def _free(site):
    p = site / "seo-agent" / "seo-config.yaml"
    p.write_text(p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))


def test_retest_keyword_cannot_bypass_daily_limit(site, monkeypatch):
    _free(site)
    mock_apis(monkeypatch, ideas=[
        {"keyword": "how to match colors in an outfit", "volume": 880, "source": "google_ads_keyword_planner"},
        {"keyword": "how to organize your closet", "volume": 5400, "source": "google_ads_keyword_planner"}])
    assert main.main(["run"]) == 0
    assert len(list((site / "blog").glob("*/index.html"))) == 1
    assert main.main(["run", "--keyword", "how to organize your closet"]) == 0  # manual re-test, same day
    assert len(list((site / "blog").glob("*/index.html"))) == 1
    assert "daily article limit already reached" in (site / "seo-agent" / "data" / "reports" / "2026-11-01.md").read_text()


def test_overlapping_runs_are_caught_before_push(site, monkeypatch):
    """Simulates two runs that both published (merged state after `git pull --rebase`): validation must fail."""
    _free(site)
    mock_apis(monkeypatch)
    assert main.main(["run"]) == 0
    assert main.main(["check"]) == 0
    p = site / "seo-agent" / "data" / "state.json"
    st = json.loads(p.read_text())
    other = dict(next(iter(st["articles"].values())), slug="another-article", keyword="another topic")
    st["articles"]["another-article"] = other
    p.write_text(json.dumps(st))
    assert main.main(["check"]) == 1
    cfg = config_mod.load_config(root=site)
    assert main.daily_limit_errors(cfg) and "daily article limit exceeded" in main.daily_limit_errors(cfg)[0]


def test_dry_run_respects_one_article_per_day(site, monkeypatch, capsys):
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))
    mock_apis(monkeypatch, ideas=[
        {"keyword": "how to match colors in an outfit", "volume": 880, "source": "google_ads_keyword_planner"},
        {"keyword": "how to organize your closet", "volume": 5400, "source": "google_ads_keyword_planner"},
        {"keyword": "what is my hair type", "volume": 5400, "source": "google_ads_keyword_planner"}])
    assert main.main(["run", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.count("[dry-run] would publish") == 1
    assert "## Selection summary" in out and "rejected as duplicate intent" in out
    assert not any((site / "blog").glob("*/index.html"))


def test_article_links_feature_landing_page_when_it_exists(site, monkeypatch):
    cfg_p = site / "seo-agent" / "seo-config.yaml"
    cfg_p.write_text(cfg_p.read_text().replace("organic_difficulty_source: dataforseo", "organic_difficulty_source: none"))
    (site / "ai-outfit-checker").mkdir()
    (site / "ai-outfit-checker" / "index.html").write_text(
        '<!doctype html><html><head><title>AI Outfit Checker</title></head><body><h1>x</h1></body></html>')
    mock_apis(monkeypatch)
    assert main.main(["run"]) == 0
    html = (site / "blog" / "how-to-match-colors-in-an-outfit" / "index.html").read_text()
    assert 'href="/ai-outfit-checker/"' in html
    assert 'data-cta="play-store" data-placement="end"' in html and "play.google.com" in html


def test_permanent_errors_are_not_retried():
    class AuthenticationError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    assert not http.is_transient(AuthenticationError("bad key"))
    assert http.is_transient(RateLimitError("slow down"))
    e = Exception("403"); e.status_code = 403
    assert not http.is_transient(e)
    e = Exception("503"); e.status_code = 503
    assert http.is_transient(e)
    calls = []

    @http.with_backoff(attempts=3, min_wait=0, max_wait=0)
    def f():
        calls.append(1)
        raise AuthenticationError("no")
    with pytest.raises(AuthenticationError):
        f()
    assert len(calls) == 1


def test_landing_pages_render_valid_and_do_not_touch_blog(cfg, tmp_path, monkeypatch):
    import shutil
    root = tmp_path / "repo"
    (root / "seo-agent").mkdir(parents=True)
    shutil.copytree(cfg.agent_dir / "templates", root / "seo-agent" / "templates")
    shutil.copy(cfg.agent_dir / "landing_pages.yaml", root / "seo-agent" / "landing_pages.yaml")
    shutil.copy(cfg.agent_dir / "seo-config.yaml", root / "seo-agent" / "seo-config.yaml")
    c = config_mod.load_config(root=root)
    written = landing.render_all(c, {})
    assert len(written) == 6
    for p in written:
        h = p.read_text()
        assert h.count("<h1>") == 1 and 'rel="canonical"' in h and 'data-cta="play-store"' in h
        ld = json.loads(h.split('application/ld+json">')[1].split("</script>")[0])
        assert {"WebPage", "BreadcrumbList", "FAQPage", "MobileApplication"} <= {g["@type"] for g in ld["@graph"]}
        assert re.search(r"<title>.{20,70}</title>", h)
        assert all(' alt="' in t for t in re.findall(r"<img [^>]+>", h))
    assert not (root / "blog").exists()
    assert landing.render_all(c, {}) == []  # idempotent: nothing rewritten when unchanged
    skin = (root / "ai-skin-analysis" / "index.html").read_text()
    assert "not medical advice" in skin.lower()


def test_rescore_report_runs_offline(cfg):
    text = reports.rescore(cfg, State(cfg.data_dir / "state.json"))
    assert "| 40 |" in text and "| 45 |" in text and "| 50 |" in text
    for fid in cfg.get("features"):
        assert f"(`{fid}`)" in text
