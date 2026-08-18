# P2 source verification

PRD §16 requires each upstream's live response shape to be confirmed **before**
a parser is written for it. This records what the 2026-08-17/18 probes of
clerk.house.gov and Voteview found — including three places where the shape
changes mid-range, and one where following the obvious key would have silently
compared the wrong roll calls to each other.

Companion to `docs/P1-source-verification.md`, same rules: every fixture under
`pipelines/etl/tests/fixtures/` is a real response from these probes, and the
parsers are tested against what the services actually return.

Scope: clerk.house.gov (the House backfill) and Voteview (reconciliation).
GovInfo (P3), FEC (P4) and Census (P4) were not exercised.

---

## clerk.house.gov roll-call XML — verified working

No key. Host `clerk.house.gov`, path `/evs/{year}/`. The project's honest
default User-Agent was accepted on every one of the ~250 probe requests; there
is no WAF problem here of the kind senate.gov has (P1 Finding 7).

| Path | Result |
|---|---|
| `/evs/1989/index.asp`, `/evs/1989/roll001.xml` | **404 — the Clerk starts at 1990** |
| `/evs/{1990..2016}/index.asp` | 200, `text/html` |
| `/evs/{year}/ROLL_{n00}.asp` | 200, `text/html` — 100-roll block pages |
| `/evs/{1990..2016}/roll{nnn}.xml` | 200, `text/xml` |
| `/evs/1990/roll999.xml` (nonexistent roll) | 404 with an HTML error body |

### Finding 1 — the backfill window is 1990–2016, and both ends are measured

The lower bound is not a policy choice: `evs/1989/` does not exist. senate.gov
publishes the 101st Congress's FIRST session (1989); the Clerk's earliest year
is 1990, the 101st's SECOND session. `.env`'s `ETL_BACKFILL_FROM_CONGRESS=101`
is therefore correct for both chambers, but it means different things in each —
the Senate gets both sessions of the 101st, the House only the second.

The upper bound is P1 Finding 2: Congress.gov's House Votes beta serves the
115th Congress (2017) onward. So the two sources meet exactly at the 2016/2017
boundary with no overlap:

| Source | Congresses | Years |
|---|---|---|
| clerk.house.gov | 101 (2nd session) – 114 | 1990–2016 |
| Congress.gov beta | 115 – | 2017– |

`clerk_xml_sync.backfill` refuses a `--to-year` past 2016 rather than letting
the two paths write the same roll call by different routes. (The natural key
`(congress_no, chamber, session, roll_number)` would make that idempotent
anyway, but two collectors racing to define one row is not a property worth
relying on.)

**Size of the range, counted rather than estimated.** Walking every year's
index pages: **17,433 roll calls**, with each year's numbering contiguous from
1 with no gaps.

| Era | Years | Roll calls | Identity |
|---|---|---|---|
| pre-`name-id` | 1990–2002 | 7,327 | resolved from the Congress.gov roster (Finding 3) |
| `name-id` | 2003–2016 | 10,106 | Bioguide ID on every cast |

At ~434 casts per roll call that is roughly **7.6 million `vote_cast` rows**,
which at a rough 120 bytes of heap plus three indexes lands near **1.5–2 GB**.
Worth knowing before pointing the job at a database with a storage tier.
Busiest years: 2007 (1,186), 2009 (991), 2011 (949), 1995 (885).

### Finding 2 — year → (Congress, session) is exact, and the documents say so themselves

Every roll-call document carries `<congress>` and `<session>`. Checked against
the first roll call of all 29 years 1990–2018:

| Year | `<congress>` | `<session>` | First roll call |
|---|---|---|---|
| 1990 | 101 | 2nd | 23-Jan-1990 |
| 1991 | 102 | 1st | 3-Jan-1991 |
| … | … | … | … |
| 2016 | 114 | 2nd | 5-Jan-2016 |
| 2017 | 115 | 1st | 3-Jan-2017 |

No January carry-over anywhere in the range: the first roll call of every odd
year already belongs to the incoming Congress. The P0 stub anticipated having
to handle a lame-duck vote in early January landing in the outgoing Congress's
second session; it does not occur. `congress_and_session_for` still computes the
mapping, but only to CHECK the document — a mismatch raises rather than being
quietly corrected.

