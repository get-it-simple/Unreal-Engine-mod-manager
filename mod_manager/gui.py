from __future__ import annotations

import importlib.util
import locale as _locale
from datetime import datetime
from pathlib import Path
from typing import Callable, List

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ModuleNotFoundError:
    QtCore = None
    QtGui = None
    QtWidgets = None

from .cli_utils import ensure_paths, open_folder, select_in_explorer
from .dragdrop import read_clipboard_image, read_clipboard_paths
from .models import ModItem
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
    mods_records,
    mods_view,
    remove_label_from_mods,
    toggle_mods_by_indexes,
)
from .presets import (
    delete_presets_by_indexes,
    presets_records,
    presets_view,
    save_preset_from_installed,
    toggle_presets_by_indexes,
)
from .storage import load_config, save_config
from .workers import WorkerPool, _run_import_batch, _run_save_settings


def _sys_str(key: str) -> str:
    try:
        lang = (_locale.getdefaultlocale()[0] or "en").split("_")[0].lower()
    except Exception:
        lang = "en"
    translations = {
        "install": {"uk": "Встановити", "ru": "Установить", "de": "Installieren", "fr": "Installer", "pl": "Zainstaluj", "it": "Installa", "es": "Instalar"},
        "uninstall": {"uk": "Видалити", "ru": "Удалить", "de": "Deinstallieren", "fr": "Désinstaller", "pl": "Odinstaluj", "it": "Installa", "es": "Desinstalar"},
    }
    return translations.get(key, {}).get(lang, key.capitalize())


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


