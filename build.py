"""Build static quotes and SVG history from public StrawPoll vote counts."""

import argparse
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from string import Template
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
POSITIONS = (("SF", "Strongly For"), ("F", "For"), ("Abstain", "Abstain"),
             ("A", "Against"), ("SA", "Strongly Against"))
DISCUSSION = "https://old.reddit.com/r/cpp/comments/1y3svqv/prediction_c26/"


def prices(counts):
    """Apportion 100 whole cents; never invent a price for an empty poll."""
    total = sum(counts)
    if not total:
        return [None] * len(counts)
    cents = [100 * count // total for count in counts]
    order = sorted(range(len(counts)), key=lambda i: -(100 * counts[i] % total))
    for i in order[:100 - sum(cents)]:
        cents[i] += 1
    return cents


def read_poll(poll_id):
    if not re.fullmatch(r"[a-zA-Z0-9]+", poll_id):
        raise ValueError("Invalid StrawPoll ID")
    request = Request(f"https://api.strawpoll.com/v3/polls/{poll_id}",
                      headers={"User-Agent": "cxx26-markets/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def counts_from_poll(poll):
    config = poll["poll_config"]
    if (poll["type"] != "multiple_choice"
            or config["duplication_checking"] != "ip"
            or config["is_multiple_choice"]
            or config["results_visibility"] != "always"
            or config.get("allow_other_option")
            or config.get("voting_interval")
            or config.get("vote_type", "default") != "default"):
        raise ValueError("Poll must be single-choice, IP-unique, with public results and no repeat voting")
    options = poll["poll_options"]
    expected = {code: label for code, label in POSITIONS}
    counts = {}
    for option in options:
        value = option["value"].strip()
        code = next((code for code, label in expected.items()
                     if value in (code, label, f"{code} - {label}")), None)
        if code is None or code in counts:
            raise ValueError(f"Unexpected or duplicate poll option: {value}")
        count = option["vote_count"]
        if type(count) is not int or count < 0:
            raise ValueError("Vote counts must be nonnegative integers")
        counts[code] = count
    if set(counts) != set(expected):
        raise ValueError("Poll must have exactly SF, F, Abstain, A, SA")
    return [counts[code] for code, _ in POSITIONS]


def load_history(path, url=None):
    if url:
        try:
            with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=30) as response:
                history = json.load(response)
        except HTTPError as error:
            if error.code != 404:
                raise
            history = {"version": 1, "polls": {}}
    elif path.exists():
        history = json.loads(path.read_text())
    else:
        history = {"version": 1, "polls": {}}
    if history.get("version") != 1 or not isinstance(history.get("polls"), dict):
        raise ValueError("Unrecognized history format")
    for poll_id, samples in history["polls"].items():
        if not re.fullmatch(r"[a-zA-Z0-9]+", poll_id) or not isinstance(samples, list):
            raise ValueError("Invalid poll history")
        previous = None
        for sample in samples:
            at = datetime.fromisoformat(sample["at"])
            counts = sample["counts"]
            if (at.utcoffset() is None or (previous and at <= previous)
                    or len(counts) != 5
                    or any(type(n) is not int or n < 0 for n in counts)):
                raise ValueError("Invalid history snapshot")
            previous = at
    return history


def record_history(history, poll_id, counts, at):
    samples = history["polls"].setdefault(poll_id, [])
    # Keep changes, not thousands of identical snapshots of an inactive poll.
    if samples and samples[-1]["counts"] == counts:
        return
    sample = {"at": at.isoformat(timespec="seconds"), "counts": counts}
    if samples and datetime.fromisoformat(samples[-1]["at"]) > at:
        raise ValueError("Snapshot time precedes saved history")
    if samples and samples[-1]["at"] == sample["at"]:
        samples[-1] = sample
    else:
        samples.append(sample)


def render_history(samples, title, at):
    first_price = next((i for i, sample in enumerate(samples) if sum(sample["counts"])), None)
    legend = ''.join(f'<span class="{code.lower()}">{code}</span>' for code, _ in POSITIONS)
    if first_price is None:
        chart = '<p class="history-empty">The first vote opens the chart. History starts with recorded votes.</p>'
    else:
        points = list(samples[first_price:])
        # This build is also an observation, even if the counts haven't changed.
        if datetime.fromisoformat(points[-1]["at"]) < at:
            points = [*points, {"at": at.isoformat(timespec="seconds"), "counts": points[-1]["counts"]}]
        start = datetime.fromisoformat(points[0]["at"])
        duration = (at - start).total_seconds()
        values = [prices(sample["counts"]) for sample in points]
        x = [4 + 632 * (datetime.fromisoformat(sample["at"]) - start).total_seconds() / duration
             if duration else 320 for sample in points]
        lines = []
        for i, (code, _) in enumerate(POSITIONS):
            segment = []
            for px, row in zip(x, values):
                if row[i] is None:
                    if segment:
                        lines.append(f'<polyline class="history-line {code.lower()}" points="{" ".join(segment)}"/>')
                        segment = []
                else:
                    segment.append(f'{px:.2f},{4 + (100 - row[i]) * 1.52:.2f}')
            if segment:
                lines.append(f'<polyline class="history-line {code.lower()}" points="{" ".join(segment)}"/>')
            if values[-1][i] is not None:
                lines.append(f'<circle class="history-point {code.lower()}" cx="{x[-1]:.2f}" cy="{4 + (100 - values[-1][i]) * 1.52:.2f}" r="3"/>')
        chart = f'''<div class="history-chart">
          <div class="history-axis" aria-hidden="true"><span>100&cent;</span><span>50&cent;</span><span>0&cent;</span></div>
          <svg viewBox="0 0 640 160" preserveAspectRatio="none" role="img" aria-label="{escape(title, quote=True)}: position prices over time">
            <path class="history-grid" d="M4 4H636 M4 80H636 M4 156H636"/>{''.join(lines)}</svg></div>
          <div class="history-times"><time datetime="{start.isoformat()}">{start.strftime('%d %b %H:%M')} UTC</time>
            <time datetime="{at.isoformat()}">{at.strftime('%d %b %H:%M')} UTC</time></div>'''
    return f'''<section class="history" aria-label="Price history">
      <div class="history-heading"><h4>Price history</h4><div class="history-legend">{legend}</div></div>
      {chart}<p class="history-note">Recorded vote shares. History begins when this site first observes votes.</p></section>'''


def render_market(market, poll, samples=(), at=None):
    counts = counts_from_poll(poll)
    cents = prices(counts)
    poll_url = f'https://strawpoll.com/{market["poll_id"]}'
    contracts = []
    total = sum(counts)
    for (code, label), count, price in zip(POSITIONS, counts, cents):
        value = '&mdash;' if price is None else f'{price}<small>&cent;</small>'
        share = f'{100 * count / total:.1f}% of votes' if total else 'No votes yet'
        contracts.append(f'''<div class="contract {code.lower()}" data-position="{code}">
          <dt>{code}</dt><dd><span class="price">{value}</span>
          <span class="position-label">{label}</span>
          <span class="share">{share}</span>
          <span class="ballots">{count:,} {'vote' if count == 1 else 'votes'}</span></dd></div>''')
    state = "Awaiting first vote" if not total else f"{total:,} {'vote' if total == 1 else 'votes'}"
    if not poll["is_open"]:
        state += " / Poll closed"
    action = (f'<a class="vote" href="{poll_url}">Cast a vote &nearr;</a>'
              if poll["is_open"] else '<span>Voting closed</span>')
    html = f'''<article class="market" data-poll-id="{market['poll_id']}" data-total="{total}">
      <div class="market-meta"><span class="tag">C++26 / Community poll</span><span class="quote-state">Snapshot</span><span class="market-total">{state}</span></div>
      <h3>{escape(market['title'])}</h3>
      <p class="market-description">{escape(market['description'])}</p>
      <dl class="contracts" aria-label="Position prices in cents per dollar">{''.join(contracts)}</dl>
      <div class="market-actions">{action}
        <a href="{poll_url}/results">Live results &nearr;</a>
        <p>Prices = share of votes, rounded to cents</p></div>
      {render_history(samples, market['title'], at or datetime.now(timezone.utc))}
    </article>'''
    return html, sum(counts)


def build():
    markets = json.loads((ROOT / "markets.json").read_text())
    if not markets:
        raise ValueError("Configure at least one market")
    if len({market["poll_id"] for market in markets}) != len(markets):
        raise ValueError("Each market must have its own poll")
    output = ROOT / "_site"
    history = load_history(output / "history.json", os.environ.get("HISTORY_URL"))
    polls = [read_poll(market["poll_id"]) for market in markets]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for market, poll in zip(markets, polls):
        record_history(history, market["poll_id"], counts_from_poll(poll), now)
    rendered = [render_market(market, poll, history["polls"][market["poll_id"]], now)
                for market, poll in zip(markets, polls)]
    html = Template((ROOT / "template.html").read_text()).substitute(
        discussion=DISCUSSION, market_count=len(markets),
        market_label="market" if len(markets) == 1 else "markets",
        vote_count=f"{sum(count for _, count in rendered):,}",
        markets="\n".join(html for html, _ in rendered),
        updated_iso=now.isoformat(timespec="seconds"),
        updated_display=now.strftime("%d %b %Y, %H:%M UTC"))
    # Only write after every poll succeeds. Failed builds leave the deployed snapshot intact.
    output.mkdir(exist_ok=True)
    for filename, contents in (("index.html", html), ("history.json", json.dumps(history, separators=(',', ':')))):
        temporary = output / (filename + ".tmp")
        temporary.write_text(contents, encoding="utf-8")
        temporary.replace(output / filename)
    shutil.copyfile(ROOT / "style.css", output / "style.css")
    shutil.copyfile(ROOT / "quotes.js", output / "quotes.js")
    (output / ".nojekyll").touch()
    print(f"Built {len(markets)} market(s) in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", type=int, default=0, metavar="SECONDS",
                        help="refresh preview snapshots periodically")
    options = parser.parse_args()
    if options.watch < 0:
        parser.error("--watch must be positive")
    while True:
        try:
            build()
        except Exception as error:
            if not options.watch:
                raise
            print(f"Refresh failed; retaining previous site: {error}", flush=True)
        if not options.watch:
            break
        time.sleep(options.watch)
