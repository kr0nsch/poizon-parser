"""Тесты разбора и сопоставления размеров."""

import unittest

from poizon_parser.sizechart import CM, MM, US_MEN, US_WOMEN, normalize_scale
from poizon_parser.sizes import (
    match_size,
    parse_size,
    parse_size_query,
    scale_priority,
)


class TestParseSize(unittest.TestCase):
    def test_comma_decimal(self):
        self.assertEqual(parse_size("42,5"), 42.5)

    def test_dot_decimal(self):
        self.assertEqual(parse_size("42.5"), 42.5)

    def test_integer(self):
        self.assertEqual(parse_size("42"), 42.0)

    def test_numeric_input(self):
        self.assertEqual(parse_size(41), 41.0)

    def test_size_with_noise(self):
        self.assertEqual(parse_size("38,5 RU (39,5 EU)"), 38.5)

    def test_no_number(self):
        self.assertIsNone(parse_size("один размер"))
        self.assertIsNone(parse_size(None))

    def test_vulgar_fraction_third(self):
        # Adidas публикует размеры вида «42⅓» — это не 42.
        self.assertAlmostEqual(parse_size("42⅓"), 42 + 1 / 3, places=4)

    def test_vulgar_fraction_two_thirds(self):
        self.assertAlmostEqual(parse_size("41⅔"), 41 + 2 / 3, places=4)

    def test_vulgar_fraction_half(self):
        self.assertEqual(parse_size("42½"), 42.5)

    def test_bare_fraction(self):
        self.assertEqual(parse_size("½"), 0.5)

    def test_fraction_not_confused_with_whole(self):
        self.assertNotEqual(parse_size("42⅓"), parse_size("42"))

    def test_ascii_fraction(self):
        # Так Adidas и американские таблицы пишут размеры: «36 2/3», «9 1/2».
        self.assertAlmostEqual(parse_size("42 2/3"), 42 + 2 / 3, places=9)
        self.assertEqual(parse_size("9 1/2"), 9.5)
        self.assertAlmostEqual(parse_size("EU 36 2/3 (RU 35 2/3)"), 36 + 2 / 3)

    def test_slash_that_is_not_a_size_fraction_ignored(self):
        # Ярлыки разбираются нестрого: не дробь — просто первое число.
        self.assertEqual(parse_size("10/2025"), 10.0)
        self.assertEqual(parse_size("42 3/2"), 42.0)
        self.assertEqual(parse_size("42,5 1/2"), 42.5)


