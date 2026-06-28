# Migration Unit 4 — GUI Removal

This fork is CLI-only. The Tkinter GUI (`fstogedcom`) is a pure leaf: nothing in the core
library imports it, so it can be removed without touching any shared logic.

## Files to delete

Delete the following three files outright:

| File | Description |
|---|---|
| `getmyancestors/classes/gui.py` | Tkinter UI — 664 lines, the entire GUI implementation |
| `getmyancestors/fstogedcom.py` | GUI entry-point shim — 31 lines, imports `gui.py` and launches `Tk()` |
| `getmyancestors/fstogedcom.png` | Window icon — shipped via `package-data`, used only by the GUI |

```
git rm getmyancestors/classes/gui.py
git rm getmyancestors/fstogedcom.py
git rm getmyancestors/fstogedcom.png
```

## `pyproject.toml` — 4 edits

### 1. Remove the `fstogedcom` console script (line ~40)

In `[project.scripts]`, delete this line:

```toml
fstogedcom = "getmyancestors.fstogedcom:main"
```

The remaining block should contain only the two CLI scripts:

```toml
[project.scripts]
getmyancestors = "getmyancestors.getmyancestors:main"
mergemyancestors = "getmyancestors.mergemyancestors:main"
```

### 2. Remove the `[tool.setuptools.package-data]` block entirely (lines ~34-35)

This block exists solely to ship the window icon with the package. Delete it in full:

```toml
[tool.setuptools.package-data]
getmyancestors = ["fstogedcom.png"]
```

### 3. Remove `diskcache==5.6.3` from `dependencies` (line ~20)

`diskcache` is imported only in `gui.py` (to cache the selected language between sessions).
No other module in the package imports it. Remove this entry from the `dependencies` list:

```toml
"diskcache==5.6.3",
```

### 4. Remove `"fstogedcom"` from `keywords` (line ~9)

This is cosmetic, but `fstogedcom` is no longer a registered entry point, so it should not
appear in package metadata:

```toml
keywords = [
  "getmyancestors",
  "familysearch",
  "fstogedcom",   # <-- remove this line
  "gedcom",
]
```

## `requirements.txt` — 1 edit

Remove the `diskcache` pin (line 2):

```
diskcache==5.6.3
```

The file should contain only the four remaining dependencies:

```
babelfish==0.6.1
requests==2.32.3
fake-useragent==2.0.3
requests-ratelimiter==0.7.0
```

## `README.md` — 1 edit

Remove the "With graphical user interface" section (lines 27-31):

    With graphical user interface:

    ```
    fstogedcom
    ```

The "How to use" section should begin directly with the "Command line examples:" heading.

## `CLAUDE.md` — 2 edits

If `CLAUDE.md` was added during this session and references the GUI, apply these trims:

1. **Entry points section** — remove the `fstogedcom` bullet (or the entire GUI sub-entry).
2. **i18n / translation section** — remove any mention of the `_()` helper being defined in
   `gui.py`. The helper in `translation.py` is the canonical one used by `session.py`; the
   duplicate defined at the top of `gui.py` goes away with the file.

## Dependencies not removed

The following packages may superficially appear GUI-related but are kept because they are
used by core modules:

| Package | Kept because |
|---|---|
| `babelfish` | Used by `tree.py` for language/place handling |
| `fake-useragent` | Used by `session.py` for HTTP user-agent rotation |
| `getmyancestors/classes/translation.py` | Used by `session.py` — not GUI-only |

## Verification

After completing all edits above, run the following checks in order.

### 1. Grep for GUI remnants

```bash
grep -ri "gui\|fstogedcom\|tkinter\|diskcache" . \
  --include="*.py" \
  --include="*.toml" \
  --include="*.txt" \
  --include="*.md" \
  --exclude-dir=docs
```

Expected result: no matches. The `docs/` directory is excluded because this migration guide
itself contains those terms.

### 2. Reinstall the package

```bash
pip install -e .
```

Expected result: exits without error. Confirm that `diskcache` is not pulled in as a
dependency.

### 3. Verify CLI entry points still work

```bash
getmyancestors --help
mergemyancestors --help
```

Both commands should print their help text and exit cleanly.

### 4. Confirm `fstogedcom` is gone

```bash
fstogedcom
```

Expected result: `command not found` (or the OS equivalent). If the old entry point is still
registered from a previous install, run `pip install -e .` again to refresh the script shims,
then retest.
