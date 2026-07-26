"""Локальный веб-интерфейс парсера.

Сервер на stdlib (`http.server`): отдаёт собранный Vite-фронтенд из
`frontend/dist` (или старую страницу `web/index.html`, пока сборки нет) и JSON
API. Поиск — долгая операция (карточка товара грузится отдельно), поэтому он
оформлен как фоновая задача: POST /api/search запускает поток и возвращает id,
фронтенд опрашивает GET /api/search/<id> и дорисовывает найденное на лету.

Итоги (`data/picks.json`) — отобранные пользователем позиции; хранятся на диске
и переживают перезапуск.
"""

from __future__ import annotations

import json
import mimetypes
import os
import tempfile
import threading
import time
import uuid
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .catalog import Catalog
from .client import Cancelled, ChallengeRequired, PoizonClient, PoizonError
from .finder import SizeFinder
from .report import RESULT_DIR, write_report
from .sizechart import EU, normalize_scale, resolve_official_chart
from .sizes import parse_size_query

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
FRONTEND_DIST = ROOT / "frontend" / "dist"
#: Личные избранные каждого пользователя: data/picks/<uid>.json.
PICKS_DIR = ROOT / "data" / "picks"
CACHE_DIR = Path(tempfile.gettempdir()) / "poizon-parser-cache"
#: Имя cookie с анонимным идентификатором пользователя.
UID_COOKIE = "poizon_uid"

#: Сколько строк лога держим в задаче (фронтенд показывает хвост).
LOG_LIMIT = 300
#: Пауза между запросами к сайту в фоновых задачах.
JOB_DELAY = 0.6
#: Параллельных загрузок карточек. Общий ограничитель не даёт превысить темп,
#: потоки лишь перекрывают сетевую задержку.
DEFAULT_WORKERS = 3

#: Режимы темпа: (пауза между запросами, число воркеров).
PACES = {
    "polite": (1.2, 1),
    "normal": (JOB_DELAY, DEFAULT_WORKERS),
    "fast": (0.35, 5),
}
#: Сколько живёт кэш брендов в памяти сервера.
BRANDS_TTL = 6 * 3600
#: Сколько завершённых задач держим в памяти (чтобы не текла память).
JOB_RETENTION = 20
#: Разумные границы длины стопы, см — вне них ввод считается ошибкой.
FOOT_MIN_CM = 15.0
FOOT_MAX_CM = 40.0
#: Верхняя граница JSON-тела запроса. В том числе покрывает объёмный отчёт.
MAX_JSON_BODY = 2 * 1024 * 1024


class RequestBodyTooLarge(ValueError):
    """JSON-тело запроса превышает разрешённый размер."""


def validate_search(body: dict) -> Optional[str]:
    """Проверяет параметры поиска. Возвращает текст ошибки или None."""
    if not str(body.get("brand") or "").strip():
        return "не указан бренд"
    raw_size = str(body.get("size") or "").strip().replace(",", ".")
    if not raw_size:
        return "не указан размер"
    scale = str(body.get("scale") or "CM").upper()
    try:
        value = float(raw_size)
    except ValueError:
        return f"размер «{body.get('size')}» не число"
    if value <= 0:
        return "размер должен быть больше нуля"
    # Для длины стопы — понятные границы, чтобы отсечь мм и опечатки.
    if scale in ("CM", "СМ"):
        if value < FOOT_MIN_CM or value > FOOT_MAX_CM:
            return (
                f"длина стопы {value:g} см вне разумных границ "
                f"({FOOT_MIN_CM:g}–{FOOT_MAX_CM:g} см). Введите замер в сантиметрах"
            )
    for key in ("maxPrice", "minPrice"):
        raw = body.get(key)
        if raw not in (None, ""):
            try:
                if float(raw) < 0:
                    return f"{key} не может быть отрицательной"
            except (ValueError, TypeError):
                return f"{key} должна быть числом"
    return None



