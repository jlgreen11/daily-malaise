#!/usr/bin/env python3
"""THE GRUDGE REPORT — an auto-populated Drudge Report competitor.

Fetches headlines from 25 news RSS feeds (stdlib only, no dependencies),
scores each for drama AND judges its tone (grim vs. rosy), dedupes across
outlets, picks a lead story, and renders a classic three-column, all-caps,
Courier-font front page to index.html — topped by THE JUDGMENT, a slider
that lets readers dial the mix of negative and positive news, and THE
DOSAGE, a slider that dials how much Trump coverage the page carries.

The editor never sleeps: state.json is the paper's memory between runs.
Stories that are being picked up by more outlets get boosted and badged
RISING; stories that have sat on the page too long decay and get pulled;
a lead that stops growing loses the siren after a few hours.

Run:  python3 build.py
"""

import concurrent.futures
import html
import json
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
    ("SKY", "https://feeds.skynews.com/feeds/rss/world.xml"),
    ("DW", "https://rss.dw.com/rdf/rss-en-all"),
    ("FRANCE 24", "https://www.france24.com/en/rss"),
    ("INDEPENDENT", "https://www.independent.co.uk/news/world/rss"),
    ("TIME", "https://time.com/feed/"),
    ("AXIOS", "https://api.axios.com/feed/"),
    ("ECONOMIST", "https://www.economist.com/latest/rss.xml"),
    ("MARKETWATCH", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("GOOD NEWS NETWORK", "https://www.goodnewsnetwork.org/feed/"),
    ("POSITIVE.NEWS", "https://www.positive.news/feed/"),
    ("REASONS TO BE CHEERFUL", "https://reasonstobecheerful.world/feed/"),
]

# Dedicated good-news outlets: they publish slowly (so they get a 7-day
# freshness window instead of 48h) and their stories are positive by
# construction (so they get a +1 tone prior on top of the lexicon).
GOOD_SOURCES = {"GOOD NEWS NETWORK", "POSITIVE.NEWS", "REASONS TO BE CHEERFUL"}

MAX_PER_SOURCE = 40   # stop one chatty feed from flooding the page
POOL_SIZE = 150       # stories embedded for the client-side judgment mixer
PAGE_STORIES = 60     # stories shown below the lead

# ── The night editor's rulebook: when to put on, when to pull off ──────────
STATE_FILE = "state.json"
STATE_PRUNE_H = 72.0        # forget clusters not seen for this long
TENURE_SOFT_H = 12.0        # a story starts bleeding score after this long on page
TENURE_PENALTY = 0.75       # points lost per hour past the soft limit
TENURE_HARD_H = 30.0        # pulled off the page after this long, unless rising
RISING_BONUS = 6.0          # score bonus per outlet gained since the story's peak
FRESH_BADGE_H = 3.0         # unseen stories younger than this get the NEW badge
LEAD_FATIGUE_H = 4.0        # max hours a non-growing lead keeps the siren
LEAD_MIN_OUTLETS = 2        # a lead must be confirmed by 2+ outlets...
LEAD_SOLO_SCORE = 40.0      # ...or be scorching hot on its own
LEAD_RIVAL_RATIO = 0.75     # a challenger this close (or better) can take a tired crown

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
    "breakthrough": 6, "cure": 6, "rescue": 6, "miracle": 6, "triumph": 5,
}

