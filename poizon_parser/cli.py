"""Командный интерфейс парсера."""

from __future__ import annotations

import argparse
import csv
import errno
import io
import json
import math
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .client import ChallengeRequired, PoizonClient, PoizonError
from .finder import SizeFinder
from .models import Match, Product
from .sizechart import (
    CM,
    EU,
    MM,
    NATIVE_SCALES,
    RU,
    UK,
    US_MEN,
    US_WOMEN,
    load_brand_charts,
    normalize_scale,
    official_charts,
    resolve_brand,
    resolve_query_scale,
)
from .sizes import parse_size_query

# Границы длины стопы — общие с веб-сервером, чтобы CLI и веб одинаково
# отсекали миллиметры и размеры EU, введённые как сантиметры.
from .webapp import FOOT_MAX_CM, FOOT_MIN_CM

#: Шкалы ввода shoes/allbrands (канонические имена после normalize_scale).
INPUT_SCALES = (CM, MM, EU, RU, UK, US_MEN, US_WOMEN)
_SCALES_HELP = "CM (длина стопы), MM, EU, RU, UK, «US M», «US W»"

#: Ответы на вопрос о капче, которые прерывают работу.
_STOP_WORDS = ("q", "quit", "exit", "stop")


def _setup_stdout() -> None:
    """Кириллица в консоли Windows без «кракозябр»."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _money(value: Optional[float], text: str = "") -> str:
    if text:
        return text
    if value is None:
        return "—"
    return f"{value:,.0f} ₽".replace(",", " ")


def _num(value: float) -> str:
    """Число для человека: 26.5 → «26,5», 43.3333 → «43⅓», 36.6667 → «36⅔».

    Adidas ведёт EU-сетку с шагом в треть размера, и «43,3333» в выводе
    читается хуже, чем «43⅓» с ярлыка самого бренда. Бесконечность и NaN
    не роняют вывод: math.floor(inf) — OverflowError.
    """
    if math.isnan(value):
        return "—"
    if math.isinf(value):
        return "∞" if value > 0 else "-∞"
    whole = math.floor(value)
    fraction = value - whole
    if abs(fraction - 1 / 3) < 0.01:
        return f"{whole}⅓"
    if abs(fraction - 2 / 3) < 0.01:
        return f"{whole}⅔"
    return f"{value:g}".replace(".", ",")


def _shorten(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Согласование с числом: «1 модель» / «2 модели» / «5 моделей»."""
    tail = abs(count) % 100
    last = tail % 10
    if 11 <= tail <= 14:
        word = many
    elif last == 1:
        word = one
    elif 2 <= last <= 4:
        word = few
    else:
        word = many
    return f"{count} {word}"


def _models(count: int) -> str:
    """«1 модель» / «2 модели» / «5 моделей»."""
    return _plural(count, "модель", "модели", "моделей")


#: Сдвиг размера в подсказке сайта: «-0,5», «+1», «−0,5» (типографский минус).
#: Знак не должен прилипать к слову слева, иначе «US-9» дало бы «-9».
_FIT_RE = re.compile(r"(?<![\w.,])([+\-−–])\s*(\d+(?:[.,]\d+)?)")


def _fit_hint(size_tip: str) -> str:
    """«Размер больше, возьмите размер -0,5» → «-0,5»."""
    if not size_tip:
        return "—"
    match = _FIT_RE.search(size_tip)
    if not match:
        return "—"
    sign = "+" if match.group(1) == "+" else "-"
    return sign + match.group(2).replace(".", ",")


def _join_lines(lines: list[str]) -> str:
    """Склеивает строки вывода: пустая строка — разделитель блоков, но не
    двойной и не по краям (блоки бывают пустыми)."""
    out: list[str] = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _fail(message: str, code: int = 2) -> int:
    print(f"Ошибка: {message}", file=sys.stderr)
    return code


# ----------------------------------------------------------------- вывод

def render_table(matches: list[Match], title_width: int = 46) -> str:
    if not matches:
        return "Ничего не найдено."

    rows = []
    for index, match in enumerate(matches, 1):
        offer = match.offer
        rows.append(
            (
                str(index),
                _shorten(match.product.title, title_width),
                f"{offer.size_in(match.matched_scale)} {match.matched_scale}",
                _money(offer.price, offer.price_text),
                _shorten(offer.delivery or "—", 14),
                str(match.product.spu_id),
            )
        )

    headers = ("#", "Модель", "Размер", "Цена", "Доставка", "SPU")
    widths = [
        max(len(headers[col]), max(len(row[col]) for row in rows))
        for col in range(len(headers))
    ]

    def line(cells) -> str:
        return "  ".join(str(cell).ljust(widths[col]) for col, cell in enumerate(cells)).rstrip()

    out = [line(headers), "  ".join("─" * width for width in widths)]
    out.extend(line(row) for row in rows)

    priced = [m.offer.price for m in matches if m.offer.price is not None]
    if priced:
        out.append("")
        out.append(
            f"Найдено: {len(matches)} · дешевле всего {_money(min(priced))} · "
            f"дороже всего {_money(max(priced))}"
        )

    used_scales = {m.matched_scale for m in matches}
    if len(used_scales) > 1:
        out.append(
            "Внимание: размеры подобраны в разных шкалах "
            f"({', '.join(sorted(used_scales))}) — это разная обувь. "
            "Зафиксируйте шкалу через --scale или --strict-scale."
        )

    tip = next((m.product.size_tip for m in matches if m.product.size_tip), "")
    if tip:
        out.append(f"Подсказка по размеру: {tip}")
    out.append("")
    out.append("Ссылки:")
    for index, match in enumerate(matches, 1):
        out.append(f"  {index}. {match.product.full_url}")
    return "\n".join(out)


def render_json(matches: list[Match]) -> str:
    return json.dumps(
        [match.to_dict() for match in matches], ensure_ascii=False, indent=2
    )


