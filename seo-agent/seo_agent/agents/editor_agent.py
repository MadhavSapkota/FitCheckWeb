"""Website Editor Agent: pages, metadata, internal links, blog index, sitemap, robots.txt."""
from __future__ import annotations

from typing import Any

from .. import publisher
from ..config import Config
from ..state import State, today


def site_basics(cfg: Config, state: State, audit: dict, report: dict) -> None:
    if publisher.fix_robots(cfg):
        report["changes"].append("robots.txt: sitemap URL corrected")
    static = set(cfg.get("site.static_pages", []))
    for p in audit["pages"]:
        if p.path in static and not p.noindex:
            done = publisher.add_head_meta(cfg, p)
            if done:
                report["changes"].append(f"{p.path}: added {', '.join(done)}")
                state.data["page_updates"].append({"date": today(), "page": p.path, "change": done})


def publish(cfg: Config, a: dict[str, Any], articles: dict[str, Any]) -> None:
    articles[a["slug"]] = a
    publisher.write_article(cfg, a, articles)


def finalize(cfg: Config, articles: dict[str, Any], report: dict) -> None:
    publisher.write_blog_index(cfg, articles)
    for c in publisher.refresh_related_blocks(cfg, articles):
        if not any(c in x for x in report["changes"]):
            report["changes"].append(f"internal links refreshed: {c}")
    publisher.write_sitemap(cfg, articles)
