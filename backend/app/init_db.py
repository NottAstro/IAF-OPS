"""Create tables (models.py) + views/constraints/triggers (sql/schema.sql). Idempotent.

ponytail: create_all instead of Alembic while the schema is still moving; add Alembic once real data must survive
schema changes. `init_db(reset=True)` (used by the generator) drops and recreates every operational table so a
changed model takes effect on the next `make seed`; the pipeline-owned GIS tables are kept.
"""
from pathlib import Path

from sqlalchemy import text

from .db import engine
from .models import Base

GIS_TABLES = {"gis_admin_area", "gis_place", "gis_line", "gis_point", "civil_airport", "gis_defacto_admin0"}


def init_db(reset: bool = False) -> None:
    with engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        if reset:
            names = [t.name for t in Base.metadata.sorted_tables if t.name not in GIS_TABLES]
            c.execute(text(f"DROP TABLE IF EXISTS {', '.join(names)} CASCADE"))
    Base.metadata.create_all(engine)
    sql = (Path(__file__).parent / "sql" / "schema.sql").read_text()
    with engine.begin() as c:
        c.connection.driver_connection.execute(sql)  # raw psycopg: no %-placeholder parsing (format('%I') in SQL)


if __name__ == "__main__":
    init_db()
    print("schema ready")
