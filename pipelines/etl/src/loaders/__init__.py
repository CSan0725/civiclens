"""Database write path — SQLAlchemy Core + psycopg3.

Deliberately NOT the SQLAlchemy ORM. This is a batch write path: bulk upserts
and COPY, where explicit control beats identity-map bookkeeping
(Deployment-Architecture-Report §2b).

The database schema is owned by `packages/db/migrations/*.sql` (dbmate). These
loaders reflect the live schema rather than declaring it, so there is exactly
one definition of the truth.
"""

from loaders.engine import get_engine, get_metadata, reflect_table
from loaders.upsert import bulk_upsert, copy_rows

__all__ = [
    "bulk_upsert",
    "copy_rows",
    "get_engine",
    "get_metadata",
    "reflect_table",
]
