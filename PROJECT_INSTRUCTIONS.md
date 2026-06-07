# Project Instructions

## Requirements

- Keep the code clean, simple, and readable.
- Use Python and keep dependencies minimal.
- Keep project responsibilities split across the appropriate files and modules.
- Do not leave comments in the code unless they clarify non-obvious behavior.
- Write project documentation and instruction files in English.
- Store application settings in `config.json` next to the application.
- Store presets in `presets.json` and mod labels/management metadata in `labels.json`.
- Keep JSON storage human-editable and backward compatible where reasonable.
- Manage installed mods by creating links in the configured game mods directory, not by copying mod contents there.
- Use directory junctions for folders on Windows and symlinks for files when possible.
- Preserve the user's source mod files when installing or uninstalling mods.
- Import mods only after the user explicitly chooses, drops, or pastes files/folders into the application.
- Copy imported mod files or folders into the configured mods source directory.
- Treat the `images` folder inside the mods source directory as local mod artwork storage, not as a mod.
- Support optional mod image artwork and store it under the source directory `images` folder.
- Keep CLI and tkinter GUI behavior consistent for shared operations.
- Keep pagination, search, labels, sorting, presets, and broken-link cleanup working in both shared logic and UI surfaces that use them.
- Use compact action buttons with hover tooltips in the GUI where that is already the local pattern.
- Keep user-visible settings in `DEFAULT_CONFIG` aligned with the settings UI and CLI settings command.
- Update `README.md` when commands, settings, workflows, or build behavior change.
- Keep the application version in `mod_manager/__init__.py` if version metadata is added.
- Run `python -m unittest discover -s tests -p "test_*.py"` before accepting code changes when tests exist.
- When fixing a bug, add or update a regression test when the project has a suitable test structure or the change has meaningful risk.
- Do not cheat with unit tests: tests must assert externally visible behavior or stable data contracts, must not only mirror implementation details, must not skip critical assertions to pass, and must not mock the code under test so heavily that the real behavior is no longer exercised.

## Implementation Notes

- `mods_source_dir` is the source of available mods.
- `game_mods_dir` is where active mod links are created and removed.
- `mod_extensions` is optional; when empty, all non-image files are treated as mod files.
- Folders in the source directory are treated as mods except for the reserved `images` folder.
- `link_prefix` applies to linked file names, not folders.
- Installing a mod should create the destination link and mark the mod as managed only after success.
- Uninstalling a mod should remove only the managed link or junction from the game mods directory.
- Broken-link cleanup should remove broken destinations without deleting source mods.
- Presets should store mod names and apply/deactivate those mods through the same link management path as normal mod toggles.
- Labels and last-managed state should stay associated with mod names even when filtering, sorting, or paginating.
- Preview/artwork handling must be optional and must not block importing or managing a mod when image processing fails.
- GUI long-running actions should use the existing background-action pattern so the window stays responsive.
- Build outputs belong under `build/` or `dist/` and should not be treated as source files.
