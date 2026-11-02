from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

AGENT_DIR = Path(__file__).resolve().parent.parent   # seo-agent/
REPO = AGENT_DIR.parent                               # website repository root


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @property
    def base_url(self) -> str:
        return str(self.get("site.base_url")).rstrip("/")

    @property
    def site_root(self) -> Path:
        return (self.root / self.get("site.root_dir", ".")).resolve()

    @property
    def blog_dir(self) -> Path:
        return self.site_root / self.get("site.blog_dir", "blog")

    @property
    def agent_dir(self) -> Path:
        return self.root / "seo-agent"

    @property
    def data_dir(self) -> Path:
        return self.agent_dir / "data"

    @property
    def templates_dir(self) -> Path:
        return self.agent_dir / "templates"

    @property
    def app_url(self) -> str:
        return self.get("project.app_url")


def load_config(path: str | os.PathLike | None = None, root: Path | None = None) -> Config:
    root = root or REPO
    p = Path(path) if path else root / "seo-agent" / "seo-config.yaml"
    with open(p, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    cfg = Config(raw=raw, root=root)
    if "yourdomain.com" in cfg.base_url or not cfg.base_url.startswith("https://"):
        raise ValueError("site.base_url in seo-config.yaml must be your real https:// domain")
    return cfg


def load_app_facts() -> dict[str, Any]:
    with open(Path(__file__).parent / "app_facts.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None
