"""Invariant checker (DATA_MODEL §6). Runs every tick when SIM_ASSERT=1 and in the simulator soak test."""
from sqlalchemy import text

CHECKS = {
    "I2 aircraft in ≤1 active sortie": """SELECT count(*) FROM (SELECT sa.aircraft_id FROM sortie_aircraft sa JOIN sortie s ON s.id = sa.sortie_id
        WHERE s.status IN ('CREWED','READY','AIRBORNE','ON_STATION','RTB') GROUP BY 1 HAVING count(*) > 1) x""",
    "I3 aircrew in ≤1 active sortie": """SELECT count(*) FROM (SELECT sc.aircrew_id FROM sortie_crew sc JOIN sortie s ON s.id = sc.sortie_id
        WHERE s.status IN ('CREWED','READY','AIRBORNE','ON_STATION','RTB') GROUP BY 1 HAVING count(*) > 1) x""",
    "I4 AIRBORNE <=> airborne sortie <=> no current base": """SELECT count(*) FROM aircraft a WHERE
        (a.status = 'AIRBORNE') <> EXISTS (SELECT 1 FROM sortie_aircraft sa JOIN sortie s ON s.id = sa.sortie_id
                                           WHERE sa.aircraft_id = a.id AND s.status IN ('AIRBORNE','ON_STATION','RTB'))
        OR (a.status = 'AIRBORNE') <> (a.current_base_id IS NULL)""",
    "I5 fuel within capacity": "SELECT count(*) FROM fuel_storage WHERE current_l < 0 OR current_l > capacity_l",
    "I1 inventory only at OWN bases": """SELECT count(*) FROM aircraft a JOIN base b ON b.id = a.home_base_id WHERE b.side <> 'OWN'""",
    "I7 synthetic rows flagged": "SELECT count(*) FROM aircraft WHERE NOT is_simulated",
}


def check(db) -> None:
    bad = {name: n for name, sql in CHECKS.items() if (n := db.execute(text(sql)).scalar())}
    if bad:
        raise AssertionError(f"simulator invariant violation: {bad}")
