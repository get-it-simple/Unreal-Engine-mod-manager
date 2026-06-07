from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from .models import ModItem
from .platform_utils import is_windows
from .storage import load_labels

_PT_AVAILABLE = False

def prompt(msg: str) -> str:
    try:
        return input(msg)
    except EOFError:
        return ""

def pause(msg: str = "Press Enter to continue...") -> None:
    prompt(f"{msg}")

def truncate_text(text: str, max_len: int, suffix: str = "...") -> str:
    if max_len <= 0:
        return ""
    if text is None:
        return ""
    s = str(text)
    if len(s) <= max_len:
        return s
    if max_len <= len(suffix):
        return s[:max_len]
    return s[: max_len - len(suffix)] + suffix

def format_order_short(order_mode: str) -> str:
    if order_mode in ["cd", "created date"]:
        return "cd"
    return "d"

def ensure_paths(cfg: Dict) -> bool:
    gs = cfg.get("game_mods_dir")
    ms = cfg.get("mods_source_dir")
    if not gs or not ms:
        print("Please configure paths first.")
        return False
    Path(gs).mkdir(parents=True, exist_ok=True)
    Path(ms).mkdir(parents=True, exist_ok=True)
    return True

def parse_multi_choice(choice: str) -> List[int]:
    parts = [p.strip() for p in choice.split(",") if p.strip()]
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
    return nums

def parse_page_choice(choice: str) -> int | None:
    c = choice.strip().lower()
    if c.startswith("p") and c[1:].isdigit():
        return int(c[1:])
    return None

def paginate(total: int, page: int, cfg: Dict) -> Tuple[int, int]:
    pages = max(1, (total + int(cfg.get("page_size", 10)) - 1) // int(cfg.get("page_size", 10)))
    page = max(1, min(page, pages))
    return page, pages

def page_slice(items: List, page: int, cfg: Dict) -> List:
    start = (page - 1) * int(cfg.get("page_size", 10))
    end = start + int(cfg.get("page_size", 10))
    return items[start:end]

def print_pager(pages: int, current: int):
    if pages <= 1:
        return
    labels = []
    for i in range(1, pages + 1):
        labels.append(f"[p{i}]" if i != current else f"(p{i})")
    print("Pages:")
    for i in range(0, len(labels), 10):
        print(" ".join(labels[i:i+10]))

def _windows_explorer_select_arg(target: Path) -> str:
    return f'/select,"{target}"'

def select_in_explorer(path: Path) -> None:
    target = Path(path).expanduser()
    try:
        if is_windows():
            target = target.absolute()
            if target.exists() or target.is_symlink():
                subprocess.Popen(
                    ["explorer", _windows_explorer_select_arg(target)],
                    creationflags=0x08000000,
                )
            elif target.parent.exists():
                subprocess.Popen(
                    ["explorer", str(target.parent.absolute())],
                    creationflags=0x08000000,
                )
        elif platform.system() == "Darwin":
            if target.exists():
                subprocess.Popen(["open", "-R", str(target)])
            elif target.parent.exists():
                subprocess.Popen(["open", str(target.parent)])
    except Exception:
        pass


def open_folder(path_str: str) -> Tuple[bool, str]:
    try:
        if not path_str:
            return False, "Path is empty"
        p = Path(path_str).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        if is_windows():
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True, "Opened"
    except Exception as e:
        return False, str(e)

def filter_items_by_query(items: List[ModItem], query: str) -> List[ModItem]:
    q = (query or "").lower()
    if not q:
        return items
    return [m for m in items if q in m.name.lower()]

def sort_items(items: List[ModItem], order_mode: str) -> List[ModItem]:
    if order_mode in ["cd", "created date"]:
        try:
            return sorted(items, key=lambda m: m.src.stat().st_ctime, reverse=True)
        except Exception:
            pass
    return sorted(items, key=lambda m: ((not m.is_dir), m.name.lower()))

def _normalize_label(s: str) -> str:
    s = (s or "").strip().lower().replace("_", " ")
    s = " ".join(s.split())
    return s

def _labels_for_completion() -> List[str]:
    try:
        data = load_labels() or {}
    except Exception:
        data = {}
    seen = set()
    out: List[str] = []
    for _k, v in data.items():
        if not v:
            continue
        disp = " ".join(str(v).replace("_", " ").split())
        key = _normalize_label(disp)
        if key and key not in seen:
            seen.add(key)
            out.append(disp)
    return out

def _try_prompt_toolkit():
    global _PT_AVAILABLE
    try:
        from prompt_toolkit import prompt as pt_prompt
        from prompt_toolkit.formatted_text import FormattedText
        _PT_AVAILABLE = True
        return pt_prompt, FormattedText
    except Exception:
        _PT_AVAILABLE = False
        return None, None

class _CmdCompleter:
    def __init__(self, get_cmds: Callable[[], List[str]]):
        self.get_cmds = get_cmds

    def get_completions(self, document, complete_event):
        text = document.text or ""
        if not text.startswith("/"):
            return

        from prompt_toolkit.completion import Completion

        base = text.lower()
        cmds = self.get_cmds() or []

        for c in cmds:
            if c.lower().startswith(base):
                yield Completion(c, start_position=-len(text), display=c)

        prefix = ""
        if base.startswith("/l+ "):
            prefix = "/l+ "
        elif base.startswith("/l- "):
            prefix = "/l- "
        elif base.startswith("/l "):
            prefix = "/l "

        if prefix:
            rest = text[len(prefix):]
            frag = rest.strip()
            if frag.startswith('"') or frag.startswith("'"):
                frag = frag[1:]
            nf = _normalize_label(frag)
            for lbl in _labels_for_completion():
                if not nf or _normalize_label(lbl).startswith(nf):
                    yield Completion(f'"{lbl}" ', start_position=-len(rest), display=lbl)

        yield Completion("", start_position=0, display="(keep typing)")

    async def get_completions_async(self, document, complete_event):
        for c in self.get_completions(document, complete_event):
            yield c

def smart_prompt(
    msg: str,
    get_commands: Callable[[], List[str]] | None = None,
    placeholder: str = "Type / for commands",
) -> str:
    pt_prompt, FormattedText = _try_prompt_toolkit()

    if not pt_prompt or not get_commands:
        text = prompt(msg)
        if text.strip() == "/" and get_commands:
            print("\nAvailable commands:")
            for c in get_commands():
                print(" ", c)
            prompt("\nPress Enter to continue...")
            return ""
        return text

    completer = _CmdCompleter(get_commands)

    def bottom_toolbar():
        try:
            from prompt_toolkit.application.current import get_app
            buf = get_app().current_buffer
            return FormattedText([("", placeholder)]) if not (buf.text or "") else ""
        except Exception:
            return ""

    try:
        return pt_prompt(
            msg,
            completer=completer,
            complete_while_typing=True,
            bottom_toolbar=bottom_toolbar,
        )
    except (EOFError, KeyboardInterrupt):
        return ""
