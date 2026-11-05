"""Writes articles into the existing static site without touching its layout."""
from __future__ import annotations

import html
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

import nh3

from .audit import STOP, Page, resolve_internal, tokens
from .config import Config
from .log import log

ALLOWED_TAGS = {"h2", "h3", "p", "ul", "ol", "li", "strong", "em", "a", "table", "thead", "tbody", "tr", "th", "td", "br"}


def article_url(cfg: Config, slug: str) -> str:
    return f"{cfg.base_url}/{cfg.get('site.blog_dir', 'blog')}/{slug}/"


def article_path(cfg: Config, slug: str) -> Path:
    return cfg.blog_dir / slug / "index.html"


def source_path(cfg: Config, slug: str) -> Path:
    return cfg.data_dir / "articles" / f"{slug}.json"


def sanitize_body(cfg: Config, body_html: str, page_url: str) -> str:
    clean = nh3.clean(body_html, tags=ALLOWED_TAGS, attributes={"a": {"href"}}, link_rel=None)
    # Keep only internal links that resolve, plus the Play Store link. Others become plain text.
    def fix(m: re.Match) -> str:
        href, text = html.unescape(m.group(1)), m.group(2)
        if href == cfg.app_url:
            return f'<a href="{html.escape(href)}" target="_blank" rel="noopener">{text}</a>'
        t = resolve_internal(cfg, page_url, href)
        if t is not None and t.exists():
            return f'<a href="{html.escape(href)}">{text}</a>'
        return text
    return re.sub(r'<a href="([^"]*)">(.*?)</a>', fix, clean, flags=re.S)


def _fill(tpl: str, values: dict[str, str]) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), ""), tpl)


def human_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def related_html(items: list[dict[str, str]]) -> str:
    if not items:
        return ""
    lis = "".join(f'<li><a href="{html.escape(i["href"])}">{html.escape(i["title"])}</a></li>' for i in items)
    return f'<section class="related" aria-labelledby="related-h"><h2 id="related-h">Related style guides</h2><ul>{lis}</ul></section>'


def render_article(cfg: Config, a: dict[str, Any], related: list[dict[str, str]]) -> str:
    url = article_url(cfg, a["slug"])
    brand = cfg.get("project.brand_on_site", "FitCheck AI")
    from .agents import conversion_agent
    body = conversion_agent.insert_inline(cfg, sanitize_body(cfg, a["body_html"], url), a)
    cta = conversion_agent.choose(a, cfg)
    faqs = [f for f in a.get("faqs", []) if f.get("question") and f.get("answer")]
    faq_html = ""
    if faqs:
        faq_html = '<section class="faq" aria-labelledby="faq-h"><h2 id="faq-h">Frequently asked questions</h2>' + "".join(
            f"<details><summary>{html.escape(f['question'])}</summary><p>{html.escape(f['answer'])}</p></details>" for f in faqs
        ) + "</section>"
    words = len(tokens(re.sub(r"<[^>]+>", " ", body)))
    graph: list[dict[str, Any]] = [
        {"@type": "Article", "headline": a["title"], "description": a["meta_description"],
         "datePublished": a["published"], "dateModified": a["modified"], "mainEntityOfPage": url, "inLanguage": cfg.get("keyword_research.language"),
         "author": {"@type": "Organization", "name": brand, "url": cfg.base_url + "/"},
         "publisher": {"@type": "Organization", "name": brand, "url": cfg.base_url + "/",
                       "logo": {"@type": "ImageObject", "url": cfg.base_url + "/assets/app-icon.png"}}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": cfg.base_url + "/"},
            {"@type": "ListItem", "position": 2, "name": "Style guides", "item": f"{cfg.base_url}/{cfg.get('site.blog_dir')}/"},
            {"@type": "ListItem", "position": 3, "name": a["h1"], "item": url}]},
    ]
    if faqs:
        graph.append({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f["question"], "acceptedAnswer": {"@type": "Answer", "text": f["answer"]}} for f in faqs]})
    jsonld = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False).replace("</", "<\\/")
    tpl = (cfg.templates_dir / "article.html").read_text(encoding="utf-8")
    e = html.escape
    return _fill(tpl, {
        "lang": cfg.get("keyword_research.language", "en"), "title": e(a["title"]), "description": e(a["meta_description"]),
        "canonical": url, "brand": e(brand), "published": a["published"], "modified": a["modified"],
        "modified_human": human_date(a["modified"]), "jsonld": jsonld, "app_url": e(cfg.app_url), "h1": e(a["h1"]),
        "reading_minutes": str(max(1, math.ceil(words / 225))), "body": body, "faq_html": faq_html,
        "cta_text": e(a.get("cta_text") or "Snap a photo and get an AI style score with tips on fit, color, and balance."),
        "related_html": related_html(related),
        "cta_button": conversion_agent.button_html(cfg, cta["button"], "end", a["slug"]),
        "feature_link": conversion_agent.landing_html(cfg, a),
        "analytics": analytics_snippet(cfg),
    })


