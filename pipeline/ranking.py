"""1日の記事ランキング。GoatCounter（クッキーを使わない閲覧数の集計サービス）から直近の閲覧数を取る。

- config/settings.yaml の analytics.goatcounter_code と、環境変数 GOATCOUNTER_TOKEN（GitHub の Secrets）が
  そろっているときだけ動く。どちらかがなければ何もしない（ランキング欄は表示されない）。
- 結果は data/ranking.json に保存する（リポジトリには保存しない。サイトを作るたびに取り直す）。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import requests

from .config import Paths

log = logging.getLogger(__name__)
SLUG_RE = re.compile(r"/articles/([^/]+)\.html$")


def path(paths: Paths):
    return paths.data / "ranking.json"


def fetch(settings: dict, paths: Paths) -> dict:
    cfg = settings.get("analytics", {}) or {}
    code, token = cfg.get("goatcounter_code"), os.environ.get("GOATCOUNTER_TOKEN")
    if not code or not token:
        return {"skipped": "GoatCounter のコードまたは API キーが未設定"}
    hours = int(cfg.get("ranking_hours", 24))
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    start = end - timedelta(hours=hours)
    try:
        r = requests.get(
            f"https://{code}.goatcounter.com/api/v0/stats/hits",
            params={"start": start.isoformat().replace("+00:00", "Z"), "end": end.isoformat().replace("+00:00", "Z"),
                    "limit": 100},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("ランキングの取得に失敗しました: %s", e)
        return {"error": str(e)[:200]}
    items = []
    for h in r.json().get("hits", []):
        m = SLUG_RE.search(h.get("path", ""))
        if m and h.get("count", 0) > 0:
            items.append({"slug": m.group(1), "count": int(h["count"])})
    items.sort(key=lambda x: -x["count"])
    out = {"updated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="minutes"),
           "window_hours": hours, "items": items}
    path(paths).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "articles": len(items)}


def load(paths: Paths) -> dict | None:
    p = path(paths)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
