"""Поиск моделей обуви по размеру.

Сценарий: по ключевому слову берём выдачу, затем по каждой карточке
загружаем страницу товара и проверяем, есть ли нужный размер и почём он.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Callable, Iterable, Optional

from .client import Cancelled, ChallengeRequired, PoizonClient, PoizonError
from .extract import parse_product
from .models import Match, Product, SearchItem
from .sizechart import (
    CM,
    EU,
    SizeChart,
    convert_to_eu,
    official_charts,
    resolve_brand,
    resolve_query_scale,
)
from .sizes import SIZE_EPSILON, match_size, parse_size_query, scale_priority

if TYPE_CHECKING:
    from .catalog import Catalog


def _by_price(matches: Iterable[Match]) -> list[Match]:
    """Порядок выдачи: дешевле — выше, без цены — в конце."""
    return sorted(
        matches,
        key=lambda m: m.offer.price if m.offer.price is not None else float("inf"),
    )


class SizeFinder:
    """Связывает поиск, загрузку карточек и подбор размера."""

    def __init__(
        self,
        client: Optional[PoizonClient] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.client = client or PoizonClient()
        self.on_progress = on_progress or (lambda message: None)

    # --------------------------------------------------------------- поиск

    def search_items(self, query: str, limit: int = 20) -> list[SearchItem]:
        """Поисковая выдача в виде объектов SearchItem."""
        items: list[SearchItem] = []
        for raw in self.client.search(query, limit=limit):
            spu_id = raw.get("spuId")
            if not spu_id:
                continue
            items.append(
                SearchItem(
                    spu_id=int(spu_id),
                    title=str(raw.get("title") or "").strip(),
                    url=str(raw.get("url") or f"/product/{spu_id}"),
                    article=str(raw.get("articleNumber") or ""),
                    logo_url=str(raw.get("logoUrl") or ""),
                    brand_id=raw.get("brandId"),
                )
            )
        return items

    def load_product(self, item: SearchItem | str | int) -> Product:
        """Загружает карточку товара со всеми размерами и ценами."""
        if isinstance(item, SearchItem):
            url, article = item.url, item.article
        else:
            url, article = str(item), ""
            if url.isdigit():
                url = f"/product/{url}"

        html = self.client.fetch_product_html(url)
        next_data = self.client.extract_next_data(html)
        product = parse_product(next_data, url=url, article=article)

        if isinstance(item, SearchItem):
            product.title = product.title or item.title
            product.logo_url = product.logo_url or item.logo_url
        return product

    # ------------------------------------------------------------- подбор

    def match_product(
        self,
        product: Product,
        size: float,
        scale: Optional[str] = None,
        tolerance: float = 0.0,
        only_in_stock: bool = True,
        allow_scale_fallback: bool = True,
    ) -> Optional[Match]:
        """Ищет в карточке подходящий размер. Возвращает лучший вариант.

        Шкалы перебираются строго по очереди: сначала запрошенная (или та,
        что сайт показывает по умолчанию для этой модели), и только если в
        ней размера нет — следующая. Смешивать шкалы нельзя: «42 RU» и
        «42 EU» — это разная обувь, и выбор «где дешевле» между ними подсунул
        бы не тот размер.

        allow_scale_fallback=False запрещает переход к другим шкалам: если в
        основной шкале размера нет, модель просто не попадёт в выдачу.
        """
        if scale:
            candidate_scales = [scale]
        else:
            primary = product.default_scale or (
                product.size_scales[0] if product.size_scales else None
            )
            candidate_scales = scale_priority(product.size_scales, primary)
            if not candidate_scales:
                candidate_scales = [None]  # шкал нет — сопоставляем как есть
            elif not allow_scale_fallback:
                candidate_scales = candidate_scales[:1]

        for candidate in candidate_scales:
            best = self._best_offer(product, size, candidate, tolerance, only_in_stock)
            if best is not None:
                return best
        return None

    def _best_offer(
        self,
        product: Product,
        size: float,
        scale: Optional[str],
        tolerance: float,
        only_in_stock: bool,
    ) -> Optional[Match]:
        """Лучшее предложение внутри одной шкалы: ближе по размеру, затем дешевле."""
        best: Optional[Match] = None
        best_delta = float("inf")

        for offer in product.offers:
            if only_in_stock and not offer.in_stock:
                continue
            hit = match_size(offer.sizes, size, scale=scale, tolerance=tolerance)
            if hit is None:
                continue

            matched_scale, delta = hit
            price = offer.price if offer.price is not None else float("inf")
            best_price = (
                best.offer.price
                if best and best.offer.price is not None
                else float("inf")
            )
            # В пределах одной шкалы одинаковый размер бывает в разной полноте —
            # там выбор по цене уже корректен.
            if delta < best_delta - SIZE_EPSILON or (
                abs(delta - best_delta) <= SIZE_EPSILON and price < best_price
            ):
                best = Match(
                    product=product,
                    offer=offer,
                    matched_scale=matched_scale,
                    requested_size=size,
                )
                best_delta = delta

        return best

    def find(
        self,
        query: str,
        size: str | float,
        scale: Optional[str] = None,
        limit: int = 10,
        search_limit: Optional[int] = None,
        tolerance: float = 0.0,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
        only_in_stock: bool = True,
        sort_by_price: bool = True,
        allow_scale_fallback: bool = True,
    ) -> list[Match]:
        """Полный сценарий: поиск → карточки → отбор по размеру.

        Args:
            query: ключевое слово, например «nike air force 1».
            size: искомый размер («42», «42,5», «EU 43»).
            scale: шкала размера; None — искать в любой.
            limit: сколько подходящих моделей вернуть.
            search_limit: сколько карточек проверить (по умолчанию limit * 3).
            tolerance: допуск по размеру, 0.5 захватит соседний полуразмер.
            max_price / min_price: фильтр по цене найденного размера.
            only_in_stock: пропускать размеры без предложений.
            sort_by_price: сортировать результат по цене.
        """
        if isinstance(size, str):
            parsed_scale, size_value = parse_size_query(size)
            scale = scale or parsed_scale
        else:
            size_value = float(size)
        if scale:
            scale = scale.upper()

        to_check = search_limit or max(limit * 3, 10)
        items = self.search_items(query, limit=to_check)
        if not items:
            self.on_progress(f"по запросу «{query}» ничего не найдено")
            return []

        self.on_progress(
            f"найдено моделей: {len(items)}; проверяю размер "
            f"{size_value:g}{' ' + scale if scale else ''}"
        )

        matches: list[Match] = []
        for index, item in enumerate(items, 1):
            if len(matches) >= limit:
                break
            try:
                product = self.load_product(item)
            except ChallengeRequired as exc:
                # Проверка сайта — не беда одной карточки: дальше сайт
                # блокирует всё подряд. Найденное до неё не теряем.
                exc.partial = _by_price(matches) if sort_by_price else list(matches)
                raise
            except Cancelled:
                # Пользователь уже ответил «стоп».
                raise
            except PoizonError as exc:
                self.on_progress(f"[{index}/{len(items)}] пропуск {item.spu_id}: {exc}")
                continue

            match = self.match_product(
                product, size_value, scale=scale, tolerance=tolerance,
                only_in_stock=only_in_stock, allow_scale_fallback=allow_scale_fallback,
            )
            if match is None:
                self.on_progress(
                    f"[{index}/{len(items)}] {product.title[:52]} — размера нет"
                )
                continue

            price = match.offer.price
            if price is not None:
                if max_price is not None and price > max_price:
                    self.on_progress(
                        f"[{index}/{len(items)}] {product.title[:52]} — дороже лимита ({price:.0f})"
                    )
                    continue
                if min_price is not None and price < min_price:
                    continue

            self.on_progress(
                f"[{index}/{len(items)}] {product.title[:52]} — "
                f"{match.offer.size_in(match.matched_scale)} {match.matched_scale}: "
                f"{match.offer.price_text or 'нет цены'}"
            )
            matches.append(match)

        return _by_price(matches) if sort_by_price else matches

    def match_by_scale(
        self,
        product: Product,
        value: float,
        scale: str,
        tolerance: float = 0.0,
        only_in_stock: bool = True,
        brand: Optional[str] = None,
        gender: str = "men",
    ) -> Optional[Match]:
        """Подбор размера с переводом в EU.

        Размер задан в шкале производителя (EU / US M / US W / UK / CM), а SKU
        на сайте подписаны только RU и EU. Перевод берётся в первую очередь из
        официальной таблицы бренда, если она известна.
        """
        chart = product.chart if isinstance(product.chart, SizeChart) else None
        conversion = convert_to_eu(
            scale, value, chart, brand=brand or product.brand, gender=gender
        )
        if not conversion.supported:
            return None

        # Неточный перевод — разрешаем добрать ближайший размер сетки:
        # у Adidas шаг ⅓, и точного попадания в EU может не быть.
        effective_tolerance = tolerance
        if not conversion.exact:
            effective_tolerance = max(tolerance, 0.34)

        match = self._best_offer(
            product, conversion.eu, EU, effective_tolerance, only_in_stock
        )
        if match is None:
            return None

        match.requested_size = value
        match.requested_scale = scale
        match.converted_eu = conversion.eu
        match.exact_conversion = conversion.exact
        match.conversion_source = conversion.source
        match.conversion_note = conversion.note
        match.converted_cm = conversion.cm
        match.converted_foot = conversion.foot
        return match

    def find_by_brand(
        self,
        brand: str,
        size: str | float,
        scale: str = EU,
        limit: int = 20,
        check: Optional[int] = 40,
        tolerance: float = 0.0,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
        include_kids: bool = False,
        catalog: Optional["Catalog"] = None,
        workers: int = 1,
        gender: str = "men",
    ) -> list[Match]:
        """Обувь бренда в нужном размере, только та, что есть в наличии.

        Основной сценарий: выбрал бренд → указал свой размер → получил список
        с ценами. Категория ограничена обувью, размеры без предложений
        отбрасываются.

        Шкала из строки размера («US W 7») и явная scale сводятся по общему
        правилу resolve_query_scale. Если обход оборвала проверка сайта,
        ChallengeRequired уходит наружу с находками в ``exc.partial``.
        """
        from .catalog import Catalog  # локальный импорт: избегаем цикла

        catalog = catalog or Catalog(self.client)
        found = catalog.find_brand(brand)
        if found is None:
            hints = ", ".join(b.name for b in catalog.suggest_brands(brand))
            raise ValueError(
                f"бренд «{brand}» не найден"
                + (f". Похожие: {hints}" if hints else "")
            )

        parsed_scale = None
        if isinstance(size, str):
            parsed_scale, size_value = parse_size_query(size)
        else:
            size_value = float(size)
        scale = resolve_query_scale(parsed_scale, scale, default=EU)

        depth = "весь каталог" if not check else f"до {check} моделей"
        self.on_progress(
            f"бренд: {found.name} · размер {size_value:g} {scale} · "
            f"проверяю {depth} обуви"
        )

        items = list(
            catalog.brand_items(
                found, max_items=check or None, include_kids=include_kids
            )
        )
        if not items:
            self.on_progress("в каталоге бренда нет обуви")
            return []

        # Предфильтр по цене из листинга: если минимум по всем размерам уже
        # дороже лимита, нужный размер дешевле не станет — карточку не грузим.
        if max_price is not None:
            before = len(items)
            items = [
                item for item in items
                if item.min_price is None or item.min_price <= max_price
            ]
            skipped = before - len(items)
            if skipped:
                self.on_progress(
                    f"пропущено по цене без загрузки карточек: {skipped}"
                )

        try:
            matches = self.scan_products(
                items,
                size_value,
                scale,
                brand_name=found.name,
                tolerance=tolerance,
                max_price=max_price,
                min_price=min_price,
                limit=limit,
                workers=workers,
                gender=gender,
            )
        except ChallengeRequired as exc:
            exc.partial = _by_price(getattr(exc, "partial", None) or [])
            raise
        return _by_price(matches)

    def find_in_official_brands(
        self,
        size: str | float,
        scale: str = CM,
        limit: int = 10,
        total_limit: Optional[int] = None,
        check: Optional[int] = 40,
        tolerance: float = 0.0,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
        include_kids: bool = False,
        catalog: Optional["Catalog"] = None,
        workers: int = 1,
        gender: str = "men",
        only: Optional[Iterable[str]] = None,
        on_brand: Optional[Callable[[str, list[Match]], None]] = None,
    ) -> list[Match]:
        """Обход сразу всех брендов с официальной таблицей размеров.

        Один замер стопы → одна выдача по всем таким брендам: каждому размер
        переводится по **его** официальной сетке, поэтому в одном списке лежат
        разные EU — это не ошибка, а несовпадение сеток производителей.

        Берутся только бренды, публикующие запрошенную шкалу: по длине стопы
        (``scale="CM"``) Puma отпадает, потому что замер стопы она не публикует;
        по ``scale="EU"`` или ``"US M"`` она участвует.

        Args:
            limit: сколько моделей брать у одного бренда.
            total_limit: общий потолок выдачи после сортировки по цене.
            only: ограничить список брендов — имена, ключи таблиц или их
                алиасы («nb», «jordan», «adidas originals»).
            on_brand: вызывается после каждого бренда — (имя, его находки);
                при обрыве проверкой — и для прерванного бренда с тем, что
                у него успели найти.

        Бренды, которых нет в каталоге сайта, пропускаются с сообщением
        в прогресс, а не роняют весь обход. Проверка сайта обрывает обход:
        ChallengeRequired уходит наружу, а в ``exc.partial`` — находки всех
        брендов до неё, отсортированные и обрезанные так же, как выдача.
        """
        from .catalog import Catalog  # локальный импорт: избегаем цикла

        catalog = catalog or Catalog(self.client)
        # Шкалу из строки размера учитываем уже при выборе брендов: «US M 9»
        # при scale=CM — поиск по US M, и Puma в нём участвует.
        parsed_scale = None
        if isinstance(size, str):
            parsed_scale, size = parse_size_query(size)
        scale = resolve_query_scale(parsed_scale, scale, default=CM)

        charts = official_charts(scale, gender)
        if only:
            # Имена сводятся к таблицам тем же резолвером, что и везде:
            # «nb» → New Balance, «jordan» → сетка Nike.
            wanted: set[str] = set()
            for name in only:
                chart = resolve_brand(name)
                if chart is None:
                    self.on_progress(f"нет официальной таблицы для «{name}»")
                else:
                    wanted.add(chart.key)
            charts = [chart for chart in charts if chart.key in wanted]
        if not charts:
            self.on_progress(
                f"нет брендов с официальной таблицей для шкалы {scale}"
            )
            return []

        self.on_progress(
            "бренды с официальной таблицей: "
            + ", ".join(chart.name for chart in charts)
        )

        matches: list[Match] = []

        def collect(name: str, found: list[Match]) -> None:
            for match in found:
                match.product.brand = match.product.brand or name
            matches.extend(found)
            if on_brand:
                on_brand(name, found)

        def result() -> list[Match]:
            ordered = _by_price(matches)
            return ordered[:total_limit] if total_limit else ordered

        for index, chart in enumerate(charts, 1):
            self.on_progress(f"[{index}/{len(charts)}] {chart.name}")
            try:
                found = self.find_by_brand(
                    brand=chart.name,
                    size=size,
                    scale=scale,
                    limit=limit,
                    check=check,
                    tolerance=tolerance,
                    max_price=max_price,
                    min_price=min_price,
                    include_kids=include_kids,
                    catalog=catalog,
                    workers=workers,
                    gender=gender,
                )
            except ChallengeRequired as exc:
                collect(chart.name, list(getattr(exc, "partial", None) or []))
                exc.partial = result()
                raise
            except ValueError as exc:
                # Бренда нет в каталоге сайта — остальные всё равно обходим.
                self.on_progress(f"{chart.name}: {exc}")
                found = []

            collect(chart.name, found)

        return result()

    def scan_products(
        self,
        items: list[SearchItem],
        size_value: float,
        scale: str,
        brand_name: str = "",
        tolerance: float = 0.0,
        max_price: Optional[float] = None,
        min_price: Optional[float] = None,
        limit: Optional[int] = None,
        workers: int = 1,
        should_stop: Optional[Callable[[], bool]] = None,
        on_match: Optional[Callable[[Match], None]] = None,
        gender: str = "men",
    ) -> list[Match]:
        """Проверяет карточки и отбирает подходящие по размеру.

        workers > 1 грузит карточки параллельно. Частоту это не повышает:
        общий ограничитель клиента держит заданный темп, а потоки лишь
        перекрывают сетевые задержки.

        Проверка сайта (ChallengeRequired) обрывает обход; уже принятые
        находки уходят вместе с ней в ``exc.partial`` (в порядке находок).
        """
        total = len(items)
        matches: list[Match] = []
        lock = threading.Lock()
        done = {"n": 0}

        # Даём клиенту знать про отмену: тогда «Стоп» прерывает даже долгую
        # паузу после 429, не дожидаясь её конца.
        client = getattr(self, "client", None)
        previous_stop = getattr(client, "should_stop", None)
        if client is not None and should_stop is not None:
            client.should_stop = should_stop

        def handle(index: int, item: SearchItem) -> Optional[Match]:
            if should_stop and should_stop():
                return None
            try:
                product = self.load_product(item)
                product.brand = product.brand or brand_name
                match = self.match_by_scale(
                    product, size_value, scale, tolerance=tolerance, only_in_stock=True,
                    brand=brand_name or product.brand, gender=gender,
                )
            except (ChallengeRequired, Cancelled):
                raise
            except Exception as exc:  # noqa: BLE001
                # Любая проблема с ОДНОЙ карточкой (битый разбор, кодировка URL,
                # неожиданный HTML) не должна ронять весь поиск — пропускаем её.
                with lock:
                    done["n"] += 1
                    self.on_progress(
                        f"[{done['n']}/{total}] пропуск {item.spu_id}: {exc}"
                    )
                return None

            with lock:
                done["n"] += 1
                position = done["n"]
            if match is None:
                self.on_progress(f"[{position}/{total}] {product.title[:50]} — нет размера")
                return None

            price = match.offer.price
            if price is not None:
                # О каждой проверенной карточке сообщаем ровно один раз, иначе
                # счётчик прогресса недосчитается отфильтрованных по цене.
                if max_price is not None and price > max_price:
                    self.on_progress(
                        f"[{position}/{total}] {product.title[:50]} — "
                        f"дороже лимита ({match.offer.price_text or price})"
                    )
                    return None
                if min_price is not None and price < min_price:
                    self.on_progress(
                        f"[{position}/{total}] {product.title[:50]} — дешевле лимита"
                    )
                    return None

            self.on_progress(
                f"[{position}/{total}] {product.title[:50]} — "
                f"{match.offer.price_text or '—'}"
            )
            return match

        try:
            if workers <= 1:
                for index, item in enumerate(items, 1):
                    if should_stop and should_stop():
                        break
                    if limit is not None and len(matches) >= limit:
                        break
                    match = handle(index, item)
                    if match is not None:
                        matches.append(match)
                        if on_match:
                            on_match(match)
                return matches

            # Обрабатываем порциями, а не сабмитим все карточки разом: так
            # «Стоп» и достижение лимита срабатывают сразу, а не ждут очереди
            # из тысяч заданий, и большой каталог не висит целиком в памяти.
            chunk = max(workers * 2, workers)
            stop = False
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for start in range(0, total, chunk):
                    if stop or (should_stop and should_stop()):
                        break
                    if limit is not None and len(matches) >= limit:
                        break
                    batch = list(enumerate(items[start:start + chunk], start + 1))
                    futures = [pool.submit(handle, i, it) for i, it in batch]
                    for future in as_completed(futures):
                        if future.cancelled():
                            continue
                        try:
                            match = future.result()
                        except Cancelled:
                            match, stop = None, True
                        except ChallengeRequired:
                            # Иначе выход из пула дождался бы остальных карточек
                            # порции, и каждая ещё раз постучалась бы в сайт,
                            # который уже показывает проверку.
                            for pending in futures:
                                pending.cancel()
                            raise
                        if match is not None:
                            with lock:
                                # Лимит набран раньше, а потоки порции успели
                                # найти ещё: лишнее не попадает ни в выдачу,
                                # ни в on_match.
                                accepted = limit is None or len(matches) < limit
                                if accepted:
                                    matches.append(match)
                                if limit is not None and len(matches) >= limit:
                                    stop = True
                            if accepted and on_match:
                                on_match(match)
                        if not stop and should_stop and should_stop():
                            stop = True
                        if stop:
                            # Ещё не начатые карточки порции грузить незачем.
                            for pending in futures:
                                pending.cancel()
            return matches
        except ChallengeRequired as exc:
            # Обход оборвала проверка сайта — найденное до неё отдаём вместе
            # с исключением: CLI покажет его, а не выбросит.
            with lock:
                exc.partial = list(matches)
            raise
        finally:
            if client is not None:
                client.should_stop = previous_stop

    def find_in_products(
        self,
        urls: Iterable[str | int],
        size: str | float,
        scale: Optional[str] = None,
        tolerance: float = 0.0,
        only_in_stock: bool = True,
    ) -> list[Match]:
        """То же самое, но по конкретным ссылкам или spuId, без поиска."""
        if isinstance(size, str):
            parsed_scale, size_value = parse_size_query(size)
            scale = scale or parsed_scale
        else:
            size_value = float(size)
        if scale:
            scale = scale.upper()

        matches: list[Match] = []
        for target in urls:
            try:
                product = self.load_product(target)
            except (ChallengeRequired, Cancelled):
                # Как и в find(): капча и отмена прерывают весь обход.
                raise
            except PoizonError as exc:
                self.on_progress(f"пропуск {target}: {exc}")
                continue
            match = self.match_product(
                product, size_value, scale=scale, tolerance=tolerance,
                only_in_stock=only_in_stock,
            )
            if match:
                matches.append(match)
            else:
                self.on_progress(f"{product.title[:60]} — размера нет")
        return matches
