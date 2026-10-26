"""設定ファイルとフォルダの場所をまとめて扱う。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Paths:
    """データを置く場所。デモ実行では別フォルダ（demo/）を使い、本番データと混ぜない。"""

    root: Path

    @property
    def content(self) -> Path:
        return self.root / "content"

    @property
    def published(self) -> Path:
        return self.content / "published"

    @property
    def pending(self) -> Path:
        return self.content / "pending"

    @property
    def rejected(self) -> Path:
        return self.content / "rejected"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def site(self) -> Path:
        return self.root / "site"

    def ensure(self) -> None:
        for p in (self.published, self.pending, self.rejected, self.data, self.site):
            p.mkdir(parents=True, exist_ok=True)


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings() -> dict:
    return load_yaml(PROJECT_ROOT / "config" / "settings.yaml")


def load_sources() -> list[dict]:
    return load_yaml(PROJECT_ROOT / "config" / "sources.yaml").get("sources", [])


def get_paths(demo: bool = False) -> Paths:
    root = PROJECT_ROOT / "demo" if demo else Path(os.environ.get("MB_DATA_ROOT", PROJECT_ROOT))
    paths = Paths(root)
    paths.ensure()
    return paths
