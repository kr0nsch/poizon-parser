"""Тесты генерации HTML-отчёта."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        with patch("poizon_parser.report.urllib.request.urlopen") as urlopen:
            self.assertIsNone(_fetch_data_uri("file:///etc/passwd#x-oss-process"))
            self.assertIsNone(_fetch_data_uri("http://127.0.0.1:8765/api/picks"))
            self.assertIsNone(_fetch_data_uri("https://thepoizon.ru.evil.example/a.jpg"))
        urlopen.assert_not_called()

    def test_cdn_image_is_embedded(self):
        response = MagicMock()
        response.read.return_value = b"\x89PNG"
        response.headers.get_content_type.return_value = "image/png"
        urlopen = MagicMock()
        urlopen.return_value.__enter__.return_value = response
        with patch("poizon_parser.report.urllib.request.urlopen", urlopen):
            data = _fetch_data_uri("https://cdn-img.thepoizon.ru/pro-img/a.jpg")
        self.assertEqual(data, "data:image/png;base64,iVBORw==")

    def test_non_image_response_is_not_embedded(self):
        response = MagicMock()
        response.read.return_value = b"<html>"
        response.headers.get_content_type.return_value = "text/html"
        urlopen = MagicMock()
        urlopen.return_value.__enter__.return_value = response
        with patch("poizon_parser.report.urllib.request.urlopen", urlopen):
            self.assertIsNone(
                _fetch_data_uri("https://cdn-img.thepoizon.ru/pro-img/a.jpg")
            )


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
        import time
        with tempfile.TemporaryDirectory() as tmp:
            a = write_report(MATCHES, META, base_dir=tmp)
            time.sleep(1.05)  # имя папки содержит секунды
            b = write_report(MATCHES, META, base_dir=tmp)
            self.assertNotEqual(a.name, b.name)


if __name__ == "__main__":
    unittest.main()
