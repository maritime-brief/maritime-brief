"""記事ファイル（Markdown＋先頭の設定欄）と、処理済みURLの記録を扱う。

記事ファイルの先頭は次のような形になっていて、GitHubの画面から直接書き換えられる:

    ---
    status: pending      ← approved に書き換えると次の実行で公開。rejected で却下
    title: ...
    ---
    本文
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .config import Paths

log = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

FRONT_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)


def now_jst() -> datetime:
    return datetime.now(JST)


# ---------------------------------------------------------------- 記事
def article_path(folder: Path, article: dict) -> Path:
    return folder / f"{article['slug']}.md"


def dump_article(article: dict) -> str:
    meta = {k: v for k, v in article.items() if k != "body"}
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=1000)
    return f"---\n{front}---\n{article.get('body', '').strip()}\n"


def save_article(folder: Path, article: dict) -> Path:
    path = article_path(folder, article)
    path.write_text(dump_article(article), encoding="utf-8")
    return path


def load_article(path: Path) -> dict | None:
    m = FRONT_RE.match(path.read_text(encoding="utf-8"))
    if not m:
        log.warning("記事ファイルの形式を読めませんでした: %s", path.name)
        return None
    meta = yaml.safe_load(m.group(1)) or {}
    meta["body"] = m.group(2).strip()
    meta.setdefault("slug", path.stem)
    return meta


def load_articles(folder: Path) -> list[dict]:
    arts = [a for p in sorted(folder.glob("*.md")) if (a := load_article(p))]
    return sorted(arts, key=lambda a: str(a.get("date", "")), reverse=True)


def promote_reviewed(paths: Paths) -> tuple[int, int]:
    """保留フォルダで status を approved / rejected に書き換えた記事を移動する。"""
    approved = rejected = 0
    for p in sorted(paths.pending.glob("*.md")):
        art = load_article(p)
        if not art:
            continue
        status = str(art.get("status", "")).strip().lower()
        if status == "approved":
            art["status"] = "published"
            art["date"] = now_jst().isoformat(timespec="minutes")
            art["approved_by_human"] = True
            save_article(paths.published, art)
            p.unlink()
            approved += 1
        elif status == "rejected":
            shutil.move(str(p), paths.rejected / p.name)
            rejected += 1
    return approved, rejected


# ---------------------------------------------------------------- 処理済みの記録
class State:
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"seen": {}, "leads": [], "runs": []}

    def seen(self, item_id: str) -> bool:
        return item_id in self.data["seen"]

    def mark(self, item_id: str, outcome: str, url: str, note: str = "") -> None:
        self.data["seen"][item_id] = {
            "outcome": outcome,
            "url": url,
            "note": note,
            "at": now_jst().isoformat(timespec="minutes"),
        }

    def add_lead(self, item) -> None:
        """ティア3（業界メディア）の見出し。公開はせず、話題の手がかりとして残す。"""
        self.data["leads"].insert(0, {"title": item.title, "url": item.url, "source": item.source_id,
                                      "at": now_jst().isoformat(timespec="minutes")})
        self.data["leads"] = self.data["leads"][:300]

    def log_run(self, summary: dict) -> None:
        self.data["runs"].insert(0, summary)
        self.data["runs"] = self.data["runs"][:100]

    def save(self) -> None:
        seen = self.data["seen"]
        if len(seen) > 8000:  # 古いものから捨てる
            keep = sorted(seen.items(), key=lambda kv: kv[1]["at"], reverse=True)[:6000]
            self.data["seen"] = dict(keep)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
