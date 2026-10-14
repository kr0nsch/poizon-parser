"""Тесты перевода размерных шкал."""

import json
import unittest
from pathlib import Path

from poizon_parser.extract import parse_product
from poizon_parser.sizechart import (
    CM,
    EU,
    MM,
    RU,
    US_MEN,
    US_WOMEN,
    SizeChart,
    convert_to_eu,
    normalize_scale,
    resolve_query_scale,
)
from poizon_parser.sizes import parse_size, parse_size_query

FIXTURE = Path(__file__).parent / "fixtures" / "product_nb530.json"

# Опорные строки в том виде, в каком их отдаёт сайт для Nike.
NIKE_GOODS = {
    "sizeAssistantModule": {
        "size": {
            "sizeList": [
                {"title": "inch", "sizeKeyList": [
                    {"sizeKey": "EU", "sizeValueList": ["35,5", "36", "36,5"]},
                ], "sizeParameterList": [
                    {"sizeKey": "Длина стопы", "sizeValueList": ["8,9", "9,1", "9,3"]},
                ]},
                {"title": "cm", "sizeKeyList": [
                    {"sizeKey": "EU", "sizeValueList": ["35,5", "36", "36,5"]},
                    {"sizeKey": "RU", "sizeValueList": ["34,5", "35", "35,5"]},
                    {"sizeKey": "UK", "sizeValueList": ["3", "3,5", "4"]},
                    {"sizeKey": "US Мужские", "sizeValueList": ["3,5", "4", "4,5"]},
                    {"sizeKey": "US Женские", "sizeValueList": ["5", "5,5", "6"]},
                ], "sizeParameterList": [
                    {"sizeKey": "Длина стопы", "sizeValueList": ["22,5", "23", "23,5"]},
                ]},
            ]
        }
    }
}


