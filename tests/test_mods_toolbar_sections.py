from __future__ import annotations

import unittest

from tests.qt_support import qt_available
from tests.window_fixture import WindowTestCase

if qt_available():
    from PySide6 import QtWidgets

    from mod_manager.ui.pages import toolbar_specs
    from mod_manager.ui.widgets.style_utils import TOOLBAR_SECTION, VARIANT_PROPERTY

EXPECTED_TOOLBAR = (
    ("game", "Game", ("manage game profiles",)),
    ("filter", "Search", (
        "Apply search, label and favorite filters",
        "Clear search, label and favorite filters",
        "Show favorite mods only",
    )),
    ("order", "Order", ("Sort ascending",)),
    ("view", "View", ("Show mods as a list", "Show mods as tiles")),
    ("manage", "Manage", ("Open presets", "Open settings", "Open broken links cleanup")),
)

EXPECTED_ACTIONS = (
    ("page", "Page", ("Previous mods page", "Next mods page")),
    ("state", "Install", (
        "Install all mods on the current page",
        "Uninstall all mods on the current page",
        "Toggle selected mods",
    )),
    ("label", "Label", (
        "Add label to selected mods",
        "Remove label from selected mods",
        "Add or remove selected mods from favorites",
    )),
    ("import", "Import", (
        "Import mod files", "Import a mod folder",
        "Set preview image for selected mods from the clipboard or a file; confirm when applying to multiple mods",
    )),
)


@unittest.skipUnless(qt_available(), "PySide6 is not installed")
class ModsToolbarSectionTest(WindowTestCase):
    def button_names(self, section) -> tuple[str, ...]:
        return tuple(
            widget.toolTip()
            for widget in section.widgets()
            if isinstance(widget, QtWidgets.QAbstractButton)
        )

    def test_top_toolbar_sections_keep_their_order_and_captions(self):
        self.assertEqual(
            [(key, self.window.mods_toolbar.sections[key].title) for key in self.window.mods_toolbar.section_order()],
            [(key, title) for key, title, _tooltips in EXPECTED_TOOLBAR],
        )

    def test_action_toolbar_sections_keep_their_order_and_captions(self):
        self.assertEqual(
            [(key, self.window.mods_actions.sections[key].title) for key in self.window.mods_actions.section_order()],
            [(key, title) for key, title, _tooltips in EXPECTED_ACTIONS],
        )

    def test_actions_are_grouped_in_labeled_bordered_sections(self):
        for toolbar in (self.window.mods_toolbar, self.window.mods_actions):
            for section in toolbar.sections.values():
                self.assertIsInstance(section, QtWidgets.QFrame)
                self.assertEqual(section.property(VARIANT_PROPERTY), TOOLBAR_SECTION)
                self.assertTrue(section.title)

    def test_top_toolbar_buttons_sit_in_the_expected_section(self):
        for key, _title, tooltips in EXPECTED_TOOLBAR:
            names = self.button_names(self.window.mods_toolbar.sections[key])
            self.assertEqual(len(names), len(tooltips), key)
            for name, expected in zip(names, tooltips):
                self.assertIn(expected, name, key)

    def test_action_toolbar_buttons_sit_in_the_expected_section(self):
        for key, _title, tooltips in EXPECTED_ACTIONS:
            self.assertEqual(self.button_names(self.window.mods_actions.sections[key]), tooltips, key)

    def test_search_boxes_belong_to_the_filter_section(self):
        widgets = self.window.mods_toolbar.sections["filter"].widgets()
        self.assertIn(self.window.search_box, widgets)
        self.assertIn(self.window.label_filter_box, widgets)
        self.assertIn(self.window.favorite_filter_button, widgets)

    def test_order_combo_belongs_to_the_order_section(self):
        self.assertIn(self.window.order_box, self.window.mods_toolbar.sections["order"].widgets())

    def test_label_edit_belongs_to_the_label_section(self):
        self.assertIn(self.window.label_edit, self.window.mods_actions.sections["label"].widgets())

    def test_page_label_sits_between_the_page_arrows(self):
        widgets = self.window.mods_actions.sections["page"].widgets()
        self.assertEqual(widgets[1], self.window.page_label)
        self.assertEqual(self.window.page_label.text(), "Page 1/1")

    def test_every_toolbar_button_has_an_icon_a_tooltip_and_an_accessible_name(self):
        for toolbar in (self.window.mods_toolbar, self.window.mods_actions):
            for key, button in toolbar.buttons.items():
                self.assertFalse(button.icon().isNull(), key)
                self.assertTrue(button.toolTip(), key)
                self.assertTrue(button.accessibleName(), key)

    def test_icon_only_buttons_use_the_tooltip_as_their_accessible_name(self):
        stateful = {"install_page", "uninstall_page", "order_direction"}
        for toolbar in (self.window.mods_toolbar, self.window.mods_actions):
            for key, button in toolbar.buttons.items():
                if button.text() or key in stateful:
                    continue
                self.assertEqual(button.accessibleName(), button.toolTip(), key)

    def test_install_buttons_keep_the_localized_accessible_name(self):
        from mod_manager.ui.localization import system_action_text

        self.assertEqual(self.window.mods_actions.button("install_page").accessibleName(), system_action_text("install"))
        self.assertEqual(self.window.mods_actions.button("uninstall_page").accessibleName(), system_action_text("uninstall"))

    def test_selection_actions_follow_the_mod_selection(self):
        self.select_mod_rows()

        for key in toolbar_specs.SELECTION_ACTIONS:
            self.assertFalse(self.window.mods_actions.button(key).isEnabled(), key)

        self.select_mod_rows(0)

        for key in toolbar_specs.SELECTION_ACTIONS:
            self.assertTrue(self.window.mods_actions.button(key).isEnabled(), key)

    def test_view_mode_buttons_form_a_checkable_pair(self):
        list_button = self.window.mods_toolbar.button("view_list")
        tiles_button = self.window.mods_toolbar.button("view_tiles")
        self.assertTrue(list_button.isCheckable())
        self.assertTrue(tiles_button.isCheckable())
        self.assertTrue(list_button.isChecked())
        self.assertFalse(tiles_button.isChecked())

        self.window._set_view_mode("tiles")

        self.assertFalse(list_button.isChecked())
        self.assertTrue(tiles_button.isChecked())

    def test_every_declared_button_key_is_registered(self):
        self.assertEqual(
            set(self.window.mods_toolbar.buttons),
            set(toolbar_specs.button_keys(toolbar_specs.MODS_TOOLBAR_SECTIONS)) | {"games", "order_direction"},
        )
        self.assertEqual(
            set(self.window.mods_actions.buttons),
            set(toolbar_specs.button_keys(toolbar_specs.MODS_ACTION_SECTIONS)) | {"prev_page", "next_page"},
        )

    def test_busy_state_disables_every_action_button(self):
        self.window._set_busy(True, "Working...")
        try:
            for toolbar in (self.window.mods_toolbar, self.window.mods_actions):
                for key, button in toolbar.buttons.items():
                    self.assertFalse(button.isEnabled(), key)
        finally:
            self.window._set_busy(False)


