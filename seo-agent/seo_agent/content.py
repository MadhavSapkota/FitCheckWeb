"""Claude (Anthropic API)-powered planning, writing, independent review, and article improvement."""
from __future__ import annotations

import json
from typing import Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .budget import BudgetExceeded

from .config import Config, env
from .log import log

SYSTEM = """You are a senior fashion and beauty editor and technical SEO writer for {brand}, an Android app.
Rules you must follow:
- Write genuinely helpful, original, people-first content that directly answers the searcher. No filler.
- Never invent facts, statistics, studies, quotes, testimonials, product tests, prices, or experiences.
  Give practical styling guidance (color theory, proportion, fit, occasion dressing, grooming) that is widely accepted.
- When describing the app, ONLY use the facts in APP_FACTS. Never claim anything listed under not_offered_do_not_claim.
- Never claim the app or AI is perfect, objective, or a professional stylist. Feedback is a starting point.
- No keyword stuffing: use the target phrase naturally (title, H1, intro, once or twice in body). Use synonyms.
- Follow Google Search spam policies: no scaled low-value content, no doorway pages, no hidden text, no misleading claims.
- Skin and hair topics: cosmetic and style guidance only. Never diagnose, detect, or treat any skin, scalp, or hair
  condition (acne, eczema, hair loss, moles, etc.), never promise accuracy, and say plainly that AI feedback is not
  medical advice; suggest a dermatologist or doctor for any health concern.
- Output must be valid JSON only."""


def feature_brief(cfg: Config, kw: dict[str, Any]) -> str:
    """The FitCheck feature this article supports: what the app can genuinely do for this reader."""
    fid = kw.get("feature")
    f = (cfg.get("features") or {}).get(fid or "") or {}
    if not f:
        return "FEATURE: none specific - keep app mentions minimal and general."
    out = f"FEATURE: {f.get('label', fid)} (id {fid}). Show how this feature helps the reader, using APP_FACTS only."
    if f.get("landing") and f["landing"] != "/":
        out += f" If {f['landing']} is in INTERNAL_LINKS, link it once with natural descriptive anchor text."
    if f.get("health"):
        out += (" HEALTH-ADJACENT TOPIC: cosmetic/style guidance only; include one sentence stating the AI feedback is "
                "not medical advice and to see a dermatologist or doctor for concerns. No diagnosis, detection, or treatment claims.")
    return out


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"), max_retries=3, timeout=300)


def available() -> bool:
    return bool(env("ANTHROPIC_API_KEY"))


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("model did not return JSON")
    return json.loads(text[start:end + 1])


def _retry_json(e: BaseException) -> bool:
    """Retry transient API errors and malformed/truncated JSON; never auth, permission, 400, or budget errors."""
    from .http import is_transient
    if isinstance(e, BudgetExceeded):
        return False
    return is_transient(e) or isinstance(e, (ValueError, json.JSONDecodeError))


@retry(retry=retry_if_exception(_retry_json), stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=40), reraise=True)
def _json_call(model: str, system: str, user: str, max_tokens: int = 16000) -> dict[str, Any]:
    from . import budget
    b = budget.current()
    if b:
        b.check()  # raises BudgetExceeded -> run stops generating, nothing published
    resp = _client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system + "\nRespond with a single JSON object only, no prose and no code fences.",
        messages=[{"role": "user", "content": user}],
    )
    if b:
        b.charge(resp.usage.input_tokens, resp.usage.output_tokens)
    if resp.stop_reason == "max_tokens":
        raise ValueError("response truncated")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return _extract_json(text)


def _sys(cfg: Config) -> str:
    return SYSTEM.format(brand=cfg.get("project.brand_on_site", "FitCheck AI"))


