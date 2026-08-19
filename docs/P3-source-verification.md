# P3 source verification

PRD §16 requires each upstream's live response shape to be confirmed **before**
a parser is written for it. This records what the 2026-08-19 probes of the
GovInfo API found — including one assumption the P0 stub carried that is simply
wrong, one place where the schema cannot hold what the source publishes, and
one byte that makes Postgres refuse the row outright.

Companion to `docs/P1-source-verification.md` and `docs/P2-source-verification.md`,
same rules: every fixture under `pipelines/etl/tests/fixtures/govinfo_*` is a
real response from these probes, and the parsers are tested against what the
service actually returns.

Scope: GovInfo `CREC` (the daily Congressional Record). `CRECB` (the bound
edition) was probed only far enough to establish that it is a different shape
and out of scope — see Finding 3. FEC and Census (P4) were not exercised.

---

## api.govinfo.gov — verified working

Key from `.env` (`GOVINFO_API_KEY`, an api.data.gov key). Both auth styles
work: `X-Api-Key` header and `?api_key=` query parameter. **The collector uses
the header**, because `source_url` is written to every row and published as a
"view original" link (PRD FC-5) — a query-string key would persist a live
credential in the database. `common.http.redact_url` would strip it; not
putting it there is better.

| Path | Result |
|---|---|
| `/collections/CREC/{modStart}[/{modEnd}]` | 200 — filtered by **lastModified** |
| `/published/{start}/{end}?collection=CREC` | 200 — filtered by **dateIssued** |
| `/published/{start}/{end}` (no `collection`) | **500**, not a validation error |
| `/packages/{id}/summary` | 200, JSON |
| `/packages/{id}/mods` | 200, XML — every granule's metadata in one response |
| `/packages/{id}/granules?pageSize=1000` | 200, JSON |
| `/packages/{id}/granules/{gid}/summary` | 200, JSON |
| `/packages/{id}/granules/{gid}/htm` | 200, `text/html` — the body text |
| `/packages/CREC-1899-01-01/summary` | 404 with a JSON message |
| `/packages/{id}/granules/NOPE/summary` | **400** `{"message":"invalid granuleId"}` |
| `/packages/{id}/granules/NOPE/htm` | **400**, not 404 |
| no key | 401 `API_KEY_MISSING` |
| wrong key | 401 `API_KEY_INVALID` |

`Fetcher` already treats 4xx as fatal-without-retry and 5xx as retryable, which
is the right split for all of the above.

**Rate limit.** `X-Ratelimit-Limit: 36000` per hour, live. api.data.gov's
documented default is 1,000/hour, so this key is on a raised GovInfo tier —
the same "trust the header, not the docs" situation as Congress.gov in P1
(header 20,000 vs documented 5,000). `Fetcher` reads the header.

**Pagination is a cursor, not an offset.** `offsetMark`, opaque, echoed back
inside the `nextPage` URL; there is no computable `offset`. `pageSize` caps at
1000 (`{"validationMessages":["pageSize must be less than or equal to 1000"]}`).
`govinfo._walk_offset_mark` parses the mark out of `nextPage` rather than
constructing one.

---

### Finding 1 — the two listing endpoints answer different questions, and only one is right for a nightly job

`/collections/CREC/{start}/{end}` and `/published/{start}/{end}?collection=CREC`
return the same package shape and look interchangeable. They are not.

A `/collections` query for **2026-01-01 → 2026-08-19** returned 185 packages
whose `dateIssued` values include **2017-04-06, 2023-02-10, 2024-09-18 and
2024-12-02**. The date range filters `lastModified`. Those are GPO's
corrections to old sittings being republished.

So:

* the **backfill** wants `/published` — "everything the 119th Congress issued";
* the **nightly job** wants `/collections` — "everything GPO has touched since
  I last looked", which is the only way a correction to a 2017 sitting is ever
  noticed.