# --------------------------------------------------------------------- picks


class PickStore:
    """Личные избранные каждого пользователя: файл `<uid>.json` на пользователя.

    Многопользовательский режим: разные люди (разные браузеры) идентифицируются
    анонимной cookie, и у каждого — своя выборка. Файлы лежат в `data/picks/`.
    """

    def __init__(self, base_dir: Path = PICKS_DIR) -> None:
        self.base_dir = base_dir
        self._lock = threading.Lock()

    @staticmethod
    def _safe_uid(uid: str) -> str:
        """Только hex-идентификаторы — защита от выхода за папку."""
        cleaned = "".join(c for c in str(uid or "") if c in "0123456789abcdef")
        return cleaned[:32] or "anon"

    def _path(self, uid: str) -> Path:
        return self.base_dir / f"{self._safe_uid(uid)}.json"

    def _load(self, uid: str) -> list[dict]:
        path = self._path(uid)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, uid: str, items: list[dict]) -> None:
        path = self._path(uid)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(path)

    @staticmethod
    def _dedupe_key(entry: dict) -> str:
        match = entry.get("match") or {}
        query = entry.get("query") or {}
        return (
            f"{match.get('spu_id')}|{match.get('sku_id')}|"
            f"{query.get('scale')}|{query.get('size')}"
        )

    def list(self, uid: str) -> list[dict]:
        with self._lock:
            return self._load(uid)

    def add(self, uid: str, match: dict, query: dict) -> tuple[dict, bool]:
        """Добавляет позицию пользователю. Возвращает (запись, новая ли)."""
        entry = {
            "id": uuid.uuid4().hex[:12],
            "saved_at": time.strftime("%Y-%m-%d %H:%M"),
            "query": query,
            "match": match,
        }
        with self._lock:
            items = self._load(uid)
            key = self._dedupe_key(entry)
            for existing in items:
                if self._dedupe_key(existing) == key:
                    return existing, False
            items.insert(0, entry)
            self._save(uid, items)
            return entry, True

    def remove(self, uid: str, pick_id: str) -> bool:
        with self._lock:
            items = self._load(uid)
            remaining = [item for item in items if item.get("id") != pick_id]
            if len(remaining) == len(items):
                return False
            self._save(uid, remaining)
            return True

    def clear(self, uid: str) -> int:
        with self._lock:
            items = self._load(uid)
            self._save(uid, [])
            return len(items)


# ---------------------------------------------------------------------- jobs


