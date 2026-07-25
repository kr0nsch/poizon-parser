"""Тесты мониторинга состояния и ручной паузы."""

import threading
import time
import unittest
import urllib.error

from poizon_parser.client import Cancelled, PoizonClient
from poizon_parser.webapp import JobManager


class _Resp:
    headers = {}

    def __init__(self, body=b'<html><script id="__NEXT_DATA__">{}</script>' + b"x" * 3000):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestActivityTelemetry(unittest.TestCase):
    def test_emits_request_and_response(self):
        events = []
        c = PoizonClient(delay=0.01, on_activity=lambda k, d: events.append((k, d)))
        c._opener = type("O", (), {"open": staticmethod(lambda r, timeout: _Resp())})()
        c._get_html("https://www.thepoizon.ru/product/1")
        kinds = [k for k, _ in events]
        self.assertIn("request", kinds)
        self.assertIn("response", kinds)

    def test_response_carries_timing(self):
        events = []
        c = PoizonClient(delay=0.01, on_activity=lambda k, d: events.append((k, d)))
        c._opener = type("O", (), {"open": staticmethod(lambda r, timeout: _Resp())})()
        c._get_html("https://www.thepoizon.ru/product/1")
        resp = next(d for k, d in events if k == "response")
        self.assertIn("ms", resp)

    def test_last_activity_updates(self):
        c = PoizonClient(delay=0.01)
        c._opener = type("O", (), {"open": staticmethod(lambda r, timeout: _Resp())})()
        before = c.last_activity_at
        time.sleep(0.01)
        c._get_html("https://www.thepoizon.ru/product/1")
        self.assertGreater(c.last_activity_at, before)

    def test_net_error_emitted(self):
        events = []
        c = PoizonClient(delay=0.01, retries=1, on_activity=lambda k, d: events.append(k))

        def boom(r, timeout):
            raise urllib.error.URLError("timed out")

        c._opener = type("O", (), {"open": staticmethod(boom)})()
        try:
            c._get_html("https://www.thepoizon.ru/product/1")
        except Exception:
            pass
        self.assertIn("net_error", events)

    def test_active_counter_returns_to_zero(self):
        c = PoizonClient(delay=0.01)
        c._opener = type("O", (), {"open": staticmethod(lambda r, timeout: _Resp())})()
        c._get_html("https://www.thepoizon.ru/product/1")
        self.assertEqual(c._active, 0)


class TestInterruptibleBackoff(unittest.TestCase):
    def test_sleep_interrupted_by_stop(self):
        c = PoizonClient(delay=0.01)
        stop = {"v": False}
        c.should_stop = lambda: stop["v"]
        threading.Timer(0.15, lambda: stop.__setitem__("v", True)).start()
        start = time.monotonic()
        with self.assertRaises(Cancelled):
            c._sleep(10.0)
        self.assertLess(time.monotonic() - start, 2.0)

    def test_sleep_completes_normally(self):
        c = PoizonClient(delay=0.01)
        start = time.monotonic()
        c._sleep(0.2)
        self.assertGreaterEqual(time.monotonic() - start, 0.15)


class TestManualPause(unittest.TestCase):
    def test_throttle_triggers_pause_barrier(self):
        c = PoizonClient(delay=0.01)
        # Пауза активна один раз; on_challenge «снимает» её, как resume().
        state = {"paused": {"url": "https://x", "reason": "manual"}}
        c.should_pause = lambda: state["paused"]
        calls = []

        def on_challenge(info):
            calls.append(info)
            state["paused"] = None  # пользователь продолжил → флаг снят
            return True

        c.on_challenge = on_challenge
        c._throttle()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["reason"], "manual")

    def test_pause_abort_raises_cancelled(self):
        c = PoizonClient(delay=0.01)
        c.should_pause = lambda: {"url": "https://x", "reason": "manual"}
        c.on_challenge = lambda info: False  # «отменить»
        with self.assertRaises(Cancelled):
            c._throttle()

    def test_no_pause_when_not_requested(self):
        c = PoizonClient(delay=0.01)
        c.should_pause = lambda: None
        c.on_challenge = lambda info: (_ for _ in ()).throw(AssertionError("не должно"))
        c._throttle()  # не должно дёрнуть on_challenge


class TestJobManagerPause(unittest.TestCase):
    def test_request_pause_sets_flag(self):
        m = JobManager()
        m._jobs["j"] = {"id": "j", "status": "running", "brand": {"url": "/brand/nike"},
                        "pause_requested": None, "log": []}
        self.assertTrue(m.request_pause("j"))
        self.assertIsNotNone(m._jobs["j"]["pause_requested"])
        self.assertEqual(m._jobs["j"]["pause_requested"]["reason"], "manual")

    def test_request_pause_rejected_when_done(self):
        m = JobManager()
        m._jobs["j"] = {"id": "j", "status": "done", "pause_requested": None, "log": []}
        self.assertFalse(m.request_pause("j"))

    def test_resume_clears_pause_request(self):
        m = JobManager()
        job = {"id": "j", "status": "captcha", "paused": True, "captcha": {},
               "pause_requested": {"reason": "manual"}, "log": [],
               "_cond": threading.Condition(), "_resume_gen": 0}
        m._jobs["j"] = job
        self.assertTrue(m.resume("j"))
        self.assertIsNone(job["pause_requested"])
        self.assertFalse(job["paused"])


class TestStopReasonInSnapshot(unittest.TestCase):
    def test_idle_seconds_in_snapshot(self):
        m = JobManager()
        job = {"id": "j", "status": "running", "last_activity_at": time.time() - 5,
               "log": [], "pause_requested": None}
        m._jobs["j"] = job
        snap = m.snapshot("j")
        self.assertGreaterEqual(snap["idle_seconds"], 4)

    def test_pause_requested_is_bool_in_snapshot(self):
        m = JobManager()
        job = {"id": "j", "status": "running", "last_activity_at": time.time(),
               "log": [], "pause_requested": {"reason": "manual"}}
        m._jobs["j"] = job
        snap = m.snapshot("j")
        self.assertIs(snap["pause_requested"], True)


if __name__ == "__main__":
    unittest.main()
