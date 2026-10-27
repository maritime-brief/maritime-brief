"""パイプライン全体の司令塔。

記事を作る方式は config/settings.yaml の engine で選ぶ:
  claude-app : Claudeのスケジュールされたタスクが記事を書く（APIキー不要。プランの利用枠を使う）
  api        : GitHub Actions が Claude API で記事を書く（APIキーが必要）

コマンド:
    python -m pipeline.main run            # 収集（＋ api 方式なら記事作成）→ サイト生成。Actionsが1日3回実行
    python -m pipeline.main collect        # 収集だけ（AIを使わない）
    python -m pipeline.main queue          # 記事化待ちの一覧をJSONで表示（Claudeアプリ方式の作業用）
    python -m pipeline.main finalize --id ID --facts F --draft D --review R --category C
                                           # 記事を判定して公開／保留に保存（Claudeアプリ方式の作業用）
    python -m pipeline.main skip --id ID --reason "..."   # 記事化しないと決めた新着を外す
    python -m pipeline.main review         # 保留記事の承認・却下を反映してサイトを作り直す
    python -m pipeline.main build          # サイトの作り直しだけ
    python -m pipeline.main check-sources  # 各ソースのRSSが読めるか確認
    （どのコマンドも --demo を付けると、架空データで demo/ フォルダに出力）
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import agents
from . import queue as q
from .build import build_site
from .collect import Fetcher, fetch_items, fetch_text
from .config import get_paths, load_settings, load_sources
from .llm import ClaudeLLM, LLMError, MockLLM
from .store import State, load_articles, now_jst, promote_reviewed

log = logging.getLogger("pipeline")


# ---------------------------------------------------------------- 収集（AIなし）
def collect(settings, paths, demo: bool) -> dict:
    limits = settings["limits"]
    state = State(paths.data / "state.json")
    summary = {"queued": 0, "leads": 0, "per_source": {}}

    if demo:
        from fixtures.demo import DEMO_SOURCE, demo_items, demo_text

        pairs = [(it, DEMO_SOURCE, demo_text(it.id)) for it in demo_items() if not state.seen(it.id)]
    else:
        fetcher = Fetcher(limits["request_interval_sec"])
        pairs = []
        for src in load_sources():
            if not src.get("enabled") or not (src.get("feed") or src.get("page")):
                continue
            got = fetch_items(fetcher, src, limits["items_per_feed"])
            new = [it for it in got if not state.seen(it.id)]
            log.info("収集 %-24s 新着 %d件 / 取得 %d件", src["id"], len(new), len(got))
            summary["per_source"][src["id"]] = {"fetched": len(got), "new": len(new)}
            for it in new:
                text = fetch_text(fetcher, it.url, limits["source_text_max_chars"]) if it.tier <= 2 else ""
                pairs.append((it, src, text))

    for it, src, text in pairs:
        if it.tier >= 3:
            state.add_lead(it)
            state.mark(it.id, "lead", it.url)
            summary["leads"] += 1
        else:
            q.enqueue(paths, it, src, text, settings["verify"]["english_run_max_words"])
            state.mark(it.id, "queued", it.url)
            summary["queued"] += 1

    summary["expired"] = q.expire_old(paths)
    state.log_run({"at": now_jst().isoformat(timespec="minutes"), "step": "collect", **summary})
    state.save()
    log.info("収集完了：キューに追加 %d件、話題メモ %d件、期限切れで削除 %d件", summary["queued"], summary["leads"], summary["expired"])
    return summary


# ---------------------------------------------------------------- API方式の記事作成
def process_queue_api(settings, paths, demo: bool, mode: str) -> dict:
    models, limits = settings["models"], settings["limits"]
    if demo:
        from fixtures.demo import mock_handlers

        llm = MockLLM(mock_handlers())
    else:
        llm = ClaudeLLM()

    items = q.load_queue(paths)[:40]
    out = {"published": 0, "pending": 0, "skipped": 0, "errors": 0}
    if not items:
        return out
    published = load_articles(paths.published)
    scored = agents.triage(llm, models["triage"], items, [a["title"] for a in published[:60]])

    chosen = []
    for it in items:
        s = scored.get(it["id"], {})
        if s.get("relevance", 0) >= limits["min_relevance"] and not s.get("duplicate_of"):
            chosen.append((s["relevance"], it, s))
        else:
            q.remove(paths, it["id"])
            out["skipped"] += 1
    chosen.sort(key=lambda x: x[0], reverse=True)

    fetcher = None
    for _, it, s in chosen[: limits["articles_per_run"]]:  # 残りは次回へ
        try:
            text = it["text"]
            if not text and not demo:  # ティア2は保存していないので、ここで取得
                fetcher = fetcher or Fetcher(limits["request_interval_sec"])
                text = fetch_text(fetcher, it["url"], limits["source_text_max_chars"])
            if len(text) < 300:
                q.remove(paths, it["id"])
                out["skipped"] += 1
                continue
            facts = agents.extract(llm, models["extract"], it, text)
            category = s.get("category") or facts.get("category") or "other"
            related = [{"title": a["title"]} for a in published if a.get("category") == category][:5]
            draft = agents.write(llm, models["write"], facts, related)  # ← 原文は渡さない
            review = agents.verify(llm, models["verify"], text, draft)
            status, art = q.finalize(paths, settings, it, facts, draft, review, category, mode, text)
            out[status if status == "published" else "pending"] += 1
            if status == "pending":
                log.info("保留: %s ／ 理由: %s", art["title"], "；".join(art["check"]["reasons"]) or "試験運用モード")
            else:
                published.insert(0, art)
        except LLMError as e:
            log.error("記事化に失敗: %s (%s)", it["title"], e)
            out["errors"] += 1
    out["usage"] = llm.usage
    return out


# ---------------------------------------------------------------- コマンド
def cmd_run(args, settings, paths) -> int:
    a, r = promote_reviewed(paths)
    if a or r:
        log.info("保留記事の反映：承認 %d件、却下 %d件", a, r)
    collect(settings, paths, args.demo)
    mode = args.mode or settings["publish"]["mode"]
    if settings.get("engine", "claude-app") == "api" or args.demo:
        out = process_queue_api(settings, paths, args.demo, mode)
        log.info("記事作成：公開 %d件、保留 %d件、見送り %d件、エラー %d件",
                 out["published"], out["pending"], out["skipped"], out["errors"])
    else:
        log.info("engine: claude-app のため、記事作成はClaudeのスケジュールされたタスクが行います（キュー %d件）",
                 len(q.load_queue(paths)))
    log.info("サイトを作り直しました（%d記事）", build_site(settings, paths))
    return 0


def cmd_queue(args, settings, paths) -> int:
    items = q.load_queue(paths)
    published = load_articles(paths.published) + load_articles(paths.pending)
    print(json.dumps({
        "mode": settings["publish"]["mode"],
        "articles_per_run": settings["limits"]["articles_per_run"],
        "min_relevance": settings["limits"]["min_relevance"],
        "categories": list(settings["categories"].keys()),
        "recent_titles": [a["title"] for a in published[:60]],
        "items": [{
            "id": it["id"], "tier": it["tier"], "source": it["source"]["name"], "title": it["title"],
            "summary": it["summary"][:400], "url": it["url"], "text_file": f"data/queue/{it['id']}.json" if it["text"] else None,
            "text_chars": len(it["text"]),
        } for it in items],
    }, ensure_ascii=False, indent=1))
    return 0


def _read_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_finalize(args, settings, paths) -> int:
    item = q.load_item(paths, args.id)
    facts, draft, review = _read_json(args.facts), _read_json(args.draft), _read_json(args.review)
    for key in ("title", "lead", "body"):
        if not draft.get(key):
            print(json.dumps({"error": f"draft に {key} がありません"}, ensure_ascii=False))
            return 1
    mode = args.mode or settings["publish"]["mode"]
    status, art = q.finalize(paths, settings, item, facts, draft, review, args.category, mode, item["text"])
    print(json.dumps({"status": status, "file": f"content/{'published' if status == 'published' else 'pending'}/{art['slug']}.md",
                      "title": art["title"], "reasons": art["check"]["reasons"], "scores": art["check"]["scores"]},
                     ensure_ascii=False, indent=1))
    return 0


def cmd_skip(args, settings, paths) -> int:
    q.remove(paths, args.id)
    State_ = State(paths.data / "state.json")
    State_.data["seen"].setdefault(args.id, {})["note"] = args.reason or ""
    State_.save()
    print(json.dumps({"skipped": args.id}, ensure_ascii=False))
    return 0


def check_sources() -> int:
    settings = load_settings()
    fetcher = Fetcher(settings["limits"]["request_interval_sec"])
    for src in load_sources():
        if not src.get("feed") and not src.get("page"):
            print(f"[未設定] {src['id']:<24} RSSのURLが空欄です")
            continue
        items = fetch_items(fetcher, src, 5)
        mark = "OK  " if items else "失敗"
        state = "有効" if src.get("enabled") else "無効"
        print(f"[{mark}] {src['id']:<24} ({state}) {len(items)}件  {items[0].title[:50] if items else ''}")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stderr)
    ap = argparse.ArgumentParser(description="海事ブリーフ 自動更新パイプライン")
    ap.add_argument("command", choices=["run", "collect", "queue", "finalize", "skip", "review", "build", "check-sources"])
    ap.add_argument("--demo", action="store_true", help="架空データで動作確認（demo/ に出力）")
    ap.add_argument("--mode", choices=["trial", "auto"], help="settings.yaml の公開モードを一時的に上書き")
    ap.add_argument("--id")
    ap.add_argument("--facts")
    ap.add_argument("--draft")
    ap.add_argument("--review")
    ap.add_argument("--category", default="other")
    ap.add_argument("--reason", default="")
    args = ap.parse_args(argv)

    if args.command == "check-sources":
        return check_sources()
    settings, paths = load_settings(), get_paths(args.demo)
    if args.command == "run":
        return cmd_run(args, settings, paths)
    if args.command == "collect":
        collect(settings, paths, args.demo)
        log.info("サイトを作り直しました（%d記事）", build_site(settings, paths))
        return 0
    if args.command == "queue":
        return cmd_queue(args, settings, paths)
    if args.command == "finalize":
        return cmd_finalize(args, settings, paths)
    if args.command == "skip":
        return cmd_skip(args, settings, paths)
    if args.command == "review":
        a, r = promote_reviewed(paths)
        log.info("保留記事の反映：承認 %d件、却下 %d件", a, r)
    log.info("サイトを作り直しました（%d記事）", build_site(settings, paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
