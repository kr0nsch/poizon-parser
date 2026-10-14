"""Конвертация размерных шкал.

Зачем это нужно. POIZON подписывает каждый SKU двумя шкалами — «RU» и «EU», —
причём его «RU» равен EU минус единица. Официальные сайты производителей так
размеры не маркируют: то, что Nike называет EU 42, на POIZON лежит под ярлыком
«RU 41 / EU 42». Поэтому шкала по умолчанию здесь — EU, а не POIZON-овская RU.

Шкалы US / UK / CM в SKU не публикуются вовсе, и таблица `sizeAssistantModule`
товара отдаёт лишь **три опорные строки** — самые маленькие размеры. Их мало:
у Nike US M 3,5 = EU 35,5 при смещении ровно 32, но к US M 13 смещение вырастает
до ~34,5 (US-шаг мельче EU-шага). Линейная экстраполяция от трёх строк на этом
промахивается на 2–2,5 размера.

Для Nike, Adidas, New Balance, ASICS, Reebok и Puma перевод идёт по
захардкоженному снимку официальных мужских и женских таблиц. Межбрендовые
подстановки запрещены: если бренд какую-то шкалу не публикует, она не
подставляется из чужой сетки. US/UK тогда переводятся по таблице конкретного
товара, затем по встроенной **эталонной лестнице** (`_STANDARD_LADDER`), а
длина стопы (Puma нигде её не даёт) — по **общей сетке стопы**
(`generic_foot_to_eu`): медиане всех официальных таблиц с замером стопы.
Неточный перевод помечается «≈».

Почему у длины стопы своя сетка. Сантиметры на ярлыке (CM/JP) и в колонке
«Длина стопы» карточки POIZON — это маркировка пары, а не замер: у Nike ярлык
«27 см» стоит на паре под стопу 26,2 см. Замер, сравнённый с ярлыком, давал
размер на 1–2 EU меньше (стопа 26,5 см выходила EU 41 вместо 42–43⅓).

Про «US» и «US мужской». В кроссовочном контексте «US» без уточнения — это
**мужская** шкала (US_MEN). Женская (US_WOMEN) для той же пары примерно на 1,5
размера больше: US W 5 и US M 3,5 — это одна и та же обувь (EU 35,5). Поэтому US 13
как мужской — это EU 47,5, а как женский — EU ~45,5. Выбор шкалы важен.
"""

from __future__ import annotations

import bisect
import json
import statistics
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .sizes import SIZE_EPSILON, parse_size

# Канонические имена шкал внутри парсера.
EU = "EU"
RU = "RU"
UK = "UK"
US_MEN = "US M"
US_WOMEN = "US W"
CM = "CM"
MM = "MM"

#: Шкалы, которые POIZON публикует для каждого SKU — перевод не нужен.
NATIVE_SCALES = (RU, EU)

#: Как называются шкалы в таблице `sizeAssistantModule`.
_TABLE_KEYS = {
    "EU": EU,
    "RU": RU,
    "UK": UK,
    "US Мужские": US_MEN,
    "US Женские": US_WOMEN,
    "Длина стопы": CM,
}

_ALIASES = {
    "EU": EU, "ЕВРО": EU, "EUR": EU,
    "RU": RU, "РУ": RU,
    "UK": UK, "БРИТ": UK,
    "US": US_MEN, "USM": US_MEN, "US M": US_MEN, "US МУЖСКИЕ": US_MEN,
    "USW": US_WOMEN, "US W": US_WOMEN, "US ЖЕНСКИЕ": US_WOMEN,
    "CM": CM, "СМ": CM, "MM": MM,
}

