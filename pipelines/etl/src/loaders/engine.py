"""Engine and schema reflection.

The ETL reflects the live database instead of declaring models, because
`packages/db/migrations/*.sql` is the single source of truth. If a table shape
changes, it changes there, the migration runs first, and both this pipeline and
the TypeScript app pick it up by introspection.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, MetaData, Table, create_engine

from common.settings import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Process-wide SQLAlchemy engine on psycopg3.

    Pooling is intentionally small: ETL jobs are a handful of long-running
    writers, not a request-serving fleet.
    """
    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url(),
        pool_size=2,
        max_overflow=2,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_metadata() -> MetaData:
    """Empty MetaData bound to the `public` schema; tables are reflected on demand."""
    return MetaData(schema="public")


def reflect_table(name: str) -> Table:
    """Reflect one table from the live database.

    Cached inside the shared MetaData, so repeated calls for the same table do
    not re-query the catalog.
    """
    metadata = get_metadata()
    qualified = f"public.{name}"
    existing = metadata.tables.get(qualified)
    if existing is not None:
        return existing
    return Table(name, metadata, autoload_with=get_engine())
