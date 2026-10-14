"""Тесты стабильности и новых фич веб-сервера."""

import io
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from poizon_parser import webapp
from poizon_parser.catalog import Brand
from poizon_parser.webapp import (
    JobManager,
    ReportRequestError,
    local_url,
    report_meta,
    select_report_matches,
    validate_search,
)
from poizon_parser.sizechart import compare_brands, sizes_for_foot


def add_job(manager: JobManager, **overrides) -> dict:
    """Кладёт задачу в менеджер без запуска потока (и без сети)."""
    job = JobManager._new_job({"brand": "nike", "size": "26.5", "scale": "CM"})
    job.update(overrides)
    manager._jobs[job["id"]] = job
    return job


class TestValidateSearch(unittest.TestCase):
    def test_ok_foot_input(self):
        self.assertIsNone(validate_search({"brand": "nike", "size": "26,5", "scale": "CM"}))

    def test_missing_brand(self):
        self.assertIn("бренд", validate_search({"size": "26"}))

    def test_missing_size(self):
        self.assertIn("размер", validate_search({"brand": "nike"}))

    def test_non_numeric_size(self):
        self.assertIn("число", validate_search({"brand": "nike", "size": "большой"}))

    def test_foot_too_small_rejected(self):
        # 5 см — очевидно мм или опечатка.
        msg = validate_search({"brand": "nike", "size": "5", "scale": "CM"})
        self.assertIn("границ", msg)

    def test_foot_too_large_rejected(self):
        msg = validate_search({"brand": "nike", "size": "265", "scale": "CM"})
        self.assertIn("границ", msg)

    def test_eu_scale_not_bounded_by_foot_limits(self):
        # В шкале EU число 42 нормально, границы стопы не применяются.
        self.assertIsNone(validate_search({"brand": "nike", "size": "42", "scale": "EU"}))

    def test_negative_price_rejected(self):
        msg = validate_search({"brand": "nike", "size": "26", "scale": "CM", "maxPrice": "-100"})
        self.assertIn("отрицатель", msg)

    def test_bad_price_rejected(self):
        msg = validate_search({"brand": "nike", "size": "26", "scale": "CM", "maxPrice": "дорого"})
        self.assertIn("числом", msg)

    def test_non_finite_numbers_rejected(self):
        # float() принимает «nan» и «inf», а сравнения с ними всегда ложны —
        # без явной проверки такие значения проходили бы границы стопы.
        for size in ("nan", "inf", "-inf"):
            with self.subTest(size=size):
                msg = validate_search({"brand": "nike", "size": size, "scale": "CM"})
                self.assertIn("число", msg)
        msg = validate_search({"brand": "nike", "size": "26", "maxPrice": "nan"})
        self.assertIn("числом", msg)


class TestSearchScale(unittest.TestCase):
    """Шкала веб-поиска — по тому же правилу, что у CLI и SizeFinder."""

    def scan_args(self, size, scale=None):
        """(размер, шкала), с которыми задача запускает обход карточек."""
        params = {"brand": "nike", "size": size}
        if scale is not None:
            params["scale"] = scale
        manager = JobManager()
        job = JobManager._new_job(params)
        with patch.object(webapp, "PoizonClient") as client_class, \
                patch.object(webapp, "Catalog") as catalog_class, \
                patch.object(webapp, "SizeFinder") as finder_class:
            client_class.return_value.stats = {}
            catalog = catalog_class.return_value
            catalog.find_brand.return_value = Brand(
                brand_id=1, name="Nike", url="/brand/nike"
            )
            catalog.brand_items.return_value = []
            manager._search(job, params)
        args = finder_class.return_value.scan_products.call_args[0]
        return args[1], args[2]

    def test_bare_us_does_not_override_selected_women_scale(self):
        # Регрессия: голое «US» в размере перебивало «US W» из формы.
        self.assertEqual(self.scan_args("US 7", "US W"), (7.0, "US W"))

    def test_gendered_scale_in_size_wins(self):
        self.assertEqual(self.scan_args("US W 7", "US M"), (7.0, "US W"))

    def test_bare_us_with_other_scale_is_men(self):
        self.assertEqual(self.scan_args("US 9", "EU"), (9.0, "US M"))

    def test_selected_scale_and_default(self):
        self.assertEqual(self.scan_args("26.5", "CM"), (26.5, "CM"))
        self.assertEqual(self.scan_args("42"), (42.0, "EU"))