# THE JUDGMENT: tone lexicons. tone = sum(pos) - sum(neg); >0 rosy, <0 grim.
GRIM_WORDS = {
    "dead": 3, "dies": 3, "death": 3, "killed": 3, "kills": 3, "murder": 3,
    "war": 3, "massacre": 3, "genocide": 3, "terror": 3, "bomb": 3,
    "suicide": 3, "rape": 3,
    "attack": 2, "crisis": 2, "crash": 2, "shooting": 2, "shot": 2,
    "explosion": 2, "missile": 2, "nuclear": 2, "invasion": 2, "hostage": 2,
    "riot": 2, "violence": 2, "violent": 2, "deadly": 2, "fatal": 2,
    "tragedy": 2, "tragic": 2, "disaster": 2, "famine": 2, "outbreak": 2,
    "pandemic": 2, "collapse": 2, "wildfire": 2, "hurricane": 2,
    "earthquake": 2, "flood": 2, "evacuation": 2, "destroyed": 2,
    "guilty": 2, "fraud": 2, "corruption": 2, "arrested": 2, "indicted": 2,
    "prison": 2, "abuse": 2, "assault": 2, "victims": 2, "victim": 2,
    "wounded": 2, "injured": 2, "toll": 2, "grim": 2, "dire": 2,
    "worst": 2, "fears": 2, "threat": 2, "sanctions": 2, "layoffs": 2,
    "recession": 2, "torture": 2, "kidnap": 2, "kidnapped": 2,
    "warns": 1, "warning": 1, "fear": 1, "cuts": 1, "debt": 1,
    "inflation": 1, "lawsuit": 1, "sued": 1, "banned": 1, "ban": 1,
    "protest": 1, "clash": 1, "scandal": 1, "slams": 1, "backlash": 1,
    "fury": 1, "outrage": 1, "anger": 1, "angry": 1, "feud": 1, "row": 1,
    "crackdown": 1, "resigns": 1, "fired": 1, "ousted": 1, "impeach": 1,
    "coup": 1, "plunge": 1, "plummets": 1, "slump": 1, "tumble": 1,
    "losses": 1, "loses": 1, "missing": 1, "homeless": 1, "cancer": 1,
    "disease": 1, "virus": 1, "drought": 1, "smuggling": 1, "overdose": 1,
    "custody": 1, "chaos": 1, "struggling": 1, "shortage": 1, "blackout": 1,
    "fighting": 2, "displaced": 2, "fraudsters": 2, "scam": 2,
    "hospitalized": 1, "lose": 1, "divided": 1, "concerns": 1,
    "ruined": 2, "ruins": 2, "wrecked": 2, "slammed": 1, "mocks": 1,
    "criticism": 1, "tensions": 1,
}
ROSY_WORDS = {
    "breakthrough": 3, "cure": 3, "cured": 3, "rescue": 3, "rescued": 3,
    "saves": 3, "saved": 3, "hero": 3, "heroes": 3, "reunited": 3,
    "triumph": 3, "miracle": 3,
    "wins": 2, "win": 2, "won": 2, "victory": 2, "celebrates": 2,
    "celebration": 2, "joy": 2, "hope": 2, "hopeful": 2, "recovery": 2,
    "recovers": 2, "survives": 2, "survivor": 2, "success": 2,
    "successful": 2, "award": 2, "awarded": 2, "prize": 2, "honored": 2,
    "milestone": 2, "discovery": 2, "donates": 2, "donation": 2,
    "kindness": 2, "inspiring": 2, "uplifting": 2, "beloved": 2,
    "peace": 2, "ceasefire": 2, "treaty": 2, "thriving": 2, "revival": 2,
    "restored": 2, "champions": 2, "champion": 2, "medal": 2,
    "happy": 1, "happiness": 1, "love": 1, "adorable": 1, "cute": 1,
    "smile": 1, "laughter": 1, "generous": 1, "volunteer": 1,
    "volunteers": 1, "charity": 1, "festival": 1, "wedding": 1,
    "birth": 1, "born": 1, "baby": 1, "graduates": 1, "scholarship": 1,
    "boost": 1, "boosts": 1, "gains": 1, "rally": 1, "soars": 1,
    "deal": 1, "agreement": 1, "growth": 1, "expands": 1, "hiring": 1,
    "anniversary": 1, "celebrate": 1, "welcomes": 1, "blooming": 1,
    "renewable": 1, "protects": 1, "protected": 1, "cleaner": 1,
}

