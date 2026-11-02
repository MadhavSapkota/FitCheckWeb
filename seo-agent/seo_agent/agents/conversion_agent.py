"""Conversion Optimization Agent: relevant, non-intrusive Google Play CTAs."""
from __future__ import annotations

import html
import re
from typing import Any

from ..audit import tokens
from ..config import Config

# (topic terms, CTA button text, feature sentence grounded in app_facts.yaml)
CTA_RULES = [
    ({"makeup", "beauty", "lipstick", "foundation", "eyeshadow", "blush", "glam"},
     "Get AI Makeup Feedback", "Snap a close-up in natural light and get AI beauty feedback on your makeup look."),
    ({"hair", "hairstyle", "hairstyles", "haircut", "curls", "braids", "bangs", "layers"},
     "Explore Hairstyles With AI", "Browse hairstyle, curl, and color inspiration and see how a look comes together."),
    (set(), "Check Your Outfit With AI", "Snap a head-to-toe photo and get an AI style score with tips on fit, color, and balance."),
]


def choose(article: dict[str, Any]) -> dict[str, str]:
    t = set(tokens(article.get("keyword", "") + " " + article.get("h1", "")))
    for terms, button, feature in CTA_RULES:
        if not terms or t & terms:
            return {"button": button, "feature": feature}
    return {"button": CTA_RULES[-1][1], "feature": CTA_RULES[-1][2]}


def button_html(cfg: Config, text: str, placement: str, slug: str) -> str:
    return (f'<a class="cta" href="{html.escape(cfg.app_url)}" target="_blank" rel="noopener" '
            f'data-cta="play-store" data-placement="{placement}" data-article="{html.escape(slug)}">{html.escape(text)}</a>')


def inline_cta(cfg: Config, article: dict[str, Any]) -> str:
    c = choose(article)
    return (f'<aside class="inline-cta" aria-label="Try the app"><p><strong>Want a quick second opinion?</strong> '
            f'{html.escape(c["feature"])}</p>{button_html(cfg, c["button"], "inline", article["slug"])}</aside>')


def insert_inline(cfg: Config, body: str, article: dict[str, Any]) -> str:
    """One inline CTA, placed before the 3rd <h2> (after the reader got real value). Never before the 2nd section;
    skipped for short articles so it never interrupts the opening."""
    if 'data-placement="inline"' in body:
        return body
    starts = [m.start() for m in re.finditer(r"<h2[\s>]", body)]
    if len(starts) < 4:
        return body
    i = starts[2]
    return body[:i] + inline_cta(cfg, article) + body[i:]