`/published` additionally accepts `&congress=119`, which the backfill uses; a
January-2025 window with that filter returned 20 packages, and the Congress's
full run returned 351 (Finding 8).

---

### Finding 2 — the P0 stub was wrong about speaker identity, and the correction removes a whole code path

The stub `sources/govinfo.py::resolve_speaker_bioguide` carried this TODO:

> GovInfo granule metadata carries a members list with bioGuideIds for most
> modern records; older bound-record granules often carry only a printed name
> and need name+chamber+date matching against `term`.

The first half is right and the second does not apply to CREC at all. Every
`<congMember>` element in the daily Congressional Record carries a
`bioGuideId`, and it does so for as far back as the collection goes:

| Package | Granules | With a `<congMember>` | Of those, missing `bioGuideId` |
|---|---|---|---|
| CREC-1995-03-16 | 155 | 109 | **0** |
| CREC-2005-03-16 | 244 | 184 | **0** |
| CREC-2015-03-16 | 201 | 126 | **0** |
| CREC-2026-08-06 | 143 | 69 | **0** |

Across the 17-day volume sample as well: 361 granules carried a speaker,
**zero** of them by name only.

This matters beyond tidiness. A name+chamber+date resolver is the single most
error-prone component P2 had to build (`clerk_xml.NameResolver`, and
`docs/P2-source-verification.md` Finding 3 on the 2003 identifier cliff). CREC
needs none of it. `resolve_speaker_bioguide` reads an identifier or returns
nothing, and there is deliberately no fuzzy fallback to get wrong.

The printed form is carried alongside and is stored nowhere — GovInfo gives
`<name type="parsed">Ms. NORTON</name>`, `authority-lnf`, `authority-fnf` and
`authority-other`. The parser keeps them on the in-memory granule record for
debugging and drops them at the table boundary; `member` already holds the
authoritative name.

Only `role="SPEAKING"` was ever observed — 601 of 601 member elements in the
sample. The parser filters on it anyway: the attribute exists, and a granule
that merely *mentions* a member must not become that member's speech.

---

### Finding 3 — CREC begins in 1994, and the bound edition is a different shape

| Collection | Coverage | Packaging |
|---|---|---|
| `CREC` | 1994 → | one package per **day** |
| `CRECB` | historical | one package per **volume part** |

`CREC` package counts by year: 1994 → 150, 1995 → 212, 1996 → 144, 2000 → 154.

`CRECB-2000-pt6` holds **1,287 granules spanning weeks**, and adds a granule
class `ISSUE` that has no counterpart in the daily edition. Nothing in
`sources/govinfo.py` would parse it, and it is not attempted.

This is worth stating plainly because the dossier's coverage matrix says
"본회의 발언 · GovInfo(CR) · 1990s~". The daily Record's real floor is **1994**,
which is still earlier than every other source in this pipeline
(clerk.house.gov 1990, senate.gov 1989, Congress.gov House votes 2017).
`govinfo.congress_date_range` clamps to it and raises, naming CRECB, for any
Congress that ends before it.

---

### Finding 4 — package ids are not derivable from a date

Three dates in the 119th Congress carry more than one package, and 3 January
2025 shows why:

    CREC-2025-01-03-v171
    CREC-2025-01-03-v170

The outgoing Congress's final volume and the incoming one's first, published
the same day. `/published` reported one of them under `congress: 118` and the
other under `119`. 2025-03-11 carries three packages; 2026-01-03 carries two.

Package ids are therefore only ever **read from a listing**, never constructed
as `CREC-{date}`. `govinfo.dedupe_packages` collapses on the id, and a test
pins the two-volumes-one-day case specifically, because "just build the id from
the date" is exactly the simplification a later reader would reach for.

---

### Finding 5 — one granule, several speakers, and the schema has one column

`speech.bioguide_id` is a single nullable FK, which encodes "a granule is one
member's statement". Measured over the 17-day sample: **50 of 738 granules
(7.2%) name more than one speaker.** The largest seen names nine. They are
floor colloquies — an exchange published as one granule:

