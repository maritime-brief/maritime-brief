"""公開済みの記事から静的サイト（HTML・RSS・サイトマップ）を作る。"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from datetime import datetime
from email.utils import format_datetime

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import PROJECT_ROOT, Paths
from . import glossary, ranking
from .store import load_articles, now_jst


def _md(text: str) -> str:
    # AIの出力にHTMLが混ざっても実行されないよう、先にエスケープしてから変換する
    return markdown.markdown(html.escape(text or "", quote=False), extensions=["sane_lists"])


def _date(value, fmt: str = "%Y.%m.%d") -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime(fmt)
    except ValueError:
        return str(value)[:10]


def term_id(key: str) -> str:
    """用語集ページでの用語のアンカー（記号や日本語を含む key でも安全な形に）。"""
    return "t-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def _plain(md_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[#>*_`\[\]()]", "", md_text or "")).strip()


def build_site(settings: dict, paths: Paths) -> int:
    site_cfg, cats = settings["site"], settings["categories"]
    articles = [a for a in load_articles(paths.published) if a.get("status") == "published"]

    env = Environment(loader=FileSystemLoader(PROJECT_ROOT / "templates"), autoescape=select_autoescape(["html", "xml"]))
    env.filters["md"] = _md
    env.filters["date"] = _date
    common = {
        "site": site_cfg,
        "categories": cats,
        "affiliate": settings.get("affiliate", {}),
        "built_at": now_jst(),
        "pending_mode": settings["publish"]["mode"],
        "analytics": settings.get("analytics", {}) or {},
    }

    out = paths.site
    if out.exists():
        shutil.rmtree(out)
    (out / "articles").mkdir(parents=True)
    (out / "category").mkdir()
    shutil.copytree(PROJECT_ROOT / "static", out / "static")

    def render(tpl: str, dest, root: str, **ctx) -> None:
        dest.write_text(env.get_template(tpl).render(root=root, **common, **ctx), encoding="utf-8")

    terms = glossary.load(paths.data)
    published_slugs = {a["slug"]: a for a in articles}

    def related_links(entry: dict) -> list[dict]:
        out_ = []
        for r in entry.get("related", []) or []:
            out_.append({"label": terms[r].get("headword", r) if r in terms else r,
                         "id": term_id(r) if r in terms else None})
        return out_

    for a in articles:
        # 解説の本文は辞書から引く（辞書を直せば全記事に反映される）
        a["glossary_items"] = []
        for i, g in enumerate(a.get("glossary") or [], 1):
            if g.get("key") in terms:
                d = glossary.display(terms[g["key"]])
                a["glossary_items"].append({"n": i, "term": g["term"], "id": term_id(g["key"]), **d,
                                            "related_links": related_links(terms[g["key"]])})
        a["body_linked"] = glossary.link_first_occurrences(a.get("body", ""), a["glossary_items"])

    # 1日の記事ランキング（GoatCounter の設定がない、またはまだデータがないときは表示しない）
    rk = ranking.load(paths) or {}
    size = int(common["analytics"].get("ranking_size", 5))
    common["ranking"] = [
        {"rank": n, "a": published_slugs[r["slug"]], "count": r["count"]}
        for n, r in enumerate([r for r in rk.get("items", []) if r["slug"] in published_slugs][:size], 1)
    ]
    common["ranking_hours"] = rk.get("window_hours", 24)

    render("index.html", out / "index.html", "", articles=articles[:60], page_title=None)
    for key, cat in cats.items():
        items = [a for a in articles if a.get("category") == key]
        render("list.html", out / "category" / f"{key}.html", "../", articles=items, cat_key=key, cat=cat,
               page_title=cat["label"])
    for i, a in enumerate(articles):
        related = [r for r in articles if r is not a and r.get("category") == a.get("category")][:4]
        aff = settings.get("affiliate", {})
        aff_items = aff.get("items", {}).get(a.get("category"), []) if aff.get("enabled") else []
        render("article.html", out / "articles" / f"{a['slug']}.html", "../", a=a, related=related,
               aff_items=aff_items, page_title=a["title"])
    render("about.html", out / "about.html", "", page_title="編集方針と出典について")
    gl = sorted(
        ({"key": k, "id": term_id(k), **glossary.display(v), "related_links": related_links(v),
          "articles": [published_slugs[s] for s in v.get("used_in", []) if s in published_slugs][:5]}
         for k, v in terms.items()),
        key=lambda x: x["headword"],
    )
    # 索引：0-9、A-Z、あ-わ（50音の行）。かっこ内に略語がある用語は、その頭文字の欄にも案内を出す
    groups: dict[str, dict] = {}
    for g in gl:
        key, sort_key, kind = glossary.index_group(g["headword"], g.get("reading"))
        groups.setdefault(key, {"terms": [], "refs": []})["terms"].append((sort_key, g))
        abbr = glossary.abbreviation(g["headword"])
        if abbr:
            k2, s2, _ = glossary.index_group(abbr, None)
            groups.setdefault(k2, {"terms": [], "refs": []})["refs"].append((s2, {"label": abbr, "to": g}))
    nav_keys = ["0-9"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)] + [r for r, _ in glossary.KANA_ROWS] + ["他"]
    sections = []
    for k in nav_keys:
        if k in groups:
            sections.append({"key": k, "id": "idx-" + ("num" if k == "0-9" else k),
                             "terms": [x for _, x in sorted(groups[k]["terms"], key=lambda y: y[0])],
                             "refs": [x for _, x in sorted(groups[k]["refs"], key=lambda y: y[0].upper())]})
    nav = [{"key": k, "id": "idx-" + ("num" if k == "0-9" else k), "has": k in groups} for k in nav_keys if k != "他" or k in groups]
    render("glossary.html", out / "glossary.html", "", terms=gl, sections=sections, nav=nav, page_title="用語集")
    render("search.html", out / "search.html", "", page_title="検索")

    # 検索用の索引（記事と用語集）。検索はブラウザの中で行う
    index = [{"type": "article", "url": f"articles/{a['slug']}.html", "title": a["title"], "lead": a["lead"],
              "date": _date(a["date"]), "category": cats.get(a.get("category"), {}).get("label", ""),
              "tags": a.get("tags", []), "terms": [g["term"] for g in a["glossary_items"]],
              "text": _plain(a.get("body", "")) + " " + (a.get("impact_japan") or "")}
             for a in articles]
    index += [{"type": "term", "url": f"glossary.html#{g['id']}", "title": g["headword"], "lead": g["summary"],
               "original": g.get("original") or "", "text": g.get("detail") or ""} for g in gl]
    (out / "search-index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    _write_feed(out, site_cfg, articles[:30])
    _write_sitemap(out, site_cfg, articles, cats)
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site_cfg['base_url'].rstrip('/')}/sitemap.xml\n")
    (out / ".nojekyll").write_text("")
    return len(articles)


def _write_feed(out, site_cfg, articles) -> None:
    base = site_cfg["base_url"].rstrip("/")
    items = []
    for a in articles:
        link = f"{base}/articles/{a['slug']}.html"
        pub = format_datetime(datetime.fromisoformat(str(a["date"])))
        items.append(
            f"<item><title>{html.escape(a['title'])}</title><link>{link}</link><guid>{link}</guid>"
            f"<pubDate>{pub}</pubDate><description>{html.escape(a['lead'])}</description></item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>{html.escape(site_cfg['name'])}</title><link>{base}/</link>"
        f"<description>{html.escape(site_cfg['tagline'])}</description><language>ja</language>"
        + "".join(items) + "</channel></rss>\n"
    )
    (out / "feed.xml").write_text(xml, encoding="utf-8")


def _write_sitemap(out, site_cfg, articles, cats) -> None:
    base = site_cfg["base_url"].rstrip("/")
    urls = [f"{base}/", f"{base}/about.html", f"{base}/glossary.html", f"{base}/search.html"] + [f"{base}/category/{k}.html" for k in cats]
    urls += [f"{base}/articles/{a['slug']}.html" for a in articles]
    body = "".join(f"<url><loc>{html.escape(u)}</loc></url>" for u in urls)
    (out / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>\n',
        encoding="utf-8",
    )