class TestSizeOutsideBrandChart(unittest.TestCase):
    """Размер вне официальной таблицы бренда — ошибка до сбора каталога."""

    def run_search(self, brand_name, params):
        manager = JobManager()
        job = JobManager._new_job(params)
        with patch.object(webapp, "PoizonClient") as client_class, \
                patch.object(webapp, "Catalog") as catalog_class, \
                patch.object(webapp, "SizeFinder") as finder_class:
            client_class.return_value.stats = {}
            catalog = catalog_class.return_value
            catalog.find_brand.return_value = Brand(
                brand_id=1, name=brand_name, url="/brand/x"
            )
            catalog.brand_items.return_value = []
            try:
                manager._search(job, params)
            finally:
                self.brand_items = catalog.brand_items
                self.scan = finder_class.return_value.scan_products

    def test_out_of_chart_size_fails_before_catalog(self):
        # Регрессия: такой поиск скачивал все карточки бренда ради пустого итога.
        cases = (
            ("Nike", {"brand": "nike", "size": "18", "scale": "CM"}),
            ("Puma", {"brand": "puma", "size": "30", "scale": "US W",
                      "gender": "women"}),
        )
        for brand_name, params in cases:
            with self.subTest(brand=brand_name, params=params):
                with self.assertRaises(ValueError) as ctx:
                    self.run_search(brand_name, params)
                message = str(ctx.exception)
                self.assertIn("вне официальной таблицы", message)
                self.assertIn(brand_name, message)
                self.assertIn("Проверьте", message)
                self.brand_items.assert_not_called()
                self.scan.assert_not_called()

    def test_size_inside_chart_still_searches(self):
        self.run_search("Nike", {"brand": "nike", "size": "26.5", "scale": "CM"})
        self.brand_items.assert_called_once()
        self.scan.assert_called_once()

    def test_job_reports_the_reason(self):
        manager = JobManager()
        params = {"brand": "nike", "size": "18", "scale": "CM"}
        job = JobManager._new_job(params)
        manager._jobs[job["id"]] = job
        with patch.object(webapp, "PoizonClient") as client_class, \
                patch.object(webapp, "Catalog") as catalog_class, \
                patch.object(webapp, "SizeFinder"):
            client_class.return_value.stats = {}
            catalog_class.return_value.find_brand.return_value = Brand(
                brand_id=1, name="Nike", url="/brand/nike"
            )
            manager._run(job)
        snap = manager.snapshot(job["id"])
        self.assertEqual(snap["status"], "error")
        self.assertIn("вне официальной таблицы Nike", snap["error"])
        catalog_class.return_value.brand_items.assert_not_called()


class TestLiveStats(unittest.TestCase):
    """Строка статистики под прогрессом обновляется во время поиска."""

    def test_snapshot_reads_client_counters_while_running(self):
        manager = JobManager()
        job = add_job(manager, status="running")
        counters = {"requests": 0, "cache_hits": 0, "cooldowns": 0, "challenges": 0}
        job["_client_stats"] = counters

        counters["requests"] = 3
        counters["cache_hits"] = 2
        stats = manager.snapshot(job["id"])["stats"]
        self.assertEqual(stats["requests"], 3)
        self.assertEqual(stats["cache_hits"], 2)
        # Снимок — копия: дальнейший счёт клиента его не меняет.
        counters["requests"] = 4
        self.assertEqual(stats["requests"], 3)

    def test_search_exposes_client_counters(self):
        manager = JobManager()
        params = {"brand": "nike", "size": "26.5", "scale": "CM"}
        job = JobManager._new_job(params)
        with patch.object(webapp, "PoizonClient") as client_class, \
                patch.object(webapp, "Catalog") as catalog_class, \
                patch.object(webapp, "SizeFinder"):
            client_class.return_value.stats = {"requests": 7}
            catalog = catalog_class.return_value
            catalog.find_brand.return_value = Brand(
                brand_id=1, name="Nike", url="/brand/nike"
            )
            catalog.brand_items.return_value = []
            manager._search(job, params)
        manager._jobs[job["id"]] = job
        self.assertEqual(manager.snapshot(job["id"])["stats"], {"requests": 7})


