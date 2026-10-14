"""Разбор и сопоставление размеров.

На сайте один и тот же размер публикуется в нескольких шкалах (RU, EU, US...).
Значения приходят строками с запятой в качестве разделителя: «42,5».
"""

from __future__ import annotations

import math
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

_FRACTION_CHARS = "".join(_FRACTIONS)

# Число, за которым может идти дробь: символом («42⅔») или через косую черту
# («42 2/3», «9 1/2») — так Adidas и американские таблицы пишут размеры.
# Группы: число, символ дроби, числитель, знаменатель.
_NUM_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)"
    r"(?:\s*([" + _FRACTION_CHARS + r"])|\s+(\d+)/(\d+)(?![\d/]))?"
)

# Значение в пользовательском вводе разбирается целиком, без «хвостов»:
# дробь — только после целого числа, «42,5 1/2» и «42-43» не размер.
_QUERY_NUMBER_RE = re.compile(
    r"(?P<whole>\d+)(?:\s*(?P<char>[" + _FRACTION_CHARS + r"])"
    r"|\s+(?P<num>\d+)/(?P<den>\d+))"
    r"|(?P<plain>\d+(?:[.,]\d+)?)"
    r"|(?P<bare>[" + _FRACTION_CHARS + r"])"
)
# После числа допустима единица длины: «26,5 см», «265 mm».
_UNIT_SUFFIX_RE = re.compile(r"^(?:CM|MM|СМ|ММ)\.?$", re.IGNORECASE)
# …и пол после голого «US»: «US 7W», «US 7 W», «US 9 муж».
_GENDER_SUFFIX_RE = re.compile(
    r"^(?:W|M|Ж|М|WOMEN|MEN|ЖЕН[А-ЯЁ]*|МУЖ[А-ЯЁ]*)\.?$", re.IGNORECASE
)
# «US W» / «US M» и метрические шкалы проверяются раньше голого «US»: иначе
# «US W 7» разбиралось бы как «US» + «W 7» и превращалось в мужской US 7.
# Пол — латиницей или кириллицей, словом или одной буквой: «US Ж 7», «US М 7»
# («жен», «муж» и «Женские» тоже начинаются с этих букв). Хвост слова не
# забирает двоеточие и минусы, иначе знак числа «US W−7» терялся бы.
# Группы: префикс, пробел до разделителя, разделитель, пробел после, число.
_SCALE_PREFIX_RE = re.compile(
    r"^\s*(US[\s_-]*(?:W|M|Ж|М)[^\d\s:\-−–]*|CM|MM|СМ|ММ|"
    + "|".join(KNOWN_SCALES)
    + r")(\s*)([-:]?)(\s*)(.+)$",
    re.IGNORECASE,
)
#: Кириллические «см»/«мм» → латинские коды, которые понимает sizechart.
_METRIC_PREFIXES = {"СМ": "CM", "ММ": "MM"}
#: Знаки минуса перед числом: дефис, типографский минус и короткое тире.
_MINUS_SIGNS = ("-", "−", "–")


def _canonical_scale(prefix: str) -> str:
    """Префикс из ввода → имя шкалы: «usw» → «US W», «см» → «CM»."""
    key = re.sub(r"[\s_-]+", "", prefix).upper()
    if key.startswith("US") and len(key) > 2:
        return "US W" if key[2] in ("W", "Ж") else "US M"
    return _METRIC_PREFIXES.get(key, key)


def _proper_fraction(numerator: str, denominator: str) -> Optional[float]:
    """«2», «3» → 0.667. None, если это не правильная дробь (3/2, 0/3, 1/0).

    Дроби размеров короткие: длинные цифры — не дробь, да и int() на тысячах
    цифр упал бы с собственной ошибкой.
    """
    if len(numerator) > 3 or len(denominator) > 3:
        return None
    top, bottom = int(numerator), int(denominator)
    if not 0 < top < bottom:
        return None
    return top / bottom


