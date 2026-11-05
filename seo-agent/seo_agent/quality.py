"""Mandatory quality gate. Any critical failure blocks publishing."""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from .audit import STOP, Page, resolve_internal, tokens
from .config import Config

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){1,8}$")

# Deterministic red flags for invented features / fabricated claims (complements the LLM review).
FORBIDDEN = [
    (r"\b(available|download|get it)\b[^.]{0,40}\b(app store|iphone|ios)\b(?![^.]{0,40}coming soon)", "claims iOS availability"),
    (r"\bweb (app|version)\b|\bin your browser\b", "claims web app"),
    (r"\b\d[\d,.]*\s*(k|m|million|thousand)?\+?\s*(users|downloads|installs|reviews)\b", "invented usage numbers"),
    (r"\brated\s+\d(\.\d)?\s*(stars|/5|out of)", "invented rating"),
    (r"\b(studies|research|a study|survey)\s+(show|shows|found|finds)\b", "unsourced study claim"),
    (r"\b\d{1,3}\s?%\s+of\s+(people|women|men|users|shoppers|americans)\b", "unsourced statistic"),
    (r"\b(we|our team) (tested|reviewed|tried)\b", "fabricated product testing"),
    (r"\b(buy|shop|order)\b[^.]{0,30}\b(in|inside|within|through) the app\b", "claims in-app shopping"),
    (r"\b(size|measurement)s? recommendation", "claims size recommendations"),
    (r"\bAR\b|\baugmented reality\b", "claims AR technology"),
    (r"\b(live|real-time)\b[^.]{0,30}\b(clothes|clothing|outfit) try-?on\b", "claims live clothing try-on (outfit try-on is AI images)"),
    (r"\b(diagnos|dermatolog)", "medical/skin diagnosis claim"),
    # skin & hair: no medical, treatment, or accuracy claims
    (r"\b(cure[sd]?|treat(s|ed|ing)?|heal(s|ed|ing)?|fix(es)?)\b[^.]{0,25}\b(acne|eczema|rosacea|psoriasis|dermatitis|hair loss|alopecia|dandruff|infection)",
     "medical treatment claim"),
    (r"\b(detect|identif|spot|screen)\w*\b[^.]{0,30}\b(cancer|melanoma|mole|disease|condition|disorder|infection|deficienc)",
     "medical detection claim"),
    (r"\bclinically\s+(proven|tested|validated)\b|\bmedical[- ]grade\b", "clinical claim"),
    (r"\b\d{2,3}\s?%\s+accura", "accuracy percentage claim"),
    # photo privacy: storage/retention/deletion/encryption behaviour is not confirmed, so no article may assert it
    (r"\b(photos?|images?|pictures?|selfies?|looks?|data)\b[^.]{0,40}\b(never|not|aren't|isn't|are|is)\s+"
     r"(stored|saved|kept|retained|uploaded|shared|sold|deleted|encrypted)\b", "unverified photo storage claim"),
    (r"\b(stays?|remain)\s+on\s+(your|the)\s+(device|phone)\b|\bnever\s+leaves?\s+(your|the)\s+(device|phone)\b"
     r"|\bend-to-end\s+encrypt|\bautomatically\s+deleted\b", "unverified photo storage claim"),
    (r"\b(guarantee[sd]?|100% accurate|perfect score every time)\b", "absolute guarantee"),
]


# Responsible-use sentences the writer is REQUIRED to include on skin/hair topics. They must never count as claims.
# Only the referral / negation PHRASE is removed (never the whole sentence), so a claim next to it is still caught.
SAFE_SENTENCE = re.compile(
    r"\b(see|consult|visit|ask|talk to|check with|speak (to|with))\s+(a|an|your)?\s*(board-certified\s+)?"
    r"(dermatologist|doctor|physician|gp|healthcare professional|medical professional)s?(\s+or\s+(a\s+)?(dermatologist|doctor|physician))?"
    r"|\bnot\s+a\s+substitute\s+for\s+(a|an|your)?\s*(dermatologist|doctor|physician|professional(\s+\w+)?|medical\s+\w+)"
    r"|\bnot\s+(a\s+substitute\s+for\s+)?(professional\s+)?(medical advice|a\s+(medical\s+)?diagnosis|medical)"
    r"|\b(does not|doesn't|do not|don't)\s+(give|offer|provide|make|include)\s+(\w+\s+){0,2}(size|measurement|medical|diagnos)\w*(\s+\w+){0,2}"
    r"|\b(does not|doesn't|do not|don't|cannot|can't|won't|never|is not designed to|isn't designed to)\s+"
    r"(diagnose|detect|treat|identify|assess)(\s+or\s+(diagnose|detect|treat|identify|assess))?",
    flags=re.I)


