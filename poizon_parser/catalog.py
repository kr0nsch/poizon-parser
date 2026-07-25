"""Каталог: бренды и списки товаров по бренду или категории.

Страницы `/brand/<slug>` и `/category/<slug>` рендерятся на сервере, поэтому
список товаров лежит прямо в `__NEXT_DATA__`. Пагинация — параметром `?page=N`.

Фильтры сайта (бренд, размер, пол) через query-параметры не применяются: SSR их
игнорирует, а клиентский API фильтрации отдаёт рекомендательную выдачу без учёта
переданных фасетов. Поэтому бренд задаётся адресом страницы, а категория
отбирается по `level1CategoryId` уже на нашей стороне.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterator, Optional

from .client import PoizonClient
from .models import SearchItem

#: `level1CategoryId` разделов с обувью.
FOOTWEAR_CATEGORY_IDS = frozenset({29})
KIDS_FOOTWEAR_CATEGORY_IDS = frozenset({1003733})

#: Товаров на странице листинга; неполная страница означает конец выдачи.
PAGE_SIZE = 60

#: Предохранитель от бесконечной пагинации, если сайт зациклит выдачу.
MAX_PAGES = 60

#: Категории-лендинги с обувью — на случай поиска без бренда.
SHOE_CATEGORIES = (
    "shoes",
    "sneakers",
    "boots-shoes",
    "casual-shoes",
    "flats-shoes",
    "running-sneakers",
    "basketball-sneakers",
    "skateboarding-sneakers",
    "trendy-sneakers-casual-shoes",
)


@dataclass(frozen=True)
class Brand:
    """Бренд из каталога сайта."""

    brand_id: int
    name: str
    url: str

    @property
    def slug(self) -> str:
        return self.url.rstrip("/").rsplit("/", 1)[-1]


def _slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _listing_min_price(item: dict) -> Optional[float]:
    """Минимальная цена товара из листинга (`minSpuPrice`)."""
    price = item.get("minSpuPrice")
    if not isinstance(price, dict):
        return None
    amount = (price.get("money") or {}).get("amount")
    if amount is not None:
        try:
            return float(str(amount).replace(" ", "").replace(",", "."))
        except ValueError:
            pass
    minor = (price.get("money") or {}).get("minUnitVal")
    if isinstance(minor, (int, float)):
        return minor / 100.0
    return None


def is_footwear(item: dict, include_kids: bool = False) -> bool:
    """Относится ли товар из выдачи к обуви."""
    category = item.get("level1CategoryId")
    if category in FOOTWEAR_CATEGORY_IDS:
        return True
    if include_kids and category in KIDS_FOOTWEAR_CATEGORY_IDS:
        return True
    # Запасной признак, если категория не проставлена.
    if category is None:
        gpc = str(item.get("googleProductCategory") or "")
        return gpc.endswith("> Shoes")
    return False


class Catalog:
    """Доступ к брендам и спискам товаров."""

    def __init__(self, client: Optional[PoizonClient] = None) -> None:
        self.client = client or PoizonClient()
        self._brands: Optional[list[Brand]] = None

    # ----------------------------------------------------------- бренды

    def brands(self, refresh: bool = False) -> list[Brand]:
        """Полный список брендов со страницы `/brand/list`."""
        if self._brands is not None and not refresh:
            return self._brands

        page_props = self._page_props("/brand/list")
        brands: list[Brand] = []
        seen: set[int] = set()
        for group in page_props.get("brandList") or []:
            for item in group.get("itemList") or []:
                brand_id = item.get("brandId")
                url = item.get("brandUrl") or ""
                name = str(item.get("name") or "").strip()
                if not brand_id or brand_id in seen or not url:
                    continue
                seen.add(int(brand_id))
                brands.append(Brand(brand_id=int(brand_id), name=name, url=url))

        brands.sort(key=lambda b: b.name.lower())
        self._brands = brands
        return brands

    def find_brand(self, query: str) -> Optional[Brand]:
        """Ищет бренд по имени или слагу: «nike», «New Balance», «new-balance»."""
        target = str(query).strip().lower()
        target_slug = _slugify(target)
        brands = self.brands()

        for brand in brands:
            if brand.name.lower() == target or brand.slug == target_slug:
                return brand
        # Частичное совпадение — берём самое короткое имя, чтобы «nike»
        # не превратилось в «Nike Sportswear».
        partial = [
            b for b in brands
            if target in b.name.lower() or target_slug in b.slug
        ]
        if partial:
            return min(partial, key=lambda b: len(b.name))
        return None

    def suggest_brands(self, query: str, limit: int = 8) -> list[Brand]:
        """Похожие бренды — чтобы подсказать при опечатке."""
        target = _slugify(query)
        if not target:
            return []
        scored = []
        for brand in self.brands():
            slug = brand.slug
            if target in slug or slug in target:
                scored.append((0, brand))
            elif target[:3] and target[:3] in slug:
                scored.append((1, brand))
        scored.sort(key=lambda pair: (pair[0], len(pair[1].name)))
        return [brand for _, brand in scored[:limit]]

    # ---------------------------------------------------------- выдача

    def _page_props(self, path: str) -> dict:
        html = self.client.fetch_product_html(path)
        data = self.client.extract_next_data(html)
        return (data.get("props") or {}).get("pageProps") or {}

    def _listing(self, path: str, page: int) -> tuple[list[dict], int]:
        sep = "&" if "?" in path else "?"
        target = path if page <= 1 else f"{path}{sep}page={page}"
        props = self._page_props(target)
        return list(props.get("spuList") or []), int(props.get("total") or 0)

    def iter_items(
        self,
        path: str,
        max_items: Optional[int] = 60,
        footwear_only: bool = True,
        include_kids: bool = False,
    ) -> Iterator[SearchItem]:
        """Перебирает товары листинга постранично.

        max_items=None — пройти все страницы до конца выдачи. Останавливается,
        когда набран лимит, страница пришла пустой или неполной.
        """
        seen: set[int] = set()
        yielded = 0
        page = 1
        while page <= MAX_PAGES:
            if max_items is not None and yielded >= max_items:
                return
            items, _total = self._listing(path, page)
            if not items:
                return

            for raw in items:
                spu_id = raw.get("spuId")
                if not spu_id or int(spu_id) in seen:
                    continue
                if footwear_only and not is_footwear(raw, include_kids):
                    continue
                seen.add(int(spu_id))
                yield SearchItem(
                    spu_id=int(spu_id),
                    title=str(raw.get("title") or "").strip(),
                    url=str(raw.get("url") or f"/product/{spu_id}"),
                    article=str(raw.get("articleNumber") or ""),
                    logo_url=str(raw.get("logoUrl") or ""),
                    brand_id=raw.get("brandId"),
                    min_price=_listing_min_price(raw),
                )
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return

            # Меньше полной страницы — дальше ничего нет.
            if len(items) < PAGE_SIZE:
                return
            page += 1

    def brand_items(self, brand: Brand | str, max_items: Optional[int] = 60, **kwargs) -> Iterator[SearchItem]:
        """Товары бренда (по умолчанию только обувь)."""
        url = brand.url if isinstance(brand, Brand) else str(brand)
        if not url.startswith("/"):
            found = self.find_brand(url)
            if found is None:
                raise ValueError(f"бренд не найден: {url}")
            url = found.url
        return self.iter_items(url, max_items=max_items, **kwargs)

    def category_items(self, category: str = "shoes", max_items: Optional[int] = 60, **kwargs) -> Iterator[SearchItem]:
        """Товары категории."""
        path = category if category.startswith("/") else f"/category/{category}"
        return self.iter_items(path, max_items=max_items, **kwargs)