class TestNormalizeScale(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(normalize_scale("eu"), EU)
        self.assertEqual(normalize_scale("US M"), US_MEN)
        self.assertEqual(normalize_scale("usm"), US_MEN)
        self.assertEqual(normalize_scale("см"), CM)
        self.assertEqual(normalize_scale("евро"), EU)
        self.assertEqual(normalize_scale("us_w"), US_WOMEN)

    def test_unknown_name_is_uppercased(self):
        self.assertEqual(normalize_scale("jp"), "JP")

    def test_none(self):
        self.assertIsNone(normalize_scale(None))


class TestResolveQueryScale(unittest.TestCase):
    """Общее правило: шкала из строки размера против явно выбранной."""

    def resolve(self, size, explicit, default=None):
        parsed, _value = parse_size_query(size)
        return resolve_query_scale(parsed, explicit, default)

    def test_bare_us_does_not_override_gendered_scale(self):
        # Регрессия: -s "US 7" --scale "US W" искал мужской US 7.
        self.assertEqual(self.resolve("US 7", "US W"), US_WOMEN)
        self.assertEqual(self.resolve("US 7", "usw"), US_WOMEN)
        self.assertEqual(self.resolve("US 7", "US M"), US_MEN)

    def test_bare_us_without_gendered_scale_is_men(self):
        self.assertEqual(self.resolve("US 7", CM), US_MEN)
        self.assertEqual(self.resolve("US 7", EU), US_MEN)
        self.assertEqual(self.resolve("US 7", None), US_MEN)

    def test_gendered_or_metric_scale_in_size_wins(self):
        self.assertEqual(self.resolve("US W 7", "US M"), US_WOMEN)
        self.assertEqual(self.resolve("US M 9", "US W"), US_MEN)
        self.assertEqual(self.resolve("MM 265", CM), MM)
        self.assertEqual(self.resolve("EU 43", CM), EU)

    def test_explicit_then_default(self):
        self.assertEqual(self.resolve("42", "eu"), EU)
        self.assertEqual(self.resolve("42", None, default=CM), CM)
        self.assertIsNone(resolve_query_scale(None, None))

    def test_unknown_scale_in_size_is_kept_for_validation(self):
        # Незнакомая шкала не подменяется явной: вызывающий должен её отклонить.
        self.assertEqual(self.resolve("JP 27", CM), "JP")


class TestSizeChartParsing(unittest.TestCase):
    def setUp(self):
        self.chart = SizeChart.from_goods_detail(NIKE_GOODS)

    def test_uses_cm_block_not_inch(self):
        # Длина стопы должна быть в сантиметрах, а не дюймах.
        self.assertEqual(self.chart.rows[0][CM], 22.5)

    def test_rows_parsed(self):
        self.assertEqual(len(self.chart.rows), 3)
        self.assertEqual(self.chart.rows[0][EU], 35.5)
        self.assertEqual(self.chart.rows[0][US_MEN], 3.5)

    def test_missing_module_gives_empty_chart(self):
        self.assertEqual(SizeChart.from_goods_detail({}).rows, [])


class TestConversion(unittest.TestCase):
    def setUp(self):
        self.chart = SizeChart.from_goods_detail(NIKE_GOODS)

    def test_eu_is_passthrough(self):
        result = self.chart.to_eu(EU, 42.0)
        self.assertEqual(result.eu, 42.0)
        self.assertTrue(result.exact)

    def test_ru_is_eu_minus_one(self):
        # Ключевая особенность POIZON: его RU = EU − 1.
        result = self.chart.to_eu(RU, 41.0)
        self.assertEqual(result.eu, 42.0)
        self.assertTrue(result.exact)

    def test_exact_row_hit_is_marked_exact(self):
        result = self.chart.to_eu(US_MEN, 4.0)
        self.assertEqual(result.eu, 36.0)
        self.assertTrue(result.exact)
        self.assertEqual(result.source, "table")

    def test_outside_table_uses_standard_ladder(self):
        # US M 9 по эталонной лестнице Nike = EU 42,5, а НЕ 41 (наивное +32).
        result = self.chart.to_eu(US_MEN, 9.0)
        self.assertEqual(result.eu, 42.5)
        self.assertFalse(result.exact)
        self.assertEqual(result.source, "standard")

    def test_us_men_13_is_eu_475(self):
        # Ключевой случай из обсуждения: US 13 (мужской) — это EU 47,5.
        result = self.chart.to_eu(US_MEN, 13.0)
        self.assertEqual(result.eu, 47.5)

    def test_us_women_13_differs_from_men(self):
        # Женский 13 — другая (меньшая) обувь, чем мужской 13.
        men = self.chart.to_eu(US_MEN, 13.0).eu
        women = self.chart.to_eu(US_WOMEN, 13.0).eu
        self.assertEqual(women, 45.5)
        self.assertNotEqual(men, women)

    def test_cm_conversion(self):
        self.assertEqual(self.chart.to_eu(CM, 23.0).eu, 36.0)

    def test_offset_is_median(self):
        self.assertEqual(self.chart.offset_to_eu(US_MEN), 32.0)


class TestFractionalProductTable(unittest.TestCase):
    """Таблица товара с третями: ярлык «36⅔» против числа 36.6667."""

    def setUp(self):
        goods = json.loads(json.dumps(NIKE_GOODS))
        block = goods["sizeAssistantModule"]["size"]["sizeList"][1]
        for entry in block["sizeKeyList"]:
            if entry["sizeKey"] == "EU":
                entry["sizeValueList"] = ["36", "36⅔", "37⅓"]
            if entry["sizeKey"] == "RU":
                entry["sizeValueList"] = ["35", "35⅔", "36⅓"]
        self.chart = SizeChart.from_goods_detail(goods)

    def test_ru_row_found_despite_rounding(self):
        # Пользователь вводит RU 35,6667 (округлённое) — строка «35⅔» та же.
        result = self.chart.to_eu(RU, 35.6667)
        self.assertEqual(result.source, "table")
        self.assertAlmostEqual(result.eu, parse_size("36⅔"), places=9)

    def test_neighbour_rows_not_merged(self):
        result = self.chart.to_eu(RU, 35.5)
        # Строки 35,5 нет — это не «35⅔», работает правило EU = RU + 1.
        self.assertEqual((result.eu, result.source), (36.5, "native"))


class TestBrandCorrection(unittest.TestCase):
    """Если сетка бренда сдвинута, поправка берётся по опорным строкам."""

    def setUp(self):
        # Сдвигаем EU-колонку на +0,5 относительно эталона.
        goods = json.loads(json.dumps(NIKE_GOODS))
        block = goods["sizeAssistantModule"]["size"]["sizeList"][1]
        for entry in block["sizeKeyList"]:
            if entry["sizeKey"] == "EU":
                entry["sizeValueList"] = ["36", "36,5", "37"]
        self.chart = SizeChart.from_goods_detail(goods)

    def test_correction_detected(self):
        self.assertAlmostEqual(self.chart.ladder_correction(US_MEN), 0.5)

    def test_correction_applied_to_ladder(self):
        # US M 9 по эталону EU 42,5, со сдвигом бренда +0,5 → EU 43.
        result = self.chart.to_eu(US_MEN, 9.0)
        self.assertEqual(result.eu, 43.0)
        self.assertIn("сдвиг", result.note)


class TestFallbackConversion(unittest.TestCase):
    def test_no_chart_uses_standard_ladder(self):
        # Без таблицы товара US M 9 всё равно берётся из эталонной лестницы.
        result = convert_to_eu(US_MEN, 9.0, SizeChart())
        self.assertEqual(result.eu, 42.5)
        self.assertEqual(result.source, "standard")
        self.assertFalse(result.exact)

    def test_huge_size_beyond_ladder_falls_back(self):
        result = convert_to_eu(US_MEN, 30.0, SizeChart())
        self.assertEqual(result.source, "fallback")

    def test_eu_without_chart_is_exact(self):
        result = convert_to_eu(EU, 42.0, None)
        self.assertTrue(result.exact)
        self.assertEqual(result.eu, 42.0)

    def test_ru_without_chart(self):
        self.assertEqual(convert_to_eu(RU, 41.0, None).eu, 42.0)


class TestRealFixture(unittest.TestCase):
    """Сохранённая с сайта карточка New Balance 530."""

    @classmethod
    def setUpClass(cls):
        with FIXTURE.open(encoding="utf-8") as handle:
            cls.data = json.load(handle)
        cls.goods = cls.data["props"]["pageProps"]["goodsDetail"]

    def test_card_without_size_module_gives_empty_chart(self):
        # Сайт отдаёт sizeAssistantModule не у всех товаров: у этой карточки
        # его нет, и таблица должна быть пустой, а не мусорной.
        self.assertNotIn("sizeAssistantModule", self.goods)
        self.assertEqual(SizeChart.from_goods_detail(self.goods).rows, [])

    def test_sku_ru_is_eu_minus_one(self):
        # Правило, на котором держится перевод RU → EU без таблицы товара.
        product = parse_product(self.data)
        self.assertEqual(product.size_scales, ["RU", "EU"])
        self.assertGreater(len(product.offers), 10)
        for offer in product.offers:
            with self.subTest(sizes=offer.sizes):
                self.assertEqual(
                    parse_size(offer.sizes["EU"]) - parse_size(offer.sizes["RU"]),
                    1.0,
                )

    def test_empty_product_table_falls_back_to_brand_table(self):
        product = parse_product(self.data)
        self.assertEqual(product.brand, "New Balance")
        result = convert_to_eu(US_MEN, 9.0, product.chart, brand=product.brand)
        self.assertEqual(
            (result.eu, result.source, result.exact), (42.5, "brand", True)
        )
        # И такой размер в карточке действительно есть.
        self.assertIn("42,5", {offer.sizes["EU"] for offer in product.offers})


if __name__ == "__main__":
    unittest.main()
