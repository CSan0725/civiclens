"""`civiclens-etl` command-line entry point.

Job names mirror the roadmap in PRD §14 and the schedules in
Deployment-Architecture-Report §4:

    members       weekly    Congress.gov roster -> member, term
    bills         daily     Congress.gov bills, actions, cosponsors
    votes         daily     Congress.gov (House 2023~) + senate.gov XML
    speeches      daily     GovInfo Congressional Record granules
    candidates    weekly    openFEC candidates + totals
    boundaries    manual    Census TIGER/CB -> district (+ TopoJSON to R2)
    backfill      manual    clerk.house.gov 1990-2022 House roll calls
    reconcile     daily     Voteview cross-check -> reconciliation flags

Every job is a stub in P0; `--dry-run` is the only path that currently
completes, and it just reports what would run.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from common.logging import configure_logging, get_logger
from common.settings import get_settings

JOBS: dict[str, str] = {
    "members": "Congress.gov roster -> member, term (weekly)",
    "bills": "Congress.gov bills, actions, cosponsors (daily)",
    "votes": "House 2023~ + Senate roll calls -> vote, vote_cast (daily)",
    "speeches": "GovInfo Congressional Record granules -> speech (daily)",
    "candidates": "openFEC candidates + totals -> candidate, campaign_finance (weekly)",
    "boundaries": "Census TIGER/CB -> district, TopoJSON -> R2 (per Congress)",
    "backfill": "clerk.house.gov 1990-2022 House roll calls (manual, long-running)",
    "reconcile": "Voteview cross-check -> vote_reconciliation_flag (daily)",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="civiclens-etl",
        description="CivicLens ETL — official US Congress data into Postgres/PostGIS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="jobs:\n" + "\n".join(f"  {name:<12} {desc}" for name, desc in JOBS.items()),
    )
    parser.add_argument("job", choices=sorted(JOBS), help="which collection job to run")
    parser.add_argument(
        "--congress",
        type=int,
        default=None,
        help="limit the run to one Congress (e.g. 119)",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO date; only collect records updated on or after it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would run without touching the network or the database",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.etl_log_level)
    log = get_logger("cli")

    log.info(
        "etl.start",
        job=args.job,
        congress=args.congress,
        since=args.since,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        log.info("etl.dry_run", job=args.job, description=JOBS[args.job])
        return 0

    log.error(
        "etl.not_implemented",
        job=args.job,
        detail="P0 scaffolding only — collectors land in P1. Run with --dry-run.",
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
