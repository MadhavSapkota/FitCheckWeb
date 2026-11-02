"""Crawls the local site files (the exact files GitHub Pages serves) and reports SEO issues."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .config import Config

WORD = re.compile(r"[a-z0-9']+")


@dataclass
class Page:
    path: str            # relative to site root, e.g. "blog/foo/index.html"
    url: str
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    words: int = 0
    text: str = ""
    links: list[str] = field(default_factory=list)
    imgs_missing_alt: int = 0
    noindex: bool = False
    is_article: bool = False
    issues: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        d = asdict(self)
        d.pop("text")
        d["links"] = len(self.links)
        return d


def url_for(cfg: Config, rel: str) -> str:
    rel = rel.replace("\\", "/")
    if rel == "index.html":
        return cfg.base_url + "/"
    if rel.endswith("/index.html"):
        return f"{cfg.base_url}/{rel[:-len('index.html')]}"
    return f"{cfg.base_url}/{rel}"


def tokens(text: str) -> list[str]:
    return WORD.findall(text.lower())


def parse_page(cfg: Config, file: Path) -> Page:
    rel = file.relative_to(cfg.site_root).as_posix()
    raw = file.read_text(encoding="utf-8", errors="replace")
    # Drop huge inline data URIs before parsing - the hand-built pages embed fonts/images.
    raw = re.sub(r"data:[a-z/+.-]+;base64,[A-Za-z0-9+/=]+", "data:", raw)
    soup = BeautifulSoup(raw, "html.parser")
    p = Page(path=rel, url=url_for(cfg, rel))
    p.is_article = rel.startswith(cfg.get("site.blog_dir", "blog") + "/") and rel != f"{cfg.get('site.blog_dir', 'blog')}/index.html"
    p.title = soup.title.get_text(strip=True) if soup.title else ""
    md = soup.find("meta", attrs={"name": "description"})
    p.meta_description = (md.get("content") or "").strip() if md else ""
    can = soup.find("link", rel="canonical")
    p.canonical = can.get("href", "") if can else ""
    robots = soup.find("meta", attrs={"name": "robots"})
    p.noindex = bool(robots and "noindex" in (robots.get("content") or "").lower())
    p.h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    p.h2 = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]
    p.imgs_missing_alt = sum(1 for i in soup.find_all("img") if i.get("alt") is None)
    p.links = [a.get("href") for a in soup.find_all("a", href=True)]
    for t in soup(["script", "style", "svg", "noscript"]):
        t.decompose()
    p.text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    p.words = len(tokens(p.text))

    if not p.title:
        p.issues.append("missing_title")
    elif len(p.title) > 65:
        p.issues.append("title_too_long")
    if not p.meta_description:
        p.issues.append("missing_meta_description")
    elif not 50 <= len(p.meta_description) <= 165:
        p.issues.append("meta_description_length")
    if cfg.get("seo.canonical_urls"):
        if not p.canonical:
            p.issues.append("missing_canonical")
        elif p.canonical.rstrip("/") != p.url.rstrip("/"):
            p.issues.append("canonical_mismatch")
    if len(p.h1) == 0:
        p.issues.append("missing_h1")
    elif len(p.h1) > 1:
        p.issues.append("multiple_h1")
    if p.imgs_missing_alt:
        p.issues.append("images_missing_alt")
    if not soup.find("meta", attrs={"property": "og:title"}):
        p.issues.append("missing_og_tags")
    return p


def resolve_internal(cfg: Config, page_url: str, href: str) -> Path | None:
    """Maps an internal href to the file that would serve it, or None if external/anchor."""
    if href.startswith(("mailto:", "tel:", "data:", "javascript:", "#")):
        return None
    absu = urljoin(page_url, href)
    pu = urlparse(absu)
    if pu.netloc and pu.netloc.replace("www.", "") != urlparse(cfg.base_url).netloc.replace("www.", ""):
        return None
    path = pu.path.lstrip("/")
    target = cfg.site_root / path
    if path == "" or path.endswith("/"):
        target = target / "index.html"
    return target


def broken_links(cfg: Config, page: Page) -> list[str]:
    bad = []
    for href in page.links:
        t = resolve_internal(cfg, page.url, href)
        if t is not None and not t.exists():
            bad.append(href)
    return bad


def crawl(cfg: Config) -> dict:
    root = cfg.site_root
    exclude = set(cfg.get("site.exclude_from_audit", []))
    files = [root / f for f in cfg.get("site.static_pages", []) if (root / f).exists()]
    if cfg.blog_dir.exists():
        files += sorted(cfg.blog_dir.rglob("*.html"))
    pages = [parse_page(cfg, f) for f in files if f.relative_to(root).as_posix() not in exclude]
    for p in pages:
        bl = broken_links(cfg, p)
        if bl:
            p.issues.append("broken_internal_links:" + ",".join(bl[:5]))
    site_issues = []
    robots = root / "robots.txt"
    if not robots.exists():
        site_issues.append("robots_missing")
    else:
        rt = robots.read_text(encoding="utf-8")
        if f"Sitemap: {cfg.base_url}/sitemap.xml" not in rt:
            site_issues.append("robots_sitemap_url_wrong")
        if re.search(r"(?mi)^disallow:\s*/\s*$", rt):
            site_issues.append("robots_blocks_site")
    sm = root / "sitemap.xml"
    if not sm.exists():
        site_issues.append("sitemap_missing")
    else:
        locs = set(re.findall(r"<loc>([^<]+)</loc>", sm.read_text(encoding="utf-8")))
        missing = [p.url for p in pages if not p.noindex and p.url not in locs]
        if missing:
            site_issues.append("sitemap_missing_urls:" + ",".join(missing[:10]))
        if any(cfg.base_url not in l for l in locs):
            site_issues.append("sitemap_wrong_domain")
    # near-duplicate titles
    seen: dict[str, str] = {}
    for p in pages:
        k = p.title.lower().strip()
        if k and k in seen:
            site_issues.append(f"duplicate_title:{seen[k]}|{p.path}")
        seen[k] = p.path
    return {"pages": pages, "site_issues": site_issues}


def coverage_score(keyword: str, pages: list[Page]) -> tuple[float, str | None]:
    """How well an existing page's title/H1/H2 already target the keyword (0..1) and which page."""
    kt = set(tokens(keyword)) - STOP
    if not kt:
        return 0.0, None
    best, best_page = 0.0, None
    for p in pages:
        heads = set(tokens(" ".join([p.title, *p.h1, *p.h2[:20]])))
        s = len(kt & heads) / len(kt)
        if s > best:
            best, best_page = s, p.path
    return best, best_page


STOP = {"a", "an", "the", "for", "to", "of", "and", "or", "in", "on", "with", "my", "your", "how", "what", "is",
        "are", "do", "does", "i", "you", "best", "free", "app", "apps", "online", "can", "should", "vs"}
