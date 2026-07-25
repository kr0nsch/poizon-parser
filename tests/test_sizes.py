"""Тесты разбора и сопоставления размеров."""

import unittest

from poizon_parser.sizes import (
    format_size,
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


class TestFormatSize(unittest.TestCase):
    def test_integer_has_no_decimals(self):
        self.assertEqual(format_size(42.0), "42")

    def test_half_size_uses_comma(self):
        self.assertEqual(format_size(42.5), "42,5")


class TestParseSizeQuery(unittest.TestCase):
    def test_bare_number(self):
        self.assertEqual(parse_size_query("42"), (None, 42.0))

    def test_scale_prefix_no_space(self):
        self.assertEqual(parse_size_query("RU42"), ("RU", 42.0))

    def test_scale_prefix_with_space(self):
        self.assertEqual(parse_size_query("EU 43"), ("EU", 43.0))

    def test_lowercase_scale_normalised(self):
        self.assertEqual(parse_size_query("us 9,5"), ("US", 9.5))

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            parse_size_query("  ")

    def test_garbage_rejected(self):
        with self.assertRaises(ValueError):
            parse_size_query("большой")


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


if __name__ == "__main__":
    unittest.main()
