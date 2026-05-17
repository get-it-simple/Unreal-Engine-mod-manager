#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys

from mod_manager.cli import run_cli
from mod_manager.menus import main_menu

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            raise SystemExit(run_cli(sys.argv[1:]))
        else:
            main_menu()
    except KeyboardInterrupt:
        print("\nExit…")