# ── Topic desks: every story gets filed to exactly one ─────────────────────
# Highest lexicon score wins the headline; below TOPIC_MIN it goes to the
# catch-all desk (sports, celebs, weather, oddities, good news).
TOPIC_CATCHALL = "LIFE & CULTURE"
TOPIC_MIN = 2
TOPICS = [
    ("WASHINGTON", {
        "trump": 3, "maga": 3, "white house": 3, "oval office": 3, "potus": 3,
        "vance": 3, "congress": 3, "senate": 2, "supreme court": 3, "scotus": 3,
        "executive order": 3, "impeach": 3, "impeachment": 3, "gop": 2,
        "republicans": 2, "republican": 2, "democrats": 2, "democrat": 2,
        "pentagon": 2, "doj": 2, "fbi": 2, "cia": 2, "irs": 2,
        "deportation": 2, "deportations": 2, "immigration": 2,
        "election": 1, "elections": 1, "campaign": 1, "governor": 1,
        "senator": 2, "congressman": 1, "congresswoman": 1, "capitol": 2,
        "federal judge": 2, "attorney general": 2, "biden": 2, "obama": 2,
        "medicaid": 1, "medicare": 1, "national guard": 2, "border": 1,
        "washington": 1, "filibuster": 3, "lawmakers": 2, "veto": 2,
    }),
    ("WORLD", {
        "ukraine": 3, "russia": 3, "russian": 2, "putin": 3, "zelensky": 3,
        "kyiv": 3, "moscow": 3, "gaza": 3, "israel": 3, "israeli": 2,
        "netanyahu": 3, "hamas": 3, "hezbollah": 3, "iran": 3, "tehran": 3,
        "china": 3, "chinese": 2, "beijing": 3, "taiwan": 3,
        "north korea": 3, "south korea": 3, "korea": 2, "nato": 3,
        "kremlin": 3, "united nations": 3, "europe": 2, "european": 2,
        "britain": 2, "uk": 2, "brexit": 3, "parliament": 2, "mp": 2,
        "le pen": 3, "macron": 3, "starmer": 3, "farage": 2,
        "london": 2, "france": 2, "paris": 2, "germany": 2,
        "berlin": 2, "india": 2, "pakistan": 2, "japan": 2, "tokyo": 2,
        "australia": 2, "canada": 2, "mexico": 2, "brazil": 2,
        "venezuela": 2, "cuba": 2, "syria": 2, "lebanon": 2, "yemen": 2,
        "iraq": 2, "afghanistan": 2, "taliban": 3, "africa": 2,
        "nigeria": 2, "kenya": 2, "south africa": 2, "ethiopia": 2,
        "sudan": 2, "refugee": 2, "refugees": 2, "migrants": 2,
        "minister": 1, "embassy": 2, "ambassador": 2,
    }),
    ("MONEY", {
        "stocks": 3, "stock": 2, "stock market": 3, "dow": 3, "nasdaq": 3,
        "wall street": 3, "fed": 3, "federal reserve": 3, "interest rates": 3,
        "inflation": 3, "tariff": 3, "tariffs": 3, "economy": 3,
        "economic": 2, "recession": 3, "jobs": 2, "jobless": 2,
        "unemployment": 3, "layoffs": 2, "hiring": 1, "earnings": 2,
        "profits": 2, "bitcoin": 3, "crypto": 3, "ethereum": 3, "oil": 2,
        "opec": 3, "housing": 2, "mortgage": 2, "bank": 2, "banks": 2,
        "banking": 2, "ipo": 2, "merger": 2, "dollar": 2, "treasury": 2,
        "deficit": 2, "billion": 1, "trillion": 1, "ceo": 1, "retail": 1,
        "consumer": 1, "prices": 1, "markets": 2, "investors": 2,
        "trade deal": 2, "debt": 1,
    }),
    ("TECH & SCIENCE", {
        "ai": 3, "artificial intelligence": 3, "openai": 3, "chatgpt": 3,
        "anthropic": 3, "google": 2, "apple": 2, "meta": 2, "microsoft": 2,
        "amazon": 2, "tesla": 2, "musk": 2, "spacex": 3, "nasa": 3,
        "rocket": 2, "satellite": 2, "chip": 2, "chips": 2,
        "semiconductor": 3, "nvidia": 3, "robot": 2, "robots": 2,
        "robotics": 3, "cyberattack": 3, "hackers": 2, "hacked": 2,
        "software": 2, "iphone": 2, "android": 2, "quantum": 3,
        "scientists": 3, "science": 2, "study": 2, "researchers": 3,
        "telescope": 3, "mars": 2, "moon": 2, "space": 2, "asteroid": 3,
        "vaccine": 2, "fda": 2, "medical": 2, "climate": 2, "warming": 2,
        "emissions": 2, "solar": 2, "crispr": 3, "dna": 2, "startup": 2,
    }),
]

# THE DOSAGE: stories filed under the president, whatever the desk.
TRUMP_RE = re.compile(r"\btrump\b|\bmaga\b|\bpotus\b|white house|oval office", re.I)

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


def find_date(node):
    """First date-ish child of an item: pubDate, dc:date, published, updated."""
    for child in node:
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in ("pubdate", "date", "published", "updated"):
            return text_of(child)
    return ""


def parse_feed(source, raw):
    """Parse RSS 2.0, RSS 1.0/RDF, or Atom into a list of item dicts."""
    # Strip default-namespace so RSS 1.0 / Atom tags are addressable plainly.
    raw = re.sub(rb'xmlns="[^"]+"', b"", raw, count=1)
    root = ET.fromstring(raw)
    items = []
    now = datetime.now(timezone.utc)

    for node in root.iter("item"):  # RSS 2.0 and RSS 1.0/RDF
        title = text_of(node.find("title"))
        link = text_of(node.find("link"))
        items.append((title, link, find_date(node)))
    if not items:
        for node in root.iter("entry"):  # Atom
            title = text_of(node.find("title"))
            link_el = node.find("link")
            link = link_el.get("href", "") if link_el is not None else ""
            items.append((title, link, find_date(node)))

    out = []
    for title, link, pub in items[:MAX_PER_SOURCE]:
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
        max_age = 168 if source in GOOD_SOURCES else 48
        if age_hours > max_age:  # stale news is no news
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


def lexicon_score(title, lexicon):
    padded = " " + re.sub(r"[^a-z0-9 ]", " ", title.lower()) + " "
    return sum(w for word, w in lexicon.items() if f" {word} " in padded)


def judge(title):
    """THE JUDGMENT: tone of a headline. >0 rosy, <0 grim, 0 neutral."""
    return lexicon_score(title, ROSY_WORDS) - lexicon_score(title, GRIM_WORDS)


