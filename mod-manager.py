#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from mod_manager.menus import main_menu

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nExit…")
