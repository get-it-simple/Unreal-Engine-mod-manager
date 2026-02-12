from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Dict

from app_paths import PRINT_SIZE

from .platform_utils import is_windows
from .storage import load_config, save_config, load_labels, save_labels, load_presets
from .mods import discover_mods, list_broken_links, deactivate_mod, apply_mod, get_mod_file_name
from .presets import save_preset_from_installed, delete_presets_by_names, deactivate_preset, apply_preset
from .cli_utils import (
    prompt,
    pause,
    ensure_paths,
    parse_multi_choice,
    parse_page_choice,
    paginate,
    page_slice,
    print_pager,
    open_folder,
    filter_items_by_query,
    sort_items,
)

def menu_fix_broken(cfg: Dict):
    if not ensure_paths(cfg):
        return
    broken = list_broken_links(cfg)
    page = 1
    while True:
        os.system("cls" if is_windows() else "clear")
        broken = list_broken_links(cfg)
        if not broken:
            print("No broken links detected.")
            return
        page, pages = paginate(len(broken), page, cfg)
        shown = page_slice(broken, page, cfg)
        print("Fix broken links — remove game links whose source is missing")
        print("=" * PRINT_SIZE)
        for i, m in enumerate(shown, 1):
            kind = "DIR" if m.is_dir else "FILE"
            print(f"{i:2d}) [!] {m.name} ({kind})  -> missing source: {m.src}")
        print_pager(pages, page)
        print("0) Back  |  pN to change page  |  a) Remove ALL on page  |  numbers (comma-separated) to remove selected")
        choice = prompt("> ").strip().lower()
        if choice == "0":
            return
        if choice == "a":
            for m in shown:
                deactivate_mod(m)
            print("Removed all broken links on this page.")
            continue
        page_sel = parse_page_choice(choice)
        if page_sel:
            page = page_sel
            continue
        nums = parse_multi_choice(choice)
        for num in nums:
            if 1 <= num <= len(shown):
                m = shown[num - 1]
                ok, msg = deactivate_mod(m)
                print(f"Remove {m.dest.name}: {'OK' if ok else 'ERR'} — {msg}")

