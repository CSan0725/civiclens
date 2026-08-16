"""Source collectors — one module per upstream system.

Every module here is a P0 stub: signatures, docstrings and TODOs only. The
actual network calls and parsers land in P1, once API keys are issued.

Tier 1 (official, public domain — the fact baseline, PRD §5):
    congress_gov  Congress.gov API: bills, members, committees, actions,
                  House roll calls from 2023 (118th) onward
    senate_xml    senate.gov roll-call XML, 1989~
    clerk_xml     clerk.house.gov roll-call XML, 1990-2022 (House backfill)
    govinfo       GovInfo API: Congressional Record granules (speeches)
    fec           openFEC: candidates and campaign finance
    census_tiger  Census Geocoder (address -> district) + TIGER/CB boundaries

Tier 2 (cross-check only — NEVER a display source, PRD FC-2):
    voteview      Voteview roll-call CSVs, used to reconcile tier-1 tallies.
                  NOMINATE ideology scores are deliberately NOT ingested
                  (PRD N1 / FC-4: no ideology scoring).
"""
