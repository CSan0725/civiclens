# UI/UX Design Recommendation Report: A Neutral US Political Transparency Platform

## TL;DR
- **Build a "quiet data" interface** — a fact-first encyclopedia-meets-dashboard that borrows GovTrack's data depth, openparliament.ca's clean speech cards, TheyWorkForYou's plain language, and Our World in Data's provenance discipline, while *deliberately rejecting* the evaluative scoring those sites layer on (GovTrack's ideology/leadership/prognosis scores; TheyWorkForYou's "generally voted for" summaries) because the PRD forbids interpretation.
- **Recommended stack:** Next.js (App Router, SSR) + shadcn/ui on Radix/Base UI primitives + Tailwind; TanStack Table + TanStack Virtual for large vote/ranking lists; Recharts (with visx for the bespoke seat chart/cartogram) for SSR-friendly, accessible charts; MapLibre GL for districts **with a mandatory address-input + list fallback** because MapLibre layers are not keyboard-accessible by default.
- **Neutrality is enforced in components, not just copy:** party shown as a neutral labeled chip ("D — Democratic") rather than full-bleed red/blue; a "view original source" link on every fact; an always-visible "last synced" freshness indicator; inline (never hidden) methodology footnotes and coverage-limit disclosures.

## Key Findings
- **The direct benchmark, poliwiki.kr, is the right structural model.** Its homepage is a "what changed in the last 7 days" activity digest with paired card columns (pending items vs. processed results), a data-timestamp line, and an always-visible "based on official data" footer. Its stated stance: "이 서비스는 정치인·법률을 평가하지 않습니다" ("this service does not evaluate politicians or laws"). A Korean sibling site, PoliScope, layers on "AI 신뢰도" (AI trust) scoring — precisely the anti-pattern the PRD rejects.
- **Every mature comparable platform mixes excellent raw-data UX with at least one interpretive feature to strip out.** The design task is selective adoption: take GovTrack's cartogram and bill-status tracker but not its scores; take TheyWorkForYou's speaker cards, permalinks, and keyword alerts but not its policy stance summaries.
- **The US red/blue color convention is arbitrary and recent** (assigned around the 2000 election), carries partisan heat, and should not be the primary visual encoding. Use neutral labeled chips plus desaturated, redundant-encoded tints only where charts need them.
- **Maps must never be the only path to a district.** MapLibre's markers/layers are not keyboard-accessible, so an address input and a searchable district list must be the accessible primaries, with the map as progressive enhancement.
- **SSR + accessibility drive the chart/table/library choices:** Canvas-first chart libraries (Chart.js/ECharts) need extra SSR setup and are invisible to screen readers without manual ARIA, so SVG-based Recharts/visx are the correct defaults, always shipped with the accessibility trio (labelled `role="img"`, a hidden data-table alternative, and reduced-motion handling).

## Platform-by-Platform Comparative Analysis

**GovTrack.us** — Deepest US congressional model (members, bills with introduction→enacted status tracker, votes, committees). Its roll-call **cartogram** (one square per member, grouped by state/party) packs 435 data points into a compact, scannable space and has been widely reimplemented. *Avoid:* GovTrack's evaluative analytics — ideology score (left–right from cosponsorship), leadership score (PageRank-style), and prognosis (enactment probability). GovTrack itself hedges: "A higher or lower number… doesn't necessarily make a legislator any better or worse."

**Congress.gov (Library of Congress)** — Authoritative, versioned bill text and action history; mature search with field operators (`cite:`, Boolean AND/OR/NOT, quoted phrases) defaulting to the current Congress; responsive mobile. LOC usability testing (2017, 20 users incl. lawyers/lobbyists/Hill staff) found the main homepage search is the go-to and current-Congress default works well. *Avoid:* their confusion finding — users mistook "main" vs "Quick" vs "Advanced" search labels — so provide **one obvious search plus progressive advanced options.**

**TheyWorkForYou (mySociety, UK)** — Gold standard for plain-language accessibility: scrapes official Hansard and re-presents with per-section permalinks, per-speaker photo+party+constituency cards, postcode→MP lookup, keyword email alerts. Publishes design philosophy openly ("the simplest way the information is presented should be mostly right"). *Avoid:* its "policy" voting summaries ("generally voted for," "almost always voted against") — the exact interpretive framing the PRD bans; mySociety itself documents the harm (absent MPs "branded lazy").

**Ballotpedia** — Encyclopedia model whose **Sample Ballot Lookup** (address → districts → races/candidates/measures) is the direct analogue for /districts: geocodes an address, pinpoints it on a map to find districts, offers Concise vs. Detailed views, links to candidate articles; self-describes as "neutral, accurate, and verifiable." *Avoid:* ad-heavy, text-dense pages and slower loads.

