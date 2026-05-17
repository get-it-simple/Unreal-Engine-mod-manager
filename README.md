# Unreal Engine Console Mod-Manager (Python)

---

## ✨ Features

- 🔗 **Symlink Management**
  - Uses `mklink` for creating symbolic links:
    - Files → symbolic links
    - Folders → junctions (`/J`)
- ⚙️ **Config in JSON**
  - Stored next to the script
    - labels - separate config for labels to simplify managment with different names
    - config - script base settings
  - Defines:
    - Game mods directory
    - Mods source directory
    - File types
    - Page size
- 🔄 **Mod Operations**
  - Apply / deactivate mods (create/remove links in game dir)
  - Single **mods menu**:
    - List & toggle (install/uninstall)
    - Search by name
    - Pagination (20 items per page: `p1`, `p2`, …)
    - Multi-select via comma-separated indices
- 📂 **Presets in JSON**
  - Save current installed set
  - Apply / deactivate presets
  - Delete presets
  - All actions from **one unified presets menu**
- 🛠️ **Maintenance**
  - Fix broken links (remove dead ones automatically)

---

## ⚠️ Notes

- On **Windows**, creating symlinks may require **Administrator rights** or enabling **Developer Mode**.
- Junctions (`/J`) for directories usually don’t require elevated permissions.
- Linked names in the game directory always match the source file/folder names.

---

## ⚙️ Install requirements
### optional to use autocompletion for commands
```bash
pip install -r requirements.txt
```

## ▶️ Run

```bash
python .\mod-manager.py
```

## 🖼️ GUI

Run GUI from source:

```bash
python .\mod-manager.py gui
```

Build executable GUI app:

```powershell
$env:MOD_MANAGER_BUILD_EXE="1"
python .\build-gui-exe.py
```

Default build creates a faster onedir app:

```text
dist\mod-manager-gui\mod-manager-gui.exe
```

Build onefile app:

```powershell
$env:MOD_MANAGER_BUILD_EXE="1"
$env:MOD_MANAGER_ONEFILE="1"
python .\build-gui-exe.py
```

Onefile output:

```text
dist\mod-manager-gui.exe
```

The onefile app starts slower because it unpacks files before launch. Use the onedir app for better startup performance.

Build portable Python archive without PyInstaller:

```bash
python .\build-gui-exe.py
```

Archive output:

```text
dist\mod-manager-gui.pyz
```

---

## 🖥️ Text UI Preview

```text
Mod Manager — Menu
================================================
1) ⚙️ Settings
2) 🔄 Mods    - list, toggle, search
3) 🗃️ Presets - save,  apply, toggle, delete
4) 📋 Open mods source folder
5) 📂 Open game mods folder
6) 🛠️ Fix missing mods
0) 🏠 Exit
Select [0-6]:
```
## Mods menu
```text
Advanced completion disabled. Install: pip install prompt_toolkit

Page 1/19    Order: d    Filter: -
================================================
 1.  [X] mod_name_1... - [-]
 2.  [ ] mod_name_2... - [-]
 3.  [X] mod_name_3    - [label-1]

Type / for commands
>
```
## Mods menu - filter by label and order by create date
```text
Page 1/1    Order: d    Filter: l:label-1 | s:mod_nam
================================================
1.  [X] mod_name_1...  - [label-1]

Type / for commands
>
```
