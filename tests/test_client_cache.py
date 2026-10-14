"""Тесты дискового кэша HTML клиента: где он лежит и чему в нём верить."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from poizon_parser import client as client_module
from poizon_parser import webapp
from poizon_parser.client import PoizonClient, default_cache_dir

URL = "https://www.thepoizon.ru/product/x-1"
PAGE = "<html>" + "x" * 3000 + "</html>"


def can_symlink(directory: Path) -> bool:
    """На Windows ссылки создаются только с правами или в режиме разработчика."""
    probe = directory / "probe-link"
    try:
        os.symlink(directory / "missing", probe)
    except (OSError, NotImplementedError):
        return False
    probe.unlink()
    return True


class TestDefaultCacheDir(unittest.TestCase):
    """Кэш — в личной папке пользователя, а не в общей временной."""

    @unittest.skipUnless(os.name == "nt", "раскладка папок Windows")
    def test_windows_uses_local_app_data(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}):
            self.assertEqual(
                default_cache_dir(),
                Path(r"C:\Users\u\AppData\Local") / "poizon-parser" / "cache",
            )

    @unittest.skipIf(os.name == "nt", "раскладка папок POSIX")
    def test_posix_uses_xdg_cache_home(self):
        with patch.dict(os.environ, {"XDG_CACHE_HOME": "/home/u/.xdg-cache"}):
            self.assertEqual(
                default_cache_dir(), Path("/home/u/.xdg-cache/poizon-parser")
            )

    @unittest.skipIf(os.name == "nt", "раскладка папок POSIX")
    def test_posix_falls_back_to_home_cache(self):
        env = {"HOME": "/home/u", "XDG_CACHE_HOME": "relative/ignored"}
        with patch.dict(os.environ, env):
            self.assertEqual(
                default_cache_dir(), Path("/home/u/.cache/poizon-parser")
            )

    def test_not_in_shared_temp_dir(self):
        # Регрессия: кэш лежал в общем /tmp/poizon-parser-cache, и другой
        # пользователь мог заранее создать каталог и подложить страницы.
        self.assertNotEqual(
            default_cache_dir(), Path(tempfile.gettempdir()) / "poizon-parser-cache"
        )
        self.assertEqual(webapp.CACHE_DIR, default_cache_dir())

    def test_does_not_create_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"LOCALAPPDATA": tmp, "XDG_CACHE_HOME": tmp}
            with patch.dict(os.environ, env):
                path = default_cache_dir()
            self.assertTrue(str(path).startswith(tmp))
            self.assertFalse(path.exists())


class TestCacheEntries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "cache"
        self.client = PoizonClient(cache_dir=str(self.dir), cache_ttl=900.0)
        self.path = self.client._cache_path(URL)

    def test_round_trip(self):
        self.client._cache_write(URL, PAGE)
        self.assertEqual(self.client._cache_read(URL), PAGE)
        # Временные файлы атомарной записи не остаются.
        self.assertEqual([p.name for p in self.dir.iterdir()], [self.path.name])

    def test_stale_entry_is_ignored(self):
        self.client._cache_write(URL, PAGE)
        old = time.time() - 1000
        os.utime(self.path, (old, old))
        self.assertIsNone(self.client._cache_read(URL))

    def test_future_mtime_is_treated_as_expired(self):
        # Регрессия: запись с датой из будущего не устаревала никогда —
        # подложенная страница отдавалась бы как настоящая.
        self.path.write_text("<html>FORGED</html>", encoding="utf-8")
        future = time.time() + 10 * 365 * 24 * 3600
        os.utime(self.path, (future, future))
        self.assertIsNone(self.client._cache_read(URL))

    def test_small_clock_skew_is_tolerated(self):
        # На Windows mtime только что записанного файла бывает на доли
        # микросекунды впереди time.time(): свежая запись не должна пропадать.
        self.path.write_text(PAGE, encoding="utf-8")
        ahead = time.time() + 0.5
        os.utime(self.path, (ahead, ahead))
        self.assertEqual(self.client._cache_read(URL), PAGE)

    def test_non_regular_entry_is_skipped(self):
        self.path.mkdir()
        self.assertIsNone(self.client._cache_read(URL))

    def test_symlink_entry_is_not_read(self):
        if not can_symlink(self.dir):
            self.skipTest("нет прав на создание символических ссылок")
        target = Path(self.tmp.name) / "elsewhere.html"
        target.write_text(PAGE, encoding="utf-8")
        os.symlink(target, self.path)
        self.assertIsNone(self.client._cache_read(URL))

    def test_write_replaces_planted_symlink_instead_of_following_it(self):
        # Регрессия: write_text шёл по подложенной ссылке и перезаписывал
        # файл, на который она указывала.
        if not can_symlink(self.dir):
            self.skipTest("нет прав на создание символических ссылок")
        victim = Path(self.tmp.name) / "victim.txt"
        victim.write_text("do not touch", encoding="utf-8")
        os.symlink(victim, self.path)

        self.client._cache_write(URL, PAGE)

        self.assertEqual(victim.read_text(encoding="utf-8"), "do not touch")
        self.assertFalse(self.path.is_symlink())
        self.assertEqual(self.client._cache_read(URL), PAGE)

    def test_write_does_not_go_through_planted_hard_link(self):
        # То же для жёсткой ссылки (её можно создать и без прав на symlink):
        # запись заменяет запись каталога, а не содержимое чужого файла.
        victim = Path(self.tmp.name) / "victim.txt"
        victim.write_text("do not touch", encoding="utf-8")
        try:
            os.link(victim, self.path)
        except (OSError, NotImplementedError):
            self.skipTest("жёсткие ссылки недоступны")
        old = time.time() - 1000
        os.utime(self.path, (old, old))  # запись устарела — будет перезапись

        self.client._cache_write(URL, PAGE)

        self.assertEqual(victim.read_text(encoding="utf-8"), "do not touch")
        self.assertEqual(self.client._cache_read(URL), PAGE)

    def test_failed_write_leaves_no_temp_files(self):
        with patch.object(client_module.os, "replace", side_effect=OSError("busy")):
            self.client._cache_write(URL, PAGE)
        self.assertEqual(list(self.dir.iterdir()), [])
        self.assertIsNone(self.client._cache_read(URL))

    def test_stub_pages_are_not_cached(self):
        self.client._cache_write(URL, "<html>C3VK</html>")
        self.assertFalse(self.path.exists())

    def test_unusable_cache_dir_disables_cache(self):
        # Папку кэша не создать (на её месте файл) — работаем без кэша.
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("x", encoding="utf-8")
        client = PoizonClient(cache_dir=str(blocker))
        self.assertIsNone(client.cache_dir)
        self.assertIsNone(client._cache_read(URL))
        client._cache_write(URL, PAGE)  # не падает
        self.assertEqual(blocker.read_text(encoding="utf-8"), "x")


@unittest.skipUnless(hasattr(os, "getuid"), "права каталогов POSIX")
class TestForeignCacheDir(unittest.TestCase):
    def test_world_writable_dir_disables_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            shared.mkdir()
            os.chmod(shared, 0o777)
            client = PoizonClient(cache_dir=str(shared))
            self.assertIsNone(client.cache_dir)

    def test_dir_of_other_user_disables_cache(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(client_module.os, "getuid", return_value=os.getuid() + 1):
            client = PoizonClient(cache_dir=tmp)
            self.assertIsNone(client.cache_dir)

    def test_own_private_dir_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = PoizonClient(cache_dir=str(Path(tmp) / "new"))
            self.assertIsNotNone(client.cache_dir)
            self.assertEqual(os.stat(client.cache_dir).st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
