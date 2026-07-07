# THE GRUDGE REPORT 🚨

An auto-populated [Drudge Report](https://drudgereport.com) competitor.
Holding a grudge against slow news.

A single dependency-free Python script pulls headlines from 14 major news
RSS feeds, clusters near-duplicate stories across outlets, scores them for
urgency, crowns a siren-worthy lead story, and renders the classic
three-column, all-caps, Courier-font front page. A GitHub Actions cron job
re-runs it every 30 minutes and commits the refreshed page — no server, no
database, no API keys.

## How it works

```
RSS feeds ──▶ build.py ──▶ index.html ──▶ GitHub Pages
   (14)      fetch, dedupe,   static        served to
             score, render     page          the world
```

- **`build.py`** — the whole engine, Python 3 stdlib only.
  - Fetches all feeds in parallel (BBC, NYT, CNN, Fox, NPR, Guardian,
    Al Jazeera, CNBC, The Hill, Politico, ABC, CBS, WSJ).
  - Drops anything older than 48 hours.
  - Clusters near-duplicate headlines by token overlap — a story covered
    by multiple outlets ranks higher.
  - Scores headlines with a drama dictionary (`BREAKING`, `CRISIS`,
    `RESIGNS`, …) plus a freshness bonus. The top score becomes the
    flashing-siren lead; scores over 25 turn red.
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
- The siren appears when the lead scores ≥ 30; red links at ≥ 25.

All headlines link to and belong to their original publishers.
