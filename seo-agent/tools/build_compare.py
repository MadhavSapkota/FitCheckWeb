"""Render the app comparison pages (/compare/, /compare/fitcheck-vs-<app>/, /compare/best-style-apps/).

Data: seo-agent/compare_pages.yaml (pages, FAQs, tables) + seo-agent/compare_extra.yaml (plus points, top-5 matrix).
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
from seo_agent.publisher import _fill, analytics_snippet, ensure_entities, human_date  # noqa: E402

e = html.escape


def _icon(name: str, rival: str, size: int = 56, cls: str = "app-ico") -> str:
    """Small app icon <img>. name = file stem in assets/compare/ (<name>-icon.png)."""
    return (f'<img class="{cls}" src="/assets/compare/{e(name)}-icon.png" alt="{e(rival)} app icon" '
            f'width="{size}" height="{size}" loading="lazy" decoding="async">')


def _stem(p: dict) -> str:
    return p["slug"].removeprefix("fitcheck-vs-")


def _cell(txt: str, fc: bool = False) -> str:
    """Table cell with a check / cross / muted 'not mentioned' marker. Text is always kept for screen readers."""
    t = txt.strip()
    extra = ' class="fc"' if fc else ""
    if t.startswith("Not mentioned"):
        return f'<td{extra}><span class="nm">{e(t)}</span></td>'
    if re.match(r"No\b", t):
        return f'<td{extra}><span class="mk n" role="img" aria-label="No">✕</span> {e(re.sub(r"^No[.,]?\s*", "", t))}</td>'
    if re.match(r"Yes\b", t):
        rest = re.sub(r"^Yes[.,]?\s*", "", t)
        return f'<td{extra}><span class="mk y" role="img" aria-label="Yes">✓</span> {e(rest)}</td>'
    return f"<td{extra}>{e(t)}</td>"


def _points(items: list[dict], cls: str) -> str:
    return (f'<ul class="pp-list {cls}">'
            + "".join(f'<li><span class="mk y" aria-hidden="true">✓</span><div><strong>{e(i["title"])}</strong><span>{e(i["text"])}</span></div></li>' for i in items)
            + "</ul>")


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
        "jsonld": _jsonld(ensure_entities(graph, cfg)), "app_url": e(app), "analytics": analytics_snippet(cfg), "crumbs": crumbs,
        "h1": e(d["h1"]), "icons": icons, "lede": e(d["lede"]), "hero_cta": cta("hero"), "body": body, "more": more,
        "cta_title": e(d["cta"]["title"]), "cta_text": e(d["cta"]["text"]), "end_cta": cta("end"),
    })


def build() -> list[Path]:
    cfg = load_config()
    data = yaml.safe_load((AGENT / "compare_pages.yaml").read_text(encoding="utf-8"))
    extra = yaml.safe_load((AGENT / "compare_extra.yaml").read_text(encoding="utf-8"))
    tpl = (cfg.templates_dir / "compare.html").read_text(encoding="utf-8")
    brand = cfg.get("project.brand_on_site", "FitCheck AI")
    base, checked = cfg.base_url, human_date(data["checked"])
    site = {"@type": "WebSite", "@id": base + "/#website", "url": base + "/", "name": brand}
    team = {"@type": "Organization", "name": "FitCheck Team", "url": base + "/about/"}
    pages, out = data["pages"], []
    fc_plus = extra["fitcheck_plus"]
    features = "".join(f'<li><a href="{e(f["href"])}">{e(f["text"])}</a></li>' for f in data["features"])
    features_nav = f'<nav class="lp-more" aria-label="FitCheck features"><h2>FitCheck features</h2><ul>{features}</ul></nav>'

    def write(rel: str, text: str) -> None:
        f = cfg.site_root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            f.write_text(text, encoding="utf-8")
            out.append(f)

    t5 = data.get("top5")

    # ---- index
    ix, iurl = data["index"], f"{base}/compare/"
    top = ""
    if t5:
        top = ('<li class="cmp-top"><div class="cmp-top-in"><div class="cmp-stack">' + _icon("fitcheck", "FitCheck", 64)
               + "".join(_icon(_stem(x), x["rival"], 64) for x in pages) + '</div><div>'
               '<span class="cmp-eyebrow">All 5 at once</span>'
               f'<a class="cmp-link" href="/compare/{e(t5["slug"])}/">Best style apps compared</a>'
               '<p>FitCheck next to YouCam Makeup, Acloset, Whering, Alta and Fits, feature by feature.</p></div>'
               '<span class="cmp-go">See the full table →</span></div></li>')
    cards = "".join(
        f'<li><div class="cmp-vs">{_icon("fitcheck", "FitCheck", 60)}<span aria-hidden="true">vs</span>{_icon(_stem(p), p["rival"], 60)}</div>'
        f'<a class="cmp-link" href="/compare/{e(p["slug"])}/">FitCheck vs {e(p["rival"])}</a><p>{e(p["summary"])}</p>'
        f'<span class="cmp-chip">Best known for: {e(p["known_for"])}</span><span class="cmp-go">Read the comparison →</span></li>' for p in pages)
    faq_html, faq_node = _faq(ix["faqs"])
    body = (f'<section aria-labelledby="list-h"><h2 id="list-h">{e(ix["list_title"])}</h2><ul class="cmp-cards">{top}{cards}</ul></section>'
            f'<section><h2>{e(ix["method_title"])}</h2>' + "".join(f"<p>{e(x)}</p>" for x in ix["method"])
            + f'<p class="cmp-note">Last checked: {e(checked)}.</p></section>' + faq_html)
    graph = [
        {"@type": "CollectionPage", "@id": iurl, "url": iurl, "name": ix["title"], "description": ix["meta"], "inLanguage": "en", "isPartOf": site},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": base + "/"},
            {"@type": "ListItem", "position": 2, "name": "Compare apps", "item": iurl}]},
        {"@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "position": k + 1, "name": f"FitCheck vs {p['rival']}", "url": f"{iurl}{p['slug']}/"} for k, p in enumerate(pages)]
         + [{"@type": "ListItem", "position": len(pages) + 1, "name": "Best style apps compared", "url": f"{iurl}best-style-apps/"}]},
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
        rows = "".join(f'<tr><th scope="row">{e(a)}</th>{_cell(b, True)}{_cell(c)}</tr>' for a, b, c in p["rows"])
        table = (f'<table class="cmp-table"><thead><tr><th scope="col">Feature</th><th scope="col" class="fc"><span class="cmp-th">{_icon("fitcheck", "FitCheck", 28, "app-ico-sm")}FitCheck</span></th>'
                 f'<th scope="col"><span class="cmp-th">{_icon(_stem(p), r, 28, "app-ico-sm")}{e(r)}</span></th></tr></thead><tbody>{rows}</tbody></table>')
        pick = lambda items: "".join(f"<li><strong>{e(i['title'])}</strong> {e(i['text'])}</li>" for i in items)  # noqa: E731
        faq_html, faq_node = _faq(p["faqs"])
        rival_plus = extra["plus_rival"][p["slug"]]
        plus = (
            f'<section aria-labelledby="pp-h"><h2 id="pp-h">Plus points: FitCheck vs {e(r)}</h2><div class="pp-grid">'
            f'<div class="pp-card pp-fc"><div class="pp-head">{_icon("fitcheck", "FitCheck", 44)}<div><h3>FitCheck plus points</h3><p>{len(fc_plus)} things it does</p></div></div>{_points(fc_plus, "pp-dark")}</div>'
            f'<div class="pp-card"><div class="pp-head">{_icon(_stem(p), r, 44)}<div><h3>{e(r)} plus points</h3><p>{len(rival_plus)} things its listing describes</p></div></div>{_points(rival_plus, "")}</div>'
            f'</div></section>')
        body = (
            f'<section><h2>The short answer</h2>' + "".join(f"<p>{e(x)}</p>" for x in p["quick"]) + "</section>" + plus
            + f'<section aria-labelledby="table-h"><h2 id="table-h">FitCheck vs {e(r)} at a glance</h2>{table}'
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
             "isPartOf": site, "author": team, "dateModified": data["checked"]},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": base + "/"},
                {"@type": "ListItem", "position": 2, "name": "Compare apps", "item": iurl},
                {"@type": "ListItem", "position": 3, "name": f"FitCheck vs {r}", "item": url}]},
            faq_node]
        write(f"compare/{p['slug']}/index.html", _page(
            cfg, tpl, url=url, d=p, slug=p["slug"], body=body, more=more, graph=graph,
            icons='<div class="cmp-vs cmp-vs-lg">' + _icon("fitcheck", "FitCheck", 72) + '<span aria-hidden="true">vs</span>' + _icon(_stem(p), r, 72) + "</div>",
            crumbs=f'<a href="/">Home</a> › <a href="/compare/">Compare apps</a> › <span>FitCheck vs {e(r)}</span>'))

    # ---- top-5 overview page (coverage bars + one matrix, FitCheck vs five apps)
    if t5:
        url = f"{iurl}{t5['slug']}/"
        by = {_stem(x): x for x in pages}
        apps = [by[k] for k in extra["top5_apps"]]
        feat_rows = [r for r in extra["top5_rows"] if isinstance(r, list)]
        total = len(feat_rows)
        counts = [("FitCheck", "fitcheck", sum(r[1].startswith("Yes") for r in feat_rows), True)] + [
            (a["rival"], _stem(a), sum(r[2 + k].startswith("Yes") for r in feat_rows), False) for k, a in enumerate(apps)]
        bars = "".join(
            f'<li class="{"fc" if fc else ""}"><span class="bar-name">{_icon(stem, name, 36)}<b>{e(name)}</b></span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{round(100 * n / total)}%"></span></span>'
            f'<span class="bar-n">{n}<small>/{total}</small></span></li>'
            for name, stem, n, fc in sorted(counts, key=lambda c: -c[2]))
        head = ('<th scope="col">Feature</th><th scope="col" class="fc"><span class="cmp-th">' + _icon("fitcheck", "FitCheck", 28, "app-ico-sm") + "FitCheck</span></th>"
                + "".join(f'<th scope="col"><span class="cmp-th">{_icon(_stem(a), a["rival"], 28, "app-ico-sm")}{e(a["rival"])}</span></th>' for a in apps))
        rows = ""
        for r in extra["top5_rows"]:
            if isinstance(r, dict):
                rows += f'<tr class="cat"><th scope="colgroup" colspan="{2 + len(apps)}">{e(r["cat"])}</th></tr>'
            else:
                rows += f'<tr><th scope="row">{e(r[0])}</th>{_cell(r[1], True)}' + "".join(_cell(c) for c in r[2:]) + "</tr>"
        srcs = ", ".join(f'<a href="{e(a["source_url"])}" target="_blank" rel="noopener nofollow">{e(a["rival"])}</a>' for a in apps)
        pick = lambda items: "".join(f"<li><strong>{e(i['title'])}</strong> {e(i['text'])}</li>" for i in items)  # noqa: E731
        faq_html, faq_node = _faq(t5["faqs"])
        links = "".join(f'<li><a href="/compare/{e(a["slug"])}/">FitCheck vs {e(a["rival"])}</a></li>' for a in apps)
        related = "".join(f'<li><a href="{e(x["href"])}">{e(x["text"])}</a></li>' for x in t5["related"])
        body = (
            f'<section aria-labelledby="cov-h"><h2 id="cov-h">Features described, out of {total}</h2>'
            f'<ul class="cmp-bars">{bars}</ul>'
            f'<p class="cmp-note">Counts only the {total} features in the table below, as each app describes itself on Google Play. '
            f'It is a feature count, not a quality score, and it includes the features where other apps lead.</p></section>'
            f'<section aria-labelledby="plus-h"><h2 id="plus-h">{len(fc_plus)} FitCheck plus points</h2>'
            f'<div class="pp-card pp-fc pp-wide">{_points(fc_plus, "pp-dark pp-cols")}</div></section>'
            f'<section aria-labelledby="t5-h"><h2 id="t5-h">FitCheck vs five top style apps, feature by feature</h2>'
            f'<div class="cmp-scroll"><table class="cmp-table cmp-wide"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
            f'<p class="cmp-note">Details about the other apps come from their Google Play listings ({srcs}), checked on {e(checked)}. '
            f'"Not mentioned" means the listing does not describe that feature; it may still exist in the app.</p></section>'
            f'<section><h2>Where the other apps lead</h2><ul class="lp-list">{pick(t5["others_lead"])}</ul></section>'
            f'<section><h2>Read each comparison</h2><ul>{links}</ul></section>'
            f'<section><h2>How we compared</h2><p>We compared what each app says about itself on Google Play. We did not score, rank or test the other apps, '
            f'and features, prices and limits change, so check each listing before you decide.</p>'
            f'<p>FitCheck is not affiliated with, endorsed by or sponsored by any app compared here. All app names are trademarks of their owners. '
            f'FitCheck feedback is an AI opinion to use as a second opinion, not a professional or medical assessment.</p></section>' + faq_html)
        more = (f'<section class="related" aria-labelledby="rel-h"><h2 id="rel-h">Related pages</h2><ul>{related}</ul></section>'
                f'<nav class="lp-more" aria-label="More comparisons"><h2>More comparisons</h2><ul><li><a href="/compare/">All comparisons</a></li></ul></nav>')
        icons = ('<div class="cmp-vs cmp-vs-lg">' + _icon("fitcheck", "FitCheck", 72) + '<span aria-hidden="true">vs</span>'
                 + "".join(_icon(_stem(a), a["rival"], 72) for a in apps) + "</div>")
        graph = [
            {"@type": "WebPage", "@id": url, "url": url, "name": t5["title"], "description": t5["meta"], "inLanguage": "en",
             "isPartOf": site, "author": team, "dateModified": data["checked"]},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": base + "/"},
                {"@type": "ListItem", "position": 2, "name": "Compare apps", "item": iurl},
                {"@type": "ListItem", "position": 3, "name": "Best style apps compared", "item": url}]},
            faq_node]
        write(f"compare/{t5['slug']}/index.html", _page(
            cfg, tpl, url=url, d=t5, slug=t5["slug"], body=body, more=more, graph=graph, icons=icons,
            crumbs='<a href="/">Home</a> › <a href="/compare/">Compare apps</a> › <span>Best style apps compared</span>'))
    return out


if __name__ == "__main__":
    for f in build():
        print("wrote", f)
