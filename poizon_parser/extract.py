"""Извлечение размеров и цен из данных страницы товара.

Полезная нагрузка лежит в `__NEXT_DATA__.props.pageProps`:

* `goodsDetail.saleProperties` — свойства товара. У размерного свойства есть
  `propertyMap`: {«RU»: [{propertyValueId, value}], «EU»: [...]} — один и тот же
  propertyValueId переведён в разные шкалы.
* `priceInfo.skuInfoList` — список SKU. У каждого `properties` со ссылкой на
  propertyValueId размера и `minPrice` — цена именно за этот размер.

Цена привязана к размеру, а не к модели: сайт объясняет это конкурентными
ставками поставщиков, поэтому разные размеры одной модели стоят по-разному.
"""

from __future__ import annotations

from typing import Any, Optional

from .models import Product, SizeOffer
from .sizechart import SizeChart
from .sizes import KNOWN_SCALES, parse_size

_SIZE_NAME_HINTS = ("размер", "size", "размеры")


def _dig(source: Any, *path: str, default: Any = None) -> Any:
    """Безопасный доступ по цепочке ключей."""
    current = source
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _money(price: Any) -> tuple[Optional[float], str, str]:
    """Из блока цены достаёт (число, текст, валюту)."""
    if not isinstance(price, dict):
        return None, "", "RUB"
    amount = _dig(price, "money", "amount")
    value: Optional[float] = None
    if amount is not None:
        try:
            value = float(str(amount).replace(" ", "").replace(",", "."))
        except ValueError:
            value = None
    if value is None:
        minor = _dig(price, "money", "minUnitVal")
        if isinstance(minor, (int, float)):
            value = minor / 100.0
    text = price.get("localizedDisplayText") or price.get("absText") or price.get("amountText") or ""
    currency = _dig(price, "money", "currency", default="RUB")
    return value, text, currency


def _goods_root(page_props: dict) -> dict:
    """Возвращает блок с saleProperties/skus.

    На странице товара поля разложены прямо в `goodsDetail`, а в ответе JSON API
    они вложены в `buyDialogModel`.
    """
    goods = page_props.get("goodsDetail") or {}
    if goods.get("saleProperties") or goods.get("skus"):
        return goods
    dialog = goods.get("buyDialogModel")
    if isinstance(dialog, dict):
        merged = dict(goods)
        merged.update(dialog)
        return merged
    return goods


def find_size_property(sale_properties: list) -> Optional[dict]:
    """Находит свойство, отвечающее за размер.

    Ориентируемся сначала на шкалы (RU/EU/US...), затем на название, затем
    берём свойство с наибольшим числом значений.
    """
    if not sale_properties:
        return None

    for prop in sale_properties:
        keys = set((prop.get("propertyMap") or {}).keys())
        keys |= {
            item.get("propertyKey")
            for item in (prop.get("propertyList") or [])
            if item.get("propertyKey")
        }
        if keys & set(KNOWN_SCALES) - {"DEFAULT"}:
            return prop

    for prop in sale_properties:
        name = str(prop.get("name") or "").strip().lower()
        if any(hint in name for hint in _SIZE_NAME_HINTS):
            return prop

    def value_count(prop: dict) -> int:
        total = sum(len(v or []) for v in (prop.get("propertyMap") or {}).values())
        if total:
            return total
        return sum(
            len(item.get("propertyItemModels") or [])
            for item in (prop.get("propertyList") or [])
        )

    best = max(sale_properties, key=value_count)
    return best if value_count(best) > 1 else None


def build_size_index(size_property: dict) -> tuple[dict[int, dict[str, str]], list[str]]:
    """propertyValueId → {шкала: значение}, плюс список шкал."""
    index: dict[int, dict[str, str]] = {}
    scales: list[str] = []

    property_map = size_property.get("propertyMap") or {}
    for scale, items in property_map.items():
        if not isinstance(items, list):
            continue
        if scale not in scales:
            scales.append(scale)
        for item in items:
            pv_id = item.get("propertyValueId")
            value = item.get("value")
            if pv_id is not None and value is not None:
                index.setdefault(int(pv_id), {})[scale] = str(value)

    # Запасной путь: propertyList, если propertyMap отсутствует.
    if not index:
        for entry in size_property.get("propertyList") or []:
            scale = entry.get("propertyKey") or "DEFAULT"
            if scale not in scales:
                scales.append(scale)
            for item in entry.get("propertyItemModels") or []:
                pv_id = item.get("propertyValueId")
                value = item.get("value")
                if pv_id is not None and value is not None:
                    index.setdefault(int(pv_id), {})[scale] = str(value)

    return index, scales


def build_variant_index(
    sale_properties: list, size_property: Optional[dict]
) -> dict[int, tuple[str, str]]:
    """propertyValueId → (название свойства, значение) для всего, кроме размера.

    Нужно, чтобы различать SKU с одинаковым размером, но разной полнотой,
    цветом или изданием.
    """
    size_level = (size_property or {}).get("level")
    index: dict[int, tuple[str, str]] = {}

    for prop in sale_properties or []:
        if size_property is not None and prop is size_property:
            continue
        if size_level is not None and prop.get("level") == size_level:
            continue
        name = str(prop.get("name") or "").strip()

        for items in (prop.get("propertyMap") or {}).values():
            for item in items or []:
                pv_id, value = item.get("propertyValueId"), item.get("value")
                if pv_id is not None and value:
                    index.setdefault(int(pv_id), (name, str(value)))
        for entry in prop.get("propertyList") or []:
            for item in entry.get("propertyItemModels") or []:
                pv_id, value = item.get("propertyValueId"), item.get("value")
                if pv_id is not None and value:
                    index.setdefault(int(pv_id), (name, str(value)))

    return index


