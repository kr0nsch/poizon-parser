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
            headers={"Cookie": "poizon_uid=existing-user"},
        )

        self.assertEqual(status, 200)
        self.assertNotIn("set-cookie", headers)

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