### Finding 3 — the identifier cliff at 2003

**This is the finding that shapes the whole module.** `<legislator>` gained a
`name-id` attribute — a Bioguide ID — between 2002 and 2003:

```xml
<!-- 2003 onward -->
<legislator name-id="A000374" sort-field="Abraham" unaccented-name="Abraham"
            party="R" state="LA" role="legislator">Abraham</legislator>

<!-- 1990–2002: no identifier of any kind -->
<legislator party="D" state="NY" role="legislator">Ackerman</legislator>
<legislator party="D" state="TX" role="legislator">Andrews (TX)</legislator>
```

Sampled four roll calls per year across 1990–2016: `name-id` is absent from
every cast in 1990–2002 and present on every cast in 2003–2016 (0 missing).
So the 2003+ half of the backfill needs no identity work at all, and the
1990–2002 half needs all of it.

**How the pre-2003 names are resolved.** Against the **Congress.gov** roster for
the same Congress (`/member/congress/{congress}`), which is tier-1 and is
already the source of `member`. Deliberately NOT against Voteview, even though
Voteview's `HSall_members.csv` has a clean term-scoped ICPSR↔Bioguide crosswalk:
Voteview is the independent check on this data (FC-2), and using it to supply
the identities would make the reconciliation compare the data against itself.

**Measured resolution rate.** Over all 5,692 distinct (year, state, label)
triples in 1990–2002:

| Rung | Resolved | Cumulative |
|---|---|---|
| exact folded surname | 5,594 | 98.28% |
| + surname as any token of the roster name | +54 | |
| + surname as a prefix of the roster surname | +12 | |
| + given name narrowed by prefix, then initials, then first initial | +12 | **99.65%** |
| ambiguous — dropped | 18 | |
| unresolved — dropped | 2 | |

