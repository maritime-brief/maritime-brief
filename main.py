"""パイプライン全体の司令塔（オーケストレーター）。

使い方:
    python -m pipeline.main run            # 収集から公開まで（本番。APIキーが必要）
    python -m pipeline.main run --demo     # APIもネットも使わないデモ（demo/ フォルダに出力）
    python -m pipeline.main review         # 保留記事の承認・却下を反映してサイトを作り直す
    python -m pipeline.main build          # サイトの作り直しだけ
    python -m pipeline.main check-sources  # 各ソースのRSSが読めるか確認
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import agents, checks
from .build import build_site
from .collect import Fetcher, Item, fetch_feed, fetch_text
from .config import get_paths, load_settings, load_sources
from .llm import ClaudeLLM, LLMError, MockLLM
from .store import State, load_articles, now_jst, promote_reviewed, save_article

log = logging.getLogger("pipeline")


def collect_items(settings, sources, state, demo: bool) -> tuple[list[Item], dict]:
    limits = settings["limits"]
    by_id = {s["id"]: s for s in sources}
    if demo:
        from fixtures.demo import DEMO_SOURCE, demo_items

        by_id[DEMO_SOURCE["id"]] = DEMO_SOURCE
        return [it for it in demo_items() if not state.seen(it.id)], by_id

    fetcher = Fetcher(limits["request_interval_sec"])
    items: list[Item] = []
    for src in sources:
        if not src.get("enabled") or not src.get("feed"):
            continue
        got = fetch_feed(fetcher, src, limits["items_per_feed"])
        new = [it for it in got if not state.seen(it.id)]
        log.info("収集 %-24s 新着 %d件 / 取得 %d件", src["id"], len(new), len(got))
        items.extend(new)
    collect_items.fetcher = fetcher  # 本文の取得で使い回す
    return items, by_id


def run(demo: bool, mode_override: str | None = None) -> int:
    settings = load_settings()
    sources = load_sources()
    paths = get_paths(demo)
    state = State(paths.data / "state.json")
    models, limits = settings["models"], settings["limits"]
    mode = mode_override or settings["publish"]["mode"]

    approved, rejected = promote_reviewed(paths)
    if approved or rejected:
        log.info("保留記事の反映：承認 %d件、却下 %d件", approved, rejected)

    if demo:
        from fixtures.demo import mock_handlers

        llm = MockLLM(mock_handlers())
    else:
        llm = ClaudeLLM()

    items, src_by_id = collect_items(settings, sources, state, demo)
    summary = {"at": now_jst().isoformat(timespec="minutes"), "collected": len(items),
               "published": 0, "pending": 0, "skipped": 0, "errors": 0, "leads": 0}

    # ティア3は話題メモに残すだけ
    candidates = []
    for it in items:
        if it.tier >= 3:
            state.add_lead(it)
            state.mark(it.id, "lead", it.url)
            summary["leads"] += 1
        else:
            candidates.append(it)

    published = load_articles(paths.published)
    if candidates:
        recent_titles = [a["title"] for a in published[:60]]
        scored = agents.triage(llm, models["triage"], candidates[:40], recent_titles)
        chosen = []
        for it in candidates[:40]:
            s = scored.get(it.id, {})
            if s.get("relevance", 0) >= limits["min_relevance"] and not s.get("duplicate_of"):
                chosen.append((s["relevance"], it, s))
            else:
                state.mark(it.id, "skipped", it.url, s.get("reason", "") or "重複または重要度が低い")
                summary["skipped"] += 1
        chosen.sort(key=lambda x: x[0], reverse=True)
        for rel, it, s in chosen[: limits["articles_per_run"]]:
            try:
                outcome = process_item(it, s, src_by_id[it.source_id], llm, settings, paths, published, demo, mode)
                summary[outcome] += 1
                state.mark(it.id, outcome, it.url)
            except LLMError as e:
                log.error("記事化に失敗: %s (%s)", it.title, e)
                summary["errors"] += 1
                state.mark(it.id, "error", it.url, str(e)[:200])
        # 上限を超えた分は次回に回す（記録しない）

    summary["usage"] = llm.usage
    state.log_run(summary)
    state.save()
    n = build_site(settings, paths)
    log.info("完了：公開 %d件、保留 %d件、見送り %d件、エラー %d件、話題メモ %d件 ／ サイト %d記事",
             summary["published"], summary["pending"], summary["skipped"], summary["errors"], summary["leads"], n)
    return 0


def process_item(it: Item, triage_row: dict, source: dict, llm, settings, paths, published, demo, mode) -> str:
    models, limits = settings["models"], settings["limits"]

    if demo:
        from fixtures.demo import demo_text

        it.text = demo_text(it.id)
    else:
        it.text = fetch_text(collect_items.fetcher, it.url, limits["source_text_max_chars"])
    if len(it.text) < 300:
        log.info("本文が短すぎるため見送り: %s", it.title)
        return "skipped"

    facts = agents.extract(llm, models["extract"], it, source["name"])
    category = triage_row.get("category") or facts.get("category") or "other"
    related = [{"title": a["title"], "url": f"articles/{a['slug']}.html"}
               for a in published if a.get("category") == category][:5]
    draft = agents.write(llm, models["write"], facts, related)  # ← 原文は渡さない
    review = agents.verify(llm, models["verify"], it.text, draft)
    verdict, reasons, scores = checks.evaluate(draft, it.text, it.lang, review, settings["verify"])
    if float(facts.get("confidence", 0)) < 0.6:
        verdict = "hold"
        reasons.append(f"事実抽出の確信度が低い（{facts.get('confidence')}）")

    stamp = now_jst()
    article = {
        "slug": f"{stamp:%Y%m%d}-{it.source_id}-{it.id}",
        "status": "published" if (verdict == "pass" and mode == "auto") else "pending",
        "title": draft["title"],
        "lead": draft["lead"],
        "category": category,
        "tags": draft.get("tags", []),
        "date": stamp.isoformat(timespec="minutes"),
        "impact_japan": draft.get("impact_japan", ""),
        "key_dates": facts.get("key_dates", []),
        "source": {
            "name": source["name"],
            "url": it.url,
            "title": it.title,
            "license": source.get("license", ""),
            "attribution": source.get("attribution", ""),
            "tier": source.get("tier"),
        },
        "check": {"verdict": verdict, "reasons": reasons, "scores": scores, "comment": review.get("comment", "")},
        "corrections": [],
        "body": draft["body"],
    }
    if article["status"] == "published":
        save_article(paths.published, article)
        published.insert(0, article)
        return "published"
    save_article(paths.pending, article)
    log.info("保留: %s ／ 理由: %s", article["title"], "；".join(reasons) or "試験運用モード")
    return "pending"


def check_sources() -> int:
    settings = load_settings()
    fetcher = Fetcher(settings["limits"]["request_interval_sec"])
    for src in load_sources():
        if not src.get("feed"):
            print(f"[未設定] {src['id']:<24} RSSのURLが空欄です")
            continue
        items = fetch_feed(fetcher, src, 5)
        mark = "OK  " if items else "失敗"
        state = "有効" if src.get("enabled") else "無効"
        print(f"[{mark}] {src['id']:<24} ({state}) {len(items)}件  {items[0].title[:50] if items else ''}")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="海事ブリーフ 自動更新パイプライン")
    ap.add_argument("command", choices=["run", "review", "build", "check-sources"])
    ap.add_argument("--demo", action="store_true", help="APIもネットも使わずに動作確認（demo/ に出力）")
    ap.add_argument("--mode", choices=["trial", "auto"], help="settings.yaml の公開モードを一時的に上書き")
    args = ap.parse_args(argv)

    if args.command == "run":
        return run(args.demo, args.mode)
    if args.command == "check-sources":
        return check_sources()
    settings, paths = load_settings(), get_paths(args.demo)
    if args.command == "review":
        a, r = promote_reviewed(paths)
        log.info("保留記事の反映：承認 %d件、却下 %d件", a, r)
    n = build_site(settings, paths)
    log.info("サイトを作り直しました（%d記事）", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
