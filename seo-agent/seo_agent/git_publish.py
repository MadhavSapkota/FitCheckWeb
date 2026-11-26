"""Safe commit + push of the daily run's output (CI only).

- stages ONLY files the agent is known to generate; anything else is reported and stashed, never committed
- refuses to commit a file containing a configured secret
- leaves the working tree clean before rebasing
- retries fetch/push with backoff; if master moved in a conflicting way, rebuilds the output on the new master from the
  saved article (no API call) instead of merging generated files
- never pushes a second article for the same day
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import landing, recovery
from .agents import editor_agent
from .config import load_config
from .log import _SECRET_ENV, setup_logging
from .state import State, today

BACKOFF = (3, 10, 30, 60)
ATTEMPTS = len(BACKOFF) + 1
DATA_PATTERNS = (r"seo-agent/data/state\.json", r"seo-agent/data/(articles|drafts)/[A-Za-z0-9._-]+\.json",
                 r"seo-agent/data/logs/[A-Za-z0-9._-]+\.log", r"seo-agent/data/reports/[A-Za-z0-9._-]+\.md",
                 r"seo-agent/data/search-console/[A-Za-z0-9._-]+\.json")
KEEP_ON_REPLAY = ("seo-agent/data/drafts/", "seo-agent/data/logs/", "seo-agent/data/reports/", "seo-agent/data/search-console/")


class PublishError(RuntimeError):
    pass


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and p.returncode:
        raise PublishError(f"git {' '.join(args[:2])} failed: {p.stderr.strip()[:400]}")
    return p


def changed_files(root: Path) -> list[str]:
    items = git(root, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames").stdout.split("\0")
    return [i[3:] for i in items if i]


def is_expected(cfg, path: str) -> bool:
    blog = re.escape(cfg.get("site.blog_dir", "blog"))
    patterns = (rf"{blog}/index\.html", rf"{blog}/[a-z0-9-]+/index\.html", r"sitemap\.xml", r"robots\.txt", r"llms\.txt",
                *DATA_PATTERNS)
    if any(re.fullmatch(p, path) for p in patterns):
        return True
    pages = set(cfg.get("site.static_pages", []))
    if landing.enabled(cfg):
        pages |= {f"{p['slug']}/index.html" for p in landing.load(cfg).get("pages", [])}
    # Hand-built pages only when already tracked (owner-approved, committed by hand).
    return path in pages and git(cfg.site_root, "ls-files", "--error-unmatch", "--", path, check=False).returncode == 0


def assert_no_secrets(root: Path, paths: list[str]) -> None:
    secrets = {n: os.environ[n].strip() for n in _SECRET_ENV
               if n != "DATAFORSEO_LOGIN" and len(os.environ.get(n, "").strip()) >= 8}
    for path in paths:
        f = root / path
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        hit = next((n for n, v in secrets.items() if v in text), None)
        if hit or re.search(r"sk-ant-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----", text):
            raise PublishError(f"refusing to commit {path}: it contains a secret ({hit or 'key pattern'})")


def commit(cfg) -> bool:
    """Stages expected files, commits, and leaves a clean working tree. Returns False when there is nothing to commit."""
    root = cfg.site_root
    git(root, "reset", "-q")
    paths = changed_files(root)
    wanted = [p for p in paths if is_expected(cfg, p)]
    assert_no_secrets(root, wanted)
    for i in range(0, len(wanted), 200):
        git(root, "add", "-A", "--", *wanted[i:i + 200])
    made = git(root, "diff", "--cached", "--quiet", check=False).returncode != 0
    if made:
        git(root, "commit", "-q", "-m", f"SEO agent: daily update {today()}")
    left = changed_files(root)
    if left:
        print(f"::warning::unexpected files NOT committed (stashed on the runner): {', '.join(left[:30])}")
        git(root, "stash", "push", "--include-untracked", "-q", "-m", "seo-agent unexpected files")
    if changed_files(root):
        raise PublishError(f"working tree still not clean: {changed_files(root)[:10]}")
    return made


def merge_state(remote: dict, ours: dict) -> dict:
    """Keeps the newer master state and carries over what this run learned. Articles are never merged: they are re-published."""
    published = {k for k, v in remote.get("keywords", {}).items() if str(v.get("decision", "")).startswith("published:")}
    for k, v in ours.get("keywords", {}).items():
        if k not in published and not str(v.get("decision", "")).startswith("published:"):
            remote.setdefault("keywords", {})[k] = v
    for month, u in ours.get("usage", {}).items():
        m = remote.setdefault("usage", {}).setdefault(month, {})
        for key, val in u.items():
            m[key] = max(val, m.get(key, 0))
    if ours.get("runs"):
        seen = {r.get("at") for r in remote.get("runs", [])}
        remote.setdefault("runs", []).extend(r for r in ours["runs"][-1:] if r.get("at") not in seen)
    return remote


def replay(cfg, branch: str) -> None:
    """Rebuilds this run's output on top of the new master."""
    root = cfg.site_root
    state_path = cfg.data_dir / "state.json"
    ours = json.loads(state_path.read_text(encoding="utf-8"))
    mine = git(root, "diff", "--name-only", "--diff-filter=AM", "HEAD~1", "HEAD").stdout.split()
    kept = {p: (root / p).read_bytes() for p in mine if p.startswith(KEEP_ON_REPLAY)}
    before = set(State(state_path).data["articles"])
    git(root, "reset", "-q", "--hard", f"origin/{branch}")
    for p, data in kept.items():
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_bytes(data)
    cfg = load_config(root=cfg.root)
    state = State(state_path)
    remote_articles = set(state.data["articles"])
    state.data = merge_state(state.data, ours)
    had_new = bool(before - remote_articles)
    report: dict = {"changes": [], "notes": [], "errors": []}
    if had_new and recovery.publish_pending(cfg, state, report):
        editor_agent.finalize(cfg, state.data["articles"], report)
        state.data["runs"][-1]["decision"] = report["decision"]
    elif had_new:
        if state.published_today() < cfg.get("publishing.max_new_articles_per_day", 1):
            raise PublishError("master changed and the new article could not be re-applied; it stays saved as an artifact")
        state.data["runs"][-1]["decision"] = "skip: daily article limit already reached today"
    state.save()