def classify(title):
    """File the story to a desk: highest topic-lexicon score wins."""
    best_topic, best = TOPIC_CATCHALL, 0
    for topic, lexicon in TOPICS:
        s = lexicon_score(title, lexicon)
        if s > best:
            best_topic, best = topic, s
    return best_topic if best >= TOPIC_MIN else TOPIC_CATCHALL


def score(item, cluster_size):
    s = float(lexicon_score(item["title"], HOT_WORDS))
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
        n_sources = len({i["source"] for i in cluster})
        best["score"] = score(best, n_sources)
        best["cluster"] = n_sources
        best["tone"] = judge(best["title"]) + (1 if best["source"] in GOOD_SOURCES else 0)
        best["topic"] = classify(best["title"])
        best["trump"] = bool(TRUMP_RE.search(best["title"]))
        ranked.append(best)
    ranked.sort(key=lambda i: i["score"], reverse=True)
    return ranked


# ── Editorial memory: state.json survives between runs via the CI commit ───

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"clusters": [], "lead": None}


def parse_iso(s, fallback):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return fallback


def jaccard(a, b):
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def match_state(toks, entries):
    """Find the tracked cluster this headline continues, if any. Looser
    threshold than intra-run clustering: headlines drift between runs."""
    best, best_j = None, 0.4
    for e in entries:
        j = jaccard(toks, e["_toks"])
        if j > best_j:
            best, best_j = e, j
    return best


def apply_state(ranked, state, now):
    """The night editor: boost what's rising, decay what's been sitting,
    pull off what's gone stale. Returns (on_page, tracked) — tracked keeps
    retired clusters so they can't sneak back on as 'new' next run."""
    entries = state.get("clusters", [])
    for e in entries:
        e["_toks"] = frozenset(e.get("toks", []))

    on_page, tracked, n_rising, n_retired = [], [], 0, 0
    for item in ranked:
        prev = match_state(item["toks"], entries)
        if prev is None:
            item["tenure_h"] = 0.0
            item["rising"] = False
            item["fresh"] = item["age_hours"] <= FRESH_BADGE_H
            item["first_seen"] = now.isoformat()
            item["peak_outlets"] = item["cluster"]
        else:
            prev["_claimed"] = True
            first = parse_iso(prev.get("first_seen"), now)
            item["tenure_h"] = max(0.0, (now - first).total_seconds() / 3600)
            item["first_seen"] = prev.get("first_seen") or now.isoformat()
            peak = int(prev.get("peak_outlets", 1))
            item["rising"] = item["cluster"] > peak
            item["fresh"] = False
            item["peak_outlets"] = max(peak, item["cluster"])
            if item["rising"]:
                item["score"] += RISING_BONUS * (item["cluster"] - peak)
                n_rising += 1
        item["score"] -= max(0.0, item["tenure_h"] - TENURE_SOFT_H) * TENURE_PENALTY
        tracked.append(item)
        if item["tenure_h"] > TENURE_HARD_H and not item["rising"]:
            n_retired += 1
            continue  # pulled off: it had its run
        on_page.append(item)

    on_page.sort(key=lambda i: i["score"], reverse=True)
    if n_rising or n_retired:
        print(f"  [desk] {n_rising} rising, {n_retired} pulled off the page",
              file=sys.stderr)
    return on_page, tracked


def choose_lead(ranked, state, now):
    """Crown the lead. Rules: it must be confirmed by LEAD_MIN_OUTLETS
    outlets (or be scorching), and a lead that has stopped growing loses
    the siren after LEAD_FATIGUE_H hours to the best fresh challenger."""
    if not ranked:
        return ranked

    def eligible(i):
        return i["cluster"] >= LEAD_MIN_OUTLETS or i["score"] >= LEAD_SOLO_SCORE

    order = [i for i in ranked if eligible(i)] or ranked
    top = order[0]

    prev = state.get("lead")
    if prev:
        ptoks = frozenset(prev.get("toks", []))
        crowned_h = (now - parse_iso(prev.get("since"), now)).total_seconds() / 3600
        same_story = jaccard(top["toks"], ptoks) >= 0.4
        grown = top["score"] > float(prev.get("score", 0)) + 5
        if same_story and crowned_h > LEAD_FATIGUE_H and not top.get("rising") and not grown:
            for challenger in order[1:]:
                if (challenger["score"] >= LEAD_RIVAL_RATIO * top["score"]
                        and jaccard(challenger["toks"], ptoks) < 0.4):
                    print(f"  [desk] lead fatigued after {crowned_h:.1f}h — rotating",
                          file=sys.stderr)
                    top = challenger
                    break

    return [top] + [i for i in ranked if i is not top]


