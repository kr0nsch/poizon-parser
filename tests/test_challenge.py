"""Тесты обнаружения проверок (капчи), пауз, откатов и ограничителя частоты."""

import unittest

from poizon_parser.client import ChallengeRequired, PoizonClient

GOOD_PAGE = '<html><script id="__NEXT_DATA__">{"a":1}</script>' + "x" * 3000
C3VK_STUB = '<script>document.cookie="C3VK=deadbeef; path=/;"</script>'
CAPTCHA_PAGE = "<html><body>Please solve the captcha to continue</body></html>"


class TestUrlEncoding(unittest.TestCase):
    """Регрессия: кириллица в слаге URL роняла urllib (ascii codec)."""

    def test_cyrillic_slug_encoded(self):
        url = "https://www.thepoizon.ru/product/ники-mercurial-8900"
        out = PoizonClient._encode_url(url)
        self.assertTrue(out.isascii())
        self.assertIn("%D0", out)  # кириллица закодирована

    def test_ascii_url_unchanged(self):
        url = "https://www.thepoizon.ru/product/nike-air-force-1-8900?sign=abc"
        self.assertEqual(PoizonClient._encode_url(url), url)

    def test_already_encoded_not_double_encoded(self):
        url = "https://www.thepoizon.ru/product/%D0%BD%D0%B8-8900"
        self.assertEqual(PoizonClient._encode_url(url), url)

    def test_query_preserved(self):
        url = "https://www.thepoizon.ru/x?sign=abc123&a=1"
        out = PoizonClient._encode_url(url)
        self.assertIn("sign=abc123", out)
        self.assertIn("a=1", out)


class _FakeResponse:
    """Минимальная замена HTTPResponse для тестов."""

    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")
        self.headers = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestDetectChallenge(unittest.TestCase):
    def setUp(self):
        self.client = PoizonClient()

    def test_good_page_is_not_challenge(self):
        self.assertIsNone(self.client._detect_challenge(GOOD_PAGE, True))

    def test_c3vk_stub_detected(self):
        self.assertEqual(self.client._detect_challenge(C3VK_STUB, True), "c3vk")

    def test_captcha_marker_detected(self):
        self.assertEqual(self.client._detect_challenge(CAPTCHA_PAGE, True), "captcha")

    def test_short_page_without_next_data_is_challenge(self):
        self.assertEqual(self.client._detect_challenge("<html>oops</html>", True), "captcha")

    def test_no_next_data_when_not_expected_is_ok(self):
        self.assertIsNone(self.client._detect_challenge("<html>ok</html>", False))


class TestC3vkAutoPass(unittest.TestCase):
    def test_c3vk_passed_then_good_page(self):
        client = PoizonClient()
        pages = iter([C3VK_STUB, GOOD_PAGE])
        client._get_html = lambda url: next(pages)
        html = client.fetch_product_html("/product/1")
        self.assertIn("__NEXT_DATA__", html)


class TestCaptchaPauseResume(unittest.TestCase):
    def test_callback_called_then_resume_succeeds(self):
        calls = []

        def on_challenge(info):
            calls.append(info)
            return True  # «пользователь прошёл капчу»

        client = PoizonClient(on_challenge=on_challenge)
        # Сначала капча, после «прохождения» — нормальная страница.
        pages = iter([CAPTCHA_PAGE, GOOD_PAGE])
        client._get_html = lambda url: next(pages)

        html = client.fetch_product_html("/product/1")
        self.assertIn("__NEXT_DATA__", html)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["reason"], "captcha")

    def test_callback_abort_raises(self):
        client = PoizonClient(on_challenge=lambda info: False)
        client._get_html = lambda url: CAPTCHA_PAGE
        with self.assertRaises(ChallengeRequired):
            client.fetch_product_html("/product/1")

    def test_no_callback_raises_immediately(self):
        client = PoizonClient()  # on_challenge=None
        client._get_html = lambda url: CAPTCHA_PAGE
        with self.assertRaises(ChallengeRequired):
            client.fetch_product_html("/product/1")

    def test_slows_down_on_challenge(self):
        client = PoizonClient(on_challenge=lambda info: True)
        pages = iter([CAPTCHA_PAGE, GOOD_PAGE])
        client._get_html = lambda url: next(pages)
        before = client._extra_delay
        client.fetch_product_html("/product/1")
        self.assertGreater(client._extra_delay, before)


