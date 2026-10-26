"""4つのAIエージェント（選別・事実抽出・執筆・検証）。API方式で使う。

指示文は prompts/ フォルダのファイルにあり、Claudeアプリ方式（CLAUDE_TASK.md）でも同じものを使う。

著作権対策の要点:
- 事実抽出は、原文の文を訳さず「短い事実文」に分解し、原文の順序ではなく重要度順に並べる
- 執筆には原文を一切渡さない（事実JSONだけ）
- 検証は原文と完成記事を見比べ、翻訳らしさ・構成の類似・事実の誤りを点数化する
"""
from __future__ import annotations

import json

from .config import PROJECT_ROOT

CATEGORY_KEYS = ["regulation", "safety", "shipbuilding", "technology", "other"]


def prompt(name: str) -> str:
    folder = PROJECT_ROOT / "prompts"
    return (folder / "common.md").read_text(encoding="utf-8") + "\n" + (folder / f"{name}.md").read_text(encoding="utf-8")


def triage(llm, model: str, items: list[dict], recent_titles: list[str]) -> dict[str, dict]:
    payload = {
        "new_items": [{"id": it["id"], "tier": it["tier"], "title": it["title"], "summary": it["summary"][:400]} for it in items],
        "recent_published_titles": recent_titles[:60],
    }
    out = llm.call_json("triage", model, prompt("triage"), json.dumps(payload, ensure_ascii=False), 3000)
    result = {}
    for row in out.get("items", []):
        if row.get("category") not in CATEGORY_KEYS:
            row["category"] = "other"
        result[row["id"]] = row
    return result


def extract(llm, model: str, item: dict, text: str) -> dict:
    user = (
        f"ソース: {item['source']['name']}\n見出し: {item['title']}\nURL: {item['url']}\n\n"
        f"--- 原文（事実抽出だけに使用） ---\n{text}"
    )
    return llm.call_json("extract", model, prompt("extract"), user, 2500)


def write(llm, model: str, facts: dict, related: list[dict]) -> dict:
    payload = {"facts": facts, "related_articles_on_our_site": related[:5]}
    return llm.call_json("write", model, prompt("write"), json.dumps(payload, ensure_ascii=False), 2500)


def verify(llm, model: str, source_text: str, article: dict) -> dict:
    user = (
        "--- 原文 ---\n" + source_text + "\n\n--- 日本語記事 ---\n"
        f"見出し: {article['title']}\nリード: {article['lead']}\n\n{article['body']}\n\n"
        f"日本への影響: {article.get('impact_japan', '')}"
    )
    return llm.call_json("verify", model, prompt("verify"), user, 1500)
