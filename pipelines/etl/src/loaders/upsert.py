"""Bulk write helpers.

Idempotency is the whole point (PRD §6 "자연키 우선 ... 멱등 upsert"): every
collector can be re-run over the same window and must converge on the same
rows, never duplicates. Each table's natural key is the conflict target.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Connection, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.logging import get_logger

log = get_logger(__name__)

# Rows per statement. Large enough to amortise round trips, small enough that a
# failure is legible and a retry is cheap.
DEFAULT_BATCH_SIZE = 1_000


def _chunk(rows: Sequence[dict[str, Any]], size: int) -> Iterable[Sequence[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def bulk_upsert(
    conn: Connection,
    table: Table,
    rows: Sequence[dict[str, Any]],
    *,
    conflict_columns: Sequence[str] | None = None,
    conflict_elements: Sequence[Any] | None = None,
    update_columns: Sequence[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """INSERT ... ON CONFLICT DO UPDATE a batch of rows.

    Args:
        conn: an open connection; the caller owns the transaction.
        table: reflected target table.
        rows: dicts keyed by column name. Every dict must share the same keys —
            Postgres builds one statement per batch.
        conflict_columns: the natural key, e.g. `("congress_no", "bill_type",
            "number")` for `bill`.
        conflict_elements: SQL expressions to infer the arbiter index from,
            instead of a column list. Required when the natural key is built
            from expressions, which `bill_action`'s is: Postgres infers an
            expression index only from a matching expression list, and
            `ON CONFLICT ON CONSTRAINT` cannot name a bare UNIQUE INDEX.
        update_columns: columns to refresh on conflict. Defaults to every
            supplied column that is not part of the conflict key.
        batch_size: rows per statement.

    Returns:
        Number of rows sent. Postgres does not distinguish inserted from
        updated here, and for an idempotent pipeline the distinction does not
        change what happens next.

    Raises:
        ValueError: neither or both of `conflict_columns`/`conflict_elements`
            given, or a batch carries the same conflict key twice. Postgres
            answers the latter with "ON CONFLICT DO UPDATE command cannot
            affect row a second time", which says nothing about which rows
            collided; callers get a useful message instead.
    """
    if (conflict_columns is None) == (conflict_elements is None):
        raise ValueError("pass exactly one of conflict_columns or conflict_elements")
    if not rows:
        return 0

    supplied = list(rows[0].keys())
    if update_columns is None:
        skip = set(conflict_columns or ())
        update_columns = [c for c in supplied if c not in skip]

    if conflict_columns is not None:
        _assert_unique_keys(table.name, rows, conflict_columns)

    sent = 0
    for batch in _chunk(rows, batch_size):
        stmt = pg_insert(table).values(list(batch))
        target: dict[str, Any] = {
            "index_elements": list(conflict_columns)
            if conflict_columns is not None
            else list(conflict_elements or ())
        }
        if update_columns:
            stmt = stmt.on_conflict_do_update(
                set_={c: stmt.excluded[c] for c in update_columns}, **target
            )
        else:
            # Nothing to refresh — the natural key IS the whole row.
            stmt = stmt.on_conflict_do_nothing(**target)
        conn.execute(stmt)
        sent += len(batch)

    log.debug("bulk_upsert", table=table.name, rows=sent)
    return sent


def _assert_unique_keys(
    table_name: str, rows: Sequence[dict[str, Any]], conflict_columns: Sequence[str]
) -> None:
    seen: dict[tuple[Any, ...], int] = {}
    for index, row in enumerate(rows):
        key = tuple(row.get(c) for c in conflict_columns)
        if key in seen:
            raise ValueError(
                f"{table_name}: duplicate natural key "
                f"{dict(zip(conflict_columns, key, strict=True))} "
                f"at rows {seen[key]} and {index} of the same batch"
            )
        seen[key] = index


def copy_rows(
    conn: Connection,
    table: Table,
    rows: Iterable[Sequence[Any]],
    *,
    columns: Sequence[str],
) -> int:
    """COPY rows into a table via psycopg3's binary COPY path.

    Reserved for the one case that justifies it: the 1990-2022 `vote_cast`
    backfill, millions of rows deep, where per-statement overhead dominates.

    COPY cannot upsert, so the caller must guarantee the target is empty for
    the partition being loaded — or COPY into an UNLOGGED staging table and
    merge from there with `bulk_upsert`.

    TODO(P2): implement using `conn.connection.cursor().copy(...)` against the
    partition directly, so partition routing is skipped.
    """
    raise NotImplementedError("P2: implement COPY path for the vote_cast backfill")
