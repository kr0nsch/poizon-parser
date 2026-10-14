"""Разбор и сопоставление размеров.

На сайте один и тот же размер публикуется в нескольких шкалах (RU, EU, US...).
Значения приходят строками с запятой в качестве разделителя: «42,5».
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# Шкалы, которые встречаются в данных сайта. Порядок задаёт приоритет
# при поиске без явного указания шкалы.
KNOWN_SCALES = ("RU", "EU", "US", "UK", "CN", "JP", "FR", "IT", "DEFAULT")

#: Насколько могут расходиться два числа, обозначающие один и тот же размер.
#: Таблицы брендов хранят трети округлёнными (42⅔ → 42.6667), а ярлык SKU
#: «42⅔» разбирается в 42.666…: сравнение «до 1e-9» считало бы их разными.
#: Самый мелкий настоящий шаг сетки — ⅛ (0,125), так что 1e-3 его не съедает.
SIZE_EPSILON = 1e-3

# Adidas и ряд других брендов публикуют размеры дробями: «42⅓», «41⅔».
# Без этого «42⅓» читалось бы как ровно 42 и подменяло бы размер.
_FRACTIONS = {
    "⅛": 0.125, "⅙": 1 / 6, "⅕": 0.2, "¼": 0.25, "⅓": 1 / 3, "⅜": 0.375,
    "⅖": 0.4, "½": 0.5, "⅗": 0.6, "⅝": 0.625, "⅔": 2 / 3, "¾": 0.75,
    "⅘": 0.8, "⅚": 5 / 6, "⅞": 0.875,
}

_NUM_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*([" + "".join(_FRACTIONS) + r"])?"
)
# «US W» / «US M» и метрические шкалы проверяются раньше голого «US»: иначе
# «US W 7» разбиралось бы как «US» + «W 7» и превращалось в мужской US 7.
_SCALE_PREFIX_RE = re.compile(
    r"^\s*(US[\s_-]*(?:W|M|ЖЕН|МУЖ)[^\d\s]*|CM|MM|СМ|ММ|"
    + "|".join(KNOWN_SCALES)
    + r")\s*[-:]?\s*(.+)$",
    re.IGNORECASE,
)
#: Кириллические «см»/«мм» → латинские коды, которые понимает sizechart.
_METRIC_PREFIXES = {"СМ": "CM", "ММ": "MM"}


def _canonical_scale(prefix: str) -> str:
    """Префикс из ввода → имя шкалы: «usw» → «US W», «см» → «CM»."""
    key = re.sub(r"[\s_-]+", "", prefix).upper()
    if key.startswith("US") and len(key) > 2:
        return "US W" if key[2] in ("W", "Ж") else "US M"
    return _METRIC_PREFIXES.get(key, key)


def parse_size(text: str | float | int | None) -> Optional[float]:
    """«42,5» → 42.5, «42⅓» → 42.33. None, если числа в строке нет."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)

    raw = str(text).strip()
    # Одиночная дробь без целой части: «½».
    if raw in _FRACTIONS:
        return _FRACTIONS[raw]

    match = _NUM_RE.search(raw)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    if match.group(2):
        value += _FRACTIONS[match.group(2)]
    return value


def parse_size_query(text: str) -> tuple[Optional[str], float]:
    """Разбирает пользовательский ввод размера.

    Поддерживает «42», «42,5», «RU42», «EU 43», «US 9.5», «US W 7», «usm 9»,
    «CM 26,5», «MM 265». Возвращает (шкала или None, число); шкалы с полом и
    метрические приходят в виде, понятном ``sizechart.normalize_scale``:
    «US W», «US M», «CM», «MM». Голое «US» остаётся «US» — пол в нём не задан.
    """
    raw = str(text).strip()
    if not raw:
        raise ValueError("размер не задан")

    scale: Optional[str] = None
    match = _SCALE_PREFIX_RE.match(raw)
    if match:
        scale = _canonical_scale(match.group(1))
        raw = match.group(2)

    value = parse_size(raw)
    if value is None:
        raise ValueError(f"не удалось разобрать размер: {text!r}")
    return scale, value


def scale_priority(scales: Iterable[str], preferred: Optional[str] = None) -> list[str]:
    """Упорядочивает шкалы: сначала предпочитаемая, затем известные, затем прочие."""
    available = list(scales)
    ordered: list[str] = []

    if preferred and preferred in available:
        ordered.append(preferred)
    for scale in KNOWN_SCALES:
        if scale in available and scale not in ordered:
            ordered.append(scale)
    for scale in available:
        if scale not in ordered:
            ordered.append(scale)
    return ordered


def match_size(
    sizes: dict[str, str],
    requested: float,
    scale: Optional[str] = None,
    tolerance: float = 0.0,
    preferred_scale: Optional[str] = None,
) -> Optional[tuple[str, float]]:
    """Проверяет, подходит ли набор размеров товара под запрошенный.

    Args:
        sizes: {«RU»: «42», «EU»: «43»} — размеры одного SKU.
        requested: искомое число.
        scale: искать только в этой шкале; None — в любой.
        tolerance: допустимое отклонение (0.5 захватит соседний полуразмер).
        preferred_scale: какая шкала важнее при поиске по всем.

    Returns:
        (шкала, отклонение) для лучшего совпадения либо None.
    """
    if scale:
        candidates = [scale] if scale in sizes else []
    else:
        candidates = scale_priority(sizes.keys(), preferred_scale)

    best: Optional[tuple[str, float]] = None
    for candidate in candidates:
        value = parse_size(sizes.get(candidate))
        if value is None:
            continue
        delta = abs(value - requested)
        if delta <= tolerance + SIZE_EPSILON:
            if best is None or delta < best[1]:
                best = (candidate, delta)
            # Точное совпадение в приоритетной шкале — лучше не найти.
            if delta <= SIZE_EPSILON:
                break
    return best
