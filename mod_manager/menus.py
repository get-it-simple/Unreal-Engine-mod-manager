from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Dict, List, Tuple

from app_paths import PRINT_SIZE

from .platform_utils import is_windows
from .storage import load_config, save_config, load_labels, save_labels, load_presets
from .mods import discover_mods, list_broken_links, deactivate_mod, apply_mod, apply_mods_batch
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
    smart_prompt,
    truncate_text,
    format_order_short,
)

def _clear():
    os.system("cls" if is_windows() else "clear")

def _as_int(s: str) -> int | None:
    if s and s.isdigit():
        return int(s)
    return None

def _shown_name(shown, idx_str: str) -> str | None:
    n = _as_int(idx_str)
    if n is None:
        return None
    if 1 <= n <= len(shown):
        return shown[n - 1].name
    return None

def _parse_slash(choice: str) -> Tuple[str, List[str]] | None:
    raw = (choice or "").strip()
    if not raw.startswith("/"):
        return None
    if raw == "/":
        return "/", []
    try:
        args = shlex.split(raw[1:])
    except ValueError:
        return None
    if not args:
        return "/", []
    cmd = args[0].lower()
    return cmd, args[1:]

def _mods_cmds() -> List[str]:
    return [
        "/help",
        "/search",
        "/l ",
        "/l+ ",
        "/l- ",
        "/order default",
        "/order created date",
        "/toggle ",
        "/uninstall",
        "/install",
        "/page ",
        "/back",
        "/exit",
    ]

def _presets_cmds() -> List[str]:
    return [
        "/help",
        "/toggle ",
        "/save ",
        "/delete ",
        "/page ",
        "/back",
        "/exit",
    ]

def _filter_text(label_filter: str, search_query: str) -> str:
    parts = []
    if label_filter:
        parts.append(f"l:{label_filter}")
    if search_query:
        parts.append(f"s:{search_query}")
    return " | ".join(parts) if parts else "-"

def _mod_display_name(cfg: Dict, name: str) -> str:
    return truncate_text(name, int(cfg.get("max_mod_name_len", 28)))

def _preset_display_name(cfg: Dict, name: str) -> str:
    return truncate_text(name, int(cfg.get("max_preset_name_len", 28)))

def _label_display_name(cfg: Dict, name: str) -> str:
    return truncate_text(name, int(cfg.get("max_label_name_len", 12)))

def _print_mods_help():
    print("Commands — Mods")
    print("=" * PRINT_SIZE)
    print('use "text 1" for text with spaces')
    print("/search <text>         Search mods by name (empty = clear)")
    print('/l <label>             Filter by label (empty = clear)')
    print("/l+ <label> <indexes>  Add label to items on current page")
    print("/l- <label> <indexes>  Remove label from items on current page (if matches)")
    print("/order default         Sort by default")
    print("/order created date    Sort by created date")
    print("/toggle 1,3,5          Toggle indexes (install/uninstall)")
    print("/uninstall [page]      Uninstall all on page (current if omitted)")
    print("/install [page]        Install all on page (current if omitted)")
    print("/page <n>              Go to page")
    print("/back                  Back")
    print("/exit                  Exit")
    print("\nExamples:")
    print("/search ui")
    print("/l label_1")
    print("/l+ label_1 3")
    print("/l+ label_1 1,2,3,4,5,11")
    print("/l- label_1 3")
    print("/l- label_1 1,2,3,4,5,11")
    print("/toggle 1,3,5")
    print("/install 2")
    print("/uninstall")

def _print_presets_help():
    print("Commands — Presets")
    print("=" * PRINT_SIZE)
    print("/toggle 1,3,5          Toggle presets (apply/deactivate)")
    print("/save <name>           Save current installed mods as preset")
    print("/delete 1,3,5          Delete presets by indexes on current page")
    print("/page <n>              Go to page")
    print("/back                  Back")
    print("/exit                  Exit")
    print("\nExamples:")
    print('/save "My preset"')
    print("/toggle 1")
    print("/delete 2,4")