#: Эталонная лестница атлетической размерной сетки (Nike/стандарт).
#: Каждая строка — один физический размер во всех шкалах; EU-колонка совпадает
#: с реальным рядом EU-размеров, которым POIZON подписывает SKU.
#: Формат строки: (EU, US_MEN, US_WOMEN, UK).
#:
#: Колонки длины стопы здесь нет намеренно. Прежний сантиметровый ряд был
#: ярлыком CM/JP (EU 42 = 27 см, как у Puma), и замер стопы по нему уходил на
#: 1–2 размера вниз. Длину стопы переводит generic_foot_to_eu.
_STANDARD_LADDER: tuple[tuple[float, float, float, float], ...] = (
    (35.5, 3.5, 5.0, 3.0),
    (36.0, 4.0, 5.5, 3.5),
    (36.5, 4.5, 6.0, 4.0),
    (37.5, 5.0, 6.5, 4.5),
    (38.0, 5.5, 7.0, 5.0),
    (38.5, 6.0, 7.5, 5.5),
    (39.0, 6.5, 8.0, 6.0),
    (40.0, 7.0, 8.5, 6.5),
    (40.5, 7.5, 9.0, 7.0),
    (41.0, 8.0, 9.5, 7.5),
    (42.0, 8.5, 10.0, 8.0),
    (42.5, 9.0, 10.5, 8.5),
    (43.0, 9.5, 11.0, 9.0),
    (44.0, 10.0, 11.5, 9.5),
    (44.5, 10.5, 12.0, 10.0),
    (45.0, 11.0, 12.5, 10.5),
    (45.5, 11.5, 13.0, 11.0),
    (46.0, 12.0, 13.5, 11.5),
    (47.0, 12.5, 14.0, 12.0),
    (47.5, 13.0, 14.5, 12.5),
    (48.0, 13.5, 15.0, 13.0),
    (48.5, 14.0, 15.5, 13.5),
    (49.5, 15.0, 16.5, 14.5),
)

_LADDER_COLUMN = {
    EU: 0, US_MEN: 1, US_WOMEN: 2, UK: 3,
}

#: Запасные смещения — только если размер вышел за пределы эталонной лестницы.
#: Значение прибавляется к размеру, чтобы получить EU: eu = value + offset.
#: CM — замер стопы, и нужен он, лишь когда официальных таблиц нет вовсе:
#: по общей сетке стопы 26,5 см — это EU 42,5.
_FALLBACK_OFFSET = {
    EU: 0.0,
    RU: 1.0,
    UK: 32.5,
    US_MEN: 34.5,
    US_WOMEN: 33.0,
    CM: 16.0,
}

#: Сколько официальных таблиц должны покрывать замер, чтобы их медиана была
#: общей сеткой, а не сеткой одного-двух брендов.
_FOOT_REFERENCE_MIN_BRANDS = 3
#: Шаг EU-размера — штих, ⅔ см: сантиметр стопы — полтора EU-размера.
_EU_PER_CM = 1.5


def _ladder_to_eu(scale: str, value: float) -> Optional[float]:
    """Переводит размер в EU по эталонной лестнице (ближайшая строка)."""
    column = _LADDER_COLUMN.get(scale)
    if column is None:
        return None
    best_eu: Optional[float] = None
    best_delta = float("inf")
    for row in _STANDARD_LADDER:
        delta = abs(row[column] - value)
        if delta < best_delta:
            best_delta = delta
            best_eu = row[0]
    # Слишком далеко от любой строки — лестница не покрывает такой размер.
    if best_delta > 0.34:
        return None
    return best_eu


def normalize_scale(name: Optional[str]) -> Optional[str]:
    """«us m», «usw», «см», «евро»… → канонический код шкалы.

    Незнакомое имя возвращается как есть, в верхнем регистре.
    """
    if not name:
        return None
    key = str(name).strip().upper().replace("_", " ")
    if key in _ALIASES:
        return _ALIASES[key]
    key2 = key.replace(" ", "")
    return _ALIASES.get(key2, key or None)


def resolve_query_scale(
    parsed_scale: Optional[str],
    explicit_scale: Optional[str],
    default: Optional[str] = None,
) -> Optional[str]:
    """Шкала поиска: написанная в размере («US W 7») или выбранная явно.

    Одно правило для CLI, веб-сервера и SizeFinder — раньше каждый решал
    по-своему, и «-s "US 7" --scale "US W"» в одном месте искал женский US 7,
    а в другом мужской:

    - шкала из строки размера главнее явной: «EU 43», «US W 7», «MM 265»
      при --scale CM — это EU, US W и MM;
    - кроме голого «US»: пол оно не задаёт и потому не перебивает явно
      выбранную «US M» / «US W». Без такой явной шкалы голое «US» — мужская,
      как и везде в кроссовочном контексте;
    - в размере шкалы нет — явная, а без неё — default.

    Возвращает каноническое имя шкалы (см. normalize_scale) или default.
    SizeFinder.find() и find_in_products() сравнивают размер с ярлыками SKU
    без перевода, поэтому сверх этого правила отклоняют шкалы, кроме RU и EU,
    и расхождение шкалы в размере с явной — как и команда find.
    """
    explicit = normalize_scale(explicit_scale)
    if parsed_scale:
        bare_us = str(parsed_scale).strip().upper() == "US"
        if not (bare_us and explicit in (US_MEN, US_WOMEN)):
            return normalize_scale(parsed_scale)
    return explicit or default


