"""Тесты каталога: отбор обуви и поиск бренда."""

import unittest

from poizon_parser.catalog import (
    FOOTWEAR_CATEGORY_IDS,
    Brand,
    Catalog,
    is_footwear,
)


class TestIsFootwear(unittest.TestCase):
    def test_adult_footwear(self):
        self.assertTrue(is_footwear({"level1CategoryId": 29}))

    def test_apparel_rejected(self):
        self.assertFalse(is_footwear({"level1CategoryId": 2}))

    def test_kids_excluded_by_default(self):
        self.assertFalse(is_footwear({"level1CategoryId": 1003733}))

    def test_kids_included_when_asked(self):
        self.assertTrue(is_footwear({"level1CategoryId": 1003733}, include_kids=True))

    def test_falls_back_to_google_category(self):
        item = {"googleProductCategory": "Apparel & Accessories > Shoes"}
        self.assertTrue(is_footwear(item))

    def test_google_category_non_shoes(self):
        item = {"googleProductCategory": "Apparel & Accessories > Clothing > Shirts & Tops"}
        self.assertFalse(is_footwear(item))

    def test_footwear_ids_constant(self):
        self.assertIn(29, FOOTWEAR_CATEGORY_IDS)


class TestBrand(unittest.TestCase):
    def test_slug_from_url(self):
        brand = Brand(brand_id=4, name="New Balance", url="/brand/new-balance")
        self.assertEqual(brand.slug, "new-balance")


class FakeCatalog(Catalog):
    """Каталог с заранее заданным списком брендов — без обращения к сети."""

    def __init__(self, brands):
        self._brands = brands
        self.client = None


BRANDS = [
    Brand(144, "Nike", "/brand/nike"),
    Brand(4, "New Balance", "/brand/new-balance"),
    Brand(494, "Adidas Originals", "/brand/adidas-originals"),
    Brand(1, "Adidas", "/brand/adidas"),
    Brand(999, "MACHENIKE", "/brand/machenike"),
]


def _raw(spu_id, category=29):
    return {
        "spuId": spu_id,
        "level1CategoryId": category,
        "title": f"Товар {spu_id}",
        "url": f"/product/{spu_id}",
    }


class PagedCatalog(Catalog):
    """Каталог с заранее заданными страницами — без сети."""

    def __init__(self, pages):
        self._pages = pages
        self.client = None
        self._brands = None
        self.requested_pages = []

    def _listing(self, path, page):
        self.requested_pages.append(page)
        items = self._pages[page - 1] if page <= len(self._pages) else []
        return items, 999


class TestPagination(unittest.TestCase):
    """Полный проход по всем страницам листинга."""

    def make(self, *sizes, category=29):
        counter = iter(range(1, 10_000))
        pages = [[_raw(next(counter), category) for _ in range(n)] for n in sizes]
        return PagedCatalog(pages)

    def test_unlimited_walks_all_pages(self):
        catalog = self.make(60, 60, 5)
        items = list(catalog.iter_items("/brand/x", max_items=None))
        self.assertEqual(len(items), 125)
        self.assertEqual(catalog.requested_pages, [1, 2, 3])

    def test_short_page_stops_iteration(self):
        catalog = self.make(60, 30, 60)  # третья страница не должна запрашиваться
        list(catalog.iter_items("/brand/x", max_items=None))
        self.assertEqual(catalog.requested_pages, [1, 2])

    def test_limit_stops_early(self):
        catalog = self.make(60, 60, 60)
        items = list(catalog.iter_items("/brand/x", max_items=70))
        self.assertEqual(len(items), 70)
        self.assertEqual(catalog.requested_pages, [1, 2])

    def test_duplicates_across_pages_skipped(self):
        page1 = [_raw(i) for i in range(1, 61)]
        page2 = [_raw(i) for i in range(31, 61)]  # все уже были
        catalog = PagedCatalog([page1, page2])
        items = list(catalog.iter_items("/brand/x", max_items=None))
        self.assertEqual(len(items), 60)

    def test_non_footwear_filtered_everywhere(self):
        catalog = self.make(60, 10, category=2)  # одежда
        items = list(catalog.iter_items("/brand/x", max_items=None))
        self.assertEqual(items, [])

    def test_empty_listing(self):
        catalog = PagedCatalog([[]])
        self.assertEqual(list(catalog.iter_items("/brand/x", max_items=None)), [])


class TestFindBrand(unittest.TestCase):
    def setUp(self):
        self.catalog = FakeCatalog(BRANDS)

    def test_exact_name_case_insensitive(self):
        self.assertEqual(self.catalog.find_brand("nike").brand_id, 144)

    def test_exact_slug(self):
        self.assertEqual(self.catalog.find_brand("new-balance").brand_id, 4)

    def test_name_with_space(self):
        self.assertEqual(self.catalog.find_brand("New Balance").brand_id, 4)

    def test_exact_match_beats_substring(self):
        # «Nike» не должно превратиться в «MACHENIKE».
        self.assertEqual(self.catalog.find_brand("Nike").name, "Nike")

    def test_shortest_partial_wins(self):
        self.assertEqual(self.catalog.find_brand("adidas").name, "Adidas")

    def test_unknown_returns_none(self):
        self.assertIsNone(self.catalog.find_brand("zzzz-unknown"))

    def test_suggestions_for_typo(self):
        names = [b.name for b in self.catalog.suggest_brands("adid")]
        self.assertIn("Adidas", names)


if __name__ == "__main__":
    unittest.main()
