# THE GRUDGE REPORT 🚨

An auto-populated [Drudge Report](https://drudgereport.com) competitor.
Holding a grudge against slow news.

A single dependency-free Python script pulls headlines from 25 news RSS
feeds, clusters near-duplicate stories across outlets, scores them for
urgency, judges each one's tone (GRIM vs. ROSY), crowns a siren-worthy
lead story, and renders the classic three-column, all-caps, Courier-font
front page — topped by **THE JUDGMENT**, a slider that lets readers dial
the exact percentage of positive vs. negative news they can stomach.
A GitHub Actions cron job re-runs it every 30 minutes and commits the
refreshed page — no server, no database, no API keys.

## How it works

```
RSS feeds ──▶ build.py ──▶ index.html ──▶ GitHub Pages
   (25)      fetch, dedupe,   static +      served to
             score, judge,    judgment       the world
             render            slider
```

- **`build.py`** — the whole engine, Python 3 stdlib only.
  - Fetches all 25 feeds in parallel: BBC, NYT, CNN, Fox, NPR, Guardian,
    Al Jazeera, CNBC, The Hill, Politico, ABC, CBS, WSJ, Sky, DW,
    France 24, The Independent, Time, Axios, The Economist, MarketWatch —
    plus dedicated good-news wires (Good News Network, Positive.News,
    Reasons to be Cheerful) so the sunny end of the slider has inventory.
  - Drops anything older than 48 hours (7 days for the slow-publishing
    good-news wires).
  - Clusters near-duplicate headlines by token overlap — a story covered
    by multiple distinct outlets ranks higher.
  - Scores headlines with a drama dictionary (`BREAKING`, `CRISIS`,
    `RESIGNS`, …) plus a freshness bonus. The top score becomes the
    flashing-siren lead; scores over 25 turn red.
  - **THE JUDGMENT**: judges every headline's tone with grim/rosy word
    lexicons and tags it on the page. The full story pool ships in the
    page as JSON; a no-dependency inline script re-mixes the lead and all
    three columns live as the reader drags the slider from 😱 (100% doom)
    to 😊 (100% sunshine). The slider defaults to the day's actual news
    cycle mix, and a reader's chosen verdict persists in localStorage
    across the page's half-hourly refreshes. A 100%-rosy lead gets a 🌈
    instead of the 🚨.
- **`index.html`** — the generated page. Committed so GitHub Pages can
  serve it directly from the repo root.
- **`.github/workflows/update.yml`** — cron every 30 minutes (plus a
  manual *Run workflow* button). Rebuilds the page and pushes only if the
  news actually changed.

## Run it locally

```sh
python3 build.py     # writes index.html
open index.html
```

## Publish it

1. Merge to `main`.
2. Repo **Settings → Pages → Deploy from a branch** → `main` / `/ (root)`.
3. That's it. The cron keeps the front page fresh forever.

## Tune the outrage

- Add or remove feeds in `FEEDS`.
- Adjust the drama dictionary in `HOT_WORDS` — raise `"ai": 3` to 50 for
  a very different front page.
- Adjust the tone lexicons in `GRIM_WORDS` / `ROSY_WORDS` to recalibrate
  THE JUDGMENT.
- The siren appears when the lead scores ≥ 30; red links at ≥ 25.

All headlines link to and belong to their original publishers.
