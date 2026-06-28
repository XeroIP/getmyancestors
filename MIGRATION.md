# Migration Guide

This document describes five refactoring steps for the `getmyancestors` personal fork. Each
section is self-contained and includes the full rationale, exact file edits, and verification
steps for that change. Recommended order: GUI removal first (pure deletion, no dependencies),
then Python 2 cleanup, then packaging migration to uv, then the asyncio replacement, and
finally the structural refactoring.

---

## 1. Remove the GUI (do this first — it's a clean deletion with no dependencies)

This fork is CLI-only. The Tkinter GUI (`fstogedcom`) is a pure leaf: nothing in the core
library imports it, so it can be removed without touching any shared logic.

### Files to delete

Delete the following three files outright:

| File | Description |
|---|---|
| `getmyancestors/classes/gui.py` | Tkinter UI — 664 lines, the entire GUI implementation |
| `getmyancestors/fstogedcom.py` | GUI entry-point shim — 31 lines, imports `gui.py` and launches `Tk()` |
| `getmyancestors/fstogedcom.png` | Window icon — shipped via `package-data`, used only by the GUI |

```bash
git rm getmyancestors/classes/gui.py
git rm getmyancestors/fstogedcom.py
git rm getmyancestors/fstogedcom.png
```

### `pyproject.toml` — 4 edits

#### 1. Remove the `fstogedcom` console script (line ~40)

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

#### 2. Remove the `[tool.setuptools.package-data]` block entirely (lines ~34-35)

This block exists solely to ship the window icon with the package. Delete it in full:

```toml
[tool.setuptools.package-data]
getmyancestors = ["fstogedcom.png"]
```

#### 3. Remove `diskcache==5.6.3` from `dependencies` (line ~20)

`diskcache` is imported only in `gui.py` (to cache the selected language between sessions).
No other module in the package imports it. Remove this entry from the `dependencies` list:

```toml
"diskcache==5.6.3",
```

#### 4. Remove `"fstogedcom"` from `keywords` (line ~9)

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

### `requirements.txt` — 1 edit

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

### `README.md` — 1 edit

Remove the "With graphical user interface" section (lines 27-31):

    With graphical user interface:

    ```
    fstogedcom
    ```

The "How to use" section should begin directly with the "Command line examples:" heading.

### `CLAUDE.md` — 2 edits

If `CLAUDE.md` was added during this session and references the GUI, apply these trims:

1. **Entry points section** — remove the `fstogedcom` bullet (or the entire GUI sub-entry).
2. **i18n / translation section** — remove any mention of the `_()` helper being defined in
   `gui.py`. The helper in `translation.py` is the canonical one used by `session.py`; the
   duplicate defined at the top of `gui.py` goes away with the file.

### Dependencies not removed

The following packages may superficially appear GUI-related but are kept because they are
used by core modules:

| Package | Kept because |
|---|---|
| `babelfish` | Used by `tree.py` for language/place handling |
| `fake-useragent` | Used by `session.py` for HTTP user-agent rotation |
| `getmyancestors/classes/translation.py` | Used by `session.py` — not GUI-only |

### Verification

After completing all edits above, run the following checks in order.

#### 1. Grep for GUI remnants

```bash
grep -Eri "gui|fstogedcom|tkinter|diskcache" . \
  --include="*.py" \
  --include="*.toml" \
  --include="*.txt" \
  --include="*.md" \
  --exclude="MIGRATION.md"
```

Expected result: no matches. `MIGRATION.md` is excluded because this migration guide
itself contains those terms.

#### 2. Reinstall the package

```bash
pip install -e .
```

Expected result: exits without error. Confirm that `diskcache` is not pulled in as a
dependency.

#### 3. Verify CLI entry points still work

```bash
getmyancestors --help
mergemyancestors --help
```

Both commands should print their help text and exit cleanly.

#### 4. Confirm `fstogedcom` is gone

```bash
fstogedcom
```

Expected result: `command not found` (or the OS equivalent). If the old entry point is still
registered from a previous install, run `pip install -e .` again to refresh the script shims,
then retest.

---

## 2. Clean up Python 2 vestiges

This section covers six Python 2 / legacy vestiges that should be removed from the
`getmyancestors` codebase. The package already requires Python >=3.7 and targets only
CLI use via installed entry points, so all of these are dead code.

### A. `from __future__ import print_function`

**Why it exists:** In Python 2, `print` was a statement. The `__future__` import made
`print()` behave as a function so the same source could run on both 2 and 3. Python 3
has only the function form; the import is a no-op and a misleading signal.

**Where it appears (two files):**

- `getmyancestors/getmyancestors.py`, line 4
- `getmyancestors/mergemyancestors.py`, line 3

> Note: the task brief references a third file. A grep of the repository finds exactly
> two occurrences. No action needed beyond the two files listed above.

**What to do:** Delete the `from __future__ import print_function` line from each file.
No other changes required — both files use `print()` as a function throughout and that
usage is already correct Python 3.

### B. `sys.path.append(os.path.dirname(sys.argv[0]))` in `mergemyancestors.py`

**Location:** `getmyancestors/mergemyancestors.py`, line 14

```python
sys.path.append(os.path.dirname(sys.argv[0]))
```

**Why it exists:** Before proper packaging, scripts were run directly from the source
directory. Appending `sys.argv[0]`'s directory to `sys.path` was a hack to make sibling
modules importable. When the package is installed and invoked via a `[project.scripts]`
entry point, the installed package is already on `sys.path`; this line is unnecessary
and potentially misleading.

**What to do:** Remove line 14 entirely.

**Follow-up — `os` import:** `os` is imported at line 6 and used nowhere else in the
file after removing line 14. Verify this with a quick search:

```bash
grep -n '\bos\b' getmyancestors/mergemyancestors.py
```

If the only hit is the `import os` line itself, remove the `import os` line as well.
Based on a full read of the file, `os` is not used anywhere else, so both lines should
go.

### C. Eager imports in `__init__.py`

**Location:** `getmyancestors/__init__.py`, lines 1–6 (full current content):

```python
# coding: utf-8

from . import getmyancestors
from . import mergemyancestors

__version__ = "1.1.2"
```