def _sku_size_pv(sku: dict, size_level: Optional[int], known_ids: set[int]) -> Optional[int]:
    """propertyValueId размера у конкретного SKU."""
    properties = sku.get("properties") or []
    if size_level is not None:
        for prop in properties:
            if prop.get("level") == size_level:
                pv = prop.get("propertyValueId")
                return int(pv) if pv is not None else None
    # Уровень неизвестен — берём то свойство, что есть в размерном индексе.
    for prop in properties:
        pv = prop.get("propertyValueId")
        if pv is not None and int(pv) in known_ids:
            return int(pv)
    return None


def _delivery_and_stock(sku: dict) -> tuple[str, str, list[str]]:
    """Срок доставки, инвентарный номер и метки SKU."""
    speed_info = sku.get("skuSpeedInfo") or sku.get("speedList") or []
    delivery = ""
    inventory = ""
    if speed_info:
        first = speed_info[0] or {}
        delivery = str(first.get("speedInfoTip") or "")
        inventory = str(first.get("saleInventoryNo") or first.get("invNo") or "")
    labels = [
        str(tag.get("name"))
        for tag in (sku.get("bizTagList") or [])
        if tag.get("name")
    ]
    return delivery, inventory, labels


def parse_product(
    next_data: dict,
    url: str = "",
    article: str = "",
    include_unavailable: bool = True,
) -> Product:
    """Собирает Product со всеми размерами и ценами из __NEXT_DATA__."""
    page_props = _dig(next_data, "props", "pageProps", default={}) or {}
    goods = _goods_root(page_props)
    detail = goods.get("detail") or {}

    spu_id = int(page_props.get("spuId") or detail.get("spuId") or goods.get("spuId") or 0)
    min_price, _, _ = _money(goods.get("price") or page_props.get("price"))

    product = Product(
        spu_id=spu_id,
        title=str(detail.get("title") or page_props.get("title") or "").strip(),
        url=url or _dig(goods, "linkInfo", "url", default="") or f"/product/{spu_id}",
        article=article or str(detail.get("articleNumber") or ""),
        brand=str(detail.get("brandName") or ""),
        category=str(detail.get("frontCategoryName") or ""),
        logo_url=str(detail.get("logoUrl") or ""),
        min_price=min_price,
        size_tip=str(_dig(goods, "offSizeInfo", "deviationSizeTips", default="") or ""),
        chart=SizeChart.from_goods_detail(goods),
    )

    size_property = find_size_property(goods.get("saleProperties") or [])
    if not size_property:
        return product

    size_index, scales = build_size_index(size_property)
    variant_index = build_variant_index(goods.get("saleProperties") or [], size_property)
    product.size_scales = scales
    product.default_scale = str(
        size_property.get("defaultShow") or (scales[0] if scales else "")
    )
    size_level = size_property.get("level")

    known_ids = set(size_index)
    sku_list = (
        _dig(page_props, "priceInfo", "skuInfoList")
        or goods.get("skuInfoList")
        or goods.get("skus")
        or []
    )

    seen_pv: set[int] = set()
    for sku in sku_list:
        pv_id = _sku_size_pv(sku, size_level, known_ids)
        if pv_id is None:
            continue
        sizes = size_index.get(pv_id)
        if not sizes:
            continue

        price_block = sku.get("minPrice") or sku.get("maxPrice")
        price, price_text, currency = _money(price_block)
        delivery, inventory, labels = _delivery_and_stock(sku)

        variant: dict[str, str] = {}
        for prop in sku.get("properties") or []:
            other_pv = prop.get("propertyValueId")
            if other_pv is None or int(other_pv) == pv_id:
                continue
            found = variant_index.get(int(other_pv))
            if found:
                name, value = found
                variant[name or f"level{prop.get('level')}"] = value

        product.offers.append(
            SizeOffer(
                sku_id=int(sku.get("skuId") or 0),
                sizes=dict(sizes),
                price=price,
                price_text=price_text,
                currency=currency,
                in_stock=bool(sku.get("status") == 1 and price is not None),
                delivery=delivery,
                inventory_no=inventory,
                labels=labels,
                variant=variant,
            )
        )
        seen_pv.add(pv_id)

    # Размеры из каталога, для которых нет предложений — они существуют,
    # но купить их сейчас нельзя.
    if include_unavailable:
        for pv_id, sizes in size_index.items():
            if pv_id in seen_pv:
                continue
            product.offers.append(
                SizeOffer(sku_id=0, sizes=dict(sizes), price=None, in_stock=False)
            )

    preferred = product.default_scale if product.default_scale in scales else (scales[0] if scales else "")

    def sort_key(offer: SizeOffer) -> float:
        value = parse_size(offer.sizes.get(preferred)) if preferred else None
        if value is None:
            for scale in scales:
                value = parse_size(offer.sizes.get(scale))
                if value is not None:
                    break
        return value if value is not None else float("inf")

    product.offers.sort(key=sort_key)
    return product
