export type Role = "ADMIN" | "COMMAND_HQ" | "BASE_COMMANDER" | "VIEWER";

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  base_id: number | null;
  base_code: string | null;
  base_name: string | null;
  command_id: number | null;
  command_code: string | null;
}

export interface Base {
  id: number;
  code: string;
  name: string;
  side: "OWN" | "OTHER_INDIAN_MIL" | "FOREIGN";
  operator: string;
  base_type: string;
  country_iso3: string;
  affiliation: "FRIEND" | "HOSTILE" | "NEUTRAL";
  role_tags: string[] | null;
  wing: string | null;
  ops_status: string;
  elevation_m: number | null;
  command: string | null;
  lat: number;
  lon: number;
  metar_station: string | null;
  metar_station_km: number | null;
}

export interface BaseStatus {
  base_id: number;
  total?: number;
  serviceable?: number;
  effective?: number;
  airborne?: number;
  serviceability?: number | null;
  qra_met?: boolean;
  qra_required?: number;
  qra_aircraft?: number;
  alert_severity?: Severity;
  alerts?: number;
}

export type Severity = "INFO" | "CAUTION" | "WARNING" | "CRITICAL";

export interface Site {
  id: number;
  code: string;
  status: string;
  lat: number;
  lon: number;
  base: string | null;
  max_range_km?: number;
  system?: string;
  type?: string;
  category?: string;
  node_type?: string;
  launchers_ready?: number;
  launchers_total?: number;
}

export interface LiveTrack {
  hex: string;
  callsign: string | null;
  reg: string | null;
  icao_type: string | null;
  desc: string | null;
  operator: string | null;
  category: "CIVIL" | "CARGO" | "MILITARY" | "HELICOPTER" | "UAV" | "DRONE";
  cls: string;
  lat: number;
  lon: number;
  alt_m: number | null;
  on_ground: boolean;
  gs_kt: number | null;
  track_deg: number | null;
  squawk: string | null;
  emergency: string | null;
  source: string;
  age_s: number;
  is_military: boolean;
}

export interface FeedState {
  state: "LIVE" | "STALE" | "OFF";
  last_ok: number | null;
  error: string | null;
  count: number;
}

export interface AlertItem {
  id: number;
  kind: string;
  severity: Severity;
  status: string;
  message: string;
  raised_at: string;
  base_id: number | null;
  base_code?: string;
  command_code?: string;
  can_ack?: boolean;
  ack_by_name?: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  labels?: Record<string, Record<string, string>>;
}

export type Row = Record<string, unknown> & { id: number; version?: number; simulated?: boolean };

/** GET /inv/aircraft/by-type: one row per aircraft type that has aircraft. `total` excludes retired; QRA ⊂ serviceable. */
export interface AircraftTypeCount {
  id: number;
  name: string;
  category: "FIXED_WING" | "ROTARY_WING" | "UAV_FIXED_WING" | "UAV_ROTARY_SMALL";
  role: string;
  total: number;
  serviceable: number;
  qra: number;
  maintenance: number;
  unserviceable: number;
  depot: number;
  retired: number;
  squadrons: number;
  simulated: boolean;
}

export interface ColumnMeta {
  name: string;
  type: "int" | "float" | "bool" | "text" | "enum" | "date" | "datetime" | "list" | "point" | "geometry";
  nullable: boolean;
  editable: boolean;
  values?: string[];
  fk?: string;
}

export interface EntityMeta {
  entity: string;
  label: string;
  columns: ColumnMeta[];
  search: string[];
  readonly: boolean;
  admin_only: boolean;
  scope: string | null;
  retire: boolean;
  has_point: boolean;
}

// ---------------------------------------------------------------- Phase 2: decision support (PHASE2_IMPLEMENTATION_PLAN §9)
export type Priority = "P1" | "P2" | "P3" | "P4";

export interface MissionRow {
  id: number; code: string; name: string; mission_type: string; priority: Priority; status: string; version: number;
  window_start: string; window_end: string; required_aircraft: number; eligible_roles: string[] | null; loadout_code: string | null;
  on_station_min: number; min_quals: string[] | null; max_risk: string; notes: string | null; outcome: string; on_station_achieved_min: number;
  command: string | null; lon: number; lat: number; target_base: string | null; target_base_id: number | null;
  plan_id: number | null; item_id: number | null; tasked_base: string | null; tasked_type: string | null; tasked_n: number | null;
  tasked_launch: string | null; sortie_code: string | null; sortie_status: string | null; simulated: boolean;
  depends_on_id: number | null; depends_on: string | null;                                       // D41
  parent_mission_id: number | null; parent_code: string | null; part_no: number | null; parts: number | null;
  split_kind: "RELIEF" | "BASES" | null;                                                          // D42
}

export interface Reason { code: string; text: string; count: number; examples: string[]; nearest_km?: number }
export interface Fix { kind: string; text: string; parts?: number; t0?: string; sizes?: number[] }   // SPLIT_* fixes can be applied (D42)
export interface ExplRow { label: string; value: string; note?: string; tone?: string }

export interface PlanMission {
  id: number; code: string; name: string; mission_type: string; priority: Priority; status: string; window_start: string;
  window_end: string; required_aircraft: number; on_station_min: number; max_risk: string; command: string | null; lon: number; lat: number;
}

