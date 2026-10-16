-- Views, constraints and triggers that sit on top of models.py (DATA_MODEL §5–§6).
-- Idempotent: run after metadata.create_all().

-- Simulator clock: every "now" in derived values is sim time, not wall time.
CREATE OR REPLACE FUNCTION sim_now() RETURNS timestamptz LANGUAGE sql STABLE AS $$
  SELECT coalesce((SELECT sim_now FROM sim_state WHERE id = 1), now())
$$;

-- ---------------------------------------------------------------- constraints (I5, I11, alert dedup)
DO $$ BEGIN
  ALTER TABLE fuel_storage ADD CONSTRAINT fuel_level_within_capacity CHECK (current_l >= 0 AND current_l <= capacity_l);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE app_user ADD CONSTRAINT base_cdr_has_base CHECK (role <> 'BASE_COMMANDER' OR base_id IS NOT NULL);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE UNIQUE INDEX IF NOT EXISTS alert_open_dedup ON alert (dedup_key) WHERE status <> 'CLEARED';
CREATE INDEX IF NOT EXISTS sortie_actual_launch_idx ON sortie (actual_launch_ts);
CREATE INDEX IF NOT EXISTS aircraft_current_base_idx ON aircraft (current_base_id, status);
CREATE INDEX IF NOT EXISTS audit_actor_ts_idx ON audit_log (actor_type, ts);

-- ---------------------------------------------------------------- I12 audit is append-only
-- Pruning of old SIMULATOR rows is allowed only inside a transaction that sets airops.audit_prune = 'on'.
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND OLD.actor_type = 'SIMULATOR'
     AND current_setting('airops.audit_prune', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'audit_log is append-only';
END $$;
DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_append_only();

-- ---------------------------------------------------------------- I1 inventory only at OWN bases
CREATE OR REPLACE FUNCTION assert_own_base() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b bigint; s text;
BEGIN
  EXECUTE format('SELECT ($1).%I', TG_ARGV[0]) INTO b USING NEW;
  IF b IS NULL THEN RETURN NEW; END IF;
  SELECT side INTO s FROM base WHERE id = b;
  IF s IS DISTINCT FROM 'OWN' THEN
    RAISE EXCEPTION 'inventory may only reference OWN bases (% = %)', TG_ARGV[0], b;
  END IF;
  RETURN NEW;
END $$;
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT * FROM (VALUES
    ('aircraft','home_base_id'), ('aircrew','base_id'), ('fuel_storage','base_id'), ('ground_asset','base_id'),
    ('warehouse','base_id'), ('ground_crew_strength','base_id'), ('parking_facility','base_id'),
    ('qra_posture','base_id'), ('squadron','home_base_id')) AS v(tbl, col)
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t.tbl || '_own_base', t.tbl);
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION assert_own_base(%L)',
                   t.tbl || '_own_base', t.tbl, t.col);
  END LOOP;
END $$;

-- ---------------------------------------------------------------- derived views
-- Aircraft readiness, the one definition every screen and alert uses. Small quadcopter drones (UAV_ROTARY_SMALL) are
-- counted as equipment, not aircraft, so they don't move the serviceability figures.
CREATE OR REPLACE VIEW v_aircraft_serviceability AS
SELECT a.home_base_id AS base_id, a.aircraft_type_id,
       count(*) FILTER (WHERE a.status <> 'RETIRED') AS total,
       count(*) FILTER (WHERE a.status NOT IN ('RETIRED', 'DEPOT')) AS effective,
       count(*) FILTER (WHERE a.status IN ('AVAILABLE','STANDBY','QRA','AIRBORNE','TURNAROUND')) AS serviceable,
       count(*) FILTER (WHERE a.status = 'AIRBORNE') AS airborne,
       count(*) FILTER (WHERE a.status = 'STANDBY') AS standby,
       count(*) FILTER (WHERE a.status = 'QRA') AS qra,
       count(*) FILTER (WHERE a.status IN ('MAINT_SCHEDULED','MAINT_UNSCHEDULED')) AS maintenance,
       count(*) FILTER (WHERE a.status = 'AOG') AS aog
FROM aircraft a JOIN aircraft_type t ON t.id = a.aircraft_type_id AND t.category <> 'UAV_ROTARY_SMALL'
GROUP BY a.home_base_id, a.aircraft_type_id;

CREATE OR REPLACE VIEW v_parking_occupancy AS
SELECT p.base_id, p.slot_size, sum(p.slots_total) AS slots_total, sum(p.slots_unserviceable) AS slots_us,
       coalesce((SELECT count(*) FROM aircraft a JOIN aircraft_type t ON t.id = a.aircraft_type_id
                 WHERE a.current_base_id = p.base_id AND t.slot_size = p.slot_size AND a.status <> 'RETIRED'), 0) AS occupied
FROM parking_facility p GROUP BY p.base_id, p.slot_size;

