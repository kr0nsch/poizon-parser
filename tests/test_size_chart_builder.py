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
                self.assertEqual(chart["verified_at"], VERIFIED_AT[key])
                # Ссылки на мужскую и женскую сетки обязательны; у Reebok есть
                # ещё и отдельный источник замера стопы.
                self.assertLessEqual({"men", "women"}, set(chart["sources"]))
                for source in chart["sources"].values():
                    self.assertTrue(source.startswith("https://"))

    def test_verification_dates_are_iso(self):
        for key, date in VERIFIED_AT.items():
            with self.subTest(key=key):
                self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
