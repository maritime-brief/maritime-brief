"""デモ実行用の架空データ。

APIキーもネット接続も使わずに、パイプライン全体（選別→抽出→執筆→検証→公開/保留）の流れを
確かめるためのもの。登場する船名・機関・規則はすべて架空です。
"""
from __future__ import annotations

import json

from pipeline.collect import Item, item_id

DEMO_SOURCE = {
    "id": "demo",
    "name": "架空の海難調査機関（デモ）",
    "tier": 1,
    "license": "デモ用の架空データ",
    "attribution": "これはデモ用の架空の記事です。",
}

_ITEMS = [
    {
        "key": "fire",
        "title": "SAMPLE: Report published on engine room fire aboard general cargo ship Example Star",
        "url": "https://example.org/demo/example-star-fire",
        "summary": "Investigation into a fuel oil fire in the engine room of a 5,200 gt general cargo ship.",
        "tier": 1,
        "text": (
            "The Demo Marine Accident Board has published its investigation report into an engine room fire "
            "on board the general cargo vessel Example Star on 14 March 2026. The 5,200 gt vessel was on passage "
            "in the fictional North Channel with 12 crew on board when fuel oil sprayed from a cracked low-pressure "
            "fuel pipe onto the exhaust manifold of the main engine. The fire was extinguished within 40 minutes by "
            "the fixed CO2 system. Nobody was injured. The investigation found that the insulation on the exhaust "
            "manifold had been removed during maintenance two weeks earlier and had not been refitted. Spray shields "
            "on fuel pipe flanges were also missing. The board recommends that the ship manager introduce a "
            "post-maintenance checklist covering insulation of hot surfaces, and that the flag administration issue "
            "a safety notice to owners of similar vessels. The report notes that hot surface protection is required "
            "under SOLAS regulation II-2/4. "
        ) * 2,
    },
    {
        "key": "ballast",
        "title": "SAMPLE: Committee adopts amendments to ballast water record book format",
        "url": "https://example.org/demo/ballast-amendments",
        "summary": "Amendments to the electronic ballast water record book take effect on 1 July 2027.",
        "tier": 1,
        "text": (
            "The Demo Maritime Committee has adopted amendments to the format of the ballast water record book. "
            "Ships will be allowed to keep the record book in electronic form provided the system is approved by "
            "the flag administration. The amendments are expected to enter into force on 1 July 2027. "
            "The committee also agreed to review guidance on sampling. "
        ) * 4,
    },
    {
        "key": "award",
        "title": "SAMPLE: Staff recognised at annual awards ceremony",
        "url": "https://example.org/demo/awards",
        "summary": "Three members of staff received long service awards.",
        "tier": 1,
        "text": "Three members of staff received long service awards at the annual ceremony. " * 10,
    },
    {
        "key": "lead",
        "title": "SAMPLE: Shipyard wins order for ammonia-fuelled bulk carriers (industry media)",
        "url": "https://example.org/demo/media-ammonia-order",
        "summary": "Industry media headline used only as a topic lead.",
        "tier": 3,
        "text": "",
    },
]


def _id(key: str) -> str:
    return item_id(next(i["url"] for i in _ITEMS if i["key"] == key))


def demo_items() -> list[Item]:
    return [
        Item(id=item_id(i["url"]), source_id="demo", title=i["title"], url=i["url"], summary=i["summary"],
             published="2026-10-27T00:00:00+00:00", tier=i["tier"], lang="en", categories=["safety"])
        for i in _ITEMS
    ]


def demo_text(iid: str) -> str:
    return next(i["text"] for i in _ITEMS if item_id(i["url"]) == iid)


# ---------------------------------------------------------------- 架空のAI応答
_FACTS = {
    "fire": {
        "summary_ja": "一般貨物船の機関室火災で、高温部の断熱材の未復旧が原因と判明",
        "category": "safety",
        "facts": [
            {"statement": "排気マニホールドの断熱材が整備後に戻されていなかった", "kind": "other"},
            {"statement": "断熱材は火災の約2週間前の整備で外されていた", "kind": "date"},
            {"statement": "低圧燃料管の亀裂から燃料油が噴出し、排気マニホールドに触れて出火", "kind": "other"},
            {"statement": "燃料管フランジの飛散防止カバーも外れていた", "kind": "other"},
            {"statement": "調査機関は整備後のチェックリスト導入を管理会社に勧告", "kind": "organization"},
            {"statement": "旗国当局には同型船の船主向け安全通知の発出を勧告", "kind": "organization"},
            {"statement": "固定式CO2消火装置で約40分後に鎮火、負傷者なし", "kind": "number"},
            {"statement": "船は総トン数5,200トン、乗組員12人", "kind": "vessel"},
            {"statement": "火災の発生は2026年3月14日", "kind": "date"},
            {"statement": "高温部の保護はSOLAS第II-2章第4規則で求められている", "kind": "regulation"},
        ],
        "key_dates": [{"label": "火災発生", "date": "2026.03.14"}],
        "vessel_types": ["一般貨物船"],
        "regulations": ["SOLAS II-2/4"],
        "organizations": ["架空の海難調査機関"],
        "quote": None,
        "confidence": 0.9,
    },
    "ballast": {
        "summary_ja": "バラスト水記録簿の電子化を認める改正が採択",
        "category": "regulation",
        "facts": [
            {"statement": "旗国が承認したシステムであれば、バラスト水記録簿を電子形式で記録できる", "kind": "regulation"},
            {"statement": "改正の発効予定は2027年7月1日", "kind": "date"},
            {"statement": "サンプリングの指針の見直しにも合意", "kind": "other"},
        ],
        "key_dates": [{"label": "発効予定", "date": "2027.07.01"}],
        "vessel_types": [],
        "regulations": ["バラスト水管理（架空の委員会）"],
        "organizations": ["架空の海事委員会"],
        "quote": None,
        "confidence": 0.85,
    },
}

