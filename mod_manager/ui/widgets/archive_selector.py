from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ..theme import tokens


class ArchiveNameModel(QtCore.QStringListModel):
    def data(self, index, role=QtCore.Qt.DisplayRole):
        if role in (QtCore.Qt.ToolTipRole, QtCore.Qt.AccessibleTextRole):
            role = QtCore.Qt.DisplayRole
        return super().data(index, role)


class ArchiveSelectorDelegate(QtWidgets.QStyledItemDelegate):
    def sizeHint(self, option, index):
        view = self.parent()
        count = max(1, index.model().rowCount())
        width, remainder = divmod(view.viewport().width(), count)
        minimum = tokens.ARCHIVE_SWITCHER_MIN_WIDTH + tokens.SPACE_XS * 2
        if width < minimum:
            width = minimum
        elif index.row() < remainder:
            width += 1
        return QtCore.QSize(width, view.item_height())

    def paint(self, painter, option, index) -> None:
        view = self.parent()
        styled = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.rect = option.rect.adjusted(tokens.SPACE_XS, 0, -tokens.SPACE_XS, 0)
        styled.text = view.display_text(index)
        styled.displayAlignment = QtCore.Qt.AlignCenter
        if index == view.pressed_index and option.state & QtWidgets.QStyle.State_MouseOver:
            styled.state |= QtWidgets.QStyle.State_Sunken
        view.style().drawControl(QtWidgets.QStyle.CE_ItemViewItem, styled, painter, view)


class ArchiveSelector(QtWidgets.QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("variant", "archiveSelector")
        self.setAccessibleName("Archives")
        self.setFlow(QtWidgets.QListView.LeftToRight)
        self.setWrapping(False)
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setModel(ArchiveNameModel(self))
        self.setItemDelegate(ArchiveSelectorDelegate(self))
        self.pressed_index = QtCore.QModelIndex()
        self._wheel_delta = 0
        self._pixel_delta = 0
        self.model().modelAboutToBeReset.connect(self._clear_pressed)
        self.selectionModel().currentChanged.connect(self._show_current)

    def item_height(self) -> int:
        return max(tokens.ICON_SIZE, self.fontMetrics().height()) + tokens.BUTTON_PADDING[0] * 2

    def _limited_text(self, text: str) -> str:
        if len(text) > tokens.ARCHIVE_NAME_MAX_CHARS:
            return text[:tokens.ARCHIVE_NAME_MAX_CHARS - 1] + "…"
        return text

    def display_text(self, index: QtCore.QModelIndex) -> str:
        width = self.visualRect(index).width() - (tokens.SPACE_XS + tokens.BUTTON_PADDING[1]) * 2
        return self.fontMetrics().elidedText(self._limited_text(index.data()), QtCore.Qt.ElideRight, max(0, width))

    def set_names(self, names: list[str]) -> None:
        self._wheel_delta = self._pixel_delta = 0
        self.model().setStringList(names)
        self.setVisible(len(names) > 1)
        self._relayout()

    def _relayout(self) -> None:
        minimum = tokens.ARCHIVE_SWITCHER_MIN_WIDTH + tokens.SPACE_XS * 2
        overflow = self.model().rowCount() * minimum > self.viewport().width()
        scrollbar = self.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent) if overflow else 0
        self.setFixedHeight(self.item_height() + scrollbar)
        self.doItemsLayout()
        self._show_current()

    def _show_current(self, *_args) -> None:
        if self.currentIndex().isValid():
            self.scrollTo(self.currentIndex(), QtWidgets.QAbstractItemView.EnsureVisible)
            rect = self.visualRect(self.currentIndex())
            scrollbar = self.horizontalScrollBar()
            if rect.right() >= self.viewport().width():
                scrollbar.setValue(scrollbar.value() + rect.right() - self.viewport().width() + 1)
            elif rect.left() < 0:
                scrollbar.setValue(scrollbar.value() + rect.left())

    def _move_current(self, steps: int) -> None:
        count = self.model().rowCount()
        if count:
            row = max(0, min(count - 1, self.currentIndex().row() + steps))
            self.setCurrentIndex(self.model().index(row))
            self._show_current()

    def wheelEvent(self, event) -> None:
        if event.phase() == QtCore.Qt.ScrollBegin:
            self._wheel_delta = self._pixel_delta = 0
        if not event.pixelDelta().isNull():
            delta = event.pixelDelta().y() or event.pixelDelta().x()
            self._pixel_delta += delta
            steps = int(self._pixel_delta / tokens.ARCHIVE_WHEEL_PIXEL_STEP)
            self._pixel_delta -= steps * tokens.ARCHIVE_WHEEL_PIXEL_STEP
        else:
            delta = event.angleDelta().y() or event.angleDelta().x()
            self._wheel_delta += delta
            steps = int(self._wheel_delta / tokens.WHEEL_ANGLE_STEP)
            self._wheel_delta -= steps * tokens.WHEEL_ANGLE_STEP
        if steps:
            self._move_current(-steps)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Right):
            self._move_current(-1 if event.key() == QtCore.Qt.Key_Left else 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.pressed_index = self.indexAt(event.position().toPoint())
            self.viewport().update(self.visualRect(self.pressed_index))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._clear_pressed()
        super().mouseReleaseEvent(event)

    def _clear_pressed(self) -> None:
        previous = self.pressed_index
        self.pressed_index = QtCore.QModelIndex()
        self.viewport().update(self.visualRect(previous))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._relayout()

    def hideEvent(self, event) -> None:
        self._clear_pressed()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.EnabledChange and not self.isEnabled():
            self._clear_pressed()
        elif event.type() in (QtCore.QEvent.FontChange, QtCore.QEvent.StyleChange):
            self._relayout()
