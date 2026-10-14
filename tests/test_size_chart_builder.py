"""Проверки детерминированного снимка официальных размерных таблиц."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import build_size_charts
from tools.build_size_charts import OUT, VERIFIED_AT, build_charts


class TestHardcodedOfficialCharts(unittest.TestCase):
    def test_builder_matches_committed_json_byte_for_data(self):
        committed = json.loads(OUT.read_text(encoding="utf-8"))
        self.assertEqual(build_charts(), committed)

    def test_every_chart_keeps_gender_sources_and_revision(self):
        for key, chart in build_charts().items():
            with self.subTest(key=key):
                self.assertEqual(chart["verified_at"], VERIFIED_AT[key])
                # Ссылки на мужскую и женскую сетки обязательны; у Reebok есть
                # ещё и отдельный источник замера стопы.
                self.assertLessEqual({"men", "women"}, set(chart["sources"]))
                for source in chart["sources"].values():
                    self.assertTrue(source.startswith("https://"))

    def test_verification_dates_are_iso(self):
        for key, date in VERIFIED_AT.items():
            with self.subTest(key=key):
                self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")


class _ScriptRun(unittest.TestCase):
    """Запуск main() на временной копии файла, с перехватом вывода."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "size_charts.json"
        patcher = mock.patch.object(build_size_charts, "OUT", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *argv, encoding="utf-8"):
        """(код, stdout, stderr). Потоки — как у консоли с заданной кодировкой."""
        out = io.TextIOWrapper(io.BytesIO(), encoding=encoding)
        err = io.TextIOWrapper(io.BytesIO(), encoding=encoding)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = build_size_charts.main(list(argv))
        texts = []
        for stream in (out, err):
            stream.flush()
            texts.append(stream.buffer.getvalue().decode(stream.encoding))
        return code, texts[0], texts[1]


class TestCheckMode(_ScriptRun):
    def test_committed_file_passes_and_is_not_touched(self):
        shutil.copyfile(OUT, self.path)
        before = self.path.read_bytes()
        code, out, _err = self.run_main("--check")
        self.assertEqual(code, 0)
        self.assertIn("актуален", out)
        self.assertEqual(self.path.read_bytes(), before)

    def test_crlf_line_endings_are_not_a_difference(self):
        # После checkout на Windows файл может прийти с CRLF — данные те же.
        text = build_size_charts.render(build_charts())
        self.path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        code, _out, _err = self.run_main("--check")
        self.assertEqual(code, 0)

    def test_stale_data_fails_without_writing(self):
        charts = build_charts()
        charts["nike"]["men"][0]["eu"] = 99.0
        stale = build_size_charts.render(charts).encode("utf-8")
        self.path.write_bytes(stale)
        code, _out, err = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("size_charts.json", err)
        self.assertEqual(self.path.read_bytes(), stale)

    def test_missing_file_fails(self):
        code, _out, err = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("не найден", err)
        self.assertFalse(self.path.exists())

    def test_broken_json_fails(self):
        self.path.write_text("{", encoding="utf-8")
        code, _out, _err = self.run_main("--check")
        self.assertEqual(code, 1)


class TestWriteMode(_ScriptRun):
    def test_output_is_lf_only_and_matches_committed_data(self):
        code, _out, _err = self.run_main()
        self.assertEqual(code, 0)
        raw = self.path.read_bytes()
        self.assertNotIn(b"\r\n", raw)
        self.assertTrue(raw.endswith(b"}\n"))
        self.assertEqual(
            json.loads(raw.decode("utf-8")),
            json.loads(OUT.read_text(encoding="utf-8")),
        )

    def test_output_is_byte_stable_between_runs(self):
        self.run_main()
        first = self.path.read_bytes()
        self.run_main()
        self.assertEqual(self.path.read_bytes(), first)

    def test_cp1252_console_does_not_crash(self):
        # Раньше print кириллицы на cp1252 (Windows CI) падал с
        # UnicodeEncodeError уже после записи файла.
        code, out, _err = self.run_main(encoding="cp1252")
        self.assertEqual(code, 0)
        self.assertIn("сохранено", out)
        code, out, _err = self.run_main("--check", encoding="cp1252")
        self.assertEqual(code, 0)
        self.assertIn("актуален", out)


if __name__ == "__main__":
    unittest.main()
