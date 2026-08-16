"""`dataset_sync_state` bookkeeping.

Backs the "last synced" indicator the UI must show (UIUX report) and the job
observability NFR-9 asks for. Deliberately records `data_current_as_of`
separately from `last_run_at`: users care how current the DATA is, not when the
job happened to execute.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.logging import get_logger
from loaders.engine import reflect_table

log = get_logger(__name__)


@dataclass
class SyncTally:
    """Mutable counter a job fills in while it runs."""

    rows_upserted: int = 0
    data_current_as_of: datetime | None = None
    detail: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, table: str, rows: int) -> None:
        if rows:
            self.rows_upserted += rows
            self.detail[table] = self.detail.get(table, 0) + rows

    def note(self, message: str) -> None:
        """Record something the run wants surfaced even on success.

        Lands in `dataset_sync_state.message`, so a partial result — e.g. roll
        calls skipped because their positions do not fit the enum — is visible
        in the database long after the CI logs have expired.
        """
        self.notes.append(message)

    def observe(self, moment: datetime | None) -> None:
        """Track the newest upstream timestamp seen during the run.

        Sources mix precision for the same field: a Congress.gov bill LIST
        gives `updateDate` as a bare date ("2026-07-18") while the bill DETAIL
        gives a full instant ("2026-07-11T01:08:27Z"). Comparing the two raises
        TypeError, so naive values are read as UTC before comparison.
        """
        if moment is None:
            return
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        if self.data_current_as_of is None or moment > self.data_current_as_of:
            self.data_current_as_of = moment


def _write(
    conn: Connection,
    dataset: str,
    *,
    source_system: str,
    status: str,
    started_at: datetime,
    tally: SyncTally | None = None,
    message: str | None = None,
) -> None:
    table = reflect_table("dataset_sync_state")
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "dataset": dataset,
        "source_system": source_system,
        "last_run_at": started_at,
        "last_status": status,
        "message": message,
    }
    if status == "ok":
        values["last_success_at"] = now
    if tally is not None:
        values["rows_upserted"] = tally.rows_upserted
        if tally.data_current_as_of is not None:
            values["data_current_as_of"] = tally.data_current_as_of
        if tally.notes and not message:
            values["message"] = " | ".join(tally.notes)[:2000]

    stmt = pg_insert(table).values(values)
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["dataset"],
            set_={k: stmt.excluded[k] for k in values if k != "dataset"},
        )
    )


@contextmanager
def sync_run(conn: Connection, dataset: str, *, source_system: str) -> Iterator[SyncTally]:
    """Wrap a collection job in `dataset_sync_state` bookkeeping.

    Marks the dataset `running`, then `ok` or `failed`. The failure record is
    committed even though the job's own transaction is rolled back — a job that
    fails silently is worse than one that fails loudly, and NFR-9 wants the
    failure visible.
    """
    started_at = datetime.now(UTC)
    tally = SyncTally()
    _write(conn, dataset, source_system=source_system, status="running", started_at=started_at)
    conn.commit()
    try:
        yield tally
    except Exception as exc:
        conn.rollback()
        _write(
            conn,
            dataset,
            source_system=source_system,
            status="failed",
            started_at=started_at,
            tally=tally,
            message=f"{type(exc).__name__}: {exc}"[:2000],
        )
        conn.commit()
        log.error("sync.failed", dataset=dataset, error=str(exc))
        raise
    else:
        _write(
            conn,
            dataset,
            source_system=source_system,
            status="ok",
            started_at=started_at,
            tally=tally,
        )
        conn.commit()
        log.info(
            "sync.ok",
            dataset=dataset,
            rows_upserted=tally.rows_upserted,
            detail=tally.detail,
            notes=tally.notes or None,
        )