def _always_429(request, timeout):
    import urllib.error

    raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, None)


class TestRateLimitBecomesChallenge(unittest.TestCase):
    def test_429_raises_challenge_after_cooldowns_exhausted(self):
        client = PoizonClient(retries=1, delay=0.01)
        client.auto_cooldown_tries = 0  # без ожиданий — сразу к человеку
        client._opener = type("O", (), {"open": staticmethod(_always_429)})()
        with self.assertRaises(ChallengeRequired) as ctx:
            client._get_html("https://www.thepoizon.ru/product/1")
        self.assertEqual(ctx.exception.reason, "ratelimit")

    def test_429_is_absorbed_automatically_first(self):
        """429 сначала пережидается сам, без обращения к пользователю."""
        client = PoizonClient(retries=2, delay=0.01)
        client.auto_cooldown_tries = 2
        seen: list[float] = []
        client.on_cooldown = lambda wait, reason: seen.append(wait)
        # Мгновенные «ожидания», чтобы тест не спал.
        client.limiter.pause_for = lambda seconds: None

        calls = {"n": 0}

        def flaky(request, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                _always_429(request, timeout)
            return _FakeResponse(GOOD_PAGE)

        client._opener = type("O", (), {"open": staticmethod(flaky)})()
        html = client._get_html("https://www.thepoizon.ru/product/1")
        self.assertIn("__NEXT_DATA__", html)
        self.assertEqual(len(seen), 1)  # один автоматический откат
        self.assertEqual(client.stats["cooldowns"], 1)


class TestRetryAfter(unittest.TestCase):
    def test_numeric_retry_after_parsed(self):
        import urllib.error

        exc = urllib.error.HTTPError(
            "u", 429, "m", {"Retry-After": "42"}, None
        )
        self.assertEqual(PoizonClient._retry_after(exc), 42.0)

    def test_missing_retry_after_is_none(self):
        import urllib.error

        exc = urllib.error.HTTPError("u", 429, "m", {}, None)
        self.assertIsNone(PoizonClient._retry_after(exc))


class _FakeClock:
    """Виртуальное время для ограничителя: sleep лишь двигает часы.

    С настоящими часами проверки «прошло больше 0,1 с» зависят от загрузки
    машины и грубого таймера Windows; виртуальные часы делают их точными.
    """

    def __init__(self) -> None:
        import threading as th

        self._now = 1000.0
        self._lock = th.Lock()

    def monotonic(self) -> float:
        with self._lock:
            return self._now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self._now += max(seconds, 0.0)


class TestRateLimiter(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from poizon_parser import client

        self.clock = _FakeClock()
        # Подменяем часы и сон только в модуле клиента — тест не спит, а
        # остальной процесс живёт по настоящему времени.
        patcher = patch.object(
            client,
            "time",
            SimpleNamespace(monotonic=self.clock.monotonic, sleep=self.clock.sleep),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_limits_rate_across_threads(self):
        import threading as th

        from poizon_parser.client import RateLimiter

        rate = 50.0
        limiter = RateLimiter(rate_per_sec=rate, burst=1)
        start = self.clock.monotonic()
        stamps: list[float] = []
        lock = th.Lock()

        def worker():
            for _ in range(4):
                limiter.acquire()
                with lock:
                    stamps.append(self.clock.monotonic())

        threads = [th.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(len(stamps), 12)
        # k-й по счёту запрос не раньше, чем через k/rate: первый из запаса
        # burst, остальные — по одному токену на 1/rate секунды.
        for k, stamp in enumerate(sorted(stamps)):
            self.assertGreaterEqual(stamp - start, k / rate - 1e-9)

    def test_pause_for_blocks_everyone(self):
        from poizon_parser.client import RateLimiter

        limiter = RateLimiter(rate_per_sec=1000.0, burst=5)
        start = self.clock.monotonic()
        limiter.pause_for(0.2)
        self.assertTrue(limiter.acquire())
        self.assertGreaterEqual(self.clock.monotonic() - start, 0.2)


if __name__ == "__main__":
    unittest.main()
