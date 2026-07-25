"""Тесты официальных размерных таблиц брендов."""

import unittest

from poizon_parser.sizechart import (
    CM,
    EU,
    RU,
    UK,
    US_MEN,
    US_WOMEN,
    convert_to_eu,
    load_brand_charts,
    resolve_brand,
)


class TestChartsLoaded(unittest.TestCase):
    def test_all_four_brands_present(self):
        charts = load_brand_charts()
        self.assertEqual(
            set(charts), {"nike", "adidas", "new-balance", "asics"}
        )

    def test_each_chart_has_source_and_rows(self):
        for chart in load_brand_charts().values():
            self.assertTrue(chart.source.startswith("http"), chart.key)
            self.assertGreater(len(chart.men), 10, chart.key)
            self.assertGreater(len(chart.women), 10, chart.key)

    def test_rows_sorted_and_consistent(self):
        for chart in load_brand_charts().values():
            for gender in ("men", "women"):
                eus = [r["eu"] for r in chart.rows(gender) if "eu" in r]
                self.assertEqual(eus, sorted(eus), f"{chart.key}/{gender}")


class TestResolveBrand(unittest.TestCase):
    def test_exact_names(self):
        self.assertEqual(resolve_brand("Nike").key, "nike")
        self.assertEqual(resolve_brand("ASICS").key, "asics")

    def test_adidas_originals_maps_to_adidas(self):
        self.assertEqual(resolve_brand("Adidas Originals").key, "adidas")

    def test_jordan_uses_nike_grid(self):
        self.assertEqual(resolve_brand("Jordan").key, "nike")

    def test_new_balance_variants(self):
        self.assertEqual(resolve_brand("New Balance").key, "new-balance")
        self.assertEqual(resolve_brand("new-balance").key, "new-balance")

    def test_unknown_brand_is_none(self):
        self.assertIsNone(resolve_brand("Puma"))
        self.assertIsNone(resolve_brand(None))


class TestOfficialConversion(unittest.TestCase):
    """Ключевые точки сверены с сайтами производителей."""

    def test_nike_us_men_13(self):
        result = convert_to_eu(US_MEN, 13.0, None, brand="Nike")
        self.assertEqual(result.eu, 47.5)
        self.assertEqual(result.source, "brand")
        self.assertTrue(result.exact)

    def test_adidas_us_men_13_differs_from_nike(self):
        adidas = convert_to_eu(US_MEN, 13.0, None, brand="Adidas")
        nike = convert_to_eu(US_MEN, 13.0, None, brand="Nike")
        self.assertEqual(adidas.eu, 48.0)
        self.assertNotEqual(adidas.eu, nike.eu)

    def test_asics_us_men_9(self):
        self.assertEqual(convert_to_eu(US_MEN, 9.0, None, brand="ASICS").eu, 42.5)

    def test_new_balance_us_men_9(self):
        self.assertEqual(
            convert_to_eu(US_MEN, 9.0, None, brand="New Balance").eu, 42.5
        )

    def test_adidas_thirds_preserved(self):
        # У Adidas сетка с шагом ⅓ — EU 42⅔ для US 9.
        result = convert_to_eu(US_MEN, 9.0, None, brand="Adidas")
        self.assertAlmostEqual(result.eu, 42 + 2 / 3, places=3)

    def test_women_grid_used_for_us_women(self):
        result = convert_to_eu(US_WOMEN, 9.0, None, brand="Nike")
        self.assertEqual(result.eu, 40.5)

    def test_men_and_women_differ_for_same_number(self):
        men = convert_to_eu(US_MEN, 9.0, None, brand="Nike").eu
        women = convert_to_eu(US_WOMEN, 9.0, None, brand="Nike").eu
        self.assertNotEqual(men, women)

    def test_uk_conversion(self):
        self.assertEqual(convert_to_eu(UK, 8.0, None, brand="ASICS").eu, 42.5)

    def test_foot_length_uses_measured_column(self):
        # 26,2 см — это замер стопы для Nike US 9 (ярлык у него 27 см).
        self.assertEqual(convert_to_eu(CM, 26.2, None, brand="Nike").eu, 42.5)

    def test_label_cm_is_not_confused_with_foot(self):
        # 27 см как ЗАМЕР — это уже US 10, а не US 9.
        self.assertEqual(convert_to_eu(CM, 27.1, None, brand="Nike").eu, 44.0)

    def test_brands_agree_on_same_foot_length(self):
        # Одна и та же стопа должна давать сопоставимый размер у всех брендов.
        eus = [
            convert_to_eu(CM, 26.2, None, brand=b).eu
            for b in ("Nike", "Adidas", "New Balance", "ASICS")
        ]
        self.assertTrue(max(eus) - min(eus) <= 0.7, eus)

    def test_brands_without_foot_column_use_brannock(self):
        # У NB и ASICS длины стопы нет — перевод идёт через US.
        result = convert_to_eu(CM, 26.2, None, brand="New Balance")
        self.assertEqual(result.source, "brand")
        self.assertIn("Брэннока", result.note)

    def test_cm_reported_back(self):
        result = convert_to_eu(US_MEN, 9.0, None, brand="Nike")
        self.assertEqual(result.cm, 27.0)

    def test_brand_name_in_result(self):
        self.assertEqual(convert_to_eu(US_MEN, 9.0, None, brand="Nike").brand, "Nike")

    def test_note_mentions_official_table(self):
        note = convert_to_eu(US_MEN, 9.0, None, brand="ASICS").note
        self.assertIn("официальной таблице", note)
        self.assertIn("мужская", note)


class TestFallbacks(unittest.TestCase):
    def test_unknown_brand_falls_back_to_standard(self):
        result = convert_to_eu(US_MEN, 9.0, None, brand="Puma")
        self.assertEqual(result.source, "standard")
        self.assertEqual(result.eu, 42.5)

    def test_eu_passthrough_even_with_brand(self):
        result = convert_to_eu(EU, 42.0, None, brand="Nike")
        self.assertEqual(result.eu, 42.0)

    def test_ru_not_taken_from_brand_table(self):
        # У брендов нет российской шкалы — работает правило POIZON (EU − 1).
        result = convert_to_eu(RU, 41.0, None, brand="Nike")
        self.assertEqual(result.eu, 42.0)
        self.assertNotEqual(result.source, "brand")

    def test_size_outside_grid_falls_back(self):
        result = convert_to_eu(US_MEN, 40.0, None, brand="Nike")
        self.assertNotEqual(result.source, "brand")

    def test_nearest_row_marked_inexact(self):
        # 9,2 нет в сетке — берётся ближайшая строка, но помечается неточной.
        result = convert_to_eu(US_MEN, 9.2, None, brand="Nike")
        self.assertEqual(result.source, "brand")
        self.assertFalse(result.exact)
        self.assertIn("ближайшая", result.note)


if __name__ == "__main__":
    unittest.main()
