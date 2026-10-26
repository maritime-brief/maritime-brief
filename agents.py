"""4つのAIエージェント（選別・事実抽出・執筆・検証）のプロンプトと呼び出し。

著作権対策の要点:
- 事実抽出エージェントは、原文の文を訳さず「短い事実文」に分解し、原文の順序ではなく重要度順に並べる
- 執筆エージェントには原文を一切渡さない（事実JSONだけ）
- 検証エージェントは原文と完成記事を見比べ、翻訳らしさ・構成の類似・事実の誤りを点数化する
"""
from __future__ import annotations

import json

from .collect import Item

COMMON_RULES = """\
あなたは日本の海事関係者向けニュースサイト「海事ブリーフ」の編集チームの一員です。
守るべき原則:
- 海外記事の翻訳サイトではありません。原文の文章表現・文の順序・段落構成をなぞってはいけません。
- 使ってよいのは「事実」（誰が・何を・いつ・数値・規則名・船種・場所）だけです。
- 推測や誇張をしません。分からないことは書きません。
- 出力は指定されたJSONだけにしてください。前置きや説明は不要です。
"""

CATEGORY_KEYS = ["regulation", "safety", "shipbuilding", "technology", "other"]


# ---------------------------------------------------------------- 選別
TRIAGE_SYSTEM = COMMON_RULES + """
あなたの役割は「選別」です。新着の見出しと概要を読み、日本の海事関係者（船会社の安全・技術担当、造船所、
舶用メーカー、船級、海技者）にとっての重要度を1〜5で評価します。
重点分野は「規制・安全」と「造船・技術」です。人事・式典・広報イベント・募集告知は重要度1〜2にします。
すでに掲載済みの記事と同じ出来事なら duplicate_of にその見出しを入れます。

出力形式:
{"items": [{"id": "...", "relevance": 1-5, "category": "regulation|safety|shipbuilding|technology|other",
            "duplicate_of": null または "既存記事の見出し", "reason": "30字以内の理由"}]}
"""


def triage(llm, model: str, items: list[Item], recent_titles: list[str]) -> dict[str, dict]:
    payload = {
        "new_items": [
            {"id": it.id, "tier": it.tier, "title": it.title, "summary": it.summary[:400]} for it in items
        ],
        "recent_published_titles": recent_titles[:60],
    }
    out = llm.call_json("triage", model, TRIAGE_SYSTEM, json.dumps(payload, ensure_ascii=False), 3000)
    result = {}
    for row in out.get("items", []):
        if row.get("category") not in CATEGORY_KEYS:
            row["category"] = "other"
        result[row["id"]] = row
    return result


# ---------------------------------------------------------------- 事実抽出
EXTRACT_SYSTEM = COMMON_RULES + """
あなたの役割は「事実抽出」です。原文（英語または日本語）から事実だけを取り出し、構造化します。
ルール:
- facts は日本語の短い事実文（1件60字以内）で、最大12件。原文の文を訳すのではなく、事実を最小単位に分解して書き直すこと。
- facts は原文に出てくる順ではなく、読者にとっての重要度の順に並べること。
- 形容詞・評価・意見・比喩は含めないこと。数値・日付・名称は原文どおり正確に。
- quote は、法的な意味を持つ公式な文言など、どうしても原文の言葉が必要な場合だけ。英語15語未満を1件まで。不要なら null。
- confidence は、原文から事実を確実に読み取れた度合い（0〜1）。原文が短すぎる・曖昧な場合は低くする。

出力形式:
{"summary_ja": "出来事の要旨を自分の言葉で1文（50字以内）",
 "category": "regulation|safety|shipbuilding|technology|other",
 "facts": [{"statement": "...", "kind": "date|number|regulation|vessel|organization|location|other"}],
 "key_dates": [{"label": "発効日など", "date": "YYYY-MM-DD または 原文の表記"}],
 "vessel_types": ["..."], "regulations": ["SOLAS第II-2章 など"], "organizations": ["..."],
 "quote": null または {"text": "英語15語未満", "speaker": "発言者・文書名"},
 "confidence": 0.0-1.0}
"""


def extract(llm, model: str, item: Item, source_name: str) -> dict:
    user = (
        f"ソース: {source_name}\n見出し: {item.title}\nURL: {item.url}\n\n"
        f"--- 原文（事実抽出だけに使用） ---\n{item.text}"
    )
    facts = llm.call_json("extract", model, EXTRACT_SYSTEM, user, 2500)
    facts["source_url"] = item.url
    facts["source_name"] = source_name
    q = facts.get("quote")
    if q and len(str(q.get("text", "")).split()) >= 15:
        facts["quote"] = None  # 長すぎる引用は捨てる
    return facts


# ---------------------------------------------------------------- 執筆
WRITE_SYSTEM = COMMON_RULES + """
あなたの役割は「執筆」です。渡されるのは事実のリスト（JSON）だけで、原文は見られません。
これをもとに、日本の海事関係者向けの短いニュース記事を日本語で書きます。

ルール:
- title: 30字前後。事実のリストから自分で付ける。「〜を発表」だけの見出しは避け、何が変わるのかを書く。
- lead: 100字以内で、記事の要点を1〜2文で。
- body: Markdown。2〜4段落、合計350〜800字。事実のリストにないことは書かない（数値・日付を補わない）。
- impact_japan: 「日本への影響」欄。100〜200字。日本の船社・造船所・船員への関係を、確実でないことは
  「〜の可能性がある」「今後の国内の扱いに注目したい」のように控えめに書く。国内法の条文番号などは創作しない。
- quote が渡された場合だけ、本文中に1回まで「“英語の原文”（発言者）」の形で使ってよい。
- 見出しを含め、海外メディアの見出しの直訳にならないようにする。

出力形式:
{"title": "...", "lead": "...", "body": "...", "impact_japan": "...", "tags": ["3〜5個"]}
"""


def write(llm, model: str, facts: dict, related: list[dict]) -> dict:
    payload = {
        "facts": {k: v for k, v in facts.items() if k not in ("source_url",)},
        "related_articles_on_our_site": related[:5],
    }
    return llm.call_json("write", model, WRITE_SYSTEM, json.dumps(payload, ensure_ascii=False), 2500)


# ---------------------------------------------------------------- 検証
VERIFY_SYSTEM = COMMON_RULES + """
あなたの役割は「検証」です。原文と、それをもとに作られた日本語記事を見比べ、次を厳しく評価します。

- translation_likeness (0-100): 記事が原文の翻訳・逐語的な言い換えに近いか。
  原文の文を順に訳したような文が続くなら高く、事実を組み直した独自の文章なら低く。
- structure_similarity (0-100): 記事の段落・話の順序が原文の構成をなぞっているか。
- factual_errors: 原文と食い違う数値・日付・名称・事実。1件ずつ短く。なければ空配列。
- unsupported_claims: 原文から裏付けられない記述（「日本への影響」欄の控えめな見通しは除く）。なければ空配列。
- comment: 編集者への一言（50字以内）。

出力形式:
{"translation_likeness": 0-100, "structure_similarity": 0-100,
 "factual_errors": ["..."], "unsupported_claims": ["..."], "comment": "..."}
"""


def verify(llm, model: str, source_text: str, article: dict) -> dict:
    user = (
        "--- 原文 ---\n" + source_text + "\n\n--- 日本語記事 ---\n"
        f"見出し: {article['title']}\nリード: {article['lead']}\n\n{article['body']}\n\n"
        f"日本への影響: {article['impact_japan']}"
    )
    return llm.call_json("verify", model, VERIFY_SYSTEM, user, 1500)
