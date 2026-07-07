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

from app_paths import APP_NAME, APP_VERSION

from .cli_utils import ensure_paths, open_folder, select_in_explorer
from .dragdrop import QtWindowsDropTarget, read_clipboard_image, read_clipboard_paths
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
    delete_presets_by_names,
    presets_records,
    presets_view,
    save_preset_from_installed,
    toggle_presets_by_names,
)
from .storage import (
    GAME_PROFILE_KEYS,
    active_game_profile,
    create_game_profile,
    delete_game_profile,
    game_abbreviation,
    load_config,
    normalize_game_profiles,
    save_config,
    set_active_game_profile,
    update_game_profile,
)
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

    def _accent_color() -> QtGui.QColor:
        app = QtWidgets.QApplication.instance()
        color = app.palette().color(QtGui.QPalette.Highlight) if app else QtGui.QColor("#2563eb")
        return color if color.isValid() else QtGui.QColor("#2563eb")


    def _color_luminance(color: QtGui.QColor) -> float:
        r, g, b = color.redF(), color.greenF(), color.blueF()
        return 0.2126 * r + 0.7152 * g + 0.0722 * b


    def _is_dark_palette(palette: QtGui.QPalette) -> bool:
        return _color_luminance(palette.color(QtGui.QPalette.Window)) < 0.45


    def _readable_on(color: QtGui.QColor) -> QtGui.QColor:
        return QtGui.QColor("#000000") if _color_luminance(color) > 0.58 else QtGui.QColor("#ffffff")


    def _custom_accent_color(cfg: dict) -> QtGui.QColor | None:
        if str(cfg.get("gui_accent_color_mode", "system") or "system").lower() != "custom":
            return None
        color = QtGui.QColor(str(cfg.get("gui_accent_color") or ""))
        return color if color.isValid() else None


    def _custom_text_color(cfg: dict) -> QtGui.QColor | None:
        if str(cfg.get("gui_text_color_mode", "system") or "system").lower() != "custom":
            return None
        color = QtGui.QColor(str(cfg.get("gui_text_color") or ""))
        return color if color.isValid() else None


    def _fixed_theme_palette(mode: str, source: QtGui.QPalette) -> QtGui.QPalette:
        accent = source.color(QtGui.QPalette.Highlight)
        if not accent.isValid():
            accent = QtGui.QColor("#2563eb")
        if mode == "system":
            return QtGui.QPalette(source)
        dark = mode == "dark"
        palette = QtGui.QPalette()
        colors = {
            QtGui.QPalette.Window: "#202124" if dark else "#f8fafc",
            QtGui.QPalette.WindowText: "#f8fafc" if dark else "#111827",
            QtGui.QPalette.Base: "#111827" if dark else "#ffffff",
            QtGui.QPalette.AlternateBase: "#1f2937" if dark else "#eef2f7",
            QtGui.QPalette.Text: "#f8fafc" if dark else "#111827",
            QtGui.QPalette.Button: "#2b2f36" if dark else "#f1f5f9",
            QtGui.QPalette.ButtonText: "#f8fafc" if dark else "#111827",
            QtGui.QPalette.ToolTipBase: "#111827" if dark else "#ffffff",
            QtGui.QPalette.ToolTipText: "#f8fafc" if dark else "#111827",
        }
        for role, value in colors.items():
            palette.setColor(role, QtGui.QColor(value))
        palette.setColor(QtGui.QPalette.Highlight, accent)
        palette.setColor(QtGui.QPalette.HighlightedText, _readable_on(accent))
        return palette


    def _check_icon(color: str | QtGui.QColor, size: int = 18, transparent: bool = False) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        if not transparent:
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            pen = QtGui.QPen(QtGui.QColor(color), max(2.0, size * 0.14), QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
            painter.setPen(pen)
            path = QtGui.QPainterPath()
            path.moveTo(size * 0.22, size * 0.50)
            path.lineTo(size * 0.43, size * 0.72)
            path.lineTo(size * 0.78, size * 0.28)
            painter.drawPath(path)
            painter.end()
        return QtGui.QIcon(pixmap)


    def _sort_direction_icon(descending: bool, color: QtGui.QColor, size: int = 18) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QPen(color, 2.2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        x = size // 2
        if descending:
            painter.drawLine(x, 4, x, size - 5)
            painter.drawLine(x, size - 5, x - 5, size - 10)
            painter.drawLine(x, size - 5, x + 5, size - 10)
        else:
            painter.drawLine(x, size - 4, x, 5)
            painter.drawLine(x, 5, x - 5, 10)
            painter.drawLine(x, 5, x + 5, 10)
        painter.end()
        return QtGui.QIcon(pixmap)


    class ModTableModel(QtCore.QAbstractTableModel):
        HEADERS = ("", "Name", "Label", "Last managed")

        def __init__(self, accent_color: QtGui.QColor | None = None, parent=None):
            super().__init__(parent)
            self.mods: list[ModItem] = []
            self.labels: dict[str, str] = {}
            self.records: dict[str, dict] = {}
            accent = accent_color or _accent_color()
            self._installed_icon = _check_icon(accent)
            self._empty_icon = _check_icon(accent, transparent=True)

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
            if role == QtCore.Qt.DecorationRole and index.column() == 0:
                return self._installed_icon if mod.installed else self._empty_icon
            if role == QtCore.Qt.TextAlignmentRole and index.column() == 0:
                return QtCore.Qt.AlignCenter
            if role == QtCore.Qt.DisplayRole:
                if index.column() == 0:
                    return ""
                if index.column() == 1:
                    return mod.name
                if index.column() == 2:
                    return label
                return last
            return None


    class PresetTableModel(QtCore.QAbstractTableModel):
        HEADERS = ("Preset", "State", "Mods", "Last managed")

        def __init__(self, parent=None):
            super().__init__(parent)
            self.presets: dict[str, list[str]] = {}
            self.keys: list[str] = []
            self.records: dict[str, dict] = {}
            self.installed: set[str] = set()
            self._active_icon = self._state_icon(True)
            self._inactive_icon = self._state_icon(False)

        def set_data(self, presets: dict, keys: list[str], records: dict, installed: set[str] | None = None) -> None:
            self.beginResetModel()
            self.presets = dict(presets or {})
            self.keys = list(keys or [])
            self.records = dict(records or {})
            self.installed = set(installed or set())
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
            if not index.isValid():
                return None
            name = self.keys[index.row()]
            mods = self.presets.get(name, [])
            active = bool(mods) and all(mod_name in self.installed for mod_name in mods)
            if role == QtCore.Qt.UserRole and index.column() == 1:
                return "active" if active else "inactive"
            if role == QtCore.Qt.DecorationRole and index.column() == 1:
                return self._active_icon if active else self._inactive_icon
            if role == QtCore.Qt.TextAlignmentRole and index.column() == 1:
                return QtCore.Qt.AlignCenter
            if role != QtCore.Qt.DisplayRole:
                return None
            rec = self.records.get(name, {})
            values = (name, "", str(len(mods)), rec.get("last_managed") or "-")
            return values[index.column()]

        def _state_icon(self, active: bool) -> QtGui.QIcon:
            pixmap = QtGui.QPixmap(18, 18)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            pen = QtGui.QPen(QtGui.QColor("#16a34a" if active else "#dc2626"), 2.6, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
            painter.setPen(pen)
            if active:
                path = QtGui.QPainterPath()
                path.moveTo(4, 9)
                path.lineTo(8, 13)
                path.lineTo(14, 5)
                painter.drawPath(path)
            else:
                painter.drawLine(5, 5, 13, 13)
                painter.drawLine(13, 5, 5, 13)
            painter.end()
            return QtGui.QIcon(pixmap)


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
        def __init__(self, cfg: dict, accent_color: QtGui.QColor | None = None, dark_theme: bool = False, parent=None):
            super().__init__(parent)
            self.cfg = cfg
            self.accent_color = QtGui.QColor(accent_color or _accent_color())
            self.badge_foreground = _readable_on(self.accent_color)
            self.dark_theme = dark_theme
            self._pixmaps: dict[tuple[str, int], QtGui.QPixmap] = {}

        def paint(self, painter, option, index) -> None:
            painter.save()
            mod = index.data(QtCore.Qt.UserRole)
            label = index.model().labels.get(mod.name, "-")
            selected = bool(option.state & QtWidgets.QStyle.State_Selected)
            rect = option.rect.adjusted(6, 6, -6, -6)
            self._draw_acrylic_card(painter, rect, selected)

            image_rect = QtCore.QRect(rect.left() + 8, rect.top() + 8, rect.width() - 16, max(48, rect.width() - 18))
            pixmap = self._pixmap_for(mod, image_rect.size())
            if pixmap.isNull():
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(QtGui.QColor(30, 41, 59, 155) if self.dark_theme else QtGui.QColor(226, 232, 240, 150))
                painter.drawRoundedRect(image_rect, 5, 5)
                painter.setPen(QtGui.QColor("#cbd5e1") if self.dark_theme else QtGui.QColor("#64748b"))
                painter.drawText(image_rect, QtCore.Qt.AlignCenter, "No image")
            else:
                painter.save()
                clip = QtGui.QPainterPath()
                clip.addRoundedRect(QtCore.QRectF(image_rect), 5, 5)
                painter.setClipPath(clip)
                painter.drawPixmap(image_rect, pixmap)
                painter.restore()

            accent = self.accent_color
            foreground = self.badge_foreground
            if mod.installed:
                badge = QtCore.QRect(rect.left() + 12, rect.top() + 12, 28, 24)
                self._draw_badge(painter, badge, accent)
                self._draw_badge_check(painter, badge, foreground)
            label_badge_text = self._label_badge_text(label)
            if label_badge_text:
                metrics = painter.fontMetrics()
                badge = self._label_badge_rect(rect, metrics, label_badge_text)
                self._draw_badge(painter, badge, accent)
                painter.setPen(foreground)
                painter.drawText(badge.adjusted(7, 0, -7, 0), QtCore.Qt.AlignCenter, label_badge_text)

            name_badge = self._name_badge_rect(rect, image_rect)
            self._draw_badge(painter, name_badge, accent)
            painter.setPen(foreground)
            painter.drawText(name_badge.adjusted(8, 0, -8, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self._elided_mod_name(painter.fontMetrics(), mod.name, name_badge.width() - 16))
            painter.restore()

        def helpEvent(self, event, view, option, index) -> bool:
            tooltip = self._tooltip_for_pos(option, index, event.pos())
            if tooltip:
                QtWidgets.QToolTip.showText(event.globalPos(), tooltip, view)
                return True
            QtWidgets.QToolTip.hideText()
            return super().helpEvent(event, view, option, index)

        def sizeHint(self, option, index):
            size = max(96, int(self.cfg.get("tile_size", 140)))
            return QtCore.QSize(size + 28, size + 58)

        def _draw_acrylic_card(self, painter, rect: QtCore.QRect, selected: bool) -> None:
            if self.dark_theme:
                base = QtGui.QColor(30, 64, 175, 170) if selected else QtGui.QColor(30, 41, 59, 188)
                border = QtGui.QColor(96, 165, 250, 205) if selected else QtGui.QColor(148, 163, 184, 112)
                shine = QtGui.QColor(255, 255, 255, 42)
                end = QtGui.QColor(15, 23, 42, 148)
                shadow = QtGui.QColor(0, 0, 0, 72)
            else:
                base = QtGui.QColor(219, 234, 254, 188) if selected else QtGui.QColor(255, 255, 255, 172)
                border = QtGui.QColor(59, 130, 246, 210) if selected else QtGui.QColor(148, 163, 184, 150)
                shine = QtGui.QColor(255, 255, 255, 214)
                end = QtGui.QColor(226, 232, 240, 132)
                shadow = QtGui.QColor(15, 23, 42, 24)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(shadow)
            painter.drawRoundedRect(rect.adjusted(0, 2, 0, 2), 8, 8)
            gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, shine)
            gradient.setColorAt(0.45, base)
            gradient.setColorAt(1, end)
            painter.setBrush(gradient)
            painter.setPen(QtGui.QPen(border))
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 68 if self.dark_theme else 165)))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)

        def _draw_badge(self, painter, rect: QtCore.QRect, color: QtGui.QColor) -> None:
            painter.setBrush(color)
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(rect, 4, 4)

        def _draw_badge_check(self, painter, rect: QtCore.QRect, color: QtGui.QColor) -> None:
            painter.setPen(QtGui.QPen(color, 2.8, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
            path = QtGui.QPainterPath()
            path.moveTo(rect.left() + 7, rect.top() + 12)
            path.lineTo(rect.left() + 12, rect.top() + 17)
            path.lineTo(rect.left() + 21, rect.top() + 7)
            painter.drawPath(path)

        def _label_badge_text(self, label: str) -> str:
            label = (label or "").strip()
            if not label or label == "-":
                return ""
            return label[:8]

        def _elided_mod_name(self, metrics: QtGui.QFontMetrics, name: str, width: int) -> str:
            return metrics.elidedText(str(name or ""), QtCore.Qt.ElideRight, max(1, width))

        def _content_rect(self, option) -> QtCore.QRect:
            return option.rect.adjusted(6, 6, -6, -6)

        def _image_rect(self, rect: QtCore.QRect) -> QtCore.QRect:
            return QtCore.QRect(rect.left() + 8, rect.top() + 8, rect.width() - 16, max(48, rect.width() - 18))

        def _label_badge_rect(self, rect: QtCore.QRect, metrics: QtGui.QFontMetrics, text: str) -> QtCore.QRect:
            badge_width = min(rect.width() - 24, max(34, metrics.horizontalAdvance(text) + 14))
            return QtCore.QRect(rect.right() - 12 - badge_width, rect.top() + 12, badge_width, 24)

        def _name_badge_rect(self, rect: QtCore.QRect, image_rect: QtCore.QRect) -> QtCore.QRect:
            return QtCore.QRect(rect.left() + 8, image_rect.bottom() + 8, rect.width() - 16, 24)

        def _tooltip_for_pos(self, option, index, pos: QtCore.QPoint) -> str:
            mod = index.data(QtCore.Qt.UserRole)
            if mod is None:
                return ""
            metrics = QtGui.QFontMetrics(option.font)
            rect = self._content_rect(option)
            image_rect = self._image_rect(rect)
            label = (index.model().labels.get(mod.name, "") or "").strip()
            label_badge_text = self._label_badge_text(label)
            if label_badge_text:
                label_badge = self._label_badge_rect(rect, metrics, label_badge_text)
                if label_badge.contains(pos) and label != label_badge_text:
                    return label
            name_badge = self._name_badge_rect(rect, image_rect)
            if name_badge.contains(pos):
                elided = self._elided_mod_name(metrics, mod.name, name_badge.width() - 16)
                if elided != mod.name:
                    return mod.name
            return ""

        def _label_for_pos(self, option, index, pos: QtCore.QPoint) -> str:
            mod = index.data(QtCore.Qt.UserRole)
            if mod is None:
                return ""
            label = (index.model().labels.get(mod.name, "") or "").strip()
            label_badge_text = self._label_badge_text(label)
            if not label_badge_text:
                return ""
            rect = self._content_rect(option)
            metrics = QtGui.QFontMetrics(option.font)
            return label if self._label_badge_rect(rect, metrics, label_badge_text).contains(pos) else ""

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
            self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
            self.cfg = normalize_game_profiles(load_config())
            self._applying_theme = False
            self._init_theme()
            self.resize(max(880, int(self.cfg.get("window_width", 1200))), max(560, int(self.cfg.get("window_height", 750))))
            self.setMinimumSize(880, 560)
            self.setAcceptDrops(True)

            self.mod_page = _Var(1)
            self.preset_page = _Var(1)
            self.search_var = _Var("")
            self.label_filter_var = _Var("")
            self.label_edit_var = _Var("")
            self.order_var = _Var(self._mod_order_label_from_config())
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
            self.mod_sort_key = self._mod_order_options().get(self.order_var.get(), self._normalize_mod_sort_key(self.cfg.get("mod_sort_key", "default")))
            self.mod_sort_reverse = bool(self.cfg.get("mod_sort_reverse", False))
            self.preset_sort_key = self.cfg.get("preset_sort_key", "name")
            self.preset_sort_reverse = bool(self.cfg.get("preset_sort_reverse", False))
            self._pool = WorkerPool()
            self._poll_timer = QtCore.QTimer(self)
            self._poll_timer.timeout.connect(self._poll_workers)

            self._build()
            self._setup_com_drop_targets()
            self._bind_navigation_events()
            self.refresh_all()

        def _setup_com_drop_targets(self) -> None:
            from .platform_utils import is_windows
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
            self._pool.shutdown()
            for attr in ("_table_drop_target", "_tiles_drop_target"):
                target = getattr(self, attr, None)
                if target is not None:
                    target.disable()
            super().closeEvent(event)

        def changeEvent(self, event) -> None:
            super().changeEvent(event)

        def _init_theme(self) -> None:
            app = QtWidgets.QApplication.instance()
            mode = str(self.cfg.get("gui_theme", "system") or "system").lower()
            if mode not in {"system", "light", "dark"}:
                mode = "system"
            if not hasattr(self, "_system_palette"):
                self._system_palette = QtGui.QPalette(app.palette() if app else self.palette())
            source = QtGui.QPalette(self._system_palette)
            palette = _fixed_theme_palette(mode, source)
            custom_accent = _custom_accent_color(self.cfg)
            if custom_accent is not None:
                palette.setColor(QtGui.QPalette.Highlight, custom_accent)
                palette.setColor(QtGui.QPalette.HighlightedText, _readable_on(custom_accent))
            custom_text = _custom_text_color(self.cfg)
            if custom_text is not None:
                for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.ToolTipText):
                    palette.setColor(role, custom_text)
            if app:
                app.setPalette(palette)
            self.setPalette(palette)
            self._theme_mode = mode
            self._theme_is_dark = _is_dark_palette(palette)
            accent = palette.color(QtGui.QPalette.Highlight)
            self._theme_accent = accent if accent.isValid() else QtGui.QColor("#2563eb")
            self._theme_button_text = palette.color(QtGui.QPalette.ButtonText)

        def _refresh_theme(self) -> None:
            self._applying_theme = True
            try:
                self._init_theme()
                self._apply_button_style()
                accent = self._theme_accent
                self.mods_model._installed_icon = _check_icon(accent)
                self.mods_model._empty_icon = _check_icon(accent, transparent=True)
                self.mods_model.layoutChanged.emit()
                self.tile_delegate.accent_color = QtGui.QColor(accent)
                self.tile_delegate.badge_foreground = _readable_on(accent)
                self.tile_delegate.dark_theme = self._theme_is_dark
                self.tiles_view.viewport().update()
                self._update_mod_order_direction_button()
                if hasattr(self, "_settings_form"):
                    self._update_theme_preview()
                palette = self.palette()
                ss = getattr(self, "_theme_stylesheet", "")
                for attr in ("games_dialog", "presets_dialog", "settings_dialog", "broken_dialog"):
                    dialog = getattr(self, attr, None)
                    if dialog:
                        if ss:
                            dialog.setStyleSheet(ss)
                        dialog.setPalette(palette)
                        dialog.update()
                self.update()
            finally:
                self._applying_theme = False

        def _on_system_appearance_changed(self, *_args) -> None:
            if self._applying_theme:
                return
            app = QtWidgets.QApplication.instance()
            if app:
                self._system_palette = QtGui.QPalette(app.palette())
            self._refresh_theme()

        def _setup_filter_box(self, box: QtWidgets.QComboBox) -> None:
            box.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
            completer = box.completer()
            completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
            completer.setFilterMode(QtCore.Qt.MatchContains)
            completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)

        def _filter_box_for_object(self, obj) -> QtWidgets.QComboBox | None:
            for box in getattr(self, "filter_boxes", ()):
                completer = box.completer()
                if obj is box.lineEdit() or (completer is not None and obj is completer.popup()):
                    return box
            return None

        def _complete_filter_box(self, box: QtWidgets.QComboBox) -> bool:
            completer = box.completer()
            text = box.lineEdit().text()
            if completer is None or not text:
                return False
            popup = completer.popup()
            index = popup.currentIndex() if popup is not None else None
            completion = index.data() if index is not None and index.isValid() else None
            if not completion:
                completer.setCompletionPrefix(text)
                completion = completer.currentCompletion()
            if not completion:
                return False
            box.lineEdit().setText(completion)
            if popup is not None:
                popup.hide()
            return True

        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Tab:
                box = self._filter_box_for_object(obj)
                if box is not None and self._complete_filter_box(box):
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
            self._build_menu()
            self._build_games_page()
            self._build_mods()
            self._build_presets()
            self._build_settings()
            self._build_broken()
            self._show_start_page()

        def _apply_button_style(self) -> None:
            if self._theme_is_dark:
                window_bg = "#202124"
                normal_bg = "rgba(255, 255, 255, 22)"
                hover_bg = "rgba(255, 255, 255, 38)"
                pressed_bg = "rgba(255, 255, 255, 55)"
                disabled_bg = "rgba(255, 255, 255, 10)"
                btn_text = "#f2f2f5"
                input_bg = "#2d2d30"
                input_border = "#3f3f42"
                input_focus_border = "#6b6a7c"
                input_text = "#f2f2f5"
                combo_bg = "#626071"
                combo_hover_bg = "#716f82"
                combo_focus_bg = "#78758a"
                combo_list_bg = "#2d2d30"
                combo_list_border = "#56565c"
                menu_bg = "#2d2d30"
                menu_border = "#3f3f42"
                menu_selected_bg = "#626071"
            else:
                window_bg = "#f8fafc"
                normal_bg = "rgba(0, 0, 0, 35)"
                hover_bg = "rgba(0, 0, 0, 55)"
                pressed_bg = "rgba(0, 0, 0, 75)"
                disabled_bg = "rgba(0, 0, 0, 15)"
                btn_text = "#111827"
                input_bg = "#f4f4f5"
                input_border = "#d4d4d8"
                input_focus_border = "#9291a5"
                input_text = "#111827"
                combo_bg = "#e4e4e7"
                combo_hover_bg = "#d4d4d8"
                combo_focus_bg = "#c4c4ca"
                combo_list_bg = "#ffffff"
                combo_list_border = "#d4d4d8"
                menu_bg = "#ffffff"
                menu_border = "#d4d4d8"
                menu_selected_bg = "#e4e4e7"
            accent = self._theme_accent
            stylesheet = f"""
                QMainWindow, QDialog {{
                    background-color: {window_bg};
                }}
                QPushButton[variant="acrylic"] {{
                    background-color: {normal_bg};
                    border: none;
                    border-radius: 8px;
                    padding: 6px 10px;
                    color: {btn_text};
                }}
                QPushButton[variant="acrylic"]:hover {{
                    background-color: {hover_bg};
                }}
                QPushButton[variant="acrylic"]:pressed {{
                    background-color: {pressed_bg};
                }}
                QPushButton[variant="acrylic"]:checked {{
                    background-color: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 84);
                    border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 150);
                }}
                QPushButton[variant="acrylic"]:disabled {{
                    background-color: {disabled_bg};
                }}
                QLineEdit {{
                    background: {input_bg};
                    border: 1px solid {input_border};
                    border-radius: 4px;
                    color: {input_text};
                    padding: 4px 8px;
                }}
                QLineEdit:focus {{
                    border-color: {input_focus_border};
                }}
                QComboBox {{
                    background: {combo_bg};
                    border: 0;
                    border-radius: 7px;
                    color: {input_text};
                    padding: 5px 20px 5px 9px;
                }}
                QComboBox:hover {{
                    background: {combo_hover_bg};
                }}
                QComboBox:focus {{
                    background: {combo_focus_bg};
                }}
                QComboBox::drop-down {{
                    border: 0;
                    width: 18px;
                }}
                QComboBox QAbstractItemView {{
                    background: {combo_list_bg};
                    border: 1px solid {combo_list_border};
                    color: {input_text};
                    selection-background-color: {combo_bg};
                }}
                QComboBox QLineEdit {{
                    background: transparent;
                    border: none;
                    border-radius: 0;
                    padding: 0 2px;
                    color: {input_text};
                }}
                QMenuBar {{
                    background-color: {window_bg};
                    color: {btn_text};
                }}
                QMenuBar::item {{
                    padding: 4px 8px;
                    background: transparent;
                    border-radius: 4px;
                }}
                QMenuBar::item:selected, QMenuBar::item:pressed {{
                    background: {menu_selected_bg};
                }}
                QMenu {{
                    background: {menu_bg};
                    border: 1px solid {menu_border};
                    color: {input_text};
                    padding: 4px 0;
                }}
                QMenu::item {{
                    padding: 6px 24px 6px 12px;
                    margin: 0 4px;
                    border-radius: 4px;
                }}
                QMenu::item:selected {{
                    background: {menu_selected_bg};
                }}
            """
            self._theme_stylesheet = stylesheet
            self.setStyleSheet(stylesheet)

        def _build_menu(self) -> None:
            manage = self.menuBar().addMenu("Manage")
            games = manage.addAction(self._icon("menu"), "Games")
            games.setToolTip("Manage game profiles")
            games.triggered.connect(self._open_games_dialog)
            presets = manage.addAction(self._icon("save"), "Presets")
            presets.setToolTip("Open presets")
            presets.triggered.connect(self._open_presets_dialog)
            settings = manage.addAction(self._icon("open"), "Settings")
            settings.setToolTip("Open settings")
            settings.triggered.connect(self._open_settings_dialog)
            broken = manage.addAction(self._icon("delete"), "Broken links")
            broken.setToolTip("Open broken links cleanup")
            broken.triggered.connect(self._open_broken_dialog)

        def _build_games_page(self) -> None:
            layout = QtWidgets.QVBoxLayout(self.games_page)
            layout.setContentsMargins(28, 28, 28, 28)
            title = QtWidgets.QLabel("Choose game")
            title_font = title.font()
            title_font.setPointSize(max(title_font.pointSize() + 6, 16))
            title_font.setBold(True)
            title.setFont(title_font)
            layout.addWidget(title)
            self.games_list = QtWidgets.QListWidget()
            self.games_list.itemDoubleClicked.connect(lambda item: self._select_game_profile(item.data(QtCore.Qt.UserRole)))
            layout.addWidget(self.games_list, 1)
            actions = QtWidgets.QHBoxLayout()
            actions.addWidget(self._icon_button("Select", self._select_highlighted_game, "Select highlighted game", "toggle", icon_only=False))
            actions.addWidget(self._icon_button("Add game", self._add_game_profile, "Add a game profile", "add", icon_only=False))
            actions.addWidget(self._icon_button("Edit", self._edit_highlighted_game, "Edit highlighted game profile", "open", icon_only=False))
            actions.addStretch(1)
            layout.addLayout(actions)

            self.games_dialog = self._dialog("Games", 820, 560)
            dialog_layout = QtWidgets.QVBoxLayout(self.games_dialog)
            self.games_dialog_list = QtWidgets.QListWidget()
            self.games_dialog_list.itemDoubleClicked.connect(lambda item: self._select_game_profile(item.data(QtCore.Qt.UserRole)))
            dialog_layout.addWidget(self.games_dialog_list, 1)
            dialog_actions = QtWidgets.QHBoxLayout()
            dialog_actions.addWidget(self._icon_button("Select", self._select_highlighted_game_dialog, "Select highlighted game", "toggle", icon_only=False))
            dialog_actions.addWidget(self._icon_button("Add", self._add_game_profile, "Add a game profile", "add", icon_only=False))
            dialog_actions.addWidget(self._icon_button("Edit", self._edit_highlighted_game_dialog, "Edit highlighted game profile", "open", icon_only=False))
            dialog_actions.addWidget(self._icon_button("Delete", self._delete_highlighted_game_dialog, "Delete highlighted game profile", "delete", icon_only=False))
            dialog_actions.addStretch(1)
            dialog_layout.addLayout(dialog_actions)

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
            profile = active_game_profile(self.cfg)
            if not profile:
                self.game_button.setText("??")
                self.game_button.setToolTip("Choose game")
                return
            abbr = game_abbreviation(profile.get("name", ""))
            self.game_button.setText(abbr)
            self.game_button.setToolTip(f"{profile.get('name', 'Game')} - manage game profiles")

        def _refresh_games_lists(self) -> None:
            profiles = self.cfg.get("game_profiles", []) or []
            active_id = self.cfg.get("active_game_profile_id", "")
            for list_widget in [getattr(self, "games_list", None), getattr(self, "games_dialog_list", None)]:
                if list_widget is None:
                    continue
                list_widget.clear()
                for profile in profiles:
                    mark = " *" if profile.get("id") == active_id else ""
                    item = QtWidgets.QListWidgetItem(f"{game_abbreviation(profile.get('name', ''))}  {profile.get('name', 'Game')}{mark}")
                    item.setData(QtCore.Qt.UserRole, profile.get("id", ""))
                    list_widget.addItem(item)
                if list_widget.count():
                    list_widget.setCurrentRow(0)
            self._update_game_button()

        def _highlighted_game_id(self, list_widget: QtWidgets.QListWidget) -> str:
            item = list_widget.currentItem()
            return str(item.data(QtCore.Qt.UserRole) or "") if item else ""

        def _select_highlighted_game(self) -> None:
            self._select_game_profile(self._highlighted_game_id(self.games_list))

        def _select_highlighted_game_dialog(self) -> None:
            self._select_game_profile(self._highlighted_game_id(self.games_dialog_list))

        def _edit_highlighted_game(self) -> None:
            self._edit_game_profile(self._highlighted_game_id(self.games_list))

        def _edit_highlighted_game_dialog(self) -> None:
            self._edit_game_profile(self._highlighted_game_id(self.games_dialog_list))

        def _delete_highlighted_game_dialog(self) -> None:
            profile_id = self._highlighted_game_id(self.games_dialog_list)
            if not profile_id:
                return
            if QtWidgets.QMessageBox.question(self, "Delete game", "Delete selected game profile?") != QtWidgets.QMessageBox.Yes:
                return
            if delete_game_profile(self.cfg, profile_id):
                save_config(self.cfg)
                self.cfg = load_config()
                self._refresh_games_lists()
                self._show_start_page()
                self.refresh_all()

        def _select_game_profile(self, profile_id: str) -> None:
            if not profile_id:
                return
            if set_active_game_profile(self.cfg, profile_id):
                save_config(self.cfg)
                self.cfg = load_config()
                self.tile_delegate.cfg = self.cfg
                self._refresh_games_lists()
                self._set_main_page(self.mods_tab)
                self.refresh_all()
                self._close_dialog(self.games_dialog)

        def _add_game_profile(self) -> None:
            values = self._game_profile_values()
            if not values:
                return
            create_game_profile(values.pop("name"), values, self.cfg)
            save_config(self.cfg)
            self.cfg = load_config()
            self.tile_delegate.cfg = self.cfg
            self._refresh_games_lists()
            self._set_main_page(self.mods_tab)
            self.refresh_all()

        def _edit_game_profile(self, profile_id: str) -> None:
            profile = next((p for p in self.cfg.get("game_profiles", []) if p.get("id") == profile_id), None)
            if not profile:
                return
            values = self._game_profile_values(profile)
            if not values:
                return
            update_game_profile(self.cfg, profile_id, values)
            save_config(self.cfg)
            self.cfg = load_config()
            self.tile_delegate.cfg = self.cfg
            self._refresh_games_lists()
            self.refresh_all()

        def _game_profile_values(self, profile: dict | None = None) -> dict | None:
            profile = profile or {}
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("Game profile")
            layout = QtWidgets.QFormLayout(dialog)
            widgets: dict[str, QtWidgets.QWidget] = {}
            fields = [("name", "Game name"), *[(key, key) for key in GAME_PROFILE_KEYS if key != "mod_recursive_scan"]]
            for key, label in fields:
                edit = QtWidgets.QLineEdit(str(profile.get(key, "")))
                edit.setMinimumWidth(420)
                widgets[key] = edit
                row = QtWidgets.QHBoxLayout()
                row.addWidget(edit, 1)
                if key in {"game_mods_dir", "mods_source_dir"}:
                    browse = QtWidgets.QPushButton("")
                    browse.setIcon(self._icon("folder"))
                    browse.setToolTip(f"Browse for {key}")
                    browse.clicked.connect(lambda _checked=False, e=edit, k=key: self._browse_game_profile_path(e, k))
                    row.addWidget(browse)
                if key == "mod_extensions":
                    edit.setToolTip(
                        "Comma-separated extensions, e.g. .pak,.utoc\n"
                        "Add 'folders' to also treat subfolders as mods."
                    )
                    recursive = QtWidgets.QCheckBox("Recursive")
                    recursive.setToolTip("Scan subfolders of the source directory for matching mods")
                    recursive.setChecked(bool(profile.get("mod_recursive_scan")))
                    widgets["mod_recursive_scan"] = recursive
                    row.addWidget(recursive)
                layout.addRow(label, row)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addRow(buttons)
            if dialog.exec() != QtWidgets.QDialog.Accepted:
                return None
            values = {}
            for key, widget in widgets.items():
                if isinstance(widget, QtWidgets.QCheckBox):
                    values[key] = widget.isChecked()
                else:
                    values[key] = widget.text().strip()
            if not values["name"]:
                QtWidgets.QMessageBox.critical(self, "Game profile", "Enter game name.")
                return None
            return values

        def _browse_game_profile_path(self, edit: QtWidgets.QLineEdit, key: str) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, key)
            if path:
                edit.setText(path)

        def _button(self, text: str, command: Callable, tooltip: str = ""):
            button = QtWidgets.QPushButton(text)
            button.setProperty("variant", "acrylic")
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
            button.setProperty("variant", "acrylic")
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

        def _mod_order_options(self) -> dict[str, str]:
            return {
                "Default": "default",
                "Created date": "created_date",
                "Last managed": "last_managed",
                "Label": "label",
                "Name": "name",
                "Installed": "installed",
            }

        def _normalize_mod_sort_key(self, key: str) -> str:
            aliases = {"d": "default", "Default": "default", "Default (name without prefix)": "default", "Created date": "created_date", "cd": "created_date", "created date": "created_date"}
            key = aliases.get(key, key)
            return key if key in set(self._mod_order_options().values()) else "default"

        def _mod_order_label_for_key(self, key: str) -> str:
            key = self._normalize_mod_sort_key(key)
            for label, value in self._mod_order_options().items():
                if value == key:
                    return label
            return "Default"

        def _mod_order_label_from_config(self) -> str:
            key = self._normalize_mod_sort_key(self.cfg.get("mod_sort_key", "default"))
            if key == "default":
                key = self._normalize_mod_sort_key(self.cfg.get("order_var", "default"))
            return self._mod_order_label_for_key(key)

        def _build_mods(self) -> None:
            layout = QtWidgets.QVBoxLayout(self.mods_tab)
            top = QtWidgets.QHBoxLayout()
            self.game_button = self._icon_button("Game", self._open_games_dialog, "Manage and switch game profiles", "menu", icon_only=False)
            self.game_button.setMinimumWidth(48)
            self.search_box = QtWidgets.QComboBox()
            self.search_box.setEditable(True)
            self.search_box.lineEdit().setPlaceholderText("Search")
            self.search_box.lineEdit().returnPressed.connect(self._mods_search)
            self.label_filter_box = QtWidgets.QComboBox()
            self.label_filter_box.setEditable(True)
            self.label_filter_box.lineEdit().setPlaceholderText("Label")
            self.label_filter_box.lineEdit().returnPressed.connect(self._mods_search)
            self.filter_boxes = (self.search_box, self.label_filter_box)
            for box in self.filter_boxes:
                self._setup_filter_box(box)
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
            self.order_box.addItems(list(self._mod_order_options().keys()))
            self.order_box.setCurrentText(self._mod_order_label_for_key(self.mod_sort_key))
            self.order_box.activated.connect(self._activate_mod_order)
            self.order_direction_button = QtWidgets.QPushButton("")
            self.order_direction_button.setProperty("variant", "acrylic")
            self.order_direction_button.setFixedSize(32, 32)
            self.order_direction_button.setIconSize(QtCore.QSize(18, 18))
            self.order_direction_button.clicked.connect(self._toggle_mod_order_direction)
            self.action_widgets.append(self.order_direction_button)
            self._update_mod_order_direction_button()
            top.addWidget(self.game_button)
            top.addWidget(self.search_box, 2)
            top.addWidget(self.label_filter_box, 1)
            top.addWidget(self._icon_button("Search", self._mods_search, "Apply search and label filters", "search"))
            top.addWidget(self._icon_button("Clear", self._mods_clear, "Clear search and label filters", "clear"))
            top.addWidget(QtWidgets.QLabel("Order"))
            top.addWidget(self.order_box)
            top.addWidget(self.order_direction_button)
            top.addWidget(QtWidgets.QLabel("View"))
            top.addWidget(self.view_list_button)
            top.addWidget(self.view_tiles_button)
            top.addWidget(self.manage_button)
            layout.addLayout(top)

            self.mods_model = ModTableModel(self._theme_accent, self)
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
            mods_header.setSectionsClickable(True)
            mods_header.setHighlightSections(False)
            mods_header.sectionClicked.connect(self._sort_mods_by_section)
            mods_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
            mods_header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
            mods_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
            mods_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
            self.mods_table.verticalHeader().setVisible(False)
            self.mods_table.doubleClicked.connect(lambda _idx: self._toggle_selected_mods())
            self.mods_table.selectionModel().selectionChanged.connect(lambda _a, _b: self._on_mod_selection_changed())

            self.tile_delegate = TileDelegate(self.cfg, self._theme_accent, self._theme_is_dark, self)
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
            presets_header = self.presets_table.horizontalHeader()
            presets_header.setStretchLastSection(False)
            presets_header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            presets_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
            presets_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
            presets_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
            presets_header.setHighlightSections(False)
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
                "page_size",
                "max_mod_name_len",
                "max_preset_name_len",
                "max_label_name_len",
                "gui_theme",
                "gui_accent_color_mode",
                "gui_accent_color",
                "gui_text_color_mode",
                "gui_text_color",
                "gui_font_family",
                "gui_font_size",
                "ui_scale_percent",
                "placeholder_image_col_width",
                "mod_view_mode",
                "tile_size",
            ]
            self.setting_widgets: dict[str, QtWidgets.QWidget] = {}
            for key in GAME_PROFILE_KEYS:
                if key == "mod_recursive_scan":
                    widget = QtWidgets.QCheckBox()
                    widget.setChecked(bool(self.cfg.get(key)))
                else:
                    widget = QtWidgets.QLineEdit(str(self.cfg.get(key, "")))
                    widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                self.setting_widgets[key] = widget
            for key in keys:
                value = self.cfg.get(key, "")
                self.setting_vars[key] = _Var(str(value))
                widget = self._create_setting_widget(key, value)
                self.setting_widgets[key] = widget
                self._add_setting_row(form, key, widget)

            self.accent_preview_badge = QtWidgets.QToolButton()
            self.accent_preview_badge.setAutoRaise(True)
            self.accent_preview_badge.setIconSize(QtCore.QSize(22, 22))
            self.accent_preview_badge.setCursor(QtCore.Qt.PointingHandCursor)
            self.accent_preview_badge.setToolTip("Click to toggle accent color mode")
            self.accent_preview_badge.clicked.connect(self._toggle_accent_color_mode)
            self.accent_preview_button = QtWidgets.QPushButton("Active")
            self.accent_preview_button.setEnabled(False)
            self.text_preview_badge = QtWidgets.QToolButton()
            self.text_preview_badge.setText("Aa")
            self.text_preview_badge.setAutoRaise(True)
            self.text_preview_badge.setCursor(QtCore.Qt.PointingHandCursor)
            self.text_preview_badge.setToolTip("Click to toggle text color mode")
            self.text_preview_badge.clicked.connect(self._toggle_text_color_mode)
            preview_row = QtWidgets.QHBoxLayout()
            preview_row.addWidget(self.accent_preview_badge)
            preview_row.addWidget(self.accent_preview_button)
            preview_row.addWidget(self.text_preview_badge)
            preview_row.addStretch(1)
            form.addRow("Theme preview", preview_row)

            self._settings_form = form
            self.setting_widgets["gui_accent_color_mode"].currentTextChanged.connect(self._on_accent_settings_changed)
            self.setting_widgets["gui_text_color_mode"].currentTextChanged.connect(self._on_text_settings_changed)
            self._update_accent_color_row_visibility()
            self._update_text_color_row_visibility()
            self._update_theme_preview()

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

        def _create_setting_widget(self, key: str, value) -> QtWidgets.QWidget:
            _COMBO_OPTS: dict[str, tuple] = {
                "mod_view_mode": (["list", "tiles"], "list"),
                "gui_theme": (["system", "light", "dark"], "system"),
                "gui_accent_color_mode": (["system", "custom"], "system"),
                "gui_text_color_mode": (["system", "custom"], "system"),
            }
            if key in _COMBO_OPTS:
                items, default = _COMBO_OPTS[key]
                widget = QtWidgets.QComboBox()
                widget.addItems(items)
                widget.setCurrentText(str(value or default))
            elif key == "gui_font_family":
                widget = QtWidgets.QComboBox()
                widget.addItem("")
                widget.addItems(self._system_font_families())
                if value and widget.findText(str(value)) < 0:
                    widget.addItem(str(value))
                widget.setCurrentText(str(value or ""))
            elif key == "gui_accent_color":
                widget = QtWidgets.QLineEdit(str(value or "#2563eb"))
                widget.setReadOnly(True)
            elif key == "gui_text_color":
                widget = QtWidgets.QLineEdit(str(value or "#111827"))
                widget.setReadOnly(True)
            else:
                widget = QtWidgets.QLineEdit(str(value))
            widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            return widget

        def _add_setting_row(self, form: QtWidgets.QFormLayout, key: str, widget: QtWidgets.QWidget) -> None:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(widget, 1)
            if key in {"game_mods_dir", "mods_source_dir"}:
                row.addWidget(self._icon_button("Browse", lambda _checked=False, k=key: self._browse_setting(k), f"Browse for {key}", "folder"))
            if key == "gui_accent_color":
                row.addWidget(self._icon_button("Choose", self._choose_accent_color, "Choose accent color", "image"))
                self.accent_color_row = QtWidgets.QWidget()
                self.accent_color_row.setLayout(row)
                form.addRow(key, self.accent_color_row)
            elif key == "gui_text_color":
                row.addWidget(self._icon_button("Choose", self._choose_text_color, "Choose text color", "image"))
                self.text_color_row = QtWidgets.QWidget()
                self.text_color_row.setLayout(row)
                form.addRow(key, self.text_color_row)
            else:
                form.addRow(key, row)

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
            key = self._normalize_mod_sort_key(self.mod_sort_key)
            return f"-{key}" if self.mod_sort_reverse else key

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

        def _on_mod_view_mode_changed(self) -> None:
            self._set_view_mode(self.mod_view_mode.get())

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
            keys = {0: "installed", 1: "name", 2: "label", 3: "last_managed"}
            key = keys.get(section)
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
            installed = {mod.name for mod in list_installed_mods(self.cfg)}
            self.preset_page.set(page)
            selection = self.presets_table.selectionModel()
            blocker = QtCore.QSignalBlocker(selection) if selection else None
            self.presets_table.setUpdatesEnabled(False)
            try:
                self.presets_model.set_data(presets, page_keys, presets_records(), installed)
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
            names = self._selected_preset_names()
            installed = {m.name for m in list_installed_mods(self.cfg)}

            def done(result):
                message, _messages, _has_errors = result
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                self.refresh_mods()
                self.refresh_presets()
                self._close_dialog(self.presets_dialog)

            self._run_action("Toggling presets...", lambda: toggle_presets_by_names(self.cfg, names, installed), done)

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
                self.status_var.set(message)
                self.statusBar().showMessage(message)
                self.refresh_presets()

            self._run_action("Deleting presets...", lambda: delete_presets_by_names(names), done)

        def _selected_preset_names(self) -> list[str]:
            return [
                self.presets_model.keys[row]
                for row in self._selected_rows(self.presets_table)
                if row < len(self.presets_model.keys)
            ]

        def _browse_setting(self, key: str) -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(self, key)
            if path:
                widget = self.setting_widgets.get(key)
                if isinstance(widget, QtWidgets.QLineEdit):
                    widget.setText(path)

        def _choose_accent_color(self) -> None:
            current = QtGui.QColor(self.setting_widgets["gui_accent_color"].text())
            if not current.isValid():
                current = self._theme_accent
            color = QtWidgets.QColorDialog.getColor(current, self.settings_dialog, "Choose accent color")
            if color.isValid():
                self.setting_widgets["gui_accent_color"].setText(color.name())
                self._update_theme_preview()

        def _on_accent_settings_changed(self, _text: str = "") -> None:
            self._update_accent_color_row_visibility()
            self._update_theme_preview()

        def _toggle_accent_color_mode(self) -> None:
            combo = self.setting_widgets["gui_accent_color_mode"]
            new_mode = "custom" if combo.currentText() == "system" else "system"
            combo.setCurrentText(new_mode)

        def _update_accent_color_row_visibility(self) -> None:
            is_custom = self.setting_widgets["gui_accent_color_mode"].currentText() == "custom"
            self._settings_form.setRowVisible(self.accent_color_row, is_custom)

        def _settings_accent_color(self) -> QtGui.QColor:
            if self.setting_widgets["gui_accent_color_mode"].currentText() == "custom":
                color = QtGui.QColor(self.setting_widgets["gui_accent_color"].text())
                if color.isValid():
                    return color
            return self._theme_accent

        def _choose_text_color(self) -> None:
            current = QtGui.QColor(self.setting_widgets["gui_text_color"].text())
            if not current.isValid():
                current = self._theme_button_text
            color = QtWidgets.QColorDialog.getColor(current, self.settings_dialog, "Choose text color")
            if color.isValid():
                self.setting_widgets["gui_text_color"].setText(color.name())
                self._update_theme_preview()

        def _on_text_settings_changed(self, _text: str = "") -> None:
            self._update_text_color_row_visibility()
            self._update_theme_preview()

        def _toggle_text_color_mode(self) -> None:
            combo = self.setting_widgets["gui_text_color_mode"]
            new_mode = "custom" if combo.currentText() == "system" else "system"
            combo.setCurrentText(new_mode)

        def _update_text_color_row_visibility(self) -> None:
            is_custom = self.setting_widgets["gui_text_color_mode"].currentText() == "custom"
            self._settings_form.setRowVisible(self.text_color_row, is_custom)

        def _settings_text_color(self) -> QtGui.QColor:
            if self.setting_widgets["gui_text_color_mode"].currentText() == "custom":
                color = QtGui.QColor(self.setting_widgets["gui_text_color"].text())
                if color.isValid():
                    return color
            return self._theme_button_text

        def _update_theme_preview(self) -> None:
            accent = self._settings_accent_color()
            text = self._settings_text_color()
            self.accent_preview_badge.setIcon(_check_icon(accent, size=22))
            self.accent_preview_button.setStyleSheet(
                f"background-color: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 84);"
                f"border: 1px solid rgba({accent.red()}, {accent.green()}, {accent.blue()}, 150);"
                f"border-radius: 8px; padding: 6px 10px; color: {text.name()};"
            )
            self.text_preview_badge.setStyleSheet(f"color: {text.name()}; font-weight: 600;")

        def _save_settings(self) -> None:
            old_theme_settings = (
                str(self.cfg.get("gui_theme", "system") or "system"),
                str(self.cfg.get("gui_accent_color_mode", "system") or "system"),
                str(self.cfg.get("gui_accent_color") or "#2563eb"),
                str(self.cfg.get("gui_text_color_mode", "system") or "system"),
                str(self.cfg.get("gui_text_color") or "#111827"),
            )
            values = {}
            for key, widget in self.setting_widgets.items():
                if isinstance(widget, QtWidgets.QComboBox):
                    values[key] = widget.currentText()
                elif isinstance(widget, QtWidgets.QCheckBox):
                    values[key] = widget.isChecked()
                else:
                    values[key] = widget.text()

            def done(new_cfg):
                self.cfg = new_cfg
                self.mod_view_mode.set(self.cfg.get("mod_view_mode", "list"))
                self._show_mod_view()
                new_theme_settings = (
                    str(self.cfg.get("gui_theme", "system") or "system"),
                    str(self.cfg.get("gui_accent_color_mode", "system") or "system"),
                    str(self.cfg.get("gui_accent_color") or "#2563eb"),
                    str(self.cfg.get("gui_text_color_mode", "system") or "system"),
                    str(self.cfg.get("gui_text_color") or "#111827"),
                )
                if old_theme_settings != new_theme_settings:
                    self._refresh_theme()
                message = "Settings saved."
                self.status_var.set(message)
                self.statusBar().showMessage(message)
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


def _app_icon() -> "QtGui.QIcon | None":
    icon_path = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    if not icon_path.exists():
        return None
    return QtGui.QIcon(str(icon_path))


def run_gui() -> int:
    if QtWidgets is None:
        print("PySide6 is required for the GUI. Install dependencies with: pip install -r requirements.txt")
        return 2
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    icon = _app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    window = ModManagerGui()
    if icon is not None:
        window.setWindowIcon(icon)
    window.show()
    return app.exec()


def qt_available() -> bool:
    return importlib.util.find_spec("PySide6") is not None
