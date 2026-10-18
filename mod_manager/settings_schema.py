from __future__ import annotations

from dataclasses import dataclass, field

from app_paths import DEFAULT_CONFIG

from .ui.theme.colors import normalize_hex

INT = "int"
TEXT = "text"
PATH = "path"
CHOICE = "choice"
FLAG = "flag"
COLOR = "color"
FONT = "font"

INTERNAL_KEYS = frozenset({
    "active_game_profile_id",
    "game_profiles",
    "window_width",
    "window_height",
    "order_var",
    "mod_sort_key",
    "mod_sort_reverse",
    "preset_sort_key",
    "preset_sort_reverse",
})


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    tooltip: str
    kind: str
    choices: tuple = ()
    minimum: int | None = None
    maximum: int | None = None
    depends_on: tuple | None = None
    browse: bool = False

    @property
    def range_text(self) -> str:
        return f"between {self.minimum} and {self.maximum}"


GAME_NAME_FIELD = FieldSpec(
    key="name",
    label="Game name",
    tooltip="Name shown in the game switcher. The two letter abbreviation on the game button is derived from it.",
    kind=TEXT,
)

MODS_FIELDS = (
    FieldSpec(
        key="mods_source_dir",
        label="Mods source folder",
        tooltip="Folder that holds your downloaded mod files and folders. Imported mods are copied here and are never changed when you install or uninstall.",
        kind=PATH,
        browse=True,
    ),
    FieldSpec(
        key="game_mods_dir",
        label="Game mods folder",
        tooltip="Folder inside the game where install links are created. Uninstalling removes only those links, never your source mods.",
        kind=PATH,
        browse=True,
    ),
    FieldSpec(
        key="mod_extensions",
        label="Mod file extensions",
        tooltip="Comma separated file extensions treated as mods, for example .pak,.utoc. Leave empty to accept every non image file. Add 'folders' to also treat subfolders as mods.",
        kind=TEXT,
    ),
    FieldSpec(
        key="mod_group_extensions",
        label="Grouped extensions",
        tooltip="Comma separated extensions joined into a single mod when the files share a name, for example .pak,.utoc,.ucas. Installing or uninstalling then applies to every file of the group.",
        kind=TEXT,
    ),
    FieldSpec(
        key="mod_recursive_scan",
        label="Scan subfolders",
        tooltip="Also look inside subfolders of the mods source folder when listing available mods.",
        kind=FLAG,
    ),
    FieldSpec(
        key="link_prefix",
        label="Link name prefix",
        tooltip="Text added to the start of created link names in the game mods folder. Applies to linked files only, not to folders.",
        kind=TEXT,
    ),
    FieldSpec(
        key="install_mode",
        label="Install method",
        tooltip="Link creates a symlink or junction in the game mods folder. Copy physically copies the mod files there for games that cannot load linked files.",
        kind=CHOICE,
        choices=("link", "copy"),
    ),
)

LIST_FIELDS = (
    FieldSpec(
        key="page_size",
        label="Mods per page",
        tooltip="How many mods are shown on a single page in the mods list and in paged command line output.",
        kind=INT,
        minimum=1,
        maximum=1000,
    ),
    FieldSpec(
        key="max_mod_name_len",
        label="Max mod name length",
        tooltip="Longest mod name shown before it is shortened with an ellipsis. Display only, your files are never renamed.",
        kind=INT,
        minimum=4,
        maximum=200,
    ),
    FieldSpec(
        key="max_preset_name_len",
        label="Max preset name length",
        tooltip="Longest preset name shown before it is shortened in the presets list.",
        kind=INT,
        minimum=4,
        maximum=200,
    ),
    FieldSpec(
        key="max_label_name_len",
        label="Max label length",
        tooltip="Longest label text shown before it is shortened on tiles and in the Label column.",
        kind=INT,
        minimum=2,
        maximum=64,
    ),
)

APPEARANCE_FIELDS = (
    FieldSpec(
        key="gui_theme",
        label="Theme",
        tooltip="Follow the operating system appearance, or always use the light or the dark colour scheme.",
        kind=CHOICE,
        choices=("system", "light", "dark"),
    ),
    FieldSpec(
        key="gui_accent_color_mode",
        label="Accent colour",
        tooltip="Use the accent colour of the operating system, or pick a fixed custom accent colour.",
        kind=CHOICE,
        choices=("system", "custom"),
    ),
    FieldSpec(
        key="gui_accent_color",
        label="Custom accent colour",
        tooltip="Colour used for selection highlights, tile badges and checked buttons. Used only while the accent colour is set to custom.",
        kind=COLOR,
        depends_on=("gui_accent_color_mode", "custom"),
    ),
    FieldSpec(
        key="gui_text_color_mode",
        label="Text colour",
        tooltip="Use the default text colour of the theme, or pick a fixed custom text colour.",
        kind=CHOICE,
        choices=("system", "custom"),
    ),
    FieldSpec(
        key="gui_text_color",
        label="Custom text colour",
        tooltip="Colour used for window, button, input and tooltip text. Used only while the text colour is set to custom.",
        kind=COLOR,
        depends_on=("gui_text_color_mode", "custom"),
    ),
    FieldSpec(
        key="gui_font_family",
        label="Font family",
        tooltip="Font used across the whole interface. Leave empty to use the system default font.",
        kind=FONT,
    ),
    FieldSpec(
        key="gui_font_size",
        label="Font size",
        tooltip="Point size of the interface font. Applies immediately after saving.",
        kind=INT,
        minimum=6,
        maximum=40,
    ),
    FieldSpec(
        key="ui_scale_percent",
        label="Interface scale",
        tooltip="Scales the whole interface, in percent. Restart the application for a change to take effect.",
        kind=INT,
        minimum=50,
        maximum=400,
    ),
)

