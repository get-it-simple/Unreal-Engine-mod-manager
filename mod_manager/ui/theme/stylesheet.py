from __future__ import annotations

from . import tokens
from .colors import Palette


def build_stylesheet(palette: Palette) -> str:
    button_pad_v, button_pad_h = tokens.BUTTON_PADDING
    field_pad_v, field_pad_h = tokens.FIELD_PADDING
    menubar_pad_v, menubar_pad_h = tokens.MENUBAR_ITEM_PADDING
    menu_top, menu_right, menu_bottom, menu_left = tokens.MENU_ITEM_PADDING
    return f"""
        QMainWindow, QDialog {{
            background-color: {palette.bg};
        }}
        QPushButton[variant="acrylic"], QListView[variant="archiveSelector"]::item {{
            background-color: {palette.button_normal};
            border: none;
            border-radius: {tokens.RADIUS_LG}px;
            color: {palette.control_fg};
        }}
        QPushButton[variant="acrylic"] {{
            padding: {button_pad_v}px {button_pad_h}px;
        }}
        QPushButton[variant="acrylic"]:hover, QListView[variant="archiveSelector"]::item:hover {{
            background-color: {palette.button_hover};
        }}
        QPushButton[variant="acrylic"]:pressed, QListView[variant="archiveSelector"]::item:pressed {{
            background-color: {palette.button_pressed};
        }}
        QPushButton[variant="acrylic"]:checked, QListView[variant="archiveSelector"]::item:selected {{
            background-color: {palette.accent_fill};
            border: {tokens.BORDER_WIDTH}px solid {palette.accent_border};
        }}
        QPushButton[variant="acrylic"]:disabled, QListView[variant="archiveSelector"]::item:disabled {{
            background-color: {palette.button_disabled};
        }}
        QFrame[variant="toolbarSection"] {{
            background-color: {palette.panel};
            border: {tokens.BORDER_WIDTH}px solid {palette.border};
            border-radius: {tokens.RADIUS_MD}px;
        }}
        QLabel[variant="sectionTitle"] {{
            color: {palette.muted};
        }}
        QLabel[variant="muted"] {{
            color: {palette.muted};
        }}
        QLabel[variant="heading"] {{
            font-weight: bold;
        }}
        QPushButton[variant="link"] {{
            background: transparent;
            border: none;
            text-align: left;
            padding-left: 0;
            color: {palette.control_fg};
        }}
        QWidget[variant="panel"] {{
            background-color: {palette.panel};
        }}
        QLineEdit {{
            background: {palette.field};
            border: {tokens.BORDER_WIDTH}px solid {palette.field_border};
            border-radius: {tokens.RADIUS_SM}px;
            color: {palette.field_fg};
            padding: {field_pad_v}px {field_pad_h}px;
        }}
        QLineEdit:focus {{
            border-color: {palette.field_focus};
        }}
        QComboBox {{
            background: {palette.combo};
            border: 0;
            border-radius: {tokens.RADIUS_MD}px;
            color: {palette.field_fg};
            padding: {tokens.COMBO_PAD_V}px {tokens.COMBO_PAD_RIGHT}px {tokens.COMBO_PAD_V}px {tokens.COMBO_PAD_LEFT}px;
        }}
        QComboBox:hover {{
            background: {palette.combo_hover};
        }}
        QComboBox:focus {{
            background: {palette.combo_focus};
        }}
        QComboBox::drop-down {{
            border: 0;
            width: {tokens.COMBO_ARROW_WIDTH}px;
        }}
        QComboBox::down-arrow {{
            image: none;
        }}
        QComboBox QAbstractItemView {{
            background: {palette.combo_list};
            border: {tokens.BORDER_WIDTH}px solid {palette.combo_list_border};
            color: {palette.field_fg};
            selection-background-color: {palette.combo};
        }}
        QComboBox QLineEdit {{
            background: transparent;
            border: none;
            border-radius: 0;
            padding: 0 {tokens.SPACE_XS}px;
            color: {palette.field_fg};
        }}
        QMenuBar {{
            background-color: {palette.bg};
            color: {palette.control_fg};
        }}
        QMenuBar::item {{
            padding: {menubar_pad_v}px {menubar_pad_h}px;
            background: transparent;
            border-radius: {tokens.RADIUS_SM}px;
        }}
        QMenuBar::item:selected, QMenuBar::item:pressed {{
            background: {palette.menu_selected};
        }}
        QMenu {{
            background: {palette.menu};
            border: {tokens.BORDER_WIDTH}px solid {palette.menu_border};
            color: {palette.field_fg};
            padding: {tokens.SPACE_SM}px 0;
        }}
        QMenu::item {{
            padding: {menu_top}px {menu_right}px {menu_bottom}px {menu_left}px;
            margin: 0 {tokens.SPACE_SM}px;
            border-radius: {tokens.RADIUS_SM}px;
        }}
        QMenu::item:selected {{
            background: {palette.menu_selected};
        }}
        QAbstractItemView {{
            outline: 0;
        }}
        QListView[variant="archiveSelector"] {{
            background: {palette.bg};
        }}
        QListView[variant="archiveSelector"]::item:focus {{
            border: {tokens.BORDER_WIDTH}px solid {palette.control_fg};
        }}
        QTableView::item:selected {{
            background-color: {palette.accent};
            color: {palette.accent_text};
            border: none;
            outline: none;
        }}
    """