class TestJobRetention(unittest.TestCase):
    def test_finished_jobs_evicted_over_limit(self):
        from poizon_parser import webapp
        manager = JobManager()
        # Наполняем завершёнными задачами вручную (без потоков).
        for i in range(webapp.JOB_RETENTION + 10):
            jid = f"job{i}"
            manager._jobs[jid] = {
                "id": jid, "status": "done", "finished_at": float(i),
            }
        with manager._lock:
            manager._evict_old()
        self.assertEqual(len(manager._jobs), webapp.JOB_RETENTION)
        # Остались самые новые.
        self.assertIn(f"job{webapp.JOB_RETENTION + 9}", manager._jobs)
        self.assertNotIn("job0", manager._jobs)

    def test_active_jobs_never_evicted(self):
        from poizon_parser import webapp
        manager = JobManager()
        for i in range(webapp.JOB_RETENTION + 5):
            manager._jobs[f"run{i}"] = {
                "id": f"run{i}", "status": "running", "finished_at": None,
            }
        with manager._lock:
            manager._evict_old()
        # Активные не удаляются, сколько бы их ни было.
        self.assertEqual(len(manager._jobs), webapp.JOB_RETENTION + 5)

    def test_count_reports_active(self):
        manager = JobManager()
        manager._jobs["a"] = {"id": "a", "status": "running"}
        manager._jobs["b"] = {"id": "b", "status": "done"}
        manager._jobs["c"] = {"id": "c", "status": "captcha"}
        self.assertEqual(manager.count(), {"total": 3, "active": 2})


class TestActiveJobLimit(unittest.TestCase):
    """Одновременных поисков — не больше MAX_ACTIVE_JOBS."""

    def setUp(self):
        # Потоки задач не запускаем: без сети при любом исходе теста.
        run = patch.object(JobManager, "_run")
        run.start()
        self.addCleanup(run.stop)
        limit = patch.object(webapp, "MAX_ACTIVE_JOBS", 2)
        limit.start()
        self.addCleanup(limit.stop)

    def test_create_refuses_over_limit(self):
        manager = JobManager()
        add_job(manager, status="running")
        add_job(manager, status="captcha")
        with self.assertRaises(webapp.TooManyJobs) as ctx:
            manager.create({"brand": "nike", "size": "26.5"})
        self.assertIn("2 из 2", str(ctx.exception))
        self.assertEqual(manager.count(), {"total": 2, "active": 2})

    def test_finished_jobs_do_not_count(self):
        manager = JobManager()
        add_job(manager, status="running")
        for status in ("done", "error", "cancelled"):
            add_job(manager, status=status)
        job = manager.create({"brand": "nike", "size": "26.5"})
        self.assertIn(job["id"], manager._jobs)
        self.assertEqual(manager.count()["active"], 2)

    def test_unpolled_jobs_free_their_slots(self):
        # Регрессия: после нескольких перезагрузок страницы во время долгих
        # поисков новые поиски получали 429, хотя продолжать старые некому.
        manager = JobManager()
        stale = time.time() - webapp.ABANDON_AFTER - 1
        old_running = add_job(manager, status="running", _last_poll=stale)
        old_paused = add_job(manager, status="captcha", _last_poll=stale)

        job = manager.create({"brand": "nike", "size": "26.5"})

        self.assertIn(job["id"], manager._jobs)
        for old in (old_running, old_paused):
            self.assertTrue(old["cancel"])
            self.assertTrue(old["_abandoned"])
        self.assertEqual(manager.count()["active"], 1)

    def test_polled_jobs_keep_their_slots(self):
        manager = JobManager()
        live = add_job(manager, status="running")
        add_job(manager, status="running")
        with self.assertRaises(webapp.TooManyJobs):
            manager.create({"brand": "nike", "size": "26.5"})
        self.assertFalse(live["cancel"])


