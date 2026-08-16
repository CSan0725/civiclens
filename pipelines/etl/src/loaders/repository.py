"""Table-aware upsert wrappers shared by every collector.

This is the layer that keeps `congress_gov` and `senate_xml` from each
re-implementing the same writes. Each function knows one table's natural key
and returns whatever the caller needs next (usually surrogate ids, so a child
table can reference the parent).

Everything routes through `loaders.upsert.bulk_upsert`, so idempotency is a
property of this layer rather than of each collector.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Connection, func, select, text, tuple_

from common.logging import get_logger
from loaders.engine import reflect_table
from loaders.upsert import bulk_upsert

log = get_logger(__name__)

# Columns that make up each table's natural key, mirroring the constraints in
# packages/db/migrations/*.sql. Kept here so a schema change has exactly one
# place to land on the Python side.
MEMBER_KEY = ("bioguide_id",)
TERM_KEY = ("bioguide_id", "congress_no", "chamber")
COMMITTEE_KEY = ("committee_id",)
BILL_KEY = ("congress_no", "bill_type", "number")
SPONSORSHIP_KEY = ("bill_id", "bioguide_id", "role")
VOTE_KEY = ("congress_no", "chamber", "session", "roll_number")
VOTE_CAST_KEY = ("congress_no", "vote_id", "bioguide_id")


def upsert_members(conn: Connection, rows: Sequence[dict[str, Any]]) -> int:
    return bulk_upsert(conn, reflect_table("member"), rows, conflict_columns=MEMBER_KEY)


def upsert_terms(conn: Connection, rows: Sequence[dict[str, Any]]) -> int:
    return bulk_upsert(conn, reflect_table("term"), rows, conflict_columns=TERM_KEY)


def upsert_committees(conn: Connection, rows: Sequence[dict[str, Any]]) -> int:
    return bulk_upsert(conn, reflect_table("committee"), rows, conflict_columns=COMMITTEE_KEY)


def upsert_sponsorships(conn: Connection, rows: Sequence[dict[str, Any]]) -> int:
    return bulk_upsert(conn, reflect_table("sponsorship"), rows, conflict_columns=SPONSORSHIP_KEY)


def upsert_bill(conn: Connection, row: dict[str, Any]) -> int:
    """Upsert one bill and return its surrogate id."""
    table = reflect_table("bill")
    bulk_upsert(conn, table, [row], conflict_columns=BILL_KEY)
    bill_id = conn.execute(
        select(table.c.id).where(
            table.c.congress_no == row["congress_no"],
            table.c.bill_type == row["bill_type"],
            table.c.number == row["number"],
        )
    ).scalar_one()
    return int(bill_id)


def upsert_bill_actions(conn: Connection, rows: Sequence[dict[str, Any]]) -> int:
    """Upsert bill actions on their expression-based natural key.

    The key is a UNIQUE INDEX over expressions (COALESCE, md5), not a
    constraint, so the expressions have to be restated for Postgres to infer
    the arbiter index. They must match `idx_bill_action_natural_key` in
    migration 0002 exactly — see that file for why committee and time belong in
    the key.
    """
    table = reflect_table("bill_action")
    elements = [
        table.c.bill_id,
        table.c.action_date,
        func.coalesce(table.c.action_time, text("'00:00:00'::time")),
        func.coalesce(table.c.action_code, text("''")),
        func.coalesce(table.c.committee_id, text("''")),
        func.coalesce(table.c.source_system, text("''")),
        func.md5(table.c.text),
    ]
    return bulk_upsert(
        conn,
        table,
        rows,
        conflict_elements=elements,
        update_columns=("action_type", "source_url", "retrieved_at"),
    )


def upsert_vote(conn: Connection, row: dict[str, Any]) -> int:
    """Upsert one roll call and return its surrogate id."""
    table = reflect_table("vote")
    bulk_upsert(conn, table, [row], conflict_columns=VOTE_KEY)
    vote_id = conn.execute(
        select(table.c.id).where(
            table.c.congress_no == row["congress_no"],
            table.c.chamber == row["chamber"],
            table.c.session == row["session"],
            table.c.roll_number == row["roll_number"],
        )
    ).scalar_one()
    return int(vote_id)


def upsert_vote_casts(conn: Connection, rows: Sequence[dict[str, Any]]) -> int:
    """Upsert per-member positions into the partitioned `vote_cast` table.

    Writes go to the PARENT table; Postgres routes each row to the
    `vote_cast_c{congress_no}` partition from the partition key carried on the
    row. Never target a child directly.
    """
    return bulk_upsert(conn, reflect_table("vote_cast"), rows, conflict_columns=VOTE_CAST_KEY)


def find_bill_id(conn: Connection, *, congress_no: int, bill_type: str, number: int) -> int | None:
    """Look up a bill's surrogate id by natural key, or None."""
    table = reflect_table("bill")
    result = conn.execute(
        select(table.c.id).where(
            table.c.congress_no == congress_no,
            table.c.bill_type == bill_type.lower(),
            table.c.number == number,
        )
    ).scalar_one_or_none()
    return int(result) if result is not None else None


def existing_member_ids(conn: Connection, bioguide_ids: Iterable[str]) -> set[str]:
    """Return the subset of bioguide IDs already present in `member`."""
    wanted = sorted(set(bioguide_ids))
    if not wanted:
        return set()
    table = reflect_table("member")
    rows = conn.execute(
        select(table.c.bioguide_id).where(table.c.bioguide_id.in_(wanted))
    ).scalars()
    return set(rows)


def existing_vote_keys(
    conn: Connection, keys: Sequence[tuple[int, str, int, int]]
) -> set[tuple[int, str, int, int]]:
    """Return which (congress, chamber, session, roll) roll calls are stored.

    Lets an incremental run skip roll calls it already has instead of
    re-fetching each one's member list — the expensive part of vote collection.
    """
    if not keys:
        return set()
    table = reflect_table("vote")
    stmt = select(table.c.congress_no, table.c.chamber, table.c.session, table.c.roll_number).where(
        tuple_(table.c.congress_no, table.c.chamber, table.c.session, table.c.roll_number).in_(
            list(keys)
        )
    )
    return {(int(c), str(ch), int(s), int(r)) for c, ch, s, r in conn.execute(stmt)}
