# C++26 sentiment exchange

[Live site](https://13steinj.github.io/cpp26_predictions/).

A tiny, unofficial community sentiment site with three graded outcome prices:
**Consensus, No consensus, Consensus against**. People vote using five WG21-style
choices: **SF, F, Abstain, A, SA**. No real money or trading.

## Consensus, prices and payouts

Combine SF+F as votes for and A+SA as votes against. Each ballot counts once;
abstentions do not enter the ratio.

[WG21 SD-4](https://isocpp.org/std/standing-documents/sd-4-wg21-practices-and-procedures)
says a proposal normally advances with **more than twice** as many votes for as
against, after discussion. The site applies that heuristic in both directions:

- **Consensus:** For > 2 × Against.
- **Consensus against:** Against > 2 × For.
- **No consensus:** neither test passes, including exactly 2:1.
- **Strong consensus [against]:** the winning side has at least 4 × the other side.

The 4:1 strength labels, prices and payout sizes are site conventions. Actual
WG21 chairs judge consensus after discussion.

Prices use weights **For² : 2×For×Against : Against²**, normalized to $1.00.
This makes the matching consensus outcome the largest price. Whole-cent rounding
favors No consensus at exact threshold ties. All-abstain polls price No consensus
at $1.00; empty polls have no prices.

The indicative payout per vote is:

| Vote | Payout |
|---|---|
| SF | Full Consensus price |
| F | Half Consensus price |
| Abstain | Full No consensus price |
| A | Half Consensus against price |
| SA | Full Consensus against price |

Strong votes therefore pay twice their regular counterpart. Half-cent payouts
are displayed without rounding away that difference. The maximum is $1.00 per
vote. Payout sizing does not give strong ballots extra votes in the consensus test.

## Live data and saved history

A Python standard-library build generates static HTML, CSS and SVG charts.
A small JavaScript module refreshes public StrawPoll counts every minute. There
are no frameworks, chart libraries, fonts, or production package dependencies.
Without JavaScript, the page shows the last published prices and saved charts.

The chart distinguishes:

- **Filled dots and solid lines:** saved snapshots.
- **Hollow dots and dashed lines:** the latest live observation, marked
  **Current time (not saved)**.

Current time means when the browser fetched the totals, not when individual
votes were cast. A live point does not write to history or local storage.
On an API failure, a previous live observation retains its original timestamp
and is labelled Last live check. The snapshot panel shows timestamps, three
prices, consensus labels and the original five-way counts.

`_site/history.json` preserves timestamped raw five-way counts and the latest
build's `checked_at` time. It stores no identities or IP addresses. Historical
prices are recalculated from those preserved counts using the current model.
Earlier vote events cannot be reconstructed.

Each build reads the previously published history, appends changed counts, and
redeploys it with the site. History survives clean Actions runners without a
database or automated commits. Downloads use unique URLs, and scripts/styles
are versioned to prevent stale cached charts.

## Preview

Requires Python 3.10+ and internet access at build time.

~~~sh
python build.py
python -m http.server 8000 --directory _site --bind 0.0.0.0
~~~

Open <http://127.0.0.1:8000/> or this computer's IP on port 8000.
In another terminal, run `python build.py --watch 60` to record preview history.
Restart that recorder after editing build code.

To seed a fresh checkout with existing history, set `HISTORY_URL` to the
published history.json URL. A 404 starts history; other download errors fail the
build and retain the last deployment.

## GitHub Pages

The workflow on `master` runs on pushes, manual dispatch, and a five-minute cron.
GitHub can delay scheduled runs; live points continue updating independently.
The footer shows the latest saved check. Keep Actions enabled.

`actions/upload-pages-artifact` uploads the site, and `deploy.py` publishes its
artifact ID using the workflow's automatic token and OIDC identity. No extra API
keys or deployment credentials are needed. Settings > Pages > Source must be
GitHub Actions. Scheduled refreshes deploy artifacts; they do not commit.

## Add a question

Create a [free StrawPoll](https://strawpoll.com/create/) with these exact options:

~~~text
SF - Strongly For
F - For
Abstain
A - Against
SA - Strongly Against
~~~

Use **One vote per IP address**, single choice, public results at all times,
no Other option, and no repeat-voting interval. Add its public ID, title and
description to `markets.json`; rebuild. Both the build and browser reject
incompatible poll settings.

Current questions:

- [C++26 will be a net positive for C++.](https://strawpoll.com/kjn1DKrq0yQ)
- [C++26 will pass second shot at DIS](https://strawpoll.com/NoZrzMQ63Z3)

Inspired by [this r/cpp discussion](https://old.reddit.com/r/cpp/comments/1y3svqv/prediction_c26/).
Reddit blocked retrieval during development; the first statement is a broad
starter question.

The anonymous creator session is private in ignored `.poll-admin.json` with
owner-only permissions. Preserve it to retain management access. IP limits are
per poll: people on a shared connection share the limit. Enforcement was tested
with a disposable poll: a fresh session on the same verified public IP was
rejected after the first vote. That test poll was deleted.

## Verify

~~~sh
python -m unittest discover -s tests -v
~~~

Node, when available, checks parity between the Python and browser pricing
models. For headless checks, keep the preview server running:

~~~sh
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tests/browser.mjs
~~~

Or set `CHROME_PATH=/usr/bin/google-chrome` to use installed Chrome. Tests cover
1280px, 390px and 320px layouts, saved and live observations, payout ratios,
thresholds, failures, first unsaved votes, and both real poll pages. They submit
no votes. Synthetic data and screenshots stay in ignored test-results/.