**Why the imports are a problem:** `getmyancestors.py` and `mergemyancestors.py` are
CLI entry modules. Although they guard side-effectful code with `if __name__ ==
"__main__"`, their `main()` functions contain top-level argparse setup and are only
intended to be invoked via entry points — not imported. Importing them eagerly at
package import time:

1. Slows down any `import getmyancestors` call (argparse construction, etc.) even when
   only the version string is needed.
2. Creates a circular-import risk: `getmyancestors/classes/tree.py` does
   `import getmyancestors` (to read `__version__`), which would re-enter `__init__.py`
   and try to import the CLI modules before they are fully initialized.

The CLI modules do not need to be importable from the package root. Entry points call
their `main()` functions directly.

**What to do:** Replace the entire content of `getmyancestors/__init__.py` with:

```python
__version__ = "1.1.2"
```

Remove both `from . import` lines and the `# coding: utf-8` header (see section F).

### D. `try/except TypeError` Python-version guard in `mergemyancestors.py`

**Location:** `getmyancestors/mergemyancestors.py`, lines 23–43 (inside `main()`):

```python
try:
    parser.add_argument(
        "-i",
        metavar="<FILE>",
        nargs="+",
        type=argparse.FileType("r", encoding="UTF-8"),
        default=[sys.stdin],
        help="input GEDCOM files [stdin]",
    )
    parser.add_argument(
        "-o",
        metavar="<FILE>",
        nargs="?",
        type=argparse.FileType("w", encoding="UTF-8"),
        default=sys.stdout,
        help="output GEDCOM files [stdout]",
    )
except TypeError:
    sys.stderr.write("Python >= 3.4 is required to run this script\n")
    sys.stderr.write("(see https://docs.python.org/3/whatsnew/3.4.html#argparse)\n")
    exit(2)
```

**Why the guard is dead code:** The `encoding=` keyword argument to `argparse.FileType`
was added in Python 3.4. With `requires-python = ">=3.7"` (and the planned bump to
`>=3.10`), any Python that runs this code already supports `encoding=`. The `except
TypeError` branch is unreachable.

**What to do:** Unwrap the two `parser.add_argument` calls from the `try/except` block.
Delete the `try:`, the `except TypeError:` line, and the three lines of the error body.
The two `parser.add_argument` calls themselves are kept exactly as-is, un-indented by
one level.

After the change, the relevant section of `main()` should read:

```python
parser.add_argument(
    "-i",
    metavar="<FILE>",
    nargs="+",
    type=argparse.FileType("r", encoding="UTF-8"),
    default=[sys.stdin],
    help="input GEDCOM files [stdin]",
)
parser.add_argument(
    "-o",
    metavar="<FILE>",
    nargs="?",
    type=argparse.FileType("w", encoding="UTF-8"),
    default=sys.stdout,
    help="output GEDCOM files [stdout]",
)
```

### E. `requires-python` bump

**Location:** `pyproject.toml`, line 4:

```toml
requires-python = ">=3.7"
```

**Rationale for bumping:** Python 3.7 and 3.8 both reached end-of-life in June 2023.
Python 3.9 reached end-of-life in October 2025. Python 3.10 reaches end-of-life in
October 2026 and is the recommended minimum: it is the boundary version for the
`asyncio.get_event_loop()` deprecation (addressed in section 4), it is still shipped in
many enterprise Linux distributions (RHEL 9 backport, Ubuntu 22.04), and it is the
oldest CPython release still receiving security patches at the time of writing.

Declaring `>=3.10` also unlocks cleaner type-annotation syntax (`list[str]` instead of
`List[str]`, `dict[str, int]` instead of `Dict[str, int]`, `X | Y` union syntax)
should type hints be added in the future.

**What to do:**

```toml
requires-python = ">=3.10"
```

This is a one-line change. `>=3.9` is also an improvement over the current `>=3.7` if
you need to support systems that only carry 3.9, but 3.9 is fully EOL and `>=3.10` is
the cleaner choice.

### F. `# coding: utf-8` headers

**Why they exist:** Python 2 required an explicit encoding declaration when source files
contained non-ASCII characters. Python 3 defaults to UTF-8 for all source files. The
comment has no runtime effect and is clutter.

**Where it appears (four files after GUI removal):**

| File | Line |
|---|---|
| `getmyancestors/__init__.py` | 1 |
| `getmyancestors/getmyancestors.py` | 1 |
| `getmyancestors/mergemyancestors.py` | 1 |
| `getmyancestors/classes/translation.py` | 1 |

**What to do:** Delete the `# coding: utf-8` line from each file.

### Recommended removal order

To minimize merge conflicts across edits, apply these changes in this order:

1. Remove `# coding: utf-8` headers from all four files (F).
2. Remove `from __future__ import print_function` from both CLI files (A).
3. Slim down `__init__.py` to `__version__` only (C).
4. Remove `sys.path.append` and the `import os` line from `mergemyancestors.py` (B).
5. Unwrap the `try/except TypeError` block in `mergemyancestors.py` (D).
6. Bump `requires-python` in `pyproject.toml` (E).

---

## 3. Migrate to uv

**Scope:** Replace the implicit-setuptools `pyproject.toml` + redundant `requirements.txt` with a
fully-declared PEP 517 build backend managed by **uv**. This section is purely about packaging
hygiene and tooling.

### Why uv (over Poetry or bare pip)

| Concern | pip + venv | Poetry | uv |
|---|---|---|---|
| Speed | Slow resolution | Moderate | 10–100× faster (Rust resolver) |
| Single tool | No (pip + venv + pip-tools separate) | Yes | Yes |
| Lock file | `pip-tools` needed separately | `poetry.lock` | `uv.lock` |
| PEP 517 compliant | Yes (pip) | Yes | Yes |
| Editable installs | Yes | Yes | Yes |
| Extra learning surface | Low | Medium (custom config syntax) | Low (close to pip mental model) |
| venv management | Manual | Automatic | Automatic |

Poetry is a solid tool, but it imposes its own `[tool.poetry]` config block, a custom dependency
version syntax, and a separate lock file format. For a single-author CLI project there is no benefit
to that extra surface. uv speaks standard `pyproject.toml` and produces a standard lock file; the
only new concept is replacing `pip install` with `uv sync`.

### What changes in `pyproject.toml`

#### Before

