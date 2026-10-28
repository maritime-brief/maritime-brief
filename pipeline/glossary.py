"""用語辞書（data/glossary.yaml）。

- 用語解説の担当が書き、チェックの担当が確かめた解説を、記事をまたいで使い回す。
  同じ用語には、どの記事でも同じ解説が付く。
- status: auto はAIが書いてチェックを通ったもの。人が確かめたら approved に書き換える。
  approved の解説は、AIが上書きしない。
- 解説を直したいときは、このファイルを書き換える。次にサイトを作り直したときから、全記事に反映される。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .store import now_jst


def path(data_dir: Path) -> Path:
    return data_dir / "glossary.yaml"


def load(data_dir: Path) -> dict:
    p = path(data_dir)
    if not p.exists():
        return {}
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("terms", {}) or {}


def save(data_dir: Path, terms: dict) -> None:
    header = (
        "# 用語辞書。記事の「用語解説」欄とサイトの用語集に使われます。\n"
        "# 解説を直したら status を approved にしてください（AIが上書きしなくなります）。\n"
    )
    body = yaml.safe_dump({"terms": dict(sorted(terms.items()))}, allow_unicode=True, sort_keys=False, width=1000)
    path(data_dir).write_text(header + body, encoding="utf-8")


def index(terms: dict) -> list[dict]:
    """用語解説の担当に渡す、辞書にある用語の一覧（解説本文は渡さない）。"""
    return [{"key": k, "headword": v.get("headword", k)} for k, v in terms.items()]


def merge(data_dir: Path, explained: dict, checked: dict, slug: str) -> list[dict]:
    """用語解説とチェックの結果を辞書に反映し、記事に付ける用語の一覧を返す。

    explained: 用語解説の担当の出力 {"terms": [...]}
    checked:   チェックの担当の出力 {"terms": [{"key", "verdict", "explanation"?}]}
    """
    terms = load(data_dir)
    verdicts = {c["key"]: c for c in (checked or {}).get("terms", [])}
    attached = []
    for t in (explained or {}).get("terms", [])[:6]:
        key, term = t.get("key"), t.get("term")
        if not key or not term:
            continue
        if t.get("reuse"):
            if key not in terms:
                continue  # 辞書にない語を reuse と言ってきたら付けない
        else:
            c = verdicts.get(key, {"verdict": "drop"})  # チェックを通っていない解説は使わない
            if c["verdict"] == "drop":
                continue
            text = c.get("explanation") if c["verdict"] == "fix" else t.get("explanation")
            if not text:
                continue
            if terms.get(key, {}).get("status") != "approved":
                terms[key] = {
                    "headword": t.get("headword") or term,
                    "explanation": text.strip(),
                    "status": "auto",
                    "added": terms.get(key, {}).get("added") or now_jst().date().isoformat(),
                    "aliases": sorted(set(terms.get(key, {}).get("aliases", []) + [term])),
                }
        entry = terms[key]
        if term not in entry.setdefault("aliases", []):
            entry["aliases"] = sorted(set(entry["aliases"] + [term]))
        used = entry.setdefault("used_in", [])
        if slug not in used:
            used.append(slug)
        attached.append({"key": key, "term": term})
    save(data_dir, terms)
    return attached


def background(explained: dict | None, checked: dict | None) -> str | None:
    """背景の一言。チェックで ok なら元の文、fix なら直した文。drop やチェックなしなら付けない。"""
    text = (explained or {}).get("background")
    if not text:
        return None
    v = (checked or {}).get("background_verdict")
    if v == "ok":
        return text.strip()
    if v == "fix" and (checked or {}).get("background"):
        return checked["background"].strip()
    return None


def link_first_occurrences(body_md: str, items: list[dict]) -> str:
    """本文中で、各用語が最初に出てくる箇所を用語解説欄へのリンクにする（Markdown のまま）。"""
    out = body_md
    numbered = list(enumerate(items, 1))
    # 長い語から先に処理する（「LNG」より先に「LNG運搬船」をリンクし、語の一部を誤ってリンクしない）
    for i, it in sorted(numbered, key=lambda x: -len(x[1]["term"])):
        term = it["term"]
        # すでにリンクの中にある語や、ほかの用語の一部になっている箇所は避ける
        pattern = re.compile(r"(?<!\[)" + re.escape(term) + r"(?![^\[]*\])")
        out, n = pattern.subn(f"[{term}](#g-{i})", out, count=1)
    return out
