from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from functools import partial
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
    list_installed_mods,
    mod_image_path,
    mods_view,
    mods_records,
    remove_label_from_mods,
    toggle_mods_by_indexes,
)
from .presets import delete_presets_by_indexes, presets_records, presets_view, save_preset_from_installed, toggle_presets_by_indexes
from .dragdrop import WindowsDropTarget, read_clipboard_image, read_clipboard_paths
from .storage import load_config, save_config
from .workers import WorkerPool, _run_import_batch, _run_deactivate_batch, _run_save_settings

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
        self._placed_h = 0
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
        for widget, *_ in self.items:
            widget.grid_forget()
            widget.place_forget()
        rows: list = []
        row: list = []
        used = 0
        for item in self.items:
            need = item[0].winfo_reqwidth() + self._pad_width(item[1])
            if row and used + need > width:
                rows.append(row)
                row = []
                used = 0
            row.append(item)
            used += need
        if row:
            rows.append(row)
        y = 0
        for row_items in rows:
            rh = max((w.winfo_reqheight() for w, *_ in row_items), default=28)
            rp = max((it[2] for it in row_items), default=3)
            x = 0
            for widget, padx, pady, sticky in row_items:
                pl = padx[0] if isinstance(padx, tuple) else padx
                pr = padx[1] if isinstance(padx, tuple) else padx
                x += pl
                wh = widget.winfo_reqheight()
                widget.place(x=x, y=y + rp + (rh - wh) // 2)
                x += widget.winfo_reqwidth() + pr
            y += rh + rp * 2
        h = max(1, y)
        if self._placed_h != h:
            self._placed_h = h
            self.configure(height=h)

class ScrollableTabFrame(ttk.Frame):
    def __init__(self, master, padding=0, **kwargs):
        super().__init__(master, **kwargs)
        self._vscroll = ttk.Scrollbar(self, orient="vertical")
        self._canvas = tk.Canvas(self, yscrollcommand=self._vscroll.set, highlightthickness=0, bd=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._vscroll.configure(command=self._canvas.yview)
        self.inner = ttk.Frame(self._canvas, padding=padding)
        self._win_id = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._update_scrollregion)
        self._canvas.bind("<Configure>", self._update_inner_width)

    def _update_scrollregion(self, _event=None):
        req_h = self.inner.winfo_reqheight()
        canvas_h = self._canvas.winfo_height()
        self._canvas.configure(scrollregion=(0, 0, self._canvas.winfo_width(), req_h))
        if req_h > canvas_h:
            self._vscroll.grid(row=0, column=1, sticky="ns")
        else:
            self._vscroll.grid_remove()
            self._canvas.yview_moveto(0)

    def _update_inner_width(self, event):
        self._canvas.itemconfig(self._win_id, width=event.width)
        self._update_scrollregion()

    def scroll_y(self, delta: int) -> None:
        if self.inner.winfo_reqheight() > self._canvas.winfo_height():
            self._canvas.yview_scroll(delta, "units")

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
        self.cfg = load_config()
        w = max(880, int(self.cfg.get("window_width", 1200)))
        h = max(560, int(self.cfg.get("window_height", 750)))
        self.geometry(f"{w}x{h}")
        self.minsize(880, 560)
        self._resize_job = None
        self.mod_page = tk.IntVar(value=1)
        self.preset_page = tk.IntVar(value=1)
        self.search_var = tk.StringVar()
        self.label_filter_var = tk.StringVar()
        self.label_edit_var = tk.StringVar()
        self.order_var = tk.StringVar(value=self.cfg.get("order_var", "Default"))
        self.mod_view_mode = tk.StringVar(value=self.cfg.get("mod_view_mode", "list"))
        self.status_var = tk.StringVar()
        self.placeholder_images: Dict[str, tk.PhotoImage] = {}
        self.current_mod_items = []
        self.current_mods_shown = []
        self.current_mod_labels = {}
        self.current_mod_records = {}
        self.current_broken = []
        self.drop_targets = []
        self.busy = False
        self.action_widgets = []
        self.mod_selection_widgets = []
        self.tile_widgets = []
        self.tile_columns = 1
        self.tile_canvas_width = 0
        self.tile_selected_index = 0
        self.tile_rendered_range = (0, 0)
        self.list_render_offset = 0
        self.list_selected_index = 0
        self.list_rendered_range = (0, 0)
        self.tile_layout_job = None
        self.detail_wrap_labels = []
        self.updating_mod_selection = False
        self.mod_sort_key = self.cfg.get("mod_sort_key", "d")
        self.mod_sort_reverse = bool(self.cfg.get("mod_sort_reverse", False))
        self.preset_sort_key = self.cfg.get("preset_sort_key", "name")
        self.preset_sort_reverse = bool(self.cfg.get("preset_sort_reverse", False))
        self.order_var.trace_add("write", self._save_order_setting)
        self.ui_scale_values = ["25%", "50%", "75%", "100%", "125%", "150%", "175%", "200%"]
        self._scroll_frames: list = []
        self._pool = WorkerPool()
        self._poll_job: str | None = None
        self._apply_gui_style()
        self._build()
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Control-v>", self._handle_paste)
        self._bind_navigation_events()
        self.drop_targets.append(WindowsDropTarget(self, self._handle_mods_drop))
        self.drop_targets.append(WindowsDropTarget(self.mods_tree, self._handle_mods_drop))
        self.bind("<Configure>", self._on_window_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_polling()
        self.refresh_all()

    def _on_window_configure(self, event) -> None:
        if event.widget is not self:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(500, self._save_window_size)

    def _start_polling(self) -> None:
        results = self._pool.poll()
        if results:
            self._pool.fire_callbacks(results)
        self._poll_job = self.after(50, self._start_polling)

    def _on_close(self) -> None:
        if self._poll_job:
            self.after_cancel(self._poll_job)
        self._pool.shutdown()
        self.destroy()

    def _safe_bind_all(self, sequence: str, callback: Callable) -> None:
        try:
            self.bind_all(sequence, callback)
        except tk.TclError:
            pass

    def _bind_navigation_events(self) -> None:
        for sequence in ["<BackSpace>", "<Button-4>", "<KeyPress-XF86Back>", "<KeyPress-BrowserBack>", "<KeyPress-MediaPrevious>"]:
            self._safe_bind_all(sequence, self._nav_back)
        for sequence in ["<Button-5>", "<KeyPress-XF86Forward>", "<KeyPress-BrowserForward>", "<KeyPress-MediaNext>"]:
            self._safe_bind_all(sequence, self._nav_forward)
        for sequence in ["<Up>", "<Down>", "<Left>", "<Right>"]:
            self._safe_bind_all(sequence, self._on_arrow_key)
        for sequence in ["<Control-plus>", "<Control-equal>", "<Control-KP_Add>"]:
            self._safe_bind_all(sequence, lambda _event: self._zoom_tiles(1))
        for sequence in ["<Control-minus>", "<Control-KP_Subtract>"]:
            self._safe_bind_all(sequence, lambda _event: self._zoom_tiles(-1))

    def _is_mods_tab_active(self) -> bool:
        try:
            return self.notebook.index(self.notebook.select()) == 0
        except Exception:
            return False

    def _is_tile_view(self) -> bool:
        return self.mod_view_mode.get() == "tiles"

    def _nav_back(self, event=None):
        if not self._is_mods_tab_active():
            return None
        self._change_mod_page(-1)
        return "break"

    def _nav_forward(self, event=None):
        if not self._is_mods_tab_active():
            return None
        self._change_mod_page(1)
        return "break"

    def _on_arrow_key(self, event):
        if not self._is_mods_tab_active():
            return None
        keysym = getattr(event, "keysym", "")
        if self._is_tile_view():
            moves = {
                "Left": -1,
                "Right": 1,
                "Up": -max(1, self.tile_columns),
                "Down": max(1, self.tile_columns),
            }
            delta = moves.get(keysym)
            if delta is None:
                return None
            self._select_tile_index(self.tile_selected_index + delta)
            return "break"
        if keysym not in ("Up", "Down") or not self.current_mods_shown:
            return None
        delta = 1 if keysym == "Down" else -1
        new_index = max(0, min(self.list_selected_index + delta, len(self.current_mods_shown) - 1))
        self.list_selected_index = new_index
        self.tile_selected_index = new_index
        visible = self._list_visible_rows()
        if new_index < self.list_render_offset:
            self.list_render_offset = new_index
        elif new_index >= self.list_render_offset + visible:
            self.list_render_offset = max(0, new_index - visible + 1)
        self._refresh_mod_list()
        iid = str(new_index + 1)
        if self.mods_tree.exists(iid):
            self.updating_mod_selection = True
            try:
                self.mods_tree.selection_set(iid)
                self.mods_tree.focus(iid)
            finally:
                self.updating_mod_selection = False
        return "break"

    def _save_window_size(self) -> None:
        self._resize_job = None
        w = self.winfo_width()
        h = self.winfo_height()
        if w > 0 and h > 0:
            self.cfg["window_width"] = w
            self.cfg["window_height"] = h
            save_config(self.cfg)

    def _on_mousewheel(self, event) -> None:
        ctrl_held = bool(getattr(event, "state", 0) & 0x4)
        if self._is_mods_tab_active() and self._is_tile_view():
            if ctrl_held:
                return self._zoom_tiles(1 if event.delta > 0 else -1)
            self._on_tile_scroll("scroll", int(-1 * (event.delta / 120)), "units")
            return "break"
        if self._is_mods_tab_active() and not self._is_tile_view():
            self._on_list_scroll("scroll", int(-1 * (event.delta / 120)), "units")
            return "break"
        w = self.winfo_containing(event.x_root, event.y_root)
        while w:
            if isinstance(w, ttk.Treeview):
                if event.widget is not w:
                    w.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return
            if isinstance(w, ScrollableTabFrame):
                w.scroll_y(int(-1 * (event.delta / 120)))
                return
            w = getattr(w, "master", None)

    def _resize_notebook_tabs(self) -> None:
        nb = getattr(self, "notebook", None)
        if not nb:
            return
        tabs = nb.tabs()
        if not tabs:
            return
        scale = self._ui_scale()
        hpad = max(6, int(14 * scale))
        vpad = max(4, int(8 * scale))
        for tab_id in tabs:
            nb.tab(tab_id, padding=(hpad, vpad))

    def _ui_scale(self) -> float:
        try:
            raw = self.cfg.get("ui_scale_percent") or self.cfg.get("button_size_percent", 100)
            value = str(raw).strip().rstrip("%")
            return max(25, int(value)) / 100
        except Exception:
            return 1

    def _apply_gui_style(self) -> None:
        font_family = (self.cfg.get("gui_font_family") or "").strip()
        try:
            base_font_size = max(6, int(self.cfg.get("gui_font_size", 10)))
        except Exception:
            base_font_size = 10
        scale = self._ui_scale()
        font_size = max(6, round(base_font_size * scale))
        for font_name in ["TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"]:
            try:
                options = {"size": font_size}
                if font_family:
                    options["family"] = font_family
                tkfont.nametofont(font_name).configure(**options)
            except tk.TclError:
                pass
        style = ttk.Style(self)
        style.configure("TButton", padding=(int(12 * scale), int(7 * scale)))
        style.configure("Treeview", rowheight=max(30, int(34 * scale)))
        style.configure("Mods.Treeview", rowheight=max(30, int(34 * scale)))

    def _rebuild_tabs(self) -> None:
        self.action_widgets.clear()
        self.mod_selection_widgets.clear()
        for tab in [self.mods_tab, self.presets_tab, self.settings_tab, self.broken_tab]:
            for child in tab.winfo_children():
                child.destroy()
        self._apply_gui_style()
        self._build_mods()
        self._build_presets()
        self._build_settings()
        self._build_broken()
        self.drop_targets = self.drop_targets[:1]
        self.drop_targets.append(WindowsDropTarget(self.mods_tree, self._handle_mods_drop))
        self.after_idle(self._resize_notebook_tabs)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=(4, 6))
        root.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<Configure>", lambda _e: self.after_idle(self._resize_notebook_tabs))

        def _tab(text: str) -> ttk.Frame:
            sf = ScrollableTabFrame(self.notebook, padding=(4, 6))
            self._scroll_frames.append(sf)
            self.notebook.add(sf, text=text)
            return sf.inner

        mods_outer = ttk.Frame(self.notebook, padding=(4, 6))
        self.notebook.add(mods_outer, text="⊞  Mods")
        self.mods_tab = mods_outer
        self.presets_tab  = _tab("☰  Presets")
        self.settings_tab = _tab("⚙  Settings")
        self.broken_tab   = _tab("⚠  Broken")
        self._build_mods()
        self._build_presets()
        self._build_settings()
        self._build_broken()
        status = ttk.Label(root, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", pady=(8, 0))

    def _button(self, master, text: str, command: Callable, tooltip: str = ""):
        scale = self._ui_scale()
        width = max(3, int(4 * scale)) if len(text) <= 3 else max(int(14 * scale), len(text) + 2)
        btn = ttk.Button(master, text=text, command=command, width=width)
        if tooltip:
            _Tooltip(btn, tooltip)
        self.action_widgets.append(btn)
        return btn

    def _on_mod_selection_changed(self) -> None:
        tree = getattr(self, "mods_tree", None)
        if not tree or self.busy or self.updating_mod_selection:
            return
        selection = tree.selection()
        if selection and str(selection[0]).isdigit():
            index = int(selection[0]) - 1
            if 0 <= index < len(self.current_mods_shown):
                self.list_selected_index = index
                self.tile_selected_index = index
                self._refresh_mod_detail(self.current_mods_shown[index])
        state = "normal" if selection else "disabled"
        for w in self.mod_selection_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in self.action_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        if not busy:
            self._on_mod_selection_changed()
        self.configure(cursor="watch" if busy else "")
        if text:
            self.status_var.set(text)
        self.update_idletasks()

    def _run_action(self, label: str, worker: Callable, done: Callable | None = None, file_key: str = "global") -> None:
        if self.busy:
            return
        logger.info("action: %s", label)
        self._set_busy(True, f"{label}...")

        def callback(result, error):
            self.after(0, lambda: self._finish_action(error, result, done))

        self._pool.submit(file_key, worker, callback=callback)

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
        self.search_box.bind("<Return>", lambda e: self._mods_search())
        top.add(self.search_box, padx=(6, 12))
        top.add(ttk.Label(top, text="Label"))
        self.label_filter_box = AutocompleteCombobox(top, textvariable=self.label_filter_var, width=18)
        self.label_filter_box.bind("<Return>", lambda e: self._mods_search())
        top.add(self.label_filter_box, padx=(6, 12))
        top.add(ttk.Label(top, text="Order"))
        top.add(ttk.Combobox(top, textvariable=self.order_var, values=["Default", "Created date"], width=14, state="readonly"), padx=(6, 12))
        top.add(ttk.Label(top, text="View"))
        view_box = ttk.Combobox(top, textvariable=self.mod_view_mode, values=["list", "tiles"], width=8, state="readonly")
        view_box.bind("<<ComboboxSelected>>", lambda _event: self._on_mod_view_mode_changed())
        top.add(view_box, padx=(6, 12))
        top.add(self._button(top, "↺", self._mods_search, "Search / Refresh"))
        top.add(self._button(top, "✕", self._mods_clear, "Clear"), padx=(6, 0))
        self.mods_view_area = ttk.Frame(self.mods_tab)
        self.mods_view_area.pack(fill="both", expand=True, pady=8)
        self.mods_view_area.pack_propagate(False)
        self.mods_list_frame = ttk.Frame(self.mods_view_area)
        self.mods_tree = ttk.Treeview(self.mods_list_frame, columns=("name", "label", "last"), show="tree headings", selectmode="extended", style="Mods.Treeview")
        self.mods_tree_scroll = ttk.Scrollbar(self.mods_list_frame, orient="vertical", command=self._on_list_scroll)
        self.mods_tree.heading("#0", text="")
        self.mods_tree.heading("name", text="Mod", command=lambda: self._sort_mods("name"))
        self.mods_tree.heading("label", text="Label", command=lambda: self._sort_mods("label"))
        self.mods_tree.heading("last", text="Last managed", command=lambda: self._sort_mods("last_managed"))
        self.mods_tree.column("#0", width=int(self.cfg.get("placeholder_image_col_width", 56)), minwidth=36, stretch=False, anchor="center")
        self.mods_tree.column("name", width=470)
        self.mods_tree.column("label", width=160)
        self.mods_tree.column("last", width=160, stretch=False)
        self.mods_tree.tag_configure("installed", background="#d4edda")
        self.mods_tree.bind("<ButtonRelease-1>", self._save_placeholder_width)
        self.mods_tree.bind("<Double-1>", lambda _: self._toggle_selected_mods())
        self.mods_tree.bind("<<TreeviewSelect>>", lambda _: self._on_mod_selection_changed())
        self.mods_tree.bind("<Configure>", lambda _event: self._refresh_mod_list())
        self.mods_tree.grid(row=0, column=0, sticky="nsew")
        self.mods_tree_scroll.grid(row=0, column=1, sticky="ns")
        self.mods_list_frame.rowconfigure(0, weight=1)
        self.mods_list_frame.columnconfigure(0, weight=1)
        self.tile_pane = ttk.Panedwindow(self.mods_view_area, orient="horizontal")
        tile_outer = ttk.Frame(self.tile_pane)
        self.tile_canvas = tk.Canvas(tile_outer, highlightthickness=0, bd=0)
        self.tile_scroll = ttk.Scrollbar(tile_outer, orient="vertical", command=self._on_tile_scroll)
        self.tile_canvas.configure(yscrollcommand=self.tile_scroll.set)
        self.tile_canvas.grid(row=0, column=0, sticky="nsew")
        self.tile_scroll.grid(row=0, column=1, sticky="ns")
        tile_outer.rowconfigure(0, weight=1)
        tile_outer.columnconfigure(0, weight=1)
        self.tile_inner = ttk.Frame(self.tile_canvas)
        self.tile_window_id = self.tile_canvas.create_window((0, 0), window=self.tile_inner, anchor="nw")
        self.tile_inner.bind("<Configure>", self._update_tile_scrollregion)
        self.tile_canvas.bind("<Configure>", self._on_tile_canvas_configure)
        self.detail_frame = ttk.Frame(self.tile_pane, padding=(10, 4))
        self.detail_frame.bind("<Configure>", self._update_detail_wrap)
        self.tile_pane.add(tile_outer, weight=3)
        self.tile_pane.add(self.detail_frame, weight=2)
        actions = WrapFrame(self.mods_tab)
        actions.pack(fill="x", side="bottom")
        actions.configure(height=max(44, int(52 * self._ui_scale())))
        actions.add(self._button(actions, "<", lambda: self._change_mod_page(-1), "Previous page"))
        actions.add(self._button(actions, ">", lambda: self._change_mod_page(1), "Next page"), padx=(6, 12))
        actions.add(ttk.Label(actions, text="Page"))
        mod_page_spin = ttk.Spinbox(actions, from_=1, to=9999, textvariable=self.mod_page, width=6, command=self.refresh_mods)
        self.action_widgets.append(mod_page_spin)
        actions.add(mod_page_spin, padx=(6, 12))
        actions.add(self._button(actions, "▼✓", self._install_page, "Install page"))
        actions.add(self._button(actions, "▲✗", self._uninstall_page, "Uninstall page"), padx=(6, 0))
        toggle_btn = self._button(actions, "⇅✓", self._toggle_selected_mods, "Toggle selected")
        actions.add(toggle_btn, padx=(6, 12))
        self.mod_selection_widgets.append(toggle_btn)
        actions.add(self._button(actions, "📥", self._import_mod_files, "Import mods"), padx=(6, 0))
        actions.add(self._button(actions, "📂", self._import_mod_folder, "Import folder"), padx=(6, 0))
        img_btn = self._button(actions, "🖼", self._set_mod_image, "Set image")
        actions.add(img_btn, padx=(6, 12))
        self.mod_selection_widgets.append(img_btn)
        label_group = ttk.Frame(actions)
        ttk.Label(label_group, text="Label").pack(side="left")
        self.label_edit_box = AutocompleteCombobox(label_group, textvariable=self.label_edit_var, width=18)
        self.label_edit_box.pack(side="left", padx=(6, 6))
        self.mod_selection_widgets.append(self.label_edit_box)
        add_btn = self._button(label_group, "+", self._add_label_selected, "Add label")
        add_btn.pack(side="left")
        self.mod_selection_widgets.append(add_btn)
        remove_btn = self._button(label_group, "-", self._remove_label_selected, "Remove label")
        remove_btn.pack(side="left", padx=(6, 0))
        self.mod_selection_widgets.append(remove_btn)
        actions.add(label_group)
        self.after_idle(self._on_mod_selection_changed)
        self._show_mod_view()

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
        self.presets_tree.tag_configure("applied", background="#d4edda")
        self.presets_tree.pack(fill="both", expand=True, pady=8)
        self.presets_tree.bind("<Double-1>", lambda e: self._toggle_selected_presets())
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

    def _setting_preview_text(self, key: str, val: str) -> str:
        if key == "link_prefix":
            if val:
                return f'"mod.pak"  →  "mod{val}.pak"'
            return '"mod.pak"  →  "mod.pak"  (prefix not set)'
        if key == "mod_extensions":
            if not val:
                return "All files included"
            parts = [e.strip().lstrip(".") for e in val.split(",") if e.strip()]
            return "Filter: " + ",  ".join(f".{p}" for p in parts if p)
        return ""

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
            ("ui_scale_percent", "UI Scale"),
            ("gui_font_family", "Font"),
            ("gui_font_size", "Font size"),
            ("mod_view_mode", "Mod view mode"),
            ("tile_size", "Tile size"),
            ("window_width", "Window width"),
            ("window_height", "Window height"),
        ]
        preview_keys = {"mod_extensions", "link_prefix"}
        for row, (key, label) in enumerate(rows):
            ttk.Label(self.settings_tab, text=label).grid(row=row, column=0, sticky="nw", pady=4)
            var = tk.StringVar(value=str(self.cfg.get(key, "")))
            if key == "ui_scale_percent":
                raw = self.cfg.get("ui_scale_percent") or self.cfg.get("button_size_percent", 100)
                var = tk.StringVar(value=f"{str(raw).strip().rstrip('%')}%")
            self.setting_vars[key] = var
            if key == "ui_scale_percent":
                ttk.Combobox(self.settings_tab, textvariable=var, values=self.ui_scale_values, state="readonly", width=12).grid(row=row, column=1, sticky="w", padx=8, pady=4)
            elif key == "mod_view_mode":
                ttk.Combobox(self.settings_tab, textvariable=var, values=["list", "tiles"], state="readonly", width=12).grid(row=row, column=1, sticky="w", padx=8, pady=4)
            elif key == "gui_font_family":
                ttk.Combobox(self.settings_tab, textvariable=var, values=sorted(tkfont.families()), width=40).grid(row=row, column=1, sticky="w", padx=8, pady=4)
            elif key in preview_keys:
                cell = ttk.Frame(self.settings_tab)
                ttk.Entry(cell, textvariable=var).pack(fill="x")
                preview_lbl = ttk.Label(cell, foreground="#888888")
                preview_lbl.pack(anchor="w", pady=(2, 0))
                cell.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
                def _update(*_, k=key, v=var, lbl=preview_lbl):
                    lbl.config(text=self._setting_preview_text(k, v.get().strip()))
                var.trace_add("write", _update)
                _update(None)
            else:
                ttk.Entry(self.settings_tab, textvariable=var, width=70).grid(row=row, column=1, sticky="ew", padx=8, pady=4)
            if key in ["game_mods_dir", "mods_source_dir"]:
                self._button(self.settings_tab, "…", lambda k=key: self._browse_setting(k), "Browse").grid(row=row, column=2, pady=4)
        self.settings_tab.columnconfigure(1, weight=1)
        buttons = WrapFrame(self.settings_tab)
        buttons.grid(row=len(rows), column=0, columnspan=3, sticky="ew", pady=(12, 0))
        buttons.add(self._button(buttons, "✔", self._save_settings, "Save settings"))
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

    def _on_mod_view_mode_changed(self) -> None:
        mode = self.mod_view_mode.get()
        if mode not in ["list", "tiles"]:
            mode = "list"
            self.mod_view_mode.set(mode)
        self.cfg["mod_view_mode"] = mode
        save_config(self.cfg)
        self._show_mod_view()
        self.refresh_mods()

    def _show_mod_view(self) -> None:
        if not hasattr(self, "mods_tree"):
            return
        self.mods_list_frame.pack_forget()
        self.tile_pane.pack_forget()
        if self._is_tile_view():
            self.tile_pane.pack(in_=self.mods_view_area, fill="both", expand=True)
            self._refresh_mod_tiles()
        else:
            self.mods_list_frame.pack(in_=self.mods_view_area, fill="both", expand=True)
            self._refresh_mod_list()

    def _mod_order_mode(self) -> str:
        if self.order_var.get().strip() == "Created date":
            return "cd"
        if self.mod_sort_key == "d":
            return "d"
        return f"-{self.mod_sort_key}" if self.mod_sort_reverse else self.mod_sort_key

    def _preset_order_mode(self) -> str:
        return f"-{self.preset_sort_key}" if self.preset_sort_reverse else self.preset_sort_key

    def _sort_mods(self, key: str) -> None:
        if self.mod_sort_key == key:
            self.mod_sort_reverse = not self.mod_sort_reverse
        else:
            self.mod_sort_key = key
            self.mod_sort_reverse = False
        self.cfg["mod_sort_key"] = self.mod_sort_key
        self.cfg["mod_sort_reverse"] = self.mod_sort_reverse
        save_config(self.cfg)
        self.mod_page.set(1)
        self.refresh_mods()

    def _sort_presets(self, key: str) -> None:
        if self.preset_sort_key == key:
            self.preset_sort_reverse = not self.preset_sort_reverse
        else:
            self.preset_sort_key = key
            self.preset_sort_reverse = False
        self.cfg["preset_sort_key"] = self.preset_sort_key
        self.cfg["preset_sort_reverse"] = self.preset_sort_reverse
        save_config(self.cfg)
        self.preset_page.set(1)
        self.refresh_presets()

    def _save_order_setting(self, *_) -> None:
        self.cfg["order_var"] = self.order_var.get()
        save_config(self.cfg)

    def _save_placeholder_width(self, _event=None) -> None:
        width = int(self.mods_tree.column("#0", "width"))
        if width != int(self.cfg.get("placeholder_image_col_width", 56)):
            self.cfg["placeholder_image_col_width"] = width
            save_config(self.cfg)
            self.placeholder_images.clear()
            self.refresh_mods()

    def _image_width(self) -> int:
        return max(16, int(self.mods_tree.column("#0", "width")) - 20)

    def _tile_size(self) -> int:
        try:
            return max(88, min(260, int(self.cfg.get("tile_size", 140))))
        except Exception:
            return 140

    def _list_row_height(self) -> int:
        try:
            return max(24, int(ttk.Style(self).lookup("Mods.Treeview", "rowheight") or 34))
        except Exception:
            return 34

    def _list_visible_rows(self) -> int:
        configured = str(self.mods_tree.cget("height") or "").strip()
        if configured.isdigit():
            return max(1, int(configured))
        height = max(1, self.mods_tree.winfo_height() - self._list_row_height())
        return max(1, height // self._list_row_height())

    def _list_virtual_range(self) -> tuple[int, int]:
        total = len(self.current_mods_shown)
        if total <= 0:
            return 0, 0
        visible = self._list_visible_rows()
        start = max(0, min(self.list_render_offset, max(0, total - visible)))
        end = min(total, start + visible)
        start = max(0, start - 1)
        return start, end

    def _sync_list_scrollbar(self) -> None:
        total = len(self.current_mods_shown)
        if total <= 0:
            self.mods_tree_scroll.set(0, 1)
            return
        visible = self._list_visible_rows()
        first = max(0, min(self.list_render_offset, max(0, total - visible))) / total
        last = min(total, self.list_render_offset + visible) / total
        self.mods_tree_scroll.set(first, max(first, last))

    def _on_list_scroll(self, *args) -> None:
        total = len(self.current_mods_shown)
        if total <= 0:
            return
        visible = self._list_visible_rows()
        max_offset = max(0, total - visible)
        if args[0] == "moveto":
            self.list_render_offset = min(max_offset, max(0, int(float(args[1]) * total)))
        elif args[0] == "scroll":
            amount = int(args[1])
            unit = args[2] if len(args) > 2 else "units"
            step = visible if unit == "pages" else 1
            self.list_render_offset = max(0, min(max_offset, self.list_render_offset + amount * step))
        self._refresh_mod_list()

    def _on_tile_scroll(self, *args) -> None:
        self.tile_canvas.yview(*args)
        self._refresh_mod_tiles()

    def _zoom_tiles(self, direction: int):
        if not self._is_mods_tab_active() or not self._is_tile_view():
            return None
        size = self._tile_size() + (12 if direction > 0 else -12)
        self.cfg["tile_size"] = max(88, min(260, size))
        save_config(self.cfg)
        self.placeholder_images.clear()
        self._refresh_mod_tiles()
        return "break"

    def _insert_list_row(self, index: int, position) -> None:
        mod = self.current_mods_shown[index]
        rec = self.current_mod_records.get(mod.name, {})
        image = self._placeholder(mod.name, mod.installed)
        name_display = f"✓  {mod.name}" if mod.installed else mod.name
        tags = ("installed",) if mod.installed else ()
        self.mods_tree.insert(
            "", position,
            iid=str(index + 1), text="", image=image,
            values=(name_display, self.current_mod_labels.get(mod.name, "-"), rec.get("last_managed") or "-"),
            tags=tags,
        )

    def _refresh_mod_list(self) -> None:
        if not hasattr(self, "mods_tree") or self._is_tile_view():
            return
        selected = self.mods_tree.selection()
        selected_iids = set(selected)
        start, end = self._list_virtual_range()
        old_start, old_end = self.list_rendered_range
        self.list_rendered_range = (start, end)

        overlap_start = max(start, old_start)
        overlap_end = min(end, old_end)
        incremental = overlap_end > overlap_start and all(
            self.mods_tree.exists(str(i + 1)) for i in range(overlap_start, overlap_end)
        )

        if incremental:
            gone_before = [str(i + 1) for i in range(old_start, start) if self.mods_tree.exists(str(i + 1))]
            if gone_before:
                self.mods_tree.delete(*gone_before)
            gone_after = [str(i + 1) for i in range(end, old_end) if self.mods_tree.exists(str(i + 1))]
            if gone_after:
                self.mods_tree.delete(*gone_after)
            for index in range(start, min(end, old_start)):
                self._insert_list_row(index, index - start)
            for index in range(max(start, old_end), end):
                self._insert_list_row(index, "end")
        else:
            existing = self.mods_tree.get_children()
            if existing:
                self.mods_tree.delete(*existing)
            for index in range(start, end):
                self._insert_list_row(index, "end")

        visible_selected = [iid for iid in selected_iids if self.mods_tree.exists(iid)]
        self.updating_mod_selection = True
        try:
            if visible_selected:
                self.mods_tree.selection_set(visible_selected)
            elif self.current_mods_shown and not selected_iids:
                iid = str(self.list_selected_index + 1)
                if self.mods_tree.exists(iid):
                    self.mods_tree.selection_set(iid)
                    self.mods_tree.focus(iid)
        finally:
            self.updating_mod_selection = False
        self._sync_list_scrollbar()

    def _pixel_hex(self, color) -> str:
        if isinstance(color, tuple):
            return "#%02x%02x%02x" % color[:3]
        return str(color)

    def _center_in_frame(self, img: tk.PhotoImage, width: int, height: int, bg: str) -> tk.PhotoImage:
        iw, ih = img.width(), img.height()
        if iw == width and ih == height:
            return img
        frame = tk.PhotoImage(width=width, height=height)
        frame.put(bg, to=(0, 0, width, height))
        x_off = max(0, (width - iw) // 2)
        y_off = max(0, (height - ih) // 2)
        frame.tk.call(frame, "copy", img, "-to", x_off, y_off)
        return frame

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

    def _placeholder(self, name: str, installed: bool = False, width: int | None = None) -> tk.PhotoImage:
        width = width or self._image_width()
        key = f"{name}:{width}:{installed}"
        if key in self.placeholder_images:
            return self.placeholder_images[key]
        path = mod_image_path(self.cfg, name)
        max_h = max(28, int(width * 0.65))
        bg = "#d4edda" if installed else "white"
        img = None
        if path:
            try:
                raw = tk.PhotoImage(file=str(path))
                src_w = max(1, raw.width())
                src_h = max(1, raw.height())
                fit_w = min(width, max(1, int(src_w * max_h / src_h)))
                scaled = self._resize_image(raw, fit_w)
                img = self._center_in_frame(scaled, width, max_h, bg)
            except tk.TclError:
                raw_gdi = _load_image_gdi(path, width, max_h)
                if raw_gdi:
                    img = self._center_in_frame(raw_gdi, width, max_h, bg)
        if img is None:
            img = tk.PhotoImage(width=width, height=max_h)
            colors = ["#d9e8fb", "#e4f4de", "#f7e6d0", "#eadff7", "#f7dfe8"]
            color = colors[sum(ord(c) for c in name) % len(colors)]
            img.put(color, to=(0, 0, width, max_h))
        self.placeholder_images[key] = img
        return img

    def _update_tile_scrollregion(self, _event=None) -> None:
        if not hasattr(self, "tile_canvas"):
            return
        rows = max(1, (len(self.current_mods_shown) + max(1, self.tile_columns) - 1) // max(1, self.tile_columns))
        row_h = self._tile_row_height()
        self.tile_canvas.configure(scrollregion=(0, 0, max(1, self.tile_canvas_width), max(row_h, rows * row_h)))

    def _on_tile_canvas_configure(self, event) -> None:
        old_columns = self.tile_columns
        self.tile_canvas_width = max(1, event.width)
        self.tile_canvas.itemconfig(self.tile_window_id, width=event.width)
        new_columns = self._tile_column_count()
        if self._is_tile_view() and self.current_mods_shown and new_columns != old_columns:
            self._refresh_mod_tiles()
        else:
            self._update_tile_scrollregion()

    def _tile_column_count(self) -> int:
        width = max(1, self.tile_canvas_width or self.tile_canvas.winfo_width())
        tile_w = self._tile_size() + 18
        return max(1, width // tile_w)

    def _tile_row_height(self) -> int:
        return max(1, int(self._tile_size() * 1.32) + 12)

    def _tile_virtual_range(self) -> tuple[int, int]:
        total = len(self.current_mods_shown)
        if total <= 0:
            return 0, 0
        columns = max(1, self.tile_columns)
        row_h = self._tile_row_height()
        y0 = self.tile_canvas.canvasy(0)
        height = max(1, self.tile_canvas.winfo_height())
        first_row = max(0, int(y0 // row_h) - 1)
        last_row = int((y0 + height) // row_h) + 1
        start = max(0, first_row * columns)
        end = min(total, (last_row + 1) * columns)
        return start, end

    def _select_tile_index(self, index: int) -> None:
        if not self.current_mods_shown:
            self.tile_selected_index = 0
            self.mods_tree.selection_remove(self.mods_tree.selection())
            self._refresh_mod_detail(None)
            return
        index = max(0, min(index, len(self.current_mods_shown) - 1))
        prev_index = self.tile_selected_index
        self.tile_selected_index = index
        self.list_selected_index = index
        iid = str(index + 1)
        if iid in self.mods_tree.get_children():
            self.updating_mod_selection = True
            try:
                self.mods_tree.selection_set(iid)
                self.mods_tree.focus(iid)
                self.mods_tree.see(iid)
            finally:
                self.updating_mod_selection = False
        start, _end = self.tile_rendered_range

        def _set_tile_bg(actual_index: int, selected: bool) -> None:
            widget_i = actual_index - start
            if not (0 <= widget_i < len(self.tile_widgets)):
                return
            frame = self.tile_widgets[widget_i]
            mod = self.current_mods_shown[actual_index] if actual_index < len(self.current_mods_shown) else None
            bg = "#cfe8ff" if selected else ("#d4edda" if mod and mod.installed else "#f7f7f7")
            frame.configure(bg=bg, highlightbackground="#3777b8" if selected else bg)
            for child in frame.winfo_children():
                try:
                    child.configure(bg=bg)
                except tk.TclError:
                    pass

        if prev_index != index:
            _set_tile_bg(prev_index, False)
        _set_tile_bg(index, True)
        self._refresh_mod_detail(self.current_mods_shown[index])

    def _refresh_mod_tiles(self) -> None:
        if not hasattr(self, "tile_inner") or not self._is_tile_view():
            return
        self.tile_layout_job = None
        selected_name = ""
        if self.current_mods_shown and 0 <= self.tile_selected_index < len(self.current_mods_shown):
            selected_name = self.current_mods_shown[self.tile_selected_index].name
        for child in self.tile_inner.winfo_children():
            child.destroy()
        self.tile_widgets = []
        self.tile_columns = self._tile_column_count()
        size = self._tile_size()
        start, end = self._tile_virtual_range()
        self.tile_rendered_range = (start, end)
        for index in range(start, end):
            mod = self.current_mods_shown[index]
            row = index // self.tile_columns
            col = index % self.tile_columns
            bg = "#d4edda" if mod.installed else "#f7f7f7"
            frame = tk.Frame(self.tile_inner, bg=bg, bd=0, relief="solid", highlightthickness=2, highlightbackground=bg)
            frame.grid(row=row, column=col, sticky="n", padx=6, pady=6)
            frame.configure(width=size + 12, height=int(size * 1.32))
            frame.grid_propagate(False)
            img = self._placeholder(mod.name, mod.installed, size)
            image_label = tk.Label(frame, image=img, bg=bg)
            image_label.image = img
            image_label.pack(padx=6, pady=(6, 4))
            title = f"✓ {mod.name}" if mod.installed else mod.name
            name_label = tk.Label(frame, text=title, bg=bg, wraplength=max(60, size), justify="center")
            name_label.pack(fill="x", padx=6)
            label_text = self.current_mod_labels.get(mod.name) or "-"
            label = tk.Label(frame, text=label_text, bg=bg, fg="#555555", wraplength=max(60, size), justify="center")
            label.pack(fill="x", padx=6, pady=(2, 6))
            for widget in [frame, image_label, name_label, label]:
                widget.bind("<Button-1>", lambda _event, i=index: self._select_tile_index(i))
                widget.bind("<Double-1>", lambda _event: self._toggle_selected_mods())
            self.tile_widgets.append(frame)
        if self.current_mods_shown:
            if selected_name:
                matches = [i for i, mod in enumerate(self.current_mods_shown) if mod.name == selected_name]
                self.tile_selected_index = matches[0] if matches else min(self.tile_selected_index, len(self.current_mods_shown) - 1)
            self._select_tile_index(self.tile_selected_index)
        else:
            self._select_tile_index(0)
        self._update_tile_scrollregion()

    def _detail_row(self, parent, label: str, value: str, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", pady=2)
        value_label = ttk.Label(parent, text=value, wraplength=max(120, parent.winfo_width() - 120), justify="left")
        value_label.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
        parent.columnconfigure(1, weight=1)
        self.detail_wrap_labels.append(value_label)

    def _toggle_label_filter(self, label: str) -> None:
        label = (label or "").strip()
        if not label or label == "-":
            return
        if self.label_filter_var.get().strip().lower() == label.lower():
            self.label_filter_var.set("")
        else:
            self.label_filter_var.set(label)
        self.mod_page.set(1)
        self.refresh_mods()

    def _detail_label_row(self, parent, value: str, row: int) -> None:
        ttk.Label(parent, text="Label").grid(row=row, column=0, sticky="nw", pady=2)
        active = bool(value and value != "-" and self.label_filter_var.get().strip().lower() == value.lower())
        text = value if value and value != "-" else "-"
        suffix = " (active)" if active else ""
        label_button = ttk.Label(
            parent,
            text=text + suffix,
            relief="solid",
            padding=(4, 0),
            cursor="hand2" if value and value != "-" else "",
        )
        if value and value != "-":
            label_button._command = lambda v=value: self._toggle_label_filter(v)
            label_button.bind("<Button-1>", lambda _event: label_button._command())
        label_button.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=2)
        parent.columnconfigure(1, weight=1)

    def _refresh_mod_detail(self, mod: ModItem | None) -> None:
        if not hasattr(self, "detail_frame"):
            return
        for child in self.detail_frame.winfo_children():
            child.destroy()
        self.detail_wrap_labels = []
        if not mod:
            ttk.Label(self.detail_frame, text="No mod selected").pack(anchor="w")
            return
        rec = self.current_mod_records.get(mod.name, {})
        title = f"✓ {mod.name}" if mod.installed else mod.name
        ttk.Label(self.detail_frame, text=title, font=("TkDefaultFont", 12, "bold")).pack(anchor="w", fill="x")
        status = ttk.Frame(self.detail_frame)
        status.pack(fill="x", pady=(10, 0))
        label_value = self.current_mod_labels.get(mod.name) or "-"
        rows = [
            ("State", "Installed" if mod.installed else "Not installed"),
            ("Type", "Folder" if mod.is_dir else "File"),
            ("Last managed", rec.get("last_managed") or "-"),
            ("Source", str(mod.src)),
            ("Destination", str(mod.dest)),
        ]
        for row, (label, value) in enumerate(rows[:2]):
            self._detail_row(status, label, value, row)
        self._detail_label_row(status, label_value, 2)
        for row, (label, value) in enumerate(rows[2:], start=3):
            self._detail_row(status, label, value, row)
        description = ttk.LabelFrame(self.detail_frame, text="Description", padding=(8, 6))
        description.pack(fill="both", expand=True, pady=(12, 0))
        text = (
            f"{mod.name} is {'installed through a link in the game mods folder' if mod.installed else 'available in the source mods folder'}."
            " No separate mod description metadata is stored yet."
        )
        desc = ttk.Label(description, text=text, wraplength=max(180, self.detail_frame.winfo_width() - 30), justify="left")
        desc.pack(fill="both", expand=True)
        self.detail_wrap_labels.append(desc)
        self._update_detail_wrap()

    def _update_detail_wrap(self, _event=None) -> None:
        if not hasattr(self, "detail_frame"):
            return
        wrap = max(160, self.detail_frame.winfo_width() - 32)
        for label in self.detail_wrap_labels:
            try:
                label.configure(wraplength=wrap)
            except tk.TclError:
                pass

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

        def done(result) -> None:
            imported, skipped = result
            self.placeholder_images.clear()
            self.status_var.set(f"Imported: {len(imported)}. Skipped: {len(skipped)}.")
            self.refresh_mods()

        self._run_action("Importing dropped files", partial(_run_import_batch, self.cfg, tasks), done, file_key="import")

    def _handle_paste(self, event=None) -> None:
        focused = self.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text, ttk.Spinbox)):
            return
        try:
            if self.notebook.index(self.notebook.select()) != 0:
                return
        except Exception:
            return
        paths = read_clipboard_paths()
        if paths:
            self._handle_clipboard_paths(paths)
            return
        img_path = read_clipboard_image()
        if img_path:
            self._handle_clipboard_paths([img_path])
            return
        self.status_var.set("Clipboard: no files.")

    def _handle_clipboard_paths(self, paths: List[Path]) -> None:
        if self.busy or not ensure_paths(self.cfg):
            return
        image_paths = [p for p in paths if is_image_file(p)]
        mod_paths = [p for p in paths if is_mod_file(p, self.cfg)]
        tasks = []
        if image_paths:
            indexes = self._selected_indexes(self.mods_tree)
            default_name = ""
            if indexes and 1 <= indexes[0] <= len(self.current_mods_shown):
                default_name = self.current_mods_shown[indexes[0] - 1].name
            if not default_name:
                default_name = self._choose_mod_for_image("")
            if default_name:
                for path in image_paths:
                    tasks.append(("image", path, default_name, True))
        for path in mod_paths:
            exists = any(m.name == path.name for m in self.current_mod_items)
            replace = True
            if exists:
                replace = messagebox.askyesno("Replace mod", f"Replace existing mod '{path.name}'?")
            if replace:
                tasks.append(("mod", path, "", exists))
        if not tasks:
            self.status_var.set("Clipboard: no supported files.")
            return

        def done(result) -> None:
            imported, skipped = result
            self.placeholder_images.clear()
            self.status_var.set(f"Imported: {len(imported)}. Skipped: {len(skipped)}.")
            self.refresh_mods()

        self._run_action("Importing clipboard files", partial(_run_import_batch, self.cfg, tasks), done, file_key="import")

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

        batch = [("mod", path, "", replace) for path, replace in tasks]

        def done(result) -> None:
            imported, skipped = result
            self.status_var.set(f"Imported: {len(imported)}. Skipped: {len(skipped)}.")
            self.refresh_mods()

        self._run_action("Importing mods", partial(_run_import_batch, self.cfg, batch), done, file_key="import")

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

        self._run_action("Saving image", partial(import_mod_image, self.cfg, mod_name, image), done, file_key=f"img:{mod_name}")

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
        self.current_mod_records = records
        self.mod_page.set(page)
        row_height = max(30, int(34 * self._ui_scale()))
        row_height = max(row_height, max(28, int(self._image_width() * 0.65)) + 6)
        ttk.Style(self).configure("Mods.Treeview", rowheight=row_height)
        self.mods_tree.delete(*self.mods_tree.get_children())
        if selected_names:
            selected = [str(i) for i, mod in enumerate(shown, 1) if mod.name in selected_names]
            if selected:
                self.list_selected_index = max(0, int(selected[0]) - 1)
                self.tile_selected_index = max(0, int(selected[0]) - 1)
        elif shown and not self.mods_tree.selection():
            self.list_selected_index = min(self.list_selected_index, len(shown) - 1)
            self.tile_selected_index = min(self.tile_selected_index, len(shown) - 1)
        if self.list_selected_index < self.list_render_offset or self.list_selected_index >= self.list_render_offset + self._list_visible_rows():
            self.list_render_offset = max(0, min(self.list_selected_index, max(0, len(shown) - self._list_visible_rows())))
        self.search_box.set_completion_values([m.name for m in items])
        label_values = sorted({v for v in labels.values() if v})
        self.label_filter_box.set_completion_values(label_values)
        self.label_edit_box.set_completion_values(label_values)
        self._refresh_mod_list()
        if self._is_tile_view():
            self._refresh_mod_tiles()
        self.status_var.set(f"Mods page {page}/{pages}. Items: {len(items)}")
        self._on_mod_selection_changed()

    def refresh_presets(self) -> None:
        if not ensure_paths(self.cfg):
            return
        presets, keys, page_keys, page, pages = presets_view(self.cfg, max(1, int(self.preset_page.get() or 1)), self._preset_order_mode())
        records = presets_records()
        installed_set = {m.name for m in list_installed_mods(self.cfg)}
        self.preset_page.set(page)
        self.presets_tree.delete(*self.presets_tree.get_children())
        for i, name in enumerate(page_keys, 1):
            mods = presets.get(name, [])
            rec = records.get(name, {})
            state = rec.get("state") or "undefined"
            last_managed = rec.get("last_managed") or "-"
            all_applied = bool(mods) and all(nm in installed_set for nm in mods)
            tags = ("applied",) if all_applied else ()
            self.presets_tree.insert("", "end", iid=str(i), text=name, values=(state, len(mods), last_managed), tags=tags)
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
        if tree is getattr(self, "mods_tree", None) and self._is_tile_view():
            return [self.tile_selected_index + 1] if self.current_mods_shown else []
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

        self._run_action("Installing page", partial(apply_mods_page, self.cfg, page, label, search, order), done, file_key="page")

    def _uninstall_page(self) -> None:
        page, label, search, order = self._view_args()

        def done(result) -> None:
            page, count = result
            self.status_var.set(f"Uninstalled {count} on page {page}.")
            self.refresh_mods()
            self.refresh_presets()

        self._run_action("Uninstalling page", partial(deactivate_mods_page, self.cfg, page, label, search, order), done, file_key="page")

    def _toggle_selected_mods(self) -> None:
        shown = list(self.current_mods_shown)
        indexes = self._selected_indexes(self.mods_tree)
        selected_names = [shown[i - 1].name for i in indexes if 1 <= i <= len(shown)]

        def done(msg) -> None:
            self.status_var.set(msg or "No mods selected.")
            self.refresh_mods(selected_names)
            self.refresh_presets()

        self._run_action("Toggling selected mods", partial(toggle_mods_by_indexes, shown, indexes), done, file_key="mods")

    def _add_label_selected(self) -> None:
        label = self.label_edit_var.get().strip()
        if not label:
            messagebox.showerror("Label", "Enter label.")
            return
        targets = [self.current_mods_shown[i - 1].name for i in self._selected_indexes(self.mods_tree) if 1 <= i <= len(self.current_mods_shown)]

        def done(msg) -> None:
            self.status_var.set(msg)
            self.refresh_mods()

        if not targets:
            self.status_var.set("No mods selected.")
            return
        self._run_action("Adding label", partial(add_label_to_mods, label, targets), done, file_key="labels")

    def _remove_label_selected(self) -> None:
        label = self.label_edit_var.get().strip()
        if not label:
            messagebox.showerror("Label", "Enter label.")
            return
        targets = [self.current_mods_shown[i - 1].name for i in self._selected_indexes(self.mods_tree) if 1 <= i <= len(self.current_mods_shown)]

        def done(msg) -> None:
            self.status_var.set(msg)
            self.refresh_mods()

        if not targets:
            self.status_var.set("No mods selected.")
            return
        self._run_action("Removing label", partial(remove_label_from_mods, label, targets), done, file_key="labels")

    def _save_preset(self) -> None:
        name = self.preset_name_box.get().strip()
        if not name:
            messagebox.showerror("Preset", "Enter preset name.")
            return

        def done(result) -> None:
            _ok, msg = result
            self.status_var.set(msg)
            self.refresh_presets()

        self._run_action("Saving preset", partial(save_preset_from_installed, self.cfg, name), done, file_key="presets")

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

        self._run_action("Toggling selected presets", partial(toggle_presets_by_indexes, self.cfg, page, indexes, installed), done, file_key="presets")

    def _delete_selected_presets(self) -> None:
        page = int(self.preset_page.get() or 1)
        indexes = self._selected_indexes(self.presets_tree)

        def done(result) -> None:
            count, missing = result
            self.status_var.set(f"Deleted: {count}. Missing: {', '.join(missing) if missing else 'none'}")
            self.refresh_presets()

        self._run_action("Deleting presets", partial(delete_presets_by_indexes, self.cfg, page, indexes), done, file_key="presets")

    def _browse_setting(self, key: str) -> None:
        path = filedialog.askdirectory()
        if path:
            self.setting_vars[key].set(path)

    def _save_settings(self) -> None:
        values = {key: var.get().strip() for key, var in self.setting_vars.items()}

        def done(new_cfg) -> None:
            self.cfg.clear()
            self.cfg.update(new_cfg)
            self.mod_view_mode.set(self.cfg.get("mod_view_mode", "list"))
            self._rebuild_tabs()
            w = max(880, int(self.cfg.get("window_width", 1200)))
            h = max(560, int(self.cfg.get("window_height", 750)))
            self.geometry(f"{w}x{h}")
            self.status_var.set("Settings saved.")
            self.refresh_all()

        self._run_action("Saving settings", partial(_run_save_settings, self.cfg, values), done, file_key="config")

    def _open_folder(self, target: str) -> None:
        key = "mods_source_dir" if target == "source" else "game_mods_dir"

        def done(result) -> None:
            ok, msg = result
            self.status_var.set(f"Open {target} folder: {'OK' if ok else 'ERR'} - {msg}")

        self._run_action(f"Opening {target} folder", partial(open_folder, self.cfg.get(key, "")), done, file_key="open")

    def _remove_selected_broken(self) -> None:
        targets = [self.current_broken[i - 1] for i in self._selected_indexes(self.broken_tree) if 1 <= i <= len(self.current_broken)]

        def done(count) -> None:
            self.status_var.set(f"Removed broken links: {count}")
            self.refresh_broken()

        self._run_action("Removing broken links", partial(_run_deactivate_batch, targets), done, file_key="broken")

    def _remove_all_broken(self) -> None:
        targets = list(self.current_broken)

        def done(count) -> None:
            self.status_var.set(f"Removed broken links: {count}")
            self.refresh_broken()

        self._run_action("Removing all broken links", partial(_run_deactivate_batch, targets), done, file_key="broken")

def run_gui() -> int:
    import multiprocessing as mp
    mp.freeze_support()
    app = ModManagerGui()
    app.mainloop()
    return 0
