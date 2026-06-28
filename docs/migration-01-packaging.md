# Migration Unit 1 — Packaging & Dependency Management

**Scope:** Replace the implicit-setuptools `pyproject.toml` + redundant `requirements.txt` with a
fully-declared PEP 517 build backend managed by **uv**. Drop the GUI-only dependency and script
entry. The GUI removal itself is handled in a separate unit; this unit is purely about packaging
hygiene and tooling.

---

## Why uv (over Poetry or bare pip)

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

---

## What changes in `pyproject.toml`

### Before

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

### After

```toml
[build-system]
requires = ["setuptools>=70"]
build-backend = "setuptools.backends.legacy:build"

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
    "diskcache==5.6.3",
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

### Change-by-change rationale

**`[build-system]` added.**
Without this table, tools that follow PEP 517 (including uv) fall back to a legacy setuptools shim.
Declaring it explicitly makes the build reproducible and removes the implicit dependency on whatever
setuptools version happens to be installed.

**`requires-python` raised to `>=3.10`.**
The current `>=3.7` claim is inaccurate — the codebase uses patterns that break on 3.10+ without
fixes covered in the cleanup unit. Setting this to `>=3.10` matches where the code actually runs
correctly after that unit lands. (Python 3.9 reached end-of-life in October 2025.)

**`diskcache==5.6.3` dropped.**
`diskcache` is used exclusively by the GUI (`fstogedcom`). Removing the GUI in a separate unit also
removes the only call sites. Keep this line staged until that unit merges to avoid a gap where the
import exists but the package is absent.

**`[tool.setuptools.package-data]` block removed.**
The only entry was `fstogedcom.png`, the GUI icon. With the GUI gone there is nothing to bundle.

**`fstogedcom` script entry removed.**
Same reason. The entry point `getmyancestors.fstogedcom:main` will not exist after the GUI unit
lands.

**`HomePage` URL updated.**
Changed from the upstream `Linekio/getmyancestors` to `XeroIP/getmyancestors` (this fork's
location). This was missing from the original `pyproject.toml` and has no functional effect on the
package, but keeps the metadata accurate.

**`requirements.txt` deleted.**
This file was a hand-maintained duplicate of the `dependencies` list in `pyproject.toml`. It served
as a workaround for the absence of a real lock file. `uv.lock` replaces it.

---

## Lock file strategy

Commit `uv.lock` to the repository. This file is generated and updated by uv and records the exact
resolved version of every dependency (direct and transitive). Committing it means that anyone who
clones the repo and runs `uv sync` gets the identical environment — no surprises from a dependency
releasing a patch the night before you run `pip install`.

uv's lock file is human-readable and diff-friendly; dependency updates show as clear line changes.

```
# generate / update the lock file
uv lock

# install exactly what the lock file says (what you'll run daily)
uv sync
```

Do not add `uv.lock` to `.gitignore`. That would defeat the purpose.

---

## Developer workflow — before and after

### Before (bare pip)

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

### After (uv)

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

---

## Gotchas and notes

### `babelfish` is effectively abandonware

`babelfish 0.6.1` was released in 2014 and has not been updated since. It is used for language
code normalization in the GEDCOM output. The package still works, but:

- It has no maintainer activity.
- If it ever disappears from PyPI, a vendored copy or a thin replacement will be needed.
- For now, leave it pinned at `==0.6.1` and note the risk.

No action required in this unit.

### `fake-useragent` has a history of PyPI instability

`fake-useragent` fetches a list of real browser user-agent strings. Historically the package has
had PyPI publication gaps and dependency issues. `2.0.3` is the current stable release; pin it
exactly (`==2.0.3`) and do not use a loose specifier like `>=2.0`. If a future version causes
problems, the fallback is to hardcode a static user-agent string in `getmyancestors.py` and remove
the dependency entirely.

### The `dynamic` version attribute still requires setuptools

The `dynamic = ["version"]` / `version = {attr = "getmyancestors.__version__"}` mechanism is a
setuptools feature. This is fine — the `[build-system]` table now declares setuptools explicitly,
so the dependency is no longer implicit.

### Editable installs

If you want an editable install (so that changes to the source are immediately reflected without
reinstalling), use:

```bash
uv pip install -e .
```

For a personal fork you will likely always work editable.
