from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List

from .cli_utils import ensure_paths, open_folder
from .mods import (
    add_label_to_mods,
    apply_mods_page,
    deactivate_mod,
    deactivate_mods_page,
    list_broken_links,
    mods_view,
    remove_label_from_mods,
    toggle_mods_by_indexes,
)
from .presets import delete_presets_by_indexes, presets_view, save_preset_from_installed, toggle_presets_by_indexes
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
        self._build()
        self.refresh_all()

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
        ttk.Button(top, text="List", command=self.refresh_mods).pack(side="left")
        ttk.Button(top, text="Search", command=self._mods_search).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Clear", command=self._mods_clear).pack(side="left", padx=(6, 0))
        self.mods_tree = ttk.Treeview(self.mods_tab, columns=("state", "label"), show="tree headings", selectmode="extended")
        self.mods_tree.heading("#0", text="Mod")
        self.mods_tree.heading("state", text="Installed")
        self.mods_tree.heading("label", text="Label")
        self.mods_tree.column("#0", width=560)
        self.mods_tree.column("state", width=90, anchor="center")
        self.mods_tree.column("label", width=180)
        self.mods_tree.pack(fill="both", expand=True, pady=8)
        actions = ttk.Frame(self.mods_tab)
        actions.pack(fill="x")
        ttk.Button(actions, text="Prev Page", command=lambda: self._change_mod_page(-1)).pack(side="left")
        ttk.Button(actions, text="Next Page", command=lambda: self._change_mod_page(1)).pack(side="left", padx=(6, 12))
        ttk.Label(actions, text="Page").pack(side="left")
        ttk.Spinbox(actions, from_=1, to=9999, textvariable=self.mod_page, width=6, command=self.refresh_mods).pack(side="left", padx=(6, 12))
        ttk.Button(actions, text="Install Page", command=self._install_page).pack(side="left")
        ttk.Button(actions, text="Uninstall Page", command=self._uninstall_page).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Toggle Selected", command=self._toggle_selected_mods).pack(side="left", padx=(6, 12))
        ttk.Label(actions, text="Label").pack(side="left")
        self.label_edit_box = AutocompleteCombobox(actions, textvariable=self.label_edit_var, width=18)
        self.label_edit_box.pack(side="left", padx=(6, 6))
        ttk.Button(actions, text="Add Label", command=self._add_label_selected).pack(side="left")
        ttk.Button(actions, text="Remove Label", command=self._remove_label_selected).pack(side="left", padx=(6, 0))

    def _build_presets(self) -> None:
        top = ttk.Frame(self.presets_tab)
        top.pack(fill="x")
        ttk.Label(top, text="Name").pack(side="left")
        self.preset_name_box = AutocompleteCombobox(top, width=30)
        self.preset_name_box.pack(side="left", padx=(6, 8))
        ttk.Button(top, text="Save", command=self._save_preset).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_presets).pack(side="left", padx=(6, 0))
        self.presets_tree = ttk.Treeview(self.presets_tab, columns=("state", "mods"), show="tree headings", selectmode="extended")
        self.presets_tree.heading("#0", text="Preset")
        self.presets_tree.heading("state", text="Applied")
        self.presets_tree.heading("mods", text="Mods")
        self.presets_tree.column("#0", width=620)
        self.presets_tree.column("state", width=90, anchor="center")
        self.presets_tree.column("mods", width=90, anchor="center")
        self.presets_tree.pack(fill="both", expand=True, pady=8)
        actions = ttk.Frame(self.presets_tab)
        actions.pack(fill="x")
        ttk.Button(actions, text="Prev Page", command=lambda: self._change_preset_page(-1)).pack(side="left")
        ttk.Button(actions, text="Next Page", command=lambda: self._change_preset_page(1)).pack(side="left", padx=(6, 12))
        ttk.Label(actions, text="Page").pack(side="left")
        ttk.Spinbox(actions, from_=1, to=9999, textvariable=self.preset_page, width=6, command=self.refresh_presets).pack(side="left", padx=(6, 12))
        ttk.Button(actions, text="Toggle Selected", command=self._toggle_selected_presets).pack(side="left")
        ttk.Button(actions, text="Delete Selected", command=self._delete_selected_presets).pack(side="left", padx=(6, 0))

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
        ]
        for row, (key, label) in enumerate(rows):
            ttk.Label(self.settings_tab, text=label).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=str(self.cfg.get(key, "")))
            self.setting_vars[key] = var
            ttk.Entry(self.settings_tab, textvariable=var, width=70).grid(row=row, column=1, sticky="ew", padx=8, pady=4)
            if key in ["game_mods_dir", "mods_source_dir"]:
                ttk.Button(self.settings_tab, text="Browse", command=lambda k=key: self._browse_setting(k)).grid(row=row, column=2, pady=4)
        self.settings_tab.columnconfigure(1, weight=1)
        buttons = ttk.Frame(self.settings_tab)
        buttons.grid(row=len(rows), column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Button(buttons, text="Save Settings", command=self._save_settings).pack(side="left")
        ttk.Button(buttons, text="Open Source Folder", command=lambda: self._open_folder("source")).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Open Game Folder", command=lambda: self._open_folder("game")).pack(side="left", padx=(8, 0))

    def _build_broken(self) -> None:
        top = ttk.Frame(self.broken_tab)
        top.pack(fill="x")
        ttk.Button(top, text="List", command=self.refresh_broken).pack(side="left")
        ttk.Button(top, text="Remove Selected", command=self._remove_selected_broken).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Remove All", command=self._remove_all_broken).pack(side="left", padx=(6, 0))
        self.broken_tree = ttk.Treeview(self.broken_tab, columns=("kind", "source"), show="tree headings", selectmode="extended")
        self.broken_tree.heading("#0", text="Mod")
        self.broken_tree.heading("kind", text="Kind")
        self.broken_tree.heading("source", text="Missing source")
        self.broken_tree.column("#0", width=320)
        self.broken_tree.column("kind", width=80, anchor="center")
        self.broken_tree.column("source", width=520)
        self.broken_tree.pack(fill="both", expand=True, pady=8)

    def _view_args(self):
        return max(1, int(self.mod_page.get() or 1)), self.label_filter_var.get().strip(), self.search_var.get().strip(), self.order_var.get().strip() or "d"

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

    def refresh_mods(self) -> None:
        if not ensure_paths(self.cfg):
            self.status_var.set("Configure folders first.")
            return
        page, label, search, order = self._view_args()
        items, shown, page, pages, labels = mods_view(self.cfg, page, label, search, order)
        self.mod_page.set(page)
        self.mods_tree.delete(*self.mods_tree.get_children())
        for i, mod in enumerate(shown, 1):
            mark = "Yes" if mod.installed else "No"
            self.mods_tree.insert("", "end", iid=str(i), text=mod.name, image=self._placeholder(mod.name), values=(mark, labels.get(mod.name, "-")))
        self.search_box.set_completion_values([m.name for m in items])
        label_values = sorted({v for v in labels.values() if v})
        self.label_filter_box.set_completion_values(label_values)
        self.label_edit_box.set_completion_values(label_values)
        self.status_var.set(f"Mods page {page}/{pages}. Items: {len(items)}")

    def refresh_presets(self) -> None:
        if not ensure_paths(self.cfg):
            return
        presets, keys, page_keys, page, pages = presets_view(self.cfg, max(1, int(self.preset_page.get() or 1)))
        installed = {m.name for m in mods_view(self.cfg, 1, "", "", "d")[0] if m.installed}
        self.preset_page.set(page)
        self.presets_tree.delete(*self.presets_tree.get_children())
        for i, name in enumerate(page_keys, 1):
            mods = presets.get(name, [])
            mark = "Yes" if bool(mods) and all(nm in installed for nm in mods) else "No"
            self.presets_tree.insert("", "end", iid=str(i), text=name, values=(mark, len(mods)))
        self.preset_name_box.set_completion_values(keys)
        self.status_var.set(f"Presets page {page}/{pages}. Items: {len(keys)}")

    def refresh_broken(self) -> None:
        if not ensure_paths(self.cfg):
            return
        broken = list_broken_links(self.cfg)
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
        page, total, err = apply_mods_page(self.cfg, page, label, search, order)
        self.status_var.set(f"Installed {total - err}/{total} on page {page}. Errors: {err}.")
        self.refresh_all()

    def _uninstall_page(self) -> None:
        page, label, search, order = self._view_args()
        page, count = deactivate_mods_page(self.cfg, page, label, search, order)
        self.status_var.set(f"Uninstalled {count} on page {page}.")
        self.refresh_all()

    def _toggle_selected_mods(self) -> None:
        page, label, search, order = self._view_args()
        _items, shown, _page, _pages, _labels = mods_view(self.cfg, page, label, search, order)
        msg = toggle_mods_by_indexes(shown, self._selected_indexes(self.mods_tree))
        self.status_var.set(msg or "No mods selected.")
        self.refresh_all()

    def _add_label_selected(self) -> None:
        label = self.label_edit_var.get().strip()
        if not label:
            messagebox.showerror("Label", "Enter label.")
            return
        page, current_label, search, order = self._view_args()
        _items, shown, _page, _pages, _labels = mods_view(self.cfg, page, current_label, search, order)
        targets = [shown[i - 1].name for i in self._selected_indexes(self.mods_tree) if 1 <= i <= len(shown)]
        self.status_var.set(add_label_to_mods(label, targets) if targets else "No mods selected.")
        self.refresh_mods()

    def _remove_label_selected(self) -> None:
        label = self.label_edit_var.get().strip()
        if not label:
            messagebox.showerror("Label", "Enter label.")
            return
        page, current_label, search, order = self._view_args()
        _items, shown, _page, _pages, _labels = mods_view(self.cfg, page, current_label, search, order)
        targets = [shown[i - 1].name for i in self._selected_indexes(self.mods_tree) if 1 <= i <= len(shown)]
        self.status_var.set(remove_label_from_mods(label, targets) if targets else "No mods selected.")
        self.refresh_mods()

    def _save_preset(self) -> None:
        name = self.preset_name_box.get().strip()
        if not name:
            messagebox.showerror("Preset", "Enter preset name.")
            return
        ok, msg = save_preset_from_installed(self.cfg, name)
        self.status_var.set(msg)
        self.refresh_presets()

    def _toggle_selected_presets(self) -> None:
        installed = {m.name for m in mods_view(self.cfg, 1, "", "", "d")[0] if m.installed}
        msg, messages, has_errors = toggle_presets_by_indexes(self.cfg, int(self.preset_page.get() or 1), self._selected_indexes(self.presets_tree), installed)
        self.status_var.set(msg or "No presets selected.")
        if has_errors:
            messagebox.showwarning("Preset", "\n".join(messages))
        self.refresh_all()

    def _delete_selected_presets(self) -> None:
        count, missing = delete_presets_by_indexes(self.cfg, int(self.preset_page.get() or 1), self._selected_indexes(self.presets_tree))
        self.status_var.set(f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}")
        self.refresh_presets()

    def _browse_setting(self, key: str) -> None:
        path = filedialog.askdirectory()
        if path:
            self.setting_vars[key].set(path)

    def _save_settings(self) -> None:
        for key, var in self.setting_vars.items():
            value = var.get().strip()
            if key in ["page_size", "max_mod_name_len", "max_preset_name_len", "max_label_name_len"]:
                if value.isdigit():
                    self.cfg[key] = int(value)
            else:
                self.cfg[key] = value
        save_config(self.cfg)
        self.status_var.set("Settings saved.")
        self.refresh_all()

    def _open_folder(self, target: str) -> None:
        key = "mods_source_dir" if target == "source" else "game_mods_dir"
        ok, msg = open_folder(self.cfg.get(key, ""))
        self.status_var.set(f"Open {target} folder: {'OK' if ok else 'ERR'} - {msg}")

    def _remove_selected_broken(self) -> None:
        broken = list_broken_links(self.cfg)
        targets = [broken[i - 1] for i in self._selected_indexes(self.broken_tree) if 1 <= i <= len(broken)]
        for mod in targets:
            deactivate_mod(mod)
        self.status_var.set(f"Removed broken links: {len(targets)}")
        self.refresh_broken()

    def _remove_all_broken(self) -> None:
        broken = list_broken_links(self.cfg)
        for mod in broken:
            deactivate_mod(mod)
        self.status_var.set(f"Removed broken links: {len(broken)}")
        self.refresh_broken()

def run_gui() -> int:
    app = ModManagerGui()
    app.mainloop()
    return 0