-- currency: fighter/RPA 30 d, others 45 d; lapsing within 7 d (SIMULATED policy)
CREATE OR REPLACE VIEW v_aircrew_currency AS
SELECT h.aircrew_id, h.aircraft_type_id, h.last_flown_at,
       CASE WHEN c.stream IN ('FIGHTER','RPA') THEN 30 ELSE 45 END AS window_days,
       h.last_flown_at + make_interval(days => CASE WHEN c.stream IN ('FIGHTER','RPA') THEN 30 ELSE 45 END) AS expires_at,
       CASE
         WHEN h.last_flown_at IS NULL THEN 'LAPSED'
         WHEN h.last_flown_at + make_interval(days => CASE WHEN c.stream IN ('FIGHTER','RPA') THEN 30 ELSE 45 END) < sim_now() THEN 'LAPSED'
         WHEN h.last_flown_at + make_interval(days => CASE WHEN c.stream IN ('FIGHTER','RPA') THEN 23 ELSE 38 END) < sim_now() THEN 'LAPSING'
         ELSE 'CURRENT' END AS currency
FROM aircrew_type_hours h JOIN aircrew c ON c.id = h.aircrew_id;

-- fatigue: >3 sorties/24h, >30 h flown/7d, or <10 h rest when resting (SIMULATED policy)
CREATE OR REPLACE VIEW v_aircrew_fatigue AS
SELECT c.id AS aircrew_id,
       count(*) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '24 hours') AS sorties_24h,
       coalesce(sum(sc.hours_logged) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '24 hours'), 0) AS hours_24h,
       coalesce(sum(sc.hours_logged) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '7 days'), 0) AS hours_7d,
       coalesce(sum(sc.hours_logged) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '30 days'), 0) AS hours_30d,
       CASE WHEN c.rest_started_at IS NULL THEN NULL
            ELSE extract(epoch FROM sim_now() - c.rest_started_at) / 3600 END AS rest_hours,
       (count(*) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '24 hours') > 3
        OR coalesce(sum(sc.hours_logged) FILTER (WHERE s.actual_launch_ts > sim_now() - interval '7 days'), 0) > 30
        OR (c.duty_status = 'CREW_REST' AND c.rest_started_at > sim_now() - interval '10 hours')) AS fatigued
FROM aircrew c
LEFT JOIN sortie_crew sc ON sc.aircrew_id = c.id
LEFT JOIN sortie s ON s.id = sc.sortie_id AND s.actual_launch_ts > sim_now() - interval '30 days'
GROUP BY c.id;

CREATE OR REPLACE VIEW v_aircrew_availability AS
SELECT c.id AS aircrew_id, c.base_id, c.squadron_id, c.aircrew_role,
       (c.medical_status IN ('FIT_FULL','FIT_RESTRICTED')
        AND c.duty_status IN ('ON_DUTY','STANDBY','QRA')
        AND NOT coalesce(f.fatigued, false)
        AND EXISTS (SELECT 1 FROM v_aircrew_currency cur WHERE cur.aircrew_id = c.id AND cur.currency <> 'LAPSED')
       ) AS available
FROM aircrew c LEFT JOIN v_aircrew_fatigue f ON f.aircrew_id = c.id;

CREATE OR REPLACE VIEW v_fuel_days AS
SELECT fs.id AS fuel_storage_id, fs.base_id, fs.grade,
       coalesce(sum(t.quantity_l) FILTER (WHERE t.kind IN ('ISSUE_AIRCRAFT','ISSUE_VEHICLE')), 0) / 3.0 AS daily_issue_l,
       CASE WHEN coalesce(sum(t.quantity_l) FILTER (WHERE t.kind IN ('ISSUE_AIRCRAFT','ISSUE_VEHICLE')), 0) = 0 THEN NULL
            ELSE fs.current_l / (sum(t.quantity_l) FILTER (WHERE t.kind IN ('ISSUE_AIRCRAFT','ISSUE_VEHICLE')) / 3.0) END AS days_of_supply
FROM fuel_storage fs
LEFT JOIN fuel_transaction t ON t.fuel_storage_id = fs.id AND t.ts > sim_now() - interval '3 days'
GROUP BY fs.id;

CREATE OR REPLACE VIEW v_qra_status AS
SELECT q.base_id, q.aircraft_type_id, q.required_aircraft, q.readiness_min,
       (SELECT count(*) FROM aircraft a WHERE a.current_base_id = q.base_id AND a.aircraft_type_id = q.aircraft_type_id
          AND a.status = 'QRA') AS qra_aircraft,
       (SELECT count(*) FROM aircrew c JOIN v_aircrew_availability v ON v.aircrew_id = c.id
          WHERE c.base_id = q.base_id AND c.duty_status = 'QRA' AND v.available) AS qra_crew,
       ((SELECT count(*) FROM aircraft a WHERE a.current_base_id = q.base_id AND a.aircraft_type_id = q.aircraft_type_id
          AND a.status = 'QRA') >= q.required_aircraft
        AND (SELECT count(*) FROM aircrew c JOIN v_aircrew_availability v ON v.aircrew_id = c.id
          WHERE c.base_id = q.base_id AND c.duty_status = 'QRA' AND v.available) >= q.required_aircraft) AS met
FROM qra_posture q WHERE q.active;

-- railway station importance (pipeline/osm.py stations)
ALTER TABLE gis_point ADD COLUMN IF NOT EXISTS rank smallint;

-- area for label priority in vector tiles (computed once)
ALTER TABLE gis_admin_area ADD COLUMN IF NOT EXISTS area_km2 double precision;
UPDATE gis_admin_area SET area_km2 = ST_Area(geom::geography) / 1e6 WHERE area_km2 IS NULL AND geom IS NOT NULL;
