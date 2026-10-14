"""HTTP-клиент thepoizon.ru.

Сайт отдаёт данные двумя путями, оба используются здесь:

1. JSON API `/api/v1/h5/...` — поиск товаров. Каждый запрос подписывается
   параметром `sign` = md5(конкатенация отсортированных пар ключ-значение + соль).
2. Страница товара `/product/<slug>-<spuId>` — HTML с server-side состоянием
   Next.js в теге `__NEXT_DATA__`. Именно там лежат цены по каждому размеру:
   в JSON API их нет.

Перед выдачей HTML сайт может ответить заглушкой со скриптом, который ставит
cookie `C3VK`. Значение одноразовое: его нужно прочитать и повторить запрос.
"""

from __future__ import annotations

import gzip
import hashlib
import http.cookiejar
import json
import random
import re
import sys
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote, urlsplit, urlunsplit

BASE_URL = "https://www.thepoizon.ru"

# Соль подписи запросов, зашита в клиентский код сайта.
_SIGN_SALT = "048a9c4943398714b356a696503d2d36"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_SEARCH_API = "/api/v1/h5/home-page/intl/landing/search/page"
_DETAIL_API = "/api/v1/h5/goods-detail/intl/commodity/v2/get-index-spu-detail"

_C3VK_RE = re.compile(r"C3VK=([0-9a-zA-Z]+)")
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


class PoizonError(RuntimeError):
    """Ошибка обращения к сайту."""


class ChallengeRequired(PoizonError):
    """Сайт показал проверку (капчу/анти-бот), которую нужно пройти вручную."""

    def __init__(self, url: str, reason: str = "captcha") -> None:
        super().__init__(f"требуется пройти проверку на {url} ({reason})")
        self.url = url
        self.reason = reason
        #: Что поиск успел найти до проверки (SizeFinder дописывает сюда
        #: находки, отсортированные как обычная выдача), — чтобы обрыв не
        #: уносил уже собранные результаты.
        self.partial: list = []


class Cancelled(Exception):
    """Запрос прерван отменой (нажали «Стоп»).

    Намеренно НЕ наследует PoizonError: обработчики, глотающие PoizonError
    («пропустить карточку»), не должны глотать отмену — она обязана всплыть.
    """


#: Признаки анти-бот проверки в теле ответа (проверяем в нижнем регистре).
_CHALLENGE_MARKERS = (
    "captcha", "geetest", "gt_captcha", "slider", "punish", "/_guard",
    "验证", "网络不给力", "unusual traffic", "are you human", "access denied",
    "verify you are", "forbidden",
)


def _value_string(val: Any) -> str:
    """Строковое представление значения — так же, как в JS-коде сайта."""
    if val is None or val == "":
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, dict):
        return json.dumps(val, separators=(",", ":"), ensure_ascii=False)
    if isinstance(val, (list, tuple)):
        parts = []
        for item in val:
            if isinstance(item, (dict, list, tuple)):
                parts.append(json.dumps(item, separators=(",", ":"), ensure_ascii=False))
            elif item is None:
                parts.append("null")
            else:
                parts.append(_value_string(item))
        return ",".join(parts)
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


def calc_sign(body: Optional[dict]) -> str:
    """Подпись тела запроса: md5(ключ+значение по алфавиту + соль)."""
    if not body:
        return hashlib.md5(_SIGN_SALT.encode()).hexdigest()
    token = "".join(
        key + _value_string(body[key])
        for key in sorted(body)
        if body[key] is not None
    )
    return hashlib.md5((token + _SIGN_SALT).encode("utf-8")).hexdigest()