```json
{ "granuleId": "CREC-2026-08-06-pt1-PgS4483-8",
  "title": "Republican Party Accomplishments (Executive Session)",
  "members": [
    {"bioGuideId": "B001261", "role": "SPEAKING", "parsed": "Mr. BARRASSO"},
    {"bioGuideId": "S000148", "role": "SPEAKING", "parsed": "Mr. SCHUMER"}]}
```

A single column has three options and two of them are bad: store the
first-listed speaker (misattributes an entire exchange to whoever GPO listed
first), or store NULL (deletes from a member's profile precisely the debates in
which they spoke opposite a colleague). **Migration 0005** adds
`speech_speaker`, which stores all of them in document order.
`speech.bioguide_id` keeps a narrower meaning — the speaker when the granule
named exactly one — so the column never holds a guess, and the member profile
reads the join table.

---

### Finding 6 — 47% of the Record is nobody's statement, and that is not a matching failure

The headline attribution number over 17 sampled days:

| | Granules | Attributed | Rate |
|---|---|---|---|
| All granules | 2,302 | — | — |
| Collected (excl. Daily Digest, front matter) | 2,169 | 1,145 | **52.8%** |

By section, on the 5-day subsample where each granule was inspected:

| Section | Granules | Attributed | Rate |
|---|---|---|---|
| Extensions of Remarks | 112 | 109 | **97.3%** |
| Senate | 226 | 131 | **58.0%** |
| House | 359 | 121 | **33.7%** |

The House figure looks alarming and is not. The unattributed granules are
overwhelmingly Record content that no member spoke, and they are individually
identifiable by `subGranuleClass`:

| `subGranuleClass` | Count | What it is |
|---|---|---|
| `CASTATEMENT` | 160 | Constitutional Authority Statements filed with bill introductions |
| `ALLOTHER` | 35 | mostly clerk-read documents and messages |
| `PRAYER` / `PLEDGE` / `HJOURNAL` | 19 | the opening of a sitting |
| `CALLTOORDER` / `ADJOURNMENT` | 15 | procedural |
| `HPUBBILLS` / `SINTROBILLS` / `HADDSPONSORS` / `SCOSPONSORS` | 17 | lists of bills introduced or cosponsored |
| `EXECUTIVECOMM` / `HPUBCOMMREPORT` / `SCOMMREPORT` | 13 | committee filings |

`CASTATEMENT` alone is a third of the House shortfall: 160 boilerplate
"Constitutional Authority Statement for H.R. 5419" granules, each attached to a
bill introduction and none of them a floor statement.

Every one of these is **stored with a NULL speaker, not dropped**. They are
part of the published Record, they are searchable, and the /speeches result card
says "No speaker named in the record" rather than leaving a blank where a name
would go. `dataset_sync_state.message` records the rate on every run, so the
number stays visible long after the CI log expires:

    speaker attribution: 1145/2169 granules (52.8%) resolved to a single member

The Daily Digest is excluded by default and is the one class with a genuinely
zero rate (0 of 30): it is an editorial index of the day's business, not
speech. `--include-digest` stores it anyway for anyone who wants it.

---

### Finding 7 — the `<pre>` body is not HTML, and treating it as HTML deletes real content

`/granules/{id}/htm` returns:

```
<html><head><title>…</title></head><body><pre>
[Congressional Record Volume 172, Number 129 (Thursday, August 6, 2026)]
[Extensions of Remarks]
[Page E775]
From the Congressional Record Online through the Government Publishing Office [<a href="https://www.gpo.gov">www.gpo.gov</a>]

      INTRODUCTION OF THE PROTECTING INDEPENDENT CONTRACTORS FROM
                           DISCRIMINATION ACT
…
```

Counting every angle-bracket token inside `<pre>` over 460 granules:

