"""Тесты хранилища итогов (многопользовательский режим)."""

import tempfile
import unittest
from pathlib import Path

from poizon_parser.webapp import PickStore

MATCH = {
    "spu_id": 123,
    "sku_id": 456,
    "title": "Тестовые кроссовки",
    "price": 7000.0,
    "url": "https://www.thepoizon.ru/product/123",
}
QUERY = {"brand": "Nike", "size": 42, "scale": "EU"}

UID = "aaaa1111bbbb2222"
UID2 = "cccc3333dddd4444"


class TestPickStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = PickStore(Path(self.dir.name))

    def tearDown(self):
        self.dir.cleanup()

    def test_add_and_list(self):
        entry, created = self.store.add(UID, MATCH, QUERY)
        self.assertTrue(created)
        self.assertTrue(entry["id"])
        items = self.store.list(UID)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["match"]["spu_id"], 123)

    def test_duplicate_not_added(self):
        self.store.add(UID, MATCH, QUERY)
        _, created = self.store.add(UID, MATCH, QUERY)
        self.assertFalse(created)
        self.assertEqual(len(self.store.list(UID)), 1)

    def test_same_sku_other_query_is_new_entry(self):
        self.store.add(UID, MATCH, QUERY)
        _, created = self.store.add(UID, MATCH, {**QUERY, "size": 43})
        self.assertTrue(created)
        self.assertEqual(len(self.store.list(UID)), 2)

    def test_newest_first(self):
        self.store.add(UID, MATCH, QUERY)
        self.store.add(UID, {**MATCH, "sku_id": 999}, QUERY)
        self.assertEqual(self.store.list(UID)[0]["match"]["sku_id"], 999)

    def test_remove(self):
        entry, _ = self.store.add(UID, MATCH, QUERY)
        self.assertTrue(self.store.remove(UID, entry["id"]))
        self.assertEqual(self.store.list(UID), [])
        self.assertFalse(self.store.remove(UID, "nope"))

    def test_clear(self):
        self.store.add(UID, MATCH, QUERY)
        self.store.add(UID, {**MATCH, "sku_id": 2}, QUERY)
        self.assertEqual(self.store.clear(UID), 2)
        self.assertEqual(self.store.list(UID), [])

    def test_survives_reload(self):
        self.store.add(UID, MATCH, QUERY)
        fresh = PickStore(self.store.base_dir)
        self.assertEqual(len(fresh.list(UID)), 1)

    def test_corrupt_file_treated_as_empty(self):
        path = self.store._path(UID)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("не json", encoding="utf-8")
        self.assertEqual(self.store.list(UID), [])


class TestMultiUser(unittest.TestCase):
    """Разные пользователи — разные, изолированные избранные."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = PickStore(Path(self.dir.name))

    def tearDown(self):
        self.dir.cleanup()

    def test_users_are_isolated(self):
        self.store.add(UID, MATCH, QUERY)
        self.store.add(UID2, {**MATCH, "sku_id": 777}, QUERY)
        self.assertEqual(len(self.store.list(UID)), 1)
        self.assertEqual(len(self.store.list(UID2)), 1)
        self.assertEqual(self.store.list(UID)[0]["match"]["sku_id"], 456)
        self.assertEqual(self.store.list(UID2)[0]["match"]["sku_id"], 777)

    def test_clear_one_user_keeps_other(self):
        self.store.add(UID, MATCH, QUERY)
        self.store.add(UID2, MATCH, QUERY)
        self.store.clear(UID)
        self.assertEqual(self.store.list(UID), [])
        self.assertEqual(len(self.store.list(UID2)), 1)

    def test_separate_files_per_user(self):
        self.store.add(UID, MATCH, QUERY)
        self.store.add(UID2, MATCH, QUERY)
        self.assertTrue(self.store._path(UID).exists())
        self.assertTrue(self.store._path(UID2).exists())
        self.assertNotEqual(self.store._path(UID), self.store._path(UID2))

    def test_unknown_user_is_empty(self):
        self.store.add(UID, MATCH, QUERY)
        self.assertEqual(self.store.list("ffff9999"), [])

    def test_uid_sanitized_against_traversal(self):
        # Небезопасный uid не должен вырваться из папки хранилища.
        entry, _ = self.store.add("../../etc/passwd", MATCH, QUERY)
        path = self.store._path("../../etc/passwd")
        self.assertEqual(path.parent, self.store.base_dir)
        # Все не-hex символы отброшены → безопасное имя.
        self.assertTrue(path.name.replace(".json", "").isalnum() or
                        path.name == "anon.json")

    def test_empty_uid_falls_back_to_anon(self):
        self.assertEqual(self.store._safe_uid(""), "anon")
        self.assertEqual(self.store._safe_uid(None), "anon")


if __name__ == "__main__":
    unittest.main()
