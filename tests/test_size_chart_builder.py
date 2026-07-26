"""Проверки детерминированного снимка официальных размерных таблиц."""

import json
import unittest

from tools.build_size_charts import OUT, VERIFIED_AT, build_charts


class TestHardcodedOfficialCharts(unittest.TestCase):
    def test_builder_matches_committed_json_byte_for_data(self):
        committed = json.loads(OUT.read_text(encoding="utf-8"))
        self.assertEqual(build_charts(), committed)

    def test_every_chart_keeps_gender_sources_and_revision(self):
        for key, chart in build_charts().items():
            with self.subTest(key=key):
                self.assertEqual(chart["verified_at"], VERIFIED_AT)
                self.assertEqual(set(chart["sources"]), {"men", "women"})
                self.assertTrue(chart["sources"]["men"].startswith("https://"))
                self.assertTrue(chart["sources"]["women"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
