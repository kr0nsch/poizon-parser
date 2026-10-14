"""Собирает версионированный снимок официальных размерных таблиц.

Все значения ниже вручную сверены с официальными сайтами производителей и
хранятся прямо в репозитории. Генератор намеренно не зависит от локального
Excel, HTML-кэша или доступности сети: повторный запуск всегда даёт одинаковый
``poizon_parser/data/size_charts.json``.

Источники:
  * Nike men/women — nike.com/size-fit/*-footwear
  * Adidas — adidas.com/us/help/size_charts/shoes
  * New Balance — newbalance.com/size-guide.html
  * ASICS — me.asics.com/en-qa/shoe-size-guide
  * Reebok — reebok.eu («Size guide» на карточке) + reebok.com/pages/size-guides
  * PUMA — vn.puma.com (единственная страница PUMA с колонкой JPN/CM)

Запуск: python tools/build_size_charts.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "poizon_parser" / "data" / "size_charts.json"

#: Дата ручной сверки каждой таблицы с сайтом производителя. Отдельная на
#: бренд: добавление нового бренда не должно выдавать старые таблицы за
#: только что перепроверенные.
VERIFIED_AT = {
    "nike": "2026-07-26",
    "adidas": "2026-07-26",
    "new-balance": "2026-07-26",
    "asics": "2026-07-26",
    "reebok": "2026-07-27",
    "puma": "2026-07-27",
}

# `cm` — опубликованная брендом колонка CM/JP/Length.
# `foot` — значение, с которым официальный источник предлагает сопоставлять
# замер стопы. У Nike и Adidas оно отличается от маркировки CM/JP.
FIELDS = ("us", "uk", "eu", "cm", "foot")


def num(value) -> float | None:
    """«42,5» / «36 2/3» / «27.5» → float."""
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text or text in {"--", "-", "—"}:
        return None
    mixed = re.match(r"^(\d+)\s+(\d+)/(\d+)$", text)
    if mixed:
        whole, top, bottom = (int(group) for group in mixed.groups())
        return round(whole + top / bottom, 4)
    plain = re.match(r"^(\d+)/(\d+)$", text)
    if plain:
        top, bottom = (int(group) for group in plain.groups())
        return round(top / bottom, 4)
    try:
        return float(re.sub(r"[^0-9.]", "", text))
    except ValueError:
        return None


def inches_to_cm(values: str) -> str:
    """Колонка дюймов → сантиметры с одним знаком.

    Reebok публикует замер стопы только в дюймах, поэтому в файле остаются
    исходные официальные значения, а перевод виден здесь.
    """
    out = []
    for item in values.split("|"):
        value = num(item)
        out.append("--" if value is None else f"{round(value * 2.54, 1):g}")
    return "|".join(out)


def columns(raw: dict[str, str]) -> dict[str, list[str]]:
    """Компактные колонки с разделителем ``|`` → списки значений."""
    return {key: values.split("|") for key, values in raw.items()}


def rows_from_columns(raw: dict[str, str]) -> list[dict[str, float]]:
    """Официальные колонки одинаковой длины → строки таблицы."""
    parsed = columns(raw)
    lengths = {len(values) for values in parsed.values()}
    if len(lengths) != 1:
        raise ValueError(f"Длины колонок не совпадают: {sorted(lengths)}")

    rows: list[dict[str, float]] = []
    for index in range(lengths.pop()):
        row = {}
        for key in FIELDS:
            if key not in parsed:
                continue
            value = num(parsed[key][index])
            if value is not None:
                row[key] = value
        if "eu" not in row:
            raise ValueError(f"В строке {index} отсутствует EU")
        rows.append(row)
    return rows


# Nike хранит CM/JP и фактическую Foot Length отдельными колонками.
NIKE_MEN = {
    "us": "3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|14.5|15|15.5|16|16.5|17|17.5|18|18.5|19|19.5|20|20.5|21|21.5|22",
    "uk": "3|3.5|4|4.5|5|5.5|6|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|14.5|15|15.5|16|16.5|17|17.5|18|18.5|19|19.5|20|20.5|21",
    "eu": "35.5|36|36.5|37.5|38|38.5|39|40|40.5|41|42|42.5|43|44|44.5|45|45.5|46|47|47.5|48|48.5|49|49.5|50|50.5|51|51.5|52|52.5|53|53.5|54|54.5|55|55.5|56|56.5",
    "cm": "22.5|23|23.5|23.5|24|24|24.5|25|25.5|26|26.5|27|27.5|28|28.5|29|29.5|30|30.5|31|31.5|32|32.5|33|33.5|34|34.5|35|35.5|36|36.5|37|37.5|38|38.5|39|39.5|40",
    "foot": "21.6|22|22.4|22.9|23.3|23.7|24.1|24.5|25|25.4|25.8|26.2|26.7|27.1|27.5|27.9|28.3|28.8|29.2|29.6|30|30.5|30.9|31.3|31.7|32.2|32.6|33|33.4|33.9|34.3|34.7|35.1|35.5|36|36.4|36.8|37.2",
}

NIKE_WOMEN = {
    "us": "3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|14.5|15|15.5|16|16.5|17|17.5|18|18.5|19|19.5|20|20.5|21|21.5|22|22.5",
    "uk": "1.5|1.5|2|2.5|3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|14.5|15|15.5|16|16.5|17|17.5|18|18.5|19|19.5|20",
    "eu": "33.5|34.5|35|35.5|36|36.5|37.5|38|38.5|39|40|40.5|41|42|42.5|43|44|44.5|45|45.5|46|47|47.5|48|48.5|49|50|50.5|51|51.5|52|52.5|53|53.5|54|54.5|55|55.5|56",
    "cm": "21|21|21.5|22|22.5|23|23.5|24|24.5|25|25.5|26|26.5|27|27.5|28|28.5|29|29.5|30|30.5|31|31.5|32|32.5|33|33.5|34|34.5|35|35.5|36|36.5|37|37.5|38|38.5|39|39.5",
    "foot": "20.8|21.2|21.6|22|22.4|22.9|23.3|23.7|24.1|24.5|25|25.4|25.8|26.2|26.7|27.1|27.5|27.9|28.3|28.8|29.2|29.6|30|30.5|30.9|31.3|31.7|32.2|--|--|--|--|--|--|--|--|--|--|--",
}


# Adidas: JP — маркировка, Heel-toe — фактический замер стопы.
ADIDAS_COMMON = {
    "uk": "3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|14.5|15|16|17|18|19",
    "eu": "36|36 2/3|37 1/3|38|38 2/3|39 1/3|40|40 2/3|41 1/3|42|42 2/3|43 1/3|44|44 2/3|45 1/3|46|46 2/3|47 1/3|48|48 2/3|49 1/3|50|50 2/3|51 1/3|52 2/3|53 1/3|54 2/3|55 2/3",
    "cm": "22|22.5|23|23.5|24|24.5|25|25.5|26|26.5|27|27.5|28|28.5|29|29.5|30|30.5|31|31.5|32|32.5|--|--|--|--|--|--",
    "foot": "22.1|22.5|22.9|23.3|23.8|24.2|24.6|25|25.5|25.9|26.3|26.7|27.1|27.6|28|28.4|28.8|29.3|29.7|30.1|30.5|31|31.4|31.8|32.6|33.5|34.3|35.2",
}
ADIDAS_MEN_US = "4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|14.5|15|16|17|18|19|20"
ADIDAS_WOMEN_US = "5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|14.5|15|15.5|--|--|--|--|--|--"


# New Balance называет опубликованную колонку Length (cm); для сервиса это
# одновременно `cm` и `foot`.
NEW_BALANCE_MEN = {
    "us": "2.5|3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|15|16|17|18|19|20",
    "uk": "2|2.5|3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14.5|15.5|16.5|17.5|18.5|19.5",
    "eu": "34|35|35.5|36|37|37.5|38|38.5|39.5|40|40.5|41.5|42|42.5|43|44|44.5|45|45.5|46.5|47|47.5|48.5|49|50|51|52|53|54|55",
    "cm": "20.5|21|21.5|22|22.5|23|23.5|24|24.5|25|25.5|26|26.5|27|27.5|28|28.5|29|29.5|30|30.5|31|31.5|32|33|34|35|36|37|38",
    "foot": "20.5|21|21.5|22|22.5|23|23.5|24|24.5|25|25.5|26|26.5|27|27.5|28|28.5|29|29.5|30|30.5|31|31.5|32|33|34|35|36|37|38",
}
NEW_BALANCE_WOMEN = {
    "us": "3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|15|16",
    "uk": "1|1.5|2|2.5|3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|13|14",
    "eu": "33|33.5|34|34.5|35|36|36.5|37|37.5|38|39|40|40.5|41|41.5|42.5|43|43.5|44|45|45.5|46|46.5|48|49",
    "cm": "20|20.5|21|21.5|22|22.5|23|23.5|24|24.5|25|25.5|26|26.5|27|27.5|28|28.5|29|29.5|30|30.5|31|32|32.5",
    "foot": "20|20.5|21|21.5|22|22.5|23|23.5|24|24.5|25|25.5|26|26.5|27|27.5|28|28.5|29|29.5|30|30.5|31|32|32.5",
}


# Официальная ASICS-страница предлагает измерить стопу от пятки до самого
# длинного пальца и сопоставить результат с колонкой CM этой таблицы.
ASICS_MEN = {
    "us": "4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|14|15|16|17|18",
    "uk": "3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|13|14|15|16|17",
    "eu": "36|37|37.5|38|39|39.5|40|40.5|41.5|42|42.5|43.5|44|44.5|45|46|46.5|47|48|49|50.5|51.5|53|54",
    "cm": "22.5|23|23.5|24|24.5|25|25.25|25.5|26|26.5|27|27.5|28|28.25|28.5|29|29.5|30|30.5|31|32|33|34|34.5",
    "foot": "22.5|23|23.5|24|24.5|25|25.25|25.5|26|26.5|27|27.5|28|28.25|28.5|29|29.5|30|30.5|31|32|33|34|34.5",
}
ASICS_WOMEN = {
    "us": "5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14",
    "uk": "3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12",
    "eu": "35.5|36|37|37.5|38|39|39.5|40|40.5|41.5|42|42.5|43.5|44|44.5|45|46|46.5|47",
    "cm": "22.5|22.75|23|23.5|24|24.5|25|25.5|25.75|26|26.5|27|27.5|28|28.5|28.75|29|29.5|30",
    "foot": "22.5|22.75|23|23.5|24|24.5|25|25.5|25.75|26|26.5|27|27.5|28|28.5|28.75|29|29.5|30",
}


# Reebok раздаёт сетку двумя официальными кусками. Соответствие EU/UK/US —
# из «Size guide» на карточке товара reebok.eu (таблицы «Unisex Shoes» и
# «Womens Shoes»). Замер стопы — только на reebok.com и только в дюймах
# (колонка «Heel-Toe Measurement»), поэтому дюймы и лежат в источнике.
REEBOK_MEN_FOOT_IN = (
    "8.3|8.5|8.7|8.8|9|9.2|9.3|9.5|9.7|9.8|10|10.2|10.3|10.5|10.7|10.8|11|"
    "11.2|11.3|11.5|11.7|11.8|12|12.3|12.6|13"
)
REEBOK_MEN = {
    "us": "3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14|15|16|17",
    "uk": "2|2.5|3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|14|15|16",
    "eu": "33|34|34.5|35|36|36.5|37.5|38.5|39|40|40.5|41|42|42.5|43|44|44.5|45|45.5|46|47|48|48.5|50|52|53.5",
    "foot": inches_to_cm(REEBOK_MEN_FOOT_IN),
}

REEBOK_WOMEN_FOOT_IN = (
    "8|8.2|8.3|8.5|8.7|8.8|9|9.2|9.3|9.5|9.7|9.8|10|10.2|10.3|10.5|10.7|10.8|"
    "11|11.2|11.3|11.5"
)
REEBOK_WOMEN = {
    "us": "3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|13.5|14",
    "uk": "1|1.5|2|2.5|3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5",
    "eu": "33|34|34.5|35|35.5|36|37|37.5|38|38.5|39|40|40.5|41|42|42.5|43|44|44.5|45|46|47",
    "foot": inches_to_cm(REEBOK_WOMEN_FOOT_IN),
}


# PUMA нигде не публикует длину стопы — только ярлык JPN/CM (у Nike и Adidas
# такой же ярлык «27 см» стоит на паре под замер 26,2–26,3 см). Поэтому колонки
# `foot` у PUMA нет: по замеру стопы бренд остаётся на общей сетке с «≈»,
# а перевод US / UK / EU идёт по официальной таблице.
# Мужская колонка — из таблицы «Unisex Shoes» (US (Men)), женская — из «Women».
PUMA_MEN = {
    "us": "4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|12.5|13|14|15|16",
    "uk": "3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11|11.5|12|13|14|15",
    "eu": "35.5|36|37|37.5|38|38.5|39|40|40.5|41|42|42.5|43|44|44.5|45|46|46.5|47|48.5|49.5|51",
    "cm": "22|22.5|23|23.5|24|24.5|25|25.5|26|26.5|27|27.5|28|28.5|29|29.5|30|30.5|31|32|--|--",
}
PUMA_WOMEN = {
    "us": "5.5|6|6.5|7|7.5|8|8.5|9|9.5|10|10.5|11",
    "uk": "3|3.5|4|4.5|5|5.5|6|6.5|7|7.5|8|8.5",
    "eu": "35.5|36|37|37.5|38|38.5|39|40|40.5|41|42|42.5",
    "cm": "22|22.5|23|23.5|24|24.5|25|25.5|26|26.5|27|27.5",
}


EXPECTED_ROWS = {
    "nike": {"men": 38, "women": 39, "foot_men": 38, "foot_women": 28},
    "adidas": {"men": 28, "women": 28, "foot_men": 28, "foot_women": 28},
    "new-balance": {"men": 30, "women": 25, "foot_men": 30, "foot_women": 25},
    "asics": {"men": 24, "women": 19, "foot_men": 24, "foot_women": 19},
    "reebok": {"men": 26, "women": 22, "foot_men": 26, "foot_women": 22},
    # PUMA не публикует замер стопы ни на одном своём сайте — колонки нет.
    "puma": {"men": 22, "women": 12, "foot_men": 0, "foot_women": 0},
}


def build_charts() -> dict[str, dict]:
    """Возвращает полный официальный снимок без внешних зависимостей."""
    charts = {
        "nike": {
            "name": "Nike",
            "source": "https://www.nike.com/size-fit/mens-footwear",
            "sources": {
                "men": "https://www.nike.com/size-fit/mens-footwear",
                "women": "https://www.nike.com/size-fit/womens-footwear",
            },
            "locale": "en-US",
            "verified_at": VERIFIED_AT["nike"],
            "men": rows_from_columns(NIKE_MEN),
            "women": rows_from_columns(NIKE_WOMEN),
        },
        "adidas": {
            "name": "Adidas",
            "source": "https://www.adidas.com/us/help/size_charts/shoes",
            "sources": {
                "men": "https://www.adidas.com/us/help/size_charts/shoes",
                "women": "https://www.adidas.com/us/help/size_charts/shoes",
            },
            "locale": "en-US",
            "verified_at": VERIFIED_AT["adidas"],
            "men": rows_from_columns({"us": ADIDAS_MEN_US, **ADIDAS_COMMON}),
            "women": rows_from_columns({"us": ADIDAS_WOMEN_US, **ADIDAS_COMMON}),
        },
        "new-balance": {
            "name": "New Balance",
            "source": "https://www.newbalance.com/size-guide.html",
            "sources": {
                "men": "https://www.newbalance.com/size-guide.html",
                "women": "https://www.newbalance.com/size-guide.html",
            },
            "locale": "en-US",
            "verified_at": VERIFIED_AT["new-balance"],
            "men": rows_from_columns(NEW_BALANCE_MEN),
            "women": rows_from_columns(NEW_BALANCE_WOMEN),
        },
        "asics": {
            "name": "ASICS",
            "source": "https://me.asics.com/en-qa/shoe-size-guide",
            "sources": {
                "men": "https://me.asics.com/en-qa/shoe-size-guide",
                "women": "https://me.asics.com/en-qa/shoe-size-guide",
            },
            "locale": "en-QA",
            "verified_at": VERIFIED_AT["asics"],
            "men": rows_from_columns(ASICS_MEN),
            "women": rows_from_columns(ASICS_WOMEN),
        },
        "reebok": {
            "name": "Reebok",
            "source": "https://www.reebok.com/pages/size-guides",
            "sources": {
                # Сетку EU/UK/US Reebok показывает только в модальном окне
                # «Size guide» на карточке товара — отдельного адреса у неё нет.
                "men": "https://www.reebok.eu/collections/mens-shoes",
                "women": "https://www.reebok.eu/collections/womens-shoes",
                "foot": "https://www.reebok.com/pages/size-guides",
            },
            "locale": "en-GB",
            "verified_at": VERIFIED_AT["reebok"],
            "men": rows_from_columns(REEBOK_MEN),
            "women": rows_from_columns(REEBOK_WOMEN),
        },
        "puma": {
            "name": "Puma",
            "source": "https://vn.puma.com/vn/en/VN-size-guide-footer-2025.html",
            "sources": {
                "men": "https://vn.puma.com/vn/en/VN-size-guide-footer-2025.html",
                "women": "https://vn.puma.com/vn/en/VN-size-guide-footer-2025.html",
            },
            "locale": "en-VN",
            "verified_at": VERIFIED_AT["puma"],
            "men": rows_from_columns(PUMA_MEN),
            "women": rows_from_columns(PUMA_WOMEN),
        },
    }
    validate_charts(charts)
    return charts


def validate_charts(charts: dict[str, dict]) -> None:
    """Не позволяет записать неполный или повреждённый официальный снимок."""
    if set(charts) != set(EXPECTED_ROWS):
        raise ValueError("Набор брендов не совпадает с ожидаемым")

    for key, chart in charts.items():
        expected = EXPECTED_ROWS[key]
        if not str(chart["source"]).startswith("https://"):
            raise ValueError(f"{key}: отсутствует официальный HTTPS-источник")
        if chart.get("verified_at") != VERIFIED_AT[key]:
            raise ValueError(f"{key}: отсутствует дата сверки")

        for gender in ("men", "women"):
            rows = chart[gender]
            if len(rows) != expected[gender]:
                raise ValueError(
                    f"{key}/{gender}: ожидалось {expected[gender]} строк, "
                    f"получено {len(rows)}"
                )
            eus = [row["eu"] for row in rows]
            if eus != sorted(eus):
                raise ValueError(f"{key}/{gender}: EU-ряд не отсортирован")
            feet = [row["foot"] for row in rows if "foot" in row]
            if len(feet) != expected[f"foot_{gender}"]:
                raise ValueError(f"{key}/{gender}: неполная колонка длины стопы")
            if feet != sorted(feet):
                raise ValueError(f"{key}/{gender}: длины стопы не отсортированы")


def main() -> int:
    charts = build_charts()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(charts, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    for key, chart in charts.items():
        print(
            f"{key:<13} муж. {len(chart['men']):>2} строк · "
            f"жен. {len(chart['women']):>2} строк"
        )
    print(f"\nсохранено: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