Folding strips accents and punctuation because the two sides spell the same
person differently: Clerk "Velazquez" vs Congress.gov "Velázquez",
"Jackson-Lee" vs "Jackson Lee", "Romero-Barcelo" vs "Romero-Barceló". The token
and prefix rungs exist for members Congress.gov files under a later name than
the one they served under — "Lambert" (Blanche Lambert → "Lincoln, Blanche
L."), "Chenoweth" → "Chenoweth-Hage, Helen", "Bono" → "Bono Mack, Mary",
"Greene" → "Waldholtz, Enid Greene".

**What is left over is dropped, not guessed.** The residue is six people, all
the same shape — two members sharing a surname and a state, with a Clerk label
that names neither given name:

| Label | State | Candidates |
|---|---|---|
| `Molinari` (1990) | NY | Guy Molinari (resigned Jan 1990) / Susan Molinari (elected Mar 1990) |
| `Smith (OR)` (1990) | OR | Robert Smith / Denny Smith |
| `Capps` (1997–98) | CA | Walter Capps (died Oct 1997) / Lois Capps (Mar 1998) |
| `Miller (FL)` (2001) | FL | Dan Miller / Jeff Miller (elected Oct 2001) |
| `Shuster` (2001–02) | PA | Bud Shuster (resigned Feb 2001) / Bill Shuster (May 2001) |
| `Lambert` (1993–94) | AR | serving surname Congress.gov does not record at all |

Most of these are a predecessor and the successor who replaced them mid-year,
so the vote DATE would separate them — but Congress.gov dates terms only to the
year (`startYear`/`endYear`), so it cannot. Attributing the cast to a coin-flip
is exactly the fabrication FC-1 forbids, so the cast is dropped, counted, and
reported in `dataset_sync_state`.

One rung does survive, and uses nothing but the roll call itself: if the same
document elsewhere names "Miller, Jeff" unambiguously, a bare "Miller (FL)" in
that document cannot also be him. `parse_vote_members` resolves the unambiguous
labels first and eliminates them from the ambiguous ones' candidate pools.

### Finding 4 — Delegates are stamped `state="XX"` in 1993–94

The territorial Delegates vote in the Committee of the Whole and appear in
Clerk roll calls. In 1993–94 the Clerk gave them no state at all:

```xml
<legislator party="D" state="XX" role="legislator">Norton (DC)</legislator>
<legislator party="D" state="XX" role="legislator">de Lugo (VI)</legislator>
```

The real jurisdiction is in the parenthesis. `parse_clerk_label` reads it from
there when the attribute is uninformative, and `vote_cast.state` stores NULL
rather than the literal "XX", which would pass the two-character CHECK and mean
nothing.

### Finding 5 — the cast vocabulary is six words, plus candidate names

Across the sampled range: `Yea`, `Nay`, `Aye`, `No`, `Present`, `Not Voting`.
A `YEA-AND-NAY` vote says Yea/Nay; a `RECORDED VOTE` says Aye/No. All six
already map onto the `vote_position` enum via `base._POSITION_BY_TEXT`.

The exception is an Election of the Speaker, where members call out a candidate
name — 2015 roll 581 records `Ryan (WI)` 236, `Pelosi` 184, `Webster (FL)` 9,
`Colin Powell` 1, `Cooper` 1, `Lewis` 1, `Not Voting` 3. Those go verbatim to
`vote_cast.raw_position` with `position = NULL`, exactly as the Congress.gov
path already does (migration 0003).

Optional metadata elements vary too: `amendment-num`/`amendment-author` appear
from 1990, disappear when a vote has no amendment, and `committee` appears from
2008. All are read with `findtext`, which returns None for an absent element.

### Finding 6 — `action-time` carries a zone, and it is not UTC

```xml
<action-time time-etz="18:57">6:57 PM</action-time>
```

`time-etz` is Eastern, stated. `vote_datetime` is a TIMESTAMPTZ, so the parser
combines the date with that attribute under `America/New_York` — stamping it
with the collector's local zone would record a time the House never voted at,
and treating it as UTC would move every vote five hours. If the zone database
is unavailable the column is left NULL rather than filled with a naive guess.

### Finding 7 — the year index is paginated, and roll numbers live only in a query string

`index.asp` inlines the newest 100-roll block and links the rest as
`ROLL_000.asp` … `ROLL_500.asp`. Roll numbers appear nowhere as data — only as
`href=".../vote.asp?year=1990&rollnumber=536"`. `list_roll_numbers` walks the
block pages and extracts them, rather than reading the highest number and
counting up to it: a gap in the range would then become a 404 the caller has to
swallow, and swallowing it would also swallow a genuine fetch failure.

---

## Voteview — verified working

No key. Host `voteview.com`, path `/static/data/out/`.

| File | Size | Result |
|---|---|---|
| `members/HSall_members.csv` | 6.2 MB | 200 |
| `rollcalls/HSall_rollcalls.csv` | 29.5 MB | 200 |
| `votes/HSall_votes.csv` | **701 MB** | 200 |
| `rollcalls/{H,S}{congress}_rollcalls.csv` | ~100 KB | 200 |
| `votes/{H,S}{congress}_votes.csv` | ~8 MB | 200 |

### Finding 8 — use the per-Congress files

`HSall_votes.csv` is 701 MB; `H101_votes.csv` is 8 MB and carries the same rows
for that Congress. The reconcile job downloads `HSall_members.csv` once (the
crosswalk spans every Congress a run touches) and then one rollcalls file and
one votes file per (Congress, chamber).

Note `H{congress}_rollcalls.csv` contains **only** House rows; the Senate is in
the `S`-prefixed file. The `chamber` column is still checked, because a file
being single-chamber is not something to rely on silently.

### Finding 9 — `rollnumber` is NOT the chamber's roll number

The obvious join is wrong. Voteview numbers a chamber's roll calls continuously
across a whole Congress; the Clerk and the Senate restart the count each
session. Voteview also omits quorum calls, so the two sequences diverge from
the very first row:

| Congress | Voteview `rollnumber` 1 | `session` | `clerk_rollnumber` |
|---|---|---|---|
| H104 | 1 (1995-01-04) | 1 | **2** |
| H108 | 1 (2003-01-07) | 1 | **2** |
| H114 | 1 (2015-01-06) | 1 | **2** |
| H114 | 1322 (2016-12-08) | 2 | **622** |

Joining on `rollnumber` would have compared entirely different roll calls to
each other and produced a review queue full of nonsense. `parse_rollcalls` keys
on `(congress, chamber, session, clerk_rollnumber)` instead, which is our
natural key exactly.

`session` and `clerk_rollnumber` are populated for every Congress from the
101st **except the 101st's first session (1989)** — 368 House roll calls with
both fields blank. That is outside the backfill window, so nothing is lost; the
parser drops rows without both fields rather than falling back to `rollnumber`.

Both fields are written as floats in the older files (`"2.0"`, `"536.0"`) and as
integers in the newer ones. `_to_int` reads either.

### Finding 10 — compare the COLUMNS, not counts derived from cast codes

`yea_count`/`nay_count` in `*_rollcalls.csv` reproduce the chamber's official
tally. Counts derived from `*_votes.csv` cast codes do not. Checked over 44
roll calls spanning 1990, 1996, 2004 and 2016:

| Year | Agree on yea+nay+date (columns) | Notes |
|---|---|---|
| 1990 | 9 / 11 | 2 genuine one-vote disagreements |
| 1996 | 11 / 11 | |
| 2004 | 11 / 11 | |
| 2016 | 11 / 11 | |

Derived counts drifted on most roll calls, in two predictable ways:

* **Announced and paired votes.** Codes 2/3 (announced/paired Yea) and 4/5
  (announced/paired Nay) are positions the chamber does NOT record as votes —
  the Clerk files those members under "Not Voting". They exist only in the
  early era: 1,988 of 380,634 casts in the 101st (0.52%), and none at all from
  the 104th on.
* **Members who did not vote.** The Clerk omits them from the document
  entirely; Voteview records them as code 9. This is why derived
  `not_voting` runs 1–2 above ours on a typical roll call — usually the
  Speaker, who by custom does not vote.

So `TALLY_FIELDS = ("yea_count", "nay_count")` and nothing else. There is no
official present/not-voting column in Voteview to compare against, and
comparing the derived ones would have flagged a convention as an error on a
large fraction of roll calls — hiding most of the site under FC-3.

**Amended 2026-08-18, after the first full run.** "The columns reproduce the
chamber's official tally" holds only where Voteview's ROSTER is complete. Its
columns count the members it carries, so a member it has never heard of moves
every tally that member voted in. In the 101st that is 124 roll calls — see
finding 14, which is what the 44-roll-call survey was too small to see.

Per-member comparison is restricted for the same reason: only codes 1 (Yea),
6 (Nay) and 7/8 (Present) are compared, and only for members present on both
sides.

### Finding 11 — WITHDRAWN: the two 1990 "disagreements" are finding 14

The 2026-08-17 probe reported these as genuine:

| Roll call | Clerk | Voteview |
|---|---|---|
| 1990 roll 400 (101/2) | yea 194, nay 229 | yea **193**, nay 229 |
| 1990 roll 450 (101/2) | yea 162, nay 248 | yea **161**, nay 248 |

They are not. Both are one yea, both are dated after 22 September 1990, and
both are Patsy Mink — a member Voteview does not carry for the 101st Congress
at all (finding 14). The dates and the key were checked; the ROSTER was not.

Roll 400 stays a fixture, and is now the test for the opposite property: the
same numbers are a disagreement when nothing is known about who is missing,
and not a disagreement once `covered_members` says Voteview has no 101st row
for `M000797`.

### Finding 12 — quorum calls have no counterpart, and that is not a discrepancy

Voteview indexes votes, not quorum calls. Roll 1 of most years is a `QUORUM`
call and is simply absent from `*_rollcalls.csv`. Voteview also republishes on
its own schedule: on 2026-08-17 its newest House roll call was 2026-07-23,
three and a half weeks behind the chamber.

Both are coverage gaps rather than disagreements, and both are why FC-3 is
implemented as "publish unless contradicted" rather than "withhold until
confirmed" — see `packages/db/migrations/0004_fc3_publish_unless_contradicted.sql`
for the full argument.

### Finding 13 — the ICPSR ↔ Bioguide crosswalk is clean

Over Congresses 101–119, 10,432 member-Congress rows:

* 0 rows missing `bioguide_id`
* 0 duplicate `(congress, chamber, icpsr)` keys
* 0 ICPSR numbers mapping to more than one Bioguide ID

The crosswalk is keyed term-scoped `(congress, chamber, icpsr)` anyway, because
ICPSR numbers follow a member across chambers.

NOMINATE columns are dropped in `read_csv`, at the parsing boundary rather than
at the point of use, so no caller can read an ideology score off a row it was
handed — the key is not on the row (PRD N1/FC-4). The `*_rollcalls.csv` file
carries its own set (`nominate_mid_1`, `nominate_spread_1`, …), which is why
the exclusion also matches the `nominate_`/`nokken_poole_` prefixes rather than
only the listed names.

---

## What the first full run found (2026-08-18)

`reconcile` over 2,073 stored roll calls — 1990 and 2016 from the Clerk
backfill, the 119th from the daily cron:

| | Roll calls |
|---|---|
| agree | 2,001 |
| disagree (open flags, withheld under FC-3) | 42 |
| no Voteview counterpart (quorum calls, and votes newer than its last release) | 29 |
| not tally-comparable (finding 15) | 1 |

The first pass of that run reported **157** disagreements, 156 of them in 1990.
Findings 14 and 15 are what the other 115 turned out to be.

### Finding 14 — Voteview's roster is term-scoped, and it misses mid-Congress arrivals

Patsy Mink won the HI-02 special election on 22 September 1990 and voted 146
times in the remainder of the 101st Congress. `HSall_members.csv` has **no
101st-Congress row for her at all** — her first is the 102nd. Every roll call
she voted in therefore shows the Clerk's official tally exactly one above
Voteview's column, because Voteview's columns count Voteview's roster.

Measured over the 1990 backfill: **124 of 536 roll calls**, 23% of the year.
Susan Molinari is the mirror image — sworn in March 1990, carried by Voteview,
and dropped by OUR side as an unresolvable `NY:Molinari` label (finding 3). She
costs us a cast row but not a tally, because the tally we store is the Clerk's
own `<totals-by-vote>`, not a count of the casts we managed to resolve.

Verified end to end on 1990 roll 166: the Clerk document's `<totals-by-vote>`
says yea 312, the document itself contains 312 `Aye` legislators, we store 312,
Voteview says 311.

So `compare_tally` subtracts the casts belonging to members Voteview does not
carry before deciding. A difference those members fully account for is not a
disagreement; one they only partly account for still is, and the flag records
the arithmetic. Without this, FC-3 would have withheld 29% of 1990 over a
roster gap.

### Finding 15 — an Election of the Speaker is not tally-comparable

The chamber publishes no yea/nay total for it: members call out candidate
names, and every cast lands in `raw_position` with a NULL position (migration
0003). Voteview re-codes the same roll call as 1/6 by whom the member backed
and publishes yea and nay counts — 119/1/2 comes out 218-216 against our 0-0.

Two different questions, so the roll call is left uncompared and uncaptioned
rather than retracted. One roll call in the current data.

### Finding 16 — the 42 that remain are genuine, and they are all 1990

None in 2016, none in the 119th. Eight are tally differences; the rest are
per-member positions. Spot-checked against the Clerk's own XML, which agrees
with what we stored in every case:

| Roll call | Clerk (and us) | Voteview |
|---|---|---|
| 1990 roll 9 | Wylie (R-OH) Aye, Synar (D-OK) No | Wylie Nay, Synar Yea |
| 1990 roll 516 | Porter (R-IL) Nay, Price (D-NC) Yea | Porter Yea, Price Nay |
| 1990 roll 38 | Sabo (D-MN) Yea, Savage (D-IL) Not Voting | Sabo Nay, Savage Yea |
| 1990 roll 166 | yea 312 | yea 311 — one member Voteview codes 4 (announced Nay) |

The last row is the announced/paired era showing up in the tally COLUMN rather
than in a derived count: Voteview leaves codes 2-5 out of its yea and nay
totals, and in the 101st the Clerk sometimes counted those members as voting.
Genuinely two sources saying different things about the same cast, which is
what FC-2 is for.

---

## Not verified

* GovInfo (P3), FEC (P4), Census Geocoder / TIGER (P4) — untouched, as in P1.
* Voteview's `S{congress}_votes.csv` per-member codes were checked for shape
  but the Senate reconciliation has only the 119th Congress to work on so far,
  because that is all `vote` holds for the Senate.
* `HSall_rollcalls.csv` and `HSall_votes.csv` were probed for size only; the
  pipeline never downloads them.