def wait_until(predicate, timeout: float = 2.0) -> bool:
    """Ждёт условия без фиксированных пауз (поток мог ещё не стартовать)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestManualPause(unittest.TestCase):
    """Ручная пауза: её можно отозвать, пока она не сработала."""

    def setUp(self):
        self.manager = JobManager()
        self.job = add_job(self.manager)
        # Отмена будит любой зависший на барьере поток, если тест упадёт.
        self.addCleanup(self.manager.cancel, self.job["id"])

    def test_resume_withdraws_pending_manual_pause(self):
        self.assertTrue(self.manager.request_pause(self.job["id"]))
        self.assertTrue(self.manager.snapshot(self.job["id"])["pause_requested"])

        self.assertTrue(self.manager.resume(self.job["id"]))

        snap = self.manager.snapshot(self.job["id"])
        self.assertFalse(snap["pause_requested"])
        self.assertEqual(snap["status"], "running")
        self.assertIn("отменена", snap["log"][-1])

    def test_withdrawn_pause_does_not_stop_worker(self):
        # Воркер успел прочитать запрос паузы, но дошёл до барьера уже после
        # отмены — вставать на паузу он не должен.
        self.manager.request_pause(self.job["id"])
        info = self.job["pause_requested"]
        self.manager.resume(self.job["id"])

        result = []
        worker = threading.Thread(
            target=lambda: result.append(self.manager._wait_for_captcha(self.job, info)),
            daemon=True,
        )
        worker.start()
        worker.join(timeout=2)
        if worker.is_alive():  # не оставляем висящий поток при регрессии
            self.manager.cancel(self.job["id"])
            self.fail("воркер встал на уже отменённую паузу")
        self.assertEqual(result, [True])
        self.assertFalse(self.job["paused"])
        self.assertEqual(self.job["status"], "running")

    def test_resume_after_captcha_wakes_worker(self):
        result = []
        worker = threading.Thread(
            target=lambda: result.append(
                self.manager._wait_for_captcha(self.job, {"reason": "captcha", "url": "u"})
            ),
            daemon=True,
        )
        worker.start()
        self.assertTrue(wait_until(lambda: self.job["paused"]))
        self.assertEqual(self.job["status"], "captcha")

        self.assertTrue(self.manager.resume(self.job["id"]))
        worker.join(timeout=2)
        self.assertEqual(result, [True])
        self.assertEqual(self.job["status"], "running")

    def test_resume_without_pause_is_rejected(self):
        self.assertFalse(self.manager.resume(self.job["id"]))

    def test_finished_job_cannot_be_resumed_or_paused(self):
        # Отмена во время капчи: флаг paused мог остаться — статус не должен
        # «воскреснуть» в running.
        self.job.update(status="cancelled", paused=True)
        self.assertFalse(self.manager.resume(self.job["id"]))
        self.assertEqual(self.job["status"], "cancelled")
        self.assertFalse(self.manager.request_pause(self.job["id"]))


class TestAbandonedPause(unittest.TestCase):
    """Пауза без опросов не держит задачу вечно (вкладку закрыли на капче)."""

    def setUp(self):
        self.manager = JobManager()
        self.job = add_job(self.manager)
        self.addCleanup(self.manager.cancel, self.job["id"])

    def wait_in_thread(self):
        result = []
        worker = threading.Thread(
            target=lambda: result.append(
                self.manager._wait_for_captcha(self.job, {"reason": "captcha", "url": "u"})
            ),
            daemon=True,
        )
        worker.start()
        return worker, result

    def test_unpolled_pause_cancels_itself(self):
        with patch.object(webapp, "ABANDON_AFTER", 0.05):
            worker, result = self.wait_in_thread()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive(), "пауза без опросов не закончилась")
        self.assertEqual(result, [False])
        self.assertTrue(self.job["cancel"])
        self.assertIn("брошена", self.job["log"][-1])

    def test_polling_keeps_pause_alive(self):
        with patch.object(webapp, "ABANDON_AFTER", 0.3):
            worker, result = self.wait_in_thread()
            self.assertTrue(wait_until(lambda: self.job["paused"]))
            deadline = time.monotonic() + 0.8
            while time.monotonic() < deadline:
                self.manager.snapshot(self.job["id"])  # вкладка открыта
                time.sleep(0.05)
            self.assertTrue(worker.is_alive(), "опрашиваемую паузу бросили")
            self.assertFalse(self.job["cancel"])

            self.assertTrue(self.manager.resume(self.job["id"]))
            worker.join(timeout=2)
        self.assertEqual(result, [True])

    def test_abandoned_job_finishes_and_is_evictable(self):
        def search(job, params):
            # Как клиент: проверка не пройдена — запрос прерывается.
            if not self.manager._wait_for_captcha(job, {"reason": "captcha", "url": "u"}):
                raise webapp.Cancelled()

        self.manager._search = search
        with patch.object(webapp, "ABANDON_AFTER", 0.05):
            worker = threading.Thread(
                target=self.manager._run, args=(self.job,), daemon=True
            )
            worker.start()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        snap = self.manager.snapshot(self.job["id"])
        self.assertEqual(snap["status"], "cancelled")
        self.assertIn("задача брошена", snap["stop_reason"])
        self.assertFalse(snap["paused"])
        self.assertEqual(self.manager.count()["active"], 0)
        with patch.object(webapp, "JOB_RETENTION", 0), self.manager._lock:
            self.manager._evict_old()
        self.assertIsNone(self.manager.get(self.job["id"]))

    def test_user_cancel_keeps_its_own_reason(self):
        def search(job, params):
            job["cancel"] = True
            raise webapp.Cancelled()

        self.manager._search = search
        self.manager._run(self.job)
        self.assertEqual(self.job["stop_reason"], "остановлено пользователем")


class _RecordingJob(dict):
    """Задача, запоминающая порядок записи полей."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order: list = []

    def __setitem__(self, key, value):
        self.order.append(key)
        super().__setitem__(key, value)