class TestParseSizeQuery(unittest.TestCase):
    def test_bare_number(self):
        self.assertEqual(parse_size_query("42"), (None, 42.0))

    def test_scale_prefix_no_space(self):
        self.assertEqual(parse_size_query("RU42"), ("RU", 42.0))

    def test_scale_prefix_with_space(self):
        self.assertEqual(parse_size_query("EU 43"), ("EU", 43.0))

    def test_lowercase_scale_normalised(self):
        self.assertEqual(parse_size_query("us 9,5"), ("US", 9.5))

    def test_us_women_is_not_men(self):
        # Регрессия: «US W 7» разбиралось как «US» + «W 7» → мужской US 7.
        for text in ("US W 7", "usw 7", "US-W 7", "USW7", "US Women 7",
                     "US Женские 7"):
            with self.subTest(text=text):
                self.assertEqual(parse_size_query(text), ("US W", 7.0))

    def test_us_men_explicit(self):
        for text in ("US M 9", "usm 9", "US Men 9", "US Мужские 9"):
            with self.subTest(text=text):
                self.assertEqual(parse_size_query(text), ("US M", 9.0))

    def test_single_cyrillic_gender_letter(self):
        # Регрессия: «US Ж 7» читалось как голое «US» — мужской US 7.
        for text in ("US Ж 7", "us ж 7", "USЖ7", "US жен 7"):
            with self.subTest(text=text):
                self.assertEqual(parse_size_query(text), ("US W", 7.0))
        for text in ("US М 7", "us м 7", "USМ7", "US муж 7"):  # кириллица
            with self.subTest(text=text):
                self.assertEqual(parse_size_query(text), ("US M", 7.0))

    def test_negative_size_rejected(self):
        # Регрессия: знак терялся, и «-42» искало размер 42.
        for text in (
            "-42", "−42", "–42", "EU:-42", "US W −7",
            # Минус, приклеенный к слову пола или к числу после пробела.
            "US W−7", "USW−7", "US Ж−7", "US M−9", "US W:-7", "EU -42", "CM -26,5",
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as ctx:
                    parse_size_query(text)
                self.assertIn("больше нуля", str(ctx.exception))

    def test_dash_after_scale_is_still_a_separator(self):
        self.assertEqual(parse_size_query("EU-42"), ("EU", 42.0))
        self.assertEqual(parse_size_query("EU - 42"), ("EU", 42.0))
        self.assertEqual(parse_size_query("US W-7"), ("US W", 7.0))
        self.assertEqual(parse_size_query("US Women: 7"), ("US W", 7.0))

    def test_number_too_big_for_float_rejected(self):
        # Сотни цифр подряд float() превращает в inf.
        with self.assertRaises(ValueError) as ctx:
            parse_size_query("9" * 400)
        self.assertIn("слишком большое", str(ctx.exception))

    def test_metric_prefixes(self):
        self.assertEqual(parse_size_query("CM 26,5"), ("CM", 26.5))
        self.assertEqual(parse_size_query("см 26,5"), ("CM", 26.5))
        self.assertEqual(parse_size_query("mm 265"), ("MM", 265.0))
        self.assertEqual(parse_size_query("мм 265"), ("MM", 265.0))

    def test_parsed_scales_are_understood_by_sizechart(self):
        expected = {
            "US W 7": US_WOMEN, "US M 9": US_MEN, "CM 26": CM, "MM 265": MM,
        }
        for text, scale in expected.items():
            with self.subTest(text=text):
                parsed, _value = parse_size_query(text)
                self.assertEqual(normalize_scale(parsed), scale)

    def test_fractional_value_after_prefix(self):
        scale, value = parse_size_query("EU 42⅔")
        self.assertEqual(scale, "EU")
        self.assertAlmostEqual(value, 42 + 2 / 3, places=9)

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            parse_size_query("  ")

    def test_garbage_rejected(self):
        with self.assertRaises(ValueError):
            parse_size_query("большой")

    def test_ascii_fraction_is_part_of_size(self):
        # Регрессия: «EU 42 2/3» молча искало EU 42, «US 9 1/2» — US 9.
        cases = {
            "42 2/3": (None, 42 + 2 / 3),
            "EU 42 2/3": ("EU", 42 + 2 / 3),
            "US 9 1/2": ("US", 9.5),
            "US W 7 1/2": ("US W", 7.5),
            "EU 42 ⅔": ("EU", 42 + 2 / 3),
        }
        for text, (scale, value) in cases.items():
            with self.subTest(text=text):
                parsed_scale, parsed_value = parse_size_query(text)
                self.assertEqual(parsed_scale, scale)
                self.assertAlmostEqual(parsed_value, value, places=9)

    def test_trailing_gender_after_bare_us(self):
        # Регрессия: «US 7W» искало мужской US 7.
        for text in ("US 7W", "US 7 W", "us 7w", "US 7 Ж", "US 7 жен", "US 7 women"):
            with self.subTest(text=text):
                self.assertEqual(parse_size_query(text), ("US W", 7.0))
        for text in ("US 9M", "US 9 М", "US 9 муж"):
            with self.subTest(text=text):
                self.assertEqual(parse_size_query(text), ("US M", 9.0))
        self.assertEqual(parse_size_query("US 7 1/2 W"), ("US W", 7.5))

    def test_trailing_unit_sets_metric_scale(self):
        self.assertEqual(parse_size_query("26,5 см"), ("CM", 26.5))
        self.assertEqual(parse_size_query("26.5cm"), ("CM", 26.5))
        self.assertEqual(parse_size_query("265 мм"), ("MM", 265.0))
        self.assertEqual(parse_size_query("CM 26,5 см"), ("CM", 26.5))

    def test_leftover_text_rejected(self):
        # Раньше брался первый номер: «42-43» → 42, «4 2» → 4, «7W» → 7.
        for text in (
            "42-43", "4 2", "42 EU", "7W", "42,5 1/2", "42 2/3 4",
            "US W 7 W", "EU 42 W", "42 abc", "42.5⅓",
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as ctx:
                    parse_size_query(text)
                self.assertIn("не удалось разобрать размер", str(ctx.exception))

    def test_bad_fraction_rejected(self):
        for text in ("42 3/2", "42 1/0", "42 0/3", "42 " + "1" * 5000 + "/3"):
            with self.subTest(text=text[:12]):
                with self.assertRaises(ValueError) as ctx:
                    parse_size_query(text)
                self.assertIn("не дробь размера", str(ctx.exception))

    def test_two_scales_rejected(self):
        for text in ("EU 42 см", "US 9 мм", "MM 265 cm"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as ctx:
                    parse_size_query(text)
                self.assertIn("две шкалы", str(ctx.exception))


class TestScalePriority(unittest.TestCase):
    def test_preferred_scale_goes_first(self):
        self.assertEqual(scale_priority(["EU", "RU"], "EU")[0], "EU")

    def test_known_scales_ordered_when_no_preference(self):
        self.assertEqual(scale_priority(["EU", "RU"]), ["RU", "EU"])

    def test_unknown_scales_kept_at_end(self):
        self.assertEqual(scale_priority(["XX", "RU"]), ["RU", "XX"])


class TestMatchSize(unittest.TestCase):
    SIZES = {"RU": "42", "EU": "43"}

    def test_exact_match_in_scale(self):
        self.assertEqual(match_size(self.SIZES, 42.0, scale="RU"), ("RU", 0.0))

    def test_wrong_scale_does_not_match(self):
        self.assertIsNone(match_size(self.SIZES, 43.0, scale="RU"))

    def test_missing_scale_returns_none(self):
        self.assertIsNone(match_size(self.SIZES, 42.0, scale="US"))

    def test_any_scale_prefers_ru(self):
        # 42 есть только в RU — должно найтись именно там.
        self.assertEqual(match_size(self.SIZES, 42.0), ("RU", 0.0))

    def test_any_scale_falls_back_to_eu(self):
        self.assertEqual(match_size(self.SIZES, 43.0), ("EU", 0.0))

    def test_tolerance_allows_neighbour(self):
        result = match_size({"RU": "42,5"}, 42.0, scale="RU", tolerance=0.5)
        self.assertEqual(result, ("RU", 0.5))

    def test_tolerance_zero_rejects_neighbour(self):
        self.assertIsNone(match_size({"RU": "42,5"}, 42.0, scale="RU"))

    def test_rounded_third_matches_fraction_label(self):
        # Таблицы брендов хранят 42⅔ как 42.6667, ярлык SKU — «42⅔».
        # Это один размер, хотя числа и расходятся в пятом знаке.
        hit = match_size({"EU": "42⅔"}, 42.6667, scale="EU")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "EU")
        hit = match_size({"EU": "43⅓"}, 43.3333, scale="EU")
        self.assertIsNotNone(hit)

    def test_rounded_third_does_not_match_neighbour(self):
        # Допуск на округление не должен склеивать соседние размеры сетки.
        self.assertIsNone(match_size({"EU": "42½"}, 42.6667, scale="EU"))
        self.assertIsNone(match_size({"EU": "43"}, 42.6667, scale="EU"))


if __name__ == "__main__":
    unittest.main()