@dataclass
class Conversion:
    """Результат перевода размера в шкалу EU."""

    eu: float
    exact: bool
    source: str  # "brand" | "native" | "table" | "standard" | "fallback"
    note: str = ""
    cm: Optional[float] = None
    foot: Optional[float] = None
    brand: str = ""
    supported: bool = True


# ------------------------------------------------- официальные таблицы брендов

_CHARTS_PATH = Path(__file__).resolve().parent / "data" / "size_charts.json"

#: Как названия брендов на POIZON сводятся к ключу таблицы.
_BRAND_ALIASES = {
    "nike": "nike",
    "jordan": "nike",           # Jordan — линейка Nike, сетка та же
    "air jordan": "nike",
    "adidas": "adidas",
    "adidas neo": "adidas",
    "adidas originals": "adidas",
    "adidas terrex": "adidas",
    "new balance": "new-balance",
    "newbalance": "new-balance",
    "nb": "new-balance",
    "asics": "asics",
    "reebok": "reebok",
    "puma": "puma",
}


@dataclass
class BrandChart:
    """Официальная размерная таблица бренда.

    Строки — физические размеры: {us, uk, eu, cm, foot}. Мужская и женская
    сетки хранятся раздельно и имеют собственные официальные строки.
    """

    key: str
    name: str
    source: str
    sources: dict[str, str] = field(default_factory=dict)
    locale: str = ""
    verified_at: str = ""
    men: list[dict[str, float]] = field(default_factory=list)
    women: list[dict[str, float]] = field(default_factory=list)

    def rows(self, gender: str = "men") -> list[dict[str, float]]:
        return self.women if gender == "women" else self.men

    def has_foot_column(self, gender: str = "men") -> bool:
        """Публикует ли бренд длину стопы (а не только ярлык в сантиметрах)."""
        return any("foot" in row for row in self.rows(gender))

    @staticmethod
    def _column(scale: str, gender: str) -> Optional[tuple[str, str]]:
        """Шкала ввода → (сетка, колонка таблицы); US W/US M задают сетку сами."""
        scale = normalize_scale(scale) or scale
        if scale == CM:
            return gender, "foot"
        if scale == US_WOMEN:
            return "women", "us"
        if scale == US_MEN:
            return "men", "us"
        if scale == UK:
            return gender, "uk"
        if scale == EU:
            return gender, "eu"
        return None

    def publishes(self, scale: str, gender: str = "men") -> bool:
        """Есть ли эта шкала в официальной таблице бренда.

        Отличать «шкалы нет в таблице» от «размер вне таблицы» обязательно: в
        первом случае перевод честно уходит на общую сетку, во втором размер
        для бренда просто не существует. Puma, например, публикует US/UK/EU,
        но нигде не даёт длину стопы.
        """
        return self.published_range(scale, gender) is not None

    def published_range(
        self, scale: str, gender: str = "men"
    ) -> Optional[tuple[float, float]]:
        """Наименьшее и наибольшее значение шкалы в таблице бренда.

        Для CM — длина стопы (колонку ярлыка CM/JP с ней не путаем). None —
        шкалу бренд не публикует. Нужен, чтобы подсказать, какой размер в
        таблице вообще есть, когда запрошенный в неё не попал.
        """
        values = self.published_values(scale, gender)
        return (values[0], values[-1]) if values else None

    def published_values(self, scale: str, gender: str = "men") -> list[float]:
        """Все значения шкалы в таблице бренда, по возрастанию (пусто — нет шкалы).

        Между крайними значениями бывают пропуски: у Adidas после US 15 идут
        только целые размеры, поэтому US 15,5 в таблице нет, хотя он «внутри».
        """
        target = self._column(scale, gender)
        if target is None:
            return []
        grid, column = target
        return sorted({row[column] for row in self.rows(grid) if column in row})

    def by_foot(self, foot_cm: float, gender: str = "men") -> Optional[dict]:
        """Строка таблицы по замеру стопы.

        Используется только собственная колонка ``foot`` бренда. Межбрендовые
        подстановки запрещены: неполная официальная сетка должна вернуть
        ``None``, а не незаметно перейти на шкалу другого производителя.
        """
        rows = self.rows(gender)
        if not rows:
            return None

        measured_rows = sorted(
            (row for row in rows if "foot" in row),
            key=lambda row: row["foot"],
        )
        if not measured_rows:
            return None
        if (
            foot_cm < measured_rows[0]["foot"] - SIZE_EPSILON
            or foot_cm > measured_rows[-1]["foot"] + SIZE_EPSILON
        ):
            return None
        best = next(
            (
                row for row in measured_rows
                if row["foot"] >= foot_cm - SIZE_EPSILON
            ),
            None,
        )
        return best

    def to_eu(
        self, scale: str, value: float, gender: str = "men"
    ) -> Optional[Conversion]:
        """Размер в шкале бренда → EU по его официальной таблице."""
        scale = normalize_scale(scale) or scale
        if scale == US_WOMEN:
            gender, column = "women", "us"
        elif scale == US_MEN:
            gender, column = "men", "us"
        elif scale == UK:
            column = "uk"
        elif scale == CM:
            row = self.by_foot(value, gender)
            if row is None:
                return None
            gender_label = "женская" if gender == "women" else "мужская"
            note = f"по официальной таблице {self.name} ({gender_label} сетка)"
            matched_foot = row.get("foot")
            exact = (
                matched_foot is not None
                and abs(matched_foot - value) <= SIZE_EPSILON
            )
            if matched_foot is not None and not exact:
                foot_label = f"{matched_foot:g}".replace(".", ",")
                note += f", ближайшая длина стопы {foot_label} см"
            # В cm отдаём опубликованную брендом колонку CM/JP/Length: по ней
            # удобно сверяться с маркировкой карточки POIZON. Пользовательский
            # замер сюда не подставляем, если источник различает эти величины.
            return Conversion(
                eu=row["eu"],
                exact=exact,
                source="brand",
                note=note,
                cm=row.get("cm"),
                foot=matched_foot,
                brand=self.name,
            )
        elif scale == EU:
            column = "eu"
        elif scale == RU:
            # POIZON-овский RU — это EU − 1, в таблицах брендов его нет.
            return None
        else:
            return None

        rows = self.rows(gender)
        if not rows:
            return None

        best = None
        best_delta = float("inf")
        for row in rows:
            if column not in row or "eu" not in row:
                continue
            delta = abs(row[column] - value)
            if delta < best_delta:
                best_delta, best = delta, row
        if best is None:
            return None

        # Слишком далеко от любой строки — размер вне сетки бренда. Сюда
        # доходят только US/UK/EU: длина стопы обработана выше через by_foot.
        if best_delta > 0.4:
            return None

        exact = best_delta <= SIZE_EPSILON
        gender_label = "женская" if gender == "women" else "мужская"
        note = f"по официальной таблице {self.name} ({gender_label} сетка)"
        if not exact:
            note += f", ближайшая строка {scale} {best[column]:g}".replace(".", ",")
        return Conversion(
            eu=best["eu"],
            exact=exact,
            source="brand",
            note=note,
            cm=best.get("cm"),
            foot=best.get("foot"),
            brand=self.name,
        )


