# C++26 sentiment exchange

A tiny, unofficial community sentiment site with prediction-market styling and
WG21-style positions: **SF, F, Abstain, A, SA**. Each position's price is its
share of votes in cents per dollar. No money, trading, or implied probability.

The site has no frameworks, chart libraries, fonts, or build dependencies.
A Python standard-library build generates HTML, CSS, and SVG history charts.
A small optional JavaScript module refreshes public StrawPoll results every
minute, displaying cents, exact percentage shares, and vote counts on-page.
Without JavaScript, the quotes and graphs show the last published snapshot.
Voting happens on StrawPoll and is limited to one vote per IP address.

Inspired by [this r/cpp discussion](https://old.reddit.com/r/cpp/comments/1y3svqv/prediction_c26/).
Reddit blocked retrieval during development, so the starter statement is a broad
C++26 sentiment question, not a quotation or a reconstruction of that thread.

## Preview

```sh
python build.py
python -m http.server 8000 --directory _site --bind 0.0.0.0
```

Open <http://127.0.0.1:8000/>. Requires Python 3.10+ and internet access at build
time. The generated `_site/` folder is ignored by Git.

To record history while previewing, run `python build.py --watch 60` in another
terminal. It records changed vote counts every minute while the server runs.

## GitHub Pages

Once you choose to commit and push, set **Settings > Pages > Source** to
**GitHub Actions**. The included workflow builds and deploys on pushes to `master`,
on manual runs, and roughly every five minutes. GitHub can delay scheduled runs;
the page displays its UTC snapshot time and links to live results.

There are no API keys. A failed poll fetch or incompatible
poll setting fails the build, leaving the previous deployment in place. Actions
must remain enabled; GitHub can disable schedules after prolonged inactivity in
public repositories. Scheduled refreshes deploy artifacts; they do not commit.

The workflow uploads the Pages artifact, then `deploy.py` publishes that
artifact ID through GitHub's Pages API using the workflow's automatic token
and OIDC identity. No extra deployment credentials are needed.

## Price history

`_site/history.json` stores timestamped aggregate counts for each poll. It stores
no voter identities or IP addresses. Each build reads the previously published
history using the Pages URL, adds changed counts, and redeploys the history file
with the site. This preserves history across clean Actions runners without a
database or automated commits. The file can also be downloaded as a backup.
History and chart downloads use unique URLs to avoid stale copies in the Pages cache.

History begins with this site's first observations; earlier votes cannot be
reconstructed. An empty poll has no price or graph line. Prices are rounded to
$1.00 in total, and the graph shows those prices over time. Prices below $1.00
use cents; the full dollar displays as $1.00. Live quotes can
be newer than the most recent recorded graph point.

When building elsewhere, set `HISTORY_URL` to the deployed `history.json` URL to
retain existing history. A 404 starts a new history file; other download errors
fail the build and retain the previous deployment. Keep the same Pages URL when
moving the site, or supply its old history URL for the first build at the new URL.

## Add a market

Create a [free StrawPoll](https://strawpoll.com/create/) with these exact options:

```text
SF - Strongly For
F - For
Abstain
A - Against
SA - Strongly Against
```

Use **One vote per IP address**, single choice, public results at all times,
no "Other" option, and no repeat-voting interval. Add its public ID, statement,
and description to `markets.json`; rerun the build. Poll creation can be done
without an account. The build only uses the public read endpoint, which was
verified without an API key; programmatic creation is not required.

The two questions are:

- [C++26 will be a net positive for C++.](https://strawpoll.com/kjn1DKrq0yQ)
- [C++26 will pass second shot at DIS](https://strawpoll.com/NoZrzMQ63Z3)

Their anonymous creator session is stored locally in `.poll-admin.json` with
owner-only permissions and is ignored by Git. Keep that file private if you
want to retain poll management access.

IP limits are per poll, not per person. People on a shared connection can be
blocked from voting separately; changing networks can defeat that limit.

IP enforcement was also tested on 2026-11-23 with a disposable poll using the
same security settings: the first vote succeeded, and a second vote from a
fresh browser session with the same verified public IP returned "You (or
someone on your Wi-Fi/network) have already participated in this poll."
The disposable poll was deleted afterward. The starter poll received no test votes.

## Verify

```sh
python -m unittest discover -s tests -v
```

For optional headless Chromium checks, leave the preview server running:

```sh
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tests/browser.mjs
```

Or set `CHROME_PATH=/usr/bin/google-chrome` to use installed Chrome. The check
uses 1280px, 390px, and 320px viewports with JavaScript disabled, checks layout,
contracts, disclosure, and synthetic price history. It tests live price updates
and failure fallback, then opens both real voting pages without submitting a
vote. Synthetic history stays outside the published site. Screenshots are
written to ignored `test-results/`.