**Vote Smart** — Strong biographical + positions aggregation. *Avoid:* dated UI and heavy reliance on interest-group ratings (interpretive).

**OpenStates / Plural** — Standardized 50-state legislative data, find-your-legislator by address, bill search, bulk data + API. *Heed:* the free OpenStates.org was progressively sunset in favor of the commercial Plural product — keep your free public tool first-class.

**FiveThirtyEight / ProPublica "Represent"** — Newsroom-grade roll-call cartograms (ProPublica co-originated the square-per-member style with GovTrack). Represent is archived — design reference, not a living product.

**C-SPAN** — Deep video+transcript archive indexed by subject, speaker, committee, etc. Results split into **Person / Program / Transcript** tabs; a Transcript hit deep-links to the specific moment in video with keyword highlighting and timestamps. Borrow the transcript-to-source deep-link and typed-result tabs.

**openparliament.ca (Canada)** — Cleanest Hansard presentation: per-statement cards (speaker photo, name→profile, riding, party, timestamp), **per-statement permalinks** (`/only/` URLs), links to the original Parliament record, reverse-chronological MP speech feeds. Its AI summaries carry an explicit disclaimer: "This summary is computer-generated. Usually it's accurate, but every now and then it'll contain inaccuracies or total fabrications." Copy that disclaimer discipline for any v2 summarization.

**abgeordnetenwatch.de (Germany)** — Politician profiles + voting records with explicit impartiality stance. Its 2020 relaunch deliberately "reduced the design to the most important functions" and consolidated each politician into a **single unified profile spanning all terms**. *Avoid:* Q&A/petition engagement features (out of neutral scope).

**poliwiki.kr** — Exactly the mandate. Minimal public documentation; some homepage sections load asynchronously (visible "확인하는 중" states), reinforcing the need for skeleton screens even on an SSR site.

**Adopt/Avoid summary table**

| Platform | Adopt | Avoid |
|---|---|---|
| GovTrack | Vote cartogram, bill status tracker, action timeline | Ideology/leadership/prognosis scores |
| Congress.gov | One-box search + field operators, current-Congress default | Confusing multi-mode search labels |
| TheyWorkForYou | Speaker cards, permalinks, keyword alerts, plain language | "Generally voted for" interpretive summaries |
| Ballotpedia | Address→district lookup, Concise/Detailed toggle | Ad-heavy dense pages, slow loads |
| Vote Smart | Biographical completeness | Interest-group ratings framing |
| OpenStates/Plural | Find-your-legislator, open data/API, nightly refresh | Sunsetting free tool behind a paywall |
| ProPublica Represent | Roll-call cartogram | Archived — reference only |
| C-SPAN | Transcript→moment deep-link, typed result tabs, facets | Video-centric complexity |
| openparliament.ca | Per-statement cards + permalinks, AI disclaimers | Utilitarian styling |
| abgeordnetenwatch | Unified profile, disclosure transparency, "reduce to essentials" | Q&A/petition engagement features |
| poliwiki.kr | 7-day activity digest, non-evaluation stance, source footer | Thin docs; async load gaps |

## Pattern Library — Best Patterns by Page Type
- **Dashboard/activity feed:** poliwiki's "last 7 days" digest; card/widget grid with clear section headers; skeleton screens for async sections; freshness timestamp.
- **Member profile:** abgeordnetenwatch's single unified profile; openparliament/TheyWorkForYou speaker header (photo, party chip, district); tabbed sub-nav; every metric links to underlying roll calls with a visible methodology footnote.
- **Bill detail:** GovTrack's status stepper + action-history timeline; Congress.gov's versioned text and authoritative action list; "view on Congress.gov" provenance link.
- **Vote detail:** GovTrack/ProPublica cartogram for at-a-glance breakdown + a sortable, filterable, virtualized member-by-member table.
- **District lookup:** Ballotpedia's address-first flow; MapLibre choropleth with a list/search fallback.
- **Rankings:** neutral sortable tables, chamber-separated, every value linking to source, methodology footnote always visible, no superlative copy.
- **Speech search:** C-SPAN typed result tabs + transcript deep-link; openparliament per-statement cards + permalinks; TheyWorkForYou keyword alerts + Boolean operators; faceted left-rail filters with per-facet counts.