| Token | Count | What it is |
|---|---|---|
| `<a …>` / `</a>` | 465 / 465 | the only real HTML — GPO's own gpo.gov citation |
| `<bullet>` | 33 | Record typesetting |
| `<SUP>` / `</SUP>` | 12 / 10 | superscript |
| `<INF>` / `</INF>` | 6 / 1 | subscript |
| `<gr-thn-eq>`, `<plus-minus>` | 1, 1 | typeset symbols |
| `<$1,000/polar..........` | 1 | **literal table text, not a tag** |

Zero HTML entities were found in 460 granules — GPO does not escape, which the
`<$1,000/polar` row proves outright. So `html.unescape` is not applied, and the
obvious `re.sub(r"<[^>]+>", "", body)` is not used either: it would silently
delete a dollar figure out of a table. `extract_text` removes the anchor tag
and nothing else in that family. Note the tag counts do not balance (`<SUP>` 12
vs `</SUP>` 10) — another reason not to treat this as markup.

**The boilerplate header is stripped.** Those four lines open every granule
identically. Left in, they would put "Congressional Record", "Government
Publishing Office" and "www.gpo.gov" into all ~49,000 search vectors, where
they can only ever match everything. Stripping is anchored on the sentinel line
`From the Congressional Record Online`, not on a line count: **8 of 460**
granules carry a five-line header, and a fixed count would have eaten a line of
speech from each of them. When the sentinel is absent the body is returned
untouched — losing text is worse than keeping a header. The unmodified response
is what goes to the R2 snapshot, so nothing here is lossy for provenance.

**Everything else is stored verbatim**, including the Record's fixed-width line
breaks and indentation. Whitespace is collapsed only in the display excerpt and
the search snippet, in SQL, at read time.

---

### Finding 8 — NUL bytes, and Postgres refuses the row

`CREC-2026-08-06-pt1-PgD817` — a Daily Digest granule — contains **505 NUL
bytes** in its live response, as trailing padding after a paragraph:

```
introduced, as follows: S. 5273-5358, S.J. Res. 209-211, and S. Res.
832-841.\x00\x00\x00\x00\x00\x00…
```

Postgres `text` cannot store a NUL at all. psycopg raises
`PostgreSQL text fields cannot contain NUL (0x00) bytes` and the whole batch
INSERT fails — no partial write, no degraded row, just a dead package.

Prevalence, over 381 granules across three days:

| Class | With NUL |
|---|---|
| `DAILYDIGEST` | **9 / 18** |
| `EXTENSIONS` | 0 / 63 |
| `HOUSE` | 0 / 147 |
| `SENATE` | 0 / 171 |

So the default collection scope never meets it, and `--include-digest` breaks
the moment it is used. `extract_text` drops `\x00` and only `\x00`; the other
C0 bytes the Record's typesetting uses — form feed `0x0C` (3 occurrences),
`0x14` (3) — store fine and are kept. An integration test drives the real
NUL-bearing fixture through a real Postgres.

---

## Volume, measured rather than assumed

Deployment-Architecture-Report §6 warns that the Congressional Record is
"대용량 텍스트" without saying how large. This is the measurement, and P2's rule
applies: nothing is estimated from a range nobody walked.

**The 119th Congress, counted.** Every package listed via `/published` with
`congress=119`, then its `/summary` and granule count fetched — 351 pairs of
requests:

| | |
|---|---|
| Packages (sitting days published) | **351** |
| Printed pages | **26,985** |
| Granules | **52,265** |
| Granules per package | mean 148.9, median 136 |
| Pages per package | mean 76.9, median 61 |

After excluding the Daily Digest and front matter (94.2% of granules survive),
roughly **49,000 rows** would land in `speech`.

**Bytes, from 17 fully-downloaded days.** Twelve of them stratified across the
whole page-count distribution (6 pages to 225), plus five picked by hand:

| | |
|---|---|
| Granules downloaded | 2,302 |
| Median granule | **1.8 KB** |
| Mean granule | ~5 KB |
| Largest granule | **2.8 MB** — a consolidated-appropriations explanatory statement |
| Collected text per printed page | **12,189 bytes** |

