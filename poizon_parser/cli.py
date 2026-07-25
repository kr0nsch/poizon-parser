"""Командный интерфейс парсера."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .client import PoizonClient, PoizonError
from .finder import SizeFinder
from .models import Match, Product
from .sizes import parse_size, parse_size_query


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


def _shorten(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _fit_hint(size_tip: str) -> str:
    """«Размер больше, возьмите размер -0,5» → «-0,5»."""
    if not size_tip:
        return "—"
    match = re.search(r"([+-]\s*\d+(?:[.,]\d+)?)", size_tip)
    if match:
        return match.group(1).replace(" ", "")
    return "—"


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


# --------------------------------------------------------------- команды

def _terminal_challenge(info: dict) -> bool:
    """Пауза в терминале: ждём, пока пользователь пройдёт капчу, и Enter."""
    reason = info.get("reason")
    url = info.get("url")
    print(
        f"\n⚠  Сайт показал проверку ({reason}).\n"
        f"   Откройте в браузере и пройдите её:\n   {url}\n"
        f"   Затем нажмите Enter, чтобы продолжить (или введите q + Enter — прервать).",
        file=sys.stderr,
    )
    try:
        answer = input()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() not in ("q", "quit", "exit", "stop")


def _client_from(args) -> PoizonClient:
    cache_dir = None if getattr(args, "no_cache", False) else _default_cache_dir()
    return PoizonClient(
        delay=args.delay,
        timeout=args.timeout,
        verbose=args.verbose,
        cache_dir=cache_dir,
        cache_ttl=getattr(args, "cache_ttl", 900.0),
        on_challenge=_terminal_challenge if sys.stdin and sys.stdin.isatty() else None,
    )


def _default_cache_dir() -> str:
    return str(Path(tempfile.gettempdir()) / "poizon-parser-cache")


def _build_finder(args) -> SizeFinder:
    progress = (lambda message: print(message, file=sys.stderr)) if not args.quiet else (lambda m: None)
    return SizeFinder(client=_client_from(args), on_progress=progress)


def cmd_find(args) -> int:
    finder = _build_finder(args)
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

    if args.format == "json":
        output = render_json(matches)
    elif args.format == "csv":
        output = render_csv(matches)
    else:
        output = render_table(matches)

    if args.out:
        with open(args.out, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write(output)
        print(f"Сохранено в {args.out} ({len(matches)} строк)", file=sys.stderr)
    else:
        print(output)
    return 0 if matches else 1


def cmd_sizes(args) -> int:
    finder = _build_finder(args)
    try:
        product = finder.load_product(args.product)
    except PoizonError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
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
                    "price": offer.price,
                    "price_text": offer.price_text,
                    "in_stock": offer.in_stock,
                    "delivery": offer.delivery,
                    "sku_id": offer.sku_id,
                }
                for offer in product.offers
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_product_sizes(product, only_in_stock=args.in_stock))
    return 0


def render_shoes_table(matches: list[Match], title_width: int = 44) -> str:
    """Итоговая таблица основного сценария: бренд + размер → что в наличии."""
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
                _shorten(match.product.title, title_width),
                poizon_label,
                _fit_hint(match.product.size_tip),
                ("≈ " if not match.exact_conversion else "")
                + _money(offer.price, offer.price_text),
                _shorten(offer.delivery or "—", 12),
                str(match.product.spu_id),
            )
        )

    headers = ("#", "Модель", "Размер на POIZON", "Посадка", "Цена", "Доставка", "SPU")
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
            f"В наличии: {len(matches)} моделей · от {_money(min(priced))} "
            f"до {_money(max(priced))}"
        )

    # Перевод считается по таблице каждой модели, поэтому у разных позиций
    # один и тот же размер может дать разный EU — показываем это честно.
    converted = {m.converted_eu for m in matches if m.converted_eu is not None}
    if converted:
        shown = ", ".join(f"EU {v:g}".replace(".", ",") for v in sorted(converted))
        out.append(f"Запрошено: {first.requested_size:g} {first.requested_scale} → {shown}")
        if len(converted) > 1:
            out.append(
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
    return "\n".join(line for line in out if line != "")


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
    finder = _build_finder(args)
    try:
        matches = finder.find_by_brand(
            brand=args.brand,
            size=args.size,
            scale=args.scale,
            limit=args.limit,
            check=args.check or None,  # 0 → весь каталог
            tolerance=args.tolerance,
            max_price=args.max_price,
            min_price=args.min_price,
            include_kids=args.kids,
            workers=args.workers,
            gender=args.gender,
        )
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    # HTML-отчёт: самодостаточный файл в result/, который можно переслать.
    if args.format == "html":
        if not matches:
            print("Ничего не найдено — отчёт не создан.", file=sys.stderr)
            return 1
        from .report import write_report

        meta = {
            "brand": args.brand,
            "size_input": args.size,
            "scale": args.scale,
            "gender": args.gender,
        }
        out_dir = write_report(
            [m.to_dict() for m in matches], meta,
            embed_images=getattr(args, "embed_images", False),
        )
        report = out_dir / "index.html"
        print(f"Отчёт готов: {report}")
        print(f"Откройте его в браузере или перешлите файл — {len(matches)} моделей.")
        return 0

    if args.format == "json":
        output = render_json(matches)
    elif args.format == "csv":
        output = render_csv(matches)
    else:
        output = render_shoes_table(matches)

    if args.out:
        with open(args.out, "w", encoding="utf-8-sig", newline="") as handle:
            handle.write(output)
        print(f"Сохранено в {args.out} ({len(matches)} строк)", file=sys.stderr)
    else:
        print(output)
    return 0 if matches else 1


def cmd_chart(args) -> int:
    """Официальная таблица размеров конкретной модели."""
    finder = _build_finder(args)
    try:
        product = finder.load_product(args.product)
    except PoizonError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    chart = product.chart
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


def cmd_size(args) -> int:
    """Калькулятор: длина стопы → размеры бренда (и сравнение брендов)."""
    from .sizechart import compare_brands, sizes_for_foot

    try:
        foot = float(str(args.foot).replace(",", "."))
    except ValueError:
        print(f"Ошибка: «{args.foot}» не число", file=sys.stderr)
        return 2
    if not (10 <= foot <= 40):
        print("Ошибка: длина стопы должна быть в сантиметрах (10–40)", file=sys.stderr)
        return 2

    gender_label = "женская" if args.gender == "women" else "мужская"
    print(f"Длина стопы {foot:g} см · {gender_label} сетка\n")

    if args.brand:
        result = sizes_for_foot(args.brand, foot, args.gender)
        if result is None:
            print(f"Для «{args.brand}» официальной таблицы нет — "
                  "размер подберётся по общей сетке при поиске.")
        else:
            mark = "" if result["exact"] else " (≈ ближайший)"
            print(f"{result['brand']}{mark}:")
            print(f"  EU {result.get('eu'):g}  ·  US {result.get('us'):g}  ·  "
                  f"UK {result.get('uk'):g}  ·  ярлык {result.get('cm'):g} см")
            print()

    rows = compare_brands(foot, args.gender)
    if rows:
        print("Сравнение брендов:")
        print(f"  {'Бренд':<14}{'EU':<9}{'US':<6}{'UK':<6}ярлык, см")
        for r in rows:
            def f(k):
                v = r.get(k)
                return "—" if v is None else f"{v:g}".replace(".", ",")
            print(f"  {r['brand']:<14}{f('eu'):<9}{f('us'):<6}{f('uk'):<6}{f('cm')}")
        print("\nОдна стопа — разные EU: сетки брендов не совпадают, "
              "это нормально.")
    return 0


def cmd_brandchart(args) -> int:
    """Официальная размерная таблица бренда."""
    from .sizechart import load_brand_charts, resolve_brand

    charts = load_brand_charts()
    if not charts:
        print("Таблицы не собраны. Запустите: python tools/build_size_charts.py",
              file=sys.stderr)
        return 2

    if not args.brand:
        print("Есть официальные таблицы:")
        for chart in charts.values():
            print(f"  {chart.name:<14} муж. {len(chart.men):>2} · жен. {len(chart.women):>2}"
                  f"   {chart.source}")
        return 0

    chart = resolve_brand(args.brand)
    if chart is None:
        print(f"Для «{args.brand}» официальной таблицы нет; "
              "будет использована общая атлетическая сетка.", file=sys.stderr)
        return 1

    rows = chart.rows(args.gender)
    label = "женская" if args.gender == "women" else "мужская / унисекс"
    print(f"{chart.name} — {label}")
    print(f"Источник: {chart.source}\n")
    print(f"{'US':<8}{'UK':<8}{'EU':<10}{'см':<8}")
    print("─" * 34)
    for row in rows:
        def fmt(key):
            value = row.get(key)
            return "—" if value is None else f"{value:g}".replace(".", ",")
        print(f"{fmt('us'):<8}{fmt('uk'):<8}{fmt('eu'):<10}{fmt('cm'):<8}")
    return 0


def cmd_web(args) -> int:
    from .webapp import run_server

    run_server(host=args.host, port=args.port, open_browser=not args.no_open)
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


def build_parser() -> argparse.ArgumentParser:
    # Общие флаги вынесены в родительский парсер, чтобы их можно было
    # указывать и до, и после имени команды.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--delay", type=float, default=0.7, help="пауза между запросами, с (по умолчанию 0.7)")
    common.add_argument("--timeout", type=float, default=30.0, help="таймаут запроса, с")
    common.add_argument("-v", "--verbose", action="store_true", help="подробный лог запросов")
    common.add_argument("--quiet", action="store_true", help="без прогресса в stderr")
    common.add_argument("--no-cache", action="store_true", help="не использовать кэш страниц")
    common.add_argument("--cache-ttl", type=float, default=900.0, help="срок жизни кэша, с")

    parser = argparse.ArgumentParser(
        prog="poizon",
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
            "  python main.py brandchart nike                 — официальная таблица бренда\n"
            "\n"
            "Поиск по названию:\n"
            "  python main.py find -q \"nike air force 1\" -s 42\n"
            "  python main.py sizes 8900001978861819\n"
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    web = sub.add_parser("web", parents=[common], help="запустить веб-интерфейс")
    web.add_argument("--host", default="127.0.0.1", help="адрес (по умолчанию 127.0.0.1)")
    web.add_argument("--port", type=int, default=8765, help="порт (по умолчанию 8765)")
    web.add_argument("--no-open", action="store_true", help="не открывать браузер")
    web.set_defaults(func=cmd_web)

    shoes = sub.add_parser(
        "shoes", parents=[common],
        help="обувь выбранного бренда в вашем размере (основной сценарий)",
    )
    shoes.add_argument("-b", "--brand", required=True, help="бренд: nike, adidas, «New Balance»")
    shoes.add_argument(
        "-s", "--size", required=True,
        help="длина стопы в сантиметрах, например 26,5",
    )
    shoes.add_argument(
        "--scale", default="CM",
        help="шкала: CM — длина стопы (по умолчанию). Для ввода в EU/UK/«US M»/"
             "«US W»/RU укажите шкалу явно",
    )
    shoes.add_argument(
        "--gender", choices=["men", "women"], default="men",
        help="какая сетка бренда: мужская/унисекс (по умолчанию) или женская",
    )
    shoes.add_argument("-n", "--limit", type=int, default=20, help="сколько моделей вывести")
    shoes.add_argument("--check", type=int, default=40, help="сколько карточек проверить; 0 — весь каталог")
    shoes.add_argument("--tolerance", type=float, default=0.0, help="допуск по размеру")
    shoes.add_argument("--max-price", type=float, help="максимальная цена размера")
    shoes.add_argument("--min-price", type=float, help="минимальная цена размера")
    shoes.add_argument("--kids", action="store_true", help="включая детскую обувь")
    shoes.add_argument(
        "-w", "--workers", type=int, default=3,
        help="параллельных загрузок карточек (темп запросов не растёт)",
    )
    shoes.add_argument("-f", "--format", choices=["table", "json", "csv", "html"], default="table")
    shoes.add_argument("--embed-images", action="store_true",
                       help="вшить фото в HTML-отчёт (автономный файл, тяжелее)")
    shoes.add_argument("-o", "--out", help="сохранить результат в файл")
    shoes.set_defaults(func=cmd_shoes)

    brands = sub.add_parser("brands", parents=[common], help="список брендов сайта")
    brands.add_argument("query", nargs="?", help="фильтр по названию")
    brands.add_argument("-f", "--format", choices=["table", "json"], default="table")
    brands.set_defaults(func=cmd_brands)

    size = sub.add_parser(
        "size", parents=[common],
        help="калькулятор: длина стопы → размеры бренда и сравнение брендов",
    )
    size.add_argument("foot", help="длина стопы в см, например 26,5")
    size.add_argument("-b", "--brand", help="бренд (необязательно)")
    size.add_argument("--gender", choices=["men", "women"], default="men")
    size.set_defaults(func=cmd_size)

    brandchart = sub.add_parser(
        "brandchart", parents=[common],
        help="официальная размерная таблица бренда (Nike/Adidas/NB/ASICS)",
    )
    brandchart.add_argument("brand", nargs="?", help="бренд; без имени — список таблиц")
    brandchart.add_argument("--gender", choices=["men", "women"], default="men")
    brandchart.set_defaults(func=cmd_brandchart)

    chart = sub.add_parser("chart", parents=[common], help="таблица размеров конкретной модели")
    chart.add_argument("product", help="ссылка на товар или spuId")
    chart.add_argument("-f", "--format", choices=["table"], default="table")
    chart.set_defaults(func=cmd_chart)

    find = sub.add_parser("find", parents=[common], help="найти модели с нужным размером")
    find.add_argument("-q", "--query", required=True, help="что искать, например «nike air force 1»")
    find.add_argument("-s", "--size", required=True, help="размер: 42, «42,5», «EU 43»")
    find.add_argument("--scale", choices=["RU", "EU", "US", "UK", "CN", "JP"], help="шкала размера")
    find.add_argument(
        "--strict-scale",
        action="store_true",
        help="не искать размер в других шкалах, если в основной его нет",
    )
    find.add_argument("-n", "--limit", type=int, default=10, help="сколько моделей вернуть")
    find.add_argument("--check", type=int, help="сколько карточек проверить (по умолчанию limit*3)")
    find.add_argument("--tolerance", type=float, default=0.0, help="допуск по размеру, напр. 0.5")
    find.add_argument("--max-price", type=float, help="максимальная цена размера")
    find.add_argument("--min-price", type=float, help="минимальная цена размера")
    find.add_argument("--include-unavailable", action="store_true", help="включая размеры без предложений")
    find.add_argument("-f", "--format", choices=["table", "json", "csv"], default="table")
    find.add_argument("-o", "--out", help="сохранить результат в файл")
    find.set_defaults(func=cmd_find)

    sizes = sub.add_parser("sizes", parents=[common], help="все размеры и цены одного товара")
    sizes.add_argument("product", help="ссылка на товар или spuId")
    sizes.add_argument("--in-stock", action="store_true", help="только доступные размеры")
    sizes.add_argument("-f", "--format", choices=["table", "json"], default="table")
    sizes.set_defaults(func=cmd_sizes)

    search = sub.add_parser("search", parents=[common], help="просто поиск моделей без разбора размеров")
    search.add_argument("-q", "--query", required=True)
    search.add_argument("-n", "--limit", type=int, default=20)
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
    except ValueError as exc:
        print(f"Ошибка ввода: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
