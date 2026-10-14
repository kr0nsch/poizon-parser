"""Обход сразу всех брендов с официальной таблицей размеров."""

import threading
import unittest

from poizon_parser.catalog import Brand
from poizon_parser.client import ChallengeRequired
from poizon_parser.finder import SizeFinder
from poizon_parser.models import Product, SearchItem, SizeOffer
from poizon_parser.sizechart import CM, EU, US_MEN, US_WOMEN, official_charts

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

    def test_only_filter_accepts_aliases(self):
        _catalog, _matches, seen = run(
            only=["nb", "jordan", "Adidas Originals", "new-balance"]
        )
        self.assertEqual(
            {name for name, _ in seen}, {"New Balance", "Nike", "Adidas"}
        )

    def test_only_filter_reports_unknown_brand(self):
        catalog = FakeCatalog(PRICES)
        finder = StubFinder(catalog)
        progress = []
        finder.on_progress = progress.append
        seen = []
        finder.find_in_official_brands(
            size="26,2", scale=CM, catalog=catalog, only=["vans", "nike"],
            on_brand=lambda name, found: seen.append(name),
        )
        self.assertEqual(seen, ["Nike"])
        self.assertTrue(any("vans" in line for line in progress))

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


class TestFindByBrandScale(unittest.TestCase):
    """Шкала из строки размера против явной --scale."""

    def find(self, size, scale=EU):
        catalog = FakeCatalog(PRICES)
        return StubFinder(catalog).find_by_brand(
            "Nike", size=size, scale=scale, catalog=catalog
        )

    def test_us_women_in_size_string_is_women(self):
        # Nike US W 10 = EU 42; мужской US 10 был бы EU 44 — его в ряду нет.
        matches = self.find("US W 10")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].requested_scale, US_WOMEN)
        self.assertEqual(matches[0].converted_eu, 42.0)

    def test_bare_us_does_not_override_explicit_women_scale(self):
        matches = self.find("US 10", scale="US W")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].requested_scale, US_WOMEN)

    def test_bare_us_without_explicit_scale_is_men(self):
        # US M 10 у Nike = EU 44, а ряд карточки заканчивается на 43,5.
        self.assertEqual(self.find("US 10"), [])

    def test_explicit_gender_in_size_string_wins(self):
        matches = self.find("US W 10", scale="US M")
        self.assertEqual(matches[0].requested_scale, US_WOMEN)

    def test_numeric_size_with_gendered_scale(self):
        # Так зовёт CLI: число уже разобрано, шкала — каноническая.
        matches = self.find(10.0, scale="usw")
        self.assertEqual(matches[0].requested_scale, US_WOMEN)

    def test_scale_in_size_string_selects_brands_for_all_brands(self):
        # «US M 9» при scale=CM — поиск по US M: Puma (без замера стопы)
        # участвует, как и при явной scale=US M.
        _catalog, _matches, seen = run(scale=CM, size="US M 9")
        self.assertIn("Puma", {name for name, _ in seen})


class ChallengeCatalog(FakeCatalog):
    """У каждого бренда несколько карточек: spu = номер бренда * 10 + i."""

    def brand_items(self, brand, max_items=None, include_kids=False):
        return [
            SearchItem(
                spu_id=brand.brand_id * 10 + index,
                title=brand.name,
                url=f"/product/{brand.brand_id * 10 + index}",
            )
            for index in range(3)
        ]


class ChallengeFinder(StubFinder):
    """Карточка blocked отвечает проверкой; цена падает с номером карточки."""

    def __init__(self, catalog, blocked):
        super().__init__(catalog)
        self.blocked = blocked

    def load_product(self, item):
        if item.spu_id == self.blocked:
            raise ChallengeRequired("https://www.thepoizon.ru/x", "captcha")
        price = self.catalog.prices[item.title] - (item.spu_id % 10) * 100
        return make_product(item.spu_id, item.title, price)


class TestChallengeKeepsPartial(unittest.TestCase):
    """Регрессия: при проверке сайта находки до неё терялись."""

    def test_find_by_brand_attaches_sorted_partial(self):
        catalog = ChallengeCatalog(PRICES)
        nike = catalog.find_brand("Nike").brand_id
        finder = ChallengeFinder(catalog, blocked=nike * 10 + 2)
        with self.assertRaises(ChallengeRequired) as ctx:
            finder.find_by_brand("Nike", size="26,2", scale=CM, catalog=catalog)
        partial = ctx.exception.partial
        # Найдены две карточки до проверки, дешёвая — первой, как в выдаче.
        self.assertEqual(
            [m.product.spu_id for m in partial], [nike * 10 + 1, nike * 10]
        )

    def test_all_brands_partial_includes_previous_brands(self):
        catalog = ChallengeCatalog(PRICES)
        charts = [chart.name for chart in official_charts(CM)]
        blocked_brand = charts[2]
        blocked = catalog.find_brand(blocked_brand).brand_id * 10 + 1
        finder = ChallengeFinder(catalog, blocked=blocked)
        seen = []
        with self.assertRaises(ChallengeRequired) as ctx:
            finder.find_in_official_brands(
                size="26,2", scale=CM, catalog=catalog,
                on_brand=lambda name, found: seen.append((name, len(found))),
            )
        partial = ctx.exception.partial
        brands = {m.product.brand for m in partial}
        self.assertEqual(brands, set(charts[:3]))
        prices = [m.offer.price for m in partial]
        self.assertEqual(prices, sorted(prices))
        # Прерванный бренд тоже попал в сводку — с тем, что успели найти.
        self.assertEqual(seen, [(charts[0], 3), (charts[1], 3), (blocked_brand, 1)])

    def test_all_brands_partial_respects_total_limit(self):
        catalog = ChallengeCatalog(PRICES)
        charts = [chart.name for chart in official_charts(CM)]
        blocked = catalog.find_brand(charts[2]).brand_id * 10
        finder = ChallengeFinder(catalog, blocked=blocked)
        with self.assertRaises(ChallengeRequired) as ctx:
            finder.find_in_official_brands(
                size="26,2", scale=CM, catalog=catalog, total_limit=2
            )
        self.assertEqual(len(ctx.exception.partial), 2)


if __name__ == "__main__":
    unittest.main()