def save_state(state, tracked, lead, now):
    """Persist the desk's memory. Carries over unclaimed recent clusters so
    a one-run feed hiccup doesn't reset a story's tenure."""
    entries = []
    for item in tracked[:400]:
        entries.append({
            "toks": sorted(item["toks"]),
            "first_seen": item.get("first_seen") or now.isoformat(),
            "last_seen": now.isoformat(),
            "peak_outlets": item.get("peak_outlets", item["cluster"]),
        })
    for e in state.get("clusters", []):
        if e.get("_claimed"):
            continue
        last = parse_iso(e.get("last_seen"), now)
        if (now - last).total_seconds() / 3600 <= STATE_PRUNE_H:
            entries.append({k: v for k, v in e.items() if not k.startswith("_")})

    lead_entry = None
    if lead is not None:
        lead_entry = {"toks": sorted(lead["toks"]), "since": now.isoformat(),
                      "score": round(lead["score"], 1)}
        prev = state.get("lead")
        if prev and jaccard(frozenset(prev.get("toks", [])), lead["toks"]) >= 0.4:
            # Same story keeps its original crowning time and score.
            lead_entry["since"] = prev.get("since", lead_entry["since"])
            lead_entry["score"] = prev.get("score", lead_entry["score"])

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"clusters": entries[:500], "lead": lead_entry}, f,
                  ensure_ascii=False, separators=(",", ":"))


# ── Rendering ───────────────────────────────────────────────────────────────

def headline_case(title):
    return html.escape(title.upper())


def tone_tag(tone):
    if tone > 0:
        return ' &middot; <span class="rosy">ROSY</span>'
    if tone < 0:
        return ' &middot; <span class="grim">GRIM</span>'
    return ""


