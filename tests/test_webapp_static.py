"""Интеграционные тесты раздачи production-фронтенда."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from poizon_parser import webapp
from poizon_parser.catalog import Brand


class TestFrontendStaticFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.dist = self.root / "frontend" / "dist"
        self.assets = self.dist / "assets"
        self.assets.mkdir(parents=True)
        (self.dist / "index.html").write_text(
            "<!doctype html><title>vite build</title>",
            encoding="utf-8",
        )
        (self.assets / "app-a1b2c3.js").write_text(
            "globalThis.viteBuild = true;",
            encoding="utf-8",
        )
        (self.assets / "app-d4e5f6.css").write_text(
            "body { color: green; }",
            encoding="utf-8",
        )

        self.legacy = self.root / "web"
        self.legacy.mkdir()
        (self.legacy / "index.html").write_text(
            "<!doctype html><title>legacy</title>",
            encoding="utf-8",
        )

        self.dist_patch = patch.object(webapp, "FRONTEND_DIST", self.dist)
        self.web_patch = patch.object(webapp, "WEB_DIR", self.legacy)
        self.dist_patch.start()
        self.web_patch.start()

        self.server = webapp.App(("127.0.0.1", 0))
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.web_patch.stop()
        self.dist_patch.stop()
        self.temp_dir.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.server.server_port,
            timeout=3,
        )
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
        connection.close()
        return result

    def test_root_serves_vite_index_without_caching(self) -> None:
        status, headers, body = self.request("GET", "/")

        self.assertEqual(status, 200)
        self.assertIn(b"vite build", body)
        self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertRegex(
            headers["set-cookie"],
            r"^poizon_uid=[0-9a-f]{32}; Path=/; "
            r"HttpOnly; Max-Age=31536000; SameSite=Lax$",
        )

    def test_existing_uid_cookie_is_preserved(self) -> None:
        status, headers, _ = self.request(
            "GET",
            "/index.html",
            headers={"Cookie": f"poizon_uid={'ab12' * 8}"},
        )

        self.assertEqual(status, 200)
        self.assertNotIn("set-cookie", headers)

    def test_malformed_uid_cookie_is_replaced(self) -> None:
        # Мусор в cookie сводился бы к общему файлу итогов — выдаём новый uid.
        status, headers, _ = self.request(
            "GET",
            "/index.html",
            headers={"Cookie": "poizon_uid=existing-user"},
        )

        self.assertEqual(status, 200)
        self.assertRegex(headers["set-cookie"], r"^poizon_uid=[0-9a-f]{32};")

    def use_temp_picks(self) -> Path:
        picks_dir = self.root / "picks"
        self.server.picks = webapp.PickStore(picks_dir)
        return picks_dir

    @staticmethod
    def cookie_uid(headers: dict[str, str]) -> str:
        return headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]

    def test_requests_without_cookie_never_touch_shared_bucket(self) -> None:
        picks_dir = self.use_temp_picks()
        picks_dir.mkdir()
        shared = picks_dir / "anon.json"
        shared.write_text(
            json.dumps([{"id": "old", "match": {"spu_id": 1}, "query": {}}]),
            encoding="utf-8",
        )

        status, headers, body = self.request("GET", "/api/picks")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["items"], [])
        self.assertIn("set-cookie", headers)

        status, headers, body = self.request(
            "POST",
            "/api/picks",
            body=b'{"match": {"spu_id": 7, "sku_id": 8}, "query": {}}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        uid = self.cookie_uid(headers)
        # Позиция записана тому uid, который ушёл в cookie этого же ответа.
        self.assertTrue((picks_dir / f"{uid}.json").is_file())
        self.assertEqual(len(json.loads(shared.read_text(encoding="utf-8"))), 1)

        _, _, body = self.request(
            "GET", "/api/picks", headers={"Cookie": f"poizon_uid={uid}"}
        )
        items = json.loads(body)["items"]
        self.assertEqual([item["match"]["spu_id"] for item in items], [7])

    def test_missing_pick_delete_is_explained(self) -> None:
        self.use_temp_picks()
        status, _, body = self.request(
            "DELETE",
            "/api/picks/abc",
            headers={"Cookie": f"poizon_uid={'ab12' * 8}"},
        )
        self.assertEqual(status, 404)
        payload = json.loads(body)
        self.assertFalse(payload["ok"])
        self.assertIn("уже нет", payload["error"])

    def add_job(self, **overrides) -> dict:
        job = webapp.JobManager._new_job(
            {"brand": "nike", "size": "26.5", "scale": "CM", "gender": "men"}
        )
        job.update(overrides)
        self.server.jobs._jobs[job["id"]] = job
        return job

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        status, _, body = self.request(
            "POST",
            path,
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        return status, json.loads(body)

    def test_job_actions_explain_refusals(self) -> None:
        status, payload = self.post_json("/api/search/nope/cancel", {})
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])
        self.assertIn("задача не найдена", payload["error"])

        job = self.add_job()
        self.addCleanup(self.server.jobs.cancel, job["id"])
        status, payload = self.post_json(f"/api/search/{job['id']}/continue", {})
        self.assertEqual(status, 409)
        self.assertIn("не на паузе", payload["error"])

        # Ручную паузу, которая ещё не сработала, можно отозвать.
        self.assertEqual(self.post_json(f"/api/search/{job['id']}/pause", {})[0], 200)
        status, payload = self.post_json(f"/api/search/{job['id']}/continue", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIsNone(job["pause_requested"])

        job["status"] = "done"
        status, payload = self.post_json(f"/api/search/{job['id']}/pause", {})
        self.assertEqual(status, 409)
        self.assertIn("завершён", payload["error"])

    def test_report_with_empty_filtered_list_is_rejected(self) -> None:
        job = self.add_job(status="done", matches=[{"spu_id": 1, "sku_id": 2}])
        with patch.object(webapp, "write_report") as write_report:
            status, payload = self.post_json(
                "/api/report", {"jobId": job["id"], "matches": []}
            )
        self.assertEqual(status, 400)
        self.assertIn("нет результатов", payload["error"])
        write_report.assert_not_called()

    def test_report_by_keys_uses_job_rows_and_params(self) -> None:
        rows = [
            {"spu_id": 1, "sku_id": 10, "title": "A"},
            {"spu_id": 2, "sku_id": 20, "title": "B"},
        ]
        job = self.add_job(status="done", matches=rows, brand={"name": "Nike"})
        out_dir = self.root / "result" / "nike-26-5cm"
        with patch.object(webapp, "write_report", return_value=out_dir) as write_report:
            status, payload = self.post_json(
                "/api/report",
                {
                    "jobId": job["id"],
                    "keys": [{"spu_id": 2, "sku_id": 20}, {"spu_id": 1, "sku_id": 10}],
                    # Форму поправили после поиска — в отчёт это не попадает.
                    "size": "27",
                    "gender": "women",
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["view"], "/result/nike-26-5cm/index.html")
        source, meta = write_report.call_args[0]
        self.assertEqual([row["title"] for row in source], ["B", "A"])
        self.assertEqual(meta["size_input"], "26.5")
        self.assertEqual(meta["gender"], "men")
        self.assertEqual(meta["brand"], "Nike")

    def test_report_keys_for_lost_job_return_404(self) -> None:
        status, payload = self.post_json(
            "/api/report",
            {"jobId": "gone", "keys": [{"spu_id": 1, "sku_id": 10}]},
        )
        self.assertEqual(status, 404)
        self.assertIn("задача не найдена", payload["error"])

    def test_hashed_assets_have_mime_and_immutable_cache(self) -> None:
        cases = (
            ("app-a1b2c3.js", "text/javascript; charset=utf-8"),
            ("app-d4e5f6.css", "text/css; charset=utf-8"),
        )
        for name, expected_type in cases:
            with self.subTest(name=name):
                status, headers, body = self.request(
                    "GET",
                    f"/assets/{name}?v=ignored",
                )
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertEqual(headers["content-type"], expected_type)
                self.assertEqual(
                    headers["cache-control"],
                    "public, max-age=31536000, immutable",
                )
                self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_asset_path_cannot_escape_assets_directory(self) -> None:
        secret = self.dist / "secret.js"
        secret.write_text("do not expose", encoding="utf-8")

        status, _, body = self.request(
            "GET",
            "/assets/%2e%2e/secret.js",
        )

        self.assertEqual(status, 403)
        self.assertNotIn(b"do not expose", body)

    def test_missing_dist_falls_back_to_legacy_page(self) -> None:
        with patch.object(webapp, "FRONTEND_DIST", self.root / "missing-dist"):
            status, headers, body = self.request("GET", "/")

        self.assertEqual(status, 200)
        self.assertIn(b"legacy", body)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("set-cookie", headers)

    def test_api_route_is_not_shadowed_by_frontend(self) -> None:
        status, headers, body = self.request("GET", "/api/health")

        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("set-cookie", headers)
        self.assertIn("HttpOnly", headers["set-cookie"])
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_brands_api_marks_official_size_charts(self) -> None:
        brands = [
            Brand(brand_id=1, name="Nike", url="/brand/nike"),
            Brand(
                brand_id=2,
                name="Adidas Originals",
                url="/brand/adidas-originals",
            ),
            Brand(brand_id=3, name="Puma", url="/brand/puma"),
        ]
        with (
            patch.object(webapp, "PoizonClient"),
            patch.object(webapp, "Catalog") as catalog_class,
        ):
            catalog_class.return_value.brands.return_value = brands
            status, _, body = self.request("GET", "/api/brands")

        self.assertEqual(status, 200)
        payload = json.loads(body)["brands"]
        by_name = {brand["name"]: brand for brand in payload}
        self.assertTrue(by_name["Nike"]["has_official_size_chart"])
        self.assertEqual(by_name["Nike"]["size_chart_brand"], "Nike")
        self.assertTrue(
            by_name["Nike"]["size_chart_source"].startswith("http")
        )
        self.assertTrue(
            by_name["Adidas Originals"]["has_official_size_chart"]
        )
        self.assertEqual(
            by_name["Adidas Originals"]["size_chart_brand"], "Adidas"
        )
        self.assertFalse(by_name["Puma"]["has_official_size_chart"])
        self.assertIsNone(by_name["Puma"]["size_chart_brand"])
        self.assertIsNone(by_name["Puma"]["size_chart_source"])

    def test_result_route_is_not_shadowed_by_frontend(self) -> None:
        result_dir = self.root / "result"
        report = result_dir / "report-1" / "index.html"
        report.parent.mkdir(parents=True)
        report.write_text("<h1>report</h1>", encoding="utf-8")

        with patch.object(webapp, "RESULT_DIR", result_dir):
            status, headers, body = self.request(
                "GET",
                "/result/report-1/index.html",
            )

        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
        self.assertIn(b"report", body)
        # Отчёт открывается в песочнице: его скрипты не видят API приложения.
        self.assertIn("sandbox", headers["content-security-policy"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_cross_site_post_is_rejected(self) -> None:
        port = self.server.server_port
        for origin in ("https://evil.example", "null", f"http://127.0.0.1:{port + 1}"):
            with self.subTest(origin=origin):
                status, _, body = self.request(
                    "POST",
                    "/api/picks",
                    body=b'{"match": {"spu_id": 1}}',
                    headers={"Content-Type": "text/plain", "Origin": origin},
                )
                self.assertEqual(status, 403)
                self.assertIn("другого сайта", json.loads(body)["error"])

    def test_cross_site_delete_is_rejected(self) -> None:
        status, _, _ = self.request(
            "DELETE", "/api/picks", headers={"Origin": "https://evil.example"}
        )
        self.assertEqual(status, 403)

    def test_same_origin_post_is_allowed(self) -> None:
        port = self.server.server_port
        with patch.object(self.server, "picks") as picks:
            picks.add.return_value = ({"id": "x"}, True)
            status, _, body = self.request(
                "POST",
                "/api/picks",
                body=b'{"match": {"spu_id": 1}}',
                headers={
                    "Content-Type": "application/json",
                    "Origin": f"http://127.0.0.1:{port}",
                },
            )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["created"])

    def test_report_rejects_non_object_matches(self) -> None:
        status, _, body = self.request(
            "POST",
            "/api/report",
            body=b'{"matches": ["x", 1]}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("matches", json.loads(body)["error"])

    def test_unexpected_error_returns_json_500(self) -> None:
        with patch.object(self.server.jobs, "count", side_effect=RuntimeError("boom")), \
                patch("traceback.print_exc"):
            status, headers, body = self.request("GET", "/api/health")
        self.assertEqual(status, 500)
        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        self.assertIn("внутренняя", json.loads(body)["error"])

    def test_oversized_json_body_is_rejected(self) -> None:
        with patch.object(webapp, "MAX_JSON_BODY", 32):
            status, headers, body = self.request(
                "POST",
                "/api/search",
                body=b"x" * 33,
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(status, 413)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("слишком большое", json.loads(body)["error"])


if __name__ == "__main__":
    unittest.main()