class JobManager:
    """Фоновые поисковые задачи."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, params: dict) -> dict:
        job = {
            "id": uuid.uuid4().hex[:12],
            "status": "running",
            "phase": "brand",
            "params": params,
            "brand": None,
            "collected": 0,
            "checked": 0,
            "total": 0,
            "found": 0,
            "matches": [],
            "log": [],
            "error": "",
            "cancel": False,
            "paused": False,      # ждём прохождения капчи пользователем
            "captcha": None,      # {url, reason, since}
            "cooldown_until": 0,  # автоматическое ожидание после 429
            "prefiltered": 0,     # отсеяно по цене без загрузки карточки
            "stats": {},
            # Мониторинг: что происходит прямо сейчас и когда была активность.
            "activity": "запуск…",   # человекочитаемое «сейчас происходит»
            "active_requests": 0,    # запросов «в полёте»
            "last_activity_at": time.time(),
            "pause_requested": None, # ручная пауза, запрошенная пользователем
            "stop_reason": "",       # почему задача завершилась
            "started_at": time.time(),
            "finished_at": None,
        }
        # Барьер прохождения капчи. Монотонный счётчик поколений вместо Event:
        # при нескольких воркерах clear()/set() на общем Event даёт гонку, а
        # растущий счётчик надёжно будит всех ожидающих одним resume.
        job["_cond"] = threading.Condition()
        job["_resume_gen"] = 0
        # Счётчики обновляются из воркеров — нужен свой замок.
        job["_counter"] = threading.Lock()
        with self._lock:
            self._jobs[job["id"]] = job
            self._evict_old()
        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        thread.start()
        return job

    def _evict_old(self) -> None:
        """Удаляет самые старые завершённые задачи, ограничивая память.

        Активные (running/captcha) не трогаем — только законченные, и только
        когда их накопилось сверх лимита. Вызывать под self._lock.
        """
        finished = [
            (jid, j) for jid, j in self._jobs.items()
            if j["status"] not in ("running", "captcha")
        ]
        if len(finished) <= JOB_RETENTION:
            return
        finished.sort(key=lambda pair: pair[1].get("finished_at") or 0)
        for jid, _ in finished[: len(finished) - JOB_RETENTION]:
            self._jobs.pop(jid, None)

    def count(self) -> dict:
        """Сводка по задачам — для health-эндпоинта."""
        with self._lock:
            active = sum(
                1 for j in self._jobs.values()
                if j["status"] in ("running", "captcha")
            )
            return {"total": len(self._jobs), "active": active}

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> Optional[dict]:
        job = self.get(job_id)
        if job is None:
            return None
        snap = {
            key: value
            for key, value in job.items()
            if not key.startswith("_") and key not in ("cancel", "params")
        }
        # Секунды с последней активности считаем на сервере — не зависит от
        # рассинхрона часов браузера; по этому числу интерфейс ловит «застой».
        if job["status"] in ("running", "captcha"):
            snap["idle_seconds"] = round(time.time() - job.get("last_activity_at", time.time()), 1)
        else:
            snap["idle_seconds"] = 0
        snap["pause_requested"] = bool(job.get("pause_requested"))
        return snap

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        job["cancel"] = True
        with job["_cond"]:
            job["_cond"].notify_all()  # разбудить всех, кто ждёт капчу
        return True

    def resume(self, job_id: str) -> bool:
        """Пользователь прошёл капчу — продолжаем."""
        job = self.get(job_id)
        if job is None or not job.get("paused"):
            return False
        with job["_cond"]:
            job["paused"] = False
            job["captcha"] = None
            job["pause_requested"] = None  # снимаем и ручную паузу
            job["status"] = "running"
            job["_resume_gen"] += 1
            job["_cond"].notify_all()
        self._log(job, "продолжаю после проверки")
        return True

    def request_pause(self, job_id: str) -> bool:
        """Ручная пауза: пользователь хочет сам пройти проверку на сайте.

        Воркеры встанут перед следующим запросом; уже идущие запросы
        завершатся. Снять паузу — resume().
        """
        job = self.get(job_id)
        if job is None or job["status"] not in ("running", "captcha"):
            return False
        brand = job.get("brand") or {}
        url = "https://www.thepoizon.ru" + (brand.get("url") or "/")
        job["pause_requested"] = {"url": url, "reason": "manual"}
        self._log(job, "запрошена ручная пауза — встаю после текущих запросов")
        return True

    def _note_cooldown(self, job: dict, wait: float, reason: str) -> None:
        """Клиент сам пережидает ограничение — показываем это в интерфейсе."""
        job["cooldown_until"] = time.time() + wait
        self._log(job, f"сайт ограничил частоту ({reason}) — жду {wait:.0f} c")

    def _note_activity(self, job: dict, kind: str, detail: dict) -> None:
        """Переводит сырое событие клиента в человекочитаемый статус «сейчас».

        Именно это делает видимым, чем занят парсер в каждый момент, и почему
        он мог «замереть» — сетевой запрос, ожидание лимита, проверка.
        """
        job["last_activity_at"] = time.time()
        job["active_requests"] = detail.get("active", job.get("active_requests", 0))
        path = str(detail.get("path") or "")
        short = path.rsplit("/", 1)[-1][:26] if path else ""
        if kind == "request":
            job["activity"] = f"загружаю карточку… ({short})" if short else "запрос к сайту…"
        elif kind == "response":
            job["activity"] = f"получено за {detail.get('ms', 0)} мс"
        elif kind == "cache":
            job["activity"] = "беру из кэша"
        elif kind == "waiting":
            job["activity"] = f"жду очередь запроса — пауза {detail.get('seconds')} c"
        elif kind == "cooldown":
            job["activity"] = (
                f"⏳ сайт ограничил частоту ({detail.get('reason')}), "
                f"жду {detail.get('seconds')} c (попытка {detail.get('try_no')})"
            )
        elif kind == "retry":
            job["activity"] = (
                f"↻ сеть не ответила ({detail.get('error', '')}), "
                f"повтор через {detail.get('seconds')} c"
            )
            self._log(job, f"сетевая заминка: {detail.get('error', '')} — повтор")
        elif kind == "net_error":
            job["activity"] = f"сеть: {detail.get('error', '')}"
        elif kind == "http_error":
            job["activity"] = f"ответ сайта HTTP {detail.get('code')}"
        elif kind == "challenge":
            job["activity"] = f"🛡 требуется проверка ({detail.get('reason')})"
        elif kind == "paused":
            job["activity"] = "на паузе — пройдите проверку и продолжите"

    def _wait_for_captcha(self, job: dict, info: dict) -> bool:
        """Колбэк клиента: ставит задачу на паузу и ждёт пользователя.

        Безопасен для нескольких воркеров: каждый ждёт следующего поколения
        resume. Возвращает True (повторить запрос) или False (прекратить).
        """
        with job["_cond"]:
            first = not job["paused"]
            job["paused"] = True
            job["status"] = "captcha"
            job["captcha"] = {
                "url": info.get("url"),
                "reason": info.get("reason"),
                "since": time.time(),
            }
            if first:
                self._log(
                    job,
                    f"⚠ проверка ({info.get('reason')}) — пройдите её в браузере "
                    "и нажмите «Продолжить»",
                )
            # Пауза снимается только в resume(); ждём смены поколения.
            seen = job["_resume_gen"]
            while job["_resume_gen"] == seen and not job["cancel"]:
                job["_cond"].wait(timeout=1.0)
        return not job["cancel"]

    # ------------------------------------------------------------- runner

    @staticmethod
    def _log(job: dict, message: str) -> None:
        job["log"].append(message)
        if len(job["log"]) > LOG_LIMIT:
            del job["log"][: len(job["log"]) - LOG_LIMIT]

    def _run(self, job: dict) -> None:
        params = job["params"]
        try:
            self._search(job, params)
            if job["cancel"]:
                job["status"] = "cancelled"
                job["stop_reason"] = "остановлено пользователем"
            else:
                job["status"] = "done"
                job["stop_reason"] = (
                    f"готово: проверено {job['checked']} из {job['total']}, "
                    f"подошло {job['found']}"
                )
        except Cancelled:
            job["status"] = "cancelled"
            job["stop_reason"] = "остановлено пользователем"
        except ChallengeRequired as exc:
            # Сюда попадаем, только если проверку не удалось пройти даже после
            # пауз и ручных попыток — воркеры уже остановлены, продолжать нечего.
            if job["cancel"]:
                job["status"] = "cancelled"
                job["stop_reason"] = "остановлено пользователем"
            else:
                job["status"] = "error"
                job["stop_reason"] = f"сайт требует проверку ({exc.reason})"
                job["error"] = (
                    f"Сайт настойчиво требует проверку ({exc.reason}). Откройте "
                    f"{exc.url}, пройдите её в браузере и запустите поиск снова — "
                    "проверенные карточки уже в кэше, второй прогон будет быстрым."
                )
        except (PoizonError, ValueError) as exc:
            job["status"] = "error"
            job["stop_reason"] = "ошибка"
            job["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 — фон, наружу не выбросить
            job["status"] = "error"
            job["stop_reason"] = "внутренняя ошибка"
            job["error"] = f"внутренняя ошибка: {exc!r}"
        finally:
            job["finished_at"] = time.time()
            job["activity"] = job.get("stop_reason") or "завершено"

    def _search(self, job: dict, params: dict) -> None:
        delay, workers = PACES.get(str(params.get("pace")), PACES["normal"])
        client = PoizonClient(
            delay=delay,
            cache_dir=str(CACHE_DIR),
            cache_ttl=900.0,
            on_challenge=lambda info: self._wait_for_captcha(job, info),
            on_cooldown=lambda wait, reason: self._note_cooldown(job, wait, reason),
            on_activity=lambda kind, detail: self._note_activity(job, kind, detail),
        )
        # Демо/тест обработки капчи без ожидания реального 429.
        demo = os.environ.get("POIZON_DEMO_CAPTCHA")
        if demo and demo.isdigit():
            client.force_challenge_after = int(demo)
        # Отмена прерывает и сбор каталога, и долгие паузы после 429.
        client.should_stop = lambda: bool(job["cancel"])
        # Ручная пауза: пользователь может остановиться, пройти проверку и продолжить.
        client.should_pause = lambda: job.get("pause_requested")
        catalog = Catalog(client)
        finder = SizeFinder(client, on_progress=lambda m: self._log(job, m))

        brand = catalog.find_brand(str(params.get("brand") or ""))
        if brand is None:
            hints = ", ".join(
                b.name for b in catalog.suggest_brands(str(params.get("brand") or ""))
            )
            raise ValueError(
                f"бренд «{params.get('brand')}» не найден"
                + (f"; похожие: {hints}" if hints else "")
            )
        job["brand"] = {"name": brand.name, "url": brand.url, "id": brand.brand_id}

        parsed_scale, size_value = parse_size_query(str(params.get("size") or ""))
        scale = normalize_scale(parsed_scale or params.get("scale")) or EU

        max_price = params.get("maxPrice")
        min_price = params.get("minPrice")
        depth = params.get("depth")  # None/0 → весь каталог
        include_kids = bool(params.get("kids"))

        # Этап 1: собираем каталог бренда (только обувь).
        job["phase"] = "collect"
        items = []
        for item in catalog.brand_items(
            brand, max_items=depth or None, include_kids=include_kids
        ):
            if job["cancel"]:
                raise Cancelled()
            items.append(item)
            job["collected"] = len(items)
        job["total"] = len(items)
        self._log(job, f"каталог собран: {len(items)} моделей обуви")

        # Предфильтр по цене прямо из листинга — экономит загрузки карточек.
        if max_price:
            before = len(items)
            items = [
                item for item in items
                if item.min_price is None or item.min_price <= float(max_price)
            ]
            job["prefiltered"] = before - len(items)
            job["total"] = len(items)
            if job["prefiltered"]:
                self._log(
                    job,
                    f"отсеяно по цене без загрузки карточек: {job['prefiltered']}",
                )

        # Этап 2: карточки — размер, наличие, цена.
        job["phase"] = "check"
        images = {item.spu_id: item.logo_url for item in items}

        def progress(message: str) -> None:
            # Прогресс приходит из воркеров — обновляем счётчик под замком.
            # cooldown_until не трогаем: он истекает сам по времени, а обнуление
            # из воркера, читающего кэш, давало бы мерцание индикатора паузы.
            with job["_counter"]:
                job["checked"] = min(job["checked"] + 1, job["total"])
            self._log(job, message)

        finder.on_progress = progress

        def collect(match) -> None:
            row = match.to_dict()
            row["image"] = row.get("image") or images.get(match.product.spu_id, "")
            with job["_counter"]:
                job["matches"].append(row)
                job["found"] = len(job["matches"])

        finder.scan_products(
            items,
            size_value,
            scale,
            brand_name=brand.name,
            max_price=float(max_price) if max_price else None,
            min_price=float(min_price) if min_price else None,
            workers=workers,
            should_stop=lambda: bool(job["cancel"]),
            on_match=collect,
            gender="women" if str(params.get("gender")) == "women" else "men",
        )
        if job["cancel"]:
            raise Cancelled()
        job["stats"] = dict(client.stats)


# -------------------------------------------------------------------- server


class App(ThreadingHTTPServer):
    """HTTP-сервер с общим состоянием."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int]) -> None:
        super().__init__(address, Handler)
        self.jobs = JobManager()
        self.picks = PickStore()
        self._brands_cache: Optional[list[dict]] = None
        self._brands_at = 0.0
        self._brands_lock = threading.Lock()

    def brands(self) -> list[dict]:
        with self._brands_lock:
            if (
                self._brands_cache is not None
                and time.time() - self._brands_at < BRANDS_TTL
            ):
                return self._brands_cache
            client = PoizonClient(
                delay=0.3, cache_dir=str(CACHE_DIR), cache_ttl=BRANDS_TTL
            )
            catalog = Catalog(client)
            self._brands_cache = []
            for brand in catalog.brands():
                chart = resolve_official_chart(brand.name)
                self._brands_cache.append(
                    {
                        "id": brand.brand_id,
                        "name": brand.name,
                        "slug": brand.slug,
                        "url": brand.url,
                        "has_official_size_chart": chart is not None,
                        "size_chart_brand": chart.name if chart else None,
                        "size_chart_source": chart.source if chart else None,
                    }
                )
            self._brands_at = time.time()
            return self._brands_cache