_ARTICLES = {
    "fire": {
        "title": "外した断熱材が戻らず機関室火災に　貨物船の事故報告",
        "lead": "整備で外した排気マニホールドの断熱材が戻されないまま運航し、燃料管の亀裂から噴き出した燃料油が触れて出火した。調査機関は整備後の確認手順の導入を勧告した。",
        "body": (
            "事故の直接の原因は、整備作業で外された排気マニホールドの断熱材が、作業後に元に戻されていなかったことだった。"
            "断熱材は火災のおよそ2週間前の整備で外され、そのまま運航が続いていた。"
            "低圧燃料管に生じた亀裂から燃料油が噴き出し、むき出しになった高温部に触れて火災になった。燃料管フランジの飛散防止カバーも外れていた。\n\n"
            "火災は2026年3月14日、総トン数5,200トンの一般貨物船で起きた。乗組員は12人で、固定式のCO2消火装置を使っておよそ40分後に鎮火し、けが人はいなかった。\n\n"
            "調査機関は管理会社に対し、整備のあとに高温部の断熱を確かめるチェックリストを導入するよう勧告した。"
            "旗国の当局には、同じ型の船を持つ船主へ安全通知を出すよう求めている。高温部の保護は、SOLAS条約第II-2章第4規則が定める要件でもある。"
        ),
        "impact_japan": "整備後に断熱材や飛散防止カバーを戻したかどうかの確認は、国内の船でも日常的に起こりうる見落としです。機関部の作業手順書に、高温部の復旧確認が含まれているかを点検するきっかけになりそうです。",
        "tags": ["機関室火災", "事故調査", "SOLAS", "整備"],
    },
    "ballast": {
        "title": "バラスト水記録簿、電子での記録が可能に　2027年7月発効予定",
        "lead": "旗国が承認したシステムを使えば、バラスト水記録簿を電子形式で付けられるようにする改正が採択された。発効は2027年7月1日の予定。",
        "body": (
            "バラスト水記録簿を電子形式で記録することを認める改正が採択された。条件は、使うシステムを旗国の当局が承認していることだ。"
            "発効は2027年7月1日の予定となっている。\n\n"
            "あわせて、バラスト水のサンプリングに関する指針を見直すことでも合意した。見直しの時期や内容は今後の議論で決まる。\n\n"
            "紙の記録簿は記入や保管の手間がかかり、検査の際の確認にも時間がかかっていた。電子化が進めば、記録の管理や検査対応の負担が軽くなる可能性がある。"
            "一方で、システムの承認手続きや、旗国ごとの対応の違いには注意が必要になる。"
        ),
        "impact_japan": "日本籍船で電子記録を使うには、国内での承認の手続きがどう整えられるかが鍵になります。国内の制度への取り込みの時期や方法に注目したいところです。",
        "tags": ["バラスト水", "電子記録簿", "条約改正"],
    },
}

_REVIEWS = {
    # 合格する例
    "fire": {"translation_likeness": 15, "structure_similarity": 20, "factual_errors": [], "unsupported_claims": [],
             "comment": "事実は原文と一致。構成も独自。"},
    # 保留になる例（検証で構成の類似を指摘）
    "ballast": {"translation_likeness": 35, "structure_similarity": 55, "factual_errors": [],
                "unsupported_claims": ["紙の記録簿の負担についての記述は原文にない"],
                "comment": "第1段落が原文の順序に近い。第3段落は要確認。"},
}

_TRIAGE = {
    "fire": {"relevance": 5, "category": "safety", "duplicate_of": None, "reason": "機関室火災の事故調査報告"},
    "ballast": {"relevance": 4, "category": "regulation", "duplicate_of": None, "reason": "条約改正と発効日"},
    "award": {"relevance": 1, "category": "other", "duplicate_of": None, "reason": "人事・表彰"},
}


def mock_handlers():
    def key_from(text: str) -> str:
        for k in ("fire", "ballast", "award"):
            if _id(k) in text or next(i["title"] for i in _ITEMS if i["key"] == k) in text:
                return k
        for k, f in _FACTS.items():
            if f["summary_ja"] in text:
                return k
        for k, a in _ARTICLES.items():
            if a["title"] in text:
                return k
        raise KeyError("デモデータに該当がありません")

    def triage(user: str) -> dict:
        payload = json.loads(user)
        rows = []
        for it in payload["new_items"]:
            k = key_from(it["id"] + it["title"])
            rows.append({"id": it["id"], **_TRIAGE[k]})
        return {"items": rows}

    return {
        "triage": triage,
        "extract": lambda u: json.loads(json.dumps(_FACTS[key_from(u)], ensure_ascii=False)),
        "write": lambda u: dict(_ARTICLES[key_from(u)]),
        "verify": lambda u: dict(_REVIEWS[key_from(u)]),
    }