```toml
[project]
name = "getmyancestors"
description = "Retrieve GEDCOM data from FamilySearch Tree"
requires-python = ">=3.7"
license = {text = "GNU"}
keywords = [
  "getmyancestors",
  "familysearch",
  "fstogedcom",
  "gedcom",
]
classifiers = [
    "Environment :: Console",
    "License :: OSI Approved :: GNU General Public License (GPL)",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3 :: Only",
]
dependencies = [
    "babelfish==0.6.1",
    "diskcache==5.6.3",
    "requests==2.32.3",
    "fake-useragent==2.0.3",
    "requests-ratelimiter==0.7.0"
]
dynamic = ["version", "readme"]

[tool.setuptools.dynamic]
version = {attr = "getmyancestors.__version__"}
readme = {file = ["README.md"]}

[project.urls]
HomePage = "https://github.com/Linekio/getmyancestors"

[tool.setuptools.package-data]
getmyancestors = ["fstogedcom.png"]

[project.scripts]
getmyancestors = "getmyancestors.getmyancestors:main"
mergemyancestors = "getmyancestors.mergemyancestors:main"
fstogedcom = "getmyancestors.fstogedcom:main"
```

#### After

```toml
[build-system]
requires = ["setuptools>=70"]
build-backend = "setuptools.build_meta"

[project]
name = "getmyancestors"
description = "Retrieve GEDCOM data from FamilySearch Tree"
requires-python = ">=3.10"
license = {text = "GNU"}
keywords = [
  "getmyancestors",
  "familysearch",
  "gedcom",
]
classifiers = [
    "Environment :: Console",
    "License :: OSI Approved :: GNU General Public License (GPL)",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3 :: Only",
]
dependencies = [
    "babelfish==0.6.1",
    "requests==2.32.3",
    "fake-useragent==2.0.3",
    "requests-ratelimiter==0.7.0",
]
dynamic = ["version", "readme"]

[tool.setuptools.dynamic]
version = {attr = "getmyancestors.__version__"}
readme = {file = ["README.md"]}

[project.urls]
HomePage = "https://github.com/XeroIP/getmyancestors"

[project.scripts]
getmyancestors = "getmyancestors.getmyancestors:main"
mergemyancestors = "getmyancestors.mergemyancestors:main"
```

#### Change-by-change rationale

**`[build-system]` added.**
Without this table, tools that follow PEP 517 (including uv) fall back to a legacy setuptools shim.
Declaring it explicitly makes the build reproducible and removes the implicit dependency on whatever
setuptools version happens to be installed.

**`requires-python` raised to `>=3.10`.**
The current `>=3.7` claim is inaccurate — the codebase uses `asyncio.get_event_loop()` patterns
that emit `DeprecationWarning` on 3.10 and raise `RuntimeError` on 3.12, as covered in section 4.
Setting this to `>=3.10` matches where the code runs correctly after those fixes land.
(Python 3.9 reached end-of-life in October 2025.)

**`diskcache==5.6.3` dropped.**
`diskcache` is used exclusively by the GUI (`fstogedcom`). After removing the GUI in section 1,
there are no remaining call sites.

**`[tool.setuptools.package-data]` block removed.**
The only entry was `fstogedcom.png`, the GUI icon. With the GUI gone there is nothing to bundle.

**`fstogedcom` script entry removed.**
Same reason. The entry point `getmyancestors.fstogedcom:main` no longer exists after section 1.

**`HomePage` URL updated.**
Changed from the upstream `Linekio/getmyancestors` to `XeroIP/getmyancestors` (this fork's
location). This was missing from the original `pyproject.toml` and has no functional effect on the
package, but keeps the metadata accurate.

**`requirements.txt` deleted.**
This file was a hand-maintained duplicate of the `dependencies` list in `pyproject.toml`. It served
as a workaround for the absence of a real lock file. `uv.lock` replaces it.

### Lock file strategy

Commit `uv.lock` to the repository. This file is generated and updated by uv and records the exact
resolved version of every dependency (direct and transitive). Committing it means that anyone who
clones the repo and runs `uv sync` gets the identical environment — no surprises from a dependency
releasing a patch the night before you run `pip install`.

uv's lock file is human-readable and diff-friendly; dependency updates show as clear line changes.

```bash
# generate / update the lock file
uv lock

# install exactly what the lock file says (what you'll run daily)
uv sync
```

Do not add `uv.lock` to `.gitignore`. That would defeat the purpose.

### Developer workflow — before and after

#### Before (bare pip)

```bash
# one-time setup
python -m venv .venv
source .venv/bin/activate          # or .venv\Scripts\activate on Windows
pip install -r requirements.txt    # or: pip install -e .

# running a command
python -m getmyancestors.getmyancestors --help
# or, if installed into the venv:
getmyancestors --help
```

#### After (uv)

```bash
# install uv once (system-wide, not per-project)
pip install uv
# or on Windows via winget:
winget install astral-sh.uv

# one-time setup (uv creates and manages the venv automatically)
uv sync

# running a command — uv run ensures the venv is up-to-date before executing
uv run getmyancestors --help
uv run mergemyancestors --help

# adding a dependency
uv add some-package

# removing a dependency
uv remove some-package

# updating the lock file after manually editing pyproject.toml
uv lock

# upgrading a dependency to its latest allowed version
uv lock --upgrade-package requests
```

`uv run` is the main day-to-day command. It checks whether the venv matches the lock file and
reinstalls anything that has drifted before running the script — so you never need to remember to
activate the venv manually.

### Gotchas and notes

#### `babelfish` is effectively abandonware

`babelfish 0.6.1` was released in 2014 and has not been updated since. It is used for language
code normalization in the GEDCOM output. The package still works, but:

- It has no maintainer activity.
- If it ever disappears from PyPI, a vendored copy or a thin replacement will be needed.
- For now, leave it pinned at `==0.6.1` and note the risk.

No action required in this section.

#### `fake-useragent` has a history of PyPI instability

`fake-useragent` fetches a list of real browser user-agent strings. Historically the package has
had PyPI publication gaps and dependency issues. `2.0.3` is the current stable release; pin it
exactly (`==2.0.3`) and do not use a loose specifier like `>=2.0`. If a future version causes
problems, the fallback is to hardcode a static user-agent string in `getmyancestors.py` and remove
the dependency entirely.

