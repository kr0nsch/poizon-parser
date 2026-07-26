"""Собирает официальные размерные таблицы брендов в data/size_charts.json.

Источники:
  * Nike     — nike.com/size-fit/mens-footwear (блок sizeCharts в HTML страницы)
  * Adidas   — adidas.com/us/help/size_charts (вкладка Shoes)
  * New Balance, ASICS — newbalance.com/size-guide.html и
    asics.com shoe-size-guide, полученные из подготовленной таблицы
    razmery_obuvi_new_balance_asics.xlsx

Смысл исходной колонки «см» зависит от бренда: у New Balance это официальная
длина стопы (Length (cm)), а у Nike и Adidas — маркировка CM/JP. Когда источник
публикует именно замер стопы, генератор дополнительно сохраняет его в поле
``foot``; сопоставление размера всегда опирается на это нормализованное поле.

Запуск:  python tools/build_size_charts.py [путь_к_xlsx]
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "poizon_parser" / "data" / "size_charts.json"
DEFAULT_XLSX = Path.home() / "Downloads" / "razmery_obuvi_new_balance_asics.xlsx"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


# --------------------------------------------------------------- утилиты

def num(value) -> float | None:
    """«42,5» / «36 2/3» / «27.5» → float."""
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text or text in {"--", "-", "—"}:
        return None
    # Смешанная дробь Adidas: «36 2/3».
    mixed = re.match(r"^(\d+)\s+(\d+)/(\d+)$", text)
    if mixed:
        whole, top, bottom = (int(g) for g in mixed.groups())
        return round(whole + top / bottom, 4)
    plain = re.match(r"^(\d+)/(\d+)$", text)
    if plain:
        top, bottom = (int(g) for g in plain.groups())
        return round(top / bottom, 4)
    try:
        return float(re.sub(r"[^0-9.]", "", text))
    except ValueError:
        return None


#: Поля строки таблицы. `cm` — опубликованная брендом колонка CM/JP/Length,
#: `foot` — реальная длина стопы, под которую бренд рекомендует этот размер.
FIELDS = ("us", "uk", "eu", "cm", "foot")


def rows_from_columns(columns: dict[str, list], keys: tuple[str, ...]) -> list[dict]:
    """Колонки одинаковой длины → список строк-словарей."""
    depth = min(len(columns[k]) for k in keys if k in columns)
    out = []
    for i in range(depth):
        row = {}
        for key in keys:
            if key not in columns:
                continue
            value = num(columns[key][i])
            if value is not None:
                row[key] = value
        if "eu" in row and ("us" in row or "foot" in row or "cm" in row):
            out.append(row)
    return out


# ------------------------------------------------------------------ xlsx

def read_xlsx(path: Path) -> dict[str, list[list[str]]]:
    """Читает книгу без сторонних зависимостей: zip + XML."""
    archive = zipfile.ZipFile(path)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in item.iter(f"{{{NS['m']}}}t")))

    rels = {}
    for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels")):
        rels[rel.get("Id")] = (rel.get("Target") or "").lstrip("/")

    def column_index(ref: str) -> int:
        letters = "".join(ch for ch in ref if ch.isalpha())
        index = 0
        for ch in letters:
            index = index * 26 + (ord(ch) - 64)
        return index - 1

    sheets: dict[str, list[list[str]]] = {}
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    for sheet in workbook.findall(".//m:sheet", NS):
        target = rels.get(sheet.get(REL_ID), "")
        if not target.startswith("xl/"):
            target = "xl/" + target
        data = ET.fromstring(archive.read(target))
        rows: list[list[str]] = []
        for row in data.findall(".//m:row", NS):
            cells: dict[int, str] = {}
            for cell in row.findall("m:c", NS):
                kind = cell.get("t")
                value_el = cell.find("m:v", NS)
                inline = cell.find("m:is", NS)
                if kind == "s" and value_el is not None:
                    text = shared[int(value_el.text)]
                elif kind == "inlineStr" and inline is not None:
                    text = "".join(t.text or "" for t in inline.iter(f"{{{NS['m']}}}t"))
                elif value_el is not None:
                    text = value_el.text or ""
                else:
                    continue
                cells[column_index(cell.get("r"))] = text
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        sheets[sheet.get("name")] = rows
    return sheets


def sheet_rows(
    rows: list[list[str]],
    mapping: dict[str, str],
    *,
    cm_is_foot_length: bool = False,
) -> list[dict]:
    """Ищет строку заголовков и собирает по ней размеры.

    ``cm_is_foot_length`` используется только когда официальный источник прямо
    называет колонку длиной стопы, а не размером CM/JP на ярлыке обуви.
    """
    header_at = None
    for index, row in enumerate(rows):
        cleaned = [c.strip() for c in row]
        if any(cell in mapping for cell in cleaned):
            header_at = index
            break
    if header_at is None:
        return []

    header = [c.strip() for c in rows[header_at]]
    positions = {mapping[c]: i for i, c in enumerate(header) if c in mapping}
    out = []
    for row in rows[header_at + 1:]:
        entry = {}
        for key, position in positions.items():
            if position < len(row):
                value = num(row[position])
                if value is not None:
                    entry[key] = value
        if cm_is_foot_length and "cm" in entry:
            entry["foot"] = entry["cm"]
        if "eu" in entry and ("us" in entry or "foot" in entry or "cm" in entry):
            out.append(entry)
    return out


# ------------------------------------------------------------------ Nike

def nike_charts(html_path: Path) -> dict:
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    start = html.index("[", html.find('"sizeCharts"'))
    depth = 0
    for pos in range(start, len(html)):
        if html[pos] == "[":
            depth += 1
        elif html[pos] == "]":
            depth -= 1
            if depth == 0:
                end = pos + 1
                break
    charts = json.loads(html[start:end])
    labels = {
        "US - Men": "us_m", "US - Women": "us_w", "UK": "uk",
        "CM / JP": "cm", "EU": "eu", "Foot Length (cm)": "foot",
    }
    columns: dict[str, list] = {}
    for row in charts[0]["data"]:
        values = [cell.get("value") for cell in row]
        key = labels.get(str(values[0]).strip())
        if key:
            columns[key] = values[1:]

    common = {"uk": columns["uk"], "eu": columns["eu"],
              "cm": columns["cm"], "foot": columns["foot"]}
    men = rows_from_columns({"us": columns["us_m"], **common}, FIELDS)
    women = rows_from_columns({"us": columns["us_w"], **common}, FIELDS)
    return {"men": men, "women": women}


# ---------------------------------------------------------------- Adidas

#: Снято с adidas.com/us/help/size_charts (вкладка Shoes, мужская сетка).
ADIDAS_RAW = {
    "us_m": "4 4.5 5 5.5 6 6.5 7 7.5 8 8.5 9 9.5 10 10.5 11 11.5 12 12.5 13 13.5 14 14.5 15 16 17 18 19 20",
    "us_w": "5 5.5 6 6.5 7 7.5 8 8.5 9 9.5 10 10.5 11 11.5 12 12.5 13 13.5 14 14.5 15 15.5 -- -- -- -- -- --",
    "uk": "3.5 4 4.5 5 5.5 6 6.5 7 7.5 8 8.5 9 9.5 10 10.5 11 11.5 12 12.5 13 13.5 14 14.5 15 16 17 18 19",
    "eu": ("36|36 2/3|37 1/3|38|38 2/3|39 1/3|40|40 2/3|41 1/3|42|42 2/3|43 1/3|44|44 2/3|"
           "45 1/3|46|46 2/3|47 1/3|48|48 2/3|49 1/3|50|50 2/3|51 1/3|52 2/3|53 1/3|54 2/3|55 2/3"),
    "heel_toe": ("22.1 22.5 22.9 23.3 23.8 24.2 24.6 25.0 25.5 25.9 26.3 26.7 27.1 27.6 28.0 28.4 "
                 "28.8 29.3 29.7 30.1 30.5 31.0 31.4 31.8 32.6 33.5 34.3 35.2"),
    "jp": ("220 225 230 235 240 245 250 255 260 265 270 275 280 285 290 295 300 305 310 315 "
           "320 325 -- -- -- -- -- --"),
}


def adidas_charts() -> dict:
    common = {
        "uk": ADIDAS_RAW["uk"].split(),
        "eu": ADIDAS_RAW["eu"].split("|"),
        # Ярлык в сантиметрах у Adidas — это колонка JP (220 → 22,0).
        "cm": [v if v == "--" else str(num(v) / 10) for v in ADIDAS_RAW["jp"].split()],
        # А «heel-to-toe» — это уже замер стопы.
        "foot": ADIDAS_RAW["heel_toe"].split(),
    }
    men = rows_from_columns({"us": ADIDAS_RAW["us_m"].split(), **common}, FIELDS)
    women = rows_from_columns({"us": ADIDAS_RAW["us_w"].split(), **common}, FIELDS)
    return {"men": men, "women": women}


# ------------------------------------------------------------------ сбор

def main() -> int:
    xlsx_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    charts: dict[str, dict] = {}

    nike_html = ROOT / "tools" / "cache" / "nike-size-fit.html"
    if nike_html.exists():
        data = nike_charts(nike_html)
        charts["nike"] = {
            "name": "Nike",
            "source": "https://www.nike.com/size-fit/mens-footwear",
            **data,
        }
    else:
        print(f"! нет {nike_html} — таблица Nike пропущена", file=sys.stderr)

    charts["adidas"] = {
        "name": "Adidas",
        "source": "https://www.adidas.com/us/help/size_charts",
        **adidas_charts(),
    }

    if xlsx_path.exists():
        sheets = read_xlsx(xlsx_path)
        nb_men = sheet_rows(
            sheets.get("NB Мужские", []),
            {
                "US муж.": "us",
                "UK": "uk",
                "EU": "eu",
                "Длина стопы, см": "cm",
            },
            cm_is_foot_length=True,
        )
        nb_women = sheet_rows(
            sheets.get("NB Женские", []),
            {
                "US жен.": "us",
                "UK": "uk",
                "EU": "eu",
                "Длина стопы, см": "cm",
            },
            cm_is_foot_length=True,
        )
        charts["new-balance"] = {
            "name": "New Balance",
            "source": "https://www.newbalance.com/size-guide.html",
            "men": nb_men, "women": nb_women,
        }

        asics_men = sheet_rows(sheets.get("ASICS Мужские", []), {
            "US": "us", "UK": "uk", "EU": "eu", "Длина стопы, см": "cm",
        })
        asics_women = sheet_rows(sheets.get("ASICS Женские", []), {
            "US": "us", "UK": "uk", "EU": "eu", "Длина стопы, см": "cm",
        })
        charts["asics"] = {
            "name": "ASICS",
            "source": "https://www.asics.com/us/en-us/aligned-size-charts/",
            "men": asics_men, "women": asics_women,
        }
    else:
        print(f"! нет {xlsx_path} — New Balance и ASICS пропущены", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(charts, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for key, chart in charts.items():
        print(f"{key:<13} муж. {len(chart['men']):>2} строк · жен. {len(chart['women']):>2} строк")
    print(f"\nсохранено: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
