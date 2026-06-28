# Migration Unit 2: Replace asyncio Wrapper with ThreadPoolExecutor

## Background

The codebase uses `asyncio` in three places to parallelize HTTP-bound work. In every case the implementation follows the same pattern: an `async` inner function calls `loop.run_in_executor(None, blocking_fn)` on a set of work items, then awaits each future. This is not true async I/O — `run_in_executor` with `None` dispatches to the default `ThreadPoolExecutor`, meaning every call is a regular OS thread under the hood. The `asyncio` layer sits on top and contributes nothing except complexity and deprecation warnings.

## Why the Current Pattern Needs to Go

### 1. It is not async I/O

`loop.run_in_executor(None, fn)` offloads `fn` to a thread pool and returns a `Future` that resolves when the thread finishes. The work still blocks a thread; asyncio does not make it non-blocking. The pattern is semantically equivalent to `executor.submit(fn)` with extra steps. The only case where wrapping threads in asyncio would buy anything is when you also have genuine coroutines to interleave — there are none here.

### 2. `asyncio.get_event_loop()` is deprecated

Python 3.10 deprecated `asyncio.get_event_loop()` when called with no running event loop, emitting a `DeprecationWarning` at runtime. Python 3.12 escalated this: if there is no current event loop, the call now raises `RuntimeError` instead of silently creating one. Because this code runs as a CLI (not inside an existing async framework), there is no running loop at the call sites, so any Python 3.12 installation will crash at this call site.

`add_indis` uses the slightly different `asyncio.new_event_loop()` + `asyncio.set_event_loop(loop)` pattern, which avoids the deprecation but creates a new loop for every invocation of `add_indis()` — once per call, before the batch `while` loop, not once per batch iteration. If an exception escapes before `loop.close()` is called (and it is never explicitly called here), the loop leaks.

### 3. The code is harder to reason about than the thread-only equivalent

Nesting an `async def` inside a regular method, constructing or retrieving an event loop, and awaiting futures one at a time is substantially more code than calling `executor.map()` or collecting `Future` objects from `executor.submit()`. A reader familiar with `concurrent.futures` can understand the replacement in seconds; the asyncio wrapper requires knowing what `run_in_executor` actually does.

## The Replacement: `concurrent.futures.ThreadPoolExecutor`

`concurrent.futures.ThreadPoolExecutor` is the standard library's thread pool. It has a clean, synchronous API that does exactly what the current code does — runs blocking functions on threads and waits for them to finish — without event loop machinery.

The key methods used in the migration:

- `executor.submit(fn, *args)` — schedule a call and return a `Future`
- `concurrent.futures.wait(futures)` — block until all futures complete; unlike `await future`, this never raises — errors remain stored in the future until you call `.result()`
- `executor.map(fn, iterable)` — convenience wrapper; submit + wait in one call, raises on error

## Choosing `max_workers`

`ThreadPoolExecutor(max_workers=None)` defaults to `min(32, (os.cpu_count() or 1) + 4)` as of Python 3.8. The `or 1` guard handles the case where `os.cpu_count()` returns `None` (possible in containers or restricted environments — `None + 4` would otherwise raise `TypeError`). That default is reasonable here: the bottleneck is network I/O, not CPU, so more threads help up to the point where the FamilySearch API starts rate-limiting or the connection pool saturates. A sensible explicit value is:

```python
import os
MAX_WORKERS = min(32, (os.cpu_count() or 1) + 4)
```

If you want to expose this as a CLI option, add `--workers N` to the argument parser and pass the value through. The default above is a good starting point and does not need tuning for typical tree sizes.

## What Stays the Same

- All `requests` calls inside `Session.get_url()` — unchanged.
- The `Session.get_url()` method itself — unchanged.
- `Indi.add_data()`, `Indi.get_notes()`, `Indi.get_contributors()` — unchanged.
- `Fam.add_marriage()`, `Fam.get_notes()`, `Fam.get_contributors()` — unchanged.
- `Tree.add_ordinances()` — unchanged.
- All model classes (`Indi`, `Fam`, `Tree`) — unchanged.
- The call sites in `add_indis`, `add_spouses`, and `download_stuff` change; everything else in those methods stays the same.

## Call Site 1: `Tree.add_indis` — `getmyancestors/classes/tree.py` line ~654

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

## Call Site 2: `Tree.add_spouses` — `getmyancestors/classes/tree.py` line ~777

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

## Call Site 3: `download_stuff` — `getmyancestors/getmyancestors.py` line ~247

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

## Cleaning Up After Migration

Once all three call sites are updated, `asyncio` is no longer used in `getmyancestors.py` or `classes/tree.py`. Remove the import from both files:

```python
# Remove from getmyancestors/getmyancestors.py
import asyncio  # DELETE

# Remove from getmyancestors/classes/tree.py
import asyncio  # DELETE
```

Note that `getmyancestors/classes/gui.py` also imports `asyncio`. That file is not covered by this migration unit — audit it separately.

Add `MAX_WORKERS` to `getmyancestors/classes/constants.py` alongside `MAX_PERSONS` — that is already the established home for tuning constants, and both files import from it:

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

## Summary

| Location | Old API | Problem | Replacement |
|---|---|---|---|
| `tree.py` `add_indis` | `asyncio.new_event_loop()` + `run_in_executor` | Resource leak, false async | `ThreadPoolExecutor` + `futures_wait` |
| `tree.py` `add_spouses` | `asyncio.get_event_loop()` + `run_in_executor` | Deprecated (3.10), crashes (3.12) | `ThreadPoolExecutor` + `futures_wait` |
| `getmyancestors.py` `download_stuff` | `asyncio.get_event_loop()` + `run_in_executor` | Deprecated (3.10), crashes (3.12) | `ThreadPoolExecutor` + `futures_wait` |

The migration removes approximately 30 lines of asyncio boilerplate and replaces it with an equivalent number of lines that are simpler, standard, and correct under Python 3.12+.
