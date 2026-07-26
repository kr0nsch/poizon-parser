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
    resolve_official_chart,
    sizes_for_foot,
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
            self.assertEqual(chart.verified_at, "2026-07-26", chart.key)
            self.assertTrue(chart.locale, chart.key)
            self.assertEqual(set(chart.sources), {"men", "women"}, chart.key)
            self.assertGreater(len(chart.men), 10, chart.key)
            self.assertGreater(len(chart.women), 10, chart.key)
            self.assertTrue(chart.has_foot_column("men"), chart.key)
            self.assertTrue(chart.has_foot_column("women"), chart.key)

    def test_rows_sorted_and_consistent(self):
        for chart in load_brand_charts().values():
            for gender in ("men", "women"):
                eus = [r["eu"] for r in chart.rows(gender) if "eu" in r]
                self.assertEqual(eus, sorted(eus), f"{chart.key}/{gender}")
                feet = [r["foot"] for r in chart.rows(gender) if "foot" in r]
                self.assertEqual(
                    feet, sorted(feet), f"{chart.key}/{gender}/foot"
                )

    def test_hardcoded_snapshot_row_counts(self):
        charts = load_brand_charts()
        expected = {
            "nike": (38, 39),
            "adidas": (28, 28),
            "new-balance": (30, 25),
            "asics": (24, 19),
        }
        for key, counts in expected.items():
            self.assertEqual(
                (len(charts[key].men), len(charts[key].women)),
                counts,
                key,
            )


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

    def test_substrings_do_not_impersonate_official_brands(self):
        for name in ("NBA", "ANBOLUOLI", "MACHENIKE"):
            with self.subTest(name=name):
                self.assertIsNone(resolve_brand(name))

    def test_official_catalog_marker_uses_only_exact_aliases(self):
        self.assertEqual(resolve_official_chart("Nike").key, "nike")
        self.assertEqual(
            resolve_official_chart("Adidas Originals").key, "adidas"
        )
        self.assertEqual(resolve_official_chart("Adidas Neo").key, "adidas")
        self.assertEqual(resolve_official_chart("Adidas TERREX").key, "adidas")
        self.assertIsNone(resolve_official_chart("MACHENIKE"))
        self.assertIsNone(resolve_official_chart("ANBOLUOLI"))
        self.assertIsNone(resolve_official_chart("NBA"))


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

    def test_same_foot_uses_each_official_brand_grid(self):
        expected = {
            "Nike": 43.0,
            "Adidas": 43.3333,
            "New Balance": 42.0,
            "ASICS": 42.0,
        }
        for brand, eu in expected.items():
            with self.subTest(brand=brand):
                self.assertAlmostEqual(
                    convert_to_eu(CM, 26.5, None, brand=brand).eu,
                    eu,
                    places=3,
                )

    def test_new_balance_uses_published_length_for_each_grid(self):
        men = sizes_for_foot("New Balance", 26.5, "men")
        women = sizes_for_foot("New Balance", 26.5, "women")

        self.assertEqual(
            (men["eu"], men["us"], men["uk"], men["foot"]),
            (42.0, 8.5, 8.0, 26.5),
        )
        self.assertEqual(
            (women["eu"], women["us"], women["uk"], women["foot"]),
            (41.0, 9.5, 7.5, 26.5),
        )
        self.assertTrue(men["exact"])
        self.assertTrue(women["exact"])

    def test_new_balance_rounds_between_rows_up(self):
        result = sizes_for_foot("New Balance", 26.2, "men")
        conversion = convert_to_eu(
            CM,
            26.2,
            None,
            brand="New Balance",
        )

        self.assertEqual((result["eu"], result["foot"]), (42.0, 26.5))
        self.assertFalse(result["exact"])
        self.assertFalse(conversion.exact)
        self.assertIn("ближайшая длина стопы 26,5 см", conversion.note)

    def test_asics_uses_its_own_published_cm_rows(self):
        men = sizes_for_foot("ASICS", 26.5, "men")
        women = sizes_for_foot("ASICS", 26.5, "women")

        self.assertEqual(
            (men["eu"], men["us"], men["uk"], men["foot"]),
            (42.0, 8.5, 7.5, 26.5),
        )
        self.assertEqual(
            (women["eu"], women["us"], women["uk"], women["foot"]),
            (42.0, 10.0, 8.0, 26.5),
        )
        self.assertTrue(men["exact"])
        self.assertTrue(women["exact"])

    def test_asics_full_official_endpoints_are_present(self):
        charts = load_brand_charts()
        men = charts["asics"].men[-1]
        women = charts["asics"].women[-1]
        self.assertEqual(
            (men["us"], men["uk"], men["eu"], men["foot"]),
            (18.0, 17.0, 54.0, 34.5),
        )
        self.assertEqual(
            (women["us"], women["uk"], women["eu"], women["foot"]),
            (14.0, 12.0, 47.0, 30.0),
        )

    def test_sparse_upper_rows_still_round_up_inside_official_range(self):
        cases = (
            ("Adidas", 32.7, 33.5),
            ("New Balance", 32.1, 33.0),
            ("ASICS", 31.1, 32.0),
        )
        for brand, requested, expected_foot in cases:
            with self.subTest(brand=brand):
                result = sizes_for_foot(brand, requested, "men")
                self.assertEqual(result["foot"], expected_foot)
                self.assertFalse(result["exact"])

    def test_nike_women_uses_separate_official_table(self):
        result = sizes_for_foot("Nike", 24.1, "women")
        self.assertEqual(
            (result["us"], result["uk"], result["eu"], result["foot"]),
            (7.5, 5.0, 38.5, 24.1),
        )
        self.assertTrue(result["exact"])

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

    def test_size_outside_official_grid_never_uses_another_grid(self):
        result = convert_to_eu(US_MEN, 40.0, None, brand="Nike")
        self.assertEqual(result.source, "brand")
        self.assertFalse(result.supported)
        self.assertIn("вне официальной таблицы Nike", result.note)

    def test_out_of_range_us_women_names_women_grid(self):
        result = convert_to_eu(US_WOMEN, 99.0, None, brand="Nike")
        self.assertFalse(result.supported)
        self.assertIn("женская сетка", result.note)

    def test_millimetres_are_normalized_before_official_lookup(self):
        result = convert_to_eu("MM", 265.0, None, brand="ASICS")
        self.assertTrue(result.supported)
        self.assertTrue(result.exact)
        self.assertEqual((result.eu, result.foot), (42.0, 26.5))

    def test_nearest_row_marked_inexact(self):
        # 9,2 нет в сетке — берётся ближайшая строка, но помечается неточной.
        result = convert_to_eu(US_MEN, 9.2, None, brand="Nike")
        self.assertEqual(result.source, "brand")
        self.assertFalse(result.exact)
        self.assertIn("ближайшая", result.note)


if __name__ == "__main__":
    unittest.main()
