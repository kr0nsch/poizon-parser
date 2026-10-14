"""Тесты командного интерфейса: аргументы, проверки ввода, вывод и ошибки.

Всё офлайн: сеть подменяется FakeFinder через cli._build_finder.
"""

import codecs
import errno
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from poizon_parser import __version__, cli
from poizon_parser.client import ChallengeRequired
from poizon_parser.finder import SizeFinder
from poizon_parser.models import Match, Product, SearchItem, SizeOffer
from poizon_parser.sizechart import SizeChart, load_brand_charts


def run_cli(argv):
    """main() с перехватом вывода → (код, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # ошибки argparse и --version
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def make_match(
    spu_id=1, price=9990.0, eu=43.3333, brand="Nike", tip="", requested=26.5
):
    offer = SizeOffer(
        sku_id=spu_id * 10,
        sizes={"RU": "42⅓", "EU": "43⅓"},
        price=price,
        price_text=f"{price:,.0f} ₽".replace(",", " ") if price else "",
        in_stock=True,
        delivery="10-20 дней",
    )
    product = Product(
        spu_id=spu_id, title=f"Кроссовки {spu_id}", url=f"/product/{spu_id}",
        brand=brand, size_tip=tip, offers=[offer],
    )
    return Match(
        product=product, offer=offer, matched_scale="EU",
        requested_size=requested, requested_scale="CM", converted_eu=eu,
    )


class FakeFinder:
    """Подмена SizeFinder: запоминает вызовы, в сеть не ходит."""

    def __init__(self, matches=(), product=None, error=None):
        self.matches = list(matches)
        self.product = product
        self.error = error
        self.calls = []

    def find_by_brand(self, **kwargs):
        self.calls.append(("find_by_brand", kwargs))
        if self.error is not None:
            raise self.error
        return list(self.matches)

    def find_in_official_brands(self, **kwargs):
        self.calls.append(("find_in_official_brands", kwargs))
        if kwargs.get("on_brand"):
            kwargs["on_brand"]("Nike", list(self.matches))
        return list(self.matches)

    def find(self, **kwargs):
        self.calls.append(("find", kwargs))
        return list(self.matches)

    def load_product(self, product):
        if self.error is not None:
            raise self.error
        return self.product


class CliCase(unittest.TestCase):
    def patch_finder(self, finder):
        patcher = mock.patch.object(cli, "_build_finder", return_value=finder)
        built = patcher.start()
        self.addCleanup(patcher.stop)
        return built

    def no_network(self):
        """_build_finder, который нельзя вызывать: ввод должен отсечься раньше."""
        return self.patch_finder(FakeFinder())


# ------------------------------------------------------------ аргументы


class TestGlobalFlags(unittest.TestCase):
    def setUp(self):
        self.parser = cli.build_parser()

    def test_flags_before_command(self):
        args = self.parser.parse_args(
            ["--delay", "5", "-v", "--no-cache", "--quiet", "size", "26"]
        )
        self.assertEqual(args.delay, 5.0)
        self.assertTrue(args.verbose)
        self.assertTrue(args.no_cache)
        self.assertTrue(args.quiet)

    def test_flags_after_command(self):
        args = self.parser.parse_args(
            ["shoes", "-b", "nike", "-s", "26", "--delay", "5", "-v", "--timeout", "9"]
        )
        self.assertEqual(args.delay, 5.0)
        self.assertTrue(args.verbose)
        self.assertEqual(args.timeout, 9.0)

    def test_defaults_without_flags(self):
        args = self.parser.parse_args(["size", "26"])
        self.assertEqual(args.delay, 0.7)
        self.assertEqual(args.timeout, 30.0)
        self.assertEqual(args.cache_ttl, 900.0)
        self.assertFalse(args.verbose)
        self.assertFalse(args.quiet)
        self.assertFalse(args.no_cache)

    def test_flag_after_command_wins(self):
        args = self.parser.parse_args(["--delay", "5", "size", "26", "--delay", "2"])
        self.assertEqual(args.delay, 2.0)

    def test_version(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)

    def test_prog_is_how_users_run_it(self):
        self.assertEqual(self.parser.prog, "python main.py")
        self.assertIn("python main.py", self.parser.format_usage())


class TestNumberArgs(unittest.TestCase):
    def assert_rejected(self, argv):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.build_parser().parse_args(argv)
        self.assertEqual(ctx.exception.code, 2)

    def test_negative_counts_rejected(self):
        self.assert_rejected(["shoes", "-b", "nike", "-s", "26", "-n", "-1"])
        self.assert_rejected(["shoes", "-b", "nike", "-s", "26", "--check", "-5"])
        self.assert_rejected(["shoes", "-b", "nike", "-s", "26", "-w", "0"])
        self.assert_rejected(["allbrands", "-s", "26", "--total", "-1"])
        self.assert_rejected(["allbrands", "-s", "26", "-w", "-2"])
        self.assert_rejected(["find", "-q", "x", "-s", "42", "-n", "0"])
        self.assert_rejected(["shoes", "-b", "nike", "-s", "26", "--max-price", "-100"])
        self.assert_rejected(["--delay", "-1", "size", "26"])

    def test_zero_means_unlimited_where_documented(self):
        args = cli.build_parser().parse_args(
            ["allbrands", "-s", "26", "--total", "0", "--check", "0"]
        )
        self.assertEqual((args.total, args.check), (0, 0))

    def test_port_range(self):
        self.assert_rejected(["web", "--port", "70000"])
        self.assert_rejected(["web", "--port", "0"])
        self.assertEqual(cli.build_parser().parse_args(["web", "--port", "8800"]).port, 8800)


class TestScaleArgs(unittest.TestCase):
    def parse(self, argv):
        return cli.build_parser().parse_args(argv)

    def test_shoes_scale_case_insensitive_with_aliases(self):
        base = ["shoes", "-b", "nike", "-s", "42"]
        self.assertEqual(self.parse(base + ["--scale", "eu"]).scale, "EU")
        self.assertEqual(self.parse(base + ["--scale", "us w"]).scale, "US W")
        self.assertEqual(self.parse(base + ["--scale", "US"]).scale, "US M")
        self.assertEqual(self.parse(base + ["--scale", "см"]).scale, "CM")
        self.assertEqual(self.parse(base).scale, "CM")

    def test_unknown_scale_rejected(self):
        for scale in ("JP", "US-W", "ЕУ", "cn"):
            with self.subTest(scale=scale), redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit):
                    self.parse(["shoes", "-b", "nike", "-s", "27", "--scale", scale])
            self.assertIn("неизвестная шкала", err.getvalue())

    def test_find_scale_only_poizon_scales_any_case(self):
        self.assertEqual(self.parse(["find", "-q", "x", "-s", "42", "--scale", "eu"]).scale, "EU")
        self.assertEqual(self.parse(["find", "-q", "x", "-s", "42", "--scale", "Ru"]).scale, "RU")
        for scale in ("US", "UK", "CN", "JP"):
            with self.subTest(scale=scale), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.parse(["find", "-q", "x", "-s", "42", "--scale", scale])


# ------------------------------------------------------ проверка размера


class TestShoesSizeValidation(CliCase):
    def test_cm_out_of_range_hints_eu(self):
        built = self.no_network()
        code, _, err = run_cli(["shoes", "-b", "nike", "-s", "42"])
        self.assertEqual(code, 2)
        self.assertIn("--scale EU", err)
        built.assert_not_called()

    def test_millimetres_hint(self):
        built = self.no_network()
        code, _, err = run_cli(["shoes", "-b", "nike", "-s", "265"])
        self.assertEqual(code, 2)
        self.assertIn("--scale MM", err)
        built.assert_not_called()

    def test_scale_inside_size_is_validated(self):
        built = self.no_network()
        code, _, err = run_cli(["shoes", "-b", "nike", "-s", "JP 27"])
        self.assertEqual(code, 2)
        self.assertIn("неизвестная шкала", err)
        built.assert_not_called()

    def test_valid_inputs_reach_finder(self):
        cases = [
            (["-s", "26,5"], 26.5, "CM"),
            (["-s", "42", "--scale", "eu"], 42.0, "EU"),
            (["-s", "EU 43"], 43.0, "EU"),
            (["-s", "9", "--scale", "us w"], 9.0, "US W"),
            (["-s", "265", "--scale", "MM"], 26.5, "CM"),
        ]
        for extra, size, scale in cases:
            with self.subTest(extra=extra):
                finder = FakeFinder()
                with mock.patch.object(cli, "_build_finder", return_value=finder):
                    code, _, _ = run_cli(["shoes", "-b", "nike", *extra])
                self.assertEqual(code, 1)  # ничего не нашлось — но поиск был
                kwargs = finder.calls[0][1]
                self.assertAlmostEqual(kwargs["size"], size)
                self.assertEqual(kwargs["scale"], scale)

    def test_allbrands_validates_size_too(self):
        built = self.no_network()
        code, _, err = run_cli(["allbrands", "-s", "42"])
        self.assertEqual(code, 2)
        self.assertIn("--scale EU", err)
        built.assert_not_called()

    def test_bare_us_keeps_explicit_gendered_scale(self):
        # Регрессия: голое «US» из -s перебивало --scale "US W" → мужской US 7.
        self.assertEqual(cli._foot_size("US 7", "US W"), (7.0, "US W"))
        self.assertEqual(cli._foot_size("US 7", "US M"), (7.0, "US M"))
        self.assertEqual(cli._foot_size("US 7", "CM"), (7.0, "US M"))
        self.assertEqual(cli._foot_size("US W 7", "US M"), (7.0, "US W"))
        for command in (["shoes", "-b", "nike"], ["allbrands"]):
            with self.subTest(command=command[0]):
                finder = FakeFinder()
                with mock.patch.object(cli, "_build_finder", return_value=finder):
                    run_cli([*command, "-s", "US 7", "--scale", "US W"])
                self.assertEqual(finder.calls[0][1]["scale"], "US W")

    def test_millimetres_out_of_range_reported_in_mm(self):
        for extra in (["-s", "1000", "--scale", "MM"], ["-s", "MM 1000"]):
            with self.subTest(extra=extra):
                built = self.no_network()
                code, _, err = run_cli(["shoes", "-b", "nike", *extra])
                self.assertEqual(code, 2)
                self.assertIn("1000 мм", err)
                self.assertIn("150–400 мм", err)
                # Миллиметры человек уже указал — советовать MM или EU незачем.
                self.assertNotIn("--scale MM", err)
                self.assertNotIn("--scale EU", err)
                built.assert_not_called()

    def test_centimetres_given_as_millimetres_hint(self):
        built = self.no_network()
        code, _, err = run_cli(["shoes", "-b", "nike", "-s", "26,5", "--scale", "MM"])
        self.assertEqual(code, 2)
        self.assertIn("26,5 мм", err)
        self.assertIn("уберите MM", err)
        built.assert_not_called()

    def test_negative_size_rejected(self):
        # Регрессия: «-s -42 --scale EU» искал EU 42.
        cases = [
            ["shoes", "-b", "nike", "-s", "-42", "--scale", "EU"],
            ["shoes", "-b", "nike", "-s", "−26,5"],
            ["allbrands", "-s", "–26,5"],
            ["find", "-q", "nike", "-s", "-42"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                built = self.no_network()
                code, _, err = run_cli(argv)
                self.assertEqual(code, 2)
                self.assertIn("размер должен быть больше нуля", err)
                built.assert_not_called()

    def test_huge_size_is_friendly_error(self):
        # Регрессия: inf из длинного числа ронял _num с OverflowError.
        huge = "9" * 400
        cases = [
            ["shoes", "-b", "nike", "-s", huge],
            ["shoes", "-b", "nike", "-s", huge, "--scale", "EU"],
            ["allbrands", "-s", huge],
            ["find", "-q", "nike", "-s", huge],
        ]
        for argv in cases:
            with self.subTest(argv=argv[:2]):
                built = self.no_network()
                code, _, err = run_cli(argv)
                self.assertEqual(code, 2)
                self.assertIn("слишком большое число", err)
                self.assertNotIn("Traceback", err)
                built.assert_not_called()

    def test_find_rejects_us_inside_size(self):
        built = self.no_network()
        code, _, err = run_cli(["find", "-q", "nike", "-s", "US 9"])
        self.assertEqual(code, 2)
        self.assertIn("RU и EU", err)
        built.assert_not_called()

    def test_find_rejects_foreign_scale_in_size_even_with_scale(self):
        # Регрессия: «US 9» --scale EU молча теряло «US» и искало EU 9.
        for size in ("US 9", "US W 7", "CM 26", "UK 8"):
            with self.subTest(size=size):
                built = self.no_network()
                code, _, err = run_cli(["find", "-q", "nike", "-s", size, "--scale", "EU"])
                self.assertEqual(code, 2)
                self.assertIn("RU и EU", err)
                built.assert_not_called()

    def test_find_rejects_conflicting_scales(self):
        built = self.no_network()
        code, _, err = run_cli(["find", "-q", "nike", "-s", "RU 42", "--scale", "EU"])
        self.assertEqual(code, 2)
        self.assertIn("не совпадает", err)
        built.assert_not_called()

    def test_find_same_scale_twice_is_fine(self):
        finder = FakeFinder()
        self.patch_finder(finder)
        code, _, _ = run_cli(["find", "-q", "nike", "-s", "eu 42", "--scale", "EU"])
        self.assertEqual(code, 1)  # ничего не нашлось — но поиск был
        self.assertEqual(finder.calls[0][1]["scale"], "EU")


# -------------------------------------------------------------- allbrands


class TestAllbrands(CliCase):
    def test_skipped_line_respects_brands(self):
        finder = FakeFinder([make_match()])
        self.patch_finder(finder)
        code, out, _ = run_cli(["allbrands", "-s", "26,5", "--brands", "nike"])
        self.assertEqual(code, 0)
        self.assertNotIn("Puma", out)
        self.assertEqual(finder.calls[0][1]["only"], ["nike"])

    def test_skipped_line_without_brands(self):
        self.patch_finder(FakeFinder([make_match()]))
        code, out, _ = run_cli(["allbrands", "-s", "26,5"])
        self.assertEqual(code, 0)
        self.assertIn("пропущены: Puma", out)

    def test_brand_aliases_resolved_to_chart_keys(self):
        finder = FakeFinder()
        self.patch_finder(finder)
        run_cli(["allbrands", "-s", "26,5", "--brands", "nb", "Jordan", "nike"])
        self.assertEqual(finder.calls[0][1]["only"], ["new-balance", "nike"])

    def test_unknown_brand_rejected_before_scan(self):
        built = self.no_network()
        code, _, err = run_cli(["allbrands", "-s", "26,5", "--brands", "nikee"])
        self.assertEqual(code, 2)
        self.assertIn("nikee", err)
        built.assert_not_called()

    def test_no_brand_publishes_scale(self):
        built = self.no_network()
        code, _, err = run_cli(["allbrands", "-s", "26,5", "--brands", "puma"])
        self.assertEqual(code, 2)
        self.assertIn("--scale EU", err)
        built.assert_not_called()

    def test_blank_line_between_summary_and_table(self):
        self.patch_finder(FakeFinder([make_match()]))
        _, out, _ = run_cli(["allbrands", "-s", "26,5", "--brands", "nike"])
        self.assertIn("1 модель", out)
        self.assertIn("EU 43⅓\n\n#", out)


# ----------------------------------------------------------------- вывод


class TestFormatting(unittest.TestCase):
    def test_models_plural(self):
        cases = {
            1: "1 модель", 2: "2 модели", 4: "4 модели", 5: "5 моделей",
            11: "11 моделей", 14: "14 моделей", 21: "21 модель",
            22: "22 модели", 112: "112 моделей", 0: "0 моделей",
        }
        for count, text in cases.items():
            self.assertEqual(cli._models(count), text)

    def test_num(self):
        self.assertEqual(cli._num(26.5), "26,5")
        self.assertEqual(cli._num(42.0), "42")
        self.assertEqual(cli._num(9.5), "9,5")
        self.assertEqual(cli._num(43.3333), "43⅓")
        self.assertEqual(cli._num(36.6667), "36⅔")
        self.assertEqual(cli._num(36 + 2 / 3), "36⅔")
        self.assertEqual(cli._num(22.25), "22,25")

    def test_num_non_finite(self):
        # math.floor(inf) — OverflowError; вывод не должен падать.
        self.assertEqual(cli._num(float("inf")), "∞")
        self.assertEqual(cli._num(float("-inf")), "-∞")
        self.assertEqual(cli._num(float("nan")), "—")

    def test_fit_hint(self):
        self.assertEqual(cli._fit_hint("Размер больше, возьмите размер -0,5"), "-0,5")
        self.assertEqual(cli._fit_hint("Размер меньше, возьмите размер +1"), "+1")
        self.assertEqual(cli._fit_hint("возьмите размер −0,5"), "-0,5")
        self.assertEqual(cli._fit_hint("возьмите размер +0.5"), "+0,5")
        self.assertEqual(cli._fit_hint("US-9 маломерит"), "—")
        self.assertEqual(cli._fit_hint("US-9: возьмите -0,5"), "-0,5")
        self.assertEqual(cli._fit_hint("в размер"), "—")
        self.assertEqual(cli._fit_hint(""), "—")

    def test_shoes_table(self):
        text = cli.render_shoes_table([
            make_match(1, 9990.0, tip="Размер больше, возьмите размер -0,5"),
            make_match(2, 12990.0),
        ])
        self.assertIn("В наличии: 2 модели", text)
        self.assertIn("Запрошено: 26,5 CM → EU 43⅓", text)
        self.assertNotIn("43,3333", text)
        self.assertIn("-0,5", text)
        # Блоки разделены пустой строкой, но без двойных пропусков.
        self.assertIn("\n\nВ наличии", text)
        self.assertIn("\n\nСсылки:", text)
        self.assertNotIn("\n\n\n", text)
        self.assertFalse(text.endswith("\n"))

    def test_shoes_table_without_summary(self):
        match = make_match(price=None)
        match.converted_eu = None
        text = cli.render_shoes_table([match])
        self.assertNotIn("В наличии", text)
        self.assertIn("\n\nСсылки:", text)
        self.assertNotIn("\n\n\n", text)

    def test_one_model(self):
        self.assertIn("В наличии: 1 модель ·", cli.render_shoes_table([make_match()]))


class TestOutputFiles(CliCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def shoes(self, *extra, matches=None):
        finder = FakeFinder([make_match()] if matches is None else matches)
        self.patch_finder(finder)
        return run_cli(["shoes", "-b", "nike", "-s", "26,5", *extra])

    def test_json_without_bom(self):
        path = self.tmp / "result.json"
        code, _, err = self.shoes("-f", "json", "-o", str(path))
        self.assertEqual(code, 0)
        raw = path.read_bytes()
        self.assertFalse(raw.startswith(codecs.BOM_UTF8))
        self.assertEqual(json.loads(raw.decode("utf-8"))[0]["spu_id"], 1)
        self.assertIn("1 модель", err)

    def test_csv_with_bom(self):
        path = self.tmp / "result.csv"
        code, _, _ = self.shoes("-f", "csv", "-o", str(path))
        self.assertEqual(code, 0)
        self.assertTrue(path.read_bytes().startswith(codecs.BOM_UTF8))

    def test_table_without_bom(self):
        path = self.tmp / "result.txt"
        self.shoes("-o", str(path))
        self.assertFalse(path.read_bytes().startswith(codecs.BOM_UTF8))

    def test_missing_directory_fails_before_scan(self):
        built = self.no_network()
        path = self.tmp / "нет" / "result.json"
        code, _, err = run_cli(["shoes", "-b", "nike", "-s", "26,5", "-f", "json", "-o", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("папки", err)
        built.assert_not_called()

    def test_directory_instead_of_file(self):
        built = self.no_network()
        code, _, err = run_cli(["find", "-q", "x", "-s", "42", "-o", str(self.tmp)])
        self.assertEqual(code, 2)
        self.assertIn("это папка", err)
        built.assert_not_called()

    def test_probe_does_not_leave_file(self):
        path = self.tmp / "probe.json"
        self.assertIsNone(cli._file_problem(str(path)))
        self.assertFalse(path.exists())

    def test_write_failure_keeps_results_on_screen(self):
        path = self.tmp / "нет" / "result.json"
        with mock.patch.object(cli, "_file_problem", return_value=None):
            code, out, err = self.shoes("-f", "json", "-o", str(path))
        self.assertEqual(code, 2)
        self.assertIn("не удалось сохранить", err)
        self.assertEqual(json.loads(out)[0]["spu_id"], 1)

    def test_html_out_is_report_directory(self):
        target = self.tmp / "reports"
        code, out, _ = self.shoes("-f", "html", "-o", str(target))
        self.assertEqual(code, 0)
        reports = list(target.glob("*/index.html"))
        self.assertEqual(len(reports), 1)
        self.assertIn(str(reports[0]), out)

    def test_html_out_must_not_be_file(self):
        target = self.tmp / "report.html"
        target.write_text("x", encoding="utf-8")
        built = self.no_network()
        code, _, err = run_cli(["shoes", "-b", "nike", "-s", "26,5", "-f", "html", "-o", str(target)])
        self.assertEqual(code, 2)
        self.assertIn("папку", err)
        built.assert_not_called()

    def test_dir_probe_leaves_nothing_behind(self):
        # Недостающие папки проверка создаёт и убирает за собой.
        target = self.tmp / "new" / "reports"
        self.assertIsNone(cli._dir_problem(str(target)))
        self.assertFalse((self.tmp / "new").exists())
        # В существующей папке не остаётся пробного файла.
        self.assertIsNone(cli._dir_problem(str(self.tmp)))
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_html_out_unwritable_fails_before_scan(self):
        # Регрессия: проверялось лишь, что есть папка-предок, — запрет записи
        # всплывал в write_report после всего обхода и уносил результаты.
        built = self.no_network()
        target = self.tmp / "new" / "reports"
        denied = PermissionError(13, "Permission denied")
        with mock.patch.object(cli.tempfile, "TemporaryFile", side_effect=denied):
            code, _, err = run_cli(
                ["shoes", "-b", "nike", "-s", "26,5", "-f", "html", "-o", str(target)]
            )
        self.assertEqual(code, 2)
        self.assertIn("нельзя записать отчёт", err)
        self.assertIn("Permission denied", err)
        built.assert_not_called()
        self.assertFalse((self.tmp / "new").exists())

    @unittest.skipUnless(os.name == "nt", "«<» недопустим в именах только на Windows")
    def test_html_out_invalid_name_fails_before_scan(self):
        built = self.no_network()
        target = self.tmp / "rep<ort"
        code, _, err = run_cli(
            ["allbrands", "-s", "26,5", "-f", "html", "-o", str(target)]
        )
        self.assertEqual(code, 2)
        self.assertIn("нельзя записать отчёт", err)
        built.assert_not_called()


# ------------------------------------------------------- sizes / chart


def make_product():
    narrow = SizeOffer(
        sku_id=1, sizes={"RU": "41", "EU": "42"}, price=9000.0, in_stock=True,
        variant={"Полнота": "Узкая (B)"},
    )
    wide = SizeOffer(
        sku_id=2, sizes={"RU": "41", "EU": "42"}, price=9500.0, in_stock=True,
        variant={"Полнота": "Широкая (2E)"},
    )
    gone = SizeOffer(sku_id=3, sizes={"RU": "42", "EU": "43"}, in_stock=False)
    return Product(
        spu_id=7, title="NB 530", url="/product/7", size_scales=["RU", "EU"],
        offers=[narrow, wide, gone],
        chart=SizeChart(rows=[{"EU": 36.0, "US M": 4.0}]),
    )


class TestSizesAndChart(CliCase):
    def test_sizes_json_in_stock_and_variant(self):
        self.patch_finder(FakeFinder(product=make_product()))
        code, out, _ = run_cli(["sizes", "7", "-f", "json", "--in-stock"])
        self.assertEqual(code, 0)
        offers = json.loads(out)["offers"]
        self.assertEqual([o["sku_id"] for o in offers], [1, 2])
        self.assertEqual(
            [o["variant"] for o in offers], ["Узкая (B)", "Широкая (2E)"]
        )

    def test_sizes_json_all_offers(self):
        self.patch_finder(FakeFinder(product=make_product()))
        _, out, _ = run_cli(["sizes", "7", "-f", "json"])
        self.assertEqual(len(json.loads(out)["offers"]), 3)

    def test_chart_json(self):
        self.patch_finder(FakeFinder(product=make_product()))
        code, out, _ = run_cli(["chart", "7", "-f", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["chart"], [{"EU": 36.0, "US M": 4.0}])
        self.assertEqual(len(payload["in_stock"]), 2)


# ------------------------------------------------- size / brandchart


class TestSizeCommand(unittest.TestCase):
    def test_brand_sizes(self):
        code, out, _ = run_cli(["size", "26,5", "-b", "nike"])
        self.assertEqual(code, 0)
        self.assertIn("Длина стопы 26,5 см", out)
        self.assertIn("Nike", out)
        self.assertIn("Сравнение брендов", out)
        self.assertIn("43⅓", out)  # Adidas в сравнении — третями

    def test_out_of_table_is_not_missing_table(self):
        code, out, _ = run_cli(["size", "40", "-b", "nike"])
        self.assertEqual(code, 0)
        self.assertNotIn("официальной таблицы нет", out)
        self.assertIn("нет в официальной таблице", out)
        self.assertIn("ни в одной официальной таблице", out)
        self.assertIn("Нет в сравнении: Nike (стопа", out)

    def test_brand_without_foot_column(self):
        _, out, _ = run_cli(["size", "26,5", "-b", "puma"])
        self.assertIn("не публикует длину стопы", out)

    def test_unknown_brand(self):
        _, out, _ = run_cli(["size", "26,5", "-b", "noname"])
        self.assertIn("официальной таблицы нет", out)

    def test_bounds_shared_with_web(self):
        from poizon_parser.webapp import FOOT_MAX_CM, FOOT_MIN_CM

        self.assertEqual(run_cli(["size", str(FOOT_MIN_CM - 0.1)])[0], 2)
        self.assertEqual(run_cli(["size", str(FOOT_MAX_CM + 0.1)])[0], 2)
        self.assertEqual(run_cli(["size", str(FOOT_MIN_CM)])[0], 0)
        self.assertEqual(run_cli(["size", "abc"])[0], 2)


class TestBrandchart(unittest.TestCase):
    def test_women_source(self):
        code, out, _ = run_cli(["brandchart", "nike", "--gender", "women"])
        self.assertEqual(code, 0)
        self.assertIn("nike.com/size-fit/womens-footwear", out)
        self.assertNotIn("size-fit/mens-footwear", out)

    def test_foot_source_shown_separately(self):
        _, out, _ = run_cli(["brandchart", "reebok"])
        self.assertIn("Длина стопы: https://www.reebok.com/pages/size-guides", out)

    def test_thirds(self):
        _, out, _ = run_cli(["brandchart", "adidas"])
        self.assertIn("36⅔", out)
        self.assertNotIn("36,6667", out)

    def test_help_lists_all_brands(self):
        # Широкий «терминал» и без цвета: перенос строк не разорвёт «New Balance».
        with mock.patch.dict(os.environ, {"COLUMNS": "1000", "NO_COLOR": "1"}):
            help_text = cli.build_parser().format_help()
        for chart in load_brand_charts().values():
            self.assertIn(chart.name, help_text)


# ------------------------------------------------------------- ошибки


class TestFriendlyErrors(CliCase):
    def test_json_decode_error_is_not_input_error(self):
        self.patch_finder(FakeFinder(error=json.JSONDecodeError("Expecting value", "", 0)))
        code, _, err = run_cli(["sizes", "1"])
        self.assertEqual(code, 2)
        self.assertIn("не удалось разобрать ответ сайта", err)
        self.assertNotIn("Ошибка ввода", err)

    def test_site_data_error_in_shoes_is_labelled(self):
        self.patch_finder(FakeFinder(error=json.JSONDecodeError("Expecting value", "", 0)))
        code, _, err = run_cli(["shoes", "-b", "nike", "-s", "26,5"])
        self.assertEqual(code, 2)
        self.assertIn("не удалось разобрать ответ сайта", err)

    def test_brand_not_found_still_plain_error(self):
        self.patch_finder(FakeFinder(error=ValueError("бренд «xyz» не найден")))
        code, _, err = run_cli(["shoes", "-b", "xyz", "-s", "26,5"])
        self.assertEqual(code, 2)
        self.assertIn("Ошибка: бренд «xyz» не найден", err)

    def test_unicode_decode_error_is_not_input_error(self):
        error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        self.patch_finder(FakeFinder(error=error))
        code, _, err = run_cli(["chart", "1"])
        self.assertEqual(code, 2)
        self.assertIn("не удалось разобрать ответ сайта", err)

    def test_os_error_without_traceback(self):
        self.patch_finder(FakeFinder(error=PermissionError(13, "Permission denied", "x.html")))
        code, _, err = run_cli(["sizes", "1"])
        self.assertEqual(code, 2)
        self.assertIn("Permission denied — x.html", err)

    def test_web_busy_port(self):
        busy = OSError(errno.EADDRINUSE, "Address already in use")
        with mock.patch("poizon_parser.webapp.run_server", side_effect=busy):
            code, _, err = run_cli(["web", "--no-open", "--port", "8765"])
        self.assertEqual(code, 2)
        self.assertIn("порт 8765 занят", err)
        self.assertIn("--port 8766", err)

    def test_web_bad_host(self):
        bad = socket.gaierror(11001, "getaddrinfo failed")
        with mock.patch("poizon_parser.webapp.run_server", side_effect=bad):
            code, _, err = run_cli(["web", "--no-open", "--host", "nohost.invalid"])
        self.assertEqual(code, 2)
        self.assertIn("не удалось запустить сервер", err)


# ------------------------------------------- обрыв поиска проверкой сайта


def challenge(partial=()):
    exc = ChallengeRequired("https://www.thepoizon.ru/x", "captcha")
    exc.partial = list(partial)
    return exc


class InterruptedFinder(FakeFinder):
    """Проверку не прошли (например, «q»): находки до неё — в exc.partial."""

    def __init__(self, partial=(), brands=()):
        super().__init__()
        self.partial = list(partial)
        self.brands = list(brands)  # [(бренд, находки)], пройденные до обрыва

    def find_by_brand(self, **kwargs):
        self.calls.append(("find_by_brand", kwargs))
        raise challenge(self.partial)

    def find_in_official_brands(self, **kwargs):
        self.calls.append(("find_in_official_brands", kwargs))
        for name, found in self.brands:
            kwargs["on_brand"](name, found)
        raise challenge(self.partial)

    def find(self, **kwargs):
        self.calls.append(("find", kwargs))
        raise challenge(self.partial)


class TestInterruptedSearch(CliCase):
    """Регрессия: обрыв проверкой уносил всё, что поиск успел найти."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.partial = [make_match(1, 9990.0), make_match(2, 12990.0)]

    def assert_interrupted(self, code, err, count="2 модели"):
        self.assertEqual(code, 2)  # тот же код, что и при ошибке сайта
        self.assertIn("требуется пройти проверку", err)
        self.assertIn("прерван проверкой сайта", err)
        self.assertIn(count, err)

    def test_shoes_table_shows_partial(self):
        self.patch_finder(InterruptedFinder(self.partial))
        code, out, err = run_cli(["shoes", "-b", "nike", "-s", "26,5"])
        self.assert_interrupted(code, err)
        self.assertIn("Кроссовки 1", out)
        self.assertIn("Кроссовки 2", out)
        self.assertIn("В наличии: 2 модели", out)

    def test_shoes_json_file_keeps_partial(self):
        self.patch_finder(InterruptedFinder(self.partial))
        path = self.tmp / "result.json"
        code, _, err = run_cli(
            ["shoes", "-b", "nike", "-s", "26,5", "-f", "json", "-o", str(path)]
        )
        self.assert_interrupted(code, err)
        rows = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([row["spu_id"] for row in rows], [1, 2])

    def test_shoes_html_report_keeps_partial(self):
        self.patch_finder(InterruptedFinder(self.partial))
        target = self.tmp / "reports"
        code, out, err = run_cli(
            ["shoes", "-b", "nike", "-s", "26,5", "-f", "html", "-o", str(target)]
        )
        self.assert_interrupted(code, err)
        self.assertEqual(len(list(target.glob("*/index.html"))), 1)
        self.assertIn("Отчёт готов", out)

    def test_nothing_found_before_check_is_plain_error(self):
        self.patch_finder(InterruptedFinder())
        code, out, err = run_cli(["shoes", "-b", "nike", "-s", "26,5"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("требуется пройти проверку", err)
        self.assertNotIn("прерван", err)

    def test_allbrands_shows_partial(self):
        adidas = make_match(2, 12990.0, brand="Adidas")
        finder = InterruptedFinder(
            [self.partial[0], adidas], brands=[("Nike", [self.partial[0]])]
        )
        self.patch_finder(finder)
        code, out, err = run_cli(["allbrands", "-s", "26,5"])
        self.assert_interrupted(code, err)
        self.assertIn("Nike", out)
        self.assertIn("Adidas", out)
        self.assertIn("Список неполный", out)

    def test_find_shows_partial(self):
        self.patch_finder(InterruptedFinder(self.partial[:1]))
        code, out, err = run_cli(["find", "-q", "nike", "-s", "42"])
        self.assert_interrupted(code, err, count="1 модель")
        self.assertIn("Кроссовки 1", out)


# --------------------------------------------------------------- капча


class TestTerminalChallenge(unittest.TestCase):
    INFO = {"url": "https://www.thepoizon.ru/x", "reason": "captcha"}

    def ask_from_threads(self, answer, workers=3):
        """workers потоков одновременно упираются в капчу; Enter — один."""
        challenge = cli.TerminalChallenge()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def fake_input(*_args):
            calls.append(1)
            entered.set()
            release.wait(5)
            return answer

        results = [None] * workers

        def worker(index):
            results[index] = challenge(self.INFO)

        err = io.StringIO()
        with mock.patch("builtins.input", fake_input), redirect_stderr(err):
            first = threading.Thread(target=worker, args=(0,))
            first.start()
            self.assertTrue(entered.wait(5))
            others = [
                threading.Thread(target=worker, args=(i,)) for i in range(1, workers)
            ]
            for thread in others:
                thread.start()
            deadline = time.monotonic() + 5
            while challenge.waiting < workers - 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(challenge.waiting, workers - 1)
            release.set()
            for thread in [first, *others]:
                thread.join(5)
                self.assertFalse(thread.is_alive(), "воркер завис в ожидании")
        return challenge, results, calls, err.getvalue()

    def test_one_enter_releases_all_workers(self):
        _, results, calls, err = self.ask_from_threads("")
        self.assertEqual(results, [True, True, True])
        self.assertEqual(len(calls), 1)
        self.assertEqual(err.count("Сайт показал проверку"), 1)

    def test_quit_stops_all_workers_and_sticks(self):
        challenge, results, calls, _ = self.ask_from_threads("q")
        self.assertEqual(results, [False, False, False])
        self.assertEqual(len(calls), 1)
        with mock.patch("builtins.input", side_effect=AssertionError("второй вопрос")):
            self.assertFalse(challenge(self.INFO))

    def test_eof_means_stop(self):
        challenge = cli.TerminalChallenge()
        with mock.patch("builtins.input", side_effect=EOFError), redirect_stderr(io.StringIO()):
            self.assertFalse(challenge(self.INFO))

    def test_new_question_after_continue(self):
        challenge = cli.TerminalChallenge()
        with mock.patch("builtins.input", return_value="") as fake, \
                redirect_stderr(io.StringIO()):
            self.assertTrue(challenge(self.INFO))
            self.assertTrue(challenge(self.INFO))
        self.assertEqual(fake.call_count, 2)

    def test_parallel_scan_stops_without_hanging(self):
        """«q» при -w 3: обход завершается ChallengeRequired, а не висит."""
        challenge = cli.TerminalChallenge()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def fake_input(*_args):
            calls.append(1)
            entered.set()
            release.wait(5)
            return "q"

        class BlockedFinder(SizeFinder):
            def load_product(self, item):
                # Так ведёт себя клиент: спросил человека, отказ — исключение.
                if not challenge(TestTerminalChallenge.INFO):
                    raise ChallengeRequired("https://www.thepoizon.ru/x")
                raise AssertionError("после отказа карточки не грузятся")

        finder = BlockedFinder(client=mock.Mock(should_stop=None))
        items = [SearchItem(spu_id=i, title=str(i), url=f"/product/{i}") for i in range(6)]
        outcome = {}

        def scan():
            try:
                finder.scan_products(items, 42.0, "EU", workers=3)
            except ChallengeRequired as exc:
                outcome["error"] = exc

        with mock.patch("builtins.input", fake_input), redirect_stderr(io.StringIO()):
            runner = threading.Thread(target=scan)
            runner.start()
            self.assertTrue(entered.wait(5))
            deadline = time.monotonic() + 5
            while challenge.waiting < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            release.set()
            runner.join(10)
        self.assertFalse(runner.is_alive(), "обход завис после «q»")
        self.assertIn("error", outcome)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