@unittest.skipUnless(qt_available(), "PySide6 is not installed")
class DialogToolbarSectionTest(WindowTestCase):
    def test_presets_dialog_groups_paging_and_preset_actions(self):
        toolbar = self.window.presets_toolbar
        self.assertEqual(toolbar.section_order(), ["page", "preset"])
        self.assertEqual([section.title for section in toolbar.sections.values()], ["Page", "Presets"])
        self.assertIn(self.window.preset_name, toolbar.sections["preset"].widgets())
        self.assertIn(self.window.preset_page_label, toolbar.sections["page"].widgets())
        self.assertEqual(set(toolbar.buttons), {"prev_page", "next_page", "save", "toggle", "delete"})

    def test_broken_dialog_groups_cleanup_actions(self):
        toolbar = self.window.broken_toolbar
        self.assertEqual(toolbar.section_order(), ["cleanup"])
        self.assertEqual(toolbar.sections["cleanup"].title, "Broken links")
        self.assertEqual(set(toolbar.buttons), {"remove_selected", "remove_all"})

    def test_settings_dialog_groups_its_save_action(self):
        toolbar = self.window.settings_toolbar
        self.assertEqual(toolbar.sections["settings"].title, "Settings")
        self.assertEqual(set(toolbar.buttons), {"save_settings"})

    def test_games_page_and_dialog_share_the_same_sections(self):
        for toolbar in (self.window.games_page_toolbar, self.window.games_dialog_toolbar):
            self.assertEqual(toolbar.section_order(), ["choose", "profiles"])
            self.assertEqual([section.title for section in toolbar.sections.values()], ["Game", "Profiles"])
            self.assertEqual(set(toolbar.buttons), {"select", "add", "edit", "delete"})

    def test_every_dialog_button_has_a_tooltip(self):
        toolbars = (
            self.window.presets_toolbar,
            self.window.broken_toolbar,
            self.window.settings_toolbar,
            self.window.games_page_toolbar,
            self.window.games_dialog_toolbar,
        )
        for toolbar in toolbars:
            for key, button in toolbar.buttons.items():
                self.assertTrue(button.toolTip(), key)
                self.assertFalse(button.icon().isNull(), key)


if __name__ == "__main__":
    unittest.main()