class Handler(BaseHTTPRequestHandler):
    server_version = "PoizonParser/1.0"
    server: App  # для подсказок типов

    def log_message(self, *_args: Any) -> None:  # тишина в консоли
        pass

    # ------------------------------------------------------------ helpers

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Vite проксирует API, но не открывает Python index.html. Выдаём uid
        # и здесь, чтобы личные итоги были изолированы также в dev-режиме.
        self._send_uid_cookie_if_missing()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length > MAX_JSON_BODY:
            raise RequestBodyTooLarge()
        if length <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -------- идентификация пользователя (многопользовательский режим) --------

    def _cookies(self) -> dict:
        jar = SimpleCookie()
        raw = self.headers.get("Cookie")
        if raw:
            try:
                jar.load(raw)
            except CookieError:
                return {}
        return {k: v.value for k, v in jar.items()}

    def _uid(self) -> str:
        """Идентификатор пользователя из cookie (или 'anon', если её нет)."""
        return self._cookies().get(UID_COOKIE, "anon")

    def _send_uid_cookie_if_missing(self) -> None:
        """Добавляет личный uid cookie, если браузер ещё не получил его."""
        if UID_COOKIE in self._cookies():
            return
        new_uid = uuid.uuid4().hex
        self.send_header(
            "Set-Cookie",
            (
                f"{UID_COOKIE}={new_uid}; Path=/; HttpOnly; "
                "Max-Age=31536000; SameSite=Lax"
            ),
        )

    @staticmethod
    def _content_type(path: Path) -> str:
        """Возвращает стабильный MIME, не зависящий от реестра Windows."""
        suffix = path.suffix.lower()
        if suffix in (".js", ".mjs"):
            return "text/javascript; charset=utf-8"
        if suffix == ".css":
            return "text/css; charset=utf-8"
        if suffix == ".html":
            return "text/html; charset=utf-8"
        content_type = mimetypes.guess_type(path.name)[0]
        return content_type or "application/octet-stream"

    def _send_file(
        self,
        path: Path,
        *,
        cache_control: str,
        set_uid_cookie: bool = False,
    ) -> None:
        if not path.is_file():
            self._json({"error": "статический файл не найден"}, 404)
            return
        try:
            body = path.read_bytes()
        except OSError:
            self._json({"error": "не удалось прочитать статический файл"}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", self._content_type(path))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        # При первом заходе выдаём анонимный id — так у каждого свои избранные.
        if set_uid_cookie:
            self._send_uid_cookie_if_missing()
        self.end_headers()
        self.wfile.write(body)

    def _serve_index(self) -> None:
        """Отдаёт Vite index или старый интерфейс, если сборки ещё нет."""
        vite_index = FRONTEND_DIST / "index.html"
        index = vite_index if vite_index.is_file() else WEB_DIR / "index.html"
        self._send_file(index, cache_control="no-store", set_uid_cookie=True)

    def _serve_asset(self, request_path: str) -> None:
        """Отдаёт только файлы внутри Vite assets, не допуская traversal."""
        asset_root = (FRONTEND_DIST / "assets").resolve()
        relative = unquote(request_path[len("/assets/"):])
        try:
            target = (asset_root / relative).resolve()
            target.relative_to(asset_root)
        except (OSError, RuntimeError, ValueError):
            self._json({"error": "недопустимый путь"}, 403)
            return
        self._send_file(
            target,
            cache_control="public, max-age=31536000, immutable",
        )

    # ------------------------------------------------------------- routes

    def do_GET(self) -> None:  # noqa: N802 — API stdlib
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                self._serve_index()
            elif path.startswith("/assets/"):
                self._serve_asset(path)
            elif path == "/api/health":
                self._json({
                    "status": "ok",
                    "jobs": self.server.jobs.count(),
                    "brands_loaded": self.server._brands_cache is not None,
                    "picks": len(self.server.picks.list(self._uid())),
                })
            elif path == "/api/convert":
                self._convert(parse_qs(urlparse(self.path).query))
            elif path == "/api/brands":
                self._json({"brands": self.server.brands()})
            elif path.startswith("/api/search/"):
                snapshot = self.server.jobs.snapshot(path.rsplit("/", 1)[-1])
                if snapshot is None:
                    self._json({"error": "задача не найдена"}, 404)
                else:
                    self._json(snapshot)
            elif path == "/api/picks":
                self._json({"items": self.server.picks.list(self._uid())})
            elif path.startswith("/result/"):
                self._serve_report(path)
            else:
                self._json({"error": "не найдено"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except PoizonError as exc:
            self._json({"error": str(exc)}, 502)

    def _serve_report(self, path: str) -> None:
        """Отдаёт сгенерированный отчёт из result/ (с защитой от выхода из папки)."""
        rel = unquote(path[len("/result/"):])
        target = (RESULT_DIR / rel).resolve()
        try:
            target.relative_to(RESULT_DIR.resolve())
        except ValueError:
            self._json({"error": "недопустимый путь"}, 403)
            return
        if not target.is_file():
            self._json({"error": "отчёт не найден"}, 404)
            return
        body = target.read_bytes()
        ctype = "text/html; charset=utf-8" if target.suffix == ".html" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _convert(self, query: dict) -> None:
        """Быстрый калькулятор: стопа → размеры бренда (без сети)."""
        from .sizechart import compare_brands, sizes_for_foot

        brand = (query.get("brand") or [""])[0]
        gender = (query.get("gender") or ["men"])[0]
        gender = "women" if gender == "women" else "men"
        try:
            foot = float((query.get("foot") or ["0"])[0].replace(",", "."))
        except (ValueError, AttributeError):
            self._json({"error": "нужна длина стопы в см"}, 400)
            return
        if foot < FOOT_MIN_CM or foot > FOOT_MAX_CM:
            self._json({"sizes": None, "compare": [],
                        "note": "вне разумных границ длины стопы"})
            return
        self._json({
            "sizes": sizes_for_foot(brand, foot, gender) if brand else None,
            "compare": compare_brands(foot, gender),
        })

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/search":
                body = self._body()
                problem = validate_search(body)
                if problem:
                    self._json({"error": problem}, 400)
                    return
                job = self.server.jobs.create(
                    {
                        "brand": body.get("brand"),
                        "size": body.get("size"),
                        "scale": body.get("scale") or "EU",
                        "depth": body.get("depth"),
                        "maxPrice": body.get("maxPrice"),
                        "minPrice": body.get("minPrice"),
                        "pace": body.get("pace") or "normal",
                        "gender": body.get("gender") or "men",
                        "kids": bool(body.get("kids")),
                    }
                )
                self._json({"id": job["id"]})
            elif path.startswith("/api/search/") and path.endswith("/cancel"):
                job_id = path.split("/")[3]
                ok = self.server.jobs.cancel(job_id)
                self._json({"ok": ok}, 200 if ok else 404)
            elif path.startswith("/api/search/") and path.endswith("/continue"):
                job_id = path.split("/")[3]
                ok = self.server.jobs.resume(job_id)
                self._json({"ok": ok}, 200 if ok else 409)
            elif path.startswith("/api/search/") and path.endswith("/pause"):
                job_id = path.split("/")[3]
                ok = self.server.jobs.request_pause(job_id)
                self._json({"ok": ok}, 200 if ok else 409)
            elif path == "/api/picks":
                body = self._body()
                match = body.get("match")
                if not isinstance(match, dict) or not match.get("spu_id"):
                    self._json({"error": "нет данных позиции"}, 400)
                    return
                entry, created = self.server.picks.add(
                    self._uid(), match, body.get("query") or {}
                )
                self._json({"item": entry, "created": created})
            elif path == "/api/report":
                self._make_report(self._body())
            else:
                self._json({"error": "не найдено"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except RequestBodyTooLarge:
            # Тело не читаем: соединение нельзя переиспользовать, иначе его
            # байты стали бы началом следующего HTTP-запроса.
            self.close_connection = True
            self._json(
                {
                    "error": (
                        "JSON-тело слишком большое "
                        f"(максимум {MAX_JSON_BODY} байт)"
                    )
                },
                413,
            )

    def _make_report(self, body: dict) -> None:
        """Собирает HTML-отчёт по результатам задачи в папке result/."""
        job = None
        if body.get("jobId"):
            job = self.server.jobs.get(str(body["jobId"]))
        # Присланные результаты приоритетнее: это то, что пользователь видит на
        # экране (с учётом фильтра и сортировки). Задача — запасной источник.
        source = body.get("matches") or ((job or {}).get("matches"))
        if not source:
            self._json({"error": "нет результатов для отчёта"}, 400)
            return

        params = (job or {}).get("params") or {}
        brand = (job or {}).get("brand") or {}
        meta = {
            "brand": body.get("brand") or brand.get("name") or params.get("brand") or "",
            "size_input": body.get("size") or params.get("size") or "",
            "scale": body.get("scale") or params.get("scale") or "CM",
            "gender": body.get("gender") or params.get("gender") or "men",
        }
        out_dir = write_report(source, meta, embed_images=bool(body.get("embed")))
        rel = out_dir.name
        self._json({
            "dir": str(out_dir),
            "file": str(out_dir / "index.html"),
            "view": f"/result/{rel}/index.html",
        })

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/picks":
                removed = self.server.picks.clear(self._uid())
                self._json({"removed": removed})
            elif path.startswith("/api/picks/"):
                ok = self.server.picks.remove(self._uid(), path.rsplit("/", 1)[-1])
                self._json({"ok": ok}, 200 if ok else 404)
            else:
                self._json({"error": "не найдено"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def run_server(
    host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True
) -> None:
    """Запускает сервер и (опционально) открывает браузер."""
    app = App((host, port))
    url = f"http://{host}:{port}/"
    print(f"Парсер POIZON: {url}  (Ctrl+C — остановить)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        app.server_close()