export interface PlanItemView {
  id: number; status: string; change: string | null; mission: PlanMission;
  base: { id: number; code: string; name: string }; recovery_base: { id: number; code: string; name: string } | null;
  type: { id: number; name: string; role: string; category: string }; loadout_code: string | null; n_aircraft: number;
  launch_ts: string; on_station_ts: string | null; recovery_ts: string;
  aircraft: { id: number; tail_no: string }[];
  crew: { id: number; aircraft_id: number; position: string; rank: string; name: string; callsign: string | null }[];
  risk: number; fuel_l: number;
  score: { cost: number; parts: Record<string, number>; duration_h: number; weapons: Record<string, number>; night: boolean;
    req: { quals: string[]; rating: string; ops: boolean }; snag?: SnagView | null } | null;
  explanation: { rows: ExplRow[]; binding: string[]; notes: string[]; impact: Record<string, unknown> } | null;
  alternatives: { base: string; type: string; launch: string; cost_delta: number; why_not: string }[] | null;
  route: [number, number][] | null; sortie: { id: number; code: string; status: string } | null; source_item_id: number | null;
  support: PlanSupport | null;
}

/** Predicted defect risk for a package's tails (ARCHITECTURE D38, snag-risk model). */
export interface SnagView {
  tails: Record<string, number>; package: number; worst: string; worst_p: number; drivers: string[]; auc: number | null; model_id: number | null;
}

/** GET /ops/models/snag-risk: the model card. */
export interface SnagModelCard {
  name: string; trained: boolean; id?: number; trained_at?: string | null; data_until?: string | null; features?: string[];
  method?: string; intended_use?: string; limits?: string; simulated?: boolean;
  metrics?: {
    test: { n: number; defects: number; base_rate: number; auc: number; brier: number; brier_base_rate: number; brier_skill: number;
      log_loss: number; top_decile_lift: number; calibration: { predicted: number; observed: number; n: number }[] };
    train: { n: number; defects: number; auc: number; brier: number; brier_skill: number };
    split: { train_until: string; test_from: string }; coefficients: Record<string, number>; intercept: number; labels: Record<string, string>;
  };
}

/** GET /ops/fleet/snag-risk: serviceable tails ranked by predicted defect risk. */
export interface FleetSnagRisk {
  items: { aircraft_id: number; tail_no: string; type: string; base: string; p: number; hours_left: number; recent_defects: number; why: string[] }[];
  fleet_mean?: number; n?: number; hours?: number; model: { id: number; auc: number } | null; simulated: true;
}

/** A package's support leg (ARCHITECTURE D36): today a tanker meeting the receivers on their outbound leg. */
export interface PlanSupport {
  kind: "AAR"; base: { id: number; code: string; name: string } | null; type: { id: number; name: string; role: string; category: string } | null;
  launch_ts: string; recovery_ts: string; rv: [number, number]; rv_start: string; rv_end: string; fuel_l: number; transit_min: number | null;
  aircraft: { id: number; tail_no: string }[]; crew: { id: number; position: string; rank: string; name: string; callsign: string | null }[];
  sortie: { id: number; code: string; status: string } | null;
}

export interface PlanKpis {
  missions: number; covered: number; unmet: number; by_priority: Record<Priority, { covered: number; of: number }>;
  sorties?: number; flying_hours?: number; fuel_l?: number; risk_peak?: number; risk_mean?: number; aircraft?: number; aircrew?: number;
  tanker_sorties?: number; snag_expected?: number | null; qra_postures?: number; qra_met?: number; qra_backfill?: number; candidates?: number; solver_status: string; solve_ms: number;
  total_ms?: number; violations?: number; rung?: string; changes?: Record<string, number>; proposal_ms?: number; issues?: string[];
}

export interface PlanView {
  plan: { id: number; kind: "PLAN" | "RETASK" | "WHATIF"; status: string; scope: string; preset: string; version: number; created_at: string;
    horizon_start: string; horizon_end: string; solver_status: string | null; solve_ms: number | null; kpis: PlanKpis; summary: string | null;
    parent_plan_id: number | null; approved_by: number | null; approved_at: string | null; committed_at: string | null; simulated: boolean };
  items: PlanItemView[];
  unmet: { id: number; mission: PlanMission; reasons: Reason[]; fixes: Fix[]; dropped_item_id: number | null }[];
}

export interface PlanListRow {
  id: number; kind: string; status: string; scope: string; preset: string; created_at: string; committed_at: string | null;
  solve_ms: number | null; kpis: PlanKpis | null; summary: string | null; parent_plan_id: number | null; created_by: string | null;
  command: string | null;
}

export interface Disruption {
  id: number; ts: string; kind: string; message: string; status: string; proposal_plan_id: number | null; proposal_ms: number | null;
  resolved_at: string | null; created_at: string; base: string | null;
}

export interface SimTrack {
  track_id: string; kind: "SIM_IAF" | "SIM_UNKNOWN"; simulated: true; lat: number; lon: number; heading_deg: number; alt_m: number;
  gs_kt: number; phase: string; callsign: string; sortie_id?: number; sortie_code?: string; tail_no?: string; type?: string;
  mission_type?: string; origin?: string; base?: string; status?: string; detected?: boolean; interceptor_base?: string | null;
}

export interface SimClock { sim_now: string; speed: number; paused: boolean; tick_no: number }
