"""Тесты мониторинга состояния и ручной паузы."""

import threading
import time
import unittest
import urllib.error
from unittest import mock

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


class TestVerboseLog(unittest.TestCase):
    def test_verbose_log_goes_to_stderr(self):
        # stdout — результат команды; журнал -v не должен в него попадать.
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        client = PoizonClient(verbose=True)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            client._log("проверка")
        self.assertEqual(out.getvalue(), "")
        self.assertIn("[client] проверка", err.getvalue())


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
        # Часы подменены: time.time() на Windows тикает раз в ~15,6 мс, и
        # сравнение «до/после» через реальный sleep(0.01) было нестабильным.
        c = PoizonClient(delay=0.01)
        c._opener = type("O", (), {"open": staticmethod(lambda r, timeout: _Resp())})()
        c.last_activity_at = 1000.0
        with mock.patch.object(time, "time", return_value=2000.0):
            c._get_html("https://www.thepoizon.ru/product/1")
        self.assertEqual(c.last_activity_at, 2000.0)

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
        # Поддельные часы: проверяем, что спим ровно заданное время короткими
        # кусками (чтобы «Стоп» срабатывал), не завися от разрешения таймера.
        clock = {"now": 100.0}
        naps = []

        def fake_sleep(seconds):
            naps.append(seconds)
            clock["now"] += seconds

        c = PoizonClient(delay=0.01)
        c.should_stop = lambda: False
        with mock.patch.object(time, "monotonic", lambda: clock["now"]), \
                mock.patch.object(time, "sleep", fake_sleep):
            c._sleep(1.0)
        self.assertAlmostEqual(sum(naps), 1.0, places=9)
        self.assertGreater(len(naps), 1)
        self.assertTrue(all(nap <= 0.3 for nap in naps))


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


def add_job(manager: JobManager, **fields) -> dict:
    """Задача в той же форме, что создаёт JobManager, с полями поверх."""
    job = JobManager._new_job({})
    job.update(id="j", **fields)
    manager._jobs["j"] = job
    return job


class TestJobManagerPause(unittest.TestCase):
    def test_request_pause_sets_flag(self):
        m = JobManager()
        add_job(m, status="running", brand={"url": "/brand/nike"})
        self.assertTrue(m.request_pause("j"))
        self.assertIsNotNone(m._jobs["j"]["pause_requested"])
        self.assertEqual(m._jobs["j"]["pause_requested"]["reason"], "manual")

    def test_request_pause_rejected_when_done(self):
        m = JobManager()
        add_job(m, status="done")
        self.assertFalse(m.request_pause("j"))

    def test_resume_clears_pause_request(self):
        m = JobManager()
        job = add_job(m, status="captcha", paused=True, captcha={},
                      pause_requested={"reason": "manual"})
        self.assertTrue(m.resume("j"))
        self.assertIsNone(job["pause_requested"])
        self.assertFalse(job["paused"])


class TestStopReasonInSnapshot(unittest.TestCase):
    def test_idle_seconds_in_snapshot(self):
        m = JobManager()
        add_job(m, status="running", last_activity_at=1000.0)
        with mock.patch.object(time, "time", return_value=1005.0):
            snap = m.snapshot("j")
        self.assertEqual(snap["idle_seconds"], 5.0)

    def test_pause_requested_is_bool_in_snapshot(self):
        m = JobManager()
        add_job(m, status="running", pause_requested={"reason": "manual"})
        snap = m.snapshot("j")
        self.assertIs(snap["pause_requested"], True)


if __name__ == "__main__":
    unittest.main()
