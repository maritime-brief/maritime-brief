"""公開済みの記事から静的サイト（HTML・RSS・サイトマップ）を作る。"""
from __future__ import annotations

import html
import shutil
from datetime import datetime
from email.utils import format_datetime

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import PROJECT_ROOT, Paths
from . import glossary
from .store import load_articles, now_jst


def _md(text: str) -> str:
    # AIの出力にHTMLが混ざっても実行されないよう、先にエスケープしてから変換する
    return markdown.markdown(html.escape(text or "", quote=False), extensions=["sane_lists"])


def _date(value, fmt: str = "%Y.%m.%d") -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime(fmt)
    except ValueError:
        return str(value)[:10]


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
    for a in articles:
        # 解説の本文は辞書から引く（辞書を直せば全記事に反映される）
        a["glossary_items"] = [
            {"n": i, "term": g["term"], "headword": terms[g["key"]].get("headword", g["term"]),
             "explanation": terms[g["key"]]["explanation"]}
            for i, g in enumerate(a.get("glossary") or [], 1) if g.get("key") in terms
        ]
        a["body_linked"] = glossary.link_first_occurrences(a.get("body", ""), a["glossary_items"])

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
        ({"key": k, "headword": v.get("headword", k), "explanation": v["explanation"],
          "articles": [published_slugs[s] for s in v.get("used_in", []) if s in published_slugs][:5]}
         for k, v in terms.items()),
        key=lambda x: x["headword"],
    )
    render("glossary.html", out / "glossary.html", "", terms=gl, page_title="用語集")

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
    urls = [f"{base}/", f"{base}/about.html", f"{base}/glossary.html"] + [f"{base}/category/{k}.html" for k in cats]
    urls += [f"{base}/articles/{a['slug']}.html" for a in articles]
    body = "".join(f"<url><loc>{html.escape(u)}</loc></url>" for u in urls)
    (out / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>\n',
        encoding="utf-8",
    )