#### The `dynamic` version attribute still requires setuptools

The `dynamic = ["version"]` / `version = {attr = "getmyancestors.__version__"}` mechanism is a
setuptools feature. This is fine — the `[build-system]` table now declares setuptools explicitly,
so the dependency is no longer implicit.

#### Editable installs

If you want an editable install (so that changes to the source are immediately reflected without
reinstalling), use:

```bash
uv pip install -e .
```

For a personal fork you will likely always work editable.

---

## 4. Replace asyncio with ThreadPoolExecutor

### Background

The codebase uses `asyncio` in three places to parallelize HTTP-bound work. In every case the implementation follows the same pattern: an `async` inner function calls `loop.run_in_executor(None, blocking_fn)` on a set of work items, then awaits each future. This is not true async I/O — `run_in_executor` with `None` dispatches to the default `ThreadPoolExecutor`, meaning every call is a regular OS thread under the hood. The `asyncio` layer sits on top and contributes nothing except complexity and deprecation warnings.

### Why the Current Pattern Needs to Go

#### 1. It is not async I/O

`loop.run_in_executor(None, fn)` offloads `fn` to a thread pool and returns a `Future` that resolves when the thread finishes. The work still blocks a thread; asyncio does not make it non-blocking. The pattern is semantically equivalent to `executor.submit(fn)` with extra steps. The only case where wrapping threads in asyncio would buy anything is when you also have genuine coroutines to interleave — there are none here.

#### 2. `asyncio.get_event_loop()` is deprecated

Python 3.10 deprecated `asyncio.get_event_loop()` when called with no running event loop, emitting a `DeprecationWarning` at runtime. Python 3.12 escalated this: if there is no current event loop, the call now raises `RuntimeError` instead of silently creating one. Because this code runs as a CLI (not inside an existing async framework), there is no running loop at the call sites, so any Python 3.12 installation will crash at this call site.

`add_indis` uses the slightly different `asyncio.new_event_loop()` + `asyncio.set_event_loop(loop)` pattern, which avoids the deprecation but creates a new loop for every invocation of `add_indis()` — once per call, before the batch `while` loop, not once per batch iteration. If an exception escapes before `loop.close()` is called (and it is never explicitly called here), the loop leaks.

#### 3. The code is harder to reason about than the thread-only equivalent

Nesting an `async def` inside a regular method, constructing or retrieving an event loop, and awaiting futures one at a time is substantially more code than calling `executor.map()` or collecting `Future` objects from `executor.submit()`. A reader familiar with `concurrent.futures` can understand the replacement in seconds; the asyncio wrapper requires knowing what `run_in_executor` actually does.

### The Replacement: `concurrent.futures.ThreadPoolExecutor`

`concurrent.futures.ThreadPoolExecutor` is the standard library's thread pool. It has a clean, synchronous API that does exactly what the current code does — runs blocking functions on threads and waits for them to finish — without event loop machinery.

The key methods used in the migration:

- `executor.submit(fn, *args)` — schedule a call and return a `Future`
- `concurrent.futures.wait(futures)` — block until all futures complete; unlike `await future`, this never raises — errors remain stored in the future until you call `.result()`
- `executor.map(fn, iterable)` — convenience wrapper; submit + wait in one call, raises on error

### Choosing `max_workers`

`ThreadPoolExecutor(max_workers=None)` defaults to `min(32, (os.cpu_count() or 1) + 4)` as of Python 3.8. The `or 1` guard handles the case where `os.cpu_count()` returns `None` (possible in containers or restricted environments — `None + 4` would otherwise raise `TypeError`). That default is reasonable here: the bottleneck is network I/O, not CPU, so more threads help up to the point where the FamilySearch API starts rate-limiting or the connection pool saturates. A sensible explicit value is:

```python
import os
MAX_WORKERS = min(32, (os.cpu_count() or 1) + 4)
```

If you want to expose this as a CLI option, add `--workers N` to the argument parser and pass the value through. The default above is a good starting point and does not need tuning for typical tree sizes.

### What Stays the Same

- All `requests` calls inside `Session.get_url()` — unchanged.
- The `Session.get_url()` method itself — unchanged.
- `Indi.add_data()`, `Indi.get_notes()`, `Indi.get_contributors()` — unchanged.
- `Fam.add_marriage()`, `Fam.get_notes()`, `Fam.get_contributors()` — unchanged.
- `Tree.add_ordinances()` — unchanged.
- All model classes (`Indi`, `Fam`, `Tree`) — unchanged.
- The call sites in `add_indis`, `add_spouses`, and `download_stuff` change; everything else in those methods stays the same.

### Call Site 1: `Tree.add_indis` — `getmyancestors/classes/tree.py` line ~654

This site processes persons in batches of up to `MAX_PERSONS`. For each batch it fans out `Indi.add_data()` calls in parallel, then waits for all of them before processing the next batch.

**Before:**

```python
# Inside add_indis (called in a while loop over batches)
async def add_datas(loop, data):
    futures = set()
    for person in data["persons"]:
        self.indi[person["id"]] = Indi(person["id"], self)
        futures.add(
            loop.run_in_executor(None, self.indi[person["id"]].add_data, person)
        )
    for future in futures:
        await future

new_fids = [fid for fid in fids if fid and fid not in self.indi]
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
while new_fids:
    data = self.fs.get_url(...)
    if data:
        # ... place/relationship processing ...
        loop.run_until_complete(add_datas(loop, data))
    new_fids = new_fids[MAX_PERSONS:]
```

**After:**

```python
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait

new_fids = [fid for fid in fids if fid and fid not in self.indi]
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    while new_fids:
        data = self.fs.get_url(...)
        if data:
            # ... place/relationship processing (unchanged) ...
            pending = set()
            for person in data["persons"]:
                self.indi[person["id"]] = Indi(person["id"], self)
                pending.add(
                    executor.submit(self.indi[person["id"]].add_data, person)
                )
            futures_wait(pending)
        new_fids = new_fids[MAX_PERSONS:]
```

**Exception behavior change:** The current asyncio code propagates exceptions — `await future` re-raises any exception thrown by `add_data`. The replacement `futures_wait(pending)` does not raise; exceptions are stored in each future until you explicitly call `.result()`. If you want to preserve the existing behavior (errors from individual persons surface immediately), add a loop after `futures_wait`:

