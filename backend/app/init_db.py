"""Create tables (models.py) + views/constraints/triggers (sql/schema.sql). Idempotent.

ponytail: create_all instead of Alembic while the schema is still moving; add Alembic once real data must survive
schema changes.
"""
from pathlib import Path

from sqlalchemy import text

from .db import engine
from .models import Base


def init_db() -> None:
    with engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(engine)
    sql = (Path(__file__).parent / "sql" / "schema.sql").read_text()
    with engine.begin() as c:
        c.connection.driver_connection.execute(sql)  # raw psycopg: no %-placeholder parsing (format('%I') in SQL)


if __name__ == "__main__":
    init_db()
    print("schema ready")