class RateLimiter:
    """Ограничитель частоты запросов (token bucket), общий для всех потоков.

    Смысл: сколько бы воркеров ни качало карточки, суммарная нагрузка на сайт
    не превысит заданный темп. Параллельность тогда лишь перекрывает сетевые
    задержки, а не увеличивает частоту запросов — так быстрее и без блокировок.
    """

    def __init__(self, rate_per_sec: float, burst: int = 1) -> None:
        self.rate = max(rate_per_sec, 0.01)
        self.burst = max(burst, 1)
        self._tokens = float(self.burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()
        self._blocked_until = 0.0

    def set_rate(self, rate_per_sec: float) -> None:
        with self._lock:
            self.rate = max(rate_per_sec, 0.01)

    def pause_for(self, seconds: float) -> None:
        """Общая пауза для всех потоков — например, по Retry-After."""
        with self._lock:
            self._blocked_until = max(
                self._blocked_until, time.monotonic() + max(seconds, 0.0)
            )

    def blocked_seconds(self) -> float:
        """Сколько ещё длится общая пауза (0, если её нет)."""
        with self._lock:
            return max(0.0, self._blocked_until - time.monotonic())

    def acquire(
        self,
        should_stop: Optional[Callable[[], bool]] = None,
        wake: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Ждёт своей очереди. Возвращает False, если прервано (отмена/wake).

        Спим короткими интервалами и проверяем should_stop и wake, чтобы и
        отмена, и запрос ручной паузы срабатывали быстро даже во время длинной
        паузы после 429.
        """
        while True:
            if should_stop is not None and should_stop():
                return False
            if wake is not None and wake():
                return False
            with self._lock:
                now = time.monotonic()
                if now < self._blocked_until:
                    wait = self._blocked_until - now
                else:
                    elapsed = now - self._updated
                    self._updated = now
                    self._tokens = min(
                        self.burst, self._tokens + elapsed * self.rate
                    )
                    if self._tokens >= 1.0:
                        self._tokens -= 1.0
                        return True
                    wait = (1.0 - self._tokens) / self.rate
            # Не спим дольше 0.5 c за раз — иначе отмена «залипает».
            time.sleep(min(max(wait, 0.005), 0.5) + random.uniform(0, 0.05))


class PoizonClient:
    """Клиент к сайту: поиск и загрузка карточек товара.

    Параметры:
        delay: минимальная пауза между запросами (задаёт темп ограничителя).
        timeout: таймаут одного запроса.
        retries: число повторов при сетевой ошибке или 5xx.
        cache_dir / cache_ttl: дисковый кэш HTML.
        on_challenge: колбэк для ручного прохождения проверки.
        on_cooldown: колбэк уведомления об автоматическом ожидании после 429.
    """

    def __init__(
        self,
        delay: float = 0.7,
        timeout: float = 30.0,
        retries: int = 3,
        currency: str = "RUB",
        verbose: bool = False,
        cache_dir: Optional[str] = None,
        cache_ttl: float = 900.0,
        on_challenge: Optional[Callable[[dict], bool]] = None,
        on_cooldown: Optional[Callable[[float, str], None]] = None,
        on_activity: Optional[Callable[[str, dict], None]] = None,
        burst: int = 2,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.currency = currency
        self.verbose = verbose
        # Вызывается, когда сайт показал проверку, которую не пройти автоматически.
        # Должен ЗАБЛОКИРОВАТЬСЯ, пока пользователь не пройдёт капчу, и вернуть
        # True (повторить запрос) или False (прекратить). None → сразу исключение.
        self.on_challenge = on_challenge
        # Уведомление о том, что клиент сам ждёт после 429 (секунды, причина).
        self.on_cooldown = on_cooldown
        # Плавное замедление: растёт после проверок, спадает после успехов —
        # чтобы не провоцировать капчу частыми запросами.
        self._extra_delay = 0.0
        self._max_challenge_rounds = 6
        # Сколько раз пережидаем 429 сами, прежде чем звать человека.
        self.auto_cooldown_tries = 3
        # Потолок разовой паузы после 429 (в т.ч. по Retry-After), секунды.
        # Иначе сайт мог бы «попросить» ждать час и всё бы зависло.
        self.max_cooldown = 90.0
        # Колбэк отмены: спит и ждёт прерываемо, чтобы «Стоп» срабатывал сразу.
        self.should_stop: Optional[Callable[[], bool]] = None
        # Телеметрия: сообщаем наружу, что делаем прямо сейчас, — чтобы
        # пользователь видел активность и причину любой остановки.
        self.on_activity = on_activity
        # Ручная пауза: вернёт dict {url, reason} — тогда воркер встаёт на
        # барьер on_challenge (как при капче), пока пользователь не продолжит.
        self.should_pause: Optional[Callable[[], Optional[dict]]] = None
        # Тест-хук: сымитировать проверку на N-й загрузке страницы (0 — выкл).
        # Нужен, чтобы проверить обработку капчи, не дожидаясь реального 429.
        self.force_challenge_after = 0
        self._page_fetches = 0
        # Кэш HTML на диске: перебор бренда — это десятки карточек, и без него
        # повторный запуск с другим размером снова тянул бы весь список.
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl = cache_ttl
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar)
        )
        self._device_id = f"device_{int(time.time() * 1000)}"
        self._last_request_at = 0.0
        # Общий ограничитель: темп задаётся delay, всплеск — burst.
        self.limiter = RateLimiter(1.0 / max(delay, 0.01), burst=burst)
        self._lock = threading.Lock()
        self.stats = {"requests": 0, "cache_hits": 0, "cooldowns": 0, "challenges": 0}
        # Живое состояние: сколько запросов сейчас «в полёте», что происходит,
        # когда была последняя активность (для heartbeat в интерфейсе).
        self._active = 0
        self.last_activity_at = time.time()

    # ------------------------------------------------------------------ utils

    def _log(self, message: str) -> None:
        # В stderr: stdout — это результат, его перенаправляют в файл.
        if self.verbose:
            print(f"  [client] {message}", file=sys.stderr)

    def _emit(self, kind: str, **detail) -> None:
        """Сообщает наружу о текущем действии и обновляет heartbeat."""
        with self._lock:
            self.last_activity_at = time.time()
            detail["active"] = self._active
        if self.on_activity:
            try:
                self.on_activity(kind, detail)
            except Exception:  # noqa: BLE001 — телеметрия не должна ронять поиск
                pass

    def _sleep(self, seconds: float) -> None:
        """Прерываемый сон: просыпается на отмену, не «залипает» на бэкоффе."""
        end = time.monotonic() + max(seconds, 0.0)
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            if self.should_stop and self.should_stop():
                raise Cancelled()
            time.sleep(min(0.3, remaining))

    def _pause_pending(self) -> bool:
        # Паузу можно обработать только если есть барьер on_challenge — иначе
        # незачем будить очередь (и рисковать зациклиться).
        return bool(
            self.on_challenge and self.should_pause and self.should_pause()
        )

    def _throttle(self) -> None:
        while True:
            # Ручная пауза, запрошенная пользователем: встаём на общий барьер.
            # Проверяем здесь и после пробуждения из очереди — чтобы пауза
            # срабатывала даже посреди длинного ожидания после 429.
            if self._pause_pending() and self.on_challenge is not None:
                info = self.should_pause() or {"reason": "manual"}
                self._emit("paused", reason=info.get("reason", "manual"))
                if not self.on_challenge(info):
                    raise Cancelled()
                continue
            # Если действует общая пауза (после 429) — покажем это, а не молчим.
            blocked = self.limiter.blocked_seconds()
            if blocked > 1.0:
                self._emit("waiting", seconds=round(blocked, 1))
            if self.limiter.acquire(self.should_stop, wake=self._pause_pending):
                with self._lock:
                    self.stats["requests"] += 1
                return
            # Прервано: отмена — наверх, иначе это запрос паузы — новый виток.
            if self.should_stop and self.should_stop():
                raise Cancelled()

    def _effective_delay(self) -> float:
        return self.delay + self._extra_delay

    def _slow_down(self) -> None:
        """Увеличить паузу после проверки (до +4 c) и снизить темп."""
        with self._lock:
            self._extra_delay = min(self._extra_delay + 1.0, 4.0)
        self.limiter.set_rate(1.0 / self._effective_delay())
        self._log(f"замедляюсь: пауза теперь {self._effective_delay():.1f} c")

    def _speed_up(self) -> None:
        """Постепенно вернуться к обычному темпу после серии успехов."""
        with self._lock:
            if self._extra_delay <= 0:
                return
            self._extra_delay = max(0.0, self._extra_delay - 0.1)
        self.limiter.set_rate(1.0 / self._effective_delay())

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError) -> Optional[float]:
        """Сколько сайт просит подождать (заголовок Retry-After)."""
        raw = None
        try:
            raw = exc.headers.get("Retry-After")
        except AttributeError:
            return None
        if not raw:
            return None
        raw = raw.strip()
        if raw.isdigit():
            return float(raw)
        # Формат HTTP-даты.
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def _decode(response, raw: bytes) -> str:
        encoding = (response.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        return raw.decode("utf-8", "replace")

    def _open(self, request: urllib.request.Request) -> str:
        """Выполняет запрос с повторами при временных ошибках.

        HTTP 429/403 — это анти-бот блокировка по частоте: после короткого
        бэкоффа поднимаем ChallengeRequired, чтобы верхний уровень мог
        приостановиться и дать пользователю пройти проверку.
        """
        last_error: Optional[Exception] = None
        attempt = 0        # обычные повторы (сеть, 5xx)
        cooldowns = 0      # ожидания после 429 — свой бюджет, отдельно от retries
        path = request.full_url.replace(BASE_URL, "")

        while attempt < self.retries:
            self._throttle()
            started = time.monotonic()
            with self._lock:
                self._active += 1
            self._emit("request", path=path)
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    text = self._decode(response, response.read())
                self._emit("response", path=path,
                           ms=int((time.monotonic() - started) * 1000))
                return text
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429):
                    reason = "ratelimit" if exc.code == 429 else "forbidden"
                    self._slow_down()
                    # 429 почти всегда временный — сначала пережидаем сами,
                    # и только если не помогло, зовём человека.
                    if cooldowns < self.auto_cooldown_tries:
                        cooldowns += 1
                        wait = self._retry_after(exc)
                        if wait is None:
                            wait = min(15.0 * cooldowns, 60.0)
                        # Потолок: сайт не заставит нас зависнуть надолго.
                        wait = min(wait, self.max_cooldown) + random.uniform(0, 1.0)
                        with self._lock:
                            self.stats["cooldowns"] += 1
                        self._log(f"{exc.code}: жду {wait:.0f} c и повторяю")
                        self._emit("cooldown", seconds=round(wait, 1),
                                   reason=reason, code=exc.code, try_no=cooldowns)
                        if self.on_cooldown:
                            self.on_cooldown(wait, reason)
                        # Пауза общая для всех потоков, иначе остальные добьют лимит.
                        self.limiter.pause_for(wait)
                        continue
                    with self._lock:
                        self.stats["challenges"] += 1
                    self._emit("challenge", path=path, reason=reason)
                    raise ChallengeRequired(request.full_url, reason) from exc
                if exc.code < 500:
                    raise PoizonError(
                        f"HTTP {exc.code} для {request.full_url}"
                    ) from exc
                last_error = exc
                self._emit("http_error", path=path, code=exc.code)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                self._emit("net_error", path=path, error=str(exc)[:80])
            finally:
                with self._lock:
                    self._active = max(0, self._active - 1)

            attempt += 1
            if attempt < self.retries:
                backoff = self.delay * (2 ** attempt) + random.uniform(0, 0.4)
                self._log(f"попытка {attempt} не удалась ({last_error}), пауза {backoff:.1f}с")
                self._emit("retry", path=path, attempt=attempt,
                           seconds=round(backoff, 1), error=str(last_error)[:80])
                self._sleep(backoff)

        raise PoizonError(
            f"не удалось выполнить запрос {request.full_url}: {last_error}"
        )

    def _set_cookie(self, name: str, value: str) -> None:
        cookie = http.cookiejar.Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain="www.thepoizon.ru", domain_specified=True, domain_initial_dot=False,
            path="/", path_specified=True, secure=True, expires=None, discard=True,
            comment=None, comment_url=None, rest={},
        )
        self._jar.set_cookie(cookie)

    # ------------------------------------------------------------------- API

    def _api_headers(self) -> dict[str, str]:
        return {
            "User-Agent": _UA,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "duappid": "bbmax",
            "region": "BBMAX",
            "currencyCode": self.currency,
            "deviceId": self._device_id,
            "platform": "out_h5",
            "deviceType": "h5",
            "language": "bbmax",
            "timeZone": "GMT+03:00",
            "x-infr-flowtype": "CE_c-t1-sprint-592-round-1",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
        }

    def api_post(self, path: str, body: dict) -> dict:
        """POST к JSON API с подписью запроса."""
        url = self._encode_url(f"{BASE_URL}{path}?sign={calc_sign(body)}")
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers=self._api_headers(), method="POST"
        )
        text = self._open(request)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PoizonError(f"невалидный JSON от {path}: {text[:200]}") from exc

        code = data.get("code")
        if code not in (0, 200):
            raise PoizonError(
                f"API {path} вернул код {code}: {data.get('msg') or data.get('message')}"
            )
        return data

    def search(self, keywords: str, limit: int = 20, page: int = 1) -> list[dict]:
        """Поиск товаров по ключевым словам. Возвращает сырые элементы выдачи."""
        body = {
            "pageNum": page,
            "pageSize": max(1, min(limit, 100)),
            "scene": 1,
            "keywords": keywords,
        }
        data = self.api_post(_SEARCH_API, body)
        spu_list = (
            (data.get("data") or {}).get("searchSpuList", {}).get("spuList") or []
        )
        self._log(f"поиск «{keywords}»: найдено {len(spu_list)}")
        return spu_list

    def spu_detail(self, spu_id: int) -> dict:
        """Карточка товара через JSON API.

        Полезна для описания и списка размеров, но цен по размерам здесь нет —
        для них нужен fetch_product_html().
        """
        data = self.api_post(_DETAIL_API, {"spuId": int(spu_id)})
        return data.get("data") or {}

    # ------------------------------------------------------------------ HTML

    def fetch_product_html(
        self, url_or_spu: str | int, expect_next_data: bool = True
    ) -> str:
        """Загружает HTML страницы, проходя заглушку C3VK и капчу при появлении.

        expect_next_data — страница должна содержать __NEXT_DATA__ (товары и
        листинги); по его отсутствию распознаётся анти-бот блокировка.
        """
        if isinstance(url_or_spu, int) or str(url_or_spu).isdigit():
            path = f"/product/{url_or_spu}"
        else:
            path = str(url_or_spu)
            if path.startswith(BASE_URL):
                path = path[len(BASE_URL):]
            if not path.startswith("/"):
                path = "/" + path
        url = BASE_URL + path

        cached = self._cache_read(url)
        if cached is not None:
            with self._lock:
                self.stats["cache_hits"] += 1
            self._log(f"из кэша: {path}")
            self._emit("cache", path=path)
            return cached

        html = self._fetch_with_challenge(url, expect_next_data=expect_next_data)
        self._cache_write(url, html)
        return html

    def _fetch_with_challenge(self, url: str, expect_next_data: bool) -> str:
        """Загружает страницу, проходя C3VK-заглушку и — при необходимости —
        приостанавливаясь для ручного прохождения капчи."""
        with self._lock:
            self._page_fetches += 1
            force_here = (
                self.force_challenge_after
                and self._page_fetches == self.force_challenge_after
            )

        for attempt in range(1, self._max_challenge_rounds + 1):
            try:
                if force_here and attempt == 1:
                    # Тест-хук: один раз изображаем проверку.
                    html, reason = "", "demo"
                else:
                    html = self._get_html(url)
                    reason = self._detect_challenge(html, expect_next_data)
            except ChallengeRequired as exc:
                # 429/403 из _open — блокировка по частоте.
                reason = exc.reason
                html = ""

            if reason is None:
                self._speed_up()
                return html

            # C3VK — одноразовая JS-cookie, проходится автоматически.
            match = _C3VK_RE.search(html) if html else None
            if reason == "c3vk" and match:
                self._log(f"проходим C3VK-заглушку ({match.group(1)})")
                self._set_cookie("C3VK", match.group(1))
                continue

            # Настоящая проверка: замедляемся и просим человека пройти её.
            self._slow_down()
            info = {"url": url, "reason": reason, "attempt": attempt}
            if self.on_challenge is None:
                raise ChallengeRequired(url, reason)

            self._log(f"проверка ({reason}) — жду прохождения пользователем")
            if not self.on_challenge(info):
                raise ChallengeRequired(url, reason)

            # После ручного прохождения сбрасываем C3VK и пробуем заново.
            self._clear_c3vk()

        raise ChallengeRequired(url, "проверка не пройдена за несколько попыток")

    @staticmethod
    def _detect_challenge(html: str, expect_next_data: bool) -> Optional[str]:
        """Определяет тип помехи: 'c3vk', 'captcha' или None (страница валидна)."""
        if len(html) < 2000 and "C3VK" in html:
            return "c3vk"
        # Легитимные страницы товара и листингов всегда содержат __NEXT_DATA__.
        # Его отсутствие вместе с анти-бот маркерами — признак блокировки.
        if expect_next_data and "__NEXT_DATA__" not in html:
            low = html.lower()
            if any(marker in low for marker in _CHALLENGE_MARKERS):
                return "captcha"
            if len(html) < 4000:
                return "captcha"
        return None

    def _clear_c3vk(self) -> None:
        try:
            self._jar.clear("www.thepoizon.ru", "/", "C3VK")
        except KeyError:
            pass

    # ----------------------------------------------------------------- кэш

    def _cache_path(self, url: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.html"

    def _cache_read(self, url: str) -> Optional[str]:
        path = self._cache_path(url)
        if not path or not path.exists():
            return None
        if self.cache_ttl >= 0 and time.time() - path.stat().st_mtime > self.cache_ttl:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _cache_write(self, url: str, html: str) -> None:
        path = self._cache_path(url)
        if not path or len(html) < 2000:  # заглушки не кэшируем
            return
        try:
            path.write_text(html, encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _encode_url(url: str) -> str:
        """Percent-кодирует не-ASCII в URL: у части товаров кириллица в слаге,
        а urllib отправляет строку запроса в ASCII и без этого падает."""
        parts = urlsplit(url)
        # safe сохраняет уже закодированные %XX и служебные символы пути/запроса.
        path = quote(parts.path, safe="/%:@!$&'()*+,;=~-._")
        query = quote(parts.query, safe="/%:@!$&'()*+,;=~-._?")
        return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))

    def _get_html(self, url: str) -> str:
        request = urllib.request.Request(
            self._encode_url(url),
            headers={
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": f"{BASE_URL}/",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        return self._open(request)

    @staticmethod
    def extract_next_data(html: str) -> dict:
        """Достаёт JSON из тега __NEXT_DATA__ страницы товара."""
        match = _NEXT_DATA_RE.search(html)
        if not match:
            raise PoizonError(
                "на странице нет блока __NEXT_DATA__ "
                "(вероятно, страница не отдалась или изменилась вёрстка)"
            )
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise PoizonError(f"не удалось разобрать __NEXT_DATA__: {exc}") from exc