→ **~329 MB of raw text for the 119th Congress.**

The distribution is what makes the mean untrustworthy on its own: the median
granule is 1.8 KB and two granules on 2026-01-22 (an appropriations day)
account for 4.1 MB between them. Sizing from pages rather than from a granule
average is what keeps those days from being either ignored or extrapolated
across the whole Congress.

On disk this is less than 329 MB — Postgres TOASTs and pglz-compresses `text`,
and English prose compresses roughly 3×; against that, the GIN index on
`search_tsv` adds its own weight. Call it a few hundred MB all told, which is
comfortably inside Neon's metered storage at $0.35/GB-month and would not fit
the 0.5 GB free tier with much room to spare.

**Time.** Collection measured at ~4.2 requests/second sustained with no added
delay (1,576 requests in 375 s), well under the 36,000/hour ceiling. One
package costs 1 MODS request plus one request per granule, so metadata is 0.7%
of the traffic and everything else is text:

| Run | Requests | Wall clock |
|---|---|---|
| 119th backfill | 351 + 52,265 ≈ **52,600** | **~3.5 h** at 4.2 req/s |
| Nightly, 7-day window | ~7 + text for what moved | minutes |
| Weekly 400-day sweep | ~351 + text for what moved | minutes |

**Whole-history extrapolation, for the record.** CREC averages ~170 packages a
year over 1994–2026, so the full collection is roughly **5,500 packages, 800k
granules and 5 GB of text** — about 15× the 119th. That is the number behind
the scope decision below, and it is an extrapolation, labelled as one.

---

## The scope decision: the 119th Congress only

**Collect the 119th (2025-01-03 →) in full, verify, then decide about history
separately.** This follows P2's pattern and the measurements support it:

1. **One Congress is already a multi-hour, out-of-CI job.** 52,600 requests at
   ~3.5 hours fits inside the 6-hour hosted-runner cap only with no margin, and
   Deployment-Architecture-Report §1b already rules that class of job out of
   GitHub Actions. It runs from a developer machine, like the P2 Clerk
   backfill. The full history at ~15× would be **two days of continuous
   requests and ~5 GB**, which is a storage-tier decision, not a collection
   decision.

2. **The acceptance criterion only asks for one.** PRD FR-S1's 수용기준 is
   "최근 회기 발언이 의원 프로필과 검색에 노출" — the most recent Congress,
   visible in the profile and in search. The 119th satisfies it exactly.

3. **The 119th is the Congress the rest of the site is about.** Members, terms
   and House votes are already collected for it; the profiles that gain a
   populated Speeches tab are current members'. A 1990s speech has no member
   page to hang on until the roster backfill catches up.

4. **Nothing about the shape changes with age.** Finding 2 checked 1995, 2005
   and 2015: same granule classes, same `bioGuideId` coverage. So the history
   is a *volume* decision to be taken later on storage grounds, not a
   *feasibility* one that needs re-verifying. `civiclens-etl backfill-speeches
   --congress N` already takes any Congress back to 1994.

**Expected cost of the chosen scope:** ~49,000 `speech` rows, ~329 MB of text,
~3.5 hours of one-off collection, then minutes a night.

---

## What the run found

_Filled in from the actual 119th backfill; see the commit that adds it._

---

## Not verified

* **CRECB** beyond establishing its packaging (Finding 3). Any pre-1994
  collection needs its own verification pass.
* **The GovInfo bulk-data repository** (`govinfo.gov/bulkdata`), which the P0
  module docstring suggested for large volumes. The API path was measured and
  is fast enough for one Congress; bulk data becomes worth verifying if the
  full 1994– history is ever collected.
* **`/related`**, which every granule summary links. It would connect a
  statement to the bills it references — a real feature, and out of P3 scope.
* **FEC and Census** (P4).