def parse_size(text: str | float | int | None) -> Optional[float]:
    """«42,5» → 42.5, «42⅓» и «42 1/3» → 42.33. None, если числа нет.

    Разбор нестрогий — для ярлыков SKU и таблиц сайта: берётся первое число
    строки, остальное («RU (39,5 EU)») не мешает. Пользовательский ввод
    разбирает строгий parse_size_query.
    """
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
    number, char, numerator, denominator = match.groups()
    try:
        value = float(number.replace(",", "."))
    except ValueError:
        return None
    if char:
        value += _FRACTIONS[char]
    elif numerator and number.isdigit():
        # «42 2/3» — дробь только у целого числа; «10/2025» дробью не считаем.
        fraction = _proper_fraction(numerator, denominator)
        if fraction is not None:
            value += fraction
    return value


def _query_value(text: str, raw: str) -> tuple[float, str]:
    """Число в начале ввода и всё, что осталось после него."""
    match = _QUERY_NUMBER_RE.match(raw)
    if not match:
        raise ValueError(f"не удалось разобрать размер: {text!r}")
    if match.group("bare"):
        value = _FRACTIONS[match.group("bare")]
    elif match.group("plain"):
        value = float(match.group("plain").replace(",", "."))
    else:
        value = float(match.group("whole"))
        if match.group("char"):
            value += _FRACTIONS[match.group("char")]
        else:
            fraction = _proper_fraction(match.group("num"), match.group("den"))
            if fraction is None:
                raise ValueError(
                    f"не удалось разобрать размер: {text!r} — "
                    f"«{match.group('num')}/{match.group('den')}» не дробь "
                    "размера (нужна вида «1/2», «2/3»)"
                )
            value += fraction
    return value, raw[match.end():].strip()


def parse_size_query(text: str) -> tuple[Optional[str], float]:
    """Разбирает пользовательский ввод размера.

    Поддерживает «42», «42,5», «42⅔», «42 2/3», «RU42», «EU 43», «US 9.5»,
    «US 9 1/2», «US W 7», «US 7W», «usm 9», «CM 26,5», «26,5 см», «MM 265».
    Возвращает (шкала или None, число); шкалы с полом и метрические приходят
    в виде, понятном ``sizechart.normalize_scale``: «US W», «US M», «CM»,
    «MM». Голое «US» остаётся «US» — пол в нём не задан.

    Строка разбирается целиком: всё, что не размер, — ValueError. Раньше
    брался первый номер, и «42 2/3» молча превращалось в 42, «US 7W» — в
    мужской US 7, а «42-43» — в 42. Пол после числа понятен только после
    голого «US»: «7W» без шкалы может значить и полноту.

    Отрицательный размер («-42») и число, которое не помещается во float
    (сотни цифр подряд дают inf), — тоже ValueError: иначе знак молча
    терялся бы, а inf ронял бы вывод.
    """
    raw = str(text).strip()
    if not raw:
        raise ValueError("размер не задан")

    scale: Optional[str] = None
    match = _SCALE_PREFIX_RE.match(raw)
    if match:
        scale = _canonical_scale(match.group(1))
        space_before, separator, space_after, raw = match.group(2, 3, 4, 5)
        # «EU-42» и «EU - 42» — разделитель, а «EU -42» — минус у числа.
        if separator == "-" and space_before and not space_after:
            raise ValueError("размер должен быть больше нуля")

    # Знак перед числом регулярное выражение числа не пропустит — ловим его
    # отдельно, чтобы сообщение было про знак, а не «не удалось разобрать».
    if raw.startswith(_MINUS_SIGNS):
        raise ValueError("размер должен быть больше нуля")
    value, tail = _query_value(text, raw)
    if not math.isfinite(value):
        raise ValueError("не удалось разобрать размер: слишком большое число")

    if tail:
        if _UNIT_SUFFIX_RE.match(tail):
            unit = _canonical_scale(tail.rstrip("."))
            if scale is not None and scale != unit:
                raise ValueError(
                    f"в размере {text!r} две шкалы: {scale} и {unit}. "
                    "Оставьте одну"
                )
            scale = unit
        elif scale == "US" and _GENDER_SUFFIX_RE.match(tail):
            scale = _canonical_scale("US" + tail)
        else:
            raise ValueError(
                f"не удалось разобрать размер: {text!r} — лишнее «{tail}» после "
                "числа. Нужен один размер: «42», «42,5», «42⅔», «42 2/3», "
                "со шкалой — «EU 42», «US W 7»"
            )
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