@lru_cache(maxsize=1)
def load_brand_charts() -> dict[str, BrandChart]:
    """Читает data/size_charts.json (собирается tools/build_size_charts.py)."""
    if not _CHARTS_PATH.exists():
        return {}
    try:
        raw = json.loads(_CHARTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    charts = {}
    for key, entry in raw.items():
        charts[key] = BrandChart(
            key=key,
            name=entry.get("name") or key,
            source=entry.get("source") or "",
            sources=entry.get("sources") or {},
            locale=entry.get("locale") or "",
            verified_at=entry.get("verified_at") or "",
            men=entry.get("men") or [],
            women=entry.get("women") or [],
        )
    return charts


def resolve_brand(name: Optional[str]) -> Optional[BrandChart]:
    """«Adidas Originals», «Jordan» → таблица по явному имени или алиасу.

    Поиска по подстроке здесь нет намеренно: иначе NBA стал бы New Balance
    из-за короткого алиаса ``nb``, а MACHENIKE — Nike.
    """
    if not name:
        return None
    charts = load_brand_charts()
    key = str(name).strip().lower()
    target = key if key in charts else _BRAND_ALIASES.get(key)
    return charts.get(target) if target else None


def resolve_official_chart(name: Optional[str]) -> Optional[BrandChart]:
    """Таблица бренда, по которой можно подобрать размер **по замеру стопы**.

    Этим резолвером помечается каталог: пользователь вводит длину стопы, и
    бренд имеет смысл предлагать, только если его официальная таблица содержит
    собственную колонку замера в обеих сетках. Puma публикует лишь ярлык
    CM/JP — она сюда не попадает, хотя её US/UK/EU-таблица используется.
    """
    chart = resolve_brand(name)
    if chart is None:
        return None
    if not all(chart.has_foot_column(gender) for gender in ("men", "women")):
        return None
    return chart


def official_charts(
    scale: Optional[str] = None, gender: str = "men"
) -> list[BrandChart]:
    """Бренды с официальной таблицей размеров, по алфавиту.

    Со ``scale`` остаются только те, у кого эта шкала действительно
    опубликована: искать по длине стопы (CM) можно лишь там, где бренд сам
    даёт замер стопы.
    """
    charts = sorted(load_brand_charts().values(), key=lambda c: c.name.lower())
    if scale is None:
        return charts
    return [chart for chart in charts if chart.publishes(scale, gender)]


def sizes_for_foot(
    brand: Optional[str], foot_cm: float, gender: str = "men"
) -> Optional[dict]:
    """Все размеры бренда для замера стопы — для быстрого калькулятора.

    Возвращает {brand, eu, us, uk, cm, foot, exact} либо None, если по бренду
    нет официальной таблицы или размер вне её диапазона.
    """
    chart = resolve_brand(brand)
    if chart is None:
        return None
    row = chart.by_foot(foot_cm, gender)
    if row is None:
        return None
    result = {
        "brand": chart.name,
        "gender": gender,
        "requested_foot": round(foot_cm, 1),
        "exact": ("foot" in row and abs(row["foot"] - foot_cm) <= SIZE_EPSILON),
    }
    for key in ("eu", "us", "uk", "cm", "foot"):
        if key in row:
            result[key] = row[key]
    return result


def compare_brands(foot_cm: float, gender: str = "men") -> list[dict]:
    """Размер по стопе у всех брендов с официальной таблицей — для сравнения."""
    out = []
    for key in load_brand_charts():
        sizes = sizes_for_foot(key, foot_cm, gender)
        if sizes:
            out.append(sizes)
    return out


# ------------------------------------------------------ общая сетка стопы


def _foot_reference(foot_cm: float, gender: str) -> Optional[float]:
    """EU общей сетки для замера стопы или None, если таблиц мало.

    Каждая официальная таблица с замером стопы даёт свой EU (ближайшая
    строка не меньше замера — как и при поиске по бренду), общая сетка берёт
    медиану. При чётном числе таблиц — бо́льшую из двух средних: размер, как
    и везде, округляется вверх, и это всегда настоящий размер чьей-то сетки.
    """
    eus = []
    for chart in load_brand_charts().values():
        row = chart.by_foot(foot_cm, gender)
        if row is not None and "eu" in row:
            eus.append(row["eu"])
    if len(eus) < _FOOT_REFERENCE_MIN_BRANDS:
        return None
    return statistics.median_high(eus)


#: Шаг, с которым общая сетка сглаживается до неубывающей, см.
_FOOT_REFERENCE_STEP = 0.01


@lru_cache(maxsize=4)
def _foot_reference_floor(gender: str) -> tuple[list[float], list[float]]:
    """Бегущий максимум общей сетки: (стопа, наибольший EU до неё) с шагом 0,01 см.

    Медиана «прыгает» вниз там, где таблица бренда начинается или
    заканчивается (меняется набор, из которого берётся медиана), — и более
    длинная стопа получала бы меньший размер. Бегущий максимум это убирает.
    """
    feet = sorted({
        row["foot"]
        for chart in load_brand_charts().values()
        for row in chart.rows(gender)
        if "foot" in row
    })
    if not feet:
        return [], []
    points, floors = [], []
    best = float("-inf")
    steps = int(round((feet[-1] - feet[0]) / _FOOT_REFERENCE_STEP))
    for i in range(steps + 1):
        foot = round(feet[0] + i * _FOOT_REFERENCE_STEP, 2)
        eu = _foot_reference(foot, gender)
        if eu is None:
            continue
        best = max(best, eu)
        points.append(foot)
        floors.append(best)
    return points, floors


def _monotone_foot_reference(foot_cm: float, gender: str) -> Optional[float]:
    """EU общей сетки, неубывающий по длине стопы (None — таблиц мало)."""
    eu = _foot_reference(foot_cm, gender)
    if eu is None:
        return None
    points, floors = _foot_reference_floor(gender)
    index = bisect.bisect_right(points, foot_cm + SIZE_EPSILON) - 1
    return max(eu, floors[index]) if index >= 0 else eu


def _foot_reference_edges(
    gender: str,
) -> Optional[tuple[tuple[float, float], tuple[float, float]]]:
    """Крайние точки общей сетки: ((стопа, EU) снизу, (стопа, EU) сверху)."""
    points, floors = _foot_reference_floor(gender)
    if not points:
        return None
    return (points[0], floors[0]), (points[-1], floors[-1])


def generic_foot_to_eu(foot_cm: float, gender: str = "men") -> Conversion:
    """Длина стопы → EU по общей сетке — для брендов без замера в таблице.

    Общая сетка строится из официальных колонок длины стопы (Nike, Adidas,
    New Balance, ASICS, Reebok — что есть в data/size_charts.json): для
    замера берётся EU каждой таблицы, а итог — их медиана, если замер
    покрывают хотя бы три таблицы. Это не сетка какого-то одного бренда, и
    официальным брендам она не подставляется: у них работает своя таблица.

    Стопу за краями общей сетки (детские размеры, очень большие) оцениваем
    от ближайшего края шагом EU-размера: ⅔ см стопы — один EU. Перевод всегда
    неточный («≈»): у бренда без таблицы сетка своя.
    """
    grid = "women" if gender == "women" else "men"
    eu = _monotone_foot_reference(foot_cm, grid)
    if eu is not None:
        return Conversion(
            eu=eu,
            exact=False,
            source="standard",
            note=(
                "длина стопы переведена по общей сетке — медиане официальных "
                "таблиц брендов с замером стопы"
            ),
        )
    edges = _foot_reference_edges(grid)
    if edges is None:
        # Официальных таблиц нет вовсе (не собран size_charts.json).
        return Conversion(
            eu=foot_cm + _FALLBACK_OFFSET[CM],
            exact=False,
            source="fallback",
            note="использован типовой перевод длины стопы",
        )
    low, high = edges
    edge_foot, edge_eu = low if foot_cm < low[0] else high
    return Conversion(
        eu=round(edge_eu + (foot_cm - edge_foot) * _EU_PER_CM, 2),
        exact=False,
        source="fallback",
        note="длина стопы вне общей сетки, оценка по шагу размера (⅔ см)",
    )


@dataclass
class SizeChart:
    """Официальная таблица соответствия размеров конкретного товара.

    rows — опорные строки вида {EU: 35.5, RU: 34.5, UK: 3.0, US M: 3.5, CM: 22.5}.

    CM здесь — колонка, которую сайт называет «Длина стопы», но по значениям
    это ярлык пары: у Nike EU 35,5 там 22,5 см, а замер стопы по таблице
    Nike — 21,6. Поэтому замер с этой колонкой не сравнивается.
    """

    rows: list[dict[str, float]] = field(default_factory=list)

    # ------------------------------------------------------------ разбор

    @classmethod
    def from_goods_detail(cls, goods: dict) -> "SizeChart":
        """Собирает таблицу из `sizeAssistantModule` карточки товара."""
        module = (goods or {}).get("sizeAssistantModule") or {}
        blocks = ((module.get("size") or {}).get("sizeList")) or []
        if not blocks:
            return cls()

        # Блоки дублируются в дюймах и сантиметрах — нужен сантиметровый.
        block = next((b for b in blocks if b.get("title") == "cm"), blocks[0])

        columns: dict[str, list[float]] = {}
        entries = list(block.get("sizeKeyList") or [])
        entries += list(block.get("sizeParameterList") or [])
        for entry in entries:
            scale = _TABLE_KEYS.get(str(entry.get("sizeKey") or "").strip())
            if not scale:
                continue
            values = [parse_size(v) for v in (entry.get("sizeValueList") or [])]
            if values and all(v is not None for v in values):
                columns[scale] = values  # type: ignore[assignment]

        if EU not in columns:
            return cls()

        depth = min(len(v) for v in columns.values())
        rows = [
            {scale: values[i] for scale, values in columns.items()}
            for i in range(depth)
        ]
        return cls(rows=rows)

    # ------------------------------------------------------------ работа

    def offset_to_eu(self, scale: str) -> Optional[float]:
        """Медианное смещение EU − значение шкалы по опорным строкам.

        Медиана, а не среднее: у части товаров смещение по строкам «гуляет»
        на полразмера, и медиана устойчивее к такому выбросу.
        """
        deltas = [
            row[EU] - row[scale]
            for row in self.rows
            if EU in row and scale in row
        ]
        if not deltas:
            return None
        return statistics.median(deltas)

    def ladder_correction(self, scale: str) -> float:
        """Поправка эталонной лестницы под конкретный бренд.

        По опорным строкам товара смотрим, на сколько его EU расходится с
        эталоном в тех же точках, и берём медиану. Для Nike это 0, для брендов
        со сдвинутой сеткой — небольшая константа.

        Для длины стопы поправка всегда 0: у лестницы нет колонки замера, а
        «Длина стопы» товара — ярлык, и сдвиг по нему тянул бы замер обратно
        на размер вниз.
        """
        diffs = []
        for row in self.rows:
            if EU not in row or scale not in row:
                continue
            ladder_eu = _ladder_to_eu(scale, row[scale])
            if ladder_eu is not None:
                diffs.append(row[EU] - ladder_eu)
        return statistics.median(diffs) if diffs else 0.0

    def to_eu(
        self, scale: str, value: float, gender: str = "men"
    ) -> Optional[Conversion]:
        """Переводит размер из указанной шкалы в EU.

        gender нужен только длине стопы: она идёт по общей сетке стопы
        (generic_foot_to_eu) выбранной сетки, а не по колонке «Длина стопы»
        товара — та на деле ярлык.
        """
        scale = normalize_scale(scale) or scale

        if scale == EU:
            return Conversion(eu=value, exact=True, source="native")
        if scale == RU:
            # RU у POIZON жёстко привязан к EU как EU − 1, но если у товара
            # есть таблица — верим ей.
            row = self._row_with(RU, value)
            if row and EU in row:
                return Conversion(eu=row[EU], exact=True, source="table")
            return Conversion(eu=value + 1.0, exact=True, source="native")
        if scale == MM:
            scale, value = CM, value / 10
        if scale == CM:
            return generic_foot_to_eu(value, gender)

        # Точное попадание в опорную строку — самый надёжный перевод.
        row = self._row_with(scale, value)
        if row and EU in row:
            return Conversion(eu=row[EU], exact=True, source="table")

        # Эталонная лестница с поправкой под бренд по опорным строкам.
        ladder_eu = _ladder_to_eu(scale, value)
        if ladder_eu is not None:
            correction = self.ladder_correction(scale)
            note = "перевод по стандартной атлетической сетке"
            if abs(correction) > 0.01:
                note += f" со сдвигом под бренд ({correction:+g})"
            return Conversion(
                eu=ladder_eu + correction, exact=False, source="standard", note=note
            )

        # Размер вне лестницы, но есть в таблице товара — линейное смещение.
        offset = self.offset_to_eu(scale)
        if offset is not None:
            return Conversion(
                eu=value + offset, exact=False, source="table",
                note="размер вне стандартной сетки, оценка по таблице товара",
            )

        fallback = _FALLBACK_OFFSET.get(scale)
        if fallback is None:
            return None
        return Conversion(
            eu=value + fallback,
            exact=False,
            source="fallback",
            note="размер вне стандартной сетки, использован типовой перевод",
        )

    def _row_with(self, scale: str, value: float) -> Optional[dict[str, float]]:
        for row in self.rows:
            if scale in row and abs(row[scale] - value) <= SIZE_EPSILON:
                return row
        return None

    def describe(self) -> list[str]:
        """Человекочитаемые строки таблицы — для вывода в CLI."""
        order = [EU, RU, UK, US_MEN, US_WOMEN, CM]
        out = []
        for row in self.rows:
            parts = [
                f"{scale} {row[scale]:g}".replace(".", ",")
                for scale in order
                if scale in row
            ]
            out.append(" · ".join(parts))
        return out


def convert_to_eu(
    scale: Optional[str],
    value: float,
    chart: Optional[SizeChart] = None,
    brand: Optional[str] = None,
    gender: str = "men",
) -> Conversion:
    """Перевод размера в EU.

    Порядок источников — от самого достоверного к запасному:

    1. **Официальная таблица бренда** (Nike / Adidas / New Balance / ASICS /
       Reebok / Puma), если бренд известен и публикует нужную шкалу. Именно её
       просил пользователь: сначала сверяемся с сеткой производителя, потом
       ищем на POIZON.
    2. Таблица самого товара из карточки POIZON (3 опорные строки).
    3. Эталонная атлетическая лестница.
    4. Типовое смещение.

    Длина стопы без официальной колонки замера (Puma, бренды без таблицы)
    идёт мимо пунктов 2–4: по общей сетке стопы (generic_foot_to_eu). И
    сантиметры товара, и прежний сантиметровый ряд лестницы — ярлыки, а не
    замер, и стопа 26,5 см по ним выходила EU 41 вместо 42–43⅓.
    """
    scale = normalize_scale(scale) or EU
    if scale == MM:
        scale = CM
        value /= 10

    brand_chart = resolve_brand(brand)
    if brand_chart is not None:
        result = brand_chart.to_eu(scale, value, gender)
        if result is not None:
            return result
        # «Вне таблицы» говорим только про шкалу, которую бренд публикует.
        # Если колонки нет вовсе (у Puma нет замера стопы), это не значит, что
        # размера не существует — переводим дальше по общей сетке.
        if scale in {US_MEN, US_WOMEN, UK, CM} and brand_chart.publishes(
            scale, gender
        ):
            effective_gender = (
                "women" if scale == US_WOMEN
                else "men" if scale == US_MEN
                else gender
            )
            gender_label = (
                "женская" if effective_gender == "women" else "мужская"
            )
            return Conversion(
                eu=value,
                exact=False,
                source="brand",
                note=(
                    f"размер вне официальной таблицы {brand_chart.name} "
                    f"({gender_label} сетка)"
                ),
                brand=brand_chart.name,
                supported=False,
            )

    if scale == CM:
        return generic_foot_to_eu(value, gender)

    if chart is not None and chart.rows:
        result = chart.to_eu(scale, value, gender)
        if result is not None:
            return result

    if scale == EU:
        return Conversion(eu=value, exact=True, source="native")
    if scale == RU:
        return Conversion(eu=value + 1.0, exact=True, source="native")

    # Без таблицы товара — эталонная лестница, затем типовое смещение.
    ladder_eu = _ladder_to_eu(scale, value)
    if ladder_eu is not None:
        return Conversion(
            eu=ladder_eu, exact=False, source="standard",
            note="перевод по стандартной атлетической сетке",
        )

    offset = _FALLBACK_OFFSET.get(scale)
    if offset is None:
        return Conversion(eu=value, exact=False, source="fallback",
                          note=f"неизвестная шкала {scale}")
    return Conversion(
        eu=value + offset,
        exact=False,
        source="fallback",
        note="размер вне стандартной сетки, использован типовой перевод",
    )
