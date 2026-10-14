"""Тесты официальных размерных таблиц брендов."""

import unittest

from poizon_parser.sizechart import (
    CM,
    EU,
    RU,
    UK,
    US_MEN,
    US_WOMEN,
    SizeChart,
    convert_to_eu,
    load_brand_charts,
    resolve_brand,
    resolve_official_chart,
    sizes_for_foot,
)
from poizon_parser.sizes import match_size, parse_size


#: Бренды, публикующие собственный замер стопы, — только они годятся для
#: подбора размера по длине стопы.
FOOT_BRANDS = {"nike", "adidas", "new-balance", "asics", "reebok"}


class TestChartsLoaded(unittest.TestCase):
    def test_all_brands_present(self):
        charts = load_brand_charts()
        self.assertEqual(
            set(charts),
            {"nike", "adidas", "new-balance", "asics", "reebok", "puma"},
        )

    def test_each_chart_has_source_and_rows(self):
        for chart in load_brand_charts().values():
            self.assertTrue(chart.source.startswith("http"), chart.key)
            self.assertRegex(chart.verified_at, r"^\d{4}-\d{2}-\d{2}$", chart.key)
            self.assertTrue(chart.locale, chart.key)
            self.assertLessEqual({"men", "women"}, set(chart.sources), chart.key)
            self.assertGreater(len(chart.men), 10, chart.key)
            self.assertGreater(len(chart.women), 10, chart.key)

    def test_foot_column_present_exactly_where_brand_publishes_it(self):
        for chart in load_brand_charts().values():
            expected = chart.key in FOOT_BRANDS
            for gender in ("men", "women"):
                with self.subTest(brand=chart.key, gender=gender):
                    self.assertEqual(chart.has_foot_column(gender), expected)

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
            "reebok": (26, 22),
            "puma": (22, 12),
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
        self.assertIsNone(resolve_brand("Vans"))
        self.assertIsNone(resolve_brand(None))

    def test_reebok_and_puma_resolve(self):
        self.assertEqual(resolve_brand("Reebok").key, "reebok")
        self.assertEqual(resolve_brand("Puma").key, "puma")

    def test_brand_without_foot_column_is_not_offered_for_measurement(self):
        # Каталог помечает бренд официальным только если по нему можно
        # подобрать размер по замеру стопы; у Puma такой колонки нет.
        self.assertIsNone(resolve_official_chart("Puma"))
        self.assertEqual(resolve_official_chart("Reebok").key, "reebok")

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
        # Округлённая треть таблицы и ярлык SKU «42⅔» — один размер.
        self.assertIsNotNone(
            match_size({"EU": "42⅔"}, result.eu, scale="EU")
        )

    def test_adidas_fraction_label_is_exact_row(self):
        # EU «42⅔» с ярлыка — это строка 42.6667, а не «ближайшая строка».
        result = convert_to_eu(EU, parse_size("42⅔"), None, brand="Adidas")
        self.assertTrue(result.exact)
        self.assertNotIn("ближайшая", result.note)
        self.assertEqual(result.foot, 26.3)

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

    def test_reebok_us_men_9(self):
        # Официальная сетка Reebok: US 9 = UK 8 = EU 42.
        result = convert_to_eu(US_MEN, 9.0, None, brand="Reebok")
        self.assertEqual((result.eu, result.source), (42.0, "brand"))
        self.assertTrue(result.exact)

    def test_reebok_differs_from_nike_on_same_us(self):
        reebok = convert_to_eu(US_MEN, 9.0, None, brand="Reebok").eu
        nike = convert_to_eu(US_MEN, 9.0, None, brand="Nike").eu
        self.assertEqual((reebok, nike), (42.0, 42.5))

    def test_reebok_foot_from_official_heel_toe(self):
        # 10,3 дюйма официальной таблицы = 26,2 см → US 9.
        result = sizes_for_foot("Reebok", 26.2, "men")
        self.assertEqual(
            (result["eu"], result["us"], result["uk"], result["foot"]),
            (42.0, 9.0, 8.0, 26.2),
        )
        self.assertTrue(result["exact"])

    def test_reebok_women_uses_separate_official_table(self):
        result = sizes_for_foot("Reebok", 24.1, "women")
        self.assertEqual(
            (result["eu"], result["us"], result["uk"]), (38.5, 8.0, 5.5)
        )
        self.assertTrue(result["exact"])

    def test_puma_us_men_9(self):
        result = convert_to_eu(US_MEN, 9.0, None, brand="Puma")
        self.assertEqual((result.eu, result.source), (42.0, "brand"))
        self.assertTrue(result.exact)

    def test_puma_us_women_and_uk(self):
        self.assertEqual(convert_to_eu(US_WOMEN, 8.0, None, brand="Puma").eu, 38.5)
        self.assertEqual(convert_to_eu(UK, 8.0, None, brand="Puma").eu, 42.0)

    def test_puma_cm_label_is_never_used_as_foot_length(self):
        # Ярлык «27 см» у Puma стоит на паре под замер ~26,2 см. Считать его
        # длиной стопы нельзя, поэтому перевод уходит на общую сетку.
        result = convert_to_eu(CM, 26.5, None, brand="Puma")
        self.assertEqual(result.source, "standard")
        self.assertTrue(result.supported)
        self.assertNotEqual(result.brand, "Puma")

    def test_puma_cm_label_reported_for_us_size(self):
        self.assertEqual(convert_to_eu(US_MEN, 9.0, None, brand="Puma").cm, 27.0)
        self.assertIsNone(convert_to_eu(US_MEN, 9.0, None, brand="Puma").foot)

    def test_same_foot_uses_each_official_brand_grid(self):
        expected = {
            "Nike": 43.0,
            "Adidas": 43.3333,
            "New Balance": 42.0,
            "ASICS": 42.0,
            "Reebok": 42.5,
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
        result = convert_to_eu(US_MEN, 9.0, None, brand="Vans")
        self.assertEqual(result.source, "standard")
        self.assertEqual(result.eu, 42.5)

    def test_unpublished_scale_falls_back_instead_of_refusing(self):
        # Шкалы нет в таблице бренда — это не «размера не существует».
        result = convert_to_eu(CM, 26.2, None, brand="Puma")
        self.assertTrue(result.supported)
        self.assertEqual(result.source, "standard")

    def test_foot_without_official_column_lands_in_official_range(self):
        # Регрессия: замер искался в сантиметрах ярлыка, и стопа 26,5 см у
        # Puma, Vans и брендов без таблицы выходила EU 41, хотя все
        # официальные таблицы дают ей EU 42–43⅓.
        official = [
            convert_to_eu(CM, 26.5, None, brand=name).eu
            for name in ("Nike", "Adidas", "New Balance", "ASICS", "Reebok")
        ]
        low, high = min(official), max(official)
        self.assertEqual((low, round(high, 2)), (42.0, 43.33))
        for brand in ("Puma", "Vans", None):
            with self.subTest(brand=brand):
                result = convert_to_eu(CM, 26.5, None, brand=brand)
                self.assertTrue(low <= result.eu <= high, result.eu)
                self.assertFalse(result.exact)  # в выдаче — «≈»
                self.assertTrue(result.supported)
                self.assertEqual(result.brand, "")  # чужая сетка не названа

    def test_foot_reference_ignores_product_label_column(self):
        # «Длина стопы» карточки — ярлык (у Nike 27 см стоит на EU 42):
        # с таблицей товара стопа 27 см не должна снова съехать в EU 42.
        label_rows = SizeChart(rows=[
            {EU: 41.0, CM: 26.5}, {EU: 42.0, CM: 27.0}, {EU: 42.5, CM: 27.5},
        ])
        for brand in ("Puma", "Vans"):
            with self.subTest(brand=brand):
                result = convert_to_eu(CM, 27.0, label_rows, brand=brand)
                self.assertEqual((result.eu, result.source), (43.0, "standard"))

    def test_foot_reference_follows_gender(self):
        men = convert_to_eu(CM, 29.5, None, brand="Puma", gender="men")
        women = convert_to_eu(CM, 32.5, None, brand="Puma", gender="women")
        self.assertEqual(men.source, "standard")
        # Женские таблицы с замером стопы кончаются раньше мужских.
        self.assertEqual(women.source, "fallback")
        self.assertTrue(women.supported)

    def test_official_foot_conversions_unchanged(self):
        # Общая сетка не трогает бренды с собственным замером стопы.
        for brand in ("Nike", "Adidas", "New Balance", "ASICS", "Reebok"):
            with self.subTest(brand=brand):
                result = convert_to_eu(CM, 26.5, None, brand=brand)
                self.assertEqual(result.source, "brand")
                self.assertEqual(result.brand, brand)

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