## Neutrality & Trust Design Guidelines
1. **Party color handling.** The red/blue mapping is recent and arbitrary (dates only to the 2000 election; before then networks were inconsistent). **Do not use saturated red/blue fills as the primary encoding.** Use a neutral letter-chip ("D," "R," "I") with the full party name on first use and in tooltips/legends; if a party hue is needed for chart legibility, use desaturated, equal-luminance tints paired with a text label and a non-color redundant encoding (position, pattern, or direct label); never order lists/charts to imply a spectrum or ranking.
2. **Provenance everywhere.** Every fact gets a "view original source" link. Model on Our World in Data ("In every chart, we clearly indicate the source of the data being shown") + poliwiki's persistent "based on official data" footer.
3. **Freshness indicators.** Show a "last synced" timestamp per dataset; distinguish "data current as of" from "page generated at."
4. **Methodology disclosure.** Always-visible inline footnotes + a dedicated /methodology page; info tooltips (ⓘ) for term definitions; never hide coverage limits.
5. **Rankings without judgment.** Neutral column labels ("Attendance rate," not "Best attendee"); show the raw count and denominator; annotate context (e.g., "excused absences not distinguished — see methodology"); make every value a link to its evidence.

## Design System Recommendations
- **Typography:** one highly legible sans for UI and data (Inter or system stack) with **tabular/lining numerals** enabled for all tables/metrics (critical for column alignment); optional humanist serif for long-form speech/bill body text; generous line-height for transcripts.
- **Spacing & density:** 4/8px scale; two density modes (comfortable default, compact for power users).
- **Color:** neutral gray foundation; a single non-partisan accent (teal/slate) for interactive affordances; semantic status colors (passed/failed/pending) distinguishable by shape+label, not color alone; party tints per guideline above.
- **Dark mode:** via CSS variables (shadcn token model); ensure party tints and status colors keep contrast in both themes.
- **Component library — shadcn/ui** (copy-in components on Radix or Base UI primitives, styled with Tailwind): full code ownership/no lock-in, accessibility/keyboard/ARIA at the primitive level, SSR/RSC friendliness, CSS-variable theming. Beats MUI/Ant (heavy, theming friction) and Chakra for a bespoke, data-dense civic site in 2026.
- **Chart library — Recharts** as SSR-friendly default (bar/line/sparkline/stacked breakdowns); **visx** for the bespoke ~10% — the **hemicycle/seat chart and roll-call cartogram** — D3-level control as composable React primitives at small footprint. Avoid Canvas-first defaults (Chart.js/ECharts): SSR requires extra setup and Canvas charts are invisible to screen readers without manual ARIA. Ship every chart with: `role="img"` + `aria-labelledby` (title/description), a visually-hidden data-table alternative, and `prefers-reduced-motion` handling.
- **Table library — TanStack Table** (headless sorting/filtering/faceting/column-pinning) + **TanStack Virtual** for row virtualization (renders only ~20–40 visible rows; sticky header `top-0 z-10` outside the scroll body). Server-side pagination for the very largest sets (speeches).
- **Chart legibility & neutrality:** vote breakdowns — a hemicycle chart is instantly recognizable but must always show the **total and majority threshold** and never order parties to imply a judgment-spectrum; for member-level detail the **square-per-member cartogram** is the densest legible option; always pair either with a plain stacked bar + exact counts. Bill progress — a **stepper/timeline** (Introduced→Committee→Floor→Passed→Enacted), not a probability gauge. Attendance over time — sparklines in tables; avoid color-only heatmaps.
- **Map (MapLibre):** choropleth via GeoJSON + feature-state hover; cursor change on hover; visible legend. **Accessibility caveat:** MapLibre markers/layers are not keyboard-accessible by default, so the address input and searchable district list are the accessible primaries and the map is an enhancement; respect `prefers-reduced-motion`.
- **SEO/SSR & sharing:** SSR every page; schema.org structured data (Person for members, Legislation for bills); shareable OG images per member/vote/bill. Target P95 < 2s — server-render content, lazy-hydrate charts/maps via dynamic import, ship skeletons.

## Page-by-Page UX Blueprints

**/ (Dashboard).** poliwiki-style "what changed recently" digest: top freshness line + global search; below, a responsive card grid — "Recently passed bills," "Recent roll-call votes," "Recent floor speeches" (v2 adds in-dashboard news feed). Cards show title, date, chamber, "view source" link; skeleton loaders for async sections; small stacked bar per recent vote. Mobile: single-column stack; search collapses to a prominent button. *Rationale:* GovTrack buries recency under analysis; poliwiki's digest is the right neutral model.

**/members/:bioguide (Member Profile).** abgeordnetenwatch unified-profile header (photo, name, party chip "D — Democratic," state/district, chamber, term dates) + tabbed sub-nav: Overview · Sponsored/Cosponsored · Voting history · Speeches · Committees · Metrics. Metrics summary cards (attendance %, vote participation %) each with an ⓘ methodology link and a link to underlying roll calls; voting-history rows show bill + position + date + source link; attendance sparkline; small stacked bar of positions — **never an ideology score.** Mobile: tabs → scrollable segmented control/accordion; tables → cards.

