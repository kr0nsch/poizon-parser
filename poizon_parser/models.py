"""Модели данных парсера."""

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class SearchItem:
    """Товар из поисковой выдачи."""

    spu_id: int
    title: str
    url: str
    article: str = ""
    logo_url: str = ""
    brand_id: Optional[int] = None
    #: Минимальная цена по всем размерам из листинга. Позволяет отсеять товар
    #: до загрузки карточки: если минимум уже дороже лимита, нужный размер
    #: дешевле не будет.
    min_price: Optional[float] = None

    @property
    def full_url(self) -> str:
        from .client import BASE_URL

        return BASE_URL + self.url if self.url.startswith("/") else self.url


@dataclass
class SizeOffer:
    """Конкретный размер товара с ценой.

    sizes — значения размера во всех доступных шкалах, например {"RU": "42", "EU": "43"}.
    price — цена в рублях; None, если размер есть в каталоге, но предложений нет.
    """

    sku_id: int
    sizes: dict[str, str]
    price: Optional[float] = None
    price_text: str = ""
    currency: str = "RUB"
    in_stock: bool = False
    delivery: str = ""
    inventory_no: str = ""
    labels: list[str] = field(default_factory=list)
    # Прочие свойства SKU кроме размера: полнота, цвет, издание.
    variant: dict[str, str] = field(default_factory=dict)

    @property
    def variant_label(self) -> str:
        return " / ".join(self.variant.values())

    def size_in(self, scale: str) -> str:
        return self.sizes.get(scale, "")

    @property
    def size_label(self) -> str:
        """Компактное представление размера: 'RU 42 / EU 43'."""
        return " / ".join(f"{scale} {value}" for scale, value in self.sizes.items())


@dataclass
class Product:
    """Карточка товара с полным списком размеров."""

    spu_id: int
    title: str
    url: str
    article: str = ""
    brand: str = ""
    category: str = ""
    logo_url: str = ""
    size_scales: list[str] = field(default_factory=list)
    default_scale: str = ""
    offers: list[SizeOffer] = field(default_factory=list)
    min_price: Optional[float] = None
    size_tip: str = ""
    #: Официальная таблица соответствия размеров (SizeChart), если сайт её отдал.
    chart: object = None

    @property
    def full_url(self) -> str:
        from .client import BASE_URL

        return BASE_URL + self.url if self.url.startswith("/") else self.url

    def in_stock_offers(self) -> list[SizeOffer]:
        return [o for o in self.offers if o.in_stock]


@dataclass
class Match:
    """Найденное соответствие: товар + подходящий размер."""

    product: Product
    offer: SizeOffer
    matched_scale: str
    requested_size: float
    #: Шкала, в которой размер задал пользователь (EU / US M / UK / CM…).
    requested_scale: str = ""
    #: Размер после перевода в EU.
    converted_eu: Optional[float] = None
    #: True, если перевод взят из официальной таблицы товара, а не оценён.
    exact_conversion: bool = True
    conversion_source: str = "native"
    conversion_note: str = ""
    #: Ярлык размера в сантиметрах по таблице бренда (он же JP/мондопоинт).
    #: Не равен замеру стопы: у Nike EU 42,5 — ярлык 27 см при стопе 26,2 см.
    converted_cm: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "spu_id": self.product.spu_id,
            "title": self.product.title,
            "article": self.product.article,
            "brand": self.product.brand,
            "url": self.product.full_url,
            "requested_size": self.requested_size,
            "requested_scale": self.requested_scale,
            "converted_eu": self.converted_eu,
            "converted_cm": self.converted_cm,
            "exact_conversion": self.exact_conversion,
            "conversion_source": self.conversion_source,
            "conversion_note": self.conversion_note,
            "matched_scale": self.matched_scale,
            "size": self.offer.size_in(self.matched_scale),
            "sizes": self.offer.sizes,
            "price": self.offer.price,
            "price_text": self.offer.price_text,
            "currency": self.offer.currency,
            "in_stock": self.offer.in_stock,
            "delivery": self.offer.delivery,
            "variant": self.offer.variant_label,
            "sku_id": self.offer.sku_id,
            "inventory_no": self.offer.inventory_no,
            "labels": self.offer.labels,
            "product_min_price": self.product.min_price,
            "size_tip": self.product.size_tip,
            "image": self.product.logo_url,
        }