def partition(stories):
    """Group stories by desk (score order preserved within each), then
    bin-pack the desks onto three columns so the page stays balanced.
    Mirrored by the client-side mixer — keep the two in sync."""
    by_topic, names = {}, []
    for s in stories:
        t = s["topic"]
        if t not in by_topic:
            by_topic[t] = []
            names.append(t)
        by_topic[t].append(s)
    sections = sorted(by_topic.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    cols = [[], [], []]
    counts = [0, 0, 0]
    for name, items in sections:
        c = counts.index(min(counts))
        cols[c].append((name, items))
        counts[c] += len(items) + 2  # a header costs about two rows
    return cols


def render(ranked, sources_ok, now):
    lead = ranked[0] if ranked else None
    rest = ranked[1:]

    def badge_bits(item):
        bits = []
        if item.get("rising"):
            bits.append('<span class="rise">RISING &#9650;</span>')
        elif item.get("fresh"):
            bits.append('<span class="fresh">NEW</span>')
        if item["cluster"] >= 3:
            bits.append(f'{item["cluster"]} OUTLETS')
        return bits

    def link_html(item, cls=""):
        klass = f' class="{cls}"' if cls else ""
        src = " &middot; ".join([html.escape(item["source"])] + badge_bits(item))
        return (
            f'<div class="story"><a{klass} href="{html.escape(item["link"])}" '
            f'target="_blank" rel="noopener">{headline_case(item["title"])}</a>'
            f'<span class="src">{src}{tone_tag(item["tone"])}</span></div>'
        )

    def section_html(name, items):
        rows = [f'<div class="schead">{html.escape(name)}</div>']
        for i, item in enumerate(items):
            cls = "hot" if item["score"] >= 25 else ""
            rows.append(link_html(item, cls))
            if (i + 1) % 6 == 0 and i + 1 < len(items):
                rows.append('<hr class="rule">')
        return '<div class="sec">' + "\n".join(rows) + "</div>"

    col_html = []
    for col in partition(rest[:PAGE_STORIES]):
        col_html.append("\n".join(section_html(name, items) for name, items in col))
    while len(col_html) < 3:
        col_html.append("")

    lead_html = ""
    if lead:
        siren = '<div class="siren">🚨</div>' if lead["score"] >= 30 else ""
        lead_bits = [html.escape(lead["source"])]
        if lead["cluster"] > 1:
            lead_bits.append(f'REPORTED BY {lead["cluster"]} OUTLETS')
        if lead.get("rising"):
            lead_bits.append('<span class="rise">RISING &#9650;</span>')
        lead_html = (
            f'{siren}<a class="lead" href="{html.escape(lead["link"])}" '
            f'target="_blank" rel="noopener">{headline_case(lead["title"])}</a>'
            f'<div class="lead-src">{" &middot; ".join(lead_bits)}</div>'
        )

    # The natural news cycle's rosy share (of the tone-committed top stories)
    # is the tone slider's default position; the wire's Trump share is the
    # dosage slider's default.
    top = ranked[:PAGE_STORIES + 1]
    n_rosy = sum(1 for i in top if i["tone"] > 0)
    n_grim = sum(1 for i in top if i["tone"] < 0)
    natural = round(100 * n_rosy / (n_rosy + n_grim)) if (n_rosy + n_grim) else 50
    nat_dose = round(100 * sum(1 for i in top if i["trump"]) / len(top)) if top else 0

    # Pool for the client-side mixer: top stories by rank, plus extra rosy
    # stories from further down so the sunshine end of the slider has
    # inventory (drama scoring naturally buries the gentle stuff).
    pool_items = list(ranked[:POOL_SIZE])
    rosy_extra = [i for i in ranked[POOL_SIZE:] if i["tone"] > 0][:PAGE_STORIES]
    pool_items = sorted(pool_items + rosy_extra, key=lambda i: i["score"], reverse=True)

    pool = [
        {
            "t": item["title"],
            "u": item["link"],
            "s": item["source"],
            "sc": round(item["score"], 1),
            "tn": item["tone"],
            "cl": item["cluster"],
            "tp": item["topic"],
            "tr": 1 if item["trump"] else 0,
            "rs": 1 if item.get("rising") else 0,
            "nw": 1 if item.get("fresh") else 0,
        }
        for item in pool_items
    ]
    pool_json = json.dumps(pool, ensure_ascii=False).replace("</", "<\\/")

    stamp = now.strftime("%A %B %d, %Y").upper() + now.strftime(" &middot; %H:%M UTC")
    src_line = " &middot; ".join(html.escape(s) for s in sources_ok)
    og_desc = html.escape(
        (lead["title"].upper() + " — " if lead else "")
        + "Auto-refreshing front page. Dial your doom with THE JUDGMENT; "
          "dial your Trump with THE DOSAGE.", quote=True)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="1800">
<meta name="description" content="{og_desc}">
<meta property="og:title" content="THE GRUDGE REPORT">
<meta property="og:description" content="{og_desc}">
<meta property="og:type" content="website">
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
  .judgment {{ border: 3px double #000; max-width: 560px; margin: 0 auto 8px;
               padding: 10px 18px 14px; text-align: center; }}
  .judgment .jtitle {{ font-size: 13px; font-weight: bold; letter-spacing: 3px; }}
  .judgment .jread {{ font-size: 11px; letter-spacing: 1px; margin: 4px 0 8px; }}
  .judgment .jread .grim {{ color: #c00; font-weight: bold; }}
  .judgment .jread .rosy {{ color: #070; font-weight: bold; }}
  .judgment .jsplit {{ border-top: 1px solid #000; margin: 12px -18px 10px; }}
  .jrow {{ display: flex; align-items: center; gap: 10px; }}
  .jrow .jend {{ font-size: 14px; }}
  input[type=range] {{
    flex: 1; appearance: none; -webkit-appearance: none; height: 4px;
    background: #000; outline: none; cursor: pointer;
  }}
  input[type=range]::-webkit-slider-thumb {{
    appearance: none; -webkit-appearance: none; width: 18px; height: 18px;
    background: #fff; border: 3px solid #000; border-radius: 0;
  }}
  input[type=range]::-moz-range-thumb {{
    width: 12px; height: 12px; background: #fff; border: 3px solid #000;
    border-radius: 0;
  }}
  .leadbox {{ text-align: center; margin: 22px auto 26px; max-width: 760px; }}
  .siren {{ font-size: 34px; animation: flash 1s step-start infinite; }}
  @keyframes flash {{ 50% {{ opacity: 0.25; }} }}
  a.lead {{ font-size: 32px; font-weight: bold; line-height: 1.2;
            color: #c00; text-decoration: underline; }}
  a.lead:hover {{ background: #c00; color: #fff; }}
  a.lead.sunny {{ color: #070; }}
  a.lead.sunny:hover {{ background: #070; color: #fff; }}
  .lead-src {{ font-size: 11px; margin-top: 6px; letter-spacing: 1px; }}
  .columns {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 26px;
              border-top: 1px solid #000; padding-top: 18px; }}
  .sec {{ margin-bottom: 22px; }}
  .schead {{ color: #c00; font-size: 11px; font-weight: bold;
             letter-spacing: 3px; border-bottom: 1px solid #000;
             margin: 2px 0 10px; padding-bottom: 2px; }}
  .story {{ margin-bottom: 13px; font-size: 14px; font-weight: bold;
            line-height: 1.35; }}
  .story a.hot {{ color: #c00; }}
  .story a.hot:hover {{ background: #c00; color: #fff; }}
  .src {{ display: block; font-size: 10px; font-weight: normal; color: #555;
          letter-spacing: 1px; margin-top: 1px; }}
  .src .grim {{ color: #c00; }}
  .src .rosy {{ color: #070; }}
  .src .rise, .lead-src .rise {{ color: #c00; font-weight: bold; }}
  .src .fresh {{ color: #070; font-weight: bold; }}
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
  <div class="judgment">
    <div class="jtitle">⚖ THE JUDGMENT ⚖</div>
    <div class="jread" id="jread">TODAY'S NEWS CYCLE: <span class="grim">{100 - natural}% GRIM</span> / <span class="rosy">{natural}% ROSY</span></div>
    <div class="jrow">
      <span class="jend" title="100% doom">😱</span>
      <input type="range" id="mix" min="0" max="100" value="{natural}"
             aria-label="Percentage of positive news">
      <span class="jend" title="100% sunshine">😊</span>
    </div>
    <div class="jsplit"></div>
    <div class="jtitle">☢ THE DOSAGE ☢</div>
    <div class="jread" id="dread">TODAY'S WIRE IS <span class="grim">{nat_dose}% TRUMP</span></div>
    <div class="jrow">
      <span class="jend" title="Trump-free">🚫</span>
      <input type="range" id="dose" min="0" max="100" value="{nat_dose}"
             aria-label="Percentage of Trump coverage">
      <span class="jend" title="Full firehose">🍊</span>
    </div>
  </div>
  <div class="leadbox" id="leadbox">{lead_html}</div>
  <div class="columns">
    <div class="col" id="col0">{col_html[0]}</div>
    <div class="col" id="col1">{col_html[1]}</div>
    <div class="col" id="col2">{col_html[2]}</div>
  </div>
  <div class="footer">
    WIRES: {src_line}<br>
    AUTO-GENERATED BY <a href="https://github.com/jlgreen11/drudge">build.py</a> &middot;
    HEADLINES BELONG TO THEIR PUBLISHERS &middot; NOT AFFILIATED WITH ANY OTHER REPORT
  </div>
  <script id="pool" type="application/json">{pool_json}</script>
  <script>
  (function () {{
    var POOL = JSON.parse(document.getElementById("pool").textContent);
    var NATURAL = {natural};
    var NATDOSE = {nat_dose};
    var TOTAL = {PAGE_STORIES};
    var CATCHALL = "{TOPIC_CATCHALL}";
    var mix = document.getElementById("mix");
    var dose = document.getElementById("dose");
    var jread = document.getElementById("jread");
    var dread = document.getElementById("dread");

    function toneMix(list, n, p) {{
      if (n <= 0) return [];
      var pos = [], neg = [], neu = [];
      list.forEach(function (x) {{ (x.tn > 0 ? pos : x.tn < 0 ? neg : neu).push(x); }});
      var nPos = Math.round(n * p / 100);
      var take = pos.slice(0, nPos).concat(neg.slice(0, n - nPos));
      if (take.length < n) take = take.concat(neu.slice(0, n - take.length));
      if (take.length < n) {{
        var got = {{}};
        take.forEach(function (x) {{ got[x.u] = 1; }});
        list.forEach(function (x) {{
          if (take.length < n && !got[x.u]) take.push(x);
        }});
      }}
      return take;
    }}

    function pick(p, t) {{
      var want = TOTAL + 1; // lead + columns
      var tr = POOL.filter(function (x) {{ return x.tr; }});
      var non = POOL.filter(function (x) {{ return !x.tr; }});
      var nT = Math.min(Math.round(want * t / 100), tr.length);
      var take = toneMix(tr, nT, p).concat(toneMix(non, want - nT, p));
      if (take.length < want) {{
        var got = {{}};
        take.forEach(function (x) {{ got[x.u] = 1; }});
        POOL.forEach(function (x) {{
          if (take.length < want && !got[x.u]) take.push(x);
        }});
      }}
      take.sort(function (a, b) {{ return b.sc - a.sc; }});
      return take;
    }}

    function toneTag(tn) {{
      if (tn > 0) return ' \\u00b7 <span class="rosy">ROSY</span>';
      if (tn < 0) return ' \\u00b7 <span class="grim">GRIM</span>';
      return "";
    }}

    function srcLine(item) {{
      var bits = item.s.replace(/[<>&]/g, "");
      if (item.rs) bits += ' \\u00b7 <span class="rise">RISING \\u25b2</span>';
      else if (item.nw) bits += ' \\u00b7 <span class="fresh">NEW</span>';
      if (item.cl >= 3) bits += " \\u00b7 " + item.cl + " OUTLETS";
      return bits + toneTag(item.tn);
    }}

    function storyNode(item) {{
      var div = document.createElement("div");
      div.className = "story";
      var a = document.createElement("a");
      a.href = item.u;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = item.t.toUpperCase();
      if (item.sc >= 25) a.className = "hot";
      var src = document.createElement("span");
      src.className = "src";
      src.innerHTML = srcLine(item);
      div.appendChild(a);
      div.appendChild(src);
      return div;
    }}

    // Mirror of build.py partition(): group by desk, bin-pack onto columns.
    function partition(rest) {{
      var by = {{}}, names = [];
      rest.forEach(function (x) {{
        var t = x.tp || CATCHALL;
        if (!by[t]) {{ by[t] = []; names.push(t); }}
        by[t].push(x);
      }});
      var secs = names.map(function (n) {{ return [n, by[n]]; }});
      secs.sort(function (a, b) {{
        return b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1);
      }});
      var cols = [[], [], []], counts = [0, 0, 0];
      secs.forEach(function (s) {{
        var c = counts.indexOf(Math.min.apply(null, counts));
        cols[c].push(s);
        counts[c] += s[1].length + 2;
      }});
      return cols;
    }}

    function renderPage(p, t) {{
      var chosen = pick(p, t);
      if (!chosen.length) return;
      var lead = chosen[0], rest = chosen.slice(1);

      var box = document.getElementById("leadbox");
      box.innerHTML = "";
      if (lead.sc >= 30) {{
        var siren = document.createElement("div");
        siren.className = "siren";
        siren.textContent = lead.tn > 0 ? "🌈" : "🚨";
        box.appendChild(siren);
      }}
      var la = document.createElement("a");
      la.className = "lead" + (lead.tn > 0 ? " sunny" : "");
      la.href = lead.u;
      la.target = "_blank";
      la.rel = "noopener";
      la.textContent = lead.t.toUpperCase();
      box.appendChild(la);
      var ls = document.createElement("div");
      ls.className = "lead-src";
      ls.textContent = lead.s + (lead.cl > 1 ? " \\u00b7 REPORTED BY " + lead.cl + " OUTLETS" : "");
      box.appendChild(ls);

      partition(rest).forEach(function (col, c) {{
        var el = document.getElementById("col" + c);
        el.innerHTML = "";
        col.forEach(function (sec) {{
          var wrap = document.createElement("div");
          wrap.className = "sec";
          var head = document.createElement("div");
          head.className = "schead";
          head.textContent = sec[0];
          wrap.appendChild(head);
          sec[1].forEach(function (item, i) {{
            wrap.appendChild(storyNode(item));
            if ((i + 1) % 6 === 0 && i + 1 < sec[1].length) {{
              var hr = document.createElement("hr");
              hr.className = "rule";
              wrap.appendChild(hr);
            }}
          }});
          el.appendChild(wrap);
        }});
      }});
    }}

    function readout(p, t) {{
      var jlabel = (p === NATURAL) ? "TODAY'S NEWS CYCLE: " : "YOUR VERDICT: ";
      jread.innerHTML = jlabel +
        '<span class="grim">' + (100 - p) + "% GRIM</span> / " +
        '<span class="rosy">' + p + "% ROSY</span>";
      if (t === NATDOSE) {{
        dread.innerHTML = 'TODAY\\'S WIRE IS <span class="grim">' + t + "% TRUMP</span>";
      }} else {{
        dread.innerHTML = 'YOUR DOSAGE: <span class="grim">' + t + "% TRUMP</span>" +
          " (WIRE: " + NATDOSE + "%)";
      }}
    }}

    function apply(p, t, save) {{
      readout(p, t);
      renderPage(p, t);
      if (save) {{
        try {{
          localStorage.setItem("grudgeMix", String(p));
          localStorage.setItem("grudgeDose", String(t));
        }} catch (e) {{}}
      }}
    }}

    function current() {{
      return [parseInt(mix.value, 10), parseInt(dose.value, 10)];
    }}

    mix.addEventListener("input", function () {{
      var c = current();
      apply(c[0], c[1], true);
    }});
    dose.addEventListener("input", function () {{
      var c = current();
      apply(c[0], c[1], true);
    }});

    var savedMix = null, savedDose = null;
    try {{
      savedMix = localStorage.getItem("grudgeMix");
      savedDose = localStorage.getItem("grudgeDose");
    }} catch (e) {{}}
    var p = savedMix === null ? NATURAL : parseInt(savedMix, 10);
    var t = savedDose === null ? NATDOSE : parseInt(savedDose, 10);
    if (isNaN(p)) p = NATURAL;
    if (isNaN(t)) t = NATDOSE;
    if (p !== NATURAL || t !== NATDOSE) {{
      mix.value = p;
      dose.value = t;
      apply(p, t, false);
    }}
  }})();
  </script>
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

    now = datetime.now(timezone.utc)
    state = load_state()
    ranked = dedupe_and_rank(all_items)
    on_page, tracked = apply_state(ranked, state, now)
    on_page = choose_lead(on_page, state, now)

    sources_ok.sort()
    page = render(on_page, sources_ok, now)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)
    save_state(state, tracked, on_page[0] if on_page else None, now)

    n_rosy = sum(1 for i in on_page if i["tone"] > 0)
    n_grim = sum(1 for i in on_page if i["tone"] < 0)
    n_trump = sum(1 for i in on_page[:PAGE_STORIES + 1] if i["trump"])
    print(f"Wrote index.html: 1 lead + {min(len(on_page) - 1, PAGE_STORIES)} stories "
          f"from {len(sources_ok)} sources "
          f"({len(on_page)} clusters: {n_grim} grim / {n_rosy} rosy; "
          f"{n_trump}/{min(len(on_page), PAGE_STORIES + 1)} top stories are Trump).",
          file=sys.stderr)


if __name__ == "__main__":
    main()