```python
futures_wait(pending)
for f in pending:
    f.result()  # re-raises any stored exception
```

If you intentionally want to tolerate partial failures (continue even if some persons fail to load), omit the `.result()` calls and handle errors separately.

### Call Site 2: `Tree.add_spouses` — `getmyancestors/classes/tree.py` line ~777

This site fans out `Fam.add_marriage()` calls for a set of family relationships.

**Before:**

```python
async def add(loop, rels):
    futures = set()
    for father, mother, relfid in rels:
        if (father, mother) in self.fam:
            futures.add(
                loop.run_in_executor(
                    None, self.fam[(father, mother)].add_marriage, relfid
                )
            )
    for future in futures:
        await future

rels = set()
for fid in fids & self.indi.keys():
    rels |= self.indi[fid].spouses
loop = asyncio.get_event_loop()   # deprecated in 3.10, RuntimeError in 3.12
if rels:
    self.add_indis(...)
    # ... fam setup ...
    loop.run_until_complete(add(loop, rels))
```

**After:**

```python
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait

rels = set()
for fid in fids & self.indi.keys():
    rels |= self.indi[fid].spouses
if rels:
    self.add_indis(...)
    # ... fam setup (unchanged) ...
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        pending = {
            executor.submit(self.fam[(father, mother)].add_marriage, relfid)
            for father, mother, relfid in rels
            if (father, mother) in self.fam
        }
        futures_wait(pending)
```

The `loop` variable and the `add` inner function are entirely removed.

**Exception behavior change:** Same as Call Site 1 — `await future` in the original propagates exceptions from `add_marriage`; `futures_wait` does not. Add `for f in pending: f.result()` after `futures_wait` if you want errors to propagate.

### Call Site 3: `download_stuff` — `getmyancestors/getmyancestors.py` line ~247

This is the largest fan-out: notes, ordinances, and contributors for every individual and family are all dispatched in a single batch.

**Before:**

```python
async def download_stuff(loop):
    futures = set()
    for fid, indi in tree.indi.items():
        futures.add(loop.run_in_executor(None, indi.get_notes))
        if args.get_ordinances:
            futures.add(loop.run_in_executor(None, tree.add_ordinances, fid))
        if args.get_contributors:
            futures.add(loop.run_in_executor(None, indi.get_contributors))
    for fam in tree.fam.values():
        futures.add(loop.run_in_executor(None, fam.get_notes))
        if args.get_contributors:
            futures.add(loop.run_in_executor(None, fam.get_contributors))
    for future in futures:
        await future

loop = asyncio.get_event_loop()   # deprecated in 3.10, RuntimeError in 3.12
# ... progress print ...
loop.run_until_complete(download_stuff(loop))
```

**After:**

```python
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait

# ... progress print (unchanged) ...
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    pending = set()
    for fid, indi in tree.indi.items():
        pending.add(executor.submit(indi.get_notes))
        if args.get_ordinances:
            pending.add(executor.submit(tree.add_ordinances, fid))
        if args.get_contributors:
            pending.add(executor.submit(indi.get_contributors))
    for fam in tree.fam.values():
        pending.add(executor.submit(fam.get_notes))
        if args.get_contributors:
            pending.add(executor.submit(fam.get_contributors))
    futures_wait(pending)
```

The `download_stuff` inner function and the `loop` variable are entirely removed.

**Exception behavior change:** Same as Call Sites 1 and 2 — the original propagates exceptions from `get_notes`, `add_ordinances`, and `get_contributors`; `futures_wait` does not. Add `for f in pending: f.result()` after `futures_wait` if you want errors to propagate.

### Cleaning Up After Migration

Once all three call sites are updated, `asyncio` is no longer used in `getmyancestors.py` or `classes/tree.py`. Remove the import from both files:

```python
# Remove from getmyancestors/getmyancestors.py
import asyncio  # DELETE

# Remove from getmyancestors/classes/tree.py
import asyncio  # DELETE
```

Add `MAX_WORKERS` to `getmyancestors/classes/constants.py` alongside `MAX_PERSONS` — that is already the established home for tuning constants, and `tree.py` already imports from it. `getmyancestors.py` does not currently import from `constants.py`, so the import below is a net-new line in that file:

```python
# getmyancestors/classes/constants.py
import os
MAX_WORKERS = min(32, (os.cpu_count() or 1) + 4)
```

Then in each file that needs the executor, import it:

```python
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from getmyancestors.classes.constants import MAX_WORKERS
```

### Summary

| Location | Old API | Problem | Replacement |
|---|---|---|---|
| `tree.py` `add_indis` | `asyncio.new_event_loop()` + `run_in_executor` | Resource leak, false async | `ThreadPoolExecutor` + `futures_wait` |
| `tree.py` `add_spouses` | `asyncio.get_event_loop()` + `run_in_executor` | Deprecated (3.10), crashes (3.12) | `ThreadPoolExecutor` + `futures_wait` |
| `getmyancestors.py` `download_stuff` | `asyncio.get_event_loop()` + `run_in_executor` | Deprecated (3.10), crashes (3.12) | `ThreadPoolExecutor` + `futures_wait` |

The migration removes approximately 30 lines of asyncio boilerplate and replaces it with an equivalent number of lines that are simpler, standard, and correct under Python 3.12+.

---

## 5. Structural refactoring

This section describes four structural problems in the current codebase, why each one matters, and the concrete steps to fix them. Code snippets show before/after at the level of detail needed to implement the change, not as copy-paste-ready patches.

### A. Class-level counters → Tree-owned allocator

#### Problem

`Note`, `Source`, `Indi`, and `Fam` each carry a `counter` class attribute that auto-increments in `__init__` whenever `num=` is not supplied:

```python
# tree.py — same pattern in all four classes
class Indi:
    counter = 0

    def __init__(self, fid=None, tree=None, num=None):
        if num:
            self.num = num
        else:
            Indi.counter += 1
            self.num = Indi.counter
```

