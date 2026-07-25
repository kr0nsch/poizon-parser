"""Тесты предфильтра по цене и параллельного обхода карточек."""

import threading
import unittest

from poizon_parser.catalog import _listing_min_price
from poizon_parser.finder import SizeFinder
from poizon_parser.models import Match, Product, SearchItem, SizeOffer


def make_product(spu_id, price, eu="42"):
    return Product(
        spu_id=spu_id,
        title=f"Модель {spu_id}",
        url=f"/product/{spu_id}",
        size_scales=["RU", "EU"],
        default_scale="RU",
        offers=[
            SizeOffer(
                sku_id=spu_id * 10,
                sizes={"RU": str(int(float(eu.replace(",", ".")) - 1)), "EU": eu},
                price=price,
                price_text=f"{price:.0f} ₽",
                in_stock=True,
                delivery="3-5 дней",
            )
        ],
    )


class StubFinder(SizeFinder):
    """Finder без сети: карточки берутся из словаря."""

    def __init__(self, products, fail=()):
        self.products = products
        self.fail = set(fail)
        self.loaded = []
        self._lock = threading.Lock()
        self.on_progress = lambda message: None

    def load_product(self, item):
        from poizon_parser.client import PoizonError

        with self._lock:
            self.loaded.append(item.spu_id)
        if item.spu_id in self.fail:
            # Строка "boom!" → UnicodeEncodeError, если не PoizonError.
            if self.fail_kind == "unicode":
                "boom".encode("ascii")  # ok
                raise UnicodeEncodeError("ascii", "ы", 0, 1, "not ascii")
            raise PoizonError("bad card")
        return self.products[item.spu_id]

    fail_kind = "poizon"


ITEMS = [
    SearchItem(spu_id=1, title="A", url="/product/1", min_price=5000.0),
    SearchItem(spu_id=2, title="B", url="/product/2", min_price=20000.0),
    SearchItem(spu_id=3, title="C", url="/product/3", min_price=None),
]
PRODUCTS = {
    1: make_product(1, 5500.0),
    2: make_product(2, 21000.0),
    3: make_product(3, 7000.0),
}


class TestListingMinPrice(unittest.TestCase):
    def test_amount_parsed(self):
        raw = {"minSpuPrice": {"money": {"amount": "6700.00"}}}
        self.assertEqual(_listing_min_price(raw), 6700.0)

    def test_minor_units_fallback(self):
        raw = {"minSpuPrice": {"money": {"minUnitVal": 680000}}}
        self.assertEqual(_listing_min_price(raw), 6800.0)

    def test_missing_is_none(self):
        self.assertIsNone(_listing_min_price({}))


class TestScanProducts(unittest.TestCase):
    def test_finds_matching_sizes(self):
        finder = StubFinder(PRODUCTS)
        matches = finder.scan_products(ITEMS, 42.0, "EU")
        self.assertEqual({m.product.spu_id for m in matches}, {1, 2, 3})

    def test_max_price_filter_applied(self):
        finder = StubFinder(PRODUCTS)
        matches = finder.scan_products(ITEMS, 42.0, "EU", max_price=10000.0)
        self.assertEqual({m.product.spu_id for m in matches}, {1, 3})

    def test_limit_respected(self):
        finder = StubFinder(PRODUCTS)
        matches = finder.scan_products(ITEMS, 42.0, "EU", limit=1)
        self.assertEqual(len(matches), 1)

    def test_broken_card_skipped(self):
        finder = StubFinder(PRODUCTS, fail={2})
        matches = finder.scan_products(ITEMS, 42.0, "EU")
        self.assertEqual({m.product.spu_id for m in matches}, {1, 3})

    def test_unexpected_error_on_card_does_not_crash_scan(self):
        # Регрессия: UnicodeEncodeError (или любая не-PoizonError) на одной
        # карточке роняла весь поиск. Теперь такая карточка просто пропускается.
        finder = StubFinder(PRODUCTS, fail={2})
        finder.fail_kind = "unicode"
        matches = finder.scan_products(ITEMS, 42.0, "EU")
        self.assertEqual({m.product.spu_id for m in matches}, {1, 3})

    def test_unexpected_error_parallel_does_not_crash(self):
        finder = StubFinder(PRODUCTS, fail={2})
        finder.fail_kind = "unicode"
        matches = finder.scan_products(ITEMS, 42.0, "EU", workers=3)
        self.assertEqual({m.product.spu_id for m in matches}, {1, 3})

    def test_should_stop_halts_scan(self):
        finder = StubFinder(PRODUCTS)
        matches = finder.scan_products(ITEMS, 42.0, "EU", should_stop=lambda: True)
        self.assertEqual(matches, [])

    def test_on_match_callback_fires(self):
        finder = StubFinder(PRODUCTS)
        seen = []
        finder.scan_products(ITEMS, 42.0, "EU", on_match=seen.append)
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(isinstance(m, Match) for m in seen))

    def test_missing_size_not_matched(self):
        finder = StubFinder(PRODUCTS)
        matches = finder.scan_products(ITEMS, 48.0, "EU")
        self.assertEqual(matches, [])

    def test_progress_reported_once_per_card(self):
        """Счётчик прогресса не должен терять отфильтрованные по цене."""
        finder = StubFinder(PRODUCTS)
        seen = []
        finder.on_progress = seen.append
        finder.scan_products(ITEMS, 42.0, "EU", max_price=10000.0)
        self.assertEqual(len(seen), len(ITEMS))

    def test_progress_counts_all_when_parallel(self):
        finder = StubFinder(PRODUCTS)
        seen = []
        lock = threading.Lock()
        finder.on_progress = lambda m: (lock.acquire(), seen.append(m), lock.release())
        finder.scan_products(ITEMS, 42.0, "EU", max_price=10000.0, workers=3)
        self.assertEqual(len(seen), len(ITEMS))


class TestParallelScan(unittest.TestCase):
    def test_parallel_gives_same_result_set(self):
        finder = StubFinder(PRODUCTS)
        matches = finder.scan_products(ITEMS, 42.0, "EU", workers=3)
        self.assertEqual({m.product.spu_id for m in matches}, {1, 2, 3})

    def test_every_card_loaded_once(self):
        finder = StubFinder(PRODUCTS)
        finder.scan_products(ITEMS, 42.0, "EU", workers=3)
        self.assertEqual(sorted(finder.loaded), [1, 2, 3])

    def test_parallel_respects_price_filter(self):
        finder = StubFinder(PRODUCTS)
        matches = finder.scan_products(
            ITEMS, 42.0, "EU", workers=3, max_price=10000.0
        )
        self.assertEqual({m.product.spu_id for m in matches}, {1, 3})


if __name__ == "__main__":
    unittest.main()
