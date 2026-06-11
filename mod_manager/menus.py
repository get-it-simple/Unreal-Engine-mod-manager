from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Dict, List, Tuple

from app_paths import PRINT_SIZE

from .platform_utils import is_windows
from .storage import (
    GAME_PROFILE_KEYS,
    create_game_profile,
    delete_game_profile,
    game_abbreviation,
    load_config,
    save_config,
    set_active_game_profile,
    update_game_profile,
)
from .mods import (
    discover_mods,
    list_broken_links,
    deactivate_mod,
    mods_view,
    add_label_to_mods,
    remove_label_from_mods,
    deactivate_mods_page,
    apply_mods_page,
    toggle_mods_by_indexes,
)
from .presets import save_preset_from_installed, delete_presets_by_indexes, presets_view, toggle_presets_by_indexes
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
        print(f"1) Page size: {cfg.get('page_size') or 10}")
        print(f"2) Max mod name length: {cfg.get('max_mod_name_len') or 28}")
        print(f"3) Max preset name length: {cfg.get('max_preset_name_len') or 28}")
        print(f"4) Max label name length: {cfg.get('max_label_name_len') or 12}")
        print("\n0) Save and back\n")
        choice = prompt("Select [0-4]: ").strip()
        if choice == "1":
            p = prompt("Enter page size: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["page_size"] = int(p)
            else:
                print("incorect format, please enter a number")
        elif choice == "2":
            p = prompt("Enter max mod name length: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["max_mod_name_len"] = int(p)
        elif choice == "3":
            p = prompt("Enter max preset name length: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["max_preset_name_len"] = int(p)
        elif choice == "4":
            p = prompt("Enter max label name length: ").strip()
            if p.isdigit() and int(p) > 0:
                cfg["max_label_name_len"] = int(p)
        elif choice == "0":
            save_config(cfg)
            print("Saved.")
            return

def _prompt_game_profile(existing: Dict | None = None) -> Dict | None:
    existing = existing or {}
    name = prompt(f"Game name [{existing.get('name', '')}]: ").strip() or existing.get("name", "")
    if not name:
        print("Canceled - empty game name.")
        return None
    values = {"name": name}
    labels = {
        "game_mods_dir": "Game mods folder",
        "mods_source_dir": "Mods source folder",
        "mod_extensions": "Mod file extensions (e.g. .pak,.utoc; add 'folders' to include subfolders)",
        "mod_recursive_scan": "Recursively scan subfolders for mods",
        "link_prefix": "Link prefix",
    }
    for key in GAME_PROFILE_KEYS:
        if key == "mod_recursive_scan":
            current_bool = bool(existing.get(key))
            answer = prompt(f"{labels[key]} (y/n) [{'y' if current_bool else 'n'}]: ").strip().lower()
            values[key] = (answer in {"y", "yes"}) if answer else current_bool
            continue
        current = str(existing.get(key, ""))
        value = prompt(f"{labels[key]} [{current}]: ").strip().strip('"')
        values[key] = str(Path(value).expanduser()) if value and key.endswith("_dir") else (value or current)
    return values

def menu_games(cfg: Dict):
    while True:
        _clear()
        cfg = load_config()
        active_id = cfg.get("active_game_profile_id", "")
        profiles = cfg.get("game_profiles", []) or []
        print("Games")
        print("=" * PRINT_SIZE)
        if not profiles:
            print("No game profiles.")
        for i, profile in enumerate(profiles, 1):
            mark = "*" if profile.get("id") == active_id else " "
            print(f"{i}) [{mark}] {game_abbreviation(profile.get('name', ''))} {profile.get('name')}")
        print("\na) Add  |  eN Edit  |  dN Delete  |  number Select  |  0 Back")
        choice = prompt("> ").strip().lower()
        if choice == "0":
            return
        if choice == "a":
            values = _prompt_game_profile()
            if values:
                create_game_profile(values.pop("name"), values, cfg)
                save_config(cfg)
            continue
        if choice.startswith("e") and choice[1:].isdigit():
            idx = int(choice[1:]) - 1
            if 0 <= idx < len(profiles):
                values = _prompt_game_profile(profiles[idx])
                if values:
                    update_game_profile(cfg, profiles[idx]["id"], values)
                    save_config(cfg)
            continue
        if choice.startswith("d") and choice[1:].isdigit():
            idx = int(choice[1:]) - 1
            if 0 <= idx < len(profiles):
                delete_game_profile(cfg, profiles[idx]["id"])
                save_config(cfg)
            continue
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(profiles):
                set_active_game_profile(cfg, profiles[idx]["id"])
                save_config(cfg)
            continue

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
        items, shown, page, pages, labels = mods_view(cfg, page, label_filter, search_query, order_mode)

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
                    if cmd == "l+":
                        last_operation = add_label_to_mods(label_name, targets)
                    else:
                        last_operation = remove_label_from_mods(label_name, targets)
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
                target_page = max(1, int(args[0])) if args and args[0].isdigit() else page
                if cmd == "uninstall":
                    target_page, _count = deactivate_mods_page(cfg, target_page, label_filter, search_query, order_mode)
                    last_operation = f"All on page {target_page} uninstalled."
                else:
                    target_page, total, err = apply_mods_page(cfg, target_page, label_filter, search_query, order_mode)
                    if total > 0 and err > 0:
                        pause()
                    last_operation = f"Installed {total - err}/{total} on page {target_page}. Errors: {err}."
                continue
            if cmd in ["toggle"]:
                nums = parse_multi_choice(" ".join(args))
                last_operation = toggle_mods_by_indexes(shown, nums)
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
                if action == "add":
                    last_operation = add_label_to_mods(label_name, [file_name])
                else:
                    last_operation = remove_label_from_mods(label_name, [file_name])
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
            deactivate_mods_page(cfg, page, label_filter, search_query, order_mode)
            last_operation = "All on this page uninstalled."
            continue
        if low == "i":
            _target_page, total, err = apply_mods_page(cfg, page, label_filter, search_query, order_mode)
            if total > 0 and err > 0:
                pause()
            continue
        page_sel = parse_page_choice(choice)
        if page_sel:
            page = page_sel
            continue
        nums = parse_multi_choice(choice)
        last_operation = toggle_mods_by_indexes(shown, nums)

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
        presets, keys, page_keys, page, pages = presets_view(cfg, page)

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
                count, missing = delete_presets_by_indexes(cfg, page, nums)
                last_operation = f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}"
                continue
            if cmd in ["toggle"]:
                nums = parse_multi_choice(" ".join(args))
                last_operation, msgs, has_errors = toggle_presets_by_indexes(cfg, page, nums, installed_set)
                if has_errors:
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
            count, missing = delete_presets_by_indexes(cfg, page, nums)
            last_operation = f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}"
            continue
        page_sel = parse_page_choice(choice)
        if page_sel:
            page = page_sel
            continue
        nums = parse_multi_choice(choice)
        last_operation, msgs, has_errors = toggle_presets_by_indexes(cfg, page, nums, installed_set)
        if has_errors:
            pause()
        for m in msgs:
            print(" - ", m)

def main_menu():
    cfg = load_config()
    while True:
        _clear()
        print("Mod Manager — Menu")
        print("=" * PRINT_SIZE)
        active = next((p for p in cfg.get("game_profiles", []) if p.get("id") == cfg.get("active_game_profile_id")), None)
        print(f"Game: {active.get('name') if active else '-not selected-'}")
        print("1) 🎮 Games")
        print("2) ⚙️ Settings")
        print("3) 🔄 Mods    - list, toggle, search")
        print("4) 🗃️ Presets - save,  apply, toggle, delete")
        print("5) 📋 Open mods source folder")
        print("6) 📂 Open game mods folder")
        print("7) 🛠️ Fix missing mods")
        print("0) 🏠 Exit")
        choice = prompt("Select [0-7]: ").strip()
        if choice == "1":
            menu_games(cfg)
            cfg = load_config()
        elif choice == "2":
            menu_settings(cfg)
            cfg = load_config()
        elif choice == "3":
            menu_mods_toggle(cfg)
        elif choice == "4":
            menu_presets(cfg)
        elif choice == "5":
            ms = load_config().get("mods_source_dir", "")
            ok, msg = open_folder(ms)
            print(f"Open source folder: {'OK' if ok else 'ERR'} — {msg}")
        elif choice == "6":
            gs = load_config().get("game_mods_dir", "")
            ok, msg = open_folder(gs)
            print(f"Open game folder: {'OK' if ok else 'ERR'} — {msg}")
        elif choice == "7":
            menu_fix_broken(cfg)
        elif choice == "0":
            print("Goodbye!")
            return
