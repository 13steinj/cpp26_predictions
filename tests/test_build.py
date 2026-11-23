import copy
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from build import counts_from_poll, load_history, prices, record_history, render_history, render_market


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
        self.assertEqual(prices([0] * 5), [None] * 5)

    def test_rounding_is_exact_and_preserves_zero(self):
        self.assertEqual(prices([1, 1, 1, 0, 0]), [34, 33, 33, 0, 0])
        self.assertEqual(prices([3, 2, 1, 2, 2]), [30, 20, 10, 20, 20])
        for counts in ([1, 3, 7, 11, 13], [0, 0, 0, 0, 9999999], [1] * 5):
            result = prices(counts)
            self.assertEqual(sum(result), 100)
            self.assertTrue(all(abs(c - 100 * n / sum(counts)) < 1
                                for c, n in zip(result, counts)))

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
        record_history(history, "abc", [3, 2, 1, 2, 2], at)
        record_history(history, "abc", [5, 2, 1, 1, 1], at + timedelta(minutes=30))
        chart = render_history(history["polls"]["abc"], "A & B", at + timedelta(minutes=30))
        self.assertEqual(chart.count('<polyline'), 5)
        self.assertIn('A &amp; B', chart)
        self.assertIn('80.00', chart)  # 50-cent endpoint is halfway up the chart.
        record_history(history, "abc", [0] * 5, at + timedelta(minutes=60))
        chart = render_history(history["polls"]["abc"], "Test", at + timedelta(minutes=90))
        self.assertNotIn('<circle', chart)
        self.assertNotIn('cx="636.00"', chart)


if __name__ == "__main__":
    unittest.main()
