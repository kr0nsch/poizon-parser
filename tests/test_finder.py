"""Тесты подбора размера и подписи запросов."""

import unittest

from poizon_parser.client import (
    Cancelled,
    ChallengeRequired,
    PoizonError,
    calc_sign,
)
from poizon_parser.finder import SizeFinder
from poizon_parser.models import Product, SearchItem, SizeOffer
from poizon_parser.sizechart import CM, US_MEN


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


#: Ряд Adidas на POIZON: EU подписан третями, RU = EU − 1.
ADIDAS_EU = ("42", "42⅔", "43⅓", "44")
ADIDAS_RU = ("41", "41⅔", "42⅓", "43")


def make_adidas_product():
    return Product(
        spu_id=2,
        title="Adidas Samba OG",
        url="/product/2",
        brand="Adidas",
        size_scales=["RU", "EU"],
        default_scale="RU",
        offers=[
            SizeOffer(sku_id=100 + index, sizes={"RU": ru, "EU": eu},
                      price=9000.0 + index * 100, price_text="", in_stock=True)
            for index, (ru, eu) in enumerate(zip(ADIDAS_RU, ADIDAS_EU))
        ],
    )


class TestAdidasFractionalSizes(unittest.TestCase):
    """Точный перевод по таблице Adidas находит SKU с ярлыком-дробью.

    Таблица хранит треть округлённой (42⅔ → 42.6667), ярлык «42⅔» разбирается
    в 42.666…; раньше точное сравнение до 1e-9 отбрасывало такой SKU.
    """

    def setUp(self):
        self.finder = SizeFinder.__new__(SizeFinder)  # без сетевого клиента
        self.product = make_adidas_product()

    def assert_found(self, match, eu_label):
        self.assertIsNotNone(match)
        self.assertTrue(match.exact_conversion)
        self.assertEqual(match.conversion_source, "brand")
        self.assertEqual(match.matched_scale, "EU")
        self.assertEqual(match.offer.sizes["EU"], eu_label)

    def test_us_men_9_finds_two_thirds(self):
        match = self.finder.match_by_scale(self.product, 9.0, US_MEN)
        self.assert_found(match, "42⅔")

    def test_foot_length_finds_two_thirds(self):
        match = self.finder.match_by_scale(self.product, 26.3, CM)
        self.assert_found(match, "42⅔")

    def test_foot_length_finds_one_third(self):
        match = self.finder.match_by_scale(self.product, 26.7, CM)
        self.assert_found(match, "43⅓")

    def test_us_men_8_5_finds_whole_size(self):
        match = self.finder.match_by_scale(self.product, 8.5, US_MEN)
        self.assert_found(match, "42")


class StubSearchFinder(SizeFinder):
    """find() / find_in_products() без сети: карточки по spuId."""

    def __init__(self, errors):
        self.errors = errors
        self.loaded = []
        self.progress = []
        self.on_progress = self.progress.append

    def search_items(self, query, limit=20):
        return [
            SearchItem(spu_id=spu_id, title=f"Модель {spu_id}",
                       url=f"/product/{spu_id}")
            for spu_id in (1, 2, 3)
        ]

    def load_product(self, item):
        spu_id = item.spu_id if isinstance(item, SearchItem) else int(item)
        self.loaded.append(spu_id)
        error = self.errors.get(spu_id)
        if error is not None:
            raise error
        product = make_product("RU")
        product.spu_id = spu_id
        return product


class TestChallengeStopsSearch(unittest.TestCase):
    """Капча и отмена обрывают обход, а не превращаются в «пропуск карточки»."""

    def test_find_propagates_challenge(self):
        finder = StubSearchFinder({1: ChallengeRequired("https://x", "captcha")})
        with self.assertRaises(ChallengeRequired):
            finder.find("adidas", "42")
        # Следующие карточки к заблокированному сайту не запрашиваются.
        self.assertEqual(finder.loaded, [1])

    def test_find_challenge_keeps_found_before_it(self):
        finder = StubSearchFinder({3: ChallengeRequired("https://x", "captcha")})
        with self.assertRaises(ChallengeRequired) as ctx:
            finder.find("adidas", "42")
        self.assertEqual([m.product.spu_id for m in ctx.exception.partial], [1, 2])

    def test_find_propagates_cancel(self):
        finder = StubSearchFinder({2: Cancelled()})
        with self.assertRaises(Cancelled):
            finder.find("adidas", "42")
        self.assertEqual(finder.loaded, [1, 2])

    def test_find_still_skips_broken_card(self):
        finder = StubSearchFinder({1: PoizonError("битая карточка")})
        matches = finder.find("adidas", "42")
        self.assertEqual([m.product.spu_id for m in matches], [2, 3])
        self.assertTrue(any("пропуск 1" in line for line in finder.progress))

    def test_find_in_products_propagates_challenge(self):
        finder = StubSearchFinder({1: ChallengeRequired("https://x", "captcha")})
        with self.assertRaises(ChallengeRequired):
            finder.find_in_products([1, 2, 3], "42")
        self.assertEqual(finder.loaded, [1])

    def test_find_in_products_propagates_cancel(self):
        finder = StubSearchFinder({1: Cancelled()})
        with self.assertRaises(Cancelled):
            finder.find_in_products([1, 2], "42")

    def test_find_in_products_still_skips_broken_card(self):
        finder = StubSearchFinder({2: PoizonError("битая карточка")})
        matches = finder.find_in_products([1, 2, 3], "42")
        self.assertEqual([m.product.spu_id for m in matches], [1, 3])


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