def plan(cfg: Config, kw: dict[str, Any], serp: dict[str, Any], site_pages: list[dict[str, Any]], facts: dict) -> dict[str, Any]:
    user = f"""TARGET_KEYWORD: {kw['keyword']}
METRICS: monthly_searches={kw['volume']}, organic_difficulty={kw['difficulty']}/100, detected_intent={kw.get('intent')}
TOP_10_ORGANIC_RESULTS: {json.dumps(serp.get('organic', []), ensure_ascii=False) if serp.get('organic') else 'not available - ' + serp.get('note', '') + ' Do not claim to know what currently ranks.'}
PEOPLE_ALSO_ASK: {json.dumps(serp.get('questions', []), ensure_ascii=False)}
EXISTING_PAGES_ON_OUR_SITE: {json.dumps(site_pages, ensure_ascii=False)}
APP_FACTS: {json.dumps(facts, ensure_ascii=False)}

Analyse the search intent and the ranking pages. Decide whether we should:
- "new": write a new article (only if it would add genuinely new value vs. our existing pages),
- "update": improve an existing page under blog/ instead (give its path), or
- "skip": the topic does not fit our site/app or we cannot add real value.
Return JSON: {{"intent": "informational|commercial|transactional|navigational", "intent_explanation": str,
"action": "new|update|skip", "target_page": str|null, "reason": str,
"reader_questions": [str], "content_gaps": [str],
"slug": "lowercase-hyphenated-max-6-words", "secondary_keywords": [str],
"outline": [{{"h2": str, "h3": [str]}}], "app_relevance": "how the app genuinely helps this reader, using APP_FACTS only"}}"""
    return _json_call(cfg.get("content.model"), _sys(cfg), user)


def write_article(cfg: Config, kw: dict[str, Any], plan_: dict[str, Any], serp: dict[str, Any],
                  links: list[dict[str, str]], facts: dict) -> dict[str, Any]:
    user = f"""Write the article.
TARGET_KEYWORD: {kw['keyword']}
{feature_brief(cfg, kw)}
PLAN: {json.dumps(plan_, ensure_ascii=False)}
WHAT_COMPETITORS_COVER (titles/snippets only, do not copy): {json.dumps([{'title': o['title'], 'snippet': o['description']} for o in serp.get('organic', [])], ensure_ascii=False)}
INTERNAL_LINKS_YOU_MAY_USE (use 2-4 where genuinely relevant, exact href): {json.dumps(links, ensure_ascii=False)}
APP_FACTS: {json.dumps(facts, ensure_ascii=False)}

Requirements:
- {cfg.get('content.min_words')}-{min(cfg.get('content.max_words'), 1800)} words in body_html.
- body_html uses only <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a href>, <table>, <thead>, <tbody>, <tr>, <th>, <td>. No <h1>.
- Start with a 2-3 sentence intro that answers the query directly. At least 4 <h2> sections following the plan.
- Include concrete, practical examples (e.g. specific color pairings, outfit formulas, proportions).
- Mention the app at most twice, naturally, only where it helps (e.g. getting feedback on fit/color/balance). Do not link to external sites.
- faqs: 3-5 real questions searchers ask, each answered in 2-4 sentences. Do not repeat body text verbatim.
Return JSON: {{"title": "SEO title <= 60 chars", "meta_description": "140-155 chars, compelling, no quotes",
"h1": str, "body_html": str, "faqs": [{{"question": str, "answer": str}}],
"cta_text": "one sentence inviting the reader to try the app, factual per APP_FACTS", "summary": "one sentence for the blog index"}}"""
    return _json_call(cfg.get("content.model"), _sys(cfg), user)


def revise(cfg: Config, kw: dict[str, Any], plan_: dict[str, Any], draft: dict[str, Any], feedback: dict[str, Any],
           facts: dict) -> dict[str, Any]:
    """Rewrites a rejected draft using the exact reviewer + quality-gate feedback."""
    user = f"""Our editorial quality reviewer REJECTED this draft. Rewrite it so EVERY issue below is fixed.
TARGET_KEYWORD: {kw['keyword']}
{feature_brief(cfg, kw)}
PLAN: {json.dumps(plan_, ensure_ascii=False)}
REJECTION_FEEDBACK (fix each item exactly): {json.dumps(feedback, ensure_ascii=False)}
CURRENT_DRAFT: {json.dumps(draft, ensure_ascii=False)}
APP_FACTS: {json.dumps(facts, ensure_ascii=False)}

Rules for the rewrite:
- Correct or delete every flagged statement. If you are not certain a styling/beauty claim is accurate, remove it.
- Describe the app ONLY with wording directly supported by APP_FACTS. Do not describe app screens, menus, buttons,
  options, sliders, comparisons or workflows that APP_FACTS do not state. Do not call the app or its AI images
  private, secure, accurate or realistic beyond what APP_FACTS say.
- Never use the words guarantee, guaranteed, guarantees, 100% accurate, or similar absolute promises.
- Keep what was good: structure, practical examples, {cfg.get('content.min_words')}-{min(cfg.get('content.max_words'), 1800)} words,
  at least 4 <h2> sections, the same allowed tags (no <h1>), natural keyword use (no stuffing), and only the internal links already present.
Return the same JSON shape: {{"title": "<= 60 chars", "meta_description": "140-155 chars", "h1": str, "body_html": str,
"faqs": [{{"question": str, "answer": str}}], "cta_text": str, "summary": str, "changes_made": [str]}}"""
    return _json_call(cfg.get("content.model"), _sys(cfg), user)


