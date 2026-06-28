# Migration Unit 5 — Cleanup & Vestige Removal

This document covers six Python 2 / legacy vestiges that should be removed from the
`getmyancestors` codebase. The package already requires Python >=3.7 and targets only
CLI use via installed entry points, so all of these are dead code.

---

## A. `from __future__ import print_function`

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

---

## B. `sys.path.append(os.path.dirname(sys.argv[0]))` in `mergemyancestors.py`

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

```
grep -n '\bos\b' getmyancestors/mergemyancestors.py
```

If the only hit is the `import os` line itself, remove the `import os` line as well.
Based on a full read of the file, `os` is not used anywhere else, so both lines should
go.

---

## C. Eager imports in `__init__.py`

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

---

## D. `try/except TypeError` Python-version guard in `mergemyancestors.py`

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

---

## E. `requires-python` bump

**Location:** `pyproject.toml`, line 4:

```toml
requires-python = ">=3.7"
```

**Rationale for bumping:** Python 3.7 and 3.8 both reached end-of-life in June 2023.
Python 3.9 reached end-of-life in October 2025. Python 3.10 reached end-of-life in
October 2026 and is the recommended minimum: it is the boundary version for the
`asyncio.get_event_loop()` deprecation (addressed in unit 2), it is still shipped in
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

---

## F. `# coding: utf-8` headers

**Why they exist:** Python 2 required an explicit encoding declaration when source files
contained non-ASCII characters. Python 3 defaults to UTF-8 for all source files. The
comment has no runtime effect and is clutter.

**Where it appears (five files):**

| File | Line |
|---|---|
| `getmyancestors/__init__.py` | 1 |
| `getmyancestors/getmyancestors.py` | 1 |
| `getmyancestors/mergemyancestors.py` | 1 |
| `getmyancestors/fstogedcom.py` | 2 |
| `getmyancestors/classes/translation.py` | 1 |

**What to do:** Delete the `# coding: utf-8` line from each file. In `fstogedcom.py`
the shebang line (`#!/usr/bin/env python3`) sits on line 1; the coding comment is on
line 2 — remove line 2 only.

---

## Recommended removal order

To minimise merge conflicts across the units, apply these changes in this order:

1. Remove `# coding: utf-8` headers from all five files (F).
2. Remove `from __future__ import print_function` from both CLI files (A).
3. Slim down `__init__.py` to `__version__` only (C).
4. Remove `sys.path.append` and the `import os` line from `mergemyancestors.py` (B).
5. Unwrap the `try/except TypeError` block in `mergemyancestors.py` (D).
6. Bump `requires-python` in `pyproject.toml` (E).