SITE_GA_RE = re.compile(r"<!-- Google Analytics 4.*?</script>\s*<script async[^>]*></script>\s*<script>.*?</script>", re.S)


def analytics_snippet(cfg: Config) -> str:
    """GA4 for blog pages. Reuses the exact tag from index.html (Consent Mode v2, cookie banner and the
    `play_store_click` event) so blog Play Store clicks are counted like the rest of the site.
    Empty unless analytics.ga4_measurement_id is set."""
    mid = cfg.get("analytics.ga4_measurement_id")
    if not mid or not re.fullmatch(r"G-[A-Z0-9]{4,12}", str(mid)):
        return ""
    home = cfg.site_root / "index.html"
    m = SITE_GA_RE.search(home.read_text(encoding="utf-8")[:20000]) if home.exists() else None
    if m and mid in m.group(0):
        return m.group(0)
    return (f'<script async src="https://www.googletagmanager.com/gtag/js?id={mid}"></script>\n'
            "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}"
            f"gtag('js',new Date());gtag('config','{mid}',{{anonymize_ip:true}});"
            "document.addEventListener('click',function(e){var a=e.target.closest('a[data-cta]');if(!a)return;"
            "gtag('event','play_store_click',{page_path:location.pathname,placement:a.dataset.placement||'',article:a.dataset.article||'',"
            "link_url:a.href,transport_type:'beacon'});});</script>")


def pick_related(cfg: Config, articles: dict[str, Any], slug: str, n: int = 4) -> list[dict[str, str]]:
    from .research import cluster_of
    me = articles[slug]
    mine = set(tokens(me["keyword"] + " " + me["title"])) - STOP
    my_feat = cluster_of(cfg, me["keyword"])
    scored = []
    for s, a in articles.items():
        if s == slug:
            continue
        other = set(tokens(a["keyword"] + " " + a["title"])) - STOP
        same_cluster = 3 if cluster_of(cfg, a["keyword"]) == my_feat else 0  # same-feature links first
        scored.append((len(mine & other) + same_cluster, a["published"], s, a))
    scored.sort(key=lambda x: (-x[0], x[1]), reverse=False)
    out = [{"href": f"/{cfg.get('site.blog_dir')}/{s}/", "title": a["h1"]} for _, _, s, a in scored[:n]]
    if len(out) < n:
        from .agents import conversion_agent
        land = conversion_agent.landing_link(cfg, me)
        if land:
            out.append({"href": land["href"], "title": land["title"]})
    if len(out) < n:
        out.append({"href": "/how-it-works.html", "title": "How FitCheck AI works"})
    return out


