"""Recovery of finished articles. An article that passed the quality gate is saved as a "pending bundle" BEFORE anything is
committed; the workflow uploads it as an artifact. If publishing fails, a later run publishes that bundle without any Claude
or keyword API call.

  python -m seo_agent.recovery fetch     # download recent pending-article artifacts into $SEO_RECOVER_DIR
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import publisher, quality
from .agents import editor_agent
from .audit import crawl
from .log import log
from .state import State, today

PREFIX = "pending-article-"
MAX_AGE_DAYS = 7
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")


def save_pending(cfg, article: dict, kw: dict, review: dict) -> None:
    d = os.environ.get("SEO_PENDING_DIR")
    if not d:
        return
    p = Path(d) / f"{today()}-{article['slug']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "day": today(), "article": article, "keyword": kw, "review": review},
                            indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def load_pending() -> list[dict]:
    """Bundles from this run and from downloaded artifacts, newest first, at most MAX_AGE_DAYS old."""
    out = []
    for var in ("SEO_PENDING_DIR", "SEO_RECOVER_DIR"):
        d = os.environ.get(var)
        if not d or not Path(d).is_dir():
            continue
        for f in Path(d).rglob("*.json"):
            try:
                b = json.loads(f.read_text(encoding="utf-8"))
                age = (date.fromisoformat(today()) - date.fromisoformat(b["day"])).days
                if 0 <= age <= MAX_AGE_DAYS and SLUG_RE.fullmatch(b["article"]["slug"]) and b["keyword"] and b["review"]:
                    out.append(b)
            except (ValueError, KeyError, TypeError, OSError) as e:
                log.warning("recovery: ignoring unreadable bundle %s (%s)", f.name, type(e).__name__)
    return sorted(out, key=lambda b: b["day"], reverse=True)


def publish_pending(cfg, state: State, report: dict) -> bool:
    """Publishes at most one saved article. Re-runs the deterministic quality gate against the CURRENT site (duplicates,
    links, claims) using the stored independent review. Makes no paid API call."""
    limit = cfg.get("publishing.max_new_articles_per_day", 1)
    if state.published_today() >= limit:
        return False
    articles = state.data["articles"]
    used = state.used_keywords()
    for b in load_pending():
        a, kw = dict(b["article"]), b["keyword"]
        slug = a["slug"]
        if slug in articles or publisher.article_path(cfg, slug).exists() or a["keyword"].lower() in used:
            continue
        a["published"] = a["modified"] = today()
        html_ = publisher.render_article(cfg, a, publisher.pick_related(cfg, {**articles, slug: a}, slug))
        gate = quality.check(cfg, kw=kw, intent=a["intent"], article=a, rendered_html=html_,
                             url=publisher.article_url(cfg, slug), slug=slug, review=b["review"], existing=crawl(cfg)["pages"])
        if not gate["passed"]:
            report["notes"].append(f"recovery: saved article {slug} no longer passes the quality gate: {gate['failures']}")
            continue
        editor_agent.publish(cfg, a, articles)
        state.record_keyword(a["keyword"], kw, f"published:{slug}")
        report["decision"] = (f"published /{cfg.get('site.blog_dir')}/{slug}/ for '{a['keyword']}' "
                              f"(recovered the article saved on {b['day']}; no new API generation)")
        report["published_urls"] = [publisher.article_url(cfg, slug)]
        report["changes"].append(f"new article blog/{slug}/index.html (recovered)")
        return True
    return False


def _gh(*args: str) -> str:
    for attempt in range(4):
        p = subprocess.run(["gh", *args], capture_output=True, text=True)
        if not p.returncode:
            return p.stdout
        if attempt < 3:
            time.sleep(3 * 3 ** attempt)
    raise RuntimeError(f"gh {' '.join(args[:3])} failed: {p.stderr.strip()[:300]}")


def fetch() -> int:
    repo, dest = os.environ["GITHUB_REPOSITORY"], Path(os.environ["SEO_RECOVER_DIR"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS + 1)
    rows: list[dict] = []
    for page in range(1, 6):
        batch = json.loads(_gh("api", f"repos/{repo}/actions/artifacts?per_page=100&page={page}"))["artifacts"]
        rows += batch
        if len(batch) < 100 or datetime.fromisoformat(batch[-1]["created_at"].replace("Z", "+00:00")) < cutoff:
            break
    found = 0
    for r in rows:
        run = r.get("workflow_run") or {}
        if (r["name"].startswith(PREFIX) and not r["expired"] and run.get("head_branch") == "master"
                and run.get("repository_id") == run.get("head_repository_id")
                and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= cutoff):
            _gh("run", "download", str(run["id"]), "-R", repo, "-n", r["name"], "-D", str(dest / r["name"]))
            found += 1
    print(f"recovery: downloaded {found} saved article artifact(s)")
    return 0


if __name__ == "__main__":
    sys.exit(fetch() if sys.argv[1:] == ["fetch"] else 2)