if QtCore is not None:

    class ModTableModel(QtCore.QAbstractTableModel):
        HEADERS = ("Mod", "Label", "Last managed")

        def __init__(self, parent=None):
            super().__init__(parent)
            self.mods: list[ModItem] = []
            self.labels: dict[str, str] = {}
            self.records: dict[str, dict] = {}

        def set_data(self, mods: list[ModItem], labels: dict, records: dict) -> None:
            self.beginResetModel()
            self.mods = list(mods)
            self.labels = dict(labels or {})
            self.records = dict(records or {})
            self.endResetModel()

        def rowCount(self, parent=QtCore.QModelIndex()) -> int:
            return 0 if parent.isValid() else len(self.mods)

        def columnCount(self, parent=QtCore.QModelIndex()) -> int:
            return 0 if parent.isValid() else len(self.HEADERS)

        def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
            if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
                return self.HEADERS[section]
            return None

        def data(self, index, role=QtCore.Qt.DisplayRole):
            if not index.isValid():
                return None
            mod = self.mods[index.row()]
            label = self.labels.get(mod.name, "-")
            last = self.records.get(mod.name, {}).get("last_managed") or "-"
            if role == QtCore.Qt.UserRole:
                return mod
            if role == QtCore.Qt.DisplayRole:
                if index.column() == 0:
                    return ("[installed] " if mod.installed else "") + mod.name
                if index.column() == 1:
                    return label
                return last
            if role == QtCore.Qt.FontRole and mod.installed:
                font = QtGui.QFont()
                font.setBold(True)
                return font
            return None


    class PresetTableModel(QtCore.QAbstractTableModel):
        HEADERS = ("Preset", "State", "Mods", "Last managed")

        def __init__(self, parent=None):
            super().__init__(parent)
            self.presets: dict[str, list[str]] = {}
            self.keys: list[str] = []
            self.records: dict[str, dict] = {}

        def set_data(self, presets: dict, keys: list[str], records: dict) -> None:
            self.beginResetModel()
            self.presets = dict(presets or {})
            self.keys = list(keys or [])
            self.records = dict(records or {})
            self.endResetModel()

        def rowCount(self, parent=QtCore.QModelIndex()) -> int:
            return 0 if parent.isValid() else len(self.keys)

        def columnCount(self, parent=QtCore.QModelIndex()) -> int:
            return 0 if parent.isValid() else len(self.HEADERS)

        def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
            if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
                return self.HEADERS[section]
            return None

        def data(self, index, role=QtCore.Qt.DisplayRole):
            if not index.isValid() or role != QtCore.Qt.DisplayRole:
                return None
            name = self.keys[index.row()]
            rec = self.records.get(name, {})
            values = (name, rec.get("state") or "-", str(len(self.presets.get(name, []))), rec.get("last_managed") or "-")
            return values[index.column()]


    class BrokenTableModel(QtCore.QAbstractTableModel):
        HEADERS = ("Broken link", "Destination")

        def __init__(self, parent=None):
            super().__init__(parent)
            self.mods: list[ModItem] = []

        def set_data(self, mods: list[ModItem]) -> None:
            self.beginResetModel()
            self.mods = list(mods)
            self.endResetModel()

        def rowCount(self, parent=QtCore.QModelIndex()) -> int:
            return 0 if parent.isValid() else len(self.mods)

        def columnCount(self, parent=QtCore.QModelIndex()) -> int:
            return 0 if parent.isValid() else len(self.HEADERS)

        def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
            if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
                return self.HEADERS[section]
            return None

        def data(self, index, role=QtCore.Qt.DisplayRole):
            if not index.isValid():
                return None
            mod = self.mods[index.row()]
            if role == QtCore.Qt.UserRole:
                return mod
            if role == QtCore.Qt.DisplayRole:
                return mod.name if index.column() == 0 else str(mod.dest)
            return None


    class TileDelegate(QtWidgets.QStyledItemDelegate):
        def __init__(self, cfg: dict, parent=None):
            super().__init__(parent)
            self.cfg = cfg
            self._pixmaps: dict[tuple[str, int], QtGui.QPixmap] = {}

        def paint(self, painter, option, index) -> None:
            painter.save()
            mod = index.data(QtCore.Qt.UserRole)
            label = index.model().labels.get(mod.name, "-")
            selected = bool(option.state & QtWidgets.QStyle.State_Selected)
            rect = option.rect.adjusted(6, 6, -6, -6)
            bg = QtGui.QColor("#dbeafe" if selected else "#ffffff")
            painter.setPen(QtGui.QPen(QtGui.QColor("#94a3b8")))
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 6, 6)

            image_rect = QtCore.QRect(rect.left() + 8, rect.top() + 8, rect.width() - 16, max(48, rect.width() - 18))
            pixmap = self._pixmap_for(mod, image_rect.size())
            if pixmap.isNull():
                painter.fillRect(image_rect, QtGui.QColor("#e2e8f0"))
                painter.setPen(QtGui.QColor("#64748b"))
                painter.drawText(image_rect, QtCore.Qt.AlignCenter, "No image")
            else:
                painter.drawPixmap(image_rect, pixmap)

            if mod.installed:
                badge = QtCore.QRect(rect.left() + 12, rect.top() + 12, 72, 22)
                painter.setBrush(QtGui.QColor("#16a34a"))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawRoundedRect(badge, 4, 4)
                painter.setPen(QtGui.QColor("#ffffff"))
                painter.drawText(badge, QtCore.Qt.AlignCenter, "Installed")

            text_rect = QtCore.QRect(rect.left() + 8, image_rect.bottom() + 8, rect.width() - 16, 44)
            painter.setPen(QtGui.QColor("#0f172a"))
            painter.drawText(text_rect, QtCore.Qt.TextWordWrap | QtCore.Qt.AlignTop, mod.name)
            label_rect = QtCore.QRect(rect.left() + 8, text_rect.bottom() + 4, rect.width() - 16, 20)
            painter.setPen(QtGui.QColor("#475569"))
            painter.drawText(label_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label)
            painter.restore()

        def sizeHint(self, option, index):
            size = max(96, int(self.cfg.get("tile_size", 140)))
            return QtCore.QSize(size + 28, size + 92)

        def _pixmap_for(self, mod: ModItem, size: QtCore.QSize) -> QtGui.QPixmap:
            key = (mod.name, max(size.width(), size.height()))
            if key in self._pixmaps:
                return self._pixmaps[key]
            img_path = mod_image_path(self.cfg, mod.name)
            pixmap = QtGui.QPixmap(str(img_path)) if img_path else QtGui.QPixmap()
            if not pixmap.isNull():
                pixmap = pixmap.scaled(size, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
                if pixmap.width() > size.width() or pixmap.height() > size.height():
                    x = max(0, (pixmap.width() - size.width()) // 2)
                    y = max(0, (pixmap.height() - size.height()) // 2)
                    pixmap = pixmap.copy(x, y, size.width(), size.height())
            self._pixmaps[key] = pixmap
            return pixmap


    class ModListView(QtWidgets.QListView):
        zoomRequested = QtCore.Signal(int)

        def wheelEvent(self, event) -> None:
            if event.modifiers() & QtCore.Qt.ControlModifier:
                self.zoomRequested.emit(1 if event.angleDelta().y() > 0 else -1)
                event.accept()
                return
            super().wheelEvent(event)


    class DetailImageLabel(QtWidgets.QLabel):
        def __init__(self, pixmap: QtGui.QPixmap, parent=None):
            super().__init__(parent)
            self._source_pixmap = pixmap
            self._target_size = QtCore.QSize(1, 1)
            self.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
            self.setMinimumWidth(0)
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        def resizeEvent(self, event) -> None:
            super().resizeEvent(event)
            self.update_scaled_pixmap()

        def update_scaled_pixmap(self, size: QtCore.QSize | None = None) -> None:
            if self._source_pixmap.isNull():
                return
            if size is not None:
                self._target_size = size
            target_width = self._target_size.width() if self._target_size.width() > 1 else self.width()
            if target_width <= 1 and self.parentWidget():
                target_width = self.parentWidget().width()
            target_height = self._target_size.height() if self._target_size.height() > 1 else self._source_pixmap.height()
            target_width = max(1, target_width)
            target_height = max(1, target_height)
            scaled = self._source_pixmap.scaled(target_width, target_height, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.setPixmap(scaled)
            self.setFixedHeight(scaled.height())


    class ModManagerGui(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Mod Manager")
            self.cfg = load_config()
            self.resize(max(880, int(self.cfg.get("window_width", 1200))), max(560, int(self.cfg.get("window_height", 750))))
            self.setMinimumSize(880, 560)
            self.setAcceptDrops(True)

            self.mod_page = _Var(1)
            self.preset_page = _Var(1)
            self.search_var = _Var("")
            self.label_filter_var = _Var("")
            self.label_edit_var = _Var("")
            self.order_var = _Var(self.cfg.get("order_var", "Default"))
            self.mod_view_mode = _Var(self.cfg.get("mod_view_mode", "list"))
            self.status_var = _Var("")
            self.setting_vars: dict[str, _Var] = {}

            self.current_mod_items: list[ModItem] = []
            self.current_mods_shown: list[ModItem] = []
            self.current_mod_labels: dict[str, str] = {}
            self.current_mod_records: dict[str, dict] = {}
            self.current_broken: list[ModItem] = []
            self.busy = False
            self.action_widgets: list[QtWidgets.QWidget] = []
            self.mod_selection_widgets: list[QtWidgets.QWidget] = []
            self.mod_sort_key = self.cfg.get("mod_sort_key", "d")
            self.mod_sort_reverse = bool(self.cfg.get("mod_sort_reverse", False))
            self.preset_sort_key = self.cfg.get("preset_sort_key", "name")
            self.preset_sort_reverse = bool(self.cfg.get("preset_sort_reverse", False))
            self._pool = WorkerPool()
            self._poll_timer = QtCore.QTimer(self)
            self._poll_timer.timeout.connect(self._poll_workers)

            self._build()
            self._bind_navigation_events()
            self.refresh_all()

        def closeEvent(self, event) -> None:
            self.cfg["window_width"] = self.width()
            self.cfg["window_height"] = self.height()
            self._save_tile_splitter_sizes()
            save_config(self.cfg)
            self._pool.shutdown()
            super().closeEvent(event)

        def eventFilter(self, obj, event):
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
                if event.button() == QtCore.Qt.XButton1:
                    return self._nav_back() == "break"
                if event.button() == QtCore.Qt.XButton2:
                    return self._nav_forward() == "break"
            detail_scroll = getattr(self, "detail_scroll", None)
            if detail_scroll and obj is detail_scroll.viewport() and event.type() == QtCore.QEvent.Resize:
                self._update_detail_image_size()
            return super().eventFilter(obj, event)

        def _bind_navigation_events(self) -> None:
            QtWidgets.QApplication.instance().installEventFilter(self)
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
            self.mods_tab = QtWidgets.QWidget()
            self.setCentralWidget(self.mods_tab)
            self.statusBar().showMessage("")
            self._build_menu()
            self._build_mods()
            self._build_presets()
            self._build_settings()
            self._build_broken()

        def _build_menu(self) -> None:
            manage = self.menuBar().addMenu("Manage")
            presets = manage.addAction(self._icon("save"), "Presets")
            presets.setToolTip("Open presets")
            presets.triggered.connect(self._open_presets_dialog)
            settings = manage.addAction(self._icon("open"), "Settings")
            settings.setToolTip("Open settings")
            settings.triggered.connect(self._open_settings_dialog)
            broken = manage.addAction(self._icon("delete"), "Broken links")
            broken.setToolTip("Open broken links cleanup")
            broken.triggered.connect(self._open_broken_dialog)

        def _dialog(self, title: str, width: int = 760, height: int = 520) -> QtWidgets.QDialog:
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle(title)
            dialog.resize(width, height)
            return dialog

        def _show_dialog(self, dialog: QtWidgets.QDialog) -> None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

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

        def _button(self, text: str, command: Callable, tooltip: str = ""):
            button = QtWidgets.QPushButton(text)
            button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            button.clicked.connect(command)
            if tooltip:
                button.setToolTip(tooltip)
            self.action_widgets.append(button)
            return button

        def _icon(self, name: str) -> QtGui.QIcon:
            style = self.style()
            icons = {
                "add": QtWidgets.QStyle.SP_DialogApplyButton,
                "back": QtWidgets.QStyle.SP_ArrowBack,
                "clear": QtWidgets.QStyle.SP_DialogResetButton,
                "delete": QtWidgets.QStyle.SP_TrashIcon,
                "folder": QtWidgets.QStyle.SP_DirOpenIcon,
                "forward": QtWidgets.QStyle.SP_ArrowForward,
                "image": QtWidgets.QStyle.SP_FileIcon,
                "import": QtWidgets.QStyle.SP_FileDialogNewFolder,
                "install": QtWidgets.QStyle.SP_DialogApplyButton,
                "list": QtWidgets.QStyle.SP_FileDialogDetailedView,
                "menu": QtWidgets.QStyle.SP_TitleBarMenuButton,
                "open": QtWidgets.QStyle.SP_DirIcon,
                "remove": QtWidgets.QStyle.SP_DialogCancelButton,
                "save": QtWidgets.QStyle.SP_DialogSaveButton,
                "search": QtWidgets.QStyle.SP_FileDialogContentsView,
                "toggle": QtWidgets.QStyle.SP_BrowserReload,
                "uninstall": QtWidgets.QStyle.SP_DialogDiscardButton,
            }
            return style.standardIcon(icons.get(name, QtWidgets.QStyle.SP_FileIcon))

        def _icon_button(self, text: str, command: Callable, tooltip: str, icon: str, icon_only: bool = True):
            button = QtWidgets.QPushButton("" if icon_only else text)
            button.setIcon(self._icon(icon))
            button.setIconSize(QtCore.QSize(18, 18))
            button.setAccessibleName(text)
            button.setToolTip(tooltip or text)
            button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            if icon_only:
                button.setFixedSize(32, 32)
            button.clicked.connect(command)
            self.action_widgets.append(button)
            return button

        def _mod_selection_button(self, text: str, command: Callable, tooltip: str = "", icon: str = "toggle"):
            button = self._icon_button(text, command, tooltip or text, icon)
            button.setEnabled(False)
            self.mod_selection_widgets.append(button)
            return button

        def _set_icon_button_checked(self, button: QtWidgets.QPushButton, checked: bool) -> None:
            button.setCheckable(True)
            button.setChecked(checked)

        def _build_mods(self) -> None:
            layout = QtWidgets.QVBoxLayout(self.mods_tab)
            top = QtWidgets.QHBoxLayout()
            self.search_box = QtWidgets.QComboBox()
            self.search_box.setEditable(True)
            self.search_box.lineEdit().setPlaceholderText("Search")
            self.search_box.lineEdit().returnPressed.connect(self._mods_search)
            self.label_filter_box = QtWidgets.QComboBox()
            self.label_filter_box.setEditable(True)
            self.label_filter_box.lineEdit().setPlaceholderText("Label")
            self.label_filter_box.lineEdit().returnPressed.connect(self._mods_search)
            self.view_list_button = self._icon_button("List view", lambda: self._set_view_mode("list"), "Show mods as a list", "list")
            self.view_tiles_button = self._icon_button("Tile view", lambda: self._set_view_mode("tiles"), "Show mods as tiles", "image")
            self._set_icon_button_checked(self.view_list_button, self.mod_view_mode.get() != "tiles")
            self._set_icon_button_checked(self.view_tiles_button, self.mod_view_mode.get() == "tiles")
            self.manage_menu = QtWidgets.QMenu(self)
            self.presets_menu_action = self.manage_menu.addAction(self._icon("save"), "Presets")
            self.presets_menu_action.triggered.connect(self._open_presets_dialog)
            self.settings_menu_action = self.manage_menu.addAction(self._icon("open"), "Settings")
            self.settings_menu_action.triggered.connect(self._open_settings_dialog)
            self.broken_menu_action = self.manage_menu.addAction(self._icon("delete"), "Broken links")
            self.broken_menu_action.triggered.connect(self._open_broken_dialog)
            self.manage_button = self._icon_button("Menu", lambda: None, "Open application menu", "menu", icon_only=False)
            self.manage_button.setText("Menu")
            self.manage_button.setMenu(self.manage_menu)
            self.order_box = QtWidgets.QComboBox()
            self.order_box.addItems(["Default", "Created date"])
            self.order_box.setCurrentText(self.order_var.get() if self.order_var.get() in {"Default", "Created date"} else "Default")
            self.order_box.currentTextChanged.connect(self._set_mod_order)
            top.addWidget(self.search_box, 2)
            top.addWidget(self.label_filter_box, 1)
            top.addWidget(self._icon_button("Search", self._mods_search, "Apply search and label filters", "search"))
            top.addWidget(self._icon_button("Clear", self._mods_clear, "Clear search and label filters", "clear"))
            top.addWidget(QtWidgets.QLabel("Order"))
            top.addWidget(self.order_box)
            top.addWidget(QtWidgets.QLabel("View"))
            top.addWidget(self.view_list_button)
            top.addWidget(self.view_tiles_button)
            top.addWidget(self.manage_button)
            layout.addLayout(top)

            self.mods_model = ModTableModel(self)
            self.mods_stack = QtWidgets.QStackedWidget()
            self.mods_table = QtWidgets.QTableView()
            self.mods_table.setModel(self.mods_model)
            self.mods_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.mods_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            self.mods_table.setAcceptDrops(True)
            self.mods_table.viewport().setAcceptDrops(True)
            self.mods_table.viewport().installEventFilter(self)
            mods_header = self.mods_table.horizontalHeader()
            mods_header.setStretchLastSection(False)
            mods_header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            mods_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
            mods_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
            self.mods_table.verticalHeader().setVisible(False)
            self.mods_table.doubleClicked.connect(lambda _idx: self._toggle_selected_mods())
            self.mods_table.selectionModel().selectionChanged.connect(lambda _a, _b: self._on_mod_selection_changed())

            self.tile_delegate = TileDelegate(self.cfg, self)
            self.tiles_view = ModListView()
            self.tiles_view.setModel(self.mods_model)
            self.tiles_view.setItemDelegate(self.tile_delegate)
            self.tiles_view.setViewMode(QtWidgets.QListView.IconMode)
            self.tiles_view.setResizeMode(QtWidgets.QListView.Adjust)
            self.tiles_view.setMovement(QtWidgets.QListView.Static)
            self.tiles_view.setUniformItemSizes(True)
            self.tiles_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            self.tiles_view.setAcceptDrops(True)
            self.tiles_view.viewport().setAcceptDrops(True)
            self.tiles_view.viewport().installEventFilter(self)
            self.tiles_view.zoomRequested.connect(self._zoom_tiles)
            self.tiles_view.doubleClicked.connect(lambda _idx: self._toggle_selected_mods())
            self.tiles_view.selectionModel().selectionChanged.connect(lambda _a, _b: self._on_mod_selection_changed())

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
            self.tile_splitter.setStretchFactor(0, 3)
            self.tile_splitter.setStretchFactor(1, 2)
            self.tile_splitter.splitterMoved.connect(lambda _pos, _index: self._save_tile_splitter_sizes())
            QtCore.QTimer.singleShot(0, self._restore_tile_splitter_sizes)

            self.mods_stack.addWidget(self.mods_table)
            self.mods_stack.addWidget(self.tile_splitter)
            layout.addWidget(self.mods_stack, 1)

            actions = QtWidgets.QHBoxLayout()
            actions.addWidget(self._icon_button("Previous page", lambda: self._change_mod_page(-1), "Previous mods page", "back"))
            actions.addWidget(self._icon_button("Next page", lambda: self._change_mod_page(1), "Next mods page", "forward"))
            self.page_label = QtWidgets.QLabel("Page 1/1")
            actions.addWidget(self.page_label)
            actions.addStretch(1)
            actions.addWidget(self._icon_button(_sys_str("install"), self._install_page, "Install all mods on the current page", "install"))
            actions.addWidget(self._icon_button(_sys_str("uninstall"), self._uninstall_page, "Uninstall all mods on the current page", "uninstall"))
            actions.addWidget(self._mod_selection_button("Toggle", self._toggle_selected_mods, "Toggle selected mods", "toggle"))
            self.label_edit = QtWidgets.QLineEdit()
            self.label_edit.setPlaceholderText("Label")
            self.label_edit.setMaximumWidth(160)
            self.label_edit.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            actions.addWidget(self.label_edit)
            actions.addWidget(self._mod_selection_button("Add label", self._add_label_selected, "Add label to selected mods", "add"))
            actions.addWidget(self._mod_selection_button("Remove label", self._remove_label_selected, "Remove label from selected mods", "remove"))
            actions.addWidget(self._icon_button("Import files", self._import_mod_files, "Import mod files", "import"))
            actions.addWidget(self._icon_button("Import folder", self._import_mod_folder, "Import a mod folder", "folder"))
            actions.addWidget(self._mod_selection_button("Set image", self._set_mod_image, "Set preview image for selected mod", "image"))
            layout.addLayout(actions)
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
            self.presets_model = PresetTableModel(self)
            self.presets_table = QtWidgets.QTableView()
            self.presets_table.setModel(self.presets_model)
            self.presets_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.presets_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            self.presets_table.horizontalHeader().setStretchLastSection(True)
            self.presets_table.verticalHeader().setVisible(False)
            self.presets_table.doubleClicked.connect(self._toggle_preset_at_index)
            layout.addWidget(self.presets_table)
            actions = QtWidgets.QHBoxLayout()
            self.preset_name = QtWidgets.QLineEdit()
            self.preset_name.setPlaceholderText("Preset name")
            actions.addWidget(self._icon_button("Previous page", lambda: self._change_preset_page(-1), "Previous presets page", "back"))
            actions.addWidget(self._icon_button("Next page", lambda: self._change_preset_page(1), "Next presets page", "forward"))
            self.preset_page_label = QtWidgets.QLabel("Page 1/1")
            actions.addWidget(self.preset_page_label)
            actions.addStretch(1)
            actions.addWidget(self.preset_name)
            actions.addWidget(self._icon_button("Save", self._save_preset, "Save current installed mods as preset", "save"))
            actions.addWidget(self._icon_button("Toggle", self._toggle_selected_presets, "Toggle selected presets", "toggle"))
            actions.addWidget(self._icon_button("Delete", self._delete_selected_presets, "Delete selected presets", "delete"))
            layout.addLayout(actions)

        def _build_settings(self) -> None:
            self.settings_dialog = self._dialog("Settings", 820, 560)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            wrapper = QtWidgets.QWidget()
            wrapper_layout = QtWidgets.QVBoxLayout(wrapper)
            wrapper_layout.setAlignment(QtCore.Qt.AlignTop)
            host = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(host)
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
            keys = [
                "game_mods_dir",
                "mods_source_dir",
                "mod_extensions",
                "link_prefix",
                "page_size",
                "max_mod_name_len",
                "max_preset_name_len",
                "max_label_name_len",
                "gui_font_family",
                "gui_font_size",
                "ui_scale_percent",
                "placeholder_image_col_width",
                "mod_view_mode",
                "tile_size",
            ]
            self.setting_widgets: dict[str, QtWidgets.QWidget] = {}
            for key in keys:
                value = self.cfg.get(key, "")
                self.setting_vars[key] = _Var(str(value))
                if key == "mod_view_mode":
                    widget = QtWidgets.QComboBox()
                    widget.addItems(["list", "tiles"])
                    widget.setCurrentText(str(value or "list"))
                elif key == "gui_font_family":
                    widget = QtWidgets.QComboBox()
                    widget.addItem("")
                    widget.addItems(self._system_font_families())
                    if value and widget.findText(str(value)) < 0:
                        widget.addItem(str(value))
                    widget.setCurrentText(str(value or ""))
                else:
                    widget = QtWidgets.QLineEdit(str(value))
                widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                self.setting_widgets[key] = widget
                row = QtWidgets.QHBoxLayout()
                row.addWidget(widget, 1)
                if key in {"game_mods_dir", "mods_source_dir"}:
                    row.addWidget(self._icon_button("Browse", lambda _checked=False, k=key: self._browse_setting(k), f"Browse for {key}", "folder"))
                form.addRow(key, row)
            form.addRow(self._icon_button("Save settings", self._save_settings, "Save settings", "save", icon_only=False))
            wrapper_layout.addWidget(host)
            wrapper_layout.addStretch(1)
            scroll.setWidget(wrapper)
            layout = QtWidgets.QVBoxLayout(self.settings_dialog)
            layout.addWidget(scroll)

        def _system_font_families(self) -> list[str]:
            try:
                families = QtGui.QFontDatabase.families()
            except TypeError:
                families = QtGui.QFontDatabase().families()
            return sorted({str(family) for family in families if family}, key=str.lower)

        def _build_broken(self) -> None:
            self.broken_dialog = self._dialog("Broken links", 760, 520)
            layout = QtWidgets.QVBoxLayout(self.broken_dialog)
            self.broken_model = BrokenTableModel(self)
            self.broken_table = QtWidgets.QTableView()
            self.broken_table.setModel(self.broken_model)
            self.broken_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.broken_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            self.broken_table.horizontalHeader().setStretchLastSection(True)
            self.broken_table.verticalHeader().setVisible(False)
            layout.addWidget(self.broken_table)
            actions = QtWidgets.QHBoxLayout()
            actions.addStretch(1)
            actions.addWidget(self._icon_button("Remove selected", self._remove_selected_broken, "Remove selected broken links", "remove", icon_only=False))
            actions.addWidget(self._icon_button("Remove all", self._remove_all_broken, "Remove all broken links", "delete", icon_only=False))
            layout.addLayout(actions)

        def _set_busy(self, busy: bool, text: str = "") -> None:
            self.busy = busy
            for widget in self.action_widgets:
                widget.setEnabled(not busy)
            self._update_mod_selection_actions()
            if text:
                self.status_var.set(text)
                self.statusBar().showMessage(text)

        def _run_action(self, label: str, worker: Callable, done: Callable | None = None, file_key: str = "global") -> None:
            self._set_busy(True, label)

            def callback(result, error):
                self._set_busy(False)
                if error:
                    QtWidgets.QMessageBox.critical(self, "Error", str(error))
                    return
                if done:
                    done(result)

            self._pool.submit(file_key, worker, callback=callback)
            self._poll_timer.start(50)

        def _poll_workers(self) -> None:
            polled = self._pool.poll()
            self._pool.fire_callbacks(polled)
            if not self._pool.has_work():
                self._poll_timer.stop()

        def _view_args(self):
            return self.mod_page.get(), self.label_filter_var.get(), self.search_var.get(), self._mod_order_mode()

        def _mod_order_mode(self) -> str:
            order = self.order_var.get()
            if order == "Created date":
                return "cd"
            key = self.mod_sort_key or "d"
            return f"-{key}" if self.mod_sort_reverse and key != "d" else key

        def _preset_order_mode(self) -> str:
            key = self.preset_sort_key or "name"
            return f"-{key}" if self.preset_sort_reverse else key

        def _set_view_mode(self, mode: str) -> None:
            mode = mode if mode in {"list", "tiles"} else "list"
            self.mod_view_mode.set(mode)
            self.cfg["mod_view_mode"] = mode
            save_config(self.cfg)
            self._show_mod_view()

        def _set_mod_order(self, text: str) -> None:
            text = text if text in {"Default", "Created date"} else "Default"
            self.order_var.set(text)
            self.cfg["order_var"] = text
            self.mod_page.set(1)
            save_config(self.cfg)
            self.refresh_mods()

        def _on_mod_view_mode_changed(self) -> None:
            self._set_view_mode(self.mod_view_mode.get())

        def _show_mod_view(self) -> None:
            is_tiles = self._is_tile_view()
            self.mods_stack.setCurrentWidget(self.tile_splitter if is_tiles else self.mods_table)
            self.view_list_button.setChecked(not is_tiles)
            self.view_tiles_button.setChecked(is_tiles)
            self._refresh_selected_detail()

        def _sort_mods(self, key: str) -> None:
            if self.mod_sort_key == key:
                self.mod_sort_reverse = not self.mod_sort_reverse
            else:
                self.mod_sort_key = key
                self.mod_sort_reverse = False
            self.cfg["mod_sort_key"] = self.mod_sort_key
            self.cfg["mod_sort_reverse"] = self.mod_sort_reverse
            self.mod_page.set(1)
            save_config(self.cfg)
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
            self.refresh_presets()

        def _zoom_tiles(self, direction: int):
            if not self._is_tile_view():
                return None
            current = max(96, int(self.cfg.get("tile_size", 140)))
            self.cfg["tile_size"] = max(96, min(280, current + (12 if direction > 0 else -12)))
            self.tile_delegate._pixmaps.clear()
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
            return hasattr(self, "mods_table") and obj in (self.mods_table.viewport(), self.tiles_view.viewport())

        def _mod_name_at_view_position(self, obj, pos: QtCore.QPoint) -> str:
            if not hasattr(self, "mods_model"):
                return ""
            view = self.tiles_view if obj is self.tiles_view.viewport() else self.mods_table
            index = view.indexAt(pos)
            if not index.isValid() or index.row() >= len(self.current_mods_shown):
                return ""
            return self.current_mods_shown[index.row()].name

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
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()
                child = item.layout()
                if child:
                    self._clear_layout(child)

        def _detail_row(self, label: str, value: str) -> None:
            row = QtWidgets.QHBoxLayout()
            name = QtWidgets.QLabel(label)
            name.setMinimumWidth(110)
            name.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
            value_label = QtWidgets.QLabel(value)
            value_label.setWordWrap(True)
            row.addWidget(name)
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
            label_width = 110
            spacing = 28
            needed = (
                label_width
                + metrics.horizontalAdvance(last_managed)
                + label_width
                + metrics.horizontalAdvance(created)
                + spacing
            )
            return available_width >= needed

        def _detail_dates_row(self, mod: ModItem) -> None:
            last_managed = self.current_mod_records.get(mod.name, {}).get("last_managed") or "-"
            created = self._format_mod_created_date(mod)
            if not self._dates_fit_on_one_row(last_managed, created):
                self._detail_row("Last managed", last_managed)
                self._detail_row("Created", created)
                return

            row = QtWidgets.QHBoxLayout()
            for label, value in (("Last managed", last_managed), ("Created", created)):
                name = QtWidgets.QLabel(label)
                name.setMinimumWidth(110)
                name.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
                value_label = QtWidgets.QLabel(value)
                value_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
                row.addWidget(name)
                row.addWidget(value_label)
            row.addStretch(1)
            self.detail_layout.addLayout(row)

        def _detail_path_row(self, label: str, path: Path) -> None:
            row = QtWidgets.QHBoxLayout()
            name = QtWidgets.QLabel(label)
            name.setMinimumWidth(110)
            name.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
            button = QtWidgets.QPushButton(str(path))
            button.setFlat(True)
            button.setCursor(QtCore.Qt.PointingHandCursor)
            button.setStyleSheet("text-align: left; padding-left: 0;")
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked=False, p=Path(path): select_in_explorer(p))
            row.addWidget(name)
            row.addWidget(button, 1)
            self.detail_layout.addLayout(row)

        def _detail_label_row(self, value: str) -> None:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Label"))
            button = QtWidgets.QPushButton(value or "-")
            button.setFlat(False)
            button.setIcon(self._icon("toggle"))
            button.setToolTip("Filter mods by this label")
            button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            button.setEnabled(bool(value and value != "-"))
            button.clicked.connect(lambda: self._toggle_label_filter(value))
            row.addWidget(button)
            row.addStretch(1)
            self.detail_layout.addLayout(row)

        def _detail_state_action_row(self, mod: ModItem) -> None:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Action"))
            text = _sys_str("uninstall") if mod.installed else _sys_str("install")
            button = QtWidgets.QPushButton(text)
            button.setIcon(self._icon("uninstall" if mod.installed else "install"))
            button.setToolTip(("Uninstall" if mod.installed else "Install") + " this mod")
            button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            index = self.current_mods_shown.index(mod) + 1 if mod in self.current_mods_shown else 1
            button.clicked.connect(lambda _checked=False, i=index: self._toggle_selected_indexes([i]))
            row.addWidget(button)
            row.addStretch(1)
            self.detail_layout.addLayout(row)

        def _toggle_label_filter(self, label: str) -> None:
            if not label or label == "-":
                return
            current = self.label_filter_var.get()
            self.label_filter_var.set("" if current.lower() == label.lower() else label)
            self.label_filter_box.setCurrentText(self.label_filter_var.get())
            self.mod_page.set(1)
            self.refresh_mods()

        def _selected_mod_rows_for_state(self, installed: bool) -> list[int]:
            rows = self._selected_rows(self._current_mod_view())
            return [row + 1 for row in rows if row < len(self.current_mods_shown) and self.current_mods_shown[row].installed == installed]

        def _toggle_selected_indexes(self, indexes: list[int]) -> None:
            if not indexes:
                return
            names = [self.current_mods_shown[i - 1].name for i in indexes if 1 <= i <= len(self.current_mods_shown)]

            def done(message):
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                self.refresh_mods(names)
                self.refresh_presets()

            self._run_action("Updating selected mods...", lambda: toggle_mods_by_indexes(self.current_mods_shown, indexes), done)

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
            self._detail_state_action_row(mod)
            self._detail_dates_row(mod)
            self._detail_path_row("Source", mod.src)
            self._detail_path_row("Destination", mod.dest)
            self._detail_image(mod.name)
            self.detail_layout.addStretch(1)

        def _invalidate_mod_image(self, mod_name: str) -> None:
            self.tile_delegate._pixmaps = {key: value for key, value in self.tile_delegate._pixmaps.items() if key[0] != mod_name}
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
            items, shown, page, pages, labels = mods_view(self.cfg, page, label_filter, search, order)
            self.current_mod_items = items
            self.current_mods_shown = shown
            self.current_mod_labels = labels
            self.current_mod_records = mods_records()
            self.mod_page.set(page)
            list_blocker = QtCore.QSignalBlocker(self.mods_table.selectionModel())
            tile_blocker = QtCore.QSignalBlocker(self.tiles_view.selectionModel())
            try:
                self.mods_model.set_data(shown, labels, self.current_mod_records)
                self.page_label.setText(f"Page {page}/{pages}")
                self.search_box.clear()
                self.search_box.addItems([m.name for m in items])
                self.search_box.setCurrentText(search)
                self.label_filter_box.clear()
                self.label_filter_box.addItems(sorted({v for v in labels.values() if v}))
                self.label_filter_box.setCurrentText(label_filter)
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
            self.preset_page.set(page)
            selection = self.presets_table.selectionModel()
            blocker = QtCore.QSignalBlocker(selection) if selection else None
            self.presets_table.setUpdatesEnabled(False)
            try:
                self.presets_model.set_data(presets, page_keys, presets_records())
                self.preset_page_label.setText(f"Page {page}/{pages}")
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

        def _mods_clear(self) -> None:
            self.search_var.set("")
            self.label_filter_var.set("")
            self.search_box.setCurrentText("")
            self.label_filter_box.setCurrentText("")
            self.mod_page.set(1)
            self.refresh_mods()

        def _change_mod_page(self, delta: int) -> None:
            self.mod_page.set(max(1, int(self.mod_page.get()) + delta))
            self.refresh_mods()

        def _change_preset_page(self, delta: int) -> None:
            self.preset_page.set(max(1, int(self.preset_page.get()) + delta))
            self.refresh_presets()

        def _install_page(self) -> None:
            page, label_filter, search, order = self._view_args()

            def done(result):
                target_page, total, errors = result
                self.status_var.set(f"Installed {total - errors}/{total} on page {target_page}. Errors: {errors}.")
                self.statusBar().showMessage(self.status_var.get())
                self.refresh_mods()
                self.refresh_presets()

            self._run_action("Installing mods...", lambda: apply_mods_page(self.cfg, page, label_filter, search, order), done)

        def _uninstall_page(self) -> None:
            page, label_filter, search, order = self._view_args()

            def done(result):
                target_page, count = result
                self.status_var.set(f"Uninstalled {count} on page {target_page}.")
                self.statusBar().showMessage(self.status_var.get())
                self.refresh_mods()
                self.refresh_presets()

            self._run_action("Uninstalling mods...", lambda: deactivate_mods_page(self.cfg, page, label_filter, search, order), done)

        def _toggle_selected_mods(self) -> None:
            indexes = self._selected_indexes()
            names = [self.current_mods_shown[i - 1].name for i in indexes if 1 <= i <= len(self.current_mods_shown)]

            def done(message):
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                self.refresh_mods(names)
                self.refresh_presets()

            self._run_action("Toggling mods...", lambda: toggle_mods_by_indexes(self.current_mods_shown, indexes), done)

        def _selected_mod_names(self) -> list[str]:
            return [self.current_mods_shown[i - 1].name for i in self._selected_indexes() if 1 <= i <= len(self.current_mods_shown)]

        def _add_label_selected(self) -> None:
            label = self.label_edit.text().strip()
            self.label_edit_var.set(label)
            if not label:
                QtWidgets.QMessageBox.critical(self, "Label", "Enter label.")
                return
            targets = self._selected_mod_names()

            def done(message):
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                self.refresh_mods(targets)

            self._run_action("Adding label...", lambda: add_label_to_mods(label, targets), done)

        def _remove_label_selected(self) -> None:
            label = self.label_edit.text().strip()
            self.label_edit_var.set(label)
            targets = self._selected_mod_names()

            def done(message):
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                self.refresh_mods(targets)

            self._run_action("Removing label...", lambda: remove_label_from_mods(label, targets), done)

        def _save_preset(self) -> None:
            name = self.preset_name.text().strip()
            if not name:
                QtWidgets.QMessageBox.critical(self, "Preset", "Enter preset name.")
                return

            def done(result):
                ok, message = result
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                if ok:
                    self.refresh_presets()

            self._run_action("Saving preset...", lambda: save_preset_from_installed(self.cfg, name), done)

        def _toggle_selected_presets(self) -> None:
            indexes = [row + 1 for row in self._selected_rows(self.presets_table)]
            installed = {m.name for m in list_installed_mods(self.cfg)}

            def done(result):
                message, _messages, _has_errors = result
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                self.refresh_mods()
                self.refresh_presets()
                self._close_dialog(self.presets_dialog)

            self._run_action("Toggling presets...", lambda: toggle_presets_by_indexes(self.cfg, self.preset_page.get(), indexes, installed), done)

        def _toggle_preset_at_index(self, index) -> None:
            if index.isValid() and self.presets_table.selectionModel():
                selection = self.presets_table.selectionModel()
                selection.clearSelection()
                selection.select(index, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
                self.presets_table.setCurrentIndex(index)
            self._toggle_selected_presets()

        def _delete_selected_presets(self) -> None:
            indexes = [row + 1 for row in self._selected_rows(self.presets_table)]

            def done(result):
                removed, missing = result
                message = f"Deleted: {removed}. Missing: {', '.join(missing) if missing else 'none'}"
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                self.refresh_presets()

            self._run_action("Deleting presets...", lambda: delete_presets_by_indexes(self.cfg, self.preset_page.get(), indexes), done)

        def _browse_setting(self, key: str) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, key)
            if path:
                widget = self.setting_widgets.get(key)
                if isinstance(widget, QtWidgets.QLineEdit):
                    widget.setText(path)

        def _save_settings(self) -> None:
            values = {}
            for key, widget in self.setting_widgets.items():
                if isinstance(widget, QtWidgets.QComboBox):
                    values[key] = widget.currentText()
                else:
                    values[key] = widget.text()

            def done(new_cfg):
                self.cfg = new_cfg
                self.mod_view_mode.set(self.cfg.get("mod_view_mode", "list"))
                self._show_mod_view()
                self.status_var.set("Settings saved.")
                self.statusBar().showMessage("Settings saved.")
                self.refresh_all()
                self._close_dialog(self.settings_dialog)

            self._run_action("Saving settings...", lambda: _run_save_settings(self.cfg, values), done)

        def _open_folder(self, target: str) -> None:
            open_folder(self.cfg, target)

        def _remove_selected_broken(self) -> None:
            rows = self._selected_rows(self.broken_table)
            selected = [self.current_broken[i] for i in rows if i < len(self.current_broken)]

            def done(count):
                self.status_var.set(f"Removed broken links: {count}")
                self.statusBar().showMessage(self.status_var.get())
                self.refresh_broken()
                self._close_dialog(self.broken_dialog)

            self._run_action("Removing broken links...", lambda: sum(1 for mod in selected if deactivate_mod(mod)[0]), done)

        def _remove_all_broken(self) -> None:
            mods = list(self.current_broken)

            def done(count):
                self.status_var.set(f"Removed broken links: {count}")
                self.statusBar().showMessage(self.status_var.get())
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
            self._import_paths([Path(p) for p in paths], image_target_name=target_mod_name)

        def _handle_paste(self, event=None) -> None:
            paths = read_clipboard_paths()
            if paths:
                self._handle_clipboard_paths(paths)
                return
            image = read_clipboard_image()
            if image:
                mod_name = self._choose_mod_for_image()
                if mod_name:
                    def done(_result):
                        self._invalidate_mod_image(mod_name)
                        self.refresh_mods([mod_name])

                    self._run_action("Importing image...", lambda: import_mod_image(self.cfg, mod_name, image), done)

        def _handle_clipboard_paths(self, paths: List[Path]) -> None:
            self._import_paths(paths)

        def _import_paths(self, paths: List[Path], image_target_name: str = "") -> None:
            if not ensure_paths(self.cfg):
                return
            existing = {m.name for m in self.current_mod_items}
            tasks = []
            image_mods = []
            for path in paths:
                if is_image_file(path):
                    mod_name = image_target_name or self._choose_mod_for_image(path.stem)
                    if mod_name:
                        tasks.append(("image", path, mod_name, False))
                        image_mods.append(mod_name)
                elif is_mod_file(path, self.cfg):
                    replace = path.name in existing and QtWidgets.QMessageBox.question(
                        self,
                        "Import",
                        f"Replace existing mod '{path.name}'?",
                    ) == QtWidgets.QMessageBox.Yes
                    tasks.append(("mod", path, "", replace))
            if not tasks:
                return

            def done(result):
                imported, skipped = result
                message = f"Imported: {len(imported)}. Skipped: {len(skipped)}."
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                for mod_name in image_mods:
                    self._invalidate_mod_image(mod_name)
                if image_mods:
                    self.refresh_mods(image_mods)
                else:
                    self.refresh_mods()

            self._run_action("Importing...", lambda: _run_import_batch(self.cfg, tasks), done)

        def _import_mod_files(self) -> None:
            files, _filter = QtWidgets.QFileDialog.getOpenFileNames(self, "Import mod files")
            self._import_paths([Path(p) for p in files])

        def _import_mod_folder(self) -> None:
            folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Import mod folder")
            if folder:
                self._import_paths([Path(folder)])

        def _choose_mod_for_image(self, default_name: str = "") -> str:
            names = [m.name for m in self.current_mod_items]
            if not names:
                return ""
            if default_name in names:
                return default_name
            name, ok = QtWidgets.QInputDialog.getItem(self, "Mod image", "Mod", names, 0, False)
            return name if ok else ""

        def _set_mod_image(self) -> None:
            names = self._selected_mod_names()
            if not names:
                return
            file_name, _filter = QtWidgets.QFileDialog.getOpenFileName(self, "Set mod image")
            if not file_name:
                return
            mod_name = names[0]
            def done(_result):
                self._invalidate_mod_image(mod_name)
                self.refresh_mods([mod_name])

            self._run_action("Importing image...", lambda: import_mod_image(self.cfg, mod_name, Path(file_name)), done)


else:

    class ModManagerGui:
        def __init__(self):
            raise RuntimeError("PySide6 is required for the GUI. Install dependencies with: pip install -r requirements.txt")


def run_gui() -> int:
    if QtWidgets is None:
        print("PySide6 is required for the GUI. Install dependencies with: pip install -r requirements.txt")
        return 2
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = ModManagerGui()
    window.show()
    return app.exec()


def qt_available() -> bool:
    return importlib.util.find_spec("PySide6") is not None
