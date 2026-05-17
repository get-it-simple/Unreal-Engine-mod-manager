from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List

from .cli_utils import ensure_paths, open_folder
from .mods import (
    add_label_to_mods,
    apply_mods_page,
    deactivate_mod,
    deactivate_mods_page,
    list_broken_links,
    mods_view,
    mods_records,
    remove_label_from_mods,
    toggle_mods_by_indexes,
)
from .presets import delete_presets_by_indexes, presets_records, presets_view, save_preset_from_installed, toggle_presets_by_indexes
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
        self.order_var = tk.StringVar(value="d")
        self.status_var = tk.StringVar()
        self.placeholder_images: Dict[str, tk.PhotoImage] = {}
        self.current_mod_items = []
        self.current_mods_shown = []
        self.current_mod_labels = {}
        self.current_broken = []
        self.busy = False
        self.action_widgets = []
        self.mod_sort_key = "d"
        self.mod_sort_reverse = False
        self.preset_sort_key = "name"
        self.preset_sort_reverse = False
        self.button_scale_values = ["25%", "50%", "75%", "100%", "125%", "150%", "175%", "200%"]
        self._apply_gui_style()
        self._build()
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

    def _apply_button_widths(self) -> None:
        for widget in self.action_widgets:
            try:
                text = str(widget.cget("text"))
                if text:
                    widget.configure(width=max(int(14 * self._button_scale()), len(text) + 2))
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

    def _button(self, master, text: str, command: Callable):
        width = max(int(14 * self._button_scale()), len(text) + 2)
        btn = ttk.Button(master, text=text, command=command, width=width)
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
                self.status_var.set(str(error))
                messagebox.showerror("Error", str(error))
            elif done:
                done(result)
        finally:
            self._set_busy(False)

    def _build_mods(self) -> None:
        top = ttk.Frame(self.mods_tab)
        top.pack(fill="x")
        ttk.Label(top, text="Search").pack(side="left")
        self.search_box = AutocompleteCombobox(top, textvariable=self.search_var, width=24)
        self.search_box.pack(side="left", padx=(6, 12))
        ttk.Label(top, text="Label").pack(side="left")
        self.label_filter_box = AutocompleteCombobox(top, textvariable=self.label_filter_var, width=18)
        self.label_filter_box.pack(side="left", padx=(6, 12))
        ttk.Label(top, text="Order").pack(side="left")
        ttk.Combobox(top, textvariable=self.order_var, values=["d", "cd"], width=6, state="readonly").pack(side="left", padx=(6, 12))
        self._button(top, "List", self.refresh_mods).pack(side="left")
        self._button(top, "Search", self._mods_search).pack(side="left", padx=(6, 0))
        self._button(top, "Clear", self._mods_clear).pack(side="left", padx=(6, 0))
        self.mods_tree = ttk.Treeview(self.mods_tab, columns=("name", "state", "label", "last"), show="tree headings", selectmode="extended")
        self.mods_tree.heading("#0", text="Image")
        self.mods_tree.heading("name", text="Mod", command=lambda: self._sort_mods("name"))
        self.mods_tree.heading("state", text="Installed", command=lambda: self._sort_mods("installed"))
        self.mods_tree.heading("label", text="Label", command=lambda: self._sort_mods("label"))
        self.mods_tree.heading("last", text="Last managed", command=lambda: self._sort_mods("last_managed"))
        self.mods_tree.column("#0", width=int(self.cfg.get("placeholder_image_col_width", 56)), minwidth=36, stretch=False, anchor="center")
        self.mods_tree.column("name", width=380)
        self.mods_tree.column("state", width=90, anchor="center")
        self.mods_tree.column("label", width=160)
        self.mods_tree.column("last", width=160)
        self.mods_tree.bind("<ButtonRelease-1>", self._save_placeholder_width)
        self.mods_tree.pack(fill="both", expand=True, pady=8)
        actions = ttk.Frame(self.mods_tab)
        actions.pack(fill="x")
        self._button(actions, "Prev Page", lambda: self._change_mod_page(-1)).pack(side="left")
        self._button(actions, "Next Page", lambda: self._change_mod_page(1)).pack(side="left", padx=(6, 12))
        ttk.Label(actions, text="Page").pack(side="left")
        mod_page_spin = ttk.Spinbox(actions, from_=1, to=9999, textvariable=self.mod_page, width=6, command=self.refresh_mods)
        self.action_widgets.append(mod_page_spin)
        mod_page_spin.pack(side="left", padx=(6, 12))
        self._button(actions, "Install Page", self._install_page).pack(side="left")
        self._button(actions, "Uninstall Page", self._uninstall_page).pack(side="left", padx=(6, 0))
        self._button(actions, "Toggle Selected", self._toggle_selected_mods).pack(side="left", padx=(6, 12))
        ttk.Label(actions, text="Label").pack(side="left")
        self.label_edit_box = AutocompleteCombobox(actions, textvariable=self.label_edit_var, width=18)
        self.label_edit_box.pack(side="left", padx=(6, 6))
        self._button(actions, "Add Label", self._add_label_selected).pack(side="left")
        self._button(actions, "Remove Label", self._remove_label_selected).pack(side="left", padx=(6, 0))

    def _build_presets(self) -> None:
        top = ttk.Frame(self.presets_tab)
        top.pack(fill="x")
        ttk.Label(top, text="Name").pack(side="left")
        self.preset_name_box = AutocompleteCombobox(top, width=30)
        self.preset_name_box.pack(side="left", padx=(6, 8))
        self._button(top, "Save", self._save_preset).pack(side="left")
        self._button(top, "Refresh", self.refresh_presets).pack(side="left", padx=(6, 0))
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
        actions = ttk.Frame(self.presets_tab)
        actions.pack(fill="x")
        self._button(actions, "Prev Page", lambda: self._change_preset_page(-1)).pack(side="left")
        self._button(actions, "Next Page", lambda: self._change_preset_page(1)).pack(side="left", padx=(6, 12))
        ttk.Label(actions, text="Page").pack(side="left")
        preset_page_spin = ttk.Spinbox(actions, from_=1, to=9999, textvariable=self.preset_page, width=6, command=self.refresh_presets)
        self.action_widgets.append(preset_page_spin)
        preset_page_spin.pack(side="left", padx=(6, 12))
        self._button(actions, "Toggle Selected", self._toggle_selected_presets).pack(side="left")
        self._button(actions, "Delete Selected", self._delete_selected_presets).pack(side="left", padx=(6, 0))

    def _build_settings(self) -> None:
        self.setting_vars: Dict[str, tk.StringVar] = {}
        rows = [
            ("game_mods_dir", "Game mods folder"),
            ("mods_source_dir", "Mods source folder"),
            ("mod_extensions", "Mod extensions"),
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
                self._button(self.settings_tab, "Browse", lambda k=key: self._browse_setting(k)).grid(row=row, column=2, pady=4)
        self.settings_tab.columnconfigure(1, weight=1)
        buttons = ttk.Frame(self.settings_tab)
        buttons.grid(row=len(rows), column=0, columnspan=3, sticky="w", pady=(12, 0))
        self._button(buttons, "Save Settings", self._save_settings).pack(side="left")
        self._button(buttons, "Open Source Folder", lambda: self._open_folder("source")).pack(side="left", padx=(8, 0))
        self._button(buttons, "Open Game Folder", lambda: self._open_folder("game")).pack(side="left", padx=(8, 0))

    def _build_broken(self) -> None:
        top = ttk.Frame(self.broken_tab)
        top.pack(fill="x")
        self._button(top, "List", self.refresh_broken).pack(side="left")
        self._button(top, "Remove Selected", self._remove_selected_broken).pack(side="left", padx=(6, 0))
        self._button(top, "Remove All", self._remove_all_broken).pack(side="left", padx=(6, 0))
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
            return self.order_var.get().strip() or "d"
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

    def _placeholder(self, name: str) -> tk.PhotoImage:
        if name in self.placeholder_images:
            return self.placeholder_images[name]
        img = tk.PhotoImage(width=40, height=28)
        colors = ["#d9e8fb", "#e4f4de", "#f7e6d0", "#eadff7", "#f7dfe8"]
        color = colors[sum(ord(c) for c in name) % len(colors)]
        img.put(color, to=(0, 0, 40, 28))
        self.placeholder_images[name] = img
        return img

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
        self.mods_tree.delete(*self.mods_tree.get_children())
        for i, mod in enumerate(shown, 1):
            mark = "Yes" if mod.installed else "No"
            rec = records.get(mod.name, {})
            last_managed = rec.get("last_managed") or "-"
            self.mods_tree.insert("", "end", iid=str(i), text="", image=self._placeholder(mod.name), values=(mod.name, mark, labels.get(mod.name, "-"), last_managed))
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
