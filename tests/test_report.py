"""Тесты генерации HTML-отчёта."""

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from poizon_parser import report
from poizon_parser.report import (
    _fetch_data_uri,
    build_report_html,
    slugify,
    write_report,
)

MATCHES = [
    {
        "title": "New Balance NB 530 Сетчатая ткань",
        "url": "https://www.thepoizon.ru/product/x-123",
        "image": "https://cdn-img.thepoizon.ru/pro-img/a.jpg",
        "price": 6800.0, "price_text": "6 800 ₽", "delivery": "3-5 дней",
        "sizes": {"RU": "41,5", "EU": "42,5"}, "converted_eu": 42.5,
        "converted_cm": 27.0, "converted_foot": 27.0,
        "exact_conversion": True,
        "size_tip": "Размер больше, возьмите -0,5", "spu_id": 123, "sku_id": 1,
    },
    {
        "title": 'Кроссовки <script>alert("x")</script> & кавычки "тест"',
        "url": "https://www.thepoizon.ru/product/y-456",
        "image": "", "price": 9900.0, "price_text": "9 900 ₽",
        "delivery": "21-25 дней", "sizes": {"RU": "41,5", "EU": "42,5"},
        "converted_eu": 42.5, "exact_conversion": False, "spu_id": 456, "sku_id": 2,
    },
]
META = {"brand": "New Balance", "size_input": "26,2", "scale": "CM", "gender": "men"}


