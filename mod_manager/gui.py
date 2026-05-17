from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List

from .cli_utils import ensure_paths, open_folder
from .image import load_scaled as _load_image_gdi
from .log import logger
from .mods import (
    add_label_to_mods,
    apply_mods_page,
    deactivate_mod,
    deactivate_mods_page,
    import_mod_file,
    import_mod_image,
    is_image_file,
    is_mod_file,
    list_broken_links,
    mod_image_path,
    mods_view,
    mods_records,
    remove_label_from_mods,
    toggle_mods_by_indexes,
)
from .presets import delete_presets_by_indexes, presets_records, presets_view, save_preset_from_installed, toggle_presets_by_indexes
from .dragdrop import WindowsDropTarget
from .storage import load_config, save_config

class AutocompleteCombobox(ttk.Combobox):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._all_values: List[str] = []
        self.bind("<KeyRelease>", self._on_keyrelease)

    def set_completion_values(self, values: List[str]) -> None:
        self._all_values = sorted({str(v) for v in values if v})
        self["values"] = self._all_values

    def _on_keyrelease(self, event) -> None:
        if event.keysym in ["BackSpace", "Left", "Right", "Up", "Down", "Return", "Escape", "Tab"]:
            return
        text = self.get().lower()
        self["values"] = [v for v in self._all_values if text in v.lower()] if text else self._all_values