Because the counter lives on the class rather than on any instance, it is shared across every `Tree` object in the process. Two `Tree` instances created in the same Python session will interleave their id sequences, producing collisions like `@I3@` referring to different individuals in different trees. The problem is latent today because the CLI creates exactly one `Tree` per run, but `mergemyancestors` already works around it by always passing explicit `num=` values — a signal that the design is known to be fragile.

#### Why it matters

- Non-reentrant design makes library use impossible. Any caller that creates more than one `Tree` — for merging, diffing, or unit testing — gets silently corrupt output.
- The workaround (`num=` everywhere) couples callers to internal sequencing logic they should not need to know about.
- Class-level mutable state is notoriously hard to reset between test runs.

#### Migration steps

1. Add four allocator methods to `Tree`:

```python
class Tree:
    def __init__(self, fs=None):
        self._indi_counter = 0
        self._fam_counter = 0
        self._note_counter = 0
        self._source_counter = 0
        # ... existing init ...

    def next_indi_id(self) -> int:
        self._indi_counter += 1
        return self._indi_counter

    def next_fam_id(self) -> int:
        self._fam_counter += 1
        return self._fam_counter

    def next_note_id(self) -> int:
        self._note_counter += 1
        return self._note_counter

    def next_source_id(self) -> int:
        self._source_counter += 1
        return self._source_counter
```

2. Change each model constructor to receive its id from the tree rather than from the class counter. Because `tree` is already a parameter in all four constructors, the `num=` branch simply calls the allocator when `num` is absent:

```python
# Before
class Indi:
    counter = 0

    def __init__(self, fid=None, tree=None, num=None):
        if num:
            self.num = num
        else:
            Indi.counter += 1
            self.num = Indi.counter

# After
class Indi:
    def __init__(self, fid=None, tree=None, num=None):
        if num is not None:
            self.num = num
        elif tree:
            self.num = tree.next_indi_id()
        else:
            raise ValueError("Indi requires either num= or tree=")
```

Note the guard change from `if num:` to `if num is not None:`. The original code uses a truthiness check, so `num=0` is silently ignored and a new id is allocated instead — a latent bug for any GEDCOM that uses index 0. The identity check closes that hole.

Apply the same pattern to `Fam` — it has the identical constructor shape and the same truthiness-zero bug:

```python
class Fam:
    def __init__(self, father=None, mother=None, tree=None, num=None):
        if num is not None:
            self.num = num
        elif tree:
            self.num = tree.next_fam_id()
        else:
            raise ValueError("Fam requires either num= or tree=")
```

Apply the same `if num is not None` / `elif tree` structure to `Note` and `Source`, but do **not** add the `raise ValueError` fallback for those two classes. Both have valid standalone uses: a `Note` can be created without a tree and appended later, and `Source` similarly. Raising unconditionally when tree is absent would break any caller that constructs them standalone. Before adding a ValueError to `Note` or `Source`, grep all callers (including any scripts outside this repo that import the package) to confirm none create them without a tree argument.

3. Remove the four `counter = 0` class attributes. They are now unused and their presence would be misleading.

4. Search for any direct reads of `Indi.counter`, `Fam.counter`, `Note.counter`, or `Source.counter` in `mergemyancestors.py` and elsewhere — there are none at the time of writing, but confirm before deleting.

5. In `mergemyancestors.py`, calls that already pass explicit `num=` values continue to work unchanged. No changes are needed there.

### B. Model constructors make live HTTP calls

#### Problem

Three places in `tree.py` issue HTTP requests from inside model construction or from methods called directly during construction:

**`Indi.add_data` (called from `Tree.add_indis`)** — lines ~354 and ~374:

```python
def add_data(self, data):
    # ...
    if "sources" in data:
        sources = self.tree.fs.get_url(
            "/platform/tree/persons/%s/sources" % self.fid
        )
        # ... process sources ...

    for evidence in data.get("evidence", []):
        memory_id, *_ = evidence["id"].partition("-")
        url = "/platform/memories/memories/%s" % memory_id
        memorie = self.tree.fs.get_url(url)   # HTTP call mid-construction
        # ...
```

**`Fam.add_marriage`** — lines ~542 and ~557:

```python
def add_marriage(self, fid):
    url = "/platform/tree/couple-relationships/%s" % self.fid
    data = self.tree.fs.get_url(url)           # first HTTP call
    if data:
        # ...
        if new_sources:
            sources = self.tree.fs.get_url(
                "/platform/tree/couple-relationships/%s/sources" % self.fid
            )                                  # second HTTP call
```

**`Fact.__init__` and `Name.__init__`** — read `tree.fs._()` (translation lookup) and `tree.places` (a dict populated by `Tree.add_indis`). These are read-only dict/method accesses rather than network calls, but they still create an implicit dependency on a live session being present during construction.

#### Why it matters

- **Testability is zero.** There is no way to instantiate an `Indi` or `Fam` with real data without a live FamilySearch session. Every unit test would need to mock the session at a low level or be skipped.
- **Error attribution is poor.** When `get_url` fails inside a constructor, the exception stack points into model internals rather than at the fetch layer where the failure actually originated.
- **The thread executor makes it worse.** `Tree.add_indis` runs `add_data` calls inside a `ThreadPoolExecutor`, so HTTP calls inside `add_data` happen on worker threads without any coordination, and retry logic in `Session.get_url` runs on those same threads.

#### Migration steps

The core principle: **fetch at the `Tree` layer, construct with data.** `Tree` already does the top-level fetch; the inner fetches need to move up to the same layer before any constructors are called.

1. **Sources for individuals.** In `Tree.add_indis`, after the batch person fetch returns, check which persons have `"sources"` in their data and fetch all source lists at that point:

```python
# Before: inside Indi.add_data
if "sources" in data:
    sources = self.tree.fs.get_url("/platform/tree/persons/%s/sources" % self.fid)

# After: in Tree.add_indis, before constructing Indi objects
person_sources = {}
for person in data["persons"]:
    if "sources" in person:
        person_sources[person["id"]] = self.fs.get_url(
            "/platform/tree/persons/%s/sources" % person["id"]
        )
```

Then pass `person_sources` into `add_data` (or into the constructor) so the method works entirely from already-fetched data.