class TestBuildHtml(unittest.TestCase):
    def setUp(self):
        self.html = build_report_html(MATCHES, META)

    def test_is_full_document(self):
        self.assertTrue(self.html.lstrip().startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", self.html)

    def test_self_contained_no_external_css(self):
        # Стили встроены, без внешних ссылок.
        self.assertIn("<style>", self.html)
        self.assertNotIn('rel="stylesheet"', self.html)

    def test_shows_brand_and_prices(self):
        self.assertIn("New Balance", self.html)
        self.assertIn("6 800 ₽", self.html)
        self.assertIn("9 900 ₽", self.html)

    def test_shows_size_and_labels(self):
        self.assertIn("RU 41,5 / EU 42,5", self.html)
        self.assertIn("стопа 27 см", self.html)
        self.assertNotIn("ярлык", self.html)

    def test_links_to_poizon(self):
        self.assertIn("https://www.thepoizon.ru/product/x-123", self.html)
        self.assertIn("Открыть на POIZON", self.html)

    def test_escapes_html_in_titles(self):
        # Опасный ввод не должен попасть как исполняемый тег.
        self.assertNotIn("<script>alert", self.html)
        self.assertIn("&lt;script&gt;", self.html)

    def test_approx_marker_shown(self):
        self.assertIn("≈ перевод", self.html)

    def test_no_image_uses_placeholder(self):
        self.assertIn("👟", self.html)

    def test_price_range_in_summary(self):
        self.assertIn("6 800", self.html)
        self.assertIn("9 900", self.html)

    def test_empty_matches_still_valid(self):
        html = build_report_html([], {"brand": "Nike"})
        self.assertIn("Nike", html)
        self.assertIn("</html>", html)


class TestUntrustedInput(unittest.TestCase):
    """Результаты для отчёта присылает браузер — им нельзя доверять."""

    def card(self, **overrides):
        return build_report_html([{**MATCHES[0], **overrides}], META)

    def test_javascript_url_is_neutralized(self):
        html = self.card(url="javascript:alert(1)")
        self.assertNotIn("javascript:", html)
        self.assertIn('href="#"', html)

    def test_relative_product_path_points_to_site(self):
        html = self.card(url="/product/x-123")
        self.assertIn('href="https://www.thepoizon.ru/product/x-123"', html)

    def test_malformed_data_uri_image_is_dropped(self):
        html = self.card(image='data:image/png;base64,AAAA"><script>alert(1)</script>')
        self.assertNotIn("<script>alert", html)
        self.assertIn("👟", html)

    def test_valid_data_uri_image_is_kept(self):
        html = self.card(image="data:image/webp;base64,UklGRg==")
        self.assertIn('src="data:image/webp;base64,UklGRg=="', html)

    def test_non_web_image_scheme_is_dropped(self):
        html = self.card(image="file:///etc/passwd")
        self.assertNotIn("file:", html)

    def test_string_and_garbage_numbers_do_not_crash(self):
        html = build_report_html(
            [
                {**MATCHES[0], "price": "6800"},
                {**MATCHES[1], "price": "дорого", "converted_eu": "x"},
                {**MATCHES[1], "price": float("nan"), "title": 42},
            ],
            META,
        )
        self.assertIn('data-price="6800"', html)
        self.assertIn("</html>", html)

    def test_only_site_cdn_images_are_downloaded(self):
        with patch("poizon_parser.report._open_image") as open_image:
            self.assertIsNone(_fetch_data_uri("file:///etc/passwd#x-oss-process"))
            self.assertIsNone(_fetch_data_uri("http://127.0.0.1:8765/api/picks"))
            self.assertIsNone(_fetch_data_uri("https://thepoizon.ru.evil.example/a.jpg"))
            self.assertIsNone(_fetch_data_uri("https://[broken/a.jpg"))
        open_image.assert_not_called()

    def test_plain_http_cdn_image_is_not_downloaded(self):
        # Ответ по открытому http может подменить кто угодно на пути запроса.
        with patch("poizon_parser.report._open_image") as open_image:
            self.assertIsNone(
                _fetch_data_uri("http://cdn-img.thepoizon.ru/pro-img/a.jpg")
            )
        open_image.assert_not_called()

    def test_cdn_image_is_embedded(self):
        response = MagicMock()
        response.read.return_value = b"\x89PNG"
        response.headers.get_content_type.return_value = "image/png"
        open_image = MagicMock()
        open_image.return_value.__enter__.return_value = response
        with patch("poizon_parser.report._open_image", open_image):
            data = _fetch_data_uri("https://cdn-img.thepoizon.ru/pro-img/a.jpg")
        self.assertEqual(data, "data:image/png;base64,iVBORw==")

    def test_non_image_response_is_not_embedded(self):
        response = MagicMock()
        response.read.return_value = b"<html>"
        response.headers.get_content_type.return_value = "text/html"
        open_image = MagicMock()
        open_image.return_value.__enter__.return_value = response
        with patch("poizon_parser.report._open_image", open_image):
            self.assertIsNone(
                _fetch_data_uri("https://cdn-img.thepoizon.ru/pro-img/a.jpg")
            )

    def test_redirect_to_disallowed_scheme_is_refused(self):
        # Каждый шаг редиректа проверяется заново: с https на http — нельзя.
        handler = report._AllowlistRedirectHandler()
        request = report.urllib.request.Request("https://cdn.dewucdn.com/a.jpg")
        for target in (
            "http://cdn.dewucdn.com/a.jpg",
            "https://127.0.0.1/a.jpg",
            "file:///etc/passwd",
        ):
            with self.subTest(target=target):
                self.assertIsNone(
                    handler.redirect_request(request, None, 302, "Found", {}, target)
                )
        allowed = handler.redirect_request(
            request, None, 302, "Found", {}, "https://img.dewucdn.com/b.jpg"
        )
        self.assertEqual(allowed.full_url, "https://img.dewucdn.com/b.jpg")


class _LoopbackHandler(BaseHTTPRequestHandler):
    """Петлевой сервер: /img — картинка, /to?u=<url> — 302 на u."""

    hits: list = []

    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802 — API stdlib
        type(self).hits.append(self.path)
        if self.path.startswith("/to"):
            from urllib.parse import parse_qs, urlsplit

            target = parse_qs(urlsplit(self.path).query)["u"][0]
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"SECRET-IMAGE"
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestImageRedirects(unittest.TestCase):
    """Список разрешённых хостов проверяется на каждом шаге редиректа.

    Только петлевые серверы: «CDN» здесь — 127.0.0.1 (подставлен в
    _IMAGE_HOSTS), а «внутренний» адрес — localhost, его в списке нет.
    """

    def start_server(self):
        handler = type("Handler", (_LoopbackHandler,), {"hits": []})
        server = HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, handler

    def setUp(self):
        patches = (
            patch.object(report, "_IMAGE_HOSTS", ("127.0.0.1",)),
            patch.object(report, "_IMAGE_SCHEMES", ("http", "https")),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # Прокси из окружения не должен перехватывать петлевые запросы.
        no_proxy = patch.dict(
            "os.environ", {"no_proxy": "*", "NO_PROXY": "*"}, clear=False
        )
        no_proxy.start()
        self.addCleanup(no_proxy.stop)

    def test_redirect_off_allowlist_is_not_followed(self):
        cdn, _ = self.start_server()
        internal, internal_handler = self.start_server()
        secret = f"http://localhost:{internal.server_port}/img"
        url = f"http://127.0.0.1:{cdn.server_port}/to?u={secret}"

        self.assertIsNone(_fetch_data_uri(url))
        self.assertEqual(internal_handler.hits, [])

    def test_redirect_within_allowlist_still_works(self):
        cdn, handler = self.start_server()
        target = f"http://127.0.0.1:{cdn.server_port}/img"
        url = f"http://127.0.0.1:{cdn.server_port}/to?u={target}"

        data = _fetch_data_uri(url)

        self.assertEqual(data, "data:image/png;base64,U0VDUkVULUlNQUdF")
        self.assertEqual(len(handler.hits), 2)


class TestSlugify(unittest.TestCase):
    def test_spaces_and_case(self):
        self.assertEqual(slugify("New Balance"), "new-balance")

    def test_cyrillic_stripped(self):
        self.assertEqual(slugify("Найк"), "poizon")  # без латиницы → дефолт

    def test_empty(self):
        self.assertEqual(slugify(""), "poizon")


class TestWriteReport(unittest.TestCase):
    def test_creates_folder_with_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_report(MATCHES, META, base_dir=tmp)
            self.assertTrue(out.is_dir())
            index = out / "index.html"
            self.assertTrue(index.is_file())
            self.assertIn("New Balance", index.read_text(encoding="utf-8"))

    def test_folder_name_has_brand_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_report(MATCHES, META, base_dir=tmp)
            self.assertIn("new-balance", out.name)
            self.assertIn("26-2", out.name)

    def test_size_cannot_create_nested_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = write_report(MATCHES, {**META, "size_input": "../../x\\y"}, base_dir=tmp)
            self.assertEqual(out.parent.resolve(), Path(tmp).resolve())

    def test_separate_folders_per_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = write_report(MATCHES, META, base_dir=tmp)
            b = write_report(MATCHES, {**META, "brand": "Nike"}, base_dir=tmp)
            c = write_report(MATCHES, META, base_dir=tmp)
            self.assertEqual(len({a, b, c}), 3)
            for out in (a, b, c):
                self.assertTrue((out / "index.html").is_file())
            self.assertIn("Nike", (b / "index.html").read_text(encoding="utf-8"))

    def test_same_second_reports_get_numbered_folders(self):
        # Два отчёта за одну секунду раньше писали в одну папку (exist_ok).
        with tempfile.TemporaryDirectory() as tmp, \
                patch("poizon_parser.report.time.strftime", return_value="20260101-120000"):
            a = write_report(MATCHES, META, base_dir=tmp)
            b = write_report(MATCHES, META, base_dir=tmp)
            c = write_report(MATCHES, META, base_dir=tmp)
        self.assertEqual(a.name, "new-balance-26-2cm-20260101-120000")
        self.assertEqual(b.name, a.name + "-2")
        self.assertEqual(c.name, a.name + "-3")

    def test_folder_name_reflects_scale(self):
        # Регрессия: EU 42 попадал в папку «42cm».
        cases = (
            ({"size_input": "42", "scale": "EU"}, "nike-eu-42"),
            ({"size_input": "9", "scale": "US M"}, "nike-us-m-9"),
            ({"size_input": "7,5", "scale": "US W"}, "nike-us-w-7-5"),
            ({"size_input": "8", "scale": "uk"}, "nike-uk-8"),
            ({"size_input": "26,5", "scale": "CM"}, "nike-26-5cm"),
            ({"size_input": "26,5", "scale": "СМ"}, "nike-26-5cm"),
            ({"size_input": "26.5"}, "nike-26-5cm"),
            ({"size_input": "265", "scale": "MM"}, "nike-265mm"),
            # Шкала уже в размере — не дублируется и главнее выбранной.
            ({"size_input": "EU 43", "scale": "EU"}, "nike-eu-43"),
            ({"size_input": "EU 43", "scale": "CM"}, "nike-eu-43"),
            ({"size_input": "US W 7", "scale": "EU"}, "nike-us-w-7"),
            # Голое «US» не перебивает выбранную женскую шкалу.
            ({"size_input": "US 7", "scale": "US W"}, "nike-us-w-7"),
            ({"size_input": "26,5 cm", "scale": "CM"}, "nike-26-5cm"),
            # Трети Adidas не теряются: EU 42⅔ — не папка «EU 42».
            ({"size_input": "42⅔", "scale": "EU"}, "nike-eu-42-2-3"),
            ({"size_input": "42 2/3", "scale": "EU"}, "nike-eu-42-2-3"),
            ({"scale": "EU"}, "nike"),
        )
        for extra, expected in cases:
            with self.subTest(meta=extra), tempfile.TemporaryDirectory() as tmp, \
                    patch("poizon_parser.report.time.strftime", return_value="STAMP"):
                out = write_report(MATCHES, {"brand": "Nike", **extra}, base_dir=tmp)
                self.assertEqual(out.name, f"{expected}-STAMP")

    def test_untrusted_scale_is_sanitized_in_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("poizon_parser.report.time.strftime", return_value="STAMP"):
            out = write_report(
                MATCHES,
                {"brand": "Nike", "size_input": "42", "scale": "../../x y"},
                base_dir=tmp,
            )
            self.assertEqual(out.parent.resolve(), Path(tmp).resolve())
            self.assertEqual(out.name, "nike-x-y-42-STAMP")


if __name__ == "__main__":
    unittest.main()
