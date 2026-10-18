from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, List

from PySide6 import QtCore, QtGui, QtWidgets

from app_paths import APP_NAME, APP_VERSION

from ..cli_utils import ensure_paths, open_folder, select_in_explorer
from ..dragdrop import clipboard_has_files, read_clipboard_image, read_clipboard_paths
from ..imports import ignored_file, regular_import_tasks
from ..models import ModItem
from ..mods import (
    add_favorites_to_mods,
    add_label_to_mods,
    apply_mods_page,
    deactivate_mod,
    deactivate_mods_page,
    existing_targets,
    import_mod_file,
    is_copy_install,
    import_mod_image,
    is_image_file,
    is_mod_file,
    list_broken_links,
    list_installed_mods,
    mod_image_path,
    mods_by_indexes,
    mods_records,
    overwrite_message,
    mods_view,
    remove_label_from_mods,
    remove_favorites_from_mods,
    toggle_mods_by_indexes,
)
from ..presets import (
    delete_presets_by_names,
    preset_mods_to_install,
    presets_records,
    presets_view,
    save_preset_from_installed,
    toggle_presets_by_names,
)
from ..storage import (
    active_game_profile,
    load_config,
    load_favorites,
    normalize_game_profiles,
    save_config,
)
from .. import settings_schema
from . import icons
from .context import AppContext
from .controllers import ACTIONS, SELECTION, WidgetRegistry
from .controllers.settings_controller import SAVED_MESSAGE as SETTINGS_SAVED
from .controllers.games_controller import GamesController
from .controllers.settings_controller import SettingsController
from .controllers.archive_import_controller import ArchiveImportController
from .dialogs import prompts
from .dialogs.base import close_dialog, show_dialog, themed_dialog
from .dialogs.game_profile import GameProfileDialog
from .dialogs.prompts import show_error
from .localization import system_action_text as _sys_str
from .pages.toolbar_specs import (
    BROKEN_TOOLBAR_SECTIONS,
    MODS_ACTION_SECTIONS,
    MODS_TOOLBAR_SECTIONS,
    PRESETS_TOOLBAR_SECTIONS,
    SELECTION_ACTIONS,
    SETTINGS_TOOLBAR_SECTIONS,
)
from .models import (
    BrokenTableModel,
    FavoriteDelegate,
    ModListView,
    ModTableModel,
    PresetTableModel,
    TileDelegate,
    configure_header,
)
from .theme import colors, tokens
from .task_runner import TaskRunner
from .theme.manager import ThemeManager
from .widgets import (
    DetailImageLabel,
    IconToolbar,
    PageControl,
    QtWindowsDropTarget,
    apply_margins,
    attach_completer,
    clear_layout,
    complete,
    configure_completer,
    configure_filter_box,
    detail_name_label,
    dropped_paths,
    expanding_size_policy,
    fixed_size_policy,
    icon_button,
    owns_event_source,
    path_button,
    refresh_page_title,
    select_box,
    text_button,
)
from .view_modes import (
    MOD_ORDER_OPTIONS,
    normalize_sort_key,
    normalize_view_mode,
    order_label_for_key,
    order_label_from_config,
    order_mode,
    sort_key_for_column,
)
from ..workers import _run_import_batch

OVERWRITE_TITLE = "Overwrite files"
OVERWRITE_QUESTION = "{message}\n\nReplace them?"


class _Var:
    def __init__(self, value=None, on_change: Callable | None = None):
        self._value = value
        self._on_change = on_change

    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = value
        if self._on_change:
            self._on_change()



THEME_KEYS = (
    "gui_theme",
    "gui_accent_color_mode",
    "gui_accent_color",
    "gui_text_color_mode",
    "gui_text_color",
    "gui_font_family",
    "gui_font_size",
)


_check_icon = icons.check_icon
_sort_direction_icon = icons.sort_direction_icon


