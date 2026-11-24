import copy
import io
import json
import tempfile
import unittest
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from build import (ROOT, consensus, consensus_label, counts_from_poll, load_history,
                   payouts, prices, record_history, render_history, render_market)


def poll(counts=(0, 0, 0, 0, 0)):
    return {
        "type": "multiple_choice", "is_open": True,
        "poll_config": {"duplication_checking": "ip", "is_multiple_choice": False,
                        "results_visibility": "always"},
        "poll_options": [{"value": code, "vote_count": count}
                         for code, count in zip(("SF", "F", "Abstain", "A", "SA"), counts)],
    }


class BuildTests(unittest.TestCase):
    def test_empty_poll_has_no_prices(self):
        self.assertEqual(prices([0] * 5), [None] * 3)
        self.assertEqual(payouts([0] * 5), [None] * 5)

    def test_graded_prices_match_the_consensus_threshold(self):
        self.assertEqual(prices([17, 10, 2, 1, 6]), [63, 33, 4])
        self.assertEqual(prices([0, 11, 1, 8, 3]), [25, 50, 25])
        self.assertEqual(prices([0, 0, 10, 0, 0]), [0, 100, 0])
        self.assertEqual(prices([2, 0, 0, 1, 0]), [44, 45, 11])
        self.assertEqual(prices([1, 0, 0, 2, 0]), [11, 45, 44])
        for counts in ([1, 3, 7, 11, 13], [0, 0, 0, 0, 9999999], [1] * 5):
            result = prices(counts)
            self.assertEqual(sum(result), 100)
            self.assertEqual(result.index(max(result)), consensus(counts))

    def test_votes_count_once_and_abstentions_do_not_change_the_ratio(self):
        self.assertEqual(consensus([1, 1, 0, 1, 0]), 1)
        self.assertEqual(consensus([1, 0, 0, 1, 1]), 1)
        self.assertEqual(prices([3, 0, 0, 1, 0]), prices([0, 3, 5000, 0, 1]))
        for favor in range(13):
            for against in range(13):
                counts = [favor, 0, 2, against, 0]
                values = prices(counts)
                self.assertEqual(sum(values), 100)
                self.assertEqual(values.index(max(values)), consensus(counts))

    def test_strong_labels_start_at_four_to_one(self):
        for counts, label in (
            ([2, 0, 0, 1, 0], 'No consensus'),
            ([3, 0, 0, 1, 0], 'Consensus'),
            ([4, 0, 0, 1, 0], 'Strong consensus'),
            ([1, 0, 0, 3, 0], 'Consensus against'),
            ([1, 0, 0, 4, 0], 'Strong consensus against'),
            ([0, 1, 0, 0, 0], 'Strong consensus'),
            ([0, 0, 3, 0, 0], 'No consensus'),
            ([0, 0, 0, 0, 0], 'Awaiting first vote'),
        ):
            with self.subTest(counts=counts):
                self.assertEqual(consensus_label(counts), label)

    def test_strong_votes_receive_double_the_regular_payout(self):
        self.assertEqual(payouts([17, 10, 2, 1, 6]), [63, 31.5, 33, 2, 4])
        self.assertEqual(payouts([0, 12, 1, 8, 3]), [27, 13.5, 50, 11.5, 23])
        for counts in ([3, 2, 1, 2, 2], [18, 10, 2, 1, 6], [1, 0, 0, 4, 0]):
            values = payouts(counts)
            self.assertEqual(values[0], 2 * values[1])
            self.assertEqual(values[4], 2 * values[3])
            self.assertEqual(values[2], prices(counts)[1])
            self.assertTrue(all(0 <= value <= 100 for value in values))

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for browser/server model parity')
    def test_browser_and_server_use_identical_pricing(self):
        cases = [[f, 0, n, a, 0] for f in range(10) for a in range(10) for n in (0, 2, 100)]
        cases.append([2000000001, 0, 5, 1000000000, 0])
        script = """import {prices,payouts,consensusLabel} from './pricing.mjs';
let input=''; for await(const chunk of process.stdin) input+=chunk;
process.stdout.write(JSON.stringify(JSON.parse(input).map(c=>[prices(c),payouts(c),consensusLabel(c)])));"""
        result = subprocess.run(['node', '--input-type=module', '-e', script],
                                input=json.dumps(cases), text=True, capture_output=True, cwd=ROOT, check=True)
        expected = [[prices(c), payouts(c), consensus_label(c)] for c in cases]
        self.assertEqual(json.loads(result.stdout), expected)

    def test_backend_order_does_not_change_positions(self):
        data = poll((8, 4, 2, 1, 6))
        data["poll_options"].reverse()
        self.assertEqual(counts_from_poll(data), [8, 4, 2, 1, 6])

    def test_rejects_incompatible_poll_settings(self):
        for key, value in (("duplication_checking", "session"), ("is_multiple_choice", True),
                           ("results_visibility", "hidden"), ("allow_other_option", True),
                           ("voting_interval", 60), ("vote_type", "points")):
            data = poll()
            data["poll_config"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                counts_from_poll(data)

    def test_rejects_misleading_or_invalid_option_data(self):
        for mutation in ("missing", "duplicate", "unexpected", "negative", "float", "bool"):
            data = poll()
            if mutation == "missing":
                data["poll_options"].pop()
            elif mutation == "duplicate":
                data["poll_options"].append(copy.deepcopy(data["poll_options"][0]))
            elif mutation == "unexpected":
                data["poll_options"][0]["value"] = "Yes"
            else:
                data["poll_options"][0]["vote_count"] = {"negative": -1, "float": 1.5, "bool": True}[mutation]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                counts_from_poll(data)

    def test_escapes_content_and_handles_closed_polls(self):
        market = {"poll_id": "abc123", "title": "<script>bad()</script>", "description": "A & B"}
        data = poll((1, 1, 1, 0, 0))
        data["is_open"] = False
        html, total = render_market(market, data)
        self.assertNotIn("<script>", html)
        self.assertIn("A &amp; B", html)
        self.assertIn("Poll closed", html)
        self.assertNotIn("Cast a vote", html)
        self.assertEqual(total, 3)

    def test_history_survives_clean_builds_and_omits_unchanged_samples(self):
        at = datetime(2026, 11, 23, 21, 0, tzinfo=timezone.utc)
        original = {"version": 1, "polls": {}}
        record_history(original, "abc123", [1, 1, 1, 0, 0], at)
        record_history(original, "abc123", [1, 1, 1, 0, 0], at + timedelta(minutes=1))
        self.assertEqual(len(original["polls"]["abc123"]), 1)
        with patch("build.urlopen", return_value=io.BytesIO(json.dumps(original).encode())):
            restored = load_history(Path("/not-a-real-history-file"), "https://example.com/history.json")
        record_history(restored, "abc123", [3, 2, 1, 2, 2], at + timedelta(minutes=30))
        self.assertEqual(len(restored["polls"]["abc123"]), 2)
        self.assertEqual(restored["polls"]["abc123"][0]["counts"], [1, 1, 1, 0, 0])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.json"
            path.write_text(json.dumps(restored))
            self.assertEqual(load_history(path), restored)

    def test_history_starts_empty_only_on_404(self):
        for status in (404, 500):
            error = HTTPError("https://example.com/history.json", status, "test", {}, None)
            with patch("build.urlopen", side_effect=error):
                if status == 404:
                    self.assertEqual(load_history(Path("unused"), error.url), {"version": 1, "polls": {}})
                else:
                    with self.assertRaises(HTTPError):
                        load_history(Path("unused"), error.url)

    def test_rejects_invalid_history(self):
        sample = {"at": "2026-11-23T21:00:00+00:00", "counts": [1, 0, 0, 0, 0]}
        for samples in ([sample, sample], [{**sample, "counts": [-1, 0, 0, 0, 0]}],
                        [{**sample, "at": "2026-11-23T21:00:00"}]):
            with patch("build.urlopen", return_value=io.BytesIO(json.dumps({"version": 1, "polls": {"abc": samples}}).encode())):
                with self.assertRaises(ValueError):
                    load_history(Path("unused"), "https://example.com/history.json")

    def test_chart_shows_prices_but_does_not_price_empty_intervals(self):
        at = datetime(2026, 11, 23, 21, 0, tzinfo=timezone.utc)
        history = {"version": 1, "polls": {}}
        record_history(history, "abc", [1, 0, 1, 0, 1], at)
        record_history(history, "abc", [5, 2, 1, 1, 1], at + timedelta(minutes=30))
        chart = render_history(history["polls"]["abc"], "A & B", at + timedelta(minutes=30))
        self.assertEqual(chart.count('class="history-line saved'), 3)
        self.assertIn('A &amp; B', chart)
        self.assertIn('80.00', chart)  # 50-cent endpoint is halfway up the chart.
        record_history(history, "abc", [0] * 5, at + timedelta(minutes=60))
        chart = render_history(history["polls"]["abc"], "Test", at + timedelta(minutes=90))
        self.assertEqual(chart.count('class="history-point saved'), 6)
        self.assertNotIn('cx="636.00"', chart)


if __name__ == "__main__":
    unittest.main()