MODS_VIEW_FIELDS = (
    FieldSpec(
        key="mod_view_mode",
        label="Mods view",
        tooltip="Show mods as a details list, or as image tiles with a preview panel next to them.",
        kind=CHOICE,
        choices=("list", "tiles"),
    ),
    FieldSpec(
        key="tile_size",
        label="Tile size",
        tooltip="Width in pixels of a mod tile in tile view. Ctrl together with the mouse wheel changes this while browsing.",
        kind=INT,
        minimum=96,
        maximum=280,
    ),
    FieldSpec(
        key="placeholder_image_col_width",
        label="State column width",
        tooltip="Width in pixels of the leading install state column in the mods list.",
        kind=INT,
        minimum=16,
        maximum=400,
    ),
)

IMPORT_FIELDS = (
    FieldSpec(
        key="archive_import_mode",
        label="Default archive import mode",
        tooltip="Together creates one folder named after the archive. Separate imports each selected file or related file group as a mod.",
        kind=CHOICE,
        choices=("together", "separate"),
    ),
    FieldSpec(
        key="archive_preserve_structure",
        label="Preserve archive folder structure",
        tooltip="Keep paths inside the archive. Separate mode creates a folder for each mod. Turn off to flatten the imported files.",
        kind=FLAG,
    ),
    FieldSpec(
        key="import_ignore_extensions",
        label="Ignored import extensions",
        tooltip="Comma-separated extensions to exclude from new files, folders and archives, for example .txt,.md. Existing mods and explicitly assigned preview images are unaffected.",
        kind=TEXT,
    ),
)

SETTINGS_SECTIONS = (
    ("Lists", LIST_FIELDS),
    ("Import", IMPORT_FIELDS),
    ("Appearance", APPEARANCE_FIELDS),
    ("Mods view", MODS_VIEW_FIELDS),
)

GAME_PROFILE_FIELDS = (GAME_NAME_FIELD, *MODS_FIELDS)

PROFILE_KEYS = tuple(spec.key for spec in MODS_FIELDS)

NON_SETTING_KEYS = INTERNAL_KEYS | frozenset(PROFILE_KEYS)


def all_specs() -> tuple[FieldSpec, ...]:
    return tuple(spec for _section, specs in SETTINGS_SECTIONS for spec in specs)


def spec_for(key: str) -> FieldSpec | None:
    for spec in all_specs():
        if spec.key == key:
            return spec
    for spec in GAME_PROFILE_FIELDS:
        if spec.key == key:
            return spec
    return None


def label_for(key: str) -> str:
    spec = spec_for(key)
    return spec.label if spec else str(key).replace("_", " ")


def parse_int(spec: FieldSpec, value) -> int:
    try:
        number = int(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        raise ValueError(f"{spec.label} must be a whole number.") from None
    if spec.minimum is not None and spec.maximum is not None and not spec.minimum <= number <= spec.maximum:
        raise ValueError(f"{spec.label} must be {spec.range_text}.")
    return number


def normalize_choice(spec: FieldSpec, value) -> str:
    text = str(value or "").strip().lower()
    return text if text in spec.choices else spec.choices[0]


def normalize_color(spec: FieldSpec, value) -> str:
    fallback = str(DEFAULT_CONFIG.get(spec.key, "") or "")
    return normalize_hex(value) or normalize_hex(fallback) or fallback


def read_value(spec: FieldSpec, cfg: dict):
    value = cfg.get(spec.key, DEFAULT_CONFIG.get(spec.key, ""))
    if spec.kind == FLAG:
        return bool(value)
    return str(value if value is not None else "")


def read_settings(cfg: dict) -> dict:
    return {spec.key: read_value(spec, cfg) for spec in all_specs()}


def default_settings() -> dict:
    return read_settings(dict(DEFAULT_CONFIG))


def coerce_value(spec: FieldSpec, value):
    if spec.kind == FLAG:
        return bool(value)
    if spec.kind == INT:
        return parse_int(spec, value)
    if spec.kind == CHOICE:
        return normalize_choice(spec, value)
    if spec.kind == COLOR:
        return normalize_color(spec, value)
    return str(value or "").strip()


def coerce_settings(values: dict) -> dict:
    result = {}
    for spec in all_specs():
        if spec.key in values:
            result[spec.key] = coerce_value(spec, values[spec.key])
    return result


def coerce_game_profile(values: dict) -> dict:
    result = {}
    for spec in GAME_PROFILE_FIELDS:
        if spec.key in values:
            result[spec.key] = coerce_value(spec, values[spec.key])
    return result
