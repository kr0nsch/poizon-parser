"""Тесты подбора размера и подписи запросов."""

import unittest

from poizon_parser.client import calc_sign
from poizon_parser.finder import SizeFinder
from poizon_parser.models import Product, SizeOffer


def make_product(default_scale="RU"):
    """Модель, где RU 42 дороже, чем EU 42 (то есть RU 41)."""
    return Product(
        spu_id=1,
        title="Тестовые кроссовки",
        url="/product/1",
        size_scales=["RU", "EU"],
        default_scale=default_scale,
        offers=[
            SizeOffer(sku_id=10, sizes={"RU": "41", "EU": "42"}, price=10550.0,
                      price_text="10 550 ₽", in_stock=True),
            SizeOffer(sku_id=11, sizes={"RU": "42", "EU": "43"}, price=11700.0,
                      price_text="11 700 ₽", in_stock=True),
        ],
    )


class TestScaleConsistency(unittest.TestCase):
    """Шкалы нельзя смешивать: «42 RU» и «42 EU» — разная обувь."""

    def setUp(self):
        self.finder = SizeFinder.__new__(SizeFinder)  # без сетевого клиента

    def test_prefers_default_scale_even_if_pricier(self):
        match = self.finder.match_product(make_product("RU"), 42.0)
        self.assertEqual(match.matched_scale, "RU")
        self.assertEqual(match.offer.price, 11700.0)

    def test_explicit_scale_is_respected(self):
        match = self.finder.match_product(make_product("RU"), 42.0, scale="EU")
        self.assertEqual(match.matched_scale, "EU")
        self.assertEqual(match.offer.sizes["RU"], "41")

    def test_falls_back_to_other_scale_when_absent(self):
        product = make_product("RU")
        product.offers = [
            SizeOffer(sku_id=12, sizes={"RU": "41", "EU": "42"}, price=9000.0, in_stock=True)
        ]
        match = self.finder.match_product(product, 42.0)
        self.assertEqual(match.matched_scale, "EU")

    def test_no_match_returns_none(self):
        self.assertIsNone(self.finder.match_product(make_product(), 55.0))

    def test_cheaper_wins_within_same_scale(self):
        # Одинаковый размер в разной полноте — тут выбор по цене корректен.
        product = make_product("RU")
        product.offers = [
            SizeOffer(sku_id=20, sizes={"RU": "42"}, price=17251.0, in_stock=True,
                      variant={"Полнота": "Узкая (B)"}),
            SizeOffer(sku_id=21, sizes={"RU": "42"}, price=7650.0, in_stock=True,
                      variant={"Полнота": "Стандартная (D)"}),
        ]
        match = self.finder.match_product(product, 42.0)
        self.assertEqual(match.offer.price, 7650.0)

    def test_out_of_stock_skipped_by_default(self):
        product = make_product("RU")
        product.offers = [
            SizeOffer(sku_id=0, sizes={"RU": "42"}, price=None, in_stock=False)
        ]
        self.assertIsNone(self.finder.match_product(product, 42.0))
        match = self.finder.match_product(product, 42.0, only_in_stock=False)
        self.assertIsNotNone(match)

    def test_tolerance_finds_neighbour(self):
        product = make_product("RU")
        product.offers = [
            SizeOffer(sku_id=30, sizes={"RU": "42,5"}, price=8000.0, in_stock=True)
        ]
        self.assertIsNone(self.finder.match_product(product, 42.0))
        match = self.finder.match_product(product, 42.0, tolerance=0.5)
        self.assertEqual(match.offer.sizes["RU"], "42,5")

    def test_closest_size_wins_with_tolerance(self):
        product = make_product("RU")
        product.offers = [
            SizeOffer(sku_id=40, sizes={"RU": "42,5"}, price=5000.0, in_stock=True),
            SizeOffer(sku_id=41, sizes={"RU": "42"}, price=9000.0, in_stock=True),
        ]
        match = self.finder.match_product(product, 42.0, tolerance=0.5)
        # Точное совпадение важнее низкой цены.
        self.assertEqual(match.offer.sizes["RU"], "42")


class TestCalcSign(unittest.TestCase):
    def test_empty_body_matches_observed_value(self):
        # Значение подсмотрено в реальных запросах сайта.
        self.assertEqual(calc_sign(None), "fe26befc49444d362c8f17463630bdba")
        self.assertEqual(calc_sign({}), "fe26befc49444d362c8f17463630bdba")

    def test_sign_is_stable(self):
        body = {"pageNum": 1, "pageSize": 20, "scene": 1, "keywords": "vans slip on"}
        self.assertEqual(calc_sign(body), "e4c83fcda5a0c606959b6fd9cccef71e")

    def test_key_order_does_not_matter(self):
        self.assertEqual(
            calc_sign({"b": 2, "a": 1}), calc_sign({"a": 1, "b": 2})
        )

    def test_different_body_different_sign(self):
        self.assertNotEqual(calc_sign({"spuId": 1}), calc_sign({"spuId": 2}))

    def test_none_values_skipped(self):
        self.assertEqual(calc_sign({"a": 1, "b": None}), calc_sign({"a": 1}))


if __name__ == "__main__":
    unittest.main()