class TestFinalSnapshot(unittest.TestCase):
    """Фронтенд перестаёт опрашивать на первом финальном статусе."""

    def run_job(self, search):
        manager = JobManager()
        job = _RecordingJob(JobManager._new_job({"brand": "nike"}))
        manager._jobs[job["id"]] = job
        manager._search = search
        manager._run(job)
        return manager, job

    def assert_status_written_last(self, job):
        self.assertEqual(job.order[-1], "status")
        for key in ("finished_at", "stop_reason", "activity"):
            self.assertIn(key, job.order)

    def test_done_status_is_published_after_other_fields(self):
        manager, job = self.run_job(lambda job, params: None)
        self.assert_status_written_last(job)
        snap = manager.snapshot(job["id"])
        self.assertEqual(snap["status"], "done")
        self.assertIsNotNone(snap["finished_at"])
        self.assertTrue(snap["stop_reason"].startswith("готово"))
        self.assertEqual(snap["activity"], snap["stop_reason"])

    def test_error_status_is_published_after_error_text(self):
        def search(job, params):
            raise ValueError("бренд «x» не найден")

        _, job = self.run_job(search)
        self.assert_status_written_last(job)
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["error"], "бренд «x» не найден")
        self.assertEqual(job["stop_reason"], "ошибка")

    def test_cancel_during_pause_clears_pause_state(self):
        from poizon_parser.client import Cancelled

        def search(job, params):
            job.update(
                cancel=True, paused=True, status="captcha",
                captcha={"url": "u", "reason": "captcha", "since": 0},
                pause_requested={"reason": "manual"},
            )
            raise Cancelled()

        manager, job = self.run_job(search)
        snap = manager.snapshot(job["id"])
        self.assertEqual(snap["status"], "cancelled")
        self.assertFalse(snap["paused"])
        self.assertIsNone(snap["captcha"])
        self.assertFalse(snap["pause_requested"])


