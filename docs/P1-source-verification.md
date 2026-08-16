# P1 source verification

PRD §16 requires each upstream's live response shape to be confirmed **before**
a parser is written for it. This records what the 2026-08-16 probes found, in
particular the places where the live services disagree with their own
documentation and with the assumptions baked into the PRD.

Every fixture under `pipelines/etl/tests/fixtures/` is a real response from
these probes, trimmed. The parsers are tested against what the services
actually return.

Scope: only the sources P1 uses. GovInfo (P3), FEC (P4), Census (P4),
clerk.house.gov (P2) and Voteview (P2) were not exercised.

---

## Congress.gov API — verified working

Key: `CONGRESS_GOV_API_KEY`, query parameter. Host `api.congress.gov`.

| Endpoint | Result |
|---|---|
| `/member`, `/member/congress/{congress}` | 200 — 537 current members in the 119th |
| `/member/{bioguideId}` | 200 |
| `/bill/{congress}` | 200 — 18,386 bills in the 119th |
| `/bill/{congress}/{type}/{number}` (+ `/actions`, `/cosponsors`, `/summaries`) | 200 |
| `/house-vote`, `/house-vote/{congress}[/{session}[/{roll}]]`, `/house-vote/{...}/members` | 200 |
| `/senate-vote`, `/senate-roll-call-vote`, `/senate-votes` | **404 — no Senate vote endpoint exists** |

### Finding 1 — the rate limit is 20,000/hour, not 5,000

The PRD, the dossier and the architecture report all state 5,000 requests/hour.
The live response says otherwise:

```
X-Ratelimit-Limit: 20000
X-Ratelimit-Remaining: 19962
```

`common.http.Fetcher` reads the header and backs off when the remaining budget
drops below a floor, rather than trusting either figure. Nothing in the code
hard-codes a quota.

### Finding 2 — House vote coverage starts at the 115th Congress (2017), not the 118th (2023)

The PRD's central risk ("하원 표결 API 베타 + 2023~ 한정") is milder than
assumed. Vote counts per Congress:

| Congress | Years | Roll calls |
|---|---|---|
| 114th and earlier | ≤2016 | 0 |
| 115th | 2017–2019 | 1,210 |
| 116th | 2019–2021 | 954 |
| 117th | 2021–2023 | 998 |
| 118th | 2023–2025 | 1,241 |
| 119th | 2025– | 645 |

These sum to exactly 5,048, the total the unscoped `/house-vote` collection
reports — so the range is complete, not a sampling artefact.

**Consequence for P2:** the Clerk XML backfill gap is 1990–2016, not 1990–2022.
Roughly six fewer years of scraping. P2 is out of scope for this session, so
this is recorded but not acted on; `HOUSE_VOTE_EARLIEST_CONGRESS = 115` in
`sources/congress_gov.py` is the only code that reflects it.

Requesting an earlier Congress returns an empty list rather than an error, so
`sync_house_votes` raises instead of silently collecting nothing.

### Finding 3 — the roster gives full state names; only member detail has the 2-letter code

`/member` returns `"state": "California"`. The `member.state` and `term.state`
columns both carry `CHECK (char_length(state) = 2)`.

The two-letter form (`stateCode`) exists only inside `/member/{bioguideId}`'s
`terms[]`, which is also the only place `congress` appears per term. So member
collection *must* be two-pass: list for discovery, detail for content. This is
not an optimisation that was skipped — the roster payload cannot populate
`term` at all.

### Finding 4 — bill summaries are HTML

`/summaries` returns `text` as `<p><strong>…</strong>…</p>` with `&nbsp;`
entities. It feeds `bill.summary_text`, which feeds a `tsvector`, so markup
would produce search matches on tag names. `parse_bill_summary` flattens it.

### Finding 5 — `bill_action`'s natural key was wrong (schema bug, fixed in migration 0002)

Two independent problems, both found by probing rather than by reading:

1. **Referrals repeat per committee.** H.R. 3746 (118th) publishes one
   2023-05-29 referral **14 times**, identical in date, code and text, differing
   only by `committees[0].systemCode` (`hsag00`, `hsap00`, `hsba00`, …).
2. **Floor actions repeat within a day.** H.RES. 5 (119th) records
   "DEBATE - The House resumed debate on H. Res. 5." at both 16:54:01 and
   17:23:52 — distinct only by `actionTime`.

Under the 0001 key `(bill_id, action_date, action_code, md5(text))` the first
case collapses 14 rows into 1 *and* aborts the bulk upsert outright
("ON CONFLICT DO UPDATE command cannot affect row a second time").

Migration 0002 adds `action_time`, `committee_id` and `source_system` to the
key. Verified across **739 actions in 15 bills** spanning the 118th and 119th:
zero duplicate keys.

### Finding 6 — the API key leaked into `source_url` (bug found during the live run)

`httpx` reports the resolved request URL including the query string, and
Congress.gov authenticates via `?api_key=`. The first live run wrote a working
credential into `provenance.source_url` — a column PRD FC-5 publishes to users
as a "view original source" link — and `httpx`'s own INFO logging printed it on
every request.

Fixed in `common.http`: `redact_url` strips credential-bearing query parameters
before the URL is stored or logged, and `configure_logging` silences httpx below
WARNING. Regression tests in `tests/test_http.py`. Verified on the final run:

