#!/usr/bin/env python3
"""Точка входа парсера thepoizon.ru.

    python main.py find -q "nike air force 1" -s 42
    python main.py sizes 8900001978861819
"""

from poizon_parser.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
