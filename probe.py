import json, re, sys, html, urllib.robotparser
from urllib.parse import urljoin, urlparse
import requests
UA = "MaritimeBriefJP-Bot/0.1 (+news aggregation of public notices; contact via site)"
s = requests.Session(); s.headers["User-Agent"] = UA
out = {}
robots = {}
for line in open("candidates.txt"):
    if not line.strip(): continue
    name, url = line.split()
    rec = {"url": url}
    p = urlparse(url); base = f"{p.scheme}://{p.netloc}"
    if base not in robots:
        try:
            r = s.get(base + "/robots.txt", timeout=20)
            robots[base] = (r.status_code, r.text[:3000])
        except Exception as e:
            robots[base] = (None, str(e)[:200])
    st, txt = robots[base]
    rec["robots_status"] = st
    if st and st < 400:
        rp = urllib.robotparser.RobotFileParser(); rp.parse(txt.splitlines())
        rec["robots_allowed"] = rp.can_fetch(UA, url)
        rec["robots_excerpt"] = txt[:800]
    try:
        r = s.get(url, timeout=30)
        rec["status"] = r.status_code; rec["final"] = r.url; rec["len"] = len(r.text)
        rec["ctype"] = r.headers.get("content-type", "")
        t = r.text
        import os; os.makedirs("raw", exist_ok=True); open(f"raw/{name}.html","w").write(t)
        rec["feeds"] = re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]*>', t)[:5]
        if "xml" in rec["ctype"] or t.lstrip().startswith("<?xml"):
            rec["xml_titles"] = re.findall(r"<title[^>]*>(.*?)</title>", t, re.S)[:15]
        links = []
        for href, inner in re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', t, re.S):
            u = urljoin(r.url, html.unescape(href))
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
            if urlparse(u).netloc == urlparse(r.url).netloc and len(text) >= 15:
                links.append([u, text[:120]])
        rec["links"] = links[:400]
        rec["head"] = t[:1500] if "xml" in rec["ctype"] or t.lstrip().startswith("<?xml") else ""
        if r.status_code >= 400: rec["body_head"] = t[:300]
    except Exception as e:
        rec["error"] = str(e)[:300]
    out[name] = rec
    print(name, rec.get("status"), rec.get("robots_allowed"), len(rec.get("links", [])), file=sys.stderr)
json.dump(out, open("result.json", "w"), ensure_ascii=False, indent=1)