**Performance note:** The current `add_data` calls run concurrently via the thread executor. Moving the source fetches to a serial pre-fetch loop outside that executor will lose that concurrency for the source-fetch phase. If fetch latency is a concern, consider using `ThreadPoolExecutor` with `map` over the source fetches as well. The correctness benefit (no I/O inside constructors) is the priority here, but flag the tradeoff if runtime is already a pain point.

2. **Memories for individuals.** Same approach — collect all memory URLs from the `evidence` lists before construction, fetch them, and pass the results in:

```python
# Collect memory fetches at the Tree layer
person_memories = {}
for person in data["persons"]:
    memories = []
    for evidence in person.get("evidence", []):
        memory_id, *_ = evidence["id"].partition("-")
        result = self.fs.get_url("/platform/memories/memories/%s" % memory_id)
        if result:
            memories.append(result)
    person_memories[person["id"]] = memories
```

Pass `person_memories` into `add_data` so the method no longer calls `get_url`.

3. **Marriage sources in `Fam.add_marriage`.** Move both `get_url` calls up to wherever `add_marriage` is invoked. Pass the pre-fetched relationship data and source list in as parameters:

```python
# Before
fam.add_marriage(fid)    # add_marriage fetches internally

# After — caller fetches first
rel_data = self.fs.get_url("/platform/tree/couple-relationships/%s" % fid)
sources_data = None
if rel_data and "sources" in rel_data["relationships"][0]:
    sources_data = self.fs.get_url(
        "/platform/tree/couple-relationships/%s/sources" % fid
    )
fam.add_marriage(fid, rel_data=rel_data, sources_data=sources_data)
```

`add_marriage` then accepts `rel_data` and `sources_data` as parameters and does no network I/O of its own.

4. **`Fact.__init__` and `Name.__init__`.** These read `tree.fs._()` and `tree.places`. The translation call `tree.fs._()` can be replaced by passing the resolved string in before construction — or by extracting the translation map from the session once and passing it to `Tree`. `tree.places` is already populated by the time facts are constructed, so it can be passed directly. This is a lower-priority cleanup compared to the explicit `get_url` calls, but it removes the last session dependency from inner model constructors.

### C. Session: composition over inheritance

#### Problem

`Session` inherits from `requests.Session`:

```python
# session.py line 19
class Session(requests.Session):
    def __init__(self, username, password, ...):
        super().__init__()
        self.headers = {"User-Agent": UserAgent().firefox}
        # ...
```

The subclass uses only a small slice of the parent: `.get()`, `.post()`, `.cookies`, `.headers`, and `.mount()`. Everything else on `requests.Session` — `delete`, `put`, `patch`, `options`, `head`, `send`, `prepare_request`, `resolve_redirects`, `rebuild_auth`, and many more — becomes inadvertent public API on `Session`. Any caller can invoke them without going through the retry and auth logic that `get_url` provides.

There is also a subtle correctness hazard: `Session.__init__` assigns `self.headers = {"User-Agent": ...}`, which replaces the `CaseInsensitiveDict` that `requests.Session.__init__` sets up. The code works by accident because the later `headers.update(...)` call populates the dict incrementally, but replacing the headers object is not the intended usage pattern for the parent class and could break with future `requests` versions.

#### Why it matters

- **Unintended public surface.** Callers can bypass auth/retry by calling `.get()` directly on a `Session` object. The correct entry point is `get_url`, but nothing in the type prevents misuse.
- **Fragile `__init__` interaction.** Overwriting `self.headers` after `super().__init__()` works today but is not guaranteed to remain safe as `requests` evolves.
- **Testing is harder.** Injecting a fake transport requires either subclassing or mounting an adapter, both of which depend on the full `requests.Session` machinery being present.

#### Migration steps

1. Change `Session` to hold an internal `requests.Session` rather than extend one:

```python
# Before
class Session(requests.Session):
    def __init__(self, username, password, ...):
        super().__init__()
        self.headers = {"User-Agent": UserAgent().firefox}

# After
class Session:
    def __init__(self, username, password, ...):
        self._session = requests.Session()
        self.headers = {"User-Agent": UserAgent().firefox}
        # Do NOT call self._session.headers.update(self.headers) here —
        # keep self.headers as the sole canonical header store (see step 4).
```

2. Replace every direct call to the inherited parent methods with delegation through `self._session`:

| Current call | Replacement |
|---|---|
| `self.get(url, ...)` | `self._session.get(url, ...)` |
| `self.post(url, ...)` | `self._session.post(url, ...)` |
| `self.cookies` | `self._session.cookies` |
| `self.mount(prefix, adapter)` | `self._session.mount(prefix, adapter)` |

3. The `logged` property reads `self.cookies.get("fssessionid")` — update to `self._session.cookies.get("fssessionid")`.

4. In `login`, `self.headers.update({"Authorization": f"Bearer {access_token}"})` is used to record the current auth token. After composition, keep `self.headers` (the plain dict on `Session`) as the **sole canonical header store**. Do not also update `self._session.headers`. Instead, in `get_url`, pass the merged dict as a per-request override:

   ```python
   merged = {**headers, **self.headers}  # self.headers wins; holds current Bearer token
   r = self._session.get(base + url, timeout=self.timeout, headers=merged)
   ```

   Keeping `self._session.headers` empty (or only holding non-auth defaults) and always passing headers per-request avoids the split-brain problem where `self.headers` holds the latest token but `self._session.headers` still has a stale one, or vice versa. If you instead update `self._session.headers` as the canonical store, remove `self.headers` entirely to prevent the two dicts from diverging after a token refresh.

5. Callers outside `session.py` access `Session` through a larger surface than just `get_url`, `login`, and `logged`. They also read `fs._` (the translation method), `fs.fid`, `fs.lang`, `fs.display_name`, and `fs.counter` directly. Every one of these is an attribute on the outer `Session` instance, not on `requests.Session`, so none of them move when you introduce composition — they stay exactly where callers expect them. The only things being replaced are the inherited `requests.Session` methods (`.get`, `.post`, `.cookies`, `.mount`). This change is contained in the sense that no caller signatures need updating, but do not let the audit stop at the three methods named above — verify that `fs._`, `fs.fid`, and the other instance attributes remain on the outer object after refactoring.

### D. Unbounded retry loops → bounded backoff