class ModManagerGui(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.cfg = normalize_game_profiles(load_config())
        self._applying_theme = False
        self.runner = TaskRunner(self)
        self.runner.statusChanged.connect(self.statusBar().showMessage)
        self.runner.failed.connect(lambda message: show_error(self, "Error", message))
        self.runner.busyChanged.connect(self._on_busy_changed)
        self.archive_import = ArchiveImportController(self)
        self._init_theme()
        self.context = AppContext(self.cfg, self.theme, self.runner)
        self.registry = WidgetRegistry()
        self.resize(
            max(tokens.MIN_WIDTH, tokens.to_int(self.cfg.get("window_width"), tokens.DEFAULT_WIDTH)),
            max(tokens.MIN_HEIGHT, tokens.to_int(self.cfg.get("window_height"), tokens.DEFAULT_HEIGHT)),
        )
        self.setMinimumSize(tokens.MIN_WIDTH, tokens.MIN_HEIGHT)
        self.setAcceptDrops(True)

        self.mod_page = _Var(1)
        self.preset_page = _Var(1)
        self.search_var = _Var("")
        self.label_filter_var = _Var("")
        self.favorite_filter_var = _Var(False)
        self.label_edit_var = _Var("")
        self.order_var = _Var(self._mod_order_label_from_config())
        self.mod_view_mode = _Var(normalize_view_mode(self.cfg.get("mod_view_mode")))

        self.current_mod_items: list[ModItem] = []
        self.current_mods_shown: list[ModItem] = []
        self.current_mod_labels: dict[str, str] = {}
        self.current_mod_records: dict[str, dict] = {}
        self.current_mod_favorites: set[str] = set()
        self.current_broken: list[ModItem] = []
        self.mod_sort_key = MOD_ORDER_OPTIONS.get(self.order_var.get(), normalize_sort_key(self.cfg.get("mod_sort_key")))
        self.mod_sort_reverse = bool(self.cfg.get("mod_sort_reverse", False))
        self.preset_sort_key = self.cfg.get("preset_sort_key", "name")
        self.preset_sort_reverse = bool(self.cfg.get("preset_sort_reverse", False))

        self._build()
        self._setup_com_drop_targets()
        self._bind_navigation_events()
        self.refresh_all()

    def _setup_com_drop_targets(self) -> None:
        from ..platform_utils import is_windows
        if not is_windows():
            return

        def make_callback(viewport):
            def callback(paths, x, y):
                pos = viewport.mapFromGlobal(QtCore.QPoint(x, y))
                mod_name = self._mod_name_at_view_position(viewport, pos)
                self._handle_mods_drop(paths, target_mod_name=mod_name)
            return callback

        self._table_drop_target = QtWindowsDropTarget(
            self.mods_table.viewport(), make_callback(self.mods_table.viewport())
        )
        self._tiles_drop_target = QtWindowsDropTarget(
            self.tiles_view.viewport(), make_callback(self.tiles_view.viewport())
        )

    def closeEvent(self, event) -> None:
        self.cfg["window_width"] = self.width()
        self.cfg["window_height"] = self.height()
        self._save_tile_splitter_sizes()
        save_config(self.cfg)
        self.archive_import.shutdown()
        self.runner.shutdown()
        for attr in ("_table_drop_target", "_tiles_drop_target"):
            target = getattr(self, attr, None)
            if target is not None:
                target.disable()
        self._release_application_hooks()
        super().closeEvent(event)

    def _release_application_hooks(self) -> None:
        if not getattr(self, "_bound", False):
            return
        self._bound = False
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
            app.paletteChanged.disconnect(self._on_system_appearance_changed)
        style_hints = QtGui.QGuiApplication.styleHints()
        if hasattr(style_hints, "colorSchemeChanged"):
            style_hints.colorSchemeChanged.disconnect(self._on_system_appearance_changed)

    def _init_theme(self) -> None:
        if not hasattr(self, "theme"):
            self.theme = ThemeManager(self.cfg, self)
        self.theme.apply()
        self.setPalette(QtWidgets.QApplication.instance().palette())

    @property
    def _theme_mode(self) -> str:
        return self.theme.mode

    @property
    def _theme_palette_colors(self) -> colors.Palette:
        return self.theme.palette

    @property
    def _theme_is_dark(self) -> bool:
        return self.theme.palette.is_dark

    @property
    def _theme_accent(self) -> QtGui.QColor:
        return QtGui.QColor(self.theme.palette.accent)

    @property
    def _theme_button_text(self) -> QtGui.QColor:
        return QtGui.QColor(self.theme.palette.fg)

    def _refresh_theme(self) -> None:
        self._applying_theme = True
        try:
            self._init_theme()
            self._apply_button_style()
            palette = self.theme.palette
            self.mods_model.refresh_accent(palette.accent)
            self.presets_model.set_palette(palette)
            self.tile_delegate.set_palette(palette)
            self.favorite_delegate.set_favorites(self.current_mod_favorites)
            self.tiles_view.viewport().update()
            for button in self.action_widgets:
                if isinstance(button, QtWidgets.QAbstractButton):
                    icon_name = button.property("iconName")
                    if icon_name:
                        button.setIcon(self._icon(icon_name))
            for label in self.findChildren(QtWidgets.QLabel):
                if label.property("pageTitle"):
                    refresh_page_title(label)
            self._update_mod_order_direction_button()
            if hasattr(self, "_settings_form"):
                self._update_theme_preview()
                self.settings.update_font_preview()
            for dialog in self._dialogs():
                dialog.setPalette(self.palette())
                dialog.update()
            self._refresh_selected_detail()
            self.update()
        finally:
            self._applying_theme = False

    def _dialogs(self) -> list[QtWidgets.QDialog]:
        names = ("games_dialog", "presets_dialog", "settings_dialog", "broken_dialog")
        return [dialog for dialog in (getattr(self, name, None) for name in names) if dialog is not None]

    def _on_system_appearance_changed(self, *_args) -> None:
        if self._applying_theme or self.theme.is_applying:
            return
        self.theme.on_system_appearance_changed()
        self._refresh_theme()

    def _setup_filter_box(self, box: QtWidgets.QComboBox) -> None:
        configure_filter_box(box)

    def _setup_completer(self, completer: QtWidgets.QCompleter) -> None:
        configure_completer(completer)

    def _completion_line_edits(self) -> list[QtWidgets.QLineEdit]:
        edits = [box.lineEdit() for box in getattr(self, "filter_boxes", ())]
        label_edit = getattr(self, "label_edit", None)
        if label_edit is not None:
            edits.append(label_edit)
        return edits

    def _completion_line_edit_for_object(self, obj) -> QtWidgets.QLineEdit | None:
        for edit in self._completion_line_edits():
            if owns_event_source(edit, obj):
                return edit
        return None

    def _complete_line_edit(self, line_edit: QtWidgets.QLineEdit) -> bool:
        return complete(line_edit)

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) and event.matches(QtGui.QKeySequence.Paste):
            if isinstance(obj, QtWidgets.QWidget) and obj.window() in (self, self.archive_import.dialog) and clipboard_has_files():
                event.accept()
                if event.type() == QtCore.QEvent.KeyPress:
                    self._handle_paste()
                return True
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Tab:
            line_edit = self._completion_line_edit_for_object(obj)
            if line_edit is not None and self._complete_line_edit(line_edit):
                return True
        if self._is_mod_drop_target(obj):
            if event.type() in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove) and event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
            if event.type() == QtCore.QEvent.Drop:
                paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
                if paths:
                    self._handle_mods_drop(paths, target_mod_name=self._mod_name_at_view_position(obj, event.position().toPoint()))
                    event.acceptProposedAction()
                    return True
        if event.type() == QtCore.QEvent.MouseButtonPress:
            tiles_view = getattr(self, "tiles_view", None)
            if tiles_view is not None and obj is tiles_view.viewport() and event.button() == QtCore.Qt.LeftButton:
                label = self._tile_label_at_position(event.position().toPoint())
                if label:
                    self._toggle_label_filter(label)
                    event.accept()
                    return True
            if event.button() == QtCore.Qt.XButton1:
                return self._nav_back() == "break"
            if event.button() == QtCore.Qt.XButton2:
                return self._nav_forward() == "break"
        detail_scroll = getattr(self, "detail_scroll", None)
        if detail_scroll and obj is detail_scroll.viewport() and event.type() == QtCore.QEvent.Resize:
            self._update_detail_image_size()
        return super().eventFilter(obj, event)

    def _bind_navigation_events(self) -> None:
        app = QtWidgets.QApplication.instance()
        app.installEventFilter(self)
        app.paletteChanged.connect(self._on_system_appearance_changed)
        style_hints = QtGui.QGuiApplication.styleHints()
        if hasattr(style_hints, "colorSchemeChanged"):
            style_hints.colorSchemeChanged.connect(self._on_system_appearance_changed)
        self._bound = True
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Backspace), self, activated=self._nav_back)
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Back), self, activated=self._nav_back)
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Forward), self, activated=self._nav_forward)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl++"), self, activated=lambda: self._zoom_tiles(1))
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+="), self, activated=lambda: self._zoom_tiles(1))
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+-"), self, activated=lambda: self._zoom_tiles(-1))
        QtGui.QShortcut(QtGui.QKeySequence.Paste, self, activated=self._handle_paste)

    def _is_mods_tab_active(self) -> bool:
        return self.isActiveWindow()

    def _is_tile_view(self) -> bool:
        return self.mod_view_mode.get() == "tiles"

    def _nav_back(self, event=None):
        if self._is_mods_tab_active():
            self._change_mod_page(-1)
            return "break"
        return None

    def _nav_forward(self, event=None):
        if self._is_mods_tab_active():
            self._change_mod_page(1)
            return "break"
        return None

    def _build(self) -> None:
        self.games_page = QtWidgets.QWidget()
        self.mods_tab = QtWidgets.QWidget()
        self.setCentralWidget(self.mods_tab)
        self.statusBar().showMessage("")
        self._apply_button_style()
        self._build_games_page()
        self._build_mods()
        self._build_presets()
        self._build_settings()
        self._build_broken()
        self._show_start_page()

    def _apply_button_style(self) -> None:
        self._theme_stylesheet = self.theme.stylesheet
        self.setStyleSheet(self._theme_stylesheet)

    def _build_games_page(self) -> None:
        self.games = GamesController(self, self.games_page)
        self.games_list = self.games.page_list
        self.games_dialog = self.games.dialog
        self.games_dialog_list = self.games.dialog_list
        self.games_page_toolbar = self.games.page_toolbar
        self.games_dialog_toolbar = self.games.dialog_toolbar

    def _dialog(self, title: str, width: int | None = None, height: int | None = None) -> QtWidgets.QDialog:
        size = tokens.DIALOG_SIZE if width is None or height is None else (width, height)
        return themed_dialog(self, title, size)

    def _show_dialog(self, dialog: QtWidgets.QDialog) -> None:
        show_dialog(dialog)

    def _close_dialog(self, dialog: QtWidgets.QDialog | None) -> None:
        if dialog and dialog.isVisible():
            dialog.accept()

    def _open_presets_dialog(self) -> None:
        self.refresh_presets()
        self._show_dialog(self.presets_dialog)

    def _open_settings_dialog(self) -> None:
        self._show_dialog(self.settings_dialog)

    def _open_broken_dialog(self) -> None:
        self.refresh_broken()
        self._show_dialog(self.broken_dialog)

    def _open_games_dialog(self) -> None:
        self._refresh_games_lists()
        self._show_dialog(self.games_dialog)

    def _show_start_page(self) -> None:
        self._refresh_games_lists()
        if active_game_profile(self.cfg):
            self._set_main_page(self.mods_tab)
            self._update_game_button()
        else:
            self._set_main_page(self.games_page)

    def _set_main_page(self, widget: QtWidgets.QWidget) -> None:
        if self.centralWidget() is widget:
            return
        if self.centralWidget() is not None:
            self.takeCentralWidget()
        self.setCentralWidget(widget)

    def _update_game_button(self) -> None:
        self.games.update_game_button()

    def _refresh_games_lists(self) -> None:
        self.games.refresh_lists()

    def _select_game_profile(self, profile_id: str) -> None:
        self.games.select(profile_id)

    def _add_game_profile(self) -> None:
        self.games.add()

    def _edit_game_profile(self, profile_id: str) -> None:
        self.games.edit(profile_id)

    def _delete_game_profile(self, profile_id: str) -> None:
        self.games.delete(profile_id)

    def _game_profile_values(self, profile: dict | None = None) -> dict | None:
        return GameProfileDialog(self, profile).values()

    def _icon(self, name: str) -> QtGui.QIcon:
        return icons.standard_icon(name, self.style())

    def _icon_button(self, text: str, command: Callable, tooltip: str, icon: str, icon_only: bool = True):
        if icon_only:
            button = icon_button(icon, tooltip or text, command, self, accessible_name=text)
        else:
            button = text_button(text, tooltip or text, command, self, icon_name=icon)
        self.registry.add(ACTIONS, button)
        return button

    def _mod_selection_button(self, text: str, command: Callable, tooltip: str = "", icon: str = "toggle"):
        button = self._icon_button(text, command, tooltip or text, icon)
        button.setEnabled(False)
        self.registry.add(SELECTION, button)
        return button

    def _set_icon_button_checked(self, button: QtWidgets.QPushButton, checked: bool) -> None:
        button.setCheckable(True)
        button.setChecked(checked)

    def _mod_order_options(self) -> dict[str, str]:
        return dict(MOD_ORDER_OPTIONS)

    def _normalize_mod_sort_key(self, key: str) -> str:
        return normalize_sort_key(key)

    def _mod_order_label_for_key(self, key: str) -> str:
        return order_label_for_key(key)

    def _mod_order_label_from_config(self) -> str:
        return order_label_from_config(self.cfg)

    def _filter_box(self, placeholder: str) -> QtWidgets.QComboBox:
        box = select_box(editable=True)
        box.lineEdit().setPlaceholderText(placeholder)
        box.lineEdit().returnPressed.connect(self._mods_search)
        return configure_filter_box(box)

    def _build_mods_toolbar(self) -> IconToolbar:
        toolbar = IconToolbar(self.mods_tab)
        toolbar.build(MODS_TOOLBAR_SECTIONS)

        self.game_button = toolbar.sections["game"].add_text_action(
            "games", "Game", "menu", "Manage and switch game profiles"
        )
        self.game_button.setMinimumWidth(tokens.GAME_BUTTON_MIN_WIDTH)

        self.search_box = self._filter_box("Search")
        self.label_filter_box = self._filter_box("Label")
        self.filter_boxes = (self.search_box, self.label_filter_box)
        filter_section = toolbar.sections["filter"]
        filter_section.add_widget(self.search_box, 2)
        filter_section.add_widget(self.label_filter_box, 1)
        self.favorite_filter_button = toolbar.button("favorite_filter")
        self.favorite_filter_button.setCheckable(True)

        self.order_box = select_box()
        self.order_box.addItems(list(MOD_ORDER_OPTIONS))
        self.order_box.setCurrentText(order_label_for_key(self.mod_sort_key))
        self.order_box.activated.connect(self._activate_mod_order)
        order_section = toolbar.sections["order"]
        order_section.add_widget(self.order_box)
        self.order_direction_button = order_section.add_action(
            "order_direction", "toggle", "Sort ascending", self._toggle_mod_order_direction
        )

        self.view_list_button = toolbar.button("view_list")
        self.view_tiles_button = toolbar.button("view_tiles")
        for button in (self.view_list_button, self.view_tiles_button):
            button.setCheckable(True)
        self._set_icon_button_checked(self.view_list_button, not self._is_tile_view())
        self._set_icon_button_checked(self.view_tiles_button, self._is_tile_view())

        toolbar.connect({
            "games": self._open_games_dialog,
            "search": self._mods_search,
            "clear": self._mods_clear,
            "favorite_filter": self._toggle_favorite_filter,
            "view_list": lambda: self._set_view_mode("list"),
            "view_tiles": lambda: self._set_view_mode("tiles"),
            "presets": self._open_presets_dialog,
            "settings": self._open_settings_dialog,
            "broken": self._open_broken_dialog,
        })
        self.registry.extend(ACTIONS, toolbar.buttons.values())
        toolbar.add_stretch()
        self._update_mod_order_direction_button()
        return toolbar

    def _build_mods_actions(self) -> IconToolbar:
        toolbar = IconToolbar(self.mods_tab)
        toolbar.build(MODS_ACTION_SECTIONS)

        page_section = toolbar.sections["page"]
        page_section.add_action("prev_page", "back", "Previous mods page", lambda: self._change_mod_page(-1))
        self.page_control = page_section.add_widget(PageControl())
        self.page_control.pageRequested.connect(self._set_mod_page)
        self.page_label = self.page_control
        page_section.add_action("next_page", "forward", "Next mods page", lambda: self._change_mod_page(1))

        self.label_edit = QtWidgets.QLineEdit()
        self.label_edit.setPlaceholderText("Label")
        self.label_edit.setMaximumWidth(tokens.LABEL_EDIT_MAX_WIDTH)
        fixed_size_policy(self.label_edit)
        self.label_edit_model = QtCore.QStringListModel(self.label_edit)
        attach_completer(self.label_edit, self.label_edit_model)
        label_section = toolbar.sections["label"]
        label_section._actions_layout.insertWidget(0, self.label_edit)
        self.label_edit.setParent(label_section)

        toolbar.button("install_page").setAccessibleName(_sys_str("install"))
        toolbar.button("uninstall_page").setAccessibleName(_sys_str("uninstall"))

        toolbar.connect({
            "install_page": self._install_page,
            "uninstall_page": self._uninstall_page,
            "toggle_selected": self._toggle_selected_mods,
            "add_label": self._add_label_selected,
            "remove_label": self._remove_label_selected,
            "favorite_selected": self._toggle_favorite_selected,
            "import_files": self._import_mod_files,
            "import_folder": self._import_mod_folder,
            "set_image": self._set_mod_image,
        })
        self.registry.extend(ACTIONS, toolbar.buttons.values())
        for key in SELECTION_ACTIONS:
            button = toolbar.button(key)
            button.setEnabled(False)
            self.registry.add(SELECTION, button)
        toolbar.add_stretch()
        return toolbar

    def _apply_state_column_width(self) -> None:
        width = tokens.to_int(self.cfg.get("placeholder_image_col_width"), 0)
        if width > 0:
            self.mods_table.horizontalHeader().resizeSection(0, width)

    def _build_mods(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.mods_tab)
        self.mods_toolbar = self._build_mods_toolbar()
        layout.addWidget(self.mods_toolbar)

        self.mods_model = ModTableModel(self.theme.palette.accent, self)
        self.mods_stack = QtWidgets.QStackedWidget()
        self.mods_table = QtWidgets.QTableView()
        self.mods_table.setModel(self.mods_model)
        self.mods_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.mods_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.mods_table.setMouseTracking(True)
        self.mods_table.setAcceptDrops(True)
        self.mods_table.viewport().setAcceptDrops(True)
        self.mods_table.viewport().installEventFilter(self)
        configure_header(self.mods_table, ModTableModel.COLUMNS)
        self._apply_state_column_width()
        mods_header = self.mods_table.horizontalHeader()
        mods_header.setSectionsClickable(True)
        mods_header.sectionClicked.connect(self._sort_mods_by_section)
        self.mods_table.doubleClicked.connect(lambda _idx: self._toggle_selected_mods())
        self.mods_table.selectionModel().selectionChanged.connect(lambda _a, _b: self._on_mod_selection_changed())
        self.favorite_delegate = FavoriteDelegate(self.mods_table)
        self.favorite_delegate.favoriteToggled.connect(self._toggle_favorite_name)
        self.mods_table.setItemDelegateForColumn(1, self.favorite_delegate)

        self.tile_delegate = TileDelegate(self.cfg, self.theme.palette, self)
        self.tiles_view = ModListView()
        self.tiles_view.setModel(self.mods_model)
        self.tiles_view.setItemDelegate(self.tile_delegate)
        self.tiles_view.setViewMode(QtWidgets.QListView.IconMode)
        self.tiles_view.setResizeMode(QtWidgets.QListView.Adjust)
        self.tiles_view.setMovement(QtWidgets.QListView.Static)
        self.tiles_view.setUniformItemSizes(True)
        self.tiles_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tiles_view.setMouseTracking(True)
        self.tiles_view.setAcceptDrops(True)
        self.tiles_view.viewport().setAcceptDrops(True)
        self.tiles_view.viewport().installEventFilter(self)
        self.tiles_view.zoomRequested.connect(self._zoom_tiles)
        self.tiles_view.doubleClicked.connect(lambda _idx: self._toggle_selected_mods())
        self.tiles_view.selectionModel().selectionChanged.connect(lambda _a, _b: self._on_mod_selection_changed())
        self.tile_delegate.favoriteToggled.connect(self._toggle_favorite_name)

        self.detail_frame = QtWidgets.QWidget()
        self.detail_frame.setAutoFillBackground(True)
        self.detail_frame.setStyleSheet("background: palette(base);")
        self.detail_layout = QtWidgets.QVBoxLayout(self.detail_frame)
        self.detail_layout.setContentsMargins(12, 12, 12, 12)
        self.detail_layout.setSpacing(8)
        self.detail_layout.setAlignment(QtCore.Qt.AlignTop)
        self.detail_scroll = QtWidgets.QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.detail_scroll.setWidget(self.detail_frame)
        self.detail_scroll.viewport().installEventFilter(self)
        self.tile_splitter = QtWidgets.QSplitter()
        self.tile_splitter.addWidget(self.tiles_view)
        self.tile_splitter.addWidget(self.detail_scroll)
        self.tile_splitter.setStretchFactor(0, tokens.TILE_LIST_STRETCH)
        self.tile_splitter.setStretchFactor(1, tokens.TILE_DETAIL_STRETCH)
        self.tile_splitter.splitterMoved.connect(lambda _pos, _index: self._save_tile_splitter_sizes())
        QtCore.QTimer.singleShot(tokens.IMMEDIATE_MS, self._restore_tile_splitter_sizes)

        self.mods_stack.addWidget(self.mods_table)
        self.mods_stack.addWidget(self.tile_splitter)
        layout.addWidget(self.mods_stack, 1)

        self.mods_actions = self._build_mods_actions()
        layout.addWidget(self.mods_actions)
        self._show_mod_view()

    def _save_tile_splitter_sizes(self) -> None:
        if not hasattr(self, "tile_splitter"):
            return
        sizes = self.tile_splitter.sizes()
        if len(sizes) >= 2 and sizes[0] > 0 and sizes[1] > 0:
            self.cfg["_tile_list_width"] = int(sizes[0])
            self.cfg["_tile_detail_width"] = int(sizes[1])

    def _restore_tile_splitter_sizes(self) -> None:
        if not hasattr(self, "tile_splitter"):
            return
        list_w = int(self.cfg.get("_tile_list_width") or 0)
        detail_w = int(self.cfg.get("_tile_detail_width") or 0)
        if list_w > 0 and detail_w > 0:
            self.tile_splitter.setSizes([list_w, detail_w])

    def _build_presets(self) -> None:
        self.presets_dialog = self._dialog("Presets")
        layout = QtWidgets.QVBoxLayout(self.presets_dialog)
        self.presets_model = PresetTableModel(self.theme.palette, self)
        self.presets_table = QtWidgets.QTableView()
        self.presets_table.setModel(self.presets_model)
        self.presets_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.presets_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        configure_header(self.presets_table, PresetTableModel.COLUMNS)
        self.presets_table.doubleClicked.connect(self._toggle_preset_at_index)
        layout.addWidget(self.presets_table)

        self.presets_toolbar = IconToolbar(self.presets_dialog)
        self.presets_toolbar.build(PRESETS_TOOLBAR_SECTIONS)
        page_section = self.presets_toolbar.sections["page"]
        page_section.add_action("prev_page", "back", "Previous presets page", lambda: self._change_preset_page(-1))
        self.preset_page_control = page_section.add_widget(PageControl())
        self.preset_page_control.pageRequested.connect(self._set_preset_page)
        self.preset_page_label = self.preset_page_control
        page_section.add_action("next_page", "forward", "Next presets page", lambda: self._change_preset_page(1))

        self.preset_name = QtWidgets.QLineEdit()
        self.preset_name.setPlaceholderText("Preset name")
        preset_section = self.presets_toolbar.sections["preset"]
        preset_section._actions_layout.insertWidget(0, self.preset_name)
        self.preset_name.setParent(preset_section)

        self.presets_toolbar.connect({
            "save": self._save_preset,
            "toggle": self._toggle_selected_presets,
            "delete": self._delete_selected_presets,
        })
        self.registry.extend(ACTIONS, self.presets_toolbar.buttons.values())
        self.presets_toolbar.add_stretch()
        layout.addWidget(self.presets_toolbar)

    def _build_settings(self) -> None:
        self.settings = SettingsController(self)
        self.settings_dialog = self.settings.dialog
        self.settings_form = self.settings.form
        self._settings_form = self.settings.form
        self.setting_widgets = self.settings.fields
        self.settings_toolbar = self.settings.toolbar
        self.accent_preview_badge = self.settings.accent_badge
        self.accent_preview_button = self.settings.accent_button
        self.text_preview_badge = self.settings.text_badge

    def _build_broken(self) -> None:
        self.broken_dialog = self._dialog("Broken links")
        layout = QtWidgets.QVBoxLayout(self.broken_dialog)
        self.broken_model = BrokenTableModel(self)
        self.broken_table = QtWidgets.QTableView()
        self.broken_table.setModel(self.broken_model)
        self.broken_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.broken_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        configure_header(self.broken_table, BrokenTableModel.COLUMNS)
        self.broken_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.broken_table)
        self.broken_toolbar = IconToolbar(self.broken_dialog)
        self.broken_toolbar.build(BROKEN_TOOLBAR_SECTIONS)
        self.broken_toolbar.connect({
            "remove_selected": self._remove_selected_broken,
            "remove_all": self._remove_all_broken,
        })
        self.registry.extend(ACTIONS, self.broken_toolbar.buttons.values())
        self.broken_toolbar.add_stretch()
        layout.addWidget(self.broken_toolbar)

    @property
    def busy(self) -> bool:
        return self.runner.busy

    @property
    def action_widgets(self) -> list:
        return self.registry.widgets(ACTIONS)

    @property
    def mod_selection_widgets(self) -> list:
        return self.registry.widgets(SELECTION)

    def _set_status(self, text: str) -> None:
        self.runner.set_status(text)

    def _on_busy_changed(self, busy: bool) -> None:
        self.registry.set_enabled(ACTIONS, not busy)
        self._update_mod_selection_actions()

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.runner.set_busy(busy, text)

    def _run_action(self, label: str, worker: Callable, done: Callable | None = None, file_key: str = "global") -> None:
        self.runner.run(label, worker, done, file_key)

    def _poll_workers(self) -> None:
        self.runner.poll()

    def _view_args(self):
        return self.mod_page.get(), self.label_filter_var.get(), self.search_var.get(), self._mod_order_mode()

    def _mod_order_mode(self) -> str:
        return order_mode(self.mod_sort_key, self.mod_sort_reverse)

    def _preset_order_mode(self) -> str:
        key = self.preset_sort_key or "name"
        return f"-{key}" if self.preset_sort_reverse else key

    def _set_view_mode(self, mode: str) -> None:
        mode = normalize_view_mode(mode)
        self.mod_view_mode.set(mode)
        self.cfg["mod_view_mode"] = mode
        save_config(self.cfg)
        self._show_mod_view()

    def _set_mod_order(self, text: str) -> None:
        options = self._mod_order_options()
        text = text if text in options else "Default"
        self.order_var.set(text)
        key = options[text]
        if self.mod_sort_key == key:
            self.mod_sort_reverse = not self.mod_sort_reverse
        else:
            self.mod_sort_key = key
            self.mod_sort_reverse = False
        self.cfg["order_var"] = text
        self.cfg["mod_sort_key"] = self.mod_sort_key
        self.cfg["mod_sort_reverse"] = self.mod_sort_reverse
        self.mod_page.set(1)
        save_config(self.cfg)
        self._update_mod_order_direction_button()
        self.refresh_mods()

    def _activate_mod_order(self, _index: int) -> None:
        self._set_mod_order(self.order_box.currentText())

    def _show_mod_view(self) -> None:
        is_tiles = self._is_tile_view()
        self.mods_stack.setCurrentWidget(self.tile_splitter if is_tiles else self.mods_table)
        self.view_list_button.setChecked(not is_tiles)
        self.view_tiles_button.setChecked(is_tiles)
        self._refresh_selected_detail()

    def _sort_mods(self, key: str) -> None:
        key = self._normalize_mod_sort_key(key)
        if self.mod_sort_key == key:
            self.mod_sort_reverse = not self.mod_sort_reverse
        else:
            self.mod_sort_key = key
            self.mod_sort_reverse = False
        self.order_var.set(self._mod_order_label_for_key(self.mod_sort_key))
        if hasattr(self, "order_box"):
            blocker = QtCore.QSignalBlocker(self.order_box)
            try:
                self.order_box.setCurrentText(self.order_var.get())
            finally:
                del blocker
        self.cfg["mod_sort_key"] = self.mod_sort_key
        self.cfg["mod_sort_reverse"] = self.mod_sort_reverse
        self.cfg["order_var"] = self.order_var.get()
        self.mod_page.set(1)
        save_config(self.cfg)
        self._update_mod_order_direction_button()
        self.refresh_mods()

    def _sort_mods_by_section(self, section: int) -> None:
        key = sort_key_for_column(section)
        if key:
            self._sort_mods(key)

    def _toggle_mod_order_direction(self) -> None:
        self.mod_sort_reverse = not self.mod_sort_reverse
        self.cfg["mod_sort_key"] = self.mod_sort_key
        self.cfg["mod_sort_reverse"] = self.mod_sort_reverse
        self.cfg["order_var"] = self._mod_order_label_for_key(self.mod_sort_key)
        save_config(self.cfg)
        self._update_mod_order_direction_button()
        self.mod_page.set(1)
        self.refresh_mods()

    def _update_mod_order_direction_button(self) -> None:
        button = getattr(self, "order_direction_button", None)
        if button is None:
            return
        button.setIcon(_sort_direction_icon(self.mod_sort_reverse, self._theme_button_text))
        button.setAccessibleName("Descending" if self.mod_sort_reverse else "Ascending")
        button.setToolTip("Sort descending" if self.mod_sort_reverse else "Sort ascending")

    def _zoom_tiles(self, direction: int):
        if not self._is_tile_view():
            return None
        current = tokens.clamp_tile_size(self.cfg.get("tile_size"))
        step = tokens.TILE_SIZE_STEP if direction > 0 else -tokens.TILE_SIZE_STEP
        self.cfg["tile_size"] = tokens.clamp_tile_size(current + step)
        self.tile_delegate.clear_cache()
        self.tiles_view.reset()
        save_config(self.cfg)
        return "break"

    def _selected_rows(self, view) -> list[int]:
        if not view or not view.selectionModel():
            return []
        selection = view.selectionModel()
        rows = {idx.row() for idx in selection.selectedRows()}
        rows.update(idx.row() for idx in selection.selectedIndexes())
        return sorted(rows)

    def _selected_indexes(self, view=None) -> List[int]:
        if view is None:
            view = self.tiles_view if self._is_tile_view() else self.mods_table
        return [row + 1 for row in self._selected_rows(view)]

    def _has_mod_selection(self) -> bool:
        return bool(self._selected_rows(self.tiles_view if self._is_tile_view() else self.mods_table))

    def _update_mod_selection_actions(self) -> None:
        enabled = (not self.busy) and self._has_mod_selection()
        for widget in self.mod_selection_widgets:
            widget.setEnabled(enabled)

    def _on_mod_selection_changed(self) -> None:
        self._update_mod_selection_actions()
        self._refresh_selected_detail()

    def _select_mod_names(self, selected_names: list[str] | None = None) -> None:
        names = set(selected_names or [])
        view = self.tiles_view if self._is_tile_view() else self.mods_table
        selection = view.selectionModel()
        if not selection:
            return
        selection.clearSelection()
        rows = [i for i, mod in enumerate(self.current_mods_shown) if mod.name in names]
        if not rows and self.current_mods_shown:
            rows = [0]
        for row in rows:
            idx = self.mods_model.index(row, 0)
            selection.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
            view.setCurrentIndex(idx)
        self._update_mod_selection_actions()

    def _current_mod_view(self):
        return self.tiles_view if self._is_tile_view() else self.mods_table

    def _is_mod_drop_target(self, obj) -> bool:
        if not hasattr(self, "mods_table") or not hasattr(self, "tiles_view"):
            return False
        return obj in (self.mods_table.viewport(), self.tiles_view.viewport())

    def _mod_name_at_view_position(self, obj, pos: QtCore.QPoint) -> str:
        if not hasattr(self, "mods_model"):
            return ""
        view = self.tiles_view if obj is self.tiles_view.viewport() else self.mods_table
        index = view.indexAt(pos)
        if not index.isValid() or index.row() >= len(self.current_mods_shown):
            return ""
        return self.current_mods_shown[index.row()].name

    def _tile_label_at_position(self, pos: QtCore.QPoint) -> str:
        if not hasattr(self, "tiles_view"):
            return ""
        index = self.tiles_view.indexAt(pos)
        if not index.isValid():
            return ""
        option = QtWidgets.QStyleOptionViewItem()
        option.font = self.tiles_view.font()
        option.rect = self.tiles_view.visualRect(index)
        return self.tile_delegate._label_for_pos(option, index, pos)

    def _refresh_selected_detail(self) -> None:
        rows = self._selected_rows(self._current_mod_view())
        if len(rows) == 1 and rows[0] < len(self.current_mods_shown):
            self._refresh_mod_detail(self.current_mods_shown[rows[0]])
        elif len(rows) > 1:
            self._refresh_multi_detail([self.current_mods_shown[i] for i in rows if i < len(self.current_mods_shown)])
        else:
            self._refresh_mod_detail(None)

    def _clear_detail(self) -> None:
        self._clear_layout(self.detail_layout)

    def _clear_layout(self, layout) -> None:
        clear_layout(layout)

    def _detail_row(self, label: str, value: str) -> None:
        row = apply_margins(QtWidgets.QHBoxLayout(), margins=None)
        value_label = QtWidgets.QLabel(value)
        value_label.setWordWrap(True)
        row.addWidget(detail_name_label(label))
        row.addWidget(value_label, 1)
        self.detail_layout.addLayout(row)

    def _format_mod_created_date(self, mod: ModItem) -> str:
        record = self.current_mod_records.get(mod.name, {})
        for key in ("created_date", "created_at", "created"):
            value = record.get(key)
            if value:
                return str(value)
        try:
            return datetime.fromtimestamp(mod.src.stat().st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "-"

    def _dates_fit_on_one_row(self, last_managed: str, created: str, available_width: int | None = None) -> bool:
        if available_width is None:
            margins = self.detail_layout.contentsMargins()
            viewport_width = self.detail_scroll.viewport().width()
            if viewport_width <= 1:
                viewport_width = self.detail_scroll.width()
            available_width = max(1, viewport_width - margins.left() - margins.right())
        metrics = self.detail_frame.fontMetrics()
        needed = (
            tokens.DETAIL_LABEL_MIN_WIDTH * 2
            + metrics.horizontalAdvance(last_managed)
            + metrics.horizontalAdvance(created)
            + tokens.DETAIL_DATES_SPACING
        )
        return available_width >= needed

    def _detail_dates_row(self, mod: ModItem) -> None:
        last_managed = self.current_mod_records.get(mod.name, {}).get("last_managed") or "-"
        created = self._format_mod_created_date(mod)
        if not self._dates_fit_on_one_row(last_managed, created):
            self._detail_row("Last managed", last_managed)
            self._detail_row("Created", created)
            return

        row = apply_margins(QtWidgets.QHBoxLayout(), margins=None)
        for label, value in (("Last managed", last_managed), ("Created", created)):
            value_label = QtWidgets.QLabel(value)
            fixed_size_policy(value_label)
            row.addWidget(detail_name_label(label))
            row.addWidget(value_label)
        row.addStretch(1)
        self.detail_layout.addLayout(row)

    def _detail_path_row(self, label: str, path: Path) -> None:
        row = apply_margins(QtWidgets.QHBoxLayout(), margins=None)
        row.addWidget(detail_name_label(label))
        row.addWidget(path_button(path, lambda target: select_in_explorer(target)), 1)
        self.detail_layout.addLayout(row)

    def _detail_row_with_button(self, label: str, button: QtWidgets.QPushButton) -> None:
        row = apply_margins(QtWidgets.QHBoxLayout(), margins=None)
        row.addWidget(QtWidgets.QLabel(label))
        row.addWidget(button)
        row.addStretch(1)
        self.detail_layout.addLayout(row)

    def _detail_label_row(self, value: str) -> None:
        button = text_button(
            value or "-",
            "Filter mods by this label",
            lambda: self._toggle_label_filter(value),
            icon_name="toggle",
        )
        button.setEnabled(bool(value and value != "-"))
        self._detail_row_with_button("Label", button)

    def _detail_favorite_row(self, mod: ModItem) -> None:
        favorite = mod.name in self.current_mod_favorites
        text = "Remove from favorites" if favorite else "Add to favorites"
        button = text_button(
            text,
            text,
            lambda name=mod.name: self._toggle_favorite_name(name),
            icon_name="favorite_filled" if favorite else "favorite",
        )
        self._detail_row_with_button("Favorite", button)

    def _detail_state_action_row(self, mod: ModItem) -> None:
        action = "uninstall" if mod.installed else "install"
        index = self.current_mods_shown.index(mod) + 1 if mod in self.current_mods_shown else 1
        button = text_button(
            _sys_str(action),
            f"{action.capitalize()} this mod",
            lambda i=index: self._toggle_selected_indexes([i]),
            icon_name=action,
        )
        self._detail_row_with_button("Action", button)

    def _toggle_label_filter(self, label: str) -> None:
        if not label or label == "-":
            return
        current = self.label_filter_var.get()
        self.label_filter_var.set("" if current.lower() == label.lower() else label)
        self.label_filter_box.setCurrentText(self.label_filter_var.get())
        self.mod_page.set(1)
        self.refresh_mods()

    def _confirm_overwrite(self, mods: list) -> bool:
        """Ask before a copy install replaces files that are already in the game mods folder."""
        names = existing_targets(mods)
        if not names:
            return True
        question = OVERWRITE_QUESTION.format(message=overwrite_message(names))
        return prompts.ask_yes_no(self, OVERWRITE_TITLE, question)

    def _selected_mod_rows_for_state(self, installed: bool) -> list[int]:
        rows = self._selected_rows(self._current_mod_view())
        return [row + 1 for row in rows if row < len(self.current_mods_shown) and self.current_mods_shown[row].installed == installed]

    def _toggle_selected_indexes(self, indexes: list[int]) -> None:
        if not indexes:
            return
        selected = mods_by_indexes(self.current_mods_shown, indexes)
        if not self._confirm_overwrite([m for m in selected if not m.installed]):
            return
        names = [m.name for m in selected]

        def done(message):
            self._set_status(message)
            self.refresh_mods(names)
            self.refresh_presets()

        self._run_action(
            "Updating selected mods...",
            lambda: toggle_mods_by_indexes(self.current_mods_shown, indexes, True),
            done,
        )

    def _install_selected_mods(self) -> None:
        self._toggle_selected_indexes(self._selected_mod_rows_for_state(False))

    def _uninstall_selected_mods(self) -> None:
        self._toggle_selected_indexes(self._selected_mod_rows_for_state(True))

    def _refresh_multi_detail(self, mods: list) -> None:
        self._clear_detail()
        installed = sum(1 for mod in mods if mod.installed)
        not_installed = len(mods) - installed
        title = QtWidgets.QLabel(f"{len(mods)} mods selected")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        self.detail_layout.addWidget(title)
        self._detail_row("Installed", str(installed))
        self._detail_row("Not installed", str(not_installed))
        actions = QtWidgets.QHBoxLayout()
        install_button = QtWidgets.QPushButton(f"Install {not_installed}")
        install_button.setIcon(self._icon("install"))
        install_button.setToolTip("Install selected mods that are not installed")
        install_button.setEnabled(not_installed > 0)
        install_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        install_button.clicked.connect(self._install_selected_mods)
        uninstall_button = QtWidgets.QPushButton(f"Uninstall {installed}")
        uninstall_button.setIcon(self._icon("uninstall"))
        uninstall_button.setToolTip("Uninstall selected mods that are installed")
        uninstall_button.setEnabled(installed > 0)
        uninstall_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        uninstall_button.clicked.connect(self._uninstall_selected_mods)
        toggle_button = QtWidgets.QPushButton("Toggle selected")
        toggle_button.setIcon(self._icon("toggle"))
        toggle_button.setToolTip("Toggle all selected mods")
        toggle_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        toggle_button.clicked.connect(self._toggle_selected_mods)
        actions.addWidget(install_button)
        actions.addWidget(uninstall_button)
        actions.addWidget(toggle_button)
        actions.addStretch(1)
        self.detail_layout.addLayout(actions)

    def _detail_image(self, mod_name: str) -> None:
        img_path = mod_image_path(self.cfg, mod_name)
        if not img_path:
            return
        pixmap = QtGui.QPixmap(str(img_path))
        if pixmap.isNull():
            return
        image = DetailImageLabel(pixmap)
        image.update_scaled_pixmap(self._detail_image_target_size())
        self.detail_layout.addWidget(image)
        QtCore.QTimer.singleShot(0, self._update_detail_image_size)

    def _detail_image_target_size(self, image: DetailImageLabel | None = None) -> QtCore.QSize:
        if not hasattr(self, "detail_frame"):
            return QtCore.QSize(1, 1)
        margins = self.detail_layout.contentsMargins()
        viewport_width = self.detail_scroll.viewport().width()
        if viewport_width <= 1:
            viewport_width = self.detail_scroll.width()
        viewport_height = self.detail_scroll.viewport().height()
        if viewport_height <= 1:
            viewport_height = self.detail_scroll.height()
        max_width = max(1, viewport_width - margins.left() - margins.right() - 2)
        image_top = image.y() if image is not None and image.y() > 0 else margins.top()
        max_height = max(1, viewport_height - image_top - margins.bottom() - 2)
        return QtCore.QSize(max_width, max_height)

    def _update_detail_image_size(self) -> None:
        if not hasattr(self, "detail_frame"):
            return
        for image in self.detail_frame.findChildren(DetailImageLabel):
            image.update_scaled_pixmap(self._detail_image_target_size(image))

    def _refresh_mod_detail(self, mod: ModItem | None) -> None:
        self._clear_detail()
        if mod is None:
            self.detail_layout.addWidget(QtWidgets.QLabel("No mod selected"))
            return
        self._detail_row("Name", mod.name)
        self._detail_label_row(self.current_mod_labels.get(mod.name, "-"))
        self._detail_favorite_row(mod)
        self._detail_state_action_row(mod)
        self._detail_dates_row(mod)
        if mod.files:
            self._detail_row("Grouped files", ", ".join(f.src.name for f in mod.files))
        self._detail_path_row("Source", mod.src)
        self._detail_path_row("Destination", mod.dest)
        self._detail_image(mod.name)
        self.detail_layout.addStretch(1)

    def _invalidate_mod_image(self, mod_name: str) -> None:
        self.tile_delegate.clear_cache(mod_name)
        for row, mod in enumerate(self.current_mods_shown):
            if mod.name == mod_name:
                index = self.mods_model.index(row, 0)
                self.mods_model.dataChanged.emit(index, index, [QtCore.Qt.DecorationRole, QtCore.Qt.DisplayRole])
                self.tiles_view.viewport().update(self.tiles_view.visualRect(index))
                break

    def refresh_all(self) -> None:
        self.refresh_mods()
        self.refresh_presets()
        self.refresh_broken()

    def refresh_mods(self, selected_names: List[str] | None = None) -> None:
        page, label_filter, search, order = self._view_args()
        favorite_only = bool(self.favorite_filter_var.get())
        view_args = (self.cfg, page, label_filter, search, order)
        items, shown, page, pages, labels = (
            mods_view(*view_args, True) if favorite_only else mods_view(*view_args)
        )
        self.current_mod_items = items
        self.current_mods_shown = shown
        self.current_mod_labels = labels
        self.current_mod_records = mods_records()
        self.current_mod_favorites = load_favorites(self.cfg)
        self.mod_page.set(page)
        list_blocker = QtCore.QSignalBlocker(self.mods_table.selectionModel())
        tile_blocker = QtCore.QSignalBlocker(self.tiles_view.selectionModel())
        try:
            self.mods_model.set_data(shown, labels, self.current_mod_records, self.current_mod_favorites)
            self.favorite_delegate.set_favorites(self.current_mod_favorites)
            self.tile_delegate.set_favorites(self.current_mod_favorites)
            self.page_control.set_page(page, pages)
            self.search_box.clear()
            self.search_box.addItems([m.name for m in items])
            self.search_box.setCurrentText(search)
            label_values = sorted({v for v in labels.values() if v})
            self.label_filter_box.clear()
            self.label_filter_box.addItems(label_values)
            self.label_filter_box.setCurrentText(label_filter)
            self.label_edit_model.setStringList(label_values)
            self.favorite_filter_button.setChecked(favorite_only)
            self._select_mod_names(selected_names)
        finally:
            del tile_blocker
            del list_blocker
        self._refresh_selected_detail()

    def refresh_presets(self) -> None:
        selected_names = [
            self.presets_model.keys[row]
            for row in self._selected_rows(self.presets_table)
            if row < len(self.presets_model.keys)
        ]
        presets, keys, page_keys, page, pages = presets_view(self.cfg, self.preset_page.get(), self._preset_order_mode())
        installed = {mod.name for mod in list_installed_mods(self.cfg)}
        self.preset_page.set(page)
        selection = self.presets_table.selectionModel()
        blocker = QtCore.QSignalBlocker(selection) if selection else None
        self.presets_table.setUpdatesEnabled(False)
        try:
            self.presets_model.set_data(presets, page_keys, presets_records(), installed)
            self.preset_page_control.set_page(page, pages)
            if selection:
                selection.clearSelection()
                for name in selected_names:
                    if name in page_keys:
                        row = page_keys.index(name)
                        idx = self.presets_model.index(row, 0)
                        selection.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
                        self.presets_table.setCurrentIndex(idx)
        finally:
            self.presets_table.setUpdatesEnabled(True)
            if blocker is not None:
                del blocker

    def refresh_broken(self) -> None:
        self.current_broken = list_broken_links(self.cfg)
        self.broken_model.set_data(self.current_broken)

    def _mods_search(self) -> None:
        self.search_var.set(self.search_box.currentText().strip())
        self.label_filter_var.set(self.label_filter_box.currentText().strip())
        self.mod_page.set(1)
        self.refresh_mods()

    def _toggle_favorite_filter(self) -> None:
        self.favorite_filter_var.set(self.favorite_filter_button.isChecked())
        self.mod_page.set(1)
        self.refresh_mods()

    def _set_favorite_names(self, names: list[str], favorite: bool) -> None:
        if not names:
            return
        message = (
            add_favorites_to_mods(self.cfg, names)
            if favorite
            else remove_favorites_from_mods(self.cfg, names)
        )
        self._set_status(message)
        self.refresh_mods(names)

    def _toggle_favorite_name(self, name: str) -> None:
        self._set_favorite_names([name], name not in self.current_mod_favorites)

    def _toggle_favorite_selected(self) -> None:
        names = self._selected_mod_names()
        favorite = not all(name in self.current_mod_favorites for name in names)
        self._set_favorite_names(names, favorite)

    def _mods_clear(self) -> None:
        self.search_var.set("")
        self.label_filter_var.set("")
        self.search_box.setCurrentText("")
        self.label_filter_box.setCurrentText("")
        self.favorite_filter_var.set(False)
        self.favorite_filter_button.setChecked(False)
        self.mod_page.set(1)
        self.refresh_mods()

    def _change_mod_page(self, delta: int) -> None:
        self.mod_page.set(max(1, int(self.mod_page.get()) + delta))
        self.refresh_mods()

    def _set_mod_page(self, page: int) -> None:
        self.mod_page.set(page)
        self.refresh_mods()

    def _change_preset_page(self, delta: int) -> None:
        self.preset_page.set(max(1, int(self.preset_page.get()) + delta))
        self.refresh_presets()

    def _set_preset_page(self, page: int) -> None:
        self.preset_page.set(page)
        self.refresh_presets()

    def _install_page(self) -> None:
        page, label_filter, search, order = self._view_args()
        if not self._confirm_overwrite([m for m in self.current_mods_shown if not m.installed]):
            return

        def done(result):
            target_page, total, errors = result
            self._set_status(f"Installed {total - errors}/{total} on page {target_page}. Errors: {errors}.")
            self.refresh_mods()
            self.refresh_presets()

        favorite_only = bool(self.favorite_filter_var.get())
        view_args = (self.cfg, page, label_filter, search, order, favorite_only, True)
        self._run_action("Installing mods...", lambda: apply_mods_page(*view_args), done)

    def _uninstall_page(self) -> None:
        page, label_filter, search, order = self._view_args()

        def done(result):
            target_page, count = result
            self._set_status(f"Uninstalled {count} on page {target_page}.")
            self.refresh_mods()
            self.refresh_presets()

        view_args = (self.cfg, page, label_filter, search, order)
        self._run_action(
            "Uninstalling mods...",
            lambda: deactivate_mods_page(*view_args, True)
            if self.favorite_filter_var.get()
            else deactivate_mods_page(*view_args),
            done,
        )

    def _toggle_selected_mods(self) -> None:
        self._toggle_selected_indexes(self._selected_indexes())

    def _selected_mod_names(self) -> list[str]:
        return [self.current_mods_shown[i - 1].name for i in self._selected_indexes() if 1 <= i <= len(self.current_mods_shown)]

    def _add_label_selected(self) -> None:
        label = self.label_edit.text().strip()
        self.label_edit_var.set(label)
        if not label:
            prompts.show_error(self, "Label", "Enter label.")
            return
        targets = self._selected_mod_names()

        def done(message):
            self._set_status(message)
            self.refresh_mods(targets)

        self._run_action("Adding label...", lambda: add_label_to_mods(label, targets), done)

    def _remove_label_selected(self) -> None:
        label = self.label_edit.text().strip()
        self.label_edit_var.set(label)
        targets = self._selected_mod_names()

        def done(message):
            self._set_status(message)
            self.refresh_mods(targets)

        self._run_action("Removing label...", lambda: remove_label_from_mods(label, targets), done)

    def _save_preset(self) -> None:
        name = self.preset_name.text().strip()
        if not name:
            prompts.show_error(self, "Preset", "Enter preset name.")
            return

        def done(result):
            ok, message = result
            self._set_status(message)
            if ok:
                self.refresh_presets()

        self._run_action("Saving preset...", lambda: save_preset_from_installed(self.cfg, name), done)

    def _toggle_selected_presets(self) -> None:
        names = self._selected_preset_names()
        installed = {m.name for m in list_installed_mods(self.cfg)}
        if is_copy_install(self.cfg) and not self._confirm_overwrite(preset_mods_to_install(self.cfg, names)[0]):
            return

        def done(result):
            message, _messages, _has_errors = result
            self._set_status(message)
            self.refresh_mods()
            self.refresh_presets()
            self._close_dialog(self.presets_dialog)

        self._run_action(
            "Toggling presets...",
            lambda: toggle_presets_by_names(self.cfg, names, installed, True),
            done,
        )

    def _toggle_preset_at_index(self, index) -> None:
        if index.isValid() and self.presets_table.selectionModel():
            selection = self.presets_table.selectionModel()
            selection.clearSelection()
            selection.select(index, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
            self.presets_table.setCurrentIndex(index)
        self._toggle_selected_presets()

    def _delete_selected_presets(self) -> None:
        names = self._selected_preset_names()

        def done(result):
            removed, missing = result
            message = f"Deleted: {removed}. Missing: {', '.join(missing) if missing else 'none'}"
            self._set_status(message)
            self.refresh_presets()

        self._run_action("Deleting presets...", lambda: delete_presets_by_names(names), done)

    def _selected_preset_names(self) -> list[str]:
        return [
            self.presets_model.keys[row]
            for row in self._selected_rows(self.presets_table)
            if row < len(self.presets_model.keys)
        ]

    def _choose_color(self, key: str) -> None:
        self.settings.choose_color(key)

    def _settings_accent_color(self) -> QtGui.QColor:
        return self.settings.color("gui_accent_color")

    def _settings_text_color(self) -> QtGui.QColor:
        return self.settings.color("gui_text_color")

    def _update_theme_preview(self) -> None:
        self.settings.update_preview()

    def _save_settings(self) -> None:
        self.settings.save()

    def apply_saved_settings(self, new_cfg: dict, theme_changed: bool) -> None:
        self.cfg = self.context.replace_config(new_cfg)
        self.tile_delegate.cfg = new_cfg
        self._apply_state_column_width()
        self.mod_view_mode.set(normalize_view_mode(self.cfg.get("mod_view_mode")))
        self._show_mod_view()
        if theme_changed:
            self._refresh_theme()
        self._set_status(SETTINGS_SAVED)
        self.refresh_all()
        self._close_dialog(self.settings_dialog)

    def _remove_selected_broken(self) -> None:
        rows = self._selected_rows(self.broken_table)
        selected = [self.current_broken[i] for i in rows if i < len(self.current_broken)]

        def done(count):
            self._set_status(f"Removed broken links: {count}")
            self.refresh_broken()
            self._close_dialog(self.broken_dialog)

        self._run_action("Removing broken links...", lambda: sum(1 for mod in selected if deactivate_mod(mod)[0]), done)

    def _remove_all_broken(self) -> None:
        mods = list(self.current_broken)

        def done(count):
            self._set_status(f"Removed broken links: {count}")
            self.refresh_broken()
            self._close_dialog(self.broken_dialog)

        self._run_action("Removing broken links...", lambda: sum(1 for mod in mods if deactivate_mod(mod)[0]), done)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self._handle_mods_drop(paths)

    def _handle_mods_drop(self, paths, x: int = 0, y: int = 0, target_mod_name: str = "") -> None:
        if getattr(paths, "temporary_root", None) is None:
            paths = [Path(path) for path in paths]
        self._import_paths(paths, image_target_name=target_mod_name)

    def _handle_paste(self, event=None) -> None:
        if self.archive_import.dialog is not None:
            self.archive_import.paste()
            return
        paths = read_clipboard_paths()
        if paths:
            self._handle_clipboard_paths(paths)
            return
        image = read_clipboard_image()
        if image:
            mod_name = self._single_selected_mod_name() or self._choose_mod_for_image()
            if mod_name:
                def done(_result):
                    self._invalidate_mod_image(mod_name)
                    self.refresh_mods([mod_name])

                self._run_action("Importing image...", lambda: import_mod_image(self.cfg, mod_name, image), done)

    def _handle_clipboard_paths(self, paths: List[Path]) -> None:
        self._import_paths(paths, image_target_name=self._single_selected_mod_name())

    def _single_selected_mod_name(self) -> str:
        names = self._selected_mod_names()
        return names[0] if len(names) == 1 else ""

    def _import_paths(self, paths: List[Path], image_target_name: str = "") -> None:
        if self.archive_import.handle_paths(paths, image_target_name):
            return
        self._import_regular_paths(paths, image_target_name)

    def _import_regular_paths(self, paths: List[Path], image_target_name: str = "") -> None:
        if not ensure_paths(self.cfg):
            return
        existing = {m.name for m in self.current_mod_items}
        mod_paths = [path for path in paths if is_mod_file(path, self.cfg) and not ignored_file(path, self.cfg)]
        tasks = regular_import_tasks(self.cfg, mod_paths, existing, lambda name: prompts.choose_import_conflict(self, name))
        image_mods = []
        dropped_mods = {path.name for path in mod_paths}
        imported_names = {}
        for kind, source, name, _replace in tasks:
            if kind == "group":
                for member, _relative in source.files:
                    imported_names[member.name] = source.name
            else:
                imported_names[source.name] = name or source.name
        for path in paths:
            if is_image_file(path):
                if path.stem in dropped_mods:
                    mod_name = imported_names.get(path.stem, "")
                else:
                    mod_name = image_target_name or self._choose_mod_for_image(path.stem)
                if mod_name:
                    tasks.append(("image", path, mod_name, False))
                    image_mods.append(mod_name)
        if not tasks:
            release = getattr(paths, "close", None)
            if release:
                release()
            return

        def done(result):
            imported, skipped = result
            message = f"Imported: {len(imported)}. Skipped: {len(skipped)}."
            self._set_status(message)
            for mod_name in image_mods:
                self._invalidate_mod_image(mod_name)
            if image_mods:
                self.refresh_mods(image_mods)
            else:
                self.refresh_mods()

        cfg = dict(self.cfg)

        def worker():
            try:
                return _run_import_batch(cfg, tasks)
            finally:
                release = getattr(paths, "close", None)
                if release:
                    release()

        self._run_action("Importing...", worker, done)

    def _import_mod_files(self) -> None:
        files = prompts.choose_files(self, "Import mod files")
        self._import_paths([Path(p) for p in files])

    def _import_mod_folder(self) -> None:
        folder = prompts.choose_directory(self, "Import mod folder")
        if folder:
            self._import_paths([Path(folder)])

    def _choose_mod_for_image(self, default_name: str = "") -> str:
        names = [m.name for m in self.current_mod_items]
        if not names:
            return ""
        current = names.index(default_name) if default_name in names else 0
        name, ok = QtWidgets.QInputDialog.getItem(self, "Mod image", "Mod", names, current, False)
        return name if ok else ""

    def _set_mod_image(self) -> None:
        names = self._selected_mod_names()
        if not names:
            return
        file_name = prompts.choose_open_file(self, "Set mod image")
        if not file_name:
            return
        mod_name = names[0]
        def done(_result):
            self._invalidate_mod_image(mod_name)
            self.refresh_mods([mod_name])

        self._run_action("Importing image...", lambda: import_mod_image(self.cfg, mod_name, Path(file_name)), done)


def _app_icon() -> QtGui.QIcon | None:
    icon_path = Path(__file__).resolve().parent.parent.parent / "assets" / "icon.png"
    if not icon_path.exists():
        return None
    return QtGui.QIcon(str(icon_path))


def start() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    icon = _app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    window = ModManagerGui()
    if icon is not None:
        window.setWindowIcon(icon)
    window.show()
    return app.exec()