QUESTION_SENTENCE = re.compile(r"[^.!?\n]*\?")


def claim_text(text: str) -> str:
    """Text with disclaimers/referrals and questions removed, so 'see a dermatologist', 'does not diagnose' or an FAQ
    question like 'Can the app detect skin conditions?' never trips a claim rule. Answers are still checked."""
    return SAFE_SENTENCE.sub(" ", QUESTION_SENTENCE.sub(" ", text))


NO_ISSUE = re.compile(r"^\s*(no|none|n/a|nothing)\b", re.I)


def real_issues(review: dict[str, Any], key: str) -> list[str]:
    """Reviewer list entries that are actual problems. Drops 'No ... found' entries; drops self-labelled 'Minor'
    notes only when the reviewer itself passed the article with a value score >= 8."""
    lenient = bool(review.get("pass")) and int(review.get("value_score") or 0) >= 8
    out = []
    for x in review.get(key) or []:
        s = str(x)
        if NO_ISSUE.match(s) or (lenient and re.match(r"^\s*minor\b", s, flags=re.I)):
            continue
        out.append(s)
    return out


def shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    t = tokens(text)
    return {tuple(t[i:i + n]) for i in range(max(0, len(t) - n + 1))}


def similarity(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def keyword_density(text: str, keyword: str) -> float:
    words = tokens(text)
    phrase = tokens(keyword)
    if not words or not phrase:
        return 0.0
    n = len(phrase)
    hits = sum(1 for i in range(len(words) - n + 1) if words[i:i + n] == phrase)
    return 100.0 * hits * n / len(words)


def max_term_share(text: str) -> tuple[str, float]:
    words = [w for w in tokens(text) if w not in STOP and len(w) > 2]
    if not words:
        return "", 0.0
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    w, c = max(counts.items(), key=lambda kv: kv[1])
    return w, 100.0 * c / len(words)


def check(cfg: Config, *, kw: dict[str, Any], intent: str, article: dict[str, Any], rendered_html: str, url: str,
          slug: str, review: dict[str, Any], existing: list[Page], skip_pages: tuple[str, ...] = ()) -> dict[str, Any]:
    fails: list[str] = []
    warns: list[str] = []
    soup = BeautifulSoup(rendered_html, "html.parser")
    body = soup.select_one(".body")
    body_text = body.get_text(" ", strip=True) if body else ""
    all_text = soup.find("article").get_text(" ", strip=True) if soup.find("article") else ""
    wc = len(tokens(body_text))

    # thresholds
    vol = kw.get("volume")
    if vol is not None and vol < cfg.get("keyword_research.minimum_monthly_searches"):
        fails.append("volume_below_threshold")
    editorial = bool(cfg.get("keyword_research.unverified_topics.enabled")) and str(kw.get("source", "")).startswith("editorial")
    if vol is None and not editorial and kw.get("gsc_impressions_28d", 0) < cfg.get("keyword_research.min_gsc_impressions_if_volume_unverified", 30):
        fails.append("volume_unverified_without_search_console_evidence")
    if cfg.get("keyword_research.organic_difficulty_source") == "dataforseo":
        if kw.get("difficulty") is None or kw["difficulty"] > cfg.get("keyword_research.maximum_organic_difficulty"):
            fails.append("organic_difficulty_above_threshold_or_missing")
    elif editorial and kw.get("score_total", kw.get("opportunity_estimate", 0)) < cfg.get(
            "keyword_research.unverified_topics.min_opportunity_estimate", 40):
        fails.append("opportunity_estimate_below_threshold")
    elif not editorial and kw.get("score"):
        from . import scoring
        why = scoring.qualifies(cfg, kw)
        if why:
            fails.append(f"opportunity_estimate_below_threshold:{why}")
    elif not editorial and kw.get("opportunity_estimate", 0) < cfg.get("scoring.min_total", 45):
        fails.append("opportunity_estimate_below_threshold")
    # skin / hair analysis articles must say the feedback is not medical advice
    feat = (cfg.get("features") or {}).get(kw.get("feature") or "", {})
    written = re.sub(r"<[^>]+>", " ", article.get("body_html", "") + " " + " ".join(f.get("answer", "") for f in article.get("faqs", [])))
    if feat.get("health") and not re.search(r"not (a substitute for )?(medical|professional medical) advice|not medical advice",
                                            written, flags=re.I):  # in the writer's own text, not just the CTA
        fails.append("health_topic_missing_not_medical_advice_note")
    if intent not in cfg.get("keyword_research.allowed_intents"):
        fails.append(f"intent_not_allowed:{intent}")
    # structure / metadata
    if len(soup.find_all("h1")) != 1:
        fails.append("h1_count_not_1")
    if body and len(body.find_all("h2")) < 3:
        fails.append("too_few_h2_sections")
    t = soup.title.get_text() if soup.title else ""
    if not 20 <= len(t) <= 70:
        fails.append(f"title_length:{len(t)}")
    md = soup.find("meta", attrs={"name": "description"})
    mdc = md.get("content", "") if md else ""
    if not 70 <= len(mdc) <= 170:
        fails.append(f"meta_description_length:{len(mdc)}")
    can = soup.find("link", rel="canonical")
    if not can or can.get("href") != url:
        fails.append("canonical_incorrect")
    og = soup.find("meta", attrs={"property": "og:url"})
    if not og or og.get("content") != url:
        fails.append("og_url_incorrect")
    if not SLUG_RE.match(slug):
        fails.append("bad_slug")
    if soup.select(".body script, .body iframe, .body style"):
        fails.append("unsafe_markup")
    # length / value
    if wc < cfg.get("content.min_words"):
        fails.append(f"too_short:{wc}")
    if wc > cfg.get("content.max_words") + 400:
        warns.append(f"long:{wc}")
    # stuffing
    dens = keyword_density(body_text, kw["keyword"])
    if dens > cfg.get("content.max_keyword_density_percent"):
        fails.append(f"keyword_stuffing:{dens:.2f}%")
    term, share = max_term_share(body_text)
    if share > 6.0:
        fails.append(f"term_overuse:{term}:{share:.1f}%")
    # repetition inside the article (same sentence repeated)
    sents = [s.strip().lower() for s in re.split(r"[.!?]", body_text) if len(s.split()) > 6]
    if len(sents) - len(set(sents)) > 2:
        fails.append("repeated_sentences")
    # duplicates
    for p in existing:
        if p.path in skip_pages:
            continue
        sim = similarity(all_text, p.text)
        if sim > cfg.get("content.max_similarity_to_existing"):
            fails.append(f"near_duplicate_of:{p.path}:{sim:.2f}")
        if p.title and p.title.strip().lower() == t.strip().lower():
            fails.append(f"duplicate_title:{p.path}")
    # links
    for a in soup.find_all("a", href=True):
        target = resolve_internal(cfg, url, a["href"])
        generated = target is not None and target == cfg.blog_dir / "index.html"  # written in the same run
        if target is not None and not target.exists() and not generated and not a["href"].rstrip("/").endswith(slug):
            fails.append(f"broken_internal_link:{a['href']}")
    if not soup.find("a", attrs={"data-cta": "play-store", "data-placement": "end"}):
        fails.append("missing_app_cta")
    # invented features / fabricated claims (deterministic)
    claims = claim_text(all_text)
    for pat, label in FORBIDDEN:
        if re.search(pat, claims, flags=re.I):
            fails.append(f"forbidden_claim:{label}")
    # LLM editorial review
    if not review.get("pass"):
        fails.append("review_failed")
    if not review.get("intent_match"):
        fails.append("intent_mismatch")
    if int(review.get("value_score") or 0) < 7:
        fails.append(f"low_value_score:{review.get('value_score')}")
    for key in ("factual_issues", "invented_app_features", "unsupported_claims", "spam_policy_issues"):
        issues = real_issues(review, key)
        if issues:
            fails.append(f"{key}:{'; '.join(issues)[:200]}")
    if review.get("keyword_stuffing"):
        fails.append("review_keyword_stuffing")
    return {"passed": not fails, "failures": fails, "warnings": warns, "word_count": wc,
            "keyword_density": round(dens, 2)}