**/bills/:id (Bill Detail).** Title + status stepper at top (Introduced→…→Enacted); two-column desktop: left = action-history timeline (dated entries + source links); right = sponsors/cosponsors (party chips), committees, related votes, "view on Congress.gov." Stepper only — **no prognosis gauge.** Mobile: stepper vertical; timeline single-column.

**/votes/:id (Vote Detail).** Header (bill/question, date, result, "X needed to pass"); **cartogram or hemicycle** with legend + majority-threshold marker + exact tallies; below, a virtualized, sortable, filterable TanStack table of every member's position (Member | Party | State | Position) with filter chips and sticky header. Position encoded by shape+label+tint, not color alone. Mobile: cartogram scales down or swaps to stacked bar; table → member cards or horizontal scroll with pinned Member column. The table itself doubles as the screen-reader alternative to the cartogram.

**/districts (District Map Lookup).** **Address-input-first** (Ballotpedia model): prominent address field at top, map secondary; result panel shows 1 House rep + 2 Senators + "past-5-years candidates" tab. Address autocomplete/geocode; MapLibre choropleth (click district → result) with cursor change + hover highlight; **accessible fallback:** a searchable district list and the address flow both work without the map. Mobile: address field first; map in a collapsible panel below; results as full-width cards. *Avoid* map-only lookup.

**/rankings.** Chamber toggle (House/Senate) + metric tabs (Attendance rate · Vote participation · Bills sponsored · Speeches count); one sortable TanStack table per metric (sort, filter, sticky header, virtualization). Every value links to underlying roll calls; a persistent methodology footnote below the table; neutral column headers; optional inline sparkline/bar per row. Mobile: card collapse with the metric value prominent; sort as a dropdown. *Avoid* superlative labels and cross-metric composite "scores."

**/speeches (Full-Text Speech Search).** Prominent search box + **faceted left rail** (speaker, party, chamber, committee, date, topic, bill) with per-facet result counts; results as **per-statement cards** (speaker photo, name→profile, party chip, state, date/timestamp) with keyword-highlighted snippets. Typed result tabs (Speaker · Debate · Statement, à la C-SPAN's Person/Program/Transcript); per-statement **permalink** (openparliament `/only/` model); "view original transcript" link; documented search operators (quoted phrase, Boolean OR/AND, exclusion); **keyword email alerts** as v2. Return **granule-level results** (individual speeches, not whole sittings) and deep-link to the exact passage. Mobile: facets in a bottom-sheet/drawer; cards full-width. If AI summarization is added, use openparliament's explicit hallucination disclaimer + a helpfulness feedback widget.

## Implementation Roadmap

**Stage 1 — Foundations (before feature build).** Stand up the Next.js + shadcn/ui + Tailwind design system with the neutral token palette and party-chip component; build the reusable "provenance link," "freshness timestamp," and "methodology footnote" components first, since they must appear everywhere. Ship the dashboard and member/bill/vote detail pages using SSR + skeletons. *Benchmark to proceed:* P95 < 2s on mid-tier mobile with charts lazy-hydrated.

**Stage 2 — Data-dense interactions.** Add TanStack Table + Virtual for vote and ranking tables; build the visx cartogram/hemicycle with its mandatory hidden-table alternative; build the MapLibre district choropleth *only after* the address-input and searchable-list fallbacks pass keyboard/screen-reader testing. *Benchmark:* WCAG AA audit passes for tables, charts, and the map-alternative path before launch.

**Stage 3 — Search & v2.** Ship full-text speech search with facets, typed tabs, highlighted snippets, and permalinks; add schema.org markup and OG images. Defer keyword email alerts, the in-dashboard news feed, and any AI summarization to v2 — and if summarization ships, it must carry openparliament-style disclaimers.

**Thresholds that would change these recommendations:** if the audience skews more mobile than assumed (>60% mobile sessions), shift the dense tables/cartograms to mobile-first card layouts by default. If bundle budget forces one chart library, drop visx and render the cartogram as server-generated SVG. If a future PRD revision permits any interpretive layer, revisit the strict no-scoring stance — but keep raw records as the default view.

## Caveats
- **Live-UI details** for C-SPAN's search are drawn from tutorials and secondary sources; treat exact interface labels as directional. openparliament.ca and poliwiki.kr details come from directly fetched live pages.
- **poliwiki.kr publishes little design documentation**; inferences are based on its live homepage and stated non-evaluation policy.
- **Library/framework specifics** (shadcn/Base UI, Recharts vs. visx SSR behavior, TanStack virtualization) reflect 2025–2026 ecosystem writeups; verify current versions and SSR/RSC compatibility at implementation time.
- **The red/blue history** is well-corroborated across multiple accounts; the 2000-election framing is the most consistently reported.
- **mySociety's TheyWorkForYou** is used as a positive model for presentation/alerts and a negative model for interpretive summaries; its practices continue to evolve.