def write_article(cfg: Config, a: dict[str, Any], articles: dict[str, Any]) -> Path:
    """Persists source JSON + rendered HTML. `articles` must already include `a`."""
    sp = source_path(cfg, a["slug"])
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(a, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out = article_path(cfg, a["slug"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_article(cfg, a, pick_related(cfg, articles, a["slug"])), encoding="utf-8")
    return out


def refresh_related_blocks(cfg: Config, articles: dict[str, Any]) -> list[str]:
    """Updates only the marked related-links block in every generated article (internal linking)."""
    changed = []
    for slug in articles:
        p = article_path(cfg, slug)
        if not p.exists():
            continue
        old = p.read_text(encoding="utf-8")
        new = re.sub(r"<!-- seo:related:start -->.*?<!-- seo:related:end -->",
                     lambda _m: "<!-- seo:related:start -->\n" + related_html(pick_related(cfg, articles, slug)) + "\n<!-- seo:related:end -->",
                     old, flags=re.S)
        if new != old:
            p.write_text(new, encoding="utf-8")
            changed.append(p.relative_to(cfg.site_root).as_posix())
    return changed


def write_blog_index(cfg: Config, articles: dict[str, Any]) -> Path:
    items = sorted(articles.values(), key=lambda a: a["published"], reverse=True)
    li = "\n".join(
        f'<li><a href="/{cfg.get("site.blog_dir")}/{a["slug"]}/">{html.escape(a["h1"])}</a><p>{html.escape(a.get("summary") or a["meta_description"])}</p></li>'
        for a in items) or "<li><p>New guides are on the way.</p></li>"
    tpl = (cfg.templates_dir / "blog-index.html").read_text(encoding="utf-8")
    out = cfg.blog_dir / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_fill(tpl, {"lang": cfg.get("keyword_research.language", "en"),
                               "brand": html.escape(cfg.get("project.brand_on_site")),
                               "canonical": f"{cfg.base_url}/{cfg.get('site.blog_dir')}/",
                               "app_url": html.escape(cfg.app_url), "items": li, "analytics": analytics_snippet(cfg)}), encoding="utf-8")
    return out


def write_sitemap(cfg: Config, articles: dict[str, Any]) -> Path:
    from .audit import url_for
    rows = []
    for f in cfg.get("site.static_pages", []):
        if (cfg.site_root / f).exists():
            rows.append((url_for(cfg, f), None))
    rows.append((f"{cfg.base_url}/{cfg.get('site.blog_dir')}/", max((a["modified"] for a in articles.values()), default=None)))
    for a in sorted(articles.values(), key=lambda a: a["published"]):
        rows.append((article_url(cfg, a["slug"]), a["modified"]))
    body = "\n".join(
        f"  <url>\n    <loc>{html.escape(u)}</loc>\n" + (f"    <lastmod>{m}</lastmod>\n" if m else "") + "  </url>" for u, m in rows)
    out = cfg.site_root / "sitemap.xml"
    out.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n', encoding="utf-8")
    return out


def fix_robots(cfg: Config) -> bool:
    p = cfg.site_root / "robots.txt"
    line = f"Sitemap: {cfg.base_url}/sitemap.xml"
    old = p.read_text(encoding="utf-8") if p.exists() else "User-agent: *\nAllow: /\n"
    lines = [l for l in old.splitlines() if not l.lower().startswith("sitemap:")]
    new = "\n".join(l for l in lines if l is not None).rstrip() + "\n\n" + line + "\n"
    if new != old:
        p.write_text(new, encoding="utf-8")
        return True
    return False


def add_head_meta(cfg: Config, page: Page) -> list[str]:
    """For hand-built pages: insert ONLY missing canonical / og:url / meta description tags into <head>.
    Never changes existing tags, body, layout, or styling."""
    from .audit import url_for
    p = cfg.site_root / page.path
    raw = p.read_text(encoding="utf-8")
    head_end = raw.lower().find("</head>")
    if head_end < 0:
        return []
    head = raw[:head_end].lower()
    url = url_for(cfg, page.path)
    add, done = [], []
    if cfg.get("seo.canonical_urls") and 'rel="canonical"' not in head and "rel=canonical" not in head:
        add.append(f'<link rel="canonical" href="{url}">'); done.append("canonical")
    if 'property="og:url"' not in head:
        add.append(f'<meta property="og:url" content="{url}">'); done.append("og:url")
    e = html.escape
    desc = page.meta_description or (cfg.get("site.static_meta") or {}).get(page.path, "")
    if desc and 'name="description"' not in head:
        add.append(f'<meta name="description" content="{e(desc)}">'); done.append("meta description")
    brand = cfg.get("project.brand_on_site", "FitCheck AI")
    og = {"og:type": "website", "og:site_name": brand, "og:title": page.title or brand, "og:description": desc}
    for prop, val in og.items():
        if val and f'property="{prop}"' not in head:
            add.append(f'<meta property="{prop}" content="{e(val)}">'); done.append(prop)
    if 'name="twitter:card"' not in head:
        add.append('<meta name="twitter:card" content="summary">'); done.append("twitter:card")
    if not add:
        return []
    p.write_text(raw[:head_end] + "\n".join(add) + "\n" + raw[head_end:], encoding="utf-8")
    log.info("Added %s to %s", ", ".join(done), page.path)
    return done
