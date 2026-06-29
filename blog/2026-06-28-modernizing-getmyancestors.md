# Modernizing getmyancestors: from a fragile GEDCOM scraper to an LLM-ready family-history exporter

*28 June 2026 — the inaugural article, covering everything since this fork diverged from [Linekio/getmyancestors](https://github.com/Linekio/getmyancestors).*

`getmyancestors` is an unofficial command-line tool that logs into FamilySearch as a real user, walks your family tree generation by generation, and writes it out as a GEDCOM file. It's genuinely useful and genuinely unglamorous: a few thousand lines of Python where the domain model, the API client, and the GEDCOM serializer are all the same classes. This fork exists to (a) keep it working against a moving target, and (b) bend it toward a use the original authors never imagined — feeding your family history to an LLM.

This first article is a catch-up. It covers the whole arc of the fork, grouped by theme rather than commit order, and gets into the technical weeds where it's interesting.

---

## Part 1 — Keeping the lights on

FamilySearch is not a stable public API; it's a website with an authentication flow that changes, and the tool impersonates a browser to use it. A large share of the fork's early work is simply *making it still run*:

- **Auth flow rewrite** (`session.py`, +32 lines). The OAuth2 password → authorization-code → bearer-token dance was updated to match FamilySearch's current `ident.familysearch.org` endpoints.
- **Base URL update.** A one-line change with outsized impact — point the client at the endpoint that still answers.
- **A fake user agent** (`fake-useragent` dependency). FamilySearch began rejecting requests without a browser-like `User-Agent`; the session now mounts a randomized Firefox UA string.
- **`openid` scope on the authorization request** (fixing upstream issue #80). A single token added to the OAuth `scope` parameter — without it, the OIDC flow stopped yielding a usable code.
- **babelfish pinned for Python 3.12+.** The old `babelfish` pin wouldn't install on modern interpreters; bumped so the package builds at all.
- **GEDCOM version fix.** A correctness nudge to the version stamp the writer emits (`5.5.1`).

None of these are glamorous, but collectively they're the difference between a tool that works and a museum piece. The lesson of an unofficial API client is that **most of your maintenance budget goes to staying logged in.**

---

## Part 2 — Quality-of-life features

Two user-facing additions landed on top of the life-support work:

- **A conditional rate limiter** (`--rate-limit`, via `requests-ratelimiter`). When set, a `LimiterAdapter` is mounted on the session so requests are throttled to N/second. This matters more than it sounds: a deep crawl fires hundreds of requests, and FamilySearch will start returning `429 Too Many Requests` and `503`s, at which point the (unbounded) retry loop sleeps and the whole run stalls. The rate limiter trades a little steady-state speed for not hitting the wall.
- **Immigration events.** A one-line addition to the fact-type table in `constants.py` mapping `http://gedcomx.org/Immigration` → the GEDCOM `IMMI` tag, so immigration facts survive the round trip instead of being silently dropped.

---

## Part 3 — Writing things down

Before changing much, this session added two documents:

- **`CLAUDE.md`** — operational notes for anyone (human or AI) working in the repo: the three-jobs-at-once nature of the model classes, the global-counter reentrancy hazard, the fact that model constructors make live HTTP calls, and the asyncio-as-thread-pool reality.
- **`MIGRATION.md`** — a six-section plan for the targeted refactor the codebase deserves but hasn't had: removing the dead Tkinter GUI, clearing Python-2 vestiges, moving to `uv`, replacing the deprecated `asyncio.get_event_loop()` usage with a plain `ThreadPoolExecutor`, breaking the network-in-constructors coupling, and bounding the retry loops. It's a plan, not yet executed — deliberately, so the structural work doesn't get tangled with feature work.

The headline conclusion of the assessment: **this is "ugly but correct" code, and the right move is targeted refactoring, not a rewrite.** The weird branches in `tree.py` and `gedcom.py` encode hard-won GEDCOM 5.5.1 and FamilySearch edge cases; a from-scratch rebuild would rediscover them all through bug reports.

---

## Part 4 — The main event: Markdown narrative export for LLMs

This is the feature that motivated the fork's current direction ([PR #7](https://github.com/XeroIP/getmyancestors/pull/7)). The goal stated plainly: *export my family history so I can use it with an LLM — to find stories about my ancestors, and to find more ancestors.*

### Why not GEDCOM

GEDCOM is the wrong format for an LLM. It's pointer-based (`1 FAMS @F3@` instead of "married to Jane Doe"), its `CONC` line-wrapping splits words mid-token at a 255-byte boundary, and it's structurally noisy. An LLM *can* parse it, but you're spending tokens and inviting confusion. So instead of converting GEDCOM, we added a **second writer alongside it** — the crawl pipeline is identical; only the final serialization differs. That's why the writer lives in its own `classes/narrative.py` and the CLI gained `-f/--format {gedcom,markdown}` (default `gedcom`, so nothing existing changed).

### What it produces

One Markdown section per person: name with lifespan, vital facts, other life events, **parents/spouses/children resolved to names** (with in-document anchor links), notes, stories, and memories inline, plus a FamilySearch deep-link. Then a **Research frontier** section — the payoff for "find more ancestors" — which scans every individual and splits them into:

- **Brick walls** — people with *no parents recorded in FamilySearch* (`indi.parents` is empty). Genuine research dead-ends, listed with their birth date/place to seed a search.
- **Not yet downloaded** — people whose parents *do* exist in FamilySearch but weren't pulled because the `--ascend` depth cut the crawl short. This is also how you discover how deep your tree goes: when this list is empty, you've reached the data's true edge.

### Getting all the stories: memories pagination

The original code harvested memories only from a person's `evidence` array, fetching each via `/platform/memories/memories/{id}`. Checking the live FamilySearch docs revealed two problems: memories *not* linked as evidence were missed entirely, and the proper endpoint — `GET /platform/tree/persons/{id}/memories` — is **paged at 25**. So `Indi.get_memories()` now walks that endpoint with `start`/`count`, stopping when a short page arrives, deduping by artifact id, and routing `text/plain` artifacts to notes (life stories) and the rest to media objects. A nice side effect: on a real 128-person tree this *cut* total requests ~40% (one paged call per person instead of dozens of individual evidence fetches) while surfacing richer memory titles — and it correctly paged through one ancestor with **166** memories.

### Feedback without the firehose: a progress bar

Verbose mode (`-v`) prints one line per HTTP request — hundreds of them. Without it, the long notes/memories phase ran *silently* for a minute. The fix is an in-place progress bar (`render_progress`, stdlib only — no new dependency) driven by `asyncio.as_completed` over the download futures, since that phase has a known total. It self-disables when stderr isn't a TTY (so redirected logs stay clean) and under `-v` (where the trace already shows progress). Logging now has three clear modes: default (milestones + bar + summary), `-v` (full trace on screen), and `-l FILE` (full trace to a file — pair with the default for a clean screen *and* a complete audit log).

### Bugs the synthetic tests couldn't catch

Two defects only surfaced against a real export, a good reminder that fixtures lie:

- **Duplicate parents** — a person with multiple parent-relationship records sharing a father listed him twice; fixed with a `seen` set.
- **Raw dates** — FamilySearch sometimes stores a formal `19800811`; now formatted as `11 August 1980`, while year-only and already-readable dates are left untouched.

And one inherited cosmetic wart fixed along the way: the ungrammatical `Downloading 1. of generations of ancestors...` became `Downloading generation 1 of ancestors...` (with the i18n key renamed consistently so the French translation stays mapped).

### Results

On a real six-generation pull: 128 individuals, 67 families, 457 titled memories, life sketches rendering as readable prose, and a research frontier of 13 true brick walls vs. 53 "go deeper" — in 43 seconds with a clean progress bar.

---

## What's next

The export is working and feeding an LLM today. The backlog, roughly in priority order: a `--format json` companion for programmatic/analytical use; record-hint enrichment for the research frontier (phase 2 of "find more ancestors"); an `--ascend-all` mode so you don't have to guess depth; and finally executing the `MIGRATION.md` refactors to pay down the structural debt now that the feature direction is clear.

The throughline of this whole effort: **respect the encoded knowledge, fix what's broken, and add the thin new layer that serves the actual goal.** No rewrite required.
