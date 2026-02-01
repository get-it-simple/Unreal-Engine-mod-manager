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

## ▶️ Run

```bash
python .\mod-manager.py
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
Mods — install/uninstall (toggle)
================================================
Order: default ↓
 1) [ ] test - Copy - Copy.pak (FILE)
        test label 1

 2) [ ] test - Copy.pak (FILE)
        -

 3) [ ] test.pak (FILE)
        -


Commands:
  - f: <text> (search) | clear: (clear search filter)
  - l <labelName>: (label filter)
  - label <add|remove> <labelName> <fileIndex>
  - o: <orderType> order mode (d or default, cd or created date)
  - numbers <comma-separated>: toggle selected
  - a: Uninstall ALL (current page)
  - i: Install ALL (current page)
  - pN: go to page N   |   0: back

> label add "test label 1" 1
```
## Mods menu - filter by label and order by create date
#### commands:
- `l test label 1`
- `o cd`
```text
Mods — install/uninstall (toggle)
================================================
Order: created date ↓
Label: 'test label 1'
 1) [ ] test - Copy - Copy.pak (FILE)

Commands:
  - f: <text> (search) | clear: (clear search filter)
  - l <labelName>: (label filter)
  - label <add|remove> <labelName> <fileIndex>
  - o: <orderType> order mode (d or default, cd or created date)
  - numbers <comma-separated>: toggle selected
  - a: Uninstall ALL (current page)
  - i: Install ALL (current page)
  - pN: go to page N   |   0: back
    Order mode set to: created date
>
```
