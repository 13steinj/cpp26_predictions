"""Synthetic browser data; never written into the published site."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import ROOT, DISCUSSION, CONSENSUS_SOURCE, render_market

markets = json.loads((ROOT / 'markets.json').read_text())
at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=30)
samples = [
    {'at': (at - timedelta(hours=1)).isoformat(), 'counts': [6, 0, 2, 1, 1]},
    {'at': at.isoformat(), 'counts': [2, 1, 1, 2, 2]},
]


def poll(counts):
    return {'type': 'multiple_choice', 'is_open': True,
            'poll_config': {'duplication_checking': 'ip', 'is_multiple_choice': False,
                            'results_visibility': 'always', 'vote_type': 'default'},
            'poll_options': [{'value': code, 'vote_count': count}
                             for code, count in zip(['SF', 'F', 'Abstain', 'A', 'SA'], counts)]}


def page(counts, observations):
    rendered = [render_market(m, poll(counts), observations, at)[0] for m in markets]
    return Template((ROOT / 'template.html').read_text()).substitute(
        discussion=DISCUSSION, consensus_source=CONSENSUS_SOURCE,
        market_count=len(markets), market_label='markets',
        vote_count=sum(counts) * len(markets), markets=''.join(rendered),
        asset_version='fixture', updated_iso=at.isoformat(),
        updated_display='Synthetic browser test data')


empty_samples = [{'at': samples[0]['at'], 'counts': [0] * 5}]
print(json.dumps({
    'html': page(samples[-1]['counts'], samples),
    'empty_html': page([0] * 5, empty_samples),
    'history': {'version': 1, 'checked_at': at.isoformat(),
                'polls': {m['poll_id']: samples for m in markets}},
    'empty_history': {'version': 1, 'checked_at': at.isoformat(),
                      'polls': {m['poll_id']: empty_samples for m in markets}},
    'polls': {m['poll_id']: poll(c) for m, c in zip(markets, ([1, 0, 1, 3, 1], [0, 12, 1, 8, 3]))},
    'first_votes': {m['poll_id']: poll(c) for m, c in zip(markets, ([1, 0, 0, 0, 0], [0, 0, 2, 0, 0]))},
}))
