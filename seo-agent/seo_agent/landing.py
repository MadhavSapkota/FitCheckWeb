"""Feature landing pages (/ai-outfit-checker/ etc.), rendered from seo-agent/landing_pages.yaml.

Content lives in YAML so it can be reviewed and edited without touching HTML. Each page gets: one H1, canonical,
Open Graph, BreadcrumbList + WebPage + MobileApplication + FAQPage JSON-LD, real images with alt text and
dimensions, a Google Play CTA (tracked as play_store_click), and an auto-updated list of related blog guides.
The daily agent re-renders them only when `landing_pages.enabled: true` (owner approval); otherwise they are
local drafts rendered by `python -m seo_agent.main landing`.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import yaml

from . import scoring
from .config import Config
from .publisher import _fill, analytics_snippet, sanitize_body


def load(cfg: Config) -> dict[str, Any]:
    p = cfg.agent_dir / "landing_pages.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def enabled(cfg: Config) -> bool:
    return bool(load(cfg).get("enabled"))


def page_url(cfg: Config, slug: str) -> str:
    return f"{cfg.base_url}/{slug}/"


def related_guides(cfg: Config, articles: dict[str, Any], features: list[str], n: int = 6) -> list[dict[str, str]]:
    out = []
    for s, a in sorted(articles.items(), key=lambda kv: kv[1].get("published", ""), reverse=True):
        if scoring.classify(cfg, a["keyword"])[0] in features:
            out.append({"href": f"/{cfg.get('site.blog_dir', 'blog')}/{s}/", "title": a["h1"]})
    return out[:n]


def _app_name(cfg: Config, brand: str) -> str:
    from .config import load_app_facts
    return load_app_facts().get("app_name_on_play") or cfg.get("project.name", brand)


def render(cfg: Config, p: dict[str, Any], articles: dict[str, Any]) -> str:
    e = html.escape
    url = page_url(cfg, p["slug"])
    brand = cfg.get("project.brand_on_site", "FitCheck AI")
    app = cfg.app_url

    def cta(placement: str, text: str) -> str:
        return (f'<a class="cta" href="{e(app)}" target="_blank" rel="noopener" data-cta="play-store" '
                f'data-placement="{placement}" data-article="{e(p["slug"])}">{e(text)}</a>')

    imgs = "".join(
        f'<figure><img src="{e(i["src"])}" alt="{e(i["alt"])}" width="{i["width"]}" height="{i["height"]}" '
        f'loading="{"eager" if k == 0 else "lazy"}" decoding="async"></figure>' for k, i in enumerate(p.get("images", [])))
    steps = "".join(f"<li><strong>{e(s['title'])}</strong> {e(s['text'])}</li>" for s in p.get("steps", []))
    sections = "".join(f"<section{' id=' + chr(34) + e(s['id']) + chr(34) if s.get('id') else ''}><h2>{e(s['h2'])}</h2>"
                       f"{sanitize_body(cfg, s['html'], url)}</section>" for s in p.get("sections", []))
    benefits = "".join(f"<li><strong>{e(b['title'])}</strong> {e(b['text'])}</li>" for b in p.get("benefits", []))
    limits = "".join(f"<li>{e(x)}</li>" for x in p.get("limits", []))
    faqs = p.get("faqs", [])
    faq_html = "".join(f"<details><summary>{e(f['q'])}</summary><p>{e(f['a'])}</p></details>" for f in faqs)
    guides = related_guides(cfg, articles, p.get("features", []))
    guides_html = ("<section class=\"related\" aria-labelledby=\"guides-h\"><h2 id=\"guides-h\">Related style guides</h2><ul>"
                   + "".join(f'<li><a href="{e(g["href"])}">{e(g["title"])}</a></li>' for g in guides) + "</ul></section>") if guides else ""
    others = [o for o in load(cfg).get("pages", []) if o["slug"] != p["slug"]]
    other_html = "".join(f'<li><a href="/{e(o["slug"])}/">{e(o["nav"])}</a></li>' for o in others)
    graph: list[dict[str, Any]] = [
        {"@type": "WebPage", "@id": url, "url": url, "name": p["title"], "description": p["meta"],
         "inLanguage": cfg.get("keyword_research.language", "en"), "isPartOf": {"@type": "WebSite", "url": cfg.base_url + "/", "name": brand},
         "primaryImageOfPage": cfg.base_url + p["images"][0]["src"] if p.get("images") else None},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": cfg.base_url + "/"},
            {"@type": "ListItem", "position": 2, "name": p["nav"], "item": url}]},
        {"@type": "MobileApplication", "name": _app_name(cfg, brand), "operatingSystem": "ANDROID",
         "applicationCategory": "LifestyleApplication", "url": app,
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}},
    ]
    graph[0] = {k: v for k, v in graph[0].items() if v is not None}
    if faqs:
        graph.append({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faqs]})
    jsonld = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False).replace("</", "<\\/")
    tpl = (cfg.templates_dir / "landing.html").read_text(encoding="utf-8")
    og_image = cfg.base_url + (p["images"][0]["src"] if p.get("images") else "/assets/social-card.png")
    return _fill(tpl, {
        "lang": cfg.get("keyword_research.language", "en"), "title": e(p["title"]), "description": e(p["meta"]),
        "canonical": url, "brand": e(brand), "og_image": e(og_image), "jsonld": jsonld, "app_url": e(app),
        "analytics": analytics_snippet(cfg), "nav": e(p["nav"]), "h1": e(p["h1"]), "lede": e(p["lede"]),
        "hero_cta": cta("hero", p["cta"]["button"]), "images": imgs, "steps": steps,
        "steps_title": e(p.get("steps_title", "How it works")), "sections": sections, "benefits": benefits,
        "limits": limits, "limits_title": e(p.get("limits_title", "Good to know")), "faq_html": faq_html,
        "guides_html": guides_html, "other_features": other_html, "cta_title": e(p["cta"]["title"]),
        "cta_text": e(p["cta"]["text"]), "end_cta": cta("end", p["cta"]["button"]),
    })


def render_all(cfg: Config, articles: dict[str, Any] | None = None) -> list[Path]:
    if articles is None:
        from .state import State
        articles = State(cfg.data_dir / "state.json").data.get("articles", {})
    out = []
    for p in load(cfg).get("pages", []):
        if not re.fullmatch(r"[a-z0-9-]+", p["slug"]):
            raise ValueError(f"bad landing slug {p['slug']}")
        f = cfg.site_root / p["slug"] / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        new = render(cfg, p, articles)
        if not f.exists() or f.read_text(encoding="utf-8") != new:
            f.write_text(new, encoding="utf-8")
            out.append(f)
    return out
