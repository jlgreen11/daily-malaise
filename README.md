# THE GRUDGE REPORT 🚨

An auto-populated [Drudge Report](https://drudgereport.com) competitor.
Holding a grudge against slow news. Not affiliated with the Drudge Report.

A dependency-free Python script pulls headlines from 25 news RSS feeds,
clusters near-duplicate stories across outlets, scores them for urgency,
judges each one's tone (GRIM vs. ROSY), crowns a siren-worthy lead, and
renders the classic three-column, all-caps, Courier-font front page —
topped by **THE JUDGMENT**, a slider that lets readers dial the exact
percentage of positive vs. negative news they can stomach, and **TRUMP
DENSITY**, a dial for how much administration coverage the page carries.
A GitHub Actions cron re-runs it every 30 minutes and commits the
refreshed page — no server, no database, no API keys.

## How it works

```
RSS feeds ──▶ build.py + template.html ──▶ index.html + feed.xml ──▶ GitHub Pages
   (25)       fetch, dedupe, score,          static page +             served to
              judge, remember, render        judgment sliders           the world
                      ▲    │
                  state.json (the editor's memory between runs)
```

- **`build.py`** — the engine, Python 3 stdlib only.
  - Fetches all 25 feeds in parallel with hard caps (5MB per feed, 60s
    wall-clock per feed, 300s total) so one tarpit feed can't wedge a run.
  - Drops anything older than 48 hours (7 days for the slow-publishing
    good-news wires). Future-dated and undated items never earn the
    freshness bonus or the NEW badge.
  - Clusters near-duplicate headlines by token overlap — a story covered
    by multiple distinct outlets ranks higher.
  - Scores headlines with a drama dictionary plus a freshness bonus. The
    top score becomes the flashing-siren lead; scores over 25 turn red.
  - **The editor never sleeps**: `state.json` remembers every story
    between runs. Stories being picked up by more outlets get boosted and
    badged RISING; stories that sat on the page 12+ hours bleed score;
    at 30 hours they're pulled unless rising; a lead that stops growing
    loses the siren after 4 hours. State is shape-validated on load with
    per-section salvage, and written atomically.
  - **THE JUDGMENT / TRUMP DENSITY**: the full story pool ships in the
    page as JSON; an inline no-dependency script re-mixes the lead and
    all three columns live as the reader drags either dial. Defaults are
    the day's measured mix; a reader's verdict persists in localStorage.
  - If fewer than 10 stories or 5 distinct sources come back, the run
    holds the last good page and exits green — a broad feed outage is
    not a crash. If the published page goes stale anyway, readers get a
    "WIRE SILENT" banner and the repo gets a single `wire-down` issue.
- **`template.html`** — the page (HTML/CSS/JS), filled in by
  `string.Template`. Kept out of build.py so the JS is editable and
  testable as JS.
- **`feed.xml`** — the top 30 stories plus the daily stat line, as RSS.
  A site built on RSS should emit RSS.
- **`test_build.py`** — stdlib unittest suite: feed parsing (RSS 2.0,
  RDF, Atom), the tenure/RISING state machine, state salvage, the render
  output contract, feed round-trips, and a node-executed DOM-stub smoke
  test that drags both sliders through their historical crash path. Runs
  on every PR and before every scheduled build.
- **`.github/workflows/update.yml`** — cron every 30 minutes (offset to
  :07/:37, off GitHub's contention peak), tests-before-build, and a
  wire-down alert path.

## The stat, honestly

The page publishes its own coverage numbers with a daily history
(sparklines in THE JUDGMENT box; full series kept uncapped in
`state.json`):

- **FRONT PAGE n%** — share of the top 61 ranked stories matching the
  administration regex (`trump`, `maga`, `potus`, `white house`,
  `oval office` — it measures *administration* coverage density).
- **FULL WIRE n%** — the same share across every unique story cluster
  fetched this run, post-dedup (typically 500+ clusters).
- **ROSY / GRIM** — tone-lexicon judgment over the tone-committed top
  stories.

Both formulas live in `wire_stats()` / `full_wire_dose()` in `build.py`;
the feed list is `FEEDS` at the top of the same file, capped at 40 items
per source. Academic trackers (GDELT, Stanford Cable TV News Analyzer)
publish TV coverage-share series with heavier methodology; this is the
only consumer front page that prints its own number and hands the reader
the dial.

## Analytics (optional, off by default)

The page ships with **zero** analytics. To turn on anonymous, cookieless
counting (pageviews, outbound-headline clicks, dial usage):

1. Create a free [GoatCounter](https://www.goatcounter.com) account.
2. Set `GOATCOUNTER_CODE = "yourcode"` at the top of `build.py`.

That adds one external script tag and a footer disclosure. Caveat: the
page meta-refreshes every 30 minutes, so watch *uniques*, not pageviews —
one parked tab is ~48 pageviews/day.

## Run it locally

```sh
python3 -m unittest -v   # the suite (node optional, for the JS tests)
python3 build.py         # writes index.html, feed.xml, state.json
open index.html
```

## Publish it

1. Merge to `main`.
2. Repo **Settings → Pages → Deploy from a branch** → `main` / `/ (root)`.
3. Recommended: **Settings → Branches** → require the PR test check.
4. That's it. The cron keeps the front page fresh forever.

## Tune the outrage

- Add or remove feeds in `FEEDS`.
- Adjust the drama dictionary in `HOT_WORDS` — raise `"ai": 3` to 50 for
  a very different front page.
- Adjust the tone lexicons in `GRIM_WORDS` / `ROSY_WORDS` to recalibrate
  THE JUDGMENT.
- The siren appears when the lead scores ≥ 30; red links at ≥ 25.

## Roadmap (second wave)

- Deploy via `actions/deploy-pages` instead of committing artifacts
  (kills ~17k bot commits/yr; needs the Pages-source setting flipped,
  plus a weekly workflow keepalive).
- Custom domain; daily stat bot (Bluesky/Mastodon); one Show HN.
- Replace the meta refresh with an in-place JS re-render.
- Demand-side aging: poll GoatCounter clicks at build time and age
  stories *faster* once readers stop clicking them (never a click boost —
  no rich-get-richer).
- Generalize the density dial beyond one politician (`TRUMP_RE` → a
  configurable entity list).
- Tip jar + dropping/licensing the Dow Jones and Economist feeds happen
  together, or not at all.

All headlines link to and belong to their original publishers.