> **Prerequisite:** The proposed `get_url` replacement below uses `self._session.get(...)`.
> Apply section C (composition over inheritance) before applying this section, or replace
> `self._session.get(...)` with `self.get(...)` if you are applying this section independently.

#### Problem

Both `Session.login` and `Session.get_url` use `while True:` loops with `continue` on every retriable exception and no upper bound on attempts:

```python
# session.py — login (~line 74)
while True:
    try:
        # ... multi-step OAuth flow ...
    except requests.exceptions.ReadTimeout:
        self.write_log("Read timed out")
        continue                         # immediate retry, no sleep
    except requests.exceptions.ConnectionError:
        self.write_log("Connection aborted")
        time.sleep(self.timeout)
        continue
    # ...

# session.py — get_url (~line 170)
while True:
    try:
        r = self.get(base + url, timeout=self.timeout, headers=headers)
    except requests.exceptions.ReadTimeout:
        self.write_log("Read timed out")
        continue                         # immediate retry
    except requests.exceptions.ConnectionError:
        self.write_log("Connection aborted")
        time.sleep(self.timeout)
        continue
```

Problems with this pattern:

- **No termination on persistent failure.** Wrong credentials, a revoked token, or a prolonged outage will loop indefinitely. The process cannot be interrupted without `Ctrl+C` or a signal.
- **No backoff progression.** `ReadTimeout` retries immediately with no delay at all. `ConnectionError` and `HTTPError` sleep for a fixed `self.timeout` seconds every time, which creates thundering-herd behaviour when the API is degraded.
- **No jitter.** Multiple concurrent processes (e.g., two CLI runs started at the same time) will retry at exactly the same interval.
- **No user-visible signal on exhaustion.** When the loop eventually terminates (if it does), it is via `break` after success, not via a meaningful exception that callers can catch and handle.

#### Migration steps

1. Add `max_retries` to `Session.__init__` with a default of 5:

```python
def __init__(self, username, password, ..., timeout=60, max_retries=5, ...):
    self.timeout = timeout
    self.max_retries = max_retries
```

2. Replace the `while True:` loop in `login` with a counted loop and exponential backoff with jitter. Extract a helper so both methods share the same backoff logic:

```python
import random

def _backoff(self, attempt: int) -> float:
    """Exponential backoff with full jitter.
    Returns a sleep duration in seconds."""
    base = min(self.timeout, 2 ** attempt)
    return random.uniform(0, base)
```

3. Rewrite the `login` loop:

```python
def login(self):
    for attempt in range(self.max_retries):
        try:
            # ... OAuth flow ...
            if self.logged:
                self.set_current()
                return
            # If logged check fails but no exception, treat as retriable
            self.write_log("Login succeeded but session cookie not found, retrying")
        except requests.exceptions.ReadTimeout:
            self.write_log("Read timed out (attempt %d/%d)" % (attempt + 1, self.max_retries))
        except requests.exceptions.ConnectionError:
            self.write_log("Connection aborted (attempt %d/%d)" % (attempt + 1, self.max_retries))
        except requests.exceptions.HTTPError:
            self.write_log("HTTPError (attempt %d/%d)" % (attempt + 1, self.max_retries))
        except (KeyError, ValueError) as exc:
            self.write_log("%s (attempt %d/%d)" % (type(exc).__name__, attempt + 1, self.max_retries))

        sleep_for = self._backoff(attempt)
        self.write_log("Retrying in %.1fs" % sleep_for)
        time.sleep(sleep_for)

    raise RuntimeError(
        "Login failed after %d attempts. "
        "Check credentials and network connectivity." % self.max_retries
    )
```

4. Rewrite the `get_url` loop with the same structure. Distinguish between retriable failures (timeout, connection error, 5xx) and permanent failures (401 after re-login, 403, 404, 410) — the latter should return `None` or raise immediately rather than consuming retry budget:

```python
def get_url(self, url, headers=None, no_api=False):
    self.counter += 1
    if headers is None:
        headers = {"Accept": "application/x-gedcomx-v1+json"}
    headers = {**headers, **self.headers}
    base = "https://familysearch.org" if no_api else "https://api.familysearch.org"

    for attempt in range(self.max_retries):
        try:
            self.write_log("Downloading: " + url)
            r = self._session.get(base + url, timeout=self.timeout, headers=headers)
        except requests.exceptions.ReadTimeout:
            self.write_log("Read timed out (attempt %d/%d)" % (attempt + 1, self.max_retries))
            time.sleep(self._backoff(attempt))
            continue
        except requests.exceptions.ConnectionError:
            self.write_log("Connection aborted (attempt %d/%d)" % (attempt + 1, self.max_retries))
            time.sleep(self._backoff(attempt))
            continue

        self.write_log("Status code: %s" % r.status_code)

        # Permanent non-retriable responses
        if r.status_code == 204:
            return None
        if r.status_code in {404, 405, 410, 500}:
            self.write_log("WARNING: " + url)
            return None
        if r.status_code == 401:
            self.login()   # login() now raises after max_retries
            # Do NOT count this against the retry budget — the loop iteration
            # consumed a slot for the 401 itself; re-issue the URL without
            # decrementing by using a separate inner retry rather than continue.
            # Simplest approach: don't use continue here; fall through to the
            # r.raise_for_status() block, or restructure so 401 re-login retries
            # the URL once without consuming the outer attempt count.
            continue  # WARNING: if this is the last attempt, the URL is never
                      # retried after a successful re-login. Consider a dedicated
                      # reauth counter separate from the request retry budget.
        if r.status_code == 403:
            # ... existing 403 handling ...
            return None

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            self.write_log("HTTPError %d (attempt %d/%d)" % (r.status_code, attempt + 1, self.max_retries))
            time.sleep(self._backoff(attempt))
            continue

        try:
            return r.json()
        except Exception as exc:
            self.write_log("WARNING: corrupted response from %s: %s" % (url, exc))
            return None

    raise RuntimeError(
        "get_url failed after %d attempts: %s" % (self.max_retries, url)
    )
```

5. Update the CLI entry point (`getmyancestors.py`) to catch `RuntimeError` from `Session.__init__` (which calls `login`) and print a user-friendly message before exiting, rather than letting the exception propagate as an unhandled traceback.

6. Consider exposing `--max-retries` as a CLI flag so users with unreliable connections can increase the limit without editing source code.
