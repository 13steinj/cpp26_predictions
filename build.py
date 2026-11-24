"""Build static quotes and SVG history from public StrawPoll vote counts."""

import argparse
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from pathlib import Path
from string import Template
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
POSITIONS = (("SF", "Strongly For"), ("F", "For"), ("Abstain", "Abstain"),
             ("A", "Against"), ("SA", "Strongly Against"))
DISCUSSION = "https://old.reddit.com/r/cpp/comments/1y3svqv/prediction_c26/"
CONSENSUS_SOURCE = "https://isocpp.org/std/standing-documents/sd-4-wg21-practices-and-procedures"
OUTCOMES = (("for", "Consensus"), ("abstain", "No consensus"),
            ("against", "Consensus against"))


def grouped_counts(counts):
    return [counts[0] + counts[1], counts[2], counts[3] + counts[4]]


def consensus(counts):
    """SD-4's strict >2:1 subgroup guideline, applied symmetrically."""
    if not sum(counts):
        return None
    favor, _, against = grouped_counts(counts)
    if favor > 2 * against:
        return 0
    if against > 2 * favor:
        return 2
    return 1


def prices(counts):
    if not sum(counts):
        return [None] * 3
    favor, _, against = grouped_counts(counts)
    weights = [favor * favor, 2 * favor * against, against * against]
    total = sum(weights)
    if not total:
        return [0, 100, 0]
    result = [100 * weight // total for weight in weights]
    priority = {1: 0, 0: 1, 2: 2}
    order = sorted(range(3), key=lambda i: (-(100 * weights[i] % total), priority[i]))
    for i in order[:100 - sum(result)]:
        result[i] += 1
    return result


def consensus_label(counts):
    outcome = consensus(counts)
    if outcome is None:
        return 'Awaiting first vote'
    favor, _, against = grouped_counts(counts)
    if outcome == 0:
        return 'Strong consensus' if favor >= 4 * against else 'Consensus'
    if outcome == 2:
        return 'Strong consensus against' if against >= 4 * favor else 'Consensus against'
    return 'No consensus'


def payouts(counts):
    favor, neutral, against = prices(counts)
    return [favor, favor / 2 if favor is not None else None, neutral,
            against / 2 if against is not None else None, against]


def price_html(price):
    return '&mdash;' if price is None else '$1.00' if price == 100 else f'{price:g}<small>&cent;</small>'


def ballot_summary(counts):
    return ' / '.join(f'{code}: {count}' for (code, _), count in zip(POSITIONS, counts))


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
            separator = '&' if '?' in url else '?'
            fresh_url = f'{url}{separator}snapshot={time.time_ns()}'
            with urlopen(Request(fresh_url, headers={"Cache-Control": "no-cache"}), timeout=30) as response:
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
    if history.get("checked_at") and datetime.fromisoformat(history["checked_at"]).utcoffset() is None:
        raise ValueError("History check time must include a timezone")
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
    legend = ''.join(f'<span class="{code}">{label}</span>' for code, label in OUTCOMES)
    lines = []
    rows = []
    start = datetime.fromisoformat(samples[0]["at"]) if samples else at
    end = datetime.fromisoformat(samples[-1]["at"]) if samples else at
    duration = (end - start).total_seconds()
    for i, (code, label) in enumerate(OUTCOMES):
        path = ''
        for sample in samples:
            price = prices(sample["counts"])[i]
            if price is None:
                if path:
                    lines.append(f'<path class="history-line saved {code}" d="{path}"/>')
                    path = ''
                continue
            when = datetime.fromisoformat(sample["at"])
            x = 4 + 632 * (when - start).total_seconds() / duration if duration else 320
            y = 4 + (100 - price) * 1.52
            path += f' H{x:.2f} V{y:.2f}' if path else f'M{x:.2f},{y:.2f}'
            value = '$1.00' if price == 100 else f'{price:g} cents'
            description = f'Saved snapshot: {when.isoformat()}; {consensus_label(sample["counts"])}; {label}: {value}; {ballot_summary(sample["counts"])}'
            lines.append(f'<circle class="history-point saved {code}" cx="{x:.2f}" cy="{y:.2f}" r="3"><title>{escape(description)}</title></circle>')
        if path:
            lines.append(f'<path class="history-line saved {code}" d="{path}"/>')
    for sample in samples:
        when = datetime.fromisoformat(sample["at"])
        cells = ''.join(f'<td>{price_html(price)}</td>' for price in prices(sample["counts"]))
        rows.append(f'<tr data-kind="snapshot"><th scope="row"><time datetime="{when.isoformat()}">{when.strftime("%d %b %H:%M:%S")} UTC</time><span>Saved snapshot</span></th>{cells}<td><strong>{consensus_label(sample["counts"])}</strong><span>{ballot_summary(sample["counts"])}</span></td></tr>')
    empty = '' if any(sum(sample["counts"]) for sample in samples) else '<p class="history-empty">No recorded votes yet.</p>'
    return f'''<section class="history" aria-label="Consensus price history">
      <div class="history-heading"><h4>Price history</h4><div class="history-legend">{legend}</div></div>
      <div class="history-chart">
        <div class="history-axis" aria-hidden="true"><span>$1.00</span><span>50&cent;</span><span>0&cent;</span></div>
        <svg viewBox="0 0 640 160" preserveAspectRatio="none" role="img" aria-label="{escape(title, quote=True)}: consensus prices over time">
          <path class="history-grid" d="M4 4H636 M4 80H636 M4 156H636"/><g class="history-series">{''.join(lines)}</g></svg></div>
      <div class="history-times"><time class="history-start" datetime="{start.isoformat()}">{start.strftime('%d %b %H:%M')} UTC</time>
        <span class="history-end"><strong>Latest saved snapshot</strong><time datetime="{end.isoformat()}">{end.strftime('%d %b %H:%M')} UTC</time></span></div>
      {empty}<p class="history-note">Solid lines and filled points: saved snapshots. Dashed lines and hollow points: current time, not saved.</p>
      <details class="snapshot-details"><summary>Snapshot information and current data</summary><div class="snapshot-table">
        <table><thead><tr><th>Observation</th><th>For</th><th>No consensus</th><th>Against</th><th>Consensus and ballots</th></tr></thead>
        <tbody class="snapshot-rows">{''.join(rows)}</tbody></table></div></details></section>'''


def render_market(market, poll, samples=(), at=None):
    counts = counts_from_poll(poll)
    cents = prices(counts)
    poll_url = f'https://strawpoll.com/{market["poll_id"]}'
    contracts = []
    total = sum(counts)
    for (code, label), count, price in zip(OUTCOMES, grouped_counts(counts), cents):
        share = (f'{100 * count / total:.1f}% ' + ('abstained' if code == 'abstain' else f'voted {code}')) if total else 'No votes yet'
        quantity = f'{count:,} ' + (('abstention' if count == 1 else 'abstentions') if code == 'abstain'
                                   else f'{"vote" if count == 1 else "votes"} {code}')
        contracts.append(f'''<div class="contract {code}" data-outcome="{code}">
          <dt>{label}</dt><dd><span class="price">{price_html(price)}</span>
          <span class="share">{share}</span><span class="ballots">{quantity}</span></dd></div>''')
    ballot_rows = ''.join(f'<tr data-position="{code}"><th scope="row">{code}</th><td class="ballot-count">{count:,}</td><td>{"Full" if code in ("SF", "SA", "Abstain") else "Half"}</td><td class="vote-payout">{price_html(payout)}</td></tr>'
                          for (code, _), count, payout in zip(POSITIONS, counts, payouts(counts)))
    samples_json = escape(json.dumps(samples, separators=(',', ':')), quote=True)
    state = "Awaiting first vote" if not total else f"{total:,} {'vote' if total == 1 else 'votes'}"
    if not poll["is_open"]:
        state += " / Poll closed"
    action = (f'<a class="vote" href="{poll_url}">Cast a vote &nearr;</a>'
              if poll["is_open"] else '<span>Voting closed</span>')
    html = f'''<article class="market" data-poll-id="{market['poll_id']}" data-total="{total}" data-samples="{samples_json}">
      <div class="market-meta"><span class="tag">C++26 / Community poll</span><span class="quote-state">Snapshot</span><span class="market-total">{state}</span></div>
      <h3>{escape(market['title'])}</h3>
      <p class="market-description">{escape(market['description'])}</p>
      <dl class="contracts" aria-label="Three consensus outcome prices">{''.join(contracts)}</dl>
      <p class="consensus-result">Current result: <strong>{consensus_label(counts)}</strong></p>
      <table class="vote-payouts" aria-label="Five-way ballots and indicative payouts"><thead><tr><th>Vote</th><th>Ballots</th><th>Payout size</th><th>Indicative payout</th></tr></thead><tbody>{ballot_rows}</tbody></table>
      <div class="market-actions">{action}
        <a href="{poll_url}/results">Live results &nearr;</a>
        <p>Strong votes get the full payout; regular votes get half.</p></div>
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
    history["checked_at"] = now.isoformat(timespec="seconds")
    rendered = [render_market(market, poll, history["polls"][market["poll_id"]], now)
                for market, poll in zip(markets, polls)]
    html = Template((ROOT / "template.html").read_text()).substitute(
        discussion=DISCUSSION, market_count=len(markets),
        market_label="market" if len(markets) == 1 else "markets",
        vote_count=f"{sum(count for _, count in rendered):,}",
        markets="\n".join(html for html, _ in rendered),
        asset_version=sha256(b''.join((ROOT / filename).read_bytes() for filename in ("quotes.js", "pricing.mjs", "style.css"))).hexdigest()[:12],
        consensus_source=CONSENSUS_SOURCE,
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
    shutil.copyfile(ROOT / "pricing.mjs", output / "pricing.mjs")
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