def render_csv(matches: list[Match]) -> str:
    buffer = io.StringIO()
    fields = [
        "title", "brand", "article", "requested_size", "matched_scale", "size",
        "price", "currency", "in_stock", "delivery", "spu_id", "sku_id", "url",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for match in matches:
        writer.writerow(match.to_dict())
    return buffer.getvalue()


def render_product_sizes(product: Product, only_in_stock: bool = False) -> str:
    scales = product.size_scales or ["—"]
    out = [
        product.title or f"SPU {product.spu_id}",
        f"SPU {product.spu_id}" + (f" · арт. {product.article}" if product.article else ""),
        product.full_url,
    ]
    if product.min_price is not None:
        out.append(f"Цена от: {_money(product.min_price)}")
    if product.size_tip:
        out.append(f"Подсказка: {product.size_tip}")
    out.append("")

    show_variant = any(offer.variant for offer in product.offers)
    headers = [*scales, *(["Вариант"] if show_variant else []), "Цена", "Наличие", "Доставка"]
    rows = []
    for offer in product.offers:
        if only_in_stock and not offer.in_stock:
            continue
        rows.append(
            [
                *[offer.sizes.get(scale, "—") for scale in scales],
                *([_shorten(offer.variant_label or "—", 22)] if show_variant else []),
                _money(offer.price, offer.price_text) if offer.in_stock else "—",
                "есть" if offer.in_stock else "нет",
                _shorten(offer.delivery or "—", 16),
            ]
        )
    if not rows:
        out.append("Размеров в наличии нет.")
        return "\n".join(out)

    widths = [
        max(len(headers[col]), max(len(row[col]) for row in rows))
        for col in range(len(headers))
    ]

    def line(cells) -> str:
        return "  ".join(str(cell).ljust(widths[col]) for col, cell in enumerate(cells)).rstrip()

    out.append(line(headers))
    out.append("  ".join("─" * width for width in widths))
    out.extend(line(row) for row in rows)

    priced = [o.price for o in product.offers if o.in_stock and o.price is not None]
    if priced:
        out.append("")
        out.append(
            f"В наличии {len(priced)} из {len(product.offers)} размеров · "
            f"от {_money(min(priced))} до {_money(max(priced))}"
        )
    return "\n".join(out)


# ------------------------------------------------------------ окружение

class TerminalChallenge:
    """Пауза в терминале на время капчи — один вопрос на все воркеры.

    shoes/allbrands грузят карточки в несколько потоков, и проверку сайт
    показывает сразу всем. Без общего замка каждый поток печатал бы баннер и
    ждал свой Enter: один Enter отпускал бы один поток, а «q» обрывал бы
    обход, пока остальные висят в input(). Здесь вопрос задаёт первый поток,
    остальные ждут смены поколения и получают тот же ответ — как в
    webapp.JobManager._wait_for_captcha. Отказ запоминается: после «q»
    следующие проверки прерывают работу без нового вопроса.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._asking = False
        self._generation = 0
        self._answer = True
        self._aborted = False
        #: Сколько потоков ждут чужого ответа (для тестов и отладки).
        self.waiting = 0

    def __call__(self, info: dict) -> bool:
        with self._cond:
            if self._aborted:
                return False
            if self._asking:
                seen = self._generation
                self.waiting += 1
                try:
                    while self._generation == seen:
                        self._cond.wait()
                finally:
                    self.waiting -= 1
                return self._answer
            self._asking = True

        answer = False
        try:
            answer = self._ask(info)
        finally:
            # Ответ получают все ждущие, даже если input() упал.
            with self._cond:
                self._answer = answer
                self._aborted = not answer
                self._asking = False
                self._generation += 1
                self._cond.notify_all()
        return answer

    @staticmethod
    def _ask(info: dict) -> bool:
        print(
            f"\n⚠  Сайт показал проверку ({info.get('reason')}).\n"
            f"   Откройте в браузере и пройдите её:\n   {info.get('url')}\n"
            f"   Затем нажмите Enter, чтобы продолжить (или введите q + Enter — прервать).",
            file=sys.stderr,
        )
        try:
            answer = input()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() not in _STOP_WORDS


def _client_from(args) -> PoizonClient:
    cache_dir = None if getattr(args, "no_cache", False) else _default_cache_dir()
    interactive = bool(sys.stdin and sys.stdin.isatty())
    return PoizonClient(
        delay=args.delay,
        timeout=args.timeout,
        verbose=args.verbose,
        cache_dir=cache_dir,
        cache_ttl=getattr(args, "cache_ttl", 900.0),
        on_challenge=TerminalChallenge() if interactive else None,
    )


def _default_cache_dir() -> str:
    return str(Path(tempfile.gettempdir()) / "poizon-parser-cache")


def _build_finder(args) -> SizeFinder:
    progress = (lambda message: print(message, file=sys.stderr)) if not args.quiet else (lambda m: None)
    return SizeFinder(client=_client_from(args), on_progress=progress)


# -------------------------------------------------------------- проверки

def _foot_size(size: str, scale: str) -> tuple[float, str]:
    """Размер и шкала для shoes/allbrands → (число, каноническая шкала).

    Шкалу можно задать и в самом размере («EU 43», «US W 7») — она важнее
    --scale. Исключение — голое «US»: пол оно не задаёт и не перебивает
    --scale "US M" / "US W". Правило общее с finder и веб-сервером
    (sizechart.resolve_query_scale). Неизвестная шкала не должна молча стать
    EU, а «42» без --scale EU — длиной стопы 42 см: оба случая — ValueError
    с подсказкой; отрицательный и бесконечный размер — тоже.
    """
    parsed_scale, value = parse_size_query(size)
    canonical = resolve_query_scale(parsed_scale, scale, default=CM)
    if canonical not in INPUT_SCALES:
        # Явную --scale проверил argparse — неизвестной бывает шкала из -s.
        raise ValueError(
            f"неизвестная шкала «{parsed_scale or scale}». Доступны: {_SCALES_HELP}"
        )
    if value <= 0:
        raise ValueError("размер должен быть больше нуля")
    if canonical == MM:
        millimetres, value, canonical = value, value / 10, CM
        if not FOOT_MIN_CM <= value <= FOOT_MAX_CM:
            # Человек сам сказал «миллиметры» — подсказки про --scale MM и EU
            # тут лишние, а границы понятнее в тех же миллиметрах.
            hint = (
                " Если это сантиметры — уберите MM."
                if FOOT_MIN_CM <= millimetres <= FOOT_MAX_CM else ""
            )
            raise ValueError(
                f"длина стопы {_num(millimetres)} мм вне разумных границ "
                f"({_num(FOOT_MIN_CM * 10)}–{_num(FOOT_MAX_CM * 10)} мм).{hint}"
            )
    if canonical == CM and not FOOT_MIN_CM <= value <= FOOT_MAX_CM:
        if value > FOOT_MAX_CM * 2.5:
            hint = "Если это миллиметры — добавьте --scale MM."
        elif value > FOOT_MAX_CM:
            hint = "Если это размер EU — добавьте --scale EU."
        else:
            hint = 'Если это размер US или UK — укажите --scale "US M", "US W" или UK.'
        raise ValueError(
            f"длина стопы {_num(value)} см вне разумных границ "
            f"({_num(FOOT_MIN_CM)}–{_num(FOOT_MAX_CM)} см). {hint}"
        )
    return value, canonical


def _file_problem(path: str) -> Optional[str]:
    """Можно ли писать результат в файл -o. Текст ошибки или None."""
    target = Path(path)
    if target.is_dir():
        return f"«{path}» — это папка; укажите в -o имя файла"
    folder = target.parent
    if not folder.is_dir():
        return f"папки «{folder}» нет — создайте её или укажите в -o другой путь"
    created = False
    try:
        # «a» не стирает существующий файл, «x» — не перезапишет чужой.
        if target.exists():
            with open(target, "a", encoding="utf-8"):
                pass
        else:
            with open(target, "x", encoding="utf-8"):
                created = True
    except OSError as exc:
        return f"нельзя записать «{path}»: {exc.strerror or exc}"
    if created:
        try:
            target.unlink()
        except OSError:
            pass
    return None


def _dir_problem(path: str) -> Optional[str]:
    """Можно ли создать в -o папку HTML-отчёта. Текст ошибки или None.

    Проверяем делом, как и _file_problem: создаём недостающие папки и
    пробный файл, затем убираем всё, что создала сама проверка. Одного
    взгляда на существующего предка мало — недопустимое имя («rep<ort» на
    Windows) или папка без прав всплыли бы только после долгого обхода.
    """
    target = Path(path)
    if target.exists() and not target.is_dir():
        return f"«{path}» — это файл; для -f html укажите в -o папку для отчёта"
    missing: list[Path] = []
    ancestor = target
    while not ancestor.exists() and ancestor != ancestor.parent:
        missing.append(ancestor)
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        return f"нельзя создать папку «{path}»: «{ancestor}» нет или это не папка"
    created: list[Path] = []
    try:
        # Папки — по одной, от внешней к внутренней: так известно, что убрать.
        for folder in reversed(missing):
            folder.mkdir()
            created.append(folder)
        with tempfile.TemporaryFile(dir=str(target)):
            pass
    except OSError as exc:
        return f"нельзя записать отчёт в «{path}»: {exc.strerror or exc}"
    finally:
        for folder in reversed(created):
            try:
                folder.rmdir()
            except OSError:
                pass
    return None


def _output_problem(args) -> Optional[str]:
    """Проверка -o до обхода сайта: иначе ошибка пути всплыла бы только
    после долгого сбора и унесла бы результаты."""
    if not getattr(args, "out", None):
        return None
    if getattr(args, "format", None) == "html":
        return _dir_problem(args.out)
    return _file_problem(args.out)


def _write_output(args, output: str, count: int) -> int:
    """Печатает результат или сохраняет его в -o. Возвращает код ошибки."""
    if not args.out:
        print(output)
        return 0
    # BOM нужен только CSV — по нему Excel узнаёт UTF-8. JSON с BOM
    # json.loads не читает, а в таблице он просто лишний.
    encoding = "utf-8-sig" if args.format == "csv" else "utf-8"
    try:
        with open(args.out, "w", encoding=encoding, newline="") as handle:
            handle.write(output)
    except OSError as exc:
        # Сбор уже сделан — не теряем его: печатаем результат в консоль.
        print(
            f"Ошибка: не удалось сохранить в «{args.out}» ({exc.strerror or exc}). "
            "Результат — ниже.",
            file=sys.stderr,
        )
        print(output)
        return 2
    print(f"Сохранено в {args.out} ({_models(count)})", file=sys.stderr)
    return 0


def _html_report(
    args, matches: list[Match], brand: str, size: float, scale: str
) -> int:
    """HTML-отчёт: самодостаточный файл, который можно переслать.

    Папка — result/ или указанная в -o.
    """
    if not matches:
        print("Ничего не найдено — отчёт не создан.", file=sys.stderr)
        return 1
    from .report import write_report

    meta = {
        "brand": brand,
        "size_input": _num(size),
        "scale": scale,
        "gender": args.gender,
    }
    where = {"base_dir": args.out} if args.out else {}
    try:
        out_dir = write_report(
            [m.to_dict() for m in matches], meta,
            embed_images=getattr(args, "embed_images", False),
            **where,
        )
    except OSError as exc:
        return _fail(f"не удалось записать отчёт: {exc}")
    print(f"Отчёт готов: {out_dir / 'index.html'}")
    print(f"Откройте его в браузере или перешлите файл — {_models(len(matches))}.")
    return 0


# --------------------------------------------------------------- команды

def _partial(exc: ChallengeRequired) -> list[Match]:
    """Находки, с которыми SizeFinder выпустил проверку сайта наружу."""
    return list(getattr(exc, "partial", None) or [])


def _interrupted(exc: ChallengeRequired, count: int) -> int:
    """Итог поиска, который оборвала проверка сайта (например, «q» на капче).

    Найденное до обрыва уже выведено или сохранено — здесь только пометка,
    что выдача неполная. Код возврата тот же, что у любой ошибки сайта.
    """
    print(
        f"Ошибка: {exc}.\n"
        "Поиск прерван проверкой сайта: в выдаче только то, что нашлось до "
        f"остановки ({_models(count)}). Пройдите проверку в браузере и "
        "запустите поиск снова — проверенные карточки уже в кэше.",
        file=sys.stderr,
    )
    return 2


def cmd_find(args) -> int:
    try:
        parsed_scale, _ = parse_size_query(args.size)
    except ValueError as exc:
        return _fail(str(exc))
    # Шкалу из -s проверяем и при --scale: иначе «US 9» --scale EU молча
    # теряло бы «US» и искало EU 9.
    if parsed_scale and parsed_scale not in NATIVE_SCALES:
        return _fail(
            f"на POIZON размеры подписаны только в RU и EU, а не в {parsed_scale}. "
            'Для US/UK/CM ищите через shoes: --scale "US M", UK или CM'
        )
    if parsed_scale and args.scale and parsed_scale != args.scale:
        return _fail(
            f"шкала в размере ({parsed_scale}) не совпадает с --scale {args.scale}. "
            "Оставьте одну из них"
        )
    problem = _output_problem(args)
    if problem:
        return _fail(problem)

    finder = _build_finder(args)
    interrupted: Optional[ChallengeRequired] = None
    try:
        matches = finder.find(
            query=args.query,
            size=args.size,
            scale=args.scale,
            limit=args.limit,
            search_limit=args.check,
            tolerance=args.tolerance,
            max_price=args.max_price,
            min_price=args.min_price,
            only_in_stock=not args.include_unavailable,
            allow_scale_fallback=not args.strict_scale,
        )
    except ChallengeRequired as exc:
        matches = _partial(exc)
        if not matches:
            raise  # показать нечего — обычная ошибка сайта, её подпишет main()
        interrupted = exc

    if args.format == "json":
        output = render_json(matches)
    elif args.format == "csv":
        output = render_csv(matches)
    else:
        output = render_table(matches)

    code = _write_output(args, output, len(matches))
    if interrupted is not None:
        return _interrupted(interrupted, len(matches))
    return code or (0 if matches else 1)


def cmd_sizes(args) -> int:
    finder = _build_finder(args)
    try:
        product = finder.load_product(args.product)
    except PoizonError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        offers = [o for o in product.offers if o.in_stock or not args.in_stock]
        payload = {
            "spu_id": product.spu_id,
            "title": product.title,
            "url": product.full_url,
            "article": product.article,
            "brand": product.brand,
            "min_price": product.min_price,
            "scales": product.size_scales,
            "default_scale": product.default_scale,
            "size_tip": product.size_tip,
            "offers": [
                {
                    "sizes": offer.sizes,
                    # Полнота / издание: без них два SKU одного размера
                    # в JSON не различить.
                    "variant": offer.variant_label,
                    "price": offer.price,
                    "price_text": offer.price_text,
                    "in_stock": offer.in_stock,
                    "delivery": offer.delivery,
                    "sku_id": offer.sku_id,
                }
                for offer in offers
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_product_sizes(product, only_in_stock=args.in_stock))
    return 0


def render_shoes_table(
    matches: list[Match], title_width: int = 44, show_brand: bool = False
) -> str:
    """Итоговая таблица основного сценария: бренд + размер → что в наличии.

    show_brand добавляет колонку бренда — она нужна, когда в одной выдаче
    лежат модели нескольких брендов (обход всех официальных таблиц).
    """
    if not matches:
        return "Ничего не найдено."

    rows = []
    for index, match in enumerate(matches, 1):
        offer = match.offer
        # Ярлык POIZON — чтобы размер можно было сверить на сайте.
        poizon_label = " / ".join(
            f"{scale} {value}" for scale, value in offer.sizes.items()
        )
        rows.append(
            (
                str(index),
                *([_shorten(match.product.brand or "—", 14)] if show_brand else []),
                _shorten(match.product.title, title_width),
                poizon_label,
                _fit_hint(match.product.size_tip),
                ("≈ " if not match.exact_conversion else "")
                + _money(offer.price, offer.price_text),
                _shorten(offer.delivery or "—", 12),
                str(match.product.spu_id),
            )
        )

    headers = (
        "#",
        *(("Бренд",) if show_brand else ()),
        "Модель", "Размер на POIZON", "Посадка", "Цена", "Доставка", "SPU",
    )
    widths = [
        max(len(headers[col]), max(len(row[col]) for row in rows))
        for col in range(len(headers))
    ]

    def line(cells) -> str:
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    out = [line(headers), "  ".join("─" * w for w in widths)]
    out.extend(line(row) for row in rows)

    first = matches[0]
    priced = [m.offer.price for m in matches if m.offer.price is not None]
    out.append("")
    if priced:
        out.append(
            f"В наличии: {_models(len(matches))} · от {_money(min(priced))} "
            f"до {_money(max(priced))}"
        )

    # Перевод считается по таблице каждой модели, поэтому у разных позиций
    # один и тот же размер может дать разный EU — показываем это честно.
    converted = {m.converted_eu for m in matches if m.converted_eu is not None}
    if converted:
        shown = ", ".join(f"EU {_num(v)}" for v in sorted(converted))
        out.append(
            f"Запрошено: {_num(first.requested_size)} {first.requested_scale} → {shown}"
        )
        if len(converted) > 1:
            out.append(
                "  Разный EU — это не ошибка: у каждого бренда своя официальная "
                "сетка, перевод берётся из неё."
                if show_brand else
                "  Разный EU у моделей — это не ошибка: у каждой свой размерный "
                "ряд (мужской/женский), перевод берётся из её таблицы."
            )

    approx = [m for m in matches if not m.exact_conversion]
    if approx:
        out.append(
            f"«≈» у {len(approx)} из {len(matches)}: точного перевода из "
            f"{first.requested_scale} в таблице модели нет, взят ближайший "
            "размер — сверьте по ссылке."
        )
    notes = {m.conversion_note for m in matches if m.conversion_note}
    for note in sorted(notes):
        out.append(f"Примечание: {note}")

    if any(m.product.size_tip for m in matches):
        out.append(
            "Колонка «Посадка» — рекомендация сайта: на сколько сместить размер."
        )

    out.append("")
    out.append("Ссылки:")
    for index, match in enumerate(matches, 1):
        out.append(f"  {index}. {match.product.full_url}")
    return _join_lines(out)


def cmd_brands(args) -> int:
    from .catalog import Catalog

    catalog = Catalog(_client_from(args))
    brands = catalog.brands()
    if args.query:
        needle = args.query.strip().lower()
        brands = [b for b in brands if needle in b.name.lower() or needle in b.slug]

    if args.format == "json":
        print(json.dumps([b.__dict__ for b in brands], ensure_ascii=False, indent=2))
        return 0 if brands else 1

    if not brands:
        print("Бренды не найдены.")
        return 1
    print(f"Брендов: {len(brands)}\n")
    for brand in brands:
        print(f"  {brand.name:<32} {brand.slug}")
    return 0


def cmd_shoes(args) -> int:
    try:
        size, scale = _foot_size(args.size, args.scale)
    except ValueError as exc:
        return _fail(str(exc))
    problem = _output_problem(args)
    if problem:
        return _fail(problem)

    finder = _build_finder(args)
    interrupted: Optional[ChallengeRequired] = None
    try:
        matches = finder.find_by_brand(
            brand=args.brand,
            size=size,
            scale=scale,
            limit=args.limit,
            check=args.check or None,  # 0 → весь каталог
            tolerance=args.tolerance,
            max_price=args.max_price,
            min_price=args.min_price,
            include_kids=args.kids,
            workers=args.workers,
            gender=args.gender,
        )
    except ChallengeRequired as exc:
        # Проверку не прошли (или ответили «q») — найденное до неё не теряем.
        matches = _partial(exc)
        if not matches:
            raise  # показать нечего — обычная ошибка сайта, её подпишет main()
        interrupted = exc
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise  # виноват ответ сайта, а не ввод — подпишет main()
    except ValueError as exc:
        return _fail(str(exc))

    if args.format == "html":
        code = _html_report(args, matches, args.brand, size, scale)
    else:
        if args.format == "json":
            output = render_json(matches)
        elif args.format == "csv":
            output = render_csv(matches)
        else:
            output = render_shoes_table(matches)
        code = _write_output(args, output, len(matches)) or (0 if matches else 1)

    if interrupted is not None:
        return _interrupted(interrupted, len(matches))
    return code


def cmd_allbrands(args) -> int:
    """Один размер → обувь всех брендов с официальной таблицей."""
    try:
        size, scale = _foot_size(args.size, args.scale)
    except ValueError as exc:
        return _fail(str(exc))

    charts = official_charts()
    if not charts:
        return _fail("таблицы не собраны. Запустите: python tools/build_size_charts.py")

    # --brands сводим к ключам таблиц: «nb», «Jordan», «Adidas Originals»
    # понимает resolve_brand, а опечатку лучше поймать до обхода сайта.
    selected: Optional[list[str]] = None
    if args.brands:
        selected, unknown = [], []
        for name in args.brands:
            chart = resolve_brand(name)
            if chart is None:
                unknown.append(name)
            elif chart.key not in selected:
                selected.append(chart.key)
        if unknown:
            return _fail(
                f"нет официальной таблицы для: {', '.join(unknown)}. "
                f"Есть: {', '.join(chart.name for chart in charts)}"
            )
    wanted = [c for c in charts if selected is None or c.key in selected]
    usable = {chart.key for chart in official_charts(scale, args.gender)}
    skipped = [chart.name for chart in wanted if chart.key not in usable]
    if len(skipped) == len(wanted):
        return _fail(
            f"ни у одного из выбранных брендов ({', '.join(skipped)}) нет "
            f'официальной шкалы {scale}. Укажите другую: --scale EU, UK, "US M" или "US W"'
        )

    problem = _output_problem(args)
    if problem:
        return _fail(problem)

    finder = _build_finder(args)
    per_brand: list[tuple[str, list[Match]]] = []
    interrupted: Optional[ChallengeRequired] = None
    try:
        matches = finder.find_in_official_brands(
            size=size,
            scale=scale,
            limit=args.limit,
            total_limit=args.total or None,
            check=args.check or None,  # 0 → весь каталог
            tolerance=args.tolerance,
            max_price=args.max_price,
            min_price=args.min_price,
            include_kids=args.kids,
            workers=args.workers,
            gender=args.gender,
            only=selected,
            on_brand=lambda name, found: per_brand.append((name, found)),
        )
    except ChallengeRequired as exc:
        # Обход оборван проверкой — показываем бренды, пройденные до неё.
        matches = _partial(exc)
        if not matches:
            raise  # показать нечего — обычная ошибка сайта, её подпишет main()
        interrupted = exc
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise  # виноват ответ сайта, а не ввод — подпишет main()
    except ValueError as exc:
        return _fail(str(exc))

    if args.format == "html":
        brands = ", ".join(name for name, _ in per_brand)
        code = _html_report(args, matches, brands, size, scale)
    else:
        if args.format == "json":
            output = render_json(matches)
        elif args.format == "csv":
            output = render_csv(matches)
        else:
            lines = ["По брендам:"]
            for name, found in per_brand:
                eus = sorted({m.converted_eu for m in found if m.converted_eu is not None})
                size_label = " · ".join(f"EU {_num(v)}" for v in eus) if eus else "—"
                lines.append(f"  {name:<14} {_models(len(found)):<12} {size_label}")
            if interrupted is not None:
                lines.append("Список неполный: поиск прерван проверкой сайта.")
            if skipped:
                lines.append(
                    f"Без официальной шкалы {scale} и потому пропущены: "
                    + ", ".join(skipped)
                )
            output = _join_lines(
                [*lines, "", render_shoes_table(matches, show_brand=True)]
            )
        code = _write_output(args, output, len(matches)) or (0 if matches else 1)

    if interrupted is not None:
        return _interrupted(interrupted, len(matches))
    return code


def cmd_chart(args) -> int:
    """Официальная таблица размеров конкретной модели."""
    finder = _build_finder(args)
    try:
        product = finder.load_product(args.product)
    except PoizonError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    chart = product.chart
    if args.format == "json":
        payload = {
            "spu_id": product.spu_id,
            "title": product.title,
            "url": product.full_url,
            "size_tip": product.size_tip,
            "chart": list(getattr(chart, "rows", None) or []),
            "in_stock": [
                {
                    "sizes": offer.sizes,
                    "variant": offer.variant_label,
                    "price": offer.price,
                    "price_text": offer.price_text,
                    "sku_id": offer.sku_id,
                }
                for offer in product.in_stock_offers()
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["chart"] else 1

    print(product.title or f"SPU {product.spu_id}")
    print(product.full_url)
    if product.size_tip:
        print(f"Посадка: {product.size_tip}")
    print()
    rows = chart.describe() if chart is not None else []
    if not rows:
        print("Официальной таблицы размеров у этой модели нет.")
        return 1
    print("Официальная таблица (опорные строки с сайта):")
    for row in rows:
        print(f"  {row}")
    print()
    print("Размеры в наличии (ярлыки POIZON):")
    for offer in product.in_stock_offers():
        label = " / ".join(f"{s} {v}" for s, v in offer.sizes.items())
        print(f"  {label:<22} {_money(offer.price, offer.price_text)}")
    return 0


def _foot_range(chart, gender: str) -> Optional[tuple[float, float]]:
    """Диапазон длины стопы в официальной таблице бренда (или None)."""
    feet = [row["foot"] for row in chart.rows(gender) if "foot" in row]
    return (min(feet), max(feet)) if feet else None


def cmd_size(args) -> int:
    """Калькулятор: длина стопы → размеры бренда (и сравнение брендов)."""
    from .sizechart import compare_brands, sizes_for_foot

    try:
        foot = float(str(args.foot).replace(",", "."))
    except ValueError:
        return _fail(f"«{args.foot}» не число")
    if not FOOT_MIN_CM <= foot <= FOOT_MAX_CM:
        return _fail(
            "длина стопы должна быть в сантиметрах "
            f"({_num(FOOT_MIN_CM)}–{_num(FOOT_MAX_CM)})"
        )

    gender_label = "женская" if args.gender == "women" else "мужская"
    print(f"Длина стопы {_num(foot)} см · {gender_label} сетка\n")

    if args.brand:
        result = sizes_for_foot(args.brand, foot, args.gender)
        if result is None:
            chart = resolve_brand(args.brand)
            span = _foot_range(chart, args.gender) if chart is not None else None
            if chart is None:
                print(f"Для «{args.brand}» официальной таблицы нет — "
                      "размер подберётся по общей сетке при поиске.")
            elif span is None:
                # Таблица есть, но замера стопы бренд не публикует (Puma).
                print(f"{chart.name} не публикует длину стопы — по замеру "
                      "размер подбирается по общей сетке, а её официальная "
                      "таблица работает для US / UK / EU.")
            else:
                print(f"{chart.name}: стопы {_num(foot)} см нет в официальной "
                      f"таблице ({gender_label} сетка: стопа от {_num(span[0])} "
                      f"до {_num(span[1])} см).")
            print()
        else:
            mark = "" if result["exact"] else " (≈ ближайший)"
            print(f"{result['brand']}{mark}:")
            values = [
                f"EU {_num(result['eu'])}",
                f"US {_num(result['us'])}" if result.get("us") is not None else "US —",
                f"UK {_num(result['uk'])}" if result.get("uk") is not None else "UK —",
            ]
            if result.get("foot") is not None:
                values.append(f"стопа {_num(result['foot'])} см")
            if (
                result.get("cm") is not None
                and (
                    result.get("foot") is None
                    or abs(result["foot"] - result["cm"]) > 0.05
                )
            ):
                values.append(f"CM/JP {_num(result['cm'])} см")
            print("  " + "  ·  ".join(values))
            print()

    rows = compare_brands(foot, args.gender)
    if rows:
        print("Сравнение брендов:")
        print(
            f"  {'Бренд':<14}{'EU':<9}{'US':<6}{'UK':<6}"
            f"{'стопа':<9}CM/JP"
        )
        for r in rows:
            def f(k):
                v = r.get(k)
                return "—" if v is None else _num(v)
            cm = (
                f("cm")
                if r.get("foot") is None
                or r.get("cm") is None
                or abs(r["foot"] - r["cm"]) > 0.05
                else "—"
            )
            print(
                f"  {r['brand']:<14}{f('eu'):<9}{f('us'):<6}{f('uk'):<6}"
                f"{f('foot'):<9}{cm}"
            )
        print("\nОдна стопа — разные EU: сетки брендов не совпадают, "
              "это нормально.")
    else:
        print(f"Стопы {_num(foot)} см нет ни в одной официальной таблице "
              f"({gender_label} сетка).")

    # Почему бренда нет в сравнении — вне таблицы или нет замера стопы.
    shown = {r["brand"] for r in rows}
    missing = []
    for chart in load_brand_charts().values():
        if chart.name in shown:
            continue
        span = _foot_range(chart, args.gender)
        missing.append(
            f"{chart.name} (не публикует длину стопы)" if span is None
            else f"{chart.name} (стопа {_num(span[0])}–{_num(span[1])} см)"
        )
    if missing:
        print("Нет в сравнении: " + ", ".join(missing))
    return 0


def cmd_brandchart(args) -> int:
    """Официальная размерная таблица бренда."""
    charts = load_brand_charts()
    if not charts:
        print("Таблицы не собраны. Запустите: python tools/build_size_charts.py",
              file=sys.stderr)
        return 2

    if not args.brand:
        print("Есть официальные таблицы:")
        for chart in charts.values():
            # Бренд без колонки замера стопы не участвует в поиске по CM.
            foot = (
                "" if all(chart.has_foot_column(g) for g in ("men", "women"))
                else "  (без длины стопы)"
            )
            print(f"  {chart.name:<14} муж. {len(chart.men):>2} · жен. {len(chart.women):>2}"
                  f"   {chart.source}{foot}")
        return 0

    chart = resolve_brand(args.brand)
    if chart is None:
        print(f"Для «{args.brand}» официальной таблицы нет; "
              "будет использована общая атлетическая сетка.", file=sys.stderr)
        return 1

    rows = chart.rows(args.gender)
    label = "женская" if args.gender == "women" else "мужская / унисекс"
    # У мужской и женской сетки бывают разные страницы-источники, а замер
    # стопы у части брендов (Reebok) опубликован отдельно.
    source = chart.sources.get(args.gender) or chart.source
    print(f"{chart.name} — {label}")
    print(f"Источник: {source}")
    foot_source = chart.sources.get("foot")
    if foot_source and foot_source != source:
        print(f"Длина стопы: {foot_source}")
    print()
    # «Стопа» — замер, «CM/JP» — ярлык бренда. У части брендов есть только
    # одна из этих колонок, и подменять одну другой нельзя.
    print(f"{'US':<8}{'UK':<8}{'EU':<10}{'стопа':<8}{'CM/JP':<8}")
    print("─" * 42)
    for row in rows:
        def fmt(key):
            value = row.get(key)
            return "—" if value is None else _num(value)
        print(
            f"{fmt('us'):<8}{fmt('uk'):<8}{fmt('eu'):<10}"
            f"{fmt('foot'):<8}{fmt('cm'):<8}"
        )
    return 0


def _port_busy(exc: OSError) -> bool:
    # На Windows errno сокета — код WSA (10048 — занят, 10013 — запрещён
    # системой или чужим эксклюзивным сокетом).
    codes = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}
    return exc.errno in codes or getattr(exc, "winerror", None) in codes


def cmd_web(args) -> int:
    from .webapp import run_server

    try:
        run_server(host=args.host, port=args.port, open_browser=not args.no_open)
    except OSError as exc:
        if _port_busy(exc):
            return _fail(
                f"порт {args.port} занят или недоступен ({exc.strerror or exc}). "
                "Возможно, сервер уже запущен — откройте "
                f"http://{args.host}:{args.port}/ или укажите другой порт: "
                f"python main.py web --port {args.port % 65535 + 1}"
            )
        return _fail(
            f"не удалось запустить сервер на {args.host}:{args.port}: "
            f"{exc.strerror or exc}"
        )
    return 0


def cmd_search(args) -> int:
    finder = _build_finder(args)
    items = finder.search_items(args.query, limit=args.limit)
    if args.format == "json":
        print(json.dumps([item.__dict__ for item in items], ensure_ascii=False, indent=2))
        return 0 if items else 1
    for index, item in enumerate(items, 1):
        article = f" · {item.article}" if item.article else ""
        print(f"{index:>2}. {_shorten(item.title, 70)}{article}")
        print(f"    SPU {item.spu_id} · {item.full_url}")
    return 0 if items else 1


# ------------------------------------------------------------- аргументы

def _int_arg(minimum: int, maximum: Optional[int] = None) -> Callable[[str], int]:
    """Тип argparse: целое в границах — отрицательный -n или -w не пройдёт."""
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"«{text}» — не целое число") from None
        if value < minimum or (maximum is not None and value > maximum):
            bounds = f"от {minimum} до {maximum}" if maximum is not None else f"не меньше {minimum}"
            raise argparse.ArgumentTypeError(f"нужно число {bounds}, а не {value}")
        return value
    return parse


def _float_arg(minimum: float, strict: bool = False) -> Callable[[str], float]:
    """Тип argparse: число ≥ minimum (strict — строго больше), «0,5» тоже."""
    def parse(text: str) -> float:
        try:
            value = float(str(text).replace(",", "."))
        except ValueError:
            raise argparse.ArgumentTypeError(f"«{text}» — не число") from None
        if not math.isfinite(value) or value < minimum or (strict and value == minimum):
            relation = "больше" if strict else "не меньше"
            raise argparse.ArgumentTypeError(
                f"нужно число {relation} {_num(minimum)}, а не {text}"
            )
        return value
    return parse


def _scale_arg(text: str) -> str:
    """--scale shoes/allbrands: известная шкала в любом регистре и с алиасами."""
    canonical = normalize_scale(text)
    if canonical not in INPUT_SCALES:
        raise argparse.ArgumentTypeError(
            f"неизвестная шкала «{text}». Доступны: {_SCALES_HELP}"
        )
    return canonical


def _native_scale_arg(text: str) -> str:
    """--scale find: только шкалы, которыми POIZON подписывает SKU."""
    value = str(text).strip().upper()
    if value not in NATIVE_SCALES:
        raise argparse.ArgumentTypeError(
            f"на POIZON размеры подписаны только в {' и '.join(NATIVE_SCALES)}, "
            f"а не в «{text}». Для US/UK/CM используйте shoes --scale"
        )
    return value


def _common_flags(suppress: bool) -> argparse.ArgumentParser:
    """Родительский парсер общих флагов.

    Флаги висят и на корневом парсере, и на каждой подкоманде, чтобы их
    можно было писать и до, и после имени команды. Значения по умолчанию —
    только у корневого: у копий в подкомандах default=SUPPRESS, иначе их
    умолчания затирали бы флаг, указанный перед командой.
    """
    def default(value):
        return argparse.SUPPRESS if suppress else value

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--delay", type=_float_arg(0.0), default=default(0.7),
                        help="пауза между запросами, с (по умолчанию 0.7)")
    common.add_argument("--timeout", type=_float_arg(0.0, strict=True), default=default(30.0),
                        help="таймаут запроса, с")
    common.add_argument("-v", "--verbose", action="store_true", default=default(False),
                        help="подробный лог запросов")
    common.add_argument("--quiet", action="store_true", default=default(False),
                        help="без прогресса в stderr")
    common.add_argument("--no-cache", action="store_true", default=default(False),
                        help="не использовать кэш страниц")
    common.add_argument("--cache-ttl", type=_float_arg(0.0), default=default(900.0),
                        help="срок жизни кэша, с")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common_flags(suppress=False)
    sub_common = _common_flags(suppress=True)
    count = _int_arg(1)
    zero_or_more = _int_arg(0)
    non_negative = _float_arg(0.0)

    parser = argparse.ArgumentParser(
        prog="python main.py",
        parents=[common],
        description="Парсер thepoizon.ru: подбор моделей обуви по размеру с ценами.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Веб-интерфейс (рекомендуется):\n"
            "  python main.py web                             — откроется в браузере\n"
            "\n"
            "Основной сценарий — обувь бренда по длине стопы:\n"
            "  python main.py brands                          — список брендов\n"
            "  python main.py shoes -b nike -s 26,5           — стопа 26,5 см, в наличии\n"
            "  python main.py shoes -b adidas -s 27 --gender women\n"
            "  python main.py shoes -b nike -s 42 --scale EU  — если знаете размер в EU\n"
            "  python main.py allbrands -s 26,5               — сразу все бренды с\n"
            "                                                   официальной таблицей\n"
            "  python main.py brandchart nike                 — официальная таблица бренда\n"
            "\n"
            "Поиск по названию:\n"
            "  python main.py find -q \"nike air force 1\" -s 42\n"
            "  python main.py sizes 8900001978861819\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    web = sub.add_parser("web", parents=[sub_common], help="запустить веб-интерфейс")
    web.add_argument("--host", default="127.0.0.1", help="адрес (по умолчанию 127.0.0.1)")
    web.add_argument("--port", type=_int_arg(1, 65535), default=8765,
                     help="порт (по умолчанию 8765)")
    web.add_argument("--no-open", action="store_true", help="не открывать браузер")
    web.set_defaults(func=cmd_web)

    shoes = sub.add_parser(
        "shoes", parents=[sub_common],
        help="обувь выбранного бренда в вашем размере (основной сценарий)",
    )
    shoes.add_argument("-b", "--brand", required=True, help="бренд: nike, adidas, «New Balance»")
    shoes.add_argument(
        "-s", "--size", required=True,
        help=f"длина стопы в сантиметрах ({FOOT_MIN_CM:g}–{FOOT_MAX_CM:g}), например 26,5",
    )
    shoes.add_argument(
        "--scale", type=_scale_arg, default=CM,
        help="шкала: CM — длина стопы (по умолчанию). Для ввода в EU/UK/«US M»/"
             "«US W»/RU укажите шкалу явно",
    )
    shoes.add_argument(
        "--gender", choices=["men", "women"], default="men",
        help="какая сетка бренда: мужская/унисекс (по умолчанию) или женская",
    )
    shoes.add_argument("-n", "--limit", type=count, default=20, help="сколько моделей вывести")
    shoes.add_argument("--check", type=zero_or_more, default=40,
                       help="сколько карточек проверить; 0 — весь каталог")
    shoes.add_argument("--tolerance", type=non_negative, default=0.0, help="допуск по размеру")
    shoes.add_argument("--max-price", type=non_negative, help="максимальная цена размера")
    shoes.add_argument("--min-price", type=non_negative, help="минимальная цена размера")
    shoes.add_argument("--kids", action="store_true", help="включая детскую обувь")
    shoes.add_argument(
        "-w", "--workers", type=count, default=3,
        help="параллельных загрузок карточек (темп запросов не растёт)",
    )
    shoes.add_argument("-f", "--format", choices=["table", "json", "csv", "html"], default="table")
    shoes.add_argument("--embed-images", action="store_true",
                       help="вшить фото в HTML-отчёт (автономный файл, тяжелее)")
    shoes.add_argument("-o", "--out",
                       help="сохранить результат в файл; для -f html — папка отчёта "
                            "(по умолчанию result/)")
    shoes.set_defaults(func=cmd_shoes)

    allbrands = sub.add_parser(
        "allbrands", parents=[sub_common],
        help="обувь сразу всех брендов с официальной таблицей размеров",
    )
    allbrands.add_argument(
        "-s", "--size", required=True,
        help=f"длина стопы в сантиметрах ({FOOT_MIN_CM:g}–{FOOT_MAX_CM:g}), например 26,5",
    )
    allbrands.add_argument(
        "--scale", type=_scale_arg, default=CM,
        help="шкала: CM — длина стопы (по умолчанию). В EU/UK/«US M»/«US W» "
             "участвуют и бренды без колонки замера стопы",
    )
    allbrands.add_argument(
        "--gender", choices=["men", "women"], default="men",
        help="какая сетка брендов: мужская/унисекс (по умолчанию) или женская",
    )
    allbrands.add_argument(
        "--brands", nargs="+",
        help="только эти бренды из списка официальных, например nike reebok",
    )
    allbrands.add_argument("-n", "--limit", type=count, default=10,
                           help="сколько моделей брать у одного бренда")
    allbrands.add_argument("--total", type=zero_or_more, default=0,
                           help="общий потолок выдачи; 0 — без ограничения")
    allbrands.add_argument("--check", type=zero_or_more, default=40,
                           help="сколько карточек проверять у бренда; 0 — весь каталог")
    allbrands.add_argument("--tolerance", type=non_negative, default=0.0,
                           help="допуск по размеру")
    allbrands.add_argument("--max-price", type=non_negative, help="максимальная цена размера")
    allbrands.add_argument("--min-price", type=non_negative, help="минимальная цена размера")
    allbrands.add_argument("--kids", action="store_true", help="включая детскую обувь")
    allbrands.add_argument("-w", "--workers", type=count, default=3,
                           help="параллельных загрузок карточек")
    allbrands.add_argument("-f", "--format",
                           choices=["table", "json", "csv", "html"], default="table")
    allbrands.add_argument("--embed-images", action="store_true",
                           help="вшить фото в HTML-отчёт")
    allbrands.add_argument("-o", "--out",
                           help="сохранить результат в файл; для -f html — папка отчёта "
                                "(по умолчанию result/)")
    allbrands.set_defaults(func=cmd_allbrands)

    brands = sub.add_parser("brands", parents=[sub_common], help="список брендов сайта")
    brands.add_argument("query", nargs="?", help="фильтр по названию")
    brands.add_argument("-f", "--format", choices=["table", "json"], default="table")
    brands.set_defaults(func=cmd_brands)

    size = sub.add_parser(
        "size", parents=[sub_common],
        help="калькулятор: длина стопы → размеры бренда и сравнение брендов",
    )
    size.add_argument("foot", help="длина стопы в см, например 26,5")
    size.add_argument("-b", "--brand", help="бренд (необязательно)")
    size.add_argument("--gender", choices=["men", "women"], default="men")
    size.set_defaults(func=cmd_size)

    brandchart = sub.add_parser(
        "brandchart", parents=[sub_common],
        help="официальная размерная таблица бренда "
             "(Nike, Adidas, New Balance, ASICS, Reebok, Puma)",
    )
    brandchart.add_argument("brand", nargs="?", help="бренд; без имени — список таблиц")
    brandchart.add_argument("--gender", choices=["men", "women"], default="men")
    brandchart.set_defaults(func=cmd_brandchart)

    chart = sub.add_parser("chart", parents=[sub_common], help="таблица размеров конкретной модели")
    chart.add_argument("product", help="ссылка на товар или spuId")
    chart.add_argument("-f", "--format", choices=["table", "json"], default="table")
    chart.set_defaults(func=cmd_chart)

    find = sub.add_parser("find", parents=[sub_common], help="найти модели с нужным размером")
    find.add_argument("-q", "--query", required=True, help="что искать, например «nike air force 1»")
    find.add_argument("-s", "--size", required=True, help="размер: 42, «42,5», «EU 43»")
    find.add_argument(
        "--scale", type=_native_scale_arg, metavar="{RU,EU}",
        help="шкала размера на POIZON (регистр не важен)",
    )
    find.add_argument(
        "--strict-scale",
        action="store_true",
        help="не искать размер в других шкалах, если в основной его нет",
    )
    find.add_argument("-n", "--limit", type=count, default=10, help="сколько моделей вернуть")
    find.add_argument("--check", type=zero_or_more,
                      help="сколько карточек проверить (по умолчанию limit*3)")
    find.add_argument("--tolerance", type=non_negative, default=0.0,
                      help="допуск по размеру, напр. 0.5")
    find.add_argument("--max-price", type=non_negative, help="максимальная цена размера")
    find.add_argument("--min-price", type=non_negative, help="минимальная цена размера")
    find.add_argument("--include-unavailable", action="store_true", help="включая размеры без предложений")
    find.add_argument("-f", "--format", choices=["table", "json", "csv"], default="table")
    find.add_argument("-o", "--out", help="сохранить результат в файл")
    find.set_defaults(func=cmd_find)

    sizes = sub.add_parser("sizes", parents=[sub_common], help="все размеры и цены одного товара")
    sizes.add_argument("product", help="ссылка на товар или spuId")
    sizes.add_argument("--in-stock", action="store_true", help="только доступные размеры")
    sizes.add_argument("-f", "--format", choices=["table", "json"], default="table")
    sizes.set_defaults(func=cmd_sizes)

    search = sub.add_parser("search", parents=[sub_common], help="просто поиск моделей без разбора размеров")
    search.add_argument("-q", "--query", required=True)
    search.add_argument("-n", "--limit", type=count, default=20)
    search.add_argument("-f", "--format", choices=["table", "json"], default="table")
    search.set_defaults(func=cmd_search)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    _setup_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return 130
    except PoizonError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # Наследники ValueError, но виноват не ввод, а ответ сайта.
        print(f"Ошибка: не удалось разобрать ответ сайта ({exc})", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Ошибка ввода: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        where = f" — {exc.filename}" if getattr(exc, "filename", None) else ""
        print(f"Ошибка: {exc.strerror or exc}{where}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
