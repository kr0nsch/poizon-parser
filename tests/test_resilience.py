"""Тесты устойчивости: прерываемые паузы, потолок ожидания, отмена."""

import threading
import time
import unittest
import urllib.error

from poizon_parser.client import Cancelled, PoizonClient, RateLimiter


class TestInterruptibleLimiter(unittest.TestCase):
    def test_acquire_returns_false_on_stop(self):
        limiter = RateLimiter(rate_per_sec=1000.0, burst=1)
        limiter.pause_for(10.0)  # длинная пауза
        stop = {"v": False}
        threading.Timer(0.2, lambda: stop.__setitem__("v", True)).start()
        start = time.monotonic()
        ok = limiter.acquire(should_stop=lambda: stop["v"])
        elapsed = time.monotonic() - start
        self.assertFalse(ok)
        self.assertLess(elapsed, 2.0)  # прервались быстро, не ждали все 10 c

    def test_acquire_true_when_not_stopped(self):
        limiter = RateLimiter(rate_per_sec=1000.0, burst=2)
        self.assertTrue(limiter.acquire(should_stop=lambda: False))

    def test_blocked_seconds_reported(self):
        limiter = RateLimiter(rate_per_sec=1000.0, burst=1)
        limiter.pause_for(5.0)
        self.assertGreater(limiter.blocked_seconds(), 4.0)


class TestCooldownCap(unittest.TestCase):
    def test_retry_after_capped(self):
        """Огромный Retry-After не заставляет ждать час."""
        client = PoizonClient(retries=2, delay=0.01)
        client.max_cooldown = 2.0
        client.auto_cooldown_tries = 1
        waits = []
        client.on_cooldown = lambda wait, reason: waits.append(wait)
        paused = []
        client.limiter.pause_for = lambda s: paused.append(s)

        calls = {"n": 0}

        def flaky(request, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 429, "m", {"Retry-After": "3600"}, None
                )
            return _Resp()

        client._opener = type("O", (), {"open": staticmethod(flaky)})()
        client._get_html("https://www.thepoizon.ru/product/1")
        self.assertTrue(paused)
        self.assertLessEqual(paused[0], 3.0)  # не 3600


class TestCancellation(unittest.TestCase):
    def test_throttle_raises_cancelled_when_stopped(self):
        client = PoizonClient(delay=0.01)
        client.should_stop = lambda: True
        with self.assertRaises(Cancelled):
            client._throttle()

    def test_cancelled_is_not_poizon_error(self):
        from poizon_parser.client import PoizonError
        self.assertFalse(issubclass(Cancelled, PoizonError))


class _Resp:
    headers = {}

    def read(self):
        return (
            b'<html><script id="__NEXT_DATA__">{"a":1}</script>' + b"x" * 3000
        )

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    unittest.main()
