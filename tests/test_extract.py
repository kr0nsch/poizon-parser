"""Тесты разбора карточки товара на реальной сохранённой выдаче сайта."""

import json
import unittest
from pathlib import Path

from poizon_parser.extract import find_size_property, parse_product

FIXTURE = Path(__file__).parent / "fixtures" / "product_nb530.json"


class TestParseProduct(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with FIXTURE.open(encoding="utf-8") as handle:
            cls.next_data = json.load(handle)
        cls.product = parse_product(cls.next_data, url="/product/test-8900001978861819")

    def test_basic_fields(self):
        self.assertEqual(self.product.spu_id, 8900001978861819)
        self.assertIn("New Balance", self.product.title)
        self.assertEqual(self.product.brand, "New Balance")

    def test_scales_detected(self):
        self.assertEqual(sorted(self.product.size_scales), ["EU", "RU"])
        self.assertEqual(self.product.default_scale, "RU")

    def test_size_tip_extracted(self):
        self.assertIn("Размер", self.product.size_tip)

    def test_min_price(self):
        self.assertEqual(self.product.min_price, 6700.0)

    def test_offers_present(self):
        self.assertGreater(len(self.product.offers), 15)

    def test_every_offer_has_sizes(self):
        for offer in self.product.offers:
            self.assertTrue(offer.sizes, "у предложения нет размеров")

    def test_in_stock_offers_have_price(self):
        for offer in self.product.in_stock_offers():
            self.assertIsNotNone(offer.price)
            self.assertGreater(offer.price, 0)

    def test_ru_eu_offset(self):
        # На этом сайте шкала RU на единицу меньше EU.
        for offer in self.product.offers:
            ru, eu = offer.sizes.get("RU"), offer.sizes.get("EU")
            if ru and eu:
                self.assertAlmostEqual(
                    float(eu.replace(",", ".")) - float(ru.replace(",", ".")), 1.0
                )

    def test_known_price_for_ru_42(self):
        offers = [o for o in self.product.offers if o.sizes.get("RU") == "42" and o.in_stock]
        self.assertTrue(offers, "размер RU 42 не найден")
        self.assertEqual(offers[0].price, 7050.0)
        self.assertIn("₽", offers[0].price_text)

    def test_out_of_stock_size_included_without_price(self):
        missing = [o for o in self.product.offers if not o.in_stock]
        self.assertTrue(missing, "ожидались размеры без предложений")
        self.assertIsNone(missing[0].price)

    def test_variant_distinguishes_same_size(self):
        # RU 41,5 представлен в двух полнотах — они должны различаться.
        same_size = [o for o in self.product.offers if o.sizes.get("RU") == "41,5"]
        self.assertEqual(len(same_size), 2)
        self.assertNotEqual(same_size[0].variant_label, same_size[1].variant_label)

    def test_offers_sorted_by_size(self):
        values = [
            float(o.sizes["RU"].replace(",", "."))
            for o in self.product.offers
            if o.sizes.get("RU")
        ]
        self.assertEqual(values, sorted(values))

    def test_delivery_captured(self):
        self.assertTrue(any(o.delivery for o in self.product.in_stock_offers()))

    def test_excluding_unavailable(self):
        product = parse_product(self.next_data, include_unavailable=False)
        self.assertTrue(all(o.sku_id for o in product.offers))


class TestFindSizeProperty(unittest.TestCase):
    def test_detects_by_scale_keys(self):
        props = [
            {"level": 1, "name": "Цвет", "propertyMap": {"DEFAULT": [{"propertyValueId": 1, "value": "Белый"}]}},
            {"level": 2, "name": "Размер", "propertyMap": {"RU": [{"propertyValueId": 2, "value": "42"}]}},
        ]
        self.assertEqual(find_size_property(props)["level"], 2)

    def test_detects_by_name_when_no_scales(self):
        props = [
            {"level": 1, "name": "Цвет", "propertyMap": {"DEFAULT": [{"propertyValueId": 1, "value": "Белый"}]}},
            {"level": 2, "name": "Размер", "propertyMap": {"DEFAULT": [{"propertyValueId": 2, "value": "42"}]}},
        ]
        self.assertEqual(find_size_property(props)["name"], "Размер")

    def test_empty_returns_none(self):
        self.assertIsNone(find_size_property([]))


class TestMalformedInput(unittest.TestCase):
    def test_empty_payload_does_not_crash(self):
        product = parse_product({})
        self.assertEqual(product.offers, [])

    def test_missing_sale_properties(self):
        product = parse_product({"props": {"pageProps": {"spuId": 1, "goodsDetail": {}}}})
        self.assertEqual(product.spu_id, 1)
        self.assertEqual(product.offers, [])


if __name__ == "__main__":
    unittest.main()
