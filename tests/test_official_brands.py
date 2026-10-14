"""Обход сразу всех брендов с официальной таблицей размеров."""

import threading
import unittest

from poizon_parser.catalog import Brand
from poizon_parser.finder import SizeFinder
from poizon_parser.models import Product, SearchItem, SizeOffer
from poizon_parser.sizechart import CM, EU, US_MEN, official_charts

#: Размерный ряд карточки: одного EU мало — у каждого бренда он свой.
EU_ROW = (41.0, 41.5, 42.0, 42.5, 43.0, 43.5)


def make_product(spu_id: int, brand: str, price: float) -> Product:
    return Product(
        spu_id=spu_id,
        title=f"{brand} модель {spu_id}",
        url=f"/product/{spu_id}",
        brand=brand,
        size_scales=["RU", "EU"],
        default_scale="RU",
        offers=[
            SizeOffer(
                sku_id=spu_id * 100 + index,
                sizes={"RU": f"{eu - 1:g}", "EU": f"{eu:g}"},
                price=price,
                price_text=f"{price:.0f} ₽",
                in_stock=True,
            )
            for index, eu in enumerate(EU_ROW)
        ],
    )


class FakeCatalog:
    """Каталог сайта без сети: у каждого бренда по одной карточке."""

    def __init__(self, prices: dict[str, float]):
        self.brands = {
            name: Brand(brand_id=index, name=name, url=f"/brand/{name.lower()}")
            for index, name in enumerate(prices, 1)
        }
        self.prices = prices
        self.requested: list[str] = []

    def find_brand(self, query: str):
        self.requested.append(query)
        for name, brand in self.brands.items():
            if name.lower() == str(query).strip().lower():
                return brand
        return None

    def suggest_brands(self, query: str, limit: int = 8):
        return []

    def brand_items(self, brand, max_items=None, include_kids=False):
        return [
            SearchItem(
                spu_id=brand.brand_id,
                title=brand.name,
                url=f"/product/{brand.brand_id}",
            )
        ]


class StubFinder(SizeFinder):
    """Finder без сети: карточка строится из имени бренда."""

    def __init__(self, catalog: FakeCatalog):
        self.catalog = catalog
        self.on_progress = lambda message: None
        self._lock = threading.Lock()

    def load_product(self, item):
        brand = item.title
        return make_product(item.spu_id, brand, self.catalog.prices[brand])


PRICES = {
    "Nike": 12000.0,
    "Adidas": 9000.0,
    "New Balance": 15000.0,
    "ASICS": 7000.0,
    "Reebok": 6000.0,
    "Puma": 5000.0,
}


def run(scale=CM, size="26,2", **kwargs):
    catalog = FakeCatalog(PRICES)
    finder = StubFinder(catalog)
    seen: list[tuple[str, int]] = []
    matches = finder.find_in_official_brands(
        size=size,
        scale=scale,
        catalog=catalog,
        on_brand=lambda name, found: seen.append((name, len(found))),
        **kwargs,
    )
    return catalog, matches, seen


class TestBrandSelection(unittest.TestCase):
    def test_foot_search_skips_brand_without_foot_column(self):
        _catalog, matches, seen = run(scale=CM)
        names = {name for name, _ in seen}
        self.assertEqual(
            names, {"Nike", "Adidas", "New Balance", "ASICS", "Reebok"}
        )
        self.assertNotIn("Puma", names)
        self.assertNotIn("Puma", {m.product.brand for m in matches})

    def test_us_scale_includes_brand_without_foot_column(self):
        _catalog, _matches, seen = run(scale=US_MEN, size="9")
        self.assertIn("Puma", {name for name, _ in seen})

    def test_only_filter_limits_brands(self):
        _catalog, _matches, seen = run(only=["reebok", "Nike"])
        self.assertEqual({name for name, _ in seen}, {"Nike", "Reebok"})

    def test_brand_missing_from_catalog_does_not_stop_others(self):
        catalog = FakeCatalog({k: v for k, v in PRICES.items() if k != "Nike"})
        finder = StubFinder(catalog)
        matches = finder.find_in_official_brands(
            size="26,2", scale=CM, catalog=catalog
        )
        found = {m.product.brand for m in matches}
        self.assertNotIn("Nike", found)
        self.assertIn("Reebok", found)

    def test_official_charts_filtered_by_published_scale(self):
        by_foot = {chart.key for chart in official_charts(CM)}
        by_eu = {chart.key for chart in official_charts(EU)}
        self.assertNotIn("puma", by_foot)
        self.assertIn("puma", by_eu)
        self.assertEqual(len(official_charts()), 6)


class TestResults(unittest.TestCase):
    def test_each_brand_converted_by_its_own_grid(self):
        _catalog, matches, _seen = run()
        converted = {m.product.brand: m.converted_eu for m in matches}
        # Стопа 26,2 см: Nike даёт EU 42,5, Reebok — EU 42.
        self.assertEqual(converted["Nike"], 42.5)
        self.assertEqual(converted["Reebok"], 42.0)

    def test_result_sorted_by_price(self):
        _catalog, matches, _seen = run()
        prices = [m.offer.price for m in matches]
        self.assertEqual(prices, sorted(prices))

    def test_total_limit_keeps_cheapest(self):
        _catalog, matches, _seen = run(total_limit=2)
        self.assertEqual(len(matches), 2)
        self.assertEqual(
            [m.product.brand for m in matches], ["Reebok", "ASICS"]
        )

    def test_max_price_filter_applied_to_every_brand(self):
        _catalog, matches, _seen = run(max_price=8000.0)
        self.assertEqual(
            {m.product.brand for m in matches}, {"Reebok", "ASICS"}
        )

    def test_empty_when_no_brand_publishes_scale(self):
        _catalog, matches, seen = run(scale="RU", size="41")
        self.assertEqual((matches, seen), ([], []))


if __name__ == "__main__":
    unittest.main()