def menu_fix_broken(cfg: Dict):
    if not ensure_paths(cfg):
        return
    page = 1
    while True:
        _clear()
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
        _clear()
        print("Settings")
        print("=" * PRINT_SIZE)
        print(f"1) Game mods folder: {cfg.get('game_mods_dir') or '-not set-'}")
        print(f"2) Mods source folder: {cfg.get('mods_source_dir') or '-not set-'}")
        print(f"3) Mod file extensions: {cfg.get('mod_extensions') or '(all)'}")
        print(f"4) Page size: {cfg.get('page_size') or 10}")
        print(f"5) Max mod name length: {cfg.get('max_mod_name_len') or 28}")
        print(f"6) Max preset name length: {cfg.get('max_preset_name_len') or 28}")
        print(f"7) Max label name length: {cfg.get('max_label_name_len') or 12}")
        print("\n0) Save and back\n")
        choice = prompt("Select [0-7]: ").strip()
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
        elif choice == "5":
            p = prompt("Enter max mod name length: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["max_mod_name_len"] = int(p)
        elif choice == "6":
            p = prompt("Enter max preset name length: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["max_preset_name_len"] = int(p)
        elif choice == "7":
            p = prompt("Enter max label name length: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["max_label_name_len"] = int(p)
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
        _clear()
        from .cli_utils import _PT_AVAILABLE
        if not _PT_AVAILABLE:
            print("Advanced completion disabled. Install: pip install prompt_toolkit\n")
        items_all = discover_mods(cfg)
        items = filter_items_by_query(items_all, search_query)
        labels = load_labels()
        if label_filter:
            lf = label_filter.lower()
            items = [m for m in items if (labels.get(m.name) or "").lower() == lf]
        items = sort_items(items, order_mode)
        page, pages = paginate(len(items) if items else 1, page, cfg)
        shown = page_slice(items, page, cfg) if items else []

        print(f"Page {page}/{pages}    Order: {format_order_short(order_mode)}    Filter: {_filter_text(label_filter, search_query)}")
        print("=" * PRINT_SIZE)

        if not items:
            print("No mods.")
        else:
            idx_w = max(2, len(str(int(cfg.get("page_size", 10)))))

            name_cells = []
            label_cells = []

            for m in shown:
                name_cells.append(_mod_display_name(cfg, m.name))
                lbl = labels.get(m.name) if labels else None
                label_cells.append(_label_display_name(cfg, lbl) if lbl else "-")

            name_w = max(1, max((len(x) for x in name_cells), default=1))

            for i, m in enumerate(shown, 1):
                mark = "[X]" if m.installed else "[ ]"
                name_disp = name_cells[i - 1]
                lbl_disp = label_cells[i - 1]
                print(
                    f"{i:>{idx_w}}.  {mark} "
                    f"{name_disp:<{name_w}}  "
                    f"- [{lbl_disp}]"
                )

        if last_operation:
            print(f"\n{last_operation}")
        print("\nType / for commands")

        choice = smart_prompt("> ", _mods_cmds).strip()
        if not choice:
            print("Type / for commands")
            continue

        parsed = _parse_slash(choice)
        if parsed:
            cmd, args = parsed
            if cmd in ["help"]:
                _print_mods_help()
                pause()
                continue
            if cmd in ["back"]:
                return
            if cmd in ["exit"]:
                raise SystemExit(0)
            if cmd in ["search"]:
                if args:
                    search_query = " ".join(args).strip()
                else:
                    search_query = prompt("Search: ").strip()
                page = 1
                continue
            if cmd in ["l"]:
                label_filter = " ".join(args).strip().strip('"') if args else ""
                page = 1
                continue
            if cmd in ["l+", "l-"]:
                if len(args) >= 2:
                    label_name = args[0]
                    idxs = parse_multi_choice(" ".join(args[1:]))
                    if not idxs:
                        last_operation = "Invalid index."
                        continue
                    targets = []
                    for num in idxs:
                        if 1 <= num <= len(shown):
                            targets.append(shown[num - 1].name)
                    if not targets:
                        last_operation = "Invalid index."
                        continue
                    labels = load_labels()
                    if cmd == "l+":
                        for file_name in targets:
                            labels[file_name] = label_name
                        save_labels(labels)
                        last_operation = f"Label added: {label_name} -> {', '.join(targets)}"
                    else:
                        removed = []
                        for file_name in targets:
                            if labels.get(file_name) == label_name:
                                labels.pop(file_name, None)
                                removed.append(file_name)
                        if removed:
                            save_labels(labels)
                            last_operation = f"Label removed: {label_name} -> {', '.join(removed)}"
                        else:
                            last_operation = "Label not found."
                else:
                    last_operation = "Use: /l+ <label> <indexes> or /l- <label> <indexes>"
                continue
            if cmd in ["order"]:
                mode = " ".join(args).strip().lower()
                if mode in ["d", "default"]:
                    order_mode = "d"
                    last_operation = "Order mode set to: default"
                elif mode in ["cd", "created date"]:
                    order_mode = "cd"
                    last_operation = "Order mode set to: created date"
                else:
                    last_operation = "Invalid order mode."
                continue
            if cmd in ["page"]:
                if args and args[0].isdigit():
                    page = max(1, int(args[0]))
                continue
            if cmd in ["uninstall", "install"]:
                target_page = page
                if args and args[0].isdigit():
                    target_page = max(1, int(args[0]))
                target_page, _pages = paginate(len(items) if items else 1, target_page, cfg)
                target_shown = page_slice(items, target_page, cfg) if items else []
                if cmd == "uninstall":
                    for m in target_shown:
                        if m.installed:
                            deactivate_mod(m)
                    last_operation = f"All on page {target_page} uninstalled."
                else:
                    to_install = [m for m in target_shown if not m.installed]
                    total = len(to_install)
                    err = 0
                    for idx, m in enumerate(to_install, start=1):
                        print(f"[{idx}/{total}] Installing {m.name} ...")
                    results = apply_mods_batch(to_install)
                    for m, (ok, msg) in zip(to_install, results):
                        if not ok:
                            err += 1
                            print(f"  ERR — {msg}")
                    if total > 0 and err > 0:
                        pause()
                    last_operation = f"Installed {total - err}/{total} on page {target_page}. Errors: {err}."
                continue
            if cmd in ["toggle"]:
                nums = parse_multi_choice(" ".join(args))
                for num in nums:
                    if 1 <= num <= len(shown):
                        m = shown[num - 1]
                        if m.installed:
                            ok, msg = deactivate_mod(m)
                            last_operation = f"Uninstall {m.name}: {'OK' if ok else 'ERR'} — {msg}"
                        else:
                            ok, msg = apply_mod(m)
                            last_operation = f"Install {m.name}: {'OK' if ok else 'ERR'} — {msg}"
                continue
            if cmd == "/":
                continue

        low = choice.lower()
        if low == "0":
            return
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
                file_name = _shown_name(shown, args[3]) or args[3]
                labels = load_labels()
                if action == "add":
                    labels[file_name] = label_name
                    save_labels(labels)
                    last_operation = f"Label added: {file_name} -> {label_name}"
                else:
                    if labels.get(file_name) == label_name:
                        labels.pop(file_name, None)
                        save_labels(labels)
                        last_operation = f"Label removed: {file_name} -> {label_name}"
                    else:
                        last_operation = "Label not found."
            else:
                last_operation = 'Use: label add/remove "file name" "labelName"'
            continue
        if low.startswith("o "):
            arg = low.split(" ", 1)[1].strip()
            if arg in ["d", "default"]:
                order_mode = "d"
                last_operation = "Order mode set to: default"
            elif arg in ["cd", "created date"]:
                order_mode = "cd"
                last_operation = "Order mode set to: created date"
            else:
                last_operation = "Invalid order mode. Use: d, default, cd, or created date."
            continue
        if low == "a":
            for m in shown:
                if m.installed:
                    deactivate_mod(m)
            last_operation = "All on this page uninstalled."
            continue
        if low == "i":
            to_install = [m for m in shown if not m.installed]
            total = len(to_install)
            err = 0
            for idx, m in enumerate(to_install, start=1):
                print(f"[{idx}/{total}] Installing {m.name} ...")
            results = apply_mods_batch(to_install)
            for m, (ok, msg) in zip(to_install, results):
                if not ok:
                    err += 1
                    print(f"  ERR — {msg}")
            if total > 0 and err > 0:
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
        _clear()
        from .cli_utils import _PT_AVAILABLE
        if not _PT_AVAILABLE:
            print("Advanced completion disabled. Install: pip install prompt_toolkit\n")
        presets = load_presets()
        keys = list(presets.keys())
        if not keys:
            keys = []
        page, pages = paginate(len(keys) if keys else 1, page, cfg)
        page_keys = page_slice(keys, page, cfg)

        items = discover_mods(cfg)
        installed_set = {m.name for m in items if m.installed}

        print(f"Page {page}/{pages}    Order: d    Filter: -")
        print("=" * PRINT_SIZE)
        if not keys:
            print("No presets saved.")
        else:
            idx_w = max(2, len(str(int(cfg.get("page_size", 10)))))
            for i, key in enumerate(page_keys, 1):
                mods = presets[key]
                all_on = bool(mods) and all(nm in installed_set for nm in mods)
                mark = "[X]" if all_on else "[ ]"
                key_disp = _preset_display_name(cfg, key)
                print(f"{i:>{idx_w}}.  {mark} {key_disp} - [{len(mods)}]")

        if last_operation:
            print(f"\n{last_operation}")
        print("\nType / for commands")

        choice = smart_prompt("> ", _presets_cmds).strip()
        if not choice:
            print("Type / for commands")
            continue

        parsed = _parse_slash(choice)
        parsed = _parse_slash(choice)
        if parsed:
            cmd, args = parsed
            if cmd in ["help"]:
                _print_presets_help()
                pause()
                continue
            if cmd in ["back"]:
                return
            if cmd in ["exit"]:
                raise SystemExit(0)
            if cmd in ["page"]:
                if args and args[0].isdigit():
                    page = max(1, int(args[0]))
                continue
            if cmd in ["save"]:
                name = " ".join(args).strip() if args else prompt("Enter new preset name: ").strip()
                if not name:
                    last_operation = "Canceled — empty name"
                else:
                    ok, msg = save_preset_from_installed(cfg, name)
                    last_operation = msg
                continue
            if cmd in ["delete"]:
                after = " ".join(args).strip()
                nums = parse_multi_choice(after)
                to_delete = []
                for num in nums:
                    if 1 <= num <= len(page_keys):
                        to_delete.append(page_keys[num - 1])
                count, missing = delete_presets_by_names(to_delete)
                last_operation = f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}"
                continue
            if cmd in ["toggle"]:
                nums = parse_multi_choice(" ".join(args))
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
                continue
            if cmd == "/":
                continue

        low = choice.strip().lower()
        if low == "0":
            return
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
        _clear()
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