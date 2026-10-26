"""収集：許可リストのソースから新着を集め、本文を取得する（AIは使わない）。

- robots.txt で取得が禁止されているURLは読まない
- 同じサイトへのアクセスは間隔をあける
- ティア3（業界メディア）は見出しとURLだけ。本文は取得しない
"""
from __future__ import annotations

import hashlib
import logging
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = "MaritimeBriefJP-Bot/0.1 (+news aggregation of public notices; contact via site)"


@dataclass
class Item:
    id: str
    source_id: str
    title: str
    url: str
    summary: str = ""
    published: str = ""
    tier: int = 1
    lang: str = "en"
    categories: list[str] = field(default_factory=list)
    text: str = ""  # 本文（事実抽出と検証にだけ使い、公開はしない）

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d.pop("text")
        return d


def item_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


class Fetcher:
    def __init__(self, interval_sec: float = 2.0):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.interval = interval_sec
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _wait(self, host: str) -> None:
        last = self._last.get(host, 0)
        delta = time.time() - last
        if delta < self.interval:
            time.sleep(self.interval - delta)
        self._last[host] = time.time()

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait(parts.netloc)
                r = self.session.get(base + "/robots.txt", timeout=15)
                if r.status_code >= 400:
                    rp = None  # robots.txt が無い → 制限なしとして扱う
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException as e:
                log.warning("robots.txt を読めませんでした（%s）。安全のため取得を見送ります: %s", base, e)
                self._robots[base] = False  # type: ignore[assignment]
                return False
            self._robots[base] = rp
        rp = self._robots[base]
        if rp is False:
            return False
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> requests.Response | None:
        if not self.allowed(url):
            log.info("robots.txt により取得しません: %s", url)
            return None
        self._wait(urlparse(url).netloc)
        try:
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            log.warning("取得に失敗しました: %s (%s)", url, e)
            return None


def fetch_feed(fetcher: Fetcher, source: dict, limit: int) -> list[Item]:
    import feedparser

    r = fetcher.get(source["feed"])
    if r is None:
        return []
    parsed = feedparser.parse(r.content)
    items = []
    for e in parsed.entries[:limit]:
        url = e.get("link", "")
        if not url:
            continue
        published = ""
        for key in ("published_parsed", "updated_parsed"):
            if e.get(key):
                published = datetime(*e[key][:6], tzinfo=timezone.utc).isoformat()
                break
        items.append(
            Item(
                id=item_id(url),
                source_id=source["id"],
                title=e.get("title", "").strip(),
                url=url,
                summary=_strip_html(e.get("summary", ""))[:600],
                published=published,
                tier=int(source.get("tier", 3)),
                lang=source.get("lang", "en"),
                categories=list(source.get("categories", [])),
            )
        )
    return items


def fetch_text(fetcher: Fetcher, url: str, max_chars: int) -> str:
    r = fetcher.get(url)
    if r is None:
        return ""
    html = r.text
    text = ""
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
    except ImportError:
        pass
    if not text:
        text = _strip_html(html, prefer_main=True)
    return text[:max_chars]


def _strip_html(html: str, prefer_main: bool = False) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    node = (soup.find("article") or soup.find("main") or soup) if prefer_main else soup
    lines = [ln.strip() for ln in node.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)
