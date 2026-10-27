"""記事化待ちの「キュー」と、記事の仕上げ（判定・保存）。

収集（GitHub Actions、AIなし）が data/queue/<id>.json に新着を置き、
記事作成（Claudeアプリ方式 または API方式）がそれを取り出して記事にする。

本文の保存はティア1（再利用が許されたソース）だけ。ティア2は保存せず、使うときに取得する。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from . import checks
from .config import Paths
from .store import now_jst, save_article


def queue_dir(paths: Paths) -> Path:
    d = paths.data / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def enqueue(paths: Paths, item, source: dict, text: str, n_words: int = 8) -> None:
    rec = {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "summary": item.summary,
        "published": item.published,
        "tier": item.tier,
        "lang": item.lang,
        "source": {k: source.get(k, "") for k in ("id", "name", "license", "attribution", "tier", "adaptation_allowed")},
        # ティア1は本文を保存。ティア2は本文を保存せず、コピー判定用の指紋（復元不可のハッシュ）だけを保存
        "text": text if item.tier == 1 else "",
        "fingerprints": checks.fingerprints(text, item.lang, n_words) if (item.tier == 2 and text) else [],
        "queued_at": now_jst().isoformat(timespec="minutes"),
    }
    (queue_dir(paths) / f"{item.id}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def load_queue(paths: Paths) -> list[dict]:
    items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(queue_dir(paths).glob("*.json"))]
    return sorted(items, key=lambda r: r["queued_at"], reverse=True)


def load_item(paths: Paths, item_id: str) -> dict:
    return json.loads((queue_dir(paths) / f"{item_id}.json").read_text(encoding="utf-8"))


def remove(paths: Paths, item_id: str) -> None:
    p = queue_dir(paths) / f"{item_id}.json"
    if p.exists():
        p.unlink()


def expire_old(paths: Paths, days: int = 7) -> int:
    cutoff = now_jst() - timedelta(days=days)
    n = 0
    for rec in load_queue(paths):
        if datetime.fromisoformat(rec["queued_at"]) < cutoff:
            remove(paths, rec["id"])
            n += 1
    return n


def finalize(paths: Paths, settings: dict, item: dict, facts: dict, draft: dict, review: dict,
             category: str, mode: str, source_text: str) -> tuple[str, dict]:
    """検証結果と機械チェックから公開／保留を決め、記事ファイルを書いてキューから外す。"""
    q = facts.get("quote")
    if q and len(str(q.get("text", "")).split()) >= 15:
        facts["quote"] = None

    cfg = dict(settings["verify"])
    if item["source"].get("adaptation_allowed"):
        # 改変を含む再利用が明示的に許されたソース（OGL・CC BY・政府標準利用規約など）は基準を一部緩める。
        # 英文の連続一致・事実の誤り・長さのチェックはそのまま。
        cfg.update(settings["verify"].get("relaxed_for_adaptation_allowed", {}))
    verdict, reasons, scores = checks.evaluate(draft, source_text, item["lang"], review, cfg, fps=item.get("fingerprints"))
    fps = item.get("fingerprints") or []
    if not source_text and not fps:
        reasons.append("原文も指紋もないため、英文の一致チェックができない")
        verdict = "hold"
    if float(facts.get("confidence", 0)) < 0.6:
        verdict = "hold"
        reasons.append(f"事実抽出の確信度が低い（{facts.get('confidence')}）")

    stamp = now_jst()
    src = item["source"]
    article = {
        "slug": f"{stamp:%Y%m%d}-{src['id']}-{item['id']}",
        "status": "published" if (verdict == "pass" and mode == "auto") else "pending",
        "title": draft["title"],
        "lead": draft["lead"],
        "category": category if category in settings["categories"] else "other",
        "tags": draft.get("tags", []),
        "date": stamp.isoformat(timespec="minutes"),
        "impact_japan": draft.get("impact_japan", ""),
        "key_dates": facts.get("key_dates", []),
        "source": {
            "name": src["name"],
            "url": item["url"],
            "title": item["title"],
            "license": src.get("license", ""),
            "attribution": src.get("attribution", ""),
            "tier": src.get("tier"),
        },
        "check": {"verdict": verdict, "reasons": reasons, "scores": scores, "comment": review.get("comment", "")},
        "corrections": [],
        "body": draft["body"],
    }
    folder = paths.published if article["status"] == "published" else paths.pending
    save_article(folder, article)
    remove(paths, item["id"])
    return article["status"], article
