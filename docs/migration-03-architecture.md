# Unit 3 — Structural Refactoring

This document describes four structural problems in the current codebase, why each one matters, and the concrete steps to fix them. The audience is the repo owner doing the refactoring; code snippets show before/after at the level of detail needed to implement the change, not as copy-paste-ready patches.

---

## A. Class-level counters → Tree-owned allocator

### Problem

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

### Why it matters

- Non-reentrant design makes library use impossible. Any caller that creates more than one `Tree` — for merging, diffing, or unit testing — gets silently corrupt output.
- The workaround (`num=` everywhere) couples callers to internal sequencing logic they should not need to know about.
- Class-level mutable state is notoriously hard to reset between test runs.

### Migration steps

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

Note the guard change from `if num:` to `if num is not None:`. The original code uses a truthiness check, so `num=0` is silently ignored and a new id is allocated instead — a latent bug for any GEDCOM that uses index 0. The identity check closes that hole. Apply this same correction when updating `Fam`.

Apply the same `if num is not None` / `elif tree` structure to `Note` and `Source`, but do **not** add the `raise ValueError` fallback for those two classes. Both have valid standalone uses: a `Note` can be created without a tree and appended later, and `Source` similarly. Raising unconditionally when tree is absent would break any caller that constructs them standalone. Before adding a ValueError to `Note` or `Source`, grep all callers (including any scripts outside this repo that import the package) to confirm none create them without a tree argument.

3. Remove the four `counter = 0` class attributes. They are now unused and their presence would be misleading.

4. Search for any direct reads of `Indi.counter`, `Fam.counter`, `Note.counter`, or `Source.counter` in `mergemyancestors.py` and elsewhere — there are none at the time of writing, but confirm before deleting.

5. In `mergemyancestors.py`, calls that already pass explicit `num=` values continue to work unchanged. No changes are needed there.

---

## B. Model constructors make live HTTP calls

### Problem

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

### Why it matters

- **Testability is zero.** There is no way to instantiate an `Indi` or `Fam` with real data without a live FamilySearch session. Every unit test would need to mock the session at a low level or be skipped.
- **Error attribution is poor.** When `get_url` fails inside a constructor, the exception stack points into model internals rather than at the fetch layer where the failure actually originated.
- **The async executor makes it worse.** `Tree.add_indis` runs `add_data` calls inside `loop.run_in_executor`, so HTTP calls inside `add_data` happen on worker threads without any coordination, and retry logic in `Session.get_url` runs on those same threads.

### Migration steps

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

**Performance note:** The current `add_data` calls run concurrently via `asyncio` + `run_in_executor`. Moving the source fetches to a serial pre-fetch loop outside that executor will lose that concurrency for the source-fetch phase. If fetch latency is a concern, consider replacing the serial loop with `asyncio.gather` over a list of coroutines (one per person with sources), or use `ThreadPoolExecutor` with `map`. The correctness benefit (no I/O inside constructors) is the priority here, but flag the tradeoff if runtime is already a pain point.

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

---

## C. Session: composition over inheritance

### Problem

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

### Why it matters

- **Unintended public surface.** Callers can bypass auth/retry by calling `.get()` directly on a `Session` object. The correct entry point is `get_url`, but nothing in the type prevents misuse.
- **Fragile `__init__` interaction.** Overwriting `self.headers` after `super().__init__()` works today but is not guaranteed to remain safe as `requests` evolves.
- **Testing is harder.** Injecting a fake transport requires either subclassing or mounting an adapter, both of which depend on the full `requests.Session` machinery being present.

### Migration steps

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
        self._session.headers.update(self.headers)
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

---

## D. Unbounded retry loops → bounded backoff

### Problem

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

### Migration steps

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

5. Update the CLI entry points (`fstogedcom.py`, `getmyancestors.py`) to catch `RuntimeError` from `Session.__init__` (which calls `login`) and print a user-friendly message before exiting, rather than letting the exception propagate as an unhandled traceback.

6. Consider exposing `--max-retries` as a CLI flag so users with unreliable connections can increase the limit without editing source code.
