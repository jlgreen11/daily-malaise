#!/usr/bin/env python3
"""THE GRUDGE REPORT — an auto-populated Drudge Report competitor.

Fetches headlines from major news RSS feeds (stdlib only, no dependencies),
scores and dedupes them, picks a lead story, and renders a classic
three-column, all-caps, Courier-font front page to index.html.

Run:  python3 build.py
"""

import concurrent.futures
import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FEEDS = [
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC US", "https://feeds.bbci.co.uk/news/rss.xml"),
    ("NPR", "https://feeds.npr.org/1001/rss.xml"),
    ("GUARDIAN", "https://www.theguardian.com/world/rss"),
    ("CNN", "http://rss.cnn.com/rss/cnn_topstories.rss"),
    ("FOX", "https://moxie.foxnews.com/google-publisher/latest.xml"),
    ("NYT", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    ("AL JAZEERA", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("THE HILL", "https://thehill.com/news/feed/"),
    ("POLITICO", "https://rss.politico.com/politics-news.xml"),
    ("ABC", "https://abcnews.go.com/abcnews/topstories"),
    ("CBS", "https://www.cbsnews.com/latest/rss/main"),
    ("WSJ", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
]

# Words that make a headline siren-worthy. Weight = drama.
HOT_WORDS = {
    "breaking": 10, "dead": 8, "dies": 8, "killed": 8, "death": 7,
    "war": 7, "attack": 7, "strike": 6, "strikes": 6, "crisis": 6,
    "emergency": 6, "explosion": 7, "crash": 6, "shooting": 7,
    "resigns": 7, "fired": 6, "impeach": 8, "indicted": 8, "arrested": 6,
    "collapse": 6, "record": 4, "shock": 6, "chaos": 6, "fury": 5,
    "slams": 4, "warns": 4, "threat": 5, "nuclear": 7, "invasion": 8,
    "hurricane": 6, "earthquake": 7, "wildfire": 5, "outbreak": 6,
    "election": 5, "president": 4, "supreme court": 6, "scandal": 6,
    "leaked": 5, "exclusive": 4, "revealed": 3, "surge": 4, "plunge": 5,
    "soars": 4, "historic": 4, "unprecedented": 5, "massive": 4,
    "riot": 6, "protest": 4, "hostage": 7, "missile": 7, "troops": 5,
    "banned": 4, "lawsuit": 4, "verdict": 5, "guilty": 6, "billion": 3,
    "trillion": 4, "ai": 3, "hack": 5, "breach": 5,
}

USER_AGENT = "Mozilla/5.0 (compatible; GrudgeReport/1.0; +https://github.com/jlgreen11/drudge)"
STOPWORDS = frozenset(
    "a an the of in on at to for with as by is are was were be been from "
    "and or but not this that it its his her their he she they after over "
    "under about into out up down new says say said will would could".split()
)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def text_of(el):
    return (el.text or "").strip() if el is not None else ""


def parse_feed(source, raw):
    """Parse RSS 2.0 or Atom into a list of item dicts."""
    # Strip default-namespace so Atom tags are addressable without prefixes.
    raw = re.sub(rb'xmlns="[^"]+"', b"", raw, count=1)
    root = ET.fromstring(raw)
    items = []
    now = datetime.now(timezone.utc)

    for node in root.iter("item"):  # RSS
        title = text_of(node.find("title"))
        link = text_of(node.find("link"))
        pub = text_of(node.find("pubDate"))
        items.append((title, link, pub))
    if not items:
        for node in root.iter("entry"):  # Atom
            title = text_of(node.find("title"))
            link_el = node.find("link")
            link = link_el.get("href", "") if link_el is not None else ""
            pub = text_of(node.find("published")) or text_of(node.find("updated"))
            items.append((title, link, pub))

    out = []
    for title, link, pub in items:
        title = re.sub(r"\s+", " ", html.unescape(title)).strip()
        if not title or not link.startswith("http"):
            continue
        when = None
        if pub:
            try:
                when = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                try:
                    when = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except ValueError:
                    when = None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age_hours = (now - when).total_seconds() / 3600 if when else 24.0
        if age_hours > 48:  # stale news is no news
            continue
        out.append({
            "source": source,
            "title": title,
            "link": link,
            "age_hours": max(age_hours, 0.0),
        })
    return out


def tokens(title):
    words = re.findall(r"[a-z0-9']+", title.lower())
    return frozenset(w for w in words if w not in STOPWORDS and len(w) > 2)


def score(item, cluster_size):
    lower = " " + item["title"].lower() + " "
    s = 0.0
    for word, weight in HOT_WORDS.items():
        if f" {word} " in lower or lower.strip().startswith(word + " "):
            s += weight
    s += max(0.0, 12.0 - item["age_hours"])          # fresher is hotter
    s += (cluster_size - 1) * 8                       # multiple outlets = big story
    if item["title"].isupper():
        s += 3                                        # already shouting
    return s


def dedupe_and_rank(items):
    """Cluster near-duplicate headlines across sources; rank clusters."""
    clusters = []  # list of lists
    for item in items:
        toks = tokens(item["title"])
        if not toks:
            continue
        item["toks"] = toks
        placed = False
        for cluster in clusters:
            ref = cluster[0]["toks"]
            union = len(toks | ref)
            if union and len(toks & ref) / union >= 0.5:
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])

    ranked = []
    for cluster in clusters:
        best = min(cluster, key=lambda i: i["age_hours"])
        best["score"] = score(best, len(cluster))
        best["cluster"] = len(cluster)
        ranked.append(best)
    ranked.sort(key=lambda i: i["score"], reverse=True)
    return ranked


def headline_case(title):
    return html.escape(title.upper())


def render(ranked, sources_ok, now):
    lead = ranked[0] if ranked else None
    rest = ranked[1:]

    # Round-robin the remaining stories into three columns.
    cols = [[], [], []]
    for i, item in enumerate(rest[:60]):
        cols[i % 3].append(item)

    def link_html(item, cls=""):
        klass = f' class="{cls}"' if cls else ""
        src = html.escape(item["source"])
        return (
            f'<div class="story"><a{klass} href="{html.escape(item["link"])}" '
            f'target="_blank" rel="noopener">{headline_case(item["title"])}</a>'
            f'<span class="src">{src}</span></div>'
        )

    col_html = []
    for col in cols:
        rows = []
        for i, item in enumerate(col):
            cls = "hot" if item["score"] >= 25 else ""
            rows.append(link_html(item, cls))
            if (i + 1) % 6 == 0 and i + 1 < len(col):
                rows.append('<hr class="rule">')
        col_html.append("\n".join(rows))

    lead_html = ""
    if lead:
        siren = '<div class="siren">🚨</div>' if lead["score"] >= 30 else ""
        lead_html = (
            f'{siren}<a class="lead" href="{html.escape(lead["link"])}" '
            f'target="_blank" rel="noopener">{headline_case(lead["title"])}</a>'
            f'<div class="lead-src">{html.escape(lead["source"])}'
            + (f' &middot; REPORTED BY {lead["cluster"]} OUTLETS' if lead["cluster"] > 1 else "")
            + "</div>"
        )

    stamp = now.strftime("%A %B %d, %Y").upper() + now.strftime(" &middot; %H:%M UTC")
    src_line = " &middot; ".join(html.escape(s) for s in sources_ok)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>THE GRUDGE REPORT</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #fff; color: #000;
    font-family: "Courier New", Courier, monospace;
    padding: 12px; max-width: 1100px; margin: 0 auto;
  }}
  a {{ color: #000; }}
  a:visited {{ color: #444; }}
  a:hover {{ background: #000; color: #fff; text-decoration: none; }}
  .topbar {{ text-align: center; font-size: 11px; letter-spacing: 1px;
             border-bottom: 3px double #000; padding-bottom: 6px; }}
  .masthead {{ text-align: center; font-size: 44px; font-weight: bold;
               letter-spacing: 4px; margin: 14px 0 2px; }}
  .tagline {{ text-align: center; font-size: 11px; letter-spacing: 3px;
              margin-bottom: 16px; }}
  .leadbox {{ text-align: center; margin: 22px auto 26px; max-width: 760px; }}
  .siren {{ font-size: 34px; animation: flash 1s step-start infinite; }}
  @keyframes flash {{ 50% {{ opacity: 0.25; }} }}
  a.lead {{ font-size: 32px; font-weight: bold; line-height: 1.2;
            color: #c00; text-decoration: underline; }}
  a.lead:hover {{ background: #c00; color: #fff; }}
  .lead-src {{ font-size: 11px; margin-top: 6px; letter-spacing: 1px; }}
  .columns {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 26px;
              border-top: 1px solid #000; padding-top: 18px; }}
  .story {{ margin-bottom: 13px; font-size: 14px; font-weight: bold;
            line-height: 1.35; }}
  .story a.hot {{ color: #c00; }}
  .story a.hot:hover {{ background: #c00; color: #fff; }}
  .src {{ display: block; font-size: 10px; font-weight: normal; color: #555;
          letter-spacing: 1px; margin-top: 1px; }}
  hr.rule {{ border: none; border-top: 1px solid #000; margin: 16px 30%; }}
  .footer {{ border-top: 3px double #000; margin-top: 26px; padding-top: 8px;
             text-align: center; font-size: 10px; color: #333;
             letter-spacing: 1px; line-height: 1.8; }}
  @media (max-width: 720px) {{
    .columns {{ grid-template-columns: 1fr; }}
    .masthead {{ font-size: 30px; letter-spacing: 2px; }}
    a.lead {{ font-size: 24px; }}
  }}
</style>
</head>
<body>
  <div class="topbar">{stamp} &middot; UPDATES EVERY 30 MINUTES &middot; ALL LINKS GO TO ORIGINAL SOURCES</div>
  <div class="masthead">THE GRUDGE REPORT</div>
  <div class="tagline">HOLDING A GRUDGE AGAINST SLOW NEWS SINCE {now.year}</div>
  <div class="leadbox">{lead_html}</div>
  <div class="columns">
    <div class="col">{col_html[0]}</div>
    <div class="col">{col_html[1]}</div>
    <div class="col">{col_html[2]}</div>
  </div>
  <div class="footer">
    WIRES: {src_line}<br>
    AUTO-GENERATED BY <a href="https://github.com/jlgreen11/drudge">build.py</a> &middot;
    HEADLINES BELONG TO THEIR PUBLISHERS &middot; NOT AFFILIATED WITH ANY OTHER REPORT
  </div>
</body>
</html>
"""


def main():
    all_items = []
    sources_ok = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch, url): (source, url) for source, url in FEEDS}
        for fut in concurrent.futures.as_completed(futures):
            source, url = futures[fut]
            try:
                items = parse_feed(source, fut.result())
            except Exception as e:
                print(f"  [skip] {source}: {e}", file=sys.stderr)
                continue
            if items:
                sources_ok.append(source)
                all_items.extend(items)
                print(f"  [ok]   {source}: {len(items)} items", file=sys.stderr)

    if len(all_items) < 10:
        print("Not enough news fetched; keeping existing page.", file=sys.stderr)
        sys.exit(1)

    ranked = dedupe_and_rank(all_items)
    sources_ok.sort()
    page = render(ranked, sources_ok, datetime.now(timezone.utc))
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote index.html: 1 lead + {min(len(ranked) - 1, 60)} stories "
          f"from {len(sources_ok)} sources.", file=sys.stderr)


if __name__ == "__main__":
    main()