def publish(cfg, branch: str, sleep=time.sleep) -> bool:
    """Returns True when something was pushed."""
    from .main import validate_site
    root = cfg.site_root
    if not commit(cfg):
        print("No changes today.")
        return False
    last = ""
    for attempt in range(ATTEMPTS):
        if attempt:
            sleep(BACKOFF[attempt - 1])
        f = git(root, "fetch", "-q", "origin", branch, check=False)
        if f.returncode:
            last = f"fetch failed: {f.stderr.strip()[:300]}"
            print(f"::warning::{last}")
            continue
        if git(root, "merge-base", "--is-ancestor", "HEAD", f"origin/{branch}", check=False).returncode == 0:
            return True  # an earlier push reached the server although it reported an error
        if git(root, "rebase", f"origin/{branch}", check=False).returncode:
            git(root, "rebase", "--abort", check=False)
            print("::warning::master changed in a conflicting way; rebuilding the output on the new master")
            replay(cfg, branch)
            cfg = load_config(root=cfg.root)
            if not commit(cfg):
                return False
        errors = validate_site(cfg)
        if errors:
            if all("daily article limit exceeded" in e for e in errors):
                print("::warning::another run already published today's article; rebuilding without a second one")
                replay(cfg, branch)
                if not commit(cfg):
                    return False
                errors = validate_site(cfg)
            if errors:
                raise PublishError(f"site validation failed after rebase: {errors[:5]}")
        p = git(root, "push", "-q", "origin", f"HEAD:{branch}", check=False)
        if not p.returncode:
            return True
        last = f"push failed: {p.stderr.strip()[:300]}"
        print(f"::warning::{last}")
    raise PublishError(f"could not publish after {ATTEMPTS} attempts; {last}")


def main() -> int:
    setup_logging()
    branch = os.environ.get("GITHUB_REF_NAME", "master")
    try:
        changed = publish(load_config(), branch)
    except PublishError as e:
        print(f"::error::publish failed: {e}")
        return 1
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