def menu_settings(cfg: Dict):
    while True:
        os.system("cls" if is_windows() else "clear")
        print("Settings")
        print("=" * PRINT_SIZE)
        print(f"1) Game mods folder: {cfg.get('game_mods_dir') or '-not set-'}")
        print(f"2) Mods source folder: {cfg.get('mods_source_dir') or '-not set-'}")
        print(f"3) Mod file extensions: {cfg.get('mod_extensions') or '(all)'}")
        print(f"4) Page size: {cfg.get('page_size') or 10}")
        print("\n0) Save and back\n")
        choice = prompt("Select [0-4]: ").strip()
        if choice == "1":
            p = prompt("Enter full path to game mods folder: ").strip().strip('"')
            cfg["game_mods_dir"] = str(Path(p).expanduser()) if p else cfg.get("game_mods_dir", "")
        elif choice == "2":
            p = prompt("Enter full path to mods source folder: ").strip().strip('"')
            cfg["mods_source_dir"] = str(Path(p).expanduser()) if p else cfg.get("mods_source_dir", "")
        elif choice == "3":
            p = prompt("Enter extensions (comma-separated) or leave empty for all: ").strip()
            cfg["mod_extensions"] = p
        elif choice == "4":
            p = prompt("Enter page size: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["page_size"] = int(p)
            else:
                print("incorect format, please enter a number")
        elif choice == "0":
            save_config(cfg)
            print("Saved.")
            return

def menu_mods_toggle(cfg: Dict):
    if not ensure_paths(cfg):
        return
    page = 1
    last_operation = ""
    search_query = ""
    label_filter = ""
    order_mode = "d"
    while True:
        os.system("cls" if is_windows() else "clear")
        items_all = discover_mods(cfg)
        items = filter_items_by_query(items_all, search_query)
        labels = load_labels()
        if label_filter:
            lf = label_filter.lower()
            items = [m for m in items if (labels.get(m.name) or "").lower() == lf]
        items = sort_items(items, order_mode)
        if not items:
            print("Mods — install/uninstall (toggle)")
            print("=" * PRINT_SIZE)
            if order_mode == "d":
                print("Order: default ↓")
            else:
                print("Order: created date ↓")
            if label_filter:
                print(f"Label: '{label_filter}'")
            if search_query:
                print(f"Filter: '{search_query}' (no matches)")
            else:
                print("Filter: '' (no matches)")
            print("\nCommands:")
            print("  - f <text>: (filter)")
            print('  - l "labelName": (label filter)')
            print('  - label add/remove "file name" "labelName"')
            print("  - o: <orderType> order mode (d or default, cd or created date)")
            print("  - clear: (clear filter)")
            print("  - 0: Back")
            print(f"    {last_operation}")
            choice = prompt("> ").strip()
            if choice == "0":
                return
            low = choice.lower()
            if low == "clear":
                search_query = ""
                label_filter = ""
                continue
            if low.startswith("f ") or low.startswith("find "):
                search_query = choice.split(" ", 1)[1].strip()
                page = 1
                continue
            if low.startswith("l ") or low.startswith("l:"):
                label_filter = choice.split(" ", 1)[1].strip().strip('"')
                page = 1
                continue
            if low.startswith("label "):
                try:
                    args = shlex.split(choice)
                except ValueError:
                    continue
                if len(args) == 4 and args[1].lower() in ["add", "remove"]:
                    action = args[1].lower()
                    file_name = args[2]
                    label_name = args[3]
                    labels = load_labels()
                    if action == "add":
                        labels[file_name] = label_name
                        save_labels(labels)
                    else:
                        if labels.get(file_name) == label_name:
                            labels.pop(file_name, None)
                            save_labels(labels)
                continue
            continue
        page, pages = paginate(len(items), page, cfg)
        shown = page_slice(items, page, cfg)
        print("Mods — install/uninstall (toggle)")
        print("=" * PRINT_SIZE)
        if order_mode == "d":
            print("Order: default ↓")
        else:
            print("Order: created date ↓")
        if label_filter:
            print(f"Label: '{label_filter}'")
        if search_query:
            print(f"Filter: '{search_query}'")
        for i, m in enumerate(shown, 1):
            mark = "[X]" if m.installed else "[ ]"
            kind = "DIR" if m.is_dir else "FILE"
            prefix = f"{i:2d}) {mark} "
            print(f"{prefix}{m.name} ({kind})")
            if label_filter == "":
                lbl = labels.get(m.name) if labels else None
                print(f"{' ' * len(prefix)}{lbl if lbl else '-'}\n")
        print("")
        print_pager(pages, page)
        print("Commands:")
        print("  - f: <text> (search) | clear: (clear search filter)")
        print('  - l <labelName>: (label filter)')
        print('  - label <add|remove> <labelName> <fileIndex>')
        print("  - o: <orderType> order mode (d or default, cd or created date)")
        print("  - numbers <comma-separated>: toggle selected")
        print("  - a: Uninstall ALL (current page)")
        print("  - i: Install ALL (current page)")
        print("  - pN: go to page N   |   0: back")
        print(f"    {last_operation}")
        choice = prompt("> ").strip()
        if choice == "0":
            return
        low = choice.lower()
        if low == "clear":
            search_query = ""
            label_filter = ""
            page = 1
            continue
        if low.startswith("f ") or low.startswith("find "):
            search_query = choice.split(" ", 1)[1].strip()
            page = 1
            continue
        if low.startswith("l ") or low.startswith("l:"):
            label_filter = choice.split(" ", 1)[1].strip().strip('"')
            page = 1
            continue
        if low.startswith("label "):
            try:
                args = shlex.split(choice)
            except ValueError:
                continue
            if len(args) == 4 and args[1].lower() in ["add", "remove"]:
                action = args[1].lower()
                label_name = args[2]
                file_name = get_mod_file_name(items, page, args[3], cfg)
                labels = load_labels()
                if action == "add":
                    labels[file_name] = label_name
                    save_labels(labels)
                    last_operation = f'Label added: {file_name} -> {label_name}'
                else:
                    if labels.get(file_name) == label_name:
                        labels.pop(file_name, None)
                        save_labels(labels)
                        last_operation = f'Label removed: {file_name} -> {label_name}'
                    else:
                        last_operation = "Label not found."
            else:
                last_operation = 'Use: label add/remove "file name" "labelName"'
            continue
        if low.startswith("o "):
            arg = low.split(" ", 1)[1].strip()
            if arg in ["d", "default"]:
                order_mode = "d"
                print("Order mode set to: default")
            elif arg in ["cd", "created date"]:
                order_mode = "cd"
                last_operation = "Order mode set to: created date"
            else:
                last_operation = "Invalid order mode. Use: d, default, cd, or created date."
            continue
        if low == "a":
            for idx, m in enumerate(shown, start=1):
                if m.installed:
                    print(f"[{idx}/{len(shown)}] Uninstalling {m.name} ...")
                    deactivate_mod(m)
            last_operation = "All on this page uninstalled."
            continue
        if low == "i":
            to_install = [m for m in shown if not m.installed]
            total = len(to_install)
            err = 0
            for idx, m in enumerate(to_install, start=1):
                print(f"[{idx}/{total}] Installing {m.name} ...")
                ok, msg = apply_mod(m)
                if not ok:
                    err += 1
                    print(f"  ERR — {msg}")
            print(f"Installed {len(to_install) - err}/{total} on this page. Errors: {err}.")
            if total > 0 & err > 0:
                pause()
            continue
        page_sel = parse_page_choice(choice)
        if page_sel:
            page = page_sel
            continue
        nums = parse_multi_choice(choice)
        for num in nums:
            if 1 <= num <= len(shown):
                m = shown[num - 1]
                if m.installed:
                    ok, msg = deactivate_mod(m)
                    last_operation = f"Uninstall {m.name}: {'OK' if ok else 'ERR'} — {msg}"
                else:
                    ok, msg = apply_mod(m)
                    last_operation = f"Install {m.name}: {'OK' if ok else 'ERR'} — {msg}"

def menu_presets(cfg: Dict):
    if not ensure_paths(cfg):
        return
    last_operation = ""
    page = 1
    while True:
        os.system("cls" if is_windows() else "clear")
        presets = load_presets()
        keys = list(presets.keys())
        if not keys:
            print("No presets saved.")
        page, pages = paginate(len(keys) if keys else 1, page, cfg)
        page_keys = page_slice(keys, page, cfg)

        items = discover_mods(cfg)
        installed_set = {m.name for m in items if m.installed}
        print("Presets — save/apply(toggle)/delete")
        print("=" * PRINT_SIZE)
        for i, key in enumerate(page_keys, 1):
            mods = presets[key]
            all_on = bool(mods) and all(nm in installed_set for nm in mods)
            mark = "[X]" if all_on else "[ ]"
            print(f"{i:2d}) {mark} {key}  — {len(mods)} mods")
        print("\n")
        print_pager(pages, page)
        print("Commands:")
        print("  - numbers (comma-separated): toggle selected preset(s)")
        print("  - s: save current installed as a new preset (will ask for name)")
        print("  - d N,N2,...: delete selected presets by number(s)")
        print("  - pN: go to page N   |  0: back")
        print(f"    {last_operation}")
        choice = prompt("> ").strip()
        if choice == "0":
            return
        low = choice.strip().lower()

        if low == "s" or low == "s:":
            name = prompt("Enter new preset name: ").strip()
            if not name:
                print("Canceled — empty name")
            else:
                ok, msg = save_preset_from_installed(cfg, name)
                print(msg)
            continue

        if low.startswith("s ") or low.startswith("s:"):
            rest = choice.strip()[1:]
            if rest.startswith(":"):
                rest = rest[1:]
            rest = rest.strip()

            if not rest:
                print('Error: missing preset name. Use: s <name> or s "name with spaces"')
                continue

            try:
                args = shlex.split(rest)
            except ValueError:
                print('Error: invalid name format. If you need spaces use: s "імя"')
                continue

            if len(args) != 1:
                print('Error: preset name must be exactly 1 argument. If you need spaces use: s "імя"')
                continue

            name = args[0].strip()
            if not name:
                print("Canceled — empty name")
                continue

            ok, msg = save_preset_from_installed(cfg, name)
            print(msg)
            continue
        low = choice.lower()
        if low.startswith("d ") or low.startswith("del "):
            after = low.split(" ", 1)[1].strip()
            nums = parse_multi_choice(after)
            to_delete = []
            for num in nums:
                if 1 <= num <= len(page_keys):
                    to_delete.append(page_keys[num - 1])
            count, missing = delete_presets_by_names(to_delete)
            last_operation = f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}"
            continue
        page_sel = parse_page_choice(choice)
        if page_sel:
            page = page_sel
            continue
        nums = parse_multi_choice(choice)
        for num in nums:
            if 1 <= num <= len(page_keys):
                name = page_keys[num - 1]
                mods = presets.get(name, [])
                all_on = bool(mods) and all(nm in installed_set for nm in mods)
                if all_on:
                    okc, errc, msgs = deactivate_preset(cfg, name)
                    last_operation = f"Deactivated: {okc}, Errors: {errc}"
                else:
                    okc, errc, msgs = apply_preset(cfg, name)
                    last_operation = f"Installed: {okc}, Errors: {errc}"
                    if errc > 0:
                        pause()
                for m in msgs:
                    print(" - ", m)

