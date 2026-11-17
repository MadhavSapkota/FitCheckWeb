"""Render the app comparison pages (/compare/ and /compare/fitcheck-vs-<app>/) from seo-agent/compare_pages.yaml.

Every statement about another app must come from that app's own Google Play listing (source_url) and be re-checked
before the `checked` date is changed. FitCheck statements must match seo_agent/app_facts.yaml.

Usage (from the repo root):  python seo-agent/tools/build_compare.py
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import yaml

AGENT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT))

from seo_agent.config import load_config  # noqa: E402
from seo_agent.publisher import _fill, analytics_snippet, human_date  # noqa: E402

e = html.escape


def _icon(name: str, rival: str, size: int = 56, cls: str = "app-ico") -> str:
    """Small app icon <img>. name = file stem in assets/compare/ (<name>-icon.png)."""
    return (f'<img class="{cls}" src="/assets/compare/{e(name)}-icon.png" alt="{e(rival)} app icon" '
            f'width="{size}" height="{size}" loading="lazy" decoding="async">')


def _stem(p: dict) -> str:
    return p["slug"].removeprefix("fitcheck-vs-")


def _jsonld(graph: list[dict]) -> str:
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False).replace("</", "<\\/")


def _faq(faqs: list[dict]) -> tuple[str, dict]:
    htm = "".join(f"<details><summary>{e(f['q'])}</summary><p>{e(f['a'])}</p></details>" for f in faqs)
    node = {"@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faqs]}
    return f'<section class="faq" aria-labelledby="faq-h"><h2 id="faq-h">Frequently asked questions</h2>{htm}</section>', node


def _page(cfg, tpl: str, *, url: str, d: dict, crumbs: str, body: str, more: str, graph: list[dict], slug: str, icons: str = "") -> str:
    brand = cfg.get("project.brand_on_site", "FitCheck AI")
    app = cfg.app_url

    def cta(placement: str) -> str:
        return (f'<a class="cta" href="{e(app)}" target="_blank" rel="noopener" data-cta="play-store" '
                f'data-placement="{placement}" data-article="{e(slug)}">{e(d["cta"]["button"])}</a>')

    return _fill(tpl, {
        "lang": cfg.get("keyword_research.language", "en"), "title": e(d["title"]), "description": e(d["meta"]),
        "canonical": url, "brand": e(brand), "og_image": e(cfg.base_url + "/assets/social-card.png"),
        "jsonld": _jsonld(graph), "app_url": e(app), "analytics": analytics_snippet(cfg), "crumbs": crumbs,
        "h1": e(d["h1"]), "icons": icons, "lede": e(d["lede"]), "hero_cta": cta("hero"), "body": body, "more": more,
        "cta_title": e(d["cta"]["title"]), "cta_text": e(d["cta"]["text"]), "end_cta": cta("end"),
    })


def build() -> list[Path]:
    cfg = load_config()
    data = yaml.safe_load((AGENT / "compare_pages.yaml").read_text(encoding="utf-8"))
    tpl = (cfg.templates_dir / "compare.html").read_text(encoding="utf-8")
    brand = cfg.get("project.brand_on_site", "FitCheck AI")
    base, checked = cfg.base_url, human_date(data["checked"])
    site = {"@type": "WebSite", "url": base + "/", "name": brand}
    pages, out = data["pages"], []
    features = "".join(f'<li><a href="{e(f["href"])}">{e(f["text"])}</a></li>' for f in data["features"])
    features_nav = f'<nav class="lp-more" aria-label="FitCheck features"><h2>FitCheck features</h2><ul>{features}</ul></nav>'

    def write(rel: str, text: str) -> None:
        f = cfg.site_root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            f.write_text(text, encoding="utf-8")
            out.append(f)

    # ---- index
    ix, iurl = data["index"], f"{base}/compare/"
    cards = "".join(
        f'<li><div class="cmp-vs">{_icon("fitcheck", "FitCheck")}<span aria-hidden="true">vs</span>{_icon(_stem(p), p["rival"])}</div>'
        f'<a href="/compare/{e(p["slug"])}/">FitCheck vs {e(p["rival"])}</a><p>{e(p["summary"])}</p>'
        f'<p class="small">Best known for: {e(p["known_for"])}</p></li>' for p in pages)
    faq_html, faq_node = _faq(ix["faqs"])
    body = (f'<section aria-labelledby="list-h"><h2 id="list-h">{e(ix["list_title"])}</h2><ul class="cmp-cards">{cards}</ul></section>'
            f'<section><h2>{e(ix["method_title"])}</h2>' + "".join(f"<p>{e(x)}</p>" for x in ix["method"])
            + f'<p class="cmp-note">Last checked: {e(checked)}.</p></section>' + faq_html)
    graph = [
        {"@type": "CollectionPage", "@id": iurl, "url": iurl, "name": ix["title"], "description": ix["meta"], "inLanguage": "en", "isPartOf": site},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": base + "/"},
            {"@type": "ListItem", "position": 2, "name": "Compare apps", "item": iurl}]},
        {"@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "position": k + 1, "name": f"FitCheck vs {p['rival']}", "url": f"{iurl}{p['slug']}/"} for k, p in enumerate(pages)]},
        faq_node]
    hero_icons = ('<div class="cmp-vs cmp-vs-lg">' + _icon("fitcheck", "FitCheck", 72) + '<span aria-hidden="true">vs</span>'
                  + "".join(_icon(_stem(p), p["rival"], 72) for p in pages) + "</div>")
    write("compare/index.html", _page(cfg, tpl, url=iurl, d=ix, slug="compare", body=body, more=features_nav, graph=graph, icons=hero_icons,
                                      crumbs='<a href="/">Home</a> › <span>Compare apps</span>'))

    # ---- one page per rival app
    for p in pages:
        if not re.fullmatch(r"[a-z0-9-]+", p["slug"]):
            raise ValueError(f"bad compare slug {p['slug']}")
        url, r = f"{iurl}{p['slug']}/", p["rival"]
        rows = "".join(f'<tr><th scope="row">{e(a)}</th><td>{e(b)}</td><td>{e(c)}</td></tr>' for a, b, c in p["rows"])
        table = (f'<table class="cmp-table"><thead><tr><th scope="col">Feature</th><th scope="col"><span class="cmp-th">{_icon("fitcheck", "FitCheck", 28, "app-ico-sm")}FitCheck</span></th>'
                 f'<th scope="col"><span class="cmp-th">{_icon(_stem(p), r, 28, "app-ico-sm")}{e(r)}</span></th></tr></thead><tbody>{rows}</tbody></table>')
        pick = lambda items: "".join(f"<li><strong>{e(i['title'])}</strong> {e(i['text'])}</li>" for i in items)  # noqa: E731
        faq_html, faq_node = _faq(p["faqs"])
        body = (
            f'<section><h2>The short answer</h2>' + "".join(f"<p>{e(x)}</p>" for x in p["quick"]) + "</section>"
            f'<section aria-labelledby="table-h"><h2 id="table-h">FitCheck vs {e(r)} at a glance</h2>{table}'
            f'<p class="cmp-note">{e(r)} details are taken from its <a href="{e(p["source_url"])}" target="_blank" rel="noopener nofollow">Google Play listing</a>, '
            f'checked on {e(checked)}. "Not mentioned" means the listing does not describe that feature; it may still exist in the app.</p></section>'
            f'<section><h2>Choose {e(r)} if</h2><ul class="lp-list">{pick(p["pick_rival"])}</ul></section>'
            f'<section><h2>Choose FitCheck if</h2><ul class="lp-list">{pick(p["pick_fitcheck"])}</ul></section>'
            f'<section><h2>How we compared</h2><p>We compared what each app says about itself on Google Play. We did not score, rank or test '
            f'{e(r)}, and features, prices and limits change, so check both listings before you decide.</p>'
            f'<p>FitCheck is not affiliated with, endorsed by or sponsored by {e(p["developer"])}. {e(r)} is a trademark of its owner. '
            f'FitCheck feedback is an AI opinion to use as a second opinion, not a professional or medical assessment.</p></section>'
            + faq_html)
        others = "".join(f'<li><a href="/compare/{e(o["slug"])}/">FitCheck vs {e(o["rival"])}</a></li>' for o in pages if o["slug"] != p["slug"])
        related = "".join(f'<li><a href="{e(x["href"])}">{e(x["text"])}</a></li>' for x in p["related"])
        more = (f'<section class="related" aria-labelledby="rel-h"><h2 id="rel-h">Related pages</h2><ul>{related}</ul></section>'
                f'<nav class="lp-more" aria-label="More comparisons"><h2>More comparisons</h2><ul>{others}<li><a href="/compare/">All comparisons</a></li></ul></nav>')
        graph = [
            {"@type": "WebPage", "@id": url, "url": url, "name": p["title"], "description": p["meta"], "inLanguage": "en",
             "isPartOf": site, "dateModified": data["checked"]},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": base + "/"},
                {"@type": "ListItem", "position": 2, "name": "Compare apps", "item": iurl},
                {"@type": "ListItem", "position": 3, "name": f"FitCheck vs {r}", "item": url}]},
            faq_node]
        write(f"compare/{p['slug']}/index.html", _page(
            cfg, tpl, url=url, d=p, slug=p["slug"], body=body, more=more, graph=graph,
            icons='<div class="cmp-vs cmp-vs-lg">' + _icon("fitcheck", "FitCheck", 72) + '<span aria-hidden="true">vs</span>' + _icon(_stem(p), r, 72) + "</div>",
            crumbs=f'<a href="/">Home</a> › <a href="/compare/">Compare apps</a> › <span>FitCheck vs {e(r)}</span>'))
    return out


if __name__ == "__main__":
    for f in build():
        print("wrote", f)