class WrapFrame(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.items = []
        self.bind("<Configure>", lambda _event: self.after_idle(self._arrange))

    def add(self, widget, padx=0, pady=3, sticky="w") -> None:
        self.items.append((widget, padx, pady, sticky))
        self.after_idle(self._arrange)

    def _pad_width(self, padx) -> int:
        if isinstance(padx, tuple):
            return int(padx[0]) + int(padx[1])
        return int(padx) * 2

    def _arrange(self) -> None:
        width = max(1, self.winfo_width())
        row = 0
        col = 0
        used = 0
        for widget, padx, pady, sticky in self.items:
            widget.grid_forget()
            need = widget.winfo_reqwidth() + self._pad_width(padx)
            if col > 0 and used + need > width:
                row += 1
                col = 0
                used = 0
            widget.grid(row=row, column=col, sticky=sticky, padx=padx, pady=pady)
            used += need
            col += 1

class _Tooltip:
    _DELAY = 100

    def __init__(self, widget, text: str):
        self._widget = widget
        self._text = text
        self._tip = None
        self._job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        widget.bind("<ButtonPress>", self._cancel, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._job = self._widget.after(self._DELAY, self._show)

    def _cancel(self, _=None):
        if self._job:
            self._widget.after_cancel(self._job)
            self._job = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        if self._tip:
            return
        x = self._widget.winfo_rootx()
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(self._tip, text=self._text, relief="solid", padding=(6, 3)).pack()


class ModManagerGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mod Manager")
        self.geometry("980x640")
        self.minsize(880, 560)
        self.cfg = load_config()
        self.mod_page = tk.IntVar(value=1)
        self.preset_page = tk.IntVar(value=1)
        self.search_var = tk.StringVar()
        self.label_filter_var = tk.StringVar()
        self.label_edit_var = tk.StringVar()
        self.order_var = tk.StringVar(value="Default")
        self.status_var = tk.StringVar()
        self.placeholder_images: Dict[str, tk.PhotoImage] = {}
        self.current_mod_items = []
        self.current_mods_shown = []
        self.current_mod_labels = {}
        self.current_broken = []
        self.drop_targets = []
        self.busy = False
        self.action_widgets = []
        self.mod_sort_key = "d"
        self.mod_sort_reverse = False
        self.preset_sort_key = "name"
        self.preset_sort_reverse = False
        self.button_scale_values = ["25%", "50%", "75%", "100%", "125%", "150%", "175%", "200%"]
        self._apply_gui_style()
        self._build()
        self.drop_targets.append(WindowsDropTarget(self, self._handle_mods_drop))
        self.drop_targets.append(WindowsDropTarget(self.mods_tree, self._handle_mods_drop))
        self.refresh_all()

    def _button_scale(self) -> float:
        try:
            value = str(self.cfg.get("button_size_percent", 100)).strip().rstrip("%")
            return max(25, int(value)) / 100
        except Exception:
            return 1

    def _apply_gui_style(self) -> None:
        font_family = (self.cfg.get("gui_font_family") or "").strip()
        try:
            font_size = max(6, int(self.cfg.get("gui_font_size", 10)))
        except Exception:
            font_size = 10
        for font_name in ["TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"]:
            try:
                options = {"size": font_size}
                if font_family:
                    options["family"] = font_family
                tkfont.nametofont(font_name).configure(**options)
            except tk.TclError:
                pass
        scale = self._button_scale()
        style = ttk.Style(self)
        style.configure("TButton", padding=(int(12 * scale), int(7 * scale)))
        style.configure("TSpinbox", padding=(int(6 * scale), int(5 * scale)))
        style.configure("TCombobox", padding=(int(4 * scale), int(3 * scale)))
        style.configure("Treeview", rowheight=max(30, int(34 * scale)))
        style.configure("Mods.Treeview", rowheight=max(30, int(34 * scale)))

    def _apply_button_widths(self) -> None:
        scale = self._button_scale()
        for widget in self.action_widgets:
            try:
                text = str(widget.cget("text"))
                if text:
                    w = max(3, int(4 * scale)) if len(text) <= 3 else max(int(14 * scale), len(text) + 2)
                    widget.configure(width=w)
                    if isinstance(widget.master, WrapFrame):
                        widget.master.after_idle(widget.master._arrange)
            except tk.TclError:
                pass

    def _build(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        self.mods_tab = ttk.Frame(notebook, padding=8)
        self.presets_tab = ttk.Frame(notebook, padding=8)
        self.settings_tab = ttk.Frame(notebook, padding=8)
        self.broken_tab = ttk.Frame(notebook, padding=8)
        notebook.add(self.mods_tab, text="Mods")
        notebook.add(self.presets_tab, text="Presets")
        notebook.add(self.settings_tab, text="Settings")
        notebook.add(self.broken_tab, text="Broken")
        self._build_mods()
        self._build_presets()
        self._build_settings()
        self._build_broken()
        status = ttk.Label(root, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", pady=(8, 0))

    def _button(self, master, text: str, command: Callable, tooltip: str = ""):
        scale = self._button_scale()
        width = max(3, int(4 * scale)) if len(text) <= 3 else max(int(14 * scale), len(text) + 2)
        btn = ttk.Button(master, text=text, command=command, width=width)
        if tooltip:
            _Tooltip(btn, tooltip)
        self.action_widgets.append(btn)
        return btn

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in self.action_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        self.configure(cursor="watch" if busy else "")
        if text:
            self.status_var.set(text)
        self.update_idletasks()

    def _run_action(self, label: str, worker: Callable, done: Callable | None = None) -> None:
        if self.busy:
            return
        logger.info("action: %s", label)
        self._set_busy(True, f"{label}...")

        def run():
            result = None
            error = None
            try:
                result = worker()
            except Exception as exc:
                error = exc
            self.after(0, lambda: self._finish_action(error, result, done))

        threading.Thread(target=run, daemon=True).start()

    def _finish_action(self, error, result, done: Callable | None) -> None:
        try:
            if error:
                logger.error("action error: %s", error)
                self.status_var.set(str(error))
                messagebox.showerror("Error", str(error))
            elif done:
                done(result)
                logger.info("action result: %s", self.status_var.get())
        finally:
            self._set_busy(False)

    def _build_mods(self) -> None:
        top = WrapFrame(self.mods_tab)
        top.pack(fill="x")
        top.add(ttk.Label(top, text="Search"))
        self.search_box = AutocompleteCombobox(top, textvariable=self.search_var, width=24)
        top.add(self.search_box, padx=(6, 12))
        top.add(ttk.Label(top, text="Label"))
        self.label_filter_box = AutocompleteCombobox(top, textvariable=self.label_filter_var, width=18)
        top.add(self.label_filter_box, padx=(6, 12))
        top.add(ttk.Label(top, text="Order"))
        top.add(ttk.Combobox(top, textvariable=self.order_var, values=["Default", "Created date"], width=14, state="readonly"), padx=(6, 12))
        top.add(self._button(top, "↺", self._mods_search, "Search / Refresh"))
        top.add(self._button(top, "✕", self._mods_clear, "Clear"), padx=(6, 0))
        self.mods_tree = ttk.Treeview(self.mods_tab, columns=("name", "label", "last"), show="tree headings", selectmode="extended", style="Mods.Treeview")
        self.mods_tree.heading("#0", text="")
        self.mods_tree.heading("name", text="Mod", command=lambda: self._sort_mods("name"))
        self.mods_tree.heading("label", text="Label", command=lambda: self._sort_mods("label"))
        self.mods_tree.heading("last", text="Last managed", command=lambda: self._sort_mods("last_managed"))
        self.mods_tree.column("#0", width=int(self.cfg.get("placeholder_image_col_width", 56)), minwidth=36, stretch=False, anchor="center")
        self.mods_tree.column("name", width=470)
        self.mods_tree.column("label", width=160)
        self.mods_tree.column("last", width=160)
        self.mods_tree.tag_configure("installed", background="#d4edda")
        self.mods_tree.bind("<ButtonRelease-1>", self._save_placeholder_width)
        self.mods_tree.bind("<Double-1>", lambda _: self._toggle_selected_mods())
        actions = WrapFrame(self.mods_tab)
        actions.pack(fill="x", side="bottom")
        self.mods_tree.pack(fill="both", expand=True, pady=8)
        actions.add(self._button(actions, "<", lambda: self._change_mod_page(-1), "Previous page"))
        actions.add(self._button(actions, ">", lambda: self._change_mod_page(1), "Next page"), padx=(6, 12))
        actions.add(ttk.Label(actions, text="Page"))
        mod_page_spin = ttk.Spinbox(actions, from_=1, to=9999, textvariable=self.mod_page, width=6, command=self.refresh_mods)
        self.action_widgets.append(mod_page_spin)
        actions.add(mod_page_spin, padx=(6, 12))
        actions.add(self._button(actions, "▼", self._install_page, "Install page"))
        actions.add(self._button(actions, "▲", self._uninstall_page, "Uninstall page"), padx=(6, 0))
        actions.add(self._button(actions, "⇄", self._toggle_selected_mods, "Toggle selected"), padx=(6, 12))
        actions.add(self._button(actions, "📥", self._import_mod_files, "Import mods"), padx=(6, 0))
        actions.add(self._button(actions, "📂", self._import_mod_folder, "Import folder"), padx=(6, 0))
        actions.add(self._button(actions, "🖼", self._set_mod_image, "Set image"), padx=(6, 12))
        actions.add(ttk.Label(actions, text="Label"))
        self.label_edit_box = AutocompleteCombobox(actions, textvariable=self.label_edit_var, width=18)
        actions.add(self.label_edit_box, padx=(6, 6))
        actions.add(self._button(actions, "+", self._add_label_selected, "Add label"))
        actions.add(self._button(actions, "-", self._remove_label_selected, "Remove label"), padx=(6, 0))

    def _build_presets(self) -> None:
        top = WrapFrame(self.presets_tab)
        top.pack(fill="x")
        top.add(ttk.Label(top, text="Name"))
        self.preset_name_box = AutocompleteCombobox(top, width=30)
        top.add(self.preset_name_box, padx=(6, 8))
        top.add(self._button(top, "Save", self._save_preset))
        top.add(self._button(top, "Refresh", self.refresh_presets), padx=(6, 0))
        self.presets_tree = ttk.Treeview(self.presets_tab, columns=("state", "mods", "last"), show="tree headings", selectmode="extended")
        self.presets_tree.heading("#0", text="Preset", command=lambda: self._sort_presets("name"))
        self.presets_tree.heading("state", text="State", command=lambda: self._sort_presets("state"))
        self.presets_tree.heading("mods", text="Mods", command=lambda: self._sort_presets("mods"))
        self.presets_tree.heading("last", text="Last managed", command=lambda: self._sort_presets("last_managed"))
        self.presets_tree.column("#0", width=460)
        self.presets_tree.column("state", width=90, anchor="center")
        self.presets_tree.column("mods", width=90, anchor="center")
        self.presets_tree.column("last", width=170)
        self.presets_tree.pack(fill="both", expand=True, pady=8)
        actions = WrapFrame(self.presets_tab)
        actions.pack(fill="x")
        actions.add(self._button(actions, "<", lambda: self._change_preset_page(-1), "Previous page"))
        actions.add(self._button(actions, ">", lambda: self._change_preset_page(1), "Next page"), padx=(6, 12))
        actions.add(ttk.Label(actions, text="Page"))
        preset_page_spin = ttk.Spinbox(actions, from_=1, to=9999, textvariable=self.preset_page, width=6, command=self.refresh_presets)
        self.action_widgets.append(preset_page_spin)
        actions.add(preset_page_spin, padx=(6, 12))
        actions.add(self._button(actions, "Toggle Selected", self._toggle_selected_presets))
        actions.add(self._button(actions, "Delete Selected", self._delete_selected_presets), padx=(6, 0))

    def _build_settings(self) -> None:
        self.setting_vars: Dict[str, tk.StringVar] = {}
        rows = [
            ("game_mods_dir", "Game mods folder"),
            ("mods_source_dir", "Mods source folder"),
            ("mod_extensions", "Mod extensions"),
            ("link_prefix", "Link prefix"),
            ("page_size", "Page size"),
            ("max_mod_name_len", "Max mod name length"),
            ("max_preset_name_len", "Max preset name length"),
            ("max_label_name_len", "Max label name length"),
            ("button_size_percent", "Button size"),
            ("gui_font_family", "Font"),
            ("gui_font_size", "Font size"),
        ]
        for row, (key, label) in enumerate(rows):
            ttk.Label(self.settings_tab, text=label).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=str(self.cfg.get(key, "")))
            if key == "button_size_percent":
                var = tk.StringVar(value=f"{str(self.cfg.get(key, 100)).strip().rstrip('%')}%")
            self.setting_vars[key] = var
            if key == "button_size_percent":
                ttk.Combobox(self.settings_tab, textvariable=var, values=self.button_scale_values, state="readonly", width=12).grid(row=row, column=1, sticky="w", padx=8, pady=4)
            elif key == "gui_font_family":
                ttk.Combobox(self.settings_tab, textvariable=var, values=sorted(tkfont.families()), width=40).grid(row=row, column=1, sticky="w", padx=8, pady=4)
            else:
                ttk.Entry(self.settings_tab, textvariable=var, width=70).grid(row=row, column=1, sticky="ew", padx=8, pady=4)
            if key in ["game_mods_dir", "mods_source_dir"]:
                self._button(self.settings_tab, "…", lambda k=key: self._browse_setting(k), "Browse").grid(row=row, column=2, pady=4)
        self.settings_tab.columnconfigure(1, weight=1)
        buttons = WrapFrame(self.settings_tab)
        buttons.grid(row=len(rows), column=0, columnspan=3, sticky="ew", pady=(12, 0))
        buttons.add(self._button(buttons, "💾", self._save_settings, "Save settings"))
        buttons.add(self._button(buttons, "📁", lambda: self._open_folder("source"), "Open source folder"), padx=(8, 0))
        buttons.add(self._button(buttons, "📁", lambda: self._open_folder("game"), "Open game folder"), padx=(8, 0))

    def _build_broken(self) -> None:
        top = WrapFrame(self.broken_tab)
        top.pack(fill="x")
        top.add(self._button(top, "↺", self.refresh_broken, "Refresh"))
        top.add(self._button(top, "Remove Selected", self._remove_selected_broken), padx=(6, 0))
        top.add(self._button(top, "Remove All", self._remove_all_broken), padx=(6, 0))
        self.broken_tree = ttk.Treeview(self.broken_tab, columns=("kind", "source"), show="tree headings", selectmode="extended")
        self.broken_tree.heading("#0", text="Mod")
        self.broken_tree.heading("kind", text="Kind")
        self.broken_tree.heading("source", text="Missing source")
        self.broken_tree.column("#0", width=320)
        self.broken_tree.column("kind", width=80, anchor="center")
        self.broken_tree.column("source", width=520)
        self.broken_tree.pack(fill="both", expand=True, pady=8)

    def _view_args(self):
        return max(1, int(self.mod_page.get() or 1)), self.label_filter_var.get().strip(), self.search_var.get().strip(), self._mod_order_mode()

    def _mod_order_mode(self) -> str:
        if self.mod_sort_key == "d":
            return "cd" if self.order_var.get().strip() == "Created date" else "d"
        return f"-{self.mod_sort_key}" if self.mod_sort_reverse else self.mod_sort_key

    def _preset_order_mode(self) -> str:
        return f"-{self.preset_sort_key}" if self.preset_sort_reverse else self.preset_sort_key

    def _sort_mods(self, key: str) -> None:
        if self.mod_sort_key == key:
            self.mod_sort_reverse = not self.mod_sort_reverse
        else:
            self.mod_sort_key = key
            self.mod_sort_reverse = False
        self.mod_page.set(1)
        self.refresh_mods()

    def _sort_presets(self, key: str) -> None:
        if self.preset_sort_key == key:
            self.preset_sort_reverse = not self.preset_sort_reverse
        else:
            self.preset_sort_key = key
            self.preset_sort_reverse = False
        self.preset_page.set(1)
        self.refresh_presets()

    def _save_placeholder_width(self, _event=None) -> None:
        width = int(self.mods_tree.column("#0", "width"))
        if width != int(self.cfg.get("placeholder_image_col_width", 56)):
            self.cfg["placeholder_image_col_width"] = width
            save_config(self.cfg)
            self.placeholder_images.clear()
            self.refresh_mods()

    def _image_width(self) -> int:
        return max(16, int(self.mods_tree.column("#0", "width")) - 20)

    def _pixel_hex(self, color) -> str:
        if isinstance(color, tuple):
            return "#%02x%02x%02x" % color[:3]
        return str(color)

    def _resize_image(self, source: tk.PhotoImage, width: int) -> tk.PhotoImage:
        source_w = max(1, source.width())
        source_h = max(1, source.height())
        height = max(1, int(source_h * width / source_w))
        if source_w == width and source_h == height:
            return source
        img = tk.PhotoImage(width=width, height=height)
        rows = []
        for y in range(height):
            source_y = min(source_h - 1, int(y * source_h / height))
            colors = []
            for x in range(width):
                source_x = min(source_w - 1, int(x * source_w / width))
                colors.append(self._pixel_hex(source.get(source_x, source_y)))
            rows.append("{" + " ".join(colors) + "}")
        img.put(" ".join(rows))
        return img

    def _placeholder(self, name: str) -> tk.PhotoImage:
        width = self._image_width()
        key = f"{name}:{width}"
        if key in self.placeholder_images:
            return self.placeholder_images[key]
        path = mod_image_path(self.cfg, name)
        img = None
        if path:
            max_h = max(28, int(width * 0.65))
            try:
                raw = tk.PhotoImage(file=str(path))
                src_w = max(1, raw.width())
                src_h = max(1, raw.height())
                fit_w = min(width, max(1, int(src_w * max_h / src_h)))
                img = self._resize_image(raw, fit_w)
            except tk.TclError:
                img = _load_image_gdi(path, width, max_h)
        if img is None:
            height = max(28, int(width * 0.65))
            img = tk.PhotoImage(width=width, height=height)
            colors = ["#d9e8fb", "#e4f4de", "#f7e6d0", "#eadff7", "#f7dfe8"]
            color = colors[sum(ord(c) for c in name) % len(colors)]
            img.put(color, to=(0, 0, width, height))
        self.placeholder_images[key] = img
        return img

    def _handle_mods_drop(self, paths, x: int, y: int) -> None:
        if self.busy or not ensure_paths(self.cfg):
            return
        image_paths = [p for p in paths if is_image_file(p)]
        mod_paths = [p for p in paths if is_mod_file(p, self.cfg)]
        tasks = []
        tree_x = x - self.mods_tree.winfo_rootx()
        tree_y = y - self.mods_tree.winfo_rooty()
        row = self.mods_tree.identify_row(tree_y) if 0 <= tree_x <= self.mods_tree.winfo_width() and 0 <= tree_y <= self.mods_tree.winfo_height() else ""
        if image_paths:
            default_name = ""
            if row and row.isdigit():
                index = int(row)
                if 1 <= index <= len(self.current_mods_shown):
                    default_name = self.current_mods_shown[index - 1].name
            if default_name:
                for path in image_paths:
                    tasks.append(("image", path, default_name, True))
        for path in mod_paths:
            dst_exists = ((self.cfg.get("mods_source_dir") or "") and any(m.name == path.name for m in self.current_mod_items))
            replace = True
            if dst_exists:
                replace = messagebox.askyesno("Replace mod", f"Replace existing mod '{path.name}'?")
            if replace:
                tasks.append(("mod", path, "", dst_exists))
        if not tasks:
            self.status_var.set("No supported dropped files.")
            return

        def worker():
            imported = []
            skipped = []
            for kind, path, mod_name, replace in tasks:
                if kind == "image":
                    ok, msg = import_mod_image(self.cfg, mod_name, path)
                else:
                    ok, msg = import_mod_file(self.cfg, path, replace)
                (imported if ok else skipped).append(msg)
            return imported, skipped

        def done(result) -> None:
            imported, skipped = result
            self.placeholder_images.clear()
            self.status_var.set(f"Imported: {len(imported)}. Skipped: {len(skipped)}.")
            self.refresh_mods()

        self._run_action("Importing dropped files", worker, done)

    def _import_paths(self, paths: List[Path]) -> None:
        if self.busy or not ensure_paths(self.cfg):
            return
        tasks = []
        for path in paths:
            if not is_mod_file(path, self.cfg):
                continue
            exists = any(m.name == path.name for m in self.current_mod_items)
            replace = True
            if exists:
                replace = messagebox.askyesno("Replace mod", f"Replace existing mod '{path.name}'?")
            if replace:
                tasks.append((path, exists))
        if not tasks:
            self.status_var.set("No supported mod files.")
            return

        def worker():
            imported = []
            skipped = []
            for path, replace in tasks:
                ok, msg = import_mod_file(self.cfg, path, replace)
                (imported if ok else skipped).append(msg)
            return imported, skipped

        def done(result) -> None:
            imported, skipped = result
            self.status_var.set(f"Imported: {len(imported)}. Skipped: {len(skipped)}.")
            self.refresh_mods()

        self._run_action("Importing mods", worker, done)

    def _import_mod_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Import mods")
        if paths:
            self._import_paths([Path(p) for p in paths])

    def _import_mod_folder(self) -> None:
        path = filedialog.askdirectory(title="Import mod folder")
        if path:
            self._import_paths([Path(path)])

    def _set_mod_image(self) -> None:
        if self.busy or not ensure_paths(self.cfg):
            return
        indexes = self._selected_indexes(self.mods_tree)
        default_name = ""
        if indexes and 1 <= indexes[0] <= len(self.current_mods_shown):
            default_name = self.current_mods_shown[indexes[0] - 1].name
        mod_name = self._choose_mod_for_image(default_name)
        if not mod_name:
            return
        path = filedialog.askopenfilename(title="Select image")
        if not path:
            return
        image = Path(path)
        if not is_image_file(image):
            messagebox.showwarning("Image", "Unsupported image file.")
            return

        def done(result) -> None:
            ok, msg = result
            self.placeholder_images.clear()
            self.status_var.set(f"Image {'saved' if ok else 'skipped'}: {msg}")
            self.refresh_mods()

        self._run_action("Saving image", lambda: import_mod_image(self.cfg, mod_name, image), done)

    def _choose_mod_for_image(self, default_name: str = "") -> str:
        names = [m.name for m in self.current_mod_items]
        if not names:
            messagebox.showwarning("Image", "No mods available.")
            return ""
        result = {"name": ""}
        dialog = tk.Toplevel(self)
        dialog.title("Select mod")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)
        ttk.Label(dialog, text="Mod").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        var = tk.StringVar(value=default_name or names[0])
        box = AutocompleteCombobox(dialog, textvariable=var, width=52)
        box.set_completion_values(names)
        box.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=4)

        def ok() -> None:
            value = var.get().strip()
            if value in names:
                result["name"] = value
                dialog.destroy()
            else:
                messagebox.showwarning("Image", "Select mod from list.", parent=dialog)

        def cancel() -> None:
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", padx=12, pady=(8, 12))
        ttk.Button(buttons, text="OK", command=ok).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side="left")
        dialog.bind("<Return>", lambda _event: ok())
        dialog.bind("<Escape>", lambda _event: cancel())
        box.focus_set()
        dialog.wait_window()
        return result["name"]

    def refresh_all(self) -> None:
        self.refresh_mods()
        self.refresh_presets()
        self.refresh_broken()

    def refresh_mods(self, selected_names: List[str] | None = None) -> None:
        if not ensure_paths(self.cfg):
            self.status_var.set("Configure folders first.")
            return
        page, label, search, order = self._view_args()
        items, shown, page, pages, labels = mods_view(self.cfg, page, label, search, order)
        records = mods_records()
        self.current_mod_items = items
        self.current_mods_shown = shown
        self.current_mod_labels = labels
        self.mod_page.set(page)
        row_height = max(30, int(34 * self._button_scale()))
        row_height = max(row_height, max(28, int(self._image_width() * 0.65)) + 6)
        ttk.Style(self).configure("Mods.Treeview", rowheight=row_height)
        self.mods_tree.delete(*self.mods_tree.get_children())
        for i, mod in enumerate(shown, 1):
            rec = records.get(mod.name, {})
            last_managed = rec.get("last_managed") or "-"
            image = self._placeholder(mod.name)
            name_display = f"✓  {mod.name}" if mod.installed else mod.name
            tags = ("installed",) if mod.installed else ()
            self.mods_tree.insert("", "end", iid=str(i), text="", image=image, values=(name_display, labels.get(mod.name, "-"), last_managed), tags=tags)
        if selected_names:
            selected = [str(i) for i, mod in enumerate(shown, 1) if mod.name in selected_names]
            if selected:
                self.mods_tree.selection_set(selected)
                self.mods_tree.focus(selected[0])
                self.mods_tree.see(selected[0])
        self.search_box.set_completion_values([m.name for m in items])
        label_values = sorted({v for v in labels.values() if v})
        self.label_filter_box.set_completion_values(label_values)
        self.label_edit_box.set_completion_values(label_values)
        self.status_var.set(f"Mods page {page}/{pages}. Items: {len(items)}")

    def refresh_presets(self) -> None:
        if not ensure_paths(self.cfg):
            return
        presets, keys, page_keys, page, pages = presets_view(self.cfg, max(1, int(self.preset_page.get() or 1)), self._preset_order_mode())
        records = presets_records()
        self.preset_page.set(page)
        self.presets_tree.delete(*self.presets_tree.get_children())
        for i, name in enumerate(page_keys, 1):
            mods = presets.get(name, [])
            rec = records.get(name, {})
            state = rec.get("state") or "undefined"
            last_managed = rec.get("last_managed") or "-"
            self.presets_tree.insert("", "end", iid=str(i), text=name, values=(state, len(mods), last_managed))
        self.preset_name_box.set_completion_values(keys)
        self.status_var.set(f"Presets page {page}/{pages}. Items: {len(keys)}")

    def refresh_broken(self) -> None:
        if not ensure_paths(self.cfg):
            return
        broken = list_broken_links(self.cfg)
        self.current_broken = broken
        self.broken_tree.delete(*self.broken_tree.get_children())
        for i, mod in enumerate(broken, 1):
            kind = "DIR" if mod.is_dir else "FILE"
            self.broken_tree.insert("", "end", iid=str(i), text=mod.name, values=(kind, str(mod.src)))
        self.status_var.set(f"Broken links: {len(broken)}")

    def _selected_indexes(self, tree: ttk.Treeview) -> List[int]:
        return [int(iid) for iid in tree.selection() if str(iid).isdigit()]

    def _mods_search(self) -> None:
        self.mod_page.set(1)
        self.refresh_mods()

    def _mods_clear(self) -> None:
        self.search_var.set("")
        self.label_filter_var.set("")
        self.mod_page.set(1)
        self.refresh_mods()

    def _change_mod_page(self, delta: int) -> None:
        self.mod_page.set(max(1, int(self.mod_page.get() or 1) + delta))
        self.refresh_mods()

    def _change_preset_page(self, delta: int) -> None:
        self.preset_page.set(max(1, int(self.preset_page.get() or 1) + delta))
        self.refresh_presets()

    def _install_page(self) -> None:
        page, label, search, order = self._view_args()

        def done(result) -> None:
            page, total, err = result
            self.status_var.set(f"Installed {total - err}/{total} on page {page}. Errors: {err}.")
            self.refresh_mods()
            self.refresh_presets()

        self._run_action("Installing page", lambda: apply_mods_page(self.cfg, page, label, search, order), done)

    def _uninstall_page(self) -> None:
        page, label, search, order = self._view_args()

        def done(result) -> None:
            page, count = result
            self.status_var.set(f"Uninstalled {count} on page {page}.")
            self.refresh_mods()
            self.refresh_presets()

        self._run_action("Uninstalling page", lambda: deactivate_mods_page(self.cfg, page, label, search, order), done)

    def _toggle_selected_mods(self) -> None:
        shown = list(self.current_mods_shown)
        indexes = self._selected_indexes(self.mods_tree)
        selected_names = [shown[i - 1].name for i in indexes if 1 <= i <= len(shown)]

        def done(msg) -> None:
            self.status_var.set(msg or "No mods selected.")
            self.refresh_mods(selected_names)
            self.refresh_presets()

        self._run_action("Toggling selected mods", lambda: toggle_mods_by_indexes(shown, indexes), done)

    def _add_label_selected(self) -> None:
        label = self.label_edit_var.get().strip()
        if not label:
            messagebox.showerror("Label", "Enter label.")
            return
        targets = [self.current_mods_shown[i - 1].name for i in self._selected_indexes(self.mods_tree) if 1 <= i <= len(self.current_mods_shown)]

        def done(msg) -> None:
            self.status_var.set(msg)
            self.refresh_mods()

        self._run_action("Adding label", lambda: add_label_to_mods(label, targets) if targets else "No mods selected.", done)

    def _remove_label_selected(self) -> None:
        label = self.label_edit_var.get().strip()
        if not label:
            messagebox.showerror("Label", "Enter label.")
            return
        targets = [self.current_mods_shown[i - 1].name for i in self._selected_indexes(self.mods_tree) if 1 <= i <= len(self.current_mods_shown)]

        def done(msg) -> None:
            self.status_var.set(msg)
            self.refresh_mods()

        self._run_action("Removing label", lambda: remove_label_from_mods(label, targets) if targets else "No mods selected.", done)

    def _save_preset(self) -> None:
        name = self.preset_name_box.get().strip()
        if not name:
            messagebox.showerror("Preset", "Enter preset name.")
            return
        def done(result) -> None:
            _ok, msg = result
            self.status_var.set(msg)
            self.refresh_presets()

        self._run_action("Saving preset", lambda: save_preset_from_installed(self.cfg, name), done)

    def _toggle_selected_presets(self) -> None:
        if not self.search_var.get().strip() and not self.label_filter_var.get().strip() and self.current_mod_items:
            installed = {m.name for m in self.current_mod_items if m.installed}
        else:
            installed = {m.name for m in mods_view(self.cfg, 1, "", "", "d")[0] if m.installed}
        page = int(self.preset_page.get() or 1)
        indexes = self._selected_indexes(self.presets_tree)

        def done(result) -> None:
            msg, messages, has_errors = result
            self.status_var.set(msg or "No presets selected.")
            if has_errors:
                messagebox.showwarning("Preset", "\n".join(messages))
            self.refresh_mods()
            self.refresh_presets()

        self._run_action("Toggling selected presets", lambda: toggle_presets_by_indexes(self.cfg, page, indexes, installed), done)

    def _delete_selected_presets(self) -> None:
        page = int(self.preset_page.get() or 1)
        indexes = self._selected_indexes(self.presets_tree)

        def done(result) -> None:
            count, missing = result
            self.status_var.set(f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}")
            self.refresh_presets()

        self._run_action("Deleting presets", lambda: delete_presets_by_indexes(self.cfg, page, indexes), done)

    def _browse_setting(self, key: str) -> None:
        path = filedialog.askdirectory()
        if path:
            self.setting_vars[key].set(path)

    def _save_settings(self) -> None:
        values = {key: var.get().strip() for key, var in self.setting_vars.items()}

        def worker():
            for key, value in values.items():
                if key in ["page_size", "max_mod_name_len", "max_preset_name_len", "max_label_name_len", "button_size_percent", "gui_font_size"]:
                    numeric = value.rstrip("%")
                    if numeric.isdigit():
                        self.cfg[key] = int(numeric)
                else:
                    self.cfg[key] = value
            save_config(self.cfg)
            return "Settings saved."

        def done(msg) -> None:
            self._apply_gui_style()
            self._apply_button_widths()
            self.status_var.set(msg)
            self.refresh_all()

        self._run_action("Saving settings", worker, done)

    def _open_folder(self, target: str) -> None:
        key = "mods_source_dir" if target == "source" else "game_mods_dir"

        def done(result) -> None:
            ok, msg = result
            self.status_var.set(f"Open {target} folder: {'OK' if ok else 'ERR'} - {msg}")

        self._run_action(f"Opening {target} folder", lambda: open_folder(self.cfg.get(key, "")), done)

    def _remove_selected_broken(self) -> None:
        targets = [self.current_broken[i - 1] for i in self._selected_indexes(self.broken_tree) if 1 <= i <= len(self.current_broken)]

        def worker() -> int:
            for mod in targets:
                deactivate_mod(mod)
            return len(targets)

        def done(count) -> None:
            self.status_var.set(f"Removed broken links: {count}")
            self.refresh_broken()

        self._run_action("Removing broken links", worker, done)

    def _remove_all_broken(self) -> None:
        targets = list(self.current_broken)

        def worker() -> int:
            for mod in targets:
                deactivate_mod(mod)
            return len(targets)

        def done(count) -> None:
            self.status_var.set(f"Removed broken links: {count}")
            self.refresh_broken()

        self._run_action("Removing all broken links", worker, done)

def run_gui() -> int:
    app = ModManagerGui()
    app.mainloop()
    return 0
