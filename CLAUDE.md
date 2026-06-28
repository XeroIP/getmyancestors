# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`getmyancestors` downloads family trees from **FamilySearch** (GedcomX JSON over HTTP) and writes them as **GEDCOM 5.5.1** files. It is an unofficial third-party tool that authenticates as a real FamilySearch user, not a sanctioned API integration. This repo is a fork; upstream is https://github.com/Linekio/getmyancestors.

## Commands

```bash
pip install -e .          # editable install; also registers the console scripts below
pip install -r requirements.txt

getmyancestors -i LF7T-Y4C -o out.ged -v   # download ancestors of an individual → GEDCOM
mergemyancestors -i a.ged b.ged -o out.ged # merge/de-dupe multiple GEDCOM files
```

Key `getmyancestors` flags: `-a` generations up (default 4), `-d` generations down (default 0), `-m` add spouses/marriages, `-c` LDS ordinances (needs an LDS account), `-r` contributors, `--rate-limit` max requests/sec. FamilySearch IDs must match `[A-Z0-9]{4}-[A-Z0-9]{3}`. Credentials are prompted if `-u`/`-p` are omitted.

**There is no test suite, linter config, or CI.** Verify changes by running the CLIs end-to-end against a real FamilySearch account, or by round-tripping a GEDCOM file through `mergemyancestors`. Adding tests (recorded JSON fixtures → golden GEDCOM) is high-value and currently absent.

## Architecture — the parts that require reading multiple files

**The domain model classes in `classes/tree.py` do three jobs at once.** `Indi`, `Fam`, `Fact`, `Name`, `Source`, `Note`, `Ordinance` each (1) parse FamilySearch JSON in their constructor, (2) hold state, and (3) serialize themselves to GEDCOM via a `print(file)` method. This is the single most important thing to understand before editing — there is no separation between "API client", "data model", and "GEDCOM codec".

**Parsing reaches through the model into the network.** Model constructors and methods make live HTTP calls via `self.tree.fs.get_url(...)` — e.g. `Indi.add_data` fetches sources/memories mid-construction, `Fam.add_marriage` fetches couple relationships, `*.get_notes`/`get_contributors` fetch on demand. So instantiating a model object can trigger I/O. `Fact`/`Name` also read `tree.fs._()` (i18n), `tree.places`, and `tree.sources`. Don't assume model construction is pure.

**Class-level counters are global mutable state.** `Indi.counter`, `Fam.counter`, `Note.counter`, `Source.counter` auto-assign GEDCOM ids (`@I1@`, `@F1@`, ...) on every `__init__` unless an explicit `num=` is passed. Consequences: the code is **not reentrant** (two trees in one process collide), and `mergemyancestors` only works because it passes `num=` everywhere to bypass the counters. Be very careful introducing new model instances — they consume global ids.

**GEDCOM flows in both directions through the same model classes:**
- Download/write: `Tree` (in `tree.py`) crawls FamilySearch generation-by-generation (`add_indis` → `add_parents`/`add_children`/`add_spouses`), then `reset_num()` assigns final ids and `Tree.print()` emits GEDCOM.
- Read/merge: `Gedcom` (in `classes/gedcom.py`) is a hand-rolled line-by-line parser that reconstructs the *same* `Indi`/`Fam`/etc. objects from a `.ged` file. It uses a one-line lookahead hack (`self.flag`) and slices pointers as `data[2:len-1]`. Tag↔URI mappings live in `classes/constants.py` (`FACT_TAGS`/`FACT_TYPES` are reverses of each other).

**`asyncio` here is a thread pool in disguise.** `getmyancestors.py` and `tree.py` use `loop.run_in_executor(None, blocking_fn)` to parallelize synchronous `requests` calls — it is not async I/O. Note `asyncio.get_event_loop()` is used, which is deprecated on modern Python (3.10+); be cautious touching this.

**HTTP/auth lives in `classes/session.py`.** `Session` subclasses `requests.Session`, performs the FamilySearch OAuth2 login flow (password → auth code → bearer token), and exposes `get_url()`, the single choke-point for all API reads. `get_url` retries via `while True:` loops with `time.sleep` and re-logs-in on HTTP 401; there is no max-retry bound, so a persistent failure loops forever. The default OAuth `client_id` and a third-party `misbach.github.io` redirect URI are hardcoded (overridable with `--client_id`/`--redirect_uri`).

## Entry points

Three console scripts are declared in `pyproject.toml`: `getmyancestors` and `mergemyancestors` (CLI), and `fstogedcom` (a Tkinter GUI in `fstogedcom.py` + `classes/gui.py`). **This fork intends to be CLI-only and to remove the GUI**; the GUI is a pure leaf (nothing in the core imports it) and `diskcache` is a dependency used only by it.

## i18n

Translations are a hand-rolled dict in `classes/translation.py`, looked up by `Session._()` (and a duplicate `_()` helper in the GUI). The user's language comes from FamilySearch via `Session.set_current()`.
