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


FIELDS = ("original", "summary", "detail", "related")


def _apply_check(t: dict, c: dict) -> dict | None:
    """解説担当の出力 t に、チェックの結果 c を当てる。使えない場合は None。"""
    if c.get("verdict", "drop") == "drop":
        return None
    out = {k: t.get(k) for k in FIELDS}
    if c["verdict"] == "fix":
        for k in FIELDS:
            if k in c:
                out[k] = c[k]
    if not out.get("summary") or not out.get("detail"):
        return None
    out["related"] = [r for r in (out.get("related") or []) if r][:3]
    return out


def merge(data_dir: Path, explained: dict, checked: dict, slug: str) -> list[dict]:
    """用語解説とチェックの結果を辞書に反映し、記事に付ける用語の一覧を返す。

    explained: 用語解説の担当の出力 {"terms": [...]}
    checked:   チェックの担当の出力 {"terms": [{"key", "verdict", 直した欄...}]}
    """
    terms = load(data_dir)
    verdicts = {c["key"]: c for c in (checked or {}).get("terms", [])}
    attached = []
    for t in (explained or {}).get("terms", [])[:8]:
        key, term = t.get("key"), t.get("term")
        if not key or not term:
            continue
        if t.get("reuse"):
            if key not in terms:
                continue  # 辞書にない語を reuse と言ってきたら付けない
        else:
            fields = _apply_check(t, verdicts.get(key, {"verdict": "drop"}))  # チェックを通っていない解説は使わない
            if not fields:
                continue
            if terms.get(key, {}).get("status") != "approved":
                old = terms.get(key, {})
                terms[key] = {
                    "headword": t.get("headword") or term,
                    **fields,
                    "status": "auto",
                    "added": old.get("added") or now_jst().date().isoformat(),
                    "aliases": sorted(set(old.get("aliases", []) + [term])),
                    "used_in": old.get("used_in", []),
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


def upgrade_todo(data_dir: Path, limit: int) -> list[dict]:
    """詳しい解説（detail）がまだない辞書の用語。古い形式の解説を詳細版に書き直す対象。"""
    terms = load(data_dir)
    todo = [{"key": k, "headword": v.get("headword", k), "current": v.get("explanation", ""),
             "aliases": v.get("aliases", [])}
            for k, v in terms.items() if not v.get("detail") and v.get("status") != "approved"]
    return todo[:limit]


def apply_upgrade(data_dir: Path, explained: dict, checked: dict) -> dict:
    """用語辞書の詳細版への書き直しを反映する。チェックを通ったものだけ。"""
    terms = load(data_dir)
    verdicts = {c["key"]: c for c in (checked or {}).get("terms", [])}
    done, dropped = [], []
    for t in (explained or {}).get("terms", []):
        key = t.get("key")
        if key not in terms or terms[key].get("status") == "approved":
            continue
        fields = _apply_check(t, verdicts.get(key, {"verdict": "drop"}))
        if not fields:
            dropped.append(key)
            continue
        terms[key].update(fields)
        if t.get("headword"):
            terms[key]["headword"] = t["headword"]
        terms[key].pop("explanation", None)
        done.append(key)
    save(data_dir, terms)
    return {"upgraded": done, "kept_old": dropped}


def display(entry: dict) -> dict:
    """表示用。古い形式（explanation だけ）の用語も表示できるようにする。"""
    return {
        "headword": entry.get("headword"),
        "original": entry.get("original"),
        "summary": entry.get("summary") or entry.get("explanation", ""),
        "detail": entry.get("detail") or (entry.get("explanation", "") if entry.get("summary") else ""),
        "related": entry.get("related", []),
    }


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


LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")


def link_first_occurrences(body_md: str, items: list[dict]) -> str:
    """本文中で、各用語が最初に出てくる箇所を用語解説欄へのリンクにする（Markdown のまま）。
    リンクの title（マウスを重ねたときの表示）には「一言で」の解説を入れる。"""
    out = body_md
    numbered = list(enumerate(items, 1))
    # 長い語から先に処理する（「LNG」より先に「LNG運搬船」をリンクし、語の一部を誤ってリンクしない）
    for i, it in sorted(numbered, key=lambda x: -len(x[1]["term"])):
        term = it["term"]
        taken = [(m.start(), m.end()) for m in LINK_RE.finditer(out)]  # すでにあるリンクの範囲は触らない
        pos = 0
        while True:
            k = out.find(term, pos)
            if k < 0:
                break
            if not any(s <= k < e for s, e in taken):
                title = (it.get("summary") or "").replace('"', "”").replace("\n", " ").replace(")", "）").replace("(", "（")
                link = f'[{term}](#g-{i} "{title}")' if title else f"[{term}](#g-{i})"
                out = out[:k] + link + out[k + len(term):]
                break
            pos = k + 1
    return out
