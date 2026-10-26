"""AIに頼らない機械的なチェック。検証エージェントの評価と合わせて公開可否を決める。"""
from __future__ import annotations

import re

QUOTE_RE = re.compile(r"[“\"]([^”\"]{1,300})[”\"]")
LATIN_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-\.,;:()/ ]*[A-Za-z0-9)]")
WORD_RE = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?")


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def english_runs(article_text: str, source_text: str, n: int) -> list[str]:
    """原文と同じ英単語がn語以上連続している箇所を返す（引用符の中は引用として別に数える）。"""
    unquoted = QUOTE_RE.sub(" ", article_text)
    src = _words(source_text)
    grams = {tuple(src[i : i + n]) for i in range(len(src) - n + 1)}
    hits = []
    for run in LATIN_RUN_RE.findall(unquoted):
        w = _words(run)
        for i in range(len(w) - n + 1):
            if tuple(w[i : i + n]) in grams:
                hits.append(" ".join(w[i : i + n]))
                break
    return hits


def count_quotes(article_text: str) -> int:
    return sum(1 for q in QUOTE_RE.findall(article_text) if re.search(r"[A-Za-z]{3,}", q))


def ja_ngram_overlap(article_text: str, source_text: str, n: int = 12) -> float:
    """日本語ソースの場合の文字列の重なり（0〜1）。記事のn文字の並びのうち、原文にも現れる割合。"""
    a = re.sub(r"\s+", "", article_text)
    s = re.sub(r"\s+", "", source_text)
    if len(a) < n:
        return 0.0
    src_grams = {s[i : i + n] for i in range(len(s) - n + 1)}
    art_grams = [a[i : i + n] for i in range(len(a) - n + 1)]
    return sum(1 for g in art_grams if g in src_grams) / len(art_grams)


def body_length(body_md: str) -> int:
    plain = re.sub(r"[#>*_`\-\[\]()]", "", body_md)
    return len(re.sub(r"\s+", "", plain))


def evaluate(article: dict, source_text: str, lang: str, review: dict, cfg: dict) -> tuple[str, list[str], dict]:
    """公開可否を判定する。戻り値: (判定 'pass'|'hold', 理由のリスト, スコア)"""
    full = "\n".join([article.get("title", ""), article.get("lead", ""), article.get("body", ""), article.get("impact_japan", "")])
    reasons: list[str] = []
    scores = {
        "translation_likeness": int(review.get("translation_likeness", 100)),
        "structure_similarity": int(review.get("structure_similarity", 100)),
        "body_chars": body_length(article.get("body", "")),
        "quotes": count_quotes(full),
    }

    if scores["translation_likeness"] > cfg["translation_likeness_max"]:
        reasons.append(f"翻訳らしさが基準超え（{scores['translation_likeness']}）")
    if scores["structure_similarity"] > cfg["structure_similarity_max"]:
        reasons.append(f"原文との構成の類似が基準超え（{scores['structure_similarity']}）")
    for e in review.get("factual_errors", []) or []:
        reasons.append(f"事実の誤りの疑い：{e}")
    for c in review.get("unsupported_claims", []) or []:
        reasons.append(f"裏付けのない記述：{c}")

    if lang == "en":
        runs = english_runs(full, source_text, cfg["english_run_max_words"])
        scores["english_runs"] = len(runs)
        for r in runs:
            reasons.append(f"原文と同じ英文が連続：「{r}」")
    else:
        ov = ja_ngram_overlap(full, source_text)
        scores["ja_overlap"] = round(ov, 3)
        if ov > cfg["ja_ngram_overlap_max"]:
            reasons.append(f"日本語原文との文字列の重なりが基準超え（{ov:.0%}）")

    if scores["quotes"] > cfg["max_quotes"]:
        reasons.append(f"引用が多すぎます（{scores['quotes']}件）")
    if not cfg["min_chars"] <= scores["body_chars"] <= cfg["max_chars"]:
        reasons.append(f"本文の長さが範囲外（{scores['body_chars']}字）")

    return ("pass" if not reasons else "hold"), reasons, scores
