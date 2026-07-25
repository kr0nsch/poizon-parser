"""Парсер thepoizon.ru: поиск моделей обуви по размеру с ценами."""

from .client import PoizonClient, PoizonError
from .models import Product, SizeOffer, SearchItem
from .finder import SizeFinder

__version__ = "1.0.0"

__all__ = [
    "PoizonClient",
    "PoizonError",
    "Product",
    "SizeOffer",
    "SearchItem",
    "SizeFinder",
]