def review(cfg: Config, keyword: str, intent: str, article: dict[str, Any], facts: dict) -> dict[str, Any]:
    system = """You are a strict editorial QA reviewer and Google Search quality rater. Be skeptical. Output JSON only."""
    user = f"""Review this article for the query "{keyword}" (intent: {intent}).
APP_FACTS (the only true statements about the app): {json.dumps(facts, ensure_ascii=False)}
ARTICLE: {json.dumps(article, ensure_ascii=False)}
Check: does it satisfy the search intent; does it give meaningful, practical, accurate information;
any invented statistics/studies/testimonials/product testing; any claim about the app not supported by APP_FACTS
(or anything in not_offered_do_not_claim); keyword stuffing; Google spam-policy problems (scaled low-value content,
doorway, misleading); inaccurate styling/beauty advice; unsafe advice; for skin/hair topics any medical diagnosis,
detection, treatment, or accuracy claim (list these under unsupported_claims).
Return JSON: {{"intent_match": bool, "value_score": 1-10, "factual_issues": [str], "invented_app_features": [str],
"unsupported_claims": [str], "spam_policy_issues": [str], "keyword_stuffing": bool, "pass": bool, "notes": str}}"""
    return _json_call(cfg.get("content.review_model"), system, user)


def improve(cfg: Config, article: dict[str, Any], opp: dict[str, Any], facts: dict) -> dict[str, Any]:
    user = f"""This article of ours gets search impressions but underperforms ({opp['reason']}: impressions={opp['impressions']},
ctr={opp['ctr']:.3f}, avg position={opp['position']:.1f}). Real queries it shows for: {json.dumps([q['query'] for q in opp.get('top_queries', [])])}
ARTICLE: {json.dumps(article, ensure_ascii=False)}
APP_FACTS: {json.dumps(facts, ensure_ascii=False)}
Improve it genuinely for those queries. Do NOT change content just to look fresh. Return JSON:
{{"title": "improved title <= 60 chars (or same)", "meta_description": "140-155 chars",
"new_section_html": "one new <h2> section (<h2>,<h3>,<p>,<ul>,<li> only) answering an unanswered query, or empty string",
"new_faqs": [{{"question": str, "answer": str}}], "change_summary": str, "substantive": bool}}"""
    return _json_call(cfg.get("content.model"), _sys(cfg), user)


def suggest_topics(cfg: Config, seeds: list[str], existing_titles: list[str], facts: dict) -> list[str]:
    """Editorial topic ideas when no keyword-volume source is available. Returns search-style
    long-tail queries only; NO metrics are produced or implied."""
    user = f"""Suggest 15 specific long-tail Google search queries (5-9 words, how/what/which questions)
that real people type, closely related to these themes: {json.dumps(seeds)}.
Each must be answerable with a genuinely helpful styling/beauty guide, relevant to an app that gives
AI feedback on outfits (fit, color, balance), makeup, and hairstyles: {json.dumps(facts.get('features', []))}.
Avoid topics already covered by: {json.dumps(existing_titles)}. No brand names. Do not estimate search volume.
Return JSON: {{"queries": [str]}}"""
    data = _json_call(cfg.get("content.model"), _sys(cfg), user, max_tokens=2000)
    return [q.strip().lower() for q in data.get("queries", []) if isinstance(q, str) and q.strip()][:15]