```sql
SELECT count(*) FROM provenance WHERE source_url LIKE '%api_key%';  -- 0
```

---

## senate.gov roll-call XML — schema verified, access constrained

No key. Host `www.senate.gov`, behind Akamai.

| URL | Result |
|---|---|
| `/legislative/LIS/roll_call_lists/vote_menu_{congress}_{session}.xml` | 200, 153 KB (231 votes in 119-2) |
| `/legislative/LIS/roll_call_votes/vote{c}{s}/vote_{c}_{s}_{roll:05d}.xml` | 200, 29 KB |

### Finding 7 — the WAF rejects the project's honest User-Agent

`www.senate.gov` returns **403 Access Denied** to
`CivicLens/0.1 (open civic data; …)` from the development network, at every
path including `/`. It returns 200 to a Chrome User-Agent with a full browser
header set. There is no `robots.txt` (the path 404s), and the data is public
domain.

Behaviour is also rate-sensitive: repeated probes from one IP trip the block
regardless of headers, and clear after a pause.

**Decision (confirmed with the project owner): the default stays honest.**
`SENATE_USER_AGENT` overrides it. Rationale: the block may be IP+UA combined,
so an honest UA has a real chance of working from a US-hosted GitHub Actions
runner, and shipping browser impersonation by default is not something to do
silently.

**Consequence:** Senate collection cannot be smoke-tested live from this
network. The parser and loader are verified end-to-end against captured
fixtures instead (`test_load_senate_vote_from_fixture` writes a real roll call
to Postgres). **A live Senate run still needs confirming from CI or a US
network** — it is the one part of P1 not exercised against the live source.

### Finding 8 — senators are identified by LIS ID, not Bioguide

Each `<member>` carries `<lis_member_id>S428</lis_member_id>` plus name, party
and state. There is no Bioguide ID anywhere in the document.

Every table in this schema keys on Bioguide, so Senate votes cannot be loaded
without a crosswalk. `sources/legislators.py` reads it from
`unitedstates/congress-legislators`
(`legislators-current.csv` has `lis_id` for all 100 senators) — the source the
architecture report §5 already nominates for member identity.

Casts whose LIS id does not resolve are **dropped and logged**, never
name-matched: PRD FC-1 makes a missing vote preferable to one attributed to the
wrong senator.

### Finding 9 — `document_type` carries punctuation

The `<document>` element writes the bill type as `"S."`, `"H.R."`,
`"H.J.Res."`. Passing that to the `bill_type` enum raises
`invalid input value for enum bill_type: "s."`. `normalize_bill_type` strips
dots and case, and returns None for non-bill documents — many Senate roll calls
are on nominations and treaties, which must not be forced into a bill type.

Dates are stamped `"August 8, 2026,  04:36 AM"` (double space) and element text
is indented, so both need whitespace normalisation.

---

## Live run results (dev Postgres, 2026-08-16)

Small real collections against `localhost:55432/civiclens`, not fixtures:

| Job | Arguments | Result |
|---|---|---|
| `members` | `--congress 119 --limit 12` | 12 members, 12 terms |
| `bills` | `--congress 119 --limit 5` | 5 bills, 6 committees, 17 actions, 28 sponsorships |
| `votes` | `--congress 119 --session 1 --chamber house --limit 3` | 3 roll calls, 1,291 casts |
| `votes` | `--congress 118 --session 1 --chamber house --limit 2` | 2 roll calls, 873 casts |
| `votes` | `--chamber senate` | fails 403 (Finding 7), recorded as `failed` in `dataset_sync_state`, exit code 1 |

Final table counts — members exceed the 12 collected because votes and
sponsorships backfill every member they reference:

```
member 538 · term 2989 · committee 6 · bill 5 · bill_action 17
sponsorship 28 · vote 5 · vote_cast 2164 · provenance 590
```

Checks run against that data:

- **Partition routing.** `vote_cast_c118` 873 casts, `vote_cast_c119` 1,291.
  Rows reach the correct per-Congress partition through the parent table.
- **Tally integrity.** Reported `yea/nay/not_voting` on each `vote` matches a
  `GROUP BY position` count of its `vote_cast` rows exactly, for all 5 roll
  calls. Parsing and per-member loading agree independently.
- **Idempotency.** Re-running all three jobs with identical arguments left every
  table count unchanged, and the votes job reported `to_collect count=0`.
- **Provenance.** 590 rows, 590 distinct checksums, 0 containing `api_key`, all
  `r2_key` NULL (R2 unconfigured).
- **Freshness.** `dataset_sync_state` carries `last_status`, `rows_upserted` and
  `data_current_as_of` per dataset, including the Senate failure.
- **R2 degradation.** With no credentials the run logs
  `r2.not_configured … skipping raw snapshot` once and continues; provenance
  rows are still written.

---

## Not verified

- **A live Senate collection** (Finding 7). Parser and loader are fixture-verified.
- **Voteview reconciliation** — P2. Every `vote` row is written
  `is_published = false` and nothing is user-visible until that runs (PRD FC-3).
- **Long-run rate-limit behaviour.** The largest run here was a few hundred
  requests, well inside the 20,000/hour budget. The backoff path is unit-tested
  but has not been triggered against the live API.
- **GovInfo, FEC, Census, Clerk XML** — P2/P3/P4.