class TestReportSelection(unittest.TestCase):
    """Какие строки и параметры попадают в HTML-отчёт."""

    ROWS = [
        {"spu_id": 1, "sku_id": 10, "title": "A"},
        {"spu_id": 2, "sku_id": 20, "title": "B"},
        {"spu_id": 3, "sku_id": 30, "title": "C"},
    ]

    def job(self, **overrides):
        job = JobManager._new_job(
            {"brand": "nike", "size": "26.5", "scale": "CM", "gender": "women"}
        )
        job.update(matches=list(self.ROWS), brand={"name": "Nike"}, **overrides)
        return job

    def assert_rejected(self, body, job, status):
        with self.assertRaises(ReportRequestError) as ctx:
            select_report_matches(body, job)
        self.assertEqual(ctx.exception.status, status)
        return str(ctx.exception)

    def test_empty_filtered_list_is_not_replaced_by_all_results(self):
        message = self.assert_rejected({"matches": []}, self.job(), 400)
        self.assertIn("нет результатов", message)

    def test_keys_resolve_rows_from_job_in_given_order(self):
        rows = select_report_matches(
            {"keys": [{"spu_id": 3, "sku_id": 30}, {"spu_id": 1, "sku_id": 10}]},
            self.job(),
        )
        self.assertEqual([row["title"] for row in rows], ["C", "A"])

    def test_keys_without_job_ask_for_full_rows(self):
        self.assert_rejected({"keys": [{"spu_id": 1, "sku_id": 10}]}, None, 404)

    def test_unknown_key_is_conflict(self):
        self.assert_rejected({"keys": [{"spu_id": 9, "sku_id": 99}]}, self.job(), 409)

    def test_empty_or_malformed_keys_rejected(self):
        self.assert_rejected({"keys": []}, self.job(), 400)
        self.assert_rejected({"keys": ["1|10"]}, self.job(), 400)

    def test_posted_matches_still_supported(self):
        rows = select_report_matches({"matches": [self.ROWS[1]]}, None)
        self.assertEqual(rows, [self.ROWS[1]])

    def test_job_only_request_uses_all_results(self):
        self.assertEqual(len(select_report_matches({}, self.job())), 3)
        self.assertEqual(len(select_report_matches({"matches": None}, self.job())), 3)
        self.assert_rejected({}, None, 400)

    def test_meta_comes_from_job_not_from_edited_form(self):
        meta = report_meta(
            {"brand": "nik", "size": "27", "gender": "men", "scale": "EU"},
            self.job(),
        )
        self.assertEqual(
            meta,
            {"brand": "Nike", "size_input": "26.5", "scale": "CM", "gender": "women"},
        )

    def test_meta_falls_back_to_body_without_job(self):
        meta = report_meta({"brand": "Nike", "size": "27", "gender": "women"}, None)
        self.assertEqual(
            meta,
            {"brand": "Nike", "size_input": "27", "scale": "CM", "gender": "women"},
        )


class TestRunServer(unittest.TestCase):
    def test_wildcard_host_opens_loopback(self):
        self.assertEqual(local_url("0.0.0.0", 8765), "http://127.0.0.1:8765/")
        self.assertEqual(local_url("192.168.1.5", 80), "http://192.168.1.5:80/")

    def test_run_server_on_all_interfaces(self):
        app = MagicMock(server_port=8765)
        app.serve_forever.side_effect = KeyboardInterrupt
        out = io.StringIO()
        with patch.object(webapp, "App", return_value=app), \
                patch.object(webapp.threading, "Timer",
                             side_effect=lambda _delay, fn: MagicMock(start=fn)), \
                patch.object(webapp.webbrowser, "open") as open_browser, \
                redirect_stdout(out):
            webapp.run_server(host="0.0.0.0", port=8765)

        open_browser.assert_called_once_with("http://127.0.0.1:8765/")
        self.assertIn("http://127.0.0.1:8765/", out.getvalue())
        self.assertIn("все сетевые интерфейсы", out.getvalue())
        app.server_close.assert_called_once()


class TestSizeCalculator(unittest.TestCase):
    def test_sizes_for_foot_nike(self):
        result = sizes_for_foot("nike", 26.2, "men")
        self.assertEqual(result["eu"], 42.5)
        self.assertEqual(result["us"], 9.0)
        self.assertTrue(result["exact"])

    def test_unknown_brand_returns_none(self):
        self.assertIsNone(sizes_for_foot("vans", 26.2))

    def test_brand_without_foot_column_returns_none(self):
        # У Puma официальная таблица есть, но замера стопы в ней нет.
        self.assertIsNone(sizes_for_foot("puma", 26.2))

    def test_out_of_range_returns_none(self):
        self.assertIsNone(sizes_for_foot("nike", 8.0))

    def test_compare_covers_brands_with_foot_column(self):
        rows = compare_brands(26.2, "men")
        names = {r["brand"] for r in rows}
        self.assertEqual(
            names, {"Nike", "Adidas", "New Balance", "ASICS", "Reebok"}
        )
        # Puma сравнивать не с чем: длину стопы она не публикует.
        self.assertNotIn("Puma", names)

    def test_compare_shows_brand_differences(self):
        rows = {r["brand"]: r["eu"] for r in compare_brands(29.6, "men")}
        # Крупный размер: Nike 47,5 vs Adidas 48 — таблицы расходятся.
        self.assertNotEqual(rows["Nike"], rows["Adidas"])


if __name__ == "__main__":
    unittest.main()