def main_menu():
    cfg = load_config()
    while True:
        os.system("cls" if is_windows() else "clear")
        print("Mod Manager — Menu")
        print("=" * PRINT_SIZE)
        print("1) ⚙️ Settings")
        print("2) 🔄 Mods    - list, toggle, search")
        print("3) 🗃️ Presets - save,  apply, toggle, delete")
        print("4) 📋 Open mods source folder")
        print("5) 📂 Open game mods folder")
        print("6) 🛠️ Fix missing mods")
        print("0) 🏠 Exit")
        choice = prompt("Select [0-6]: ").strip()
        if choice == "1":
            menu_settings(cfg)
            cfg = load_config()
        elif choice == "2":
            menu_mods_toggle(cfg)
        elif choice == "3":
            menu_presets(cfg)
        elif choice == "4":
            ms = load_config().get("mods_source_dir", "")
            ok, msg = open_folder(ms)
            print(f"Open source folder: {'OK' if ok else 'ERR'} — {msg}")
        elif choice == "5":
            gs = load_config().get("game_mods_dir", "")
            ok, msg = open_folder(gs)
            print(f"Open game folder: {'OK' if ok else 'ERR'} — {msg}")
        elif choice == "6":
            menu_fix_broken(cfg)
        elif choice == "0":
            print("Goodbye!")
            return
