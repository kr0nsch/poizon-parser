"""Тесты стабильности и новых фич веб-сервера."""

import unittest

from poizon_parser.webapp import JobManager, validate_search
from poizon_parser.sizechart import compare_brands, sizes_for_foot


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


class TestSizeCalculator(unittest.TestCase):
    def test_sizes_for_foot_nike(self):
        result = sizes_for_foot("nike", 26.2, "men")
        self.assertEqual(result["eu"], 42.5)
        self.assertEqual(result["us"], 9.0)
        self.assertTrue(result["exact"])

    def test_unknown_brand_returns_none(self):
        self.assertIsNone(sizes_for_foot("puma", 26.2))

    def test_out_of_range_returns_none(self):
        self.assertIsNone(sizes_for_foot("nike", 8.0))

    def test_compare_covers_four_brands(self):
        rows = compare_brands(26.2, "men")
        self.assertEqual(len(rows), 4)
        names = {r["brand"] for r in rows}
        self.assertEqual(names, {"Nike", "Adidas", "New Balance", "ASICS"})

    def test_compare_shows_brand_differences(self):
        rows = {r["brand"]: r["eu"] for r in compare_brands(29.6, "men")}
        # Крупный размер: Nike 47,5 vs Adidas 48 — таблицы расходятся.
        self.assertNotEqual(rows["Nike"], rows["Adidas"])


if __name__ == "__main__":
    unittest.main()
