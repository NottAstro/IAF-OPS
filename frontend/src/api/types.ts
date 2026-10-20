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

export interface TrailPoint { lat: number; lon: number; alt_m: number | null; ts: number }
export interface RouteAirport { iata_code?: string; name?: string; latitude?: number; longitude?: number }
export interface LiveEnrichment {
  aircraft?: Record<string, string>;
  route?: { origin?: RouteAirport; destination?: RouteAirport };
}

export interface FeedState {
  state: "LIVE" | "STALE" | "OFF";
  last_ok: number | null;
  error: string | null;
  count: number;
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
  exercise_run_id: number | null; tag: string;                                                    // D56: Routine or the scenario's name
}

export interface Reason { code: string; text: string; count: number; examples: string[]; nearest_km?: number }
export interface Fix { kind: string; text: string; parts?: number; t0?: string; sizes?: number[] }   // SPLIT_* fixes can be applied (D42)
export interface ExplRow { label: string; value: string; note?: string; tone?: string }

export interface PlanMission {
  id: number; code: string; name: string; mission_type: string; priority: Priority; status: string; window_start: string;
  window_end: string; required_aircraft: number; on_station_min: number; max_risk: string; command: string | null; lon: number; lat: number;
  exercise_run_id: number | null; tag: string;   // D56: the scenario that demanded it, or "Routine"
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
    parent_plan_id: number | null; approved_by: number | null; approved_at: string | null; committed_at: string | null; simulated: boolean;
    why: string };
  items: PlanItemView[];
  unmet: { id: number; mission: PlanMission; reasons: Reason[]; fixes: Fix[]; dropped_item_id: number | null }[];
}

export interface PlanListRow {
  id: number; kind: string; status: string; scope: string; preset: string; created_at: string; committed_at: string | null;
  solve_ms: number | null; kpis: PlanKpis | null; summary: string | null; parent_plan_id: number | null; created_by: string | null;
  command: string | null; why: string | null;   // what made it (D57), null = a plan someone generated
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

// ---------------------------------------------------------------- scenarios (ARCHITECTURE D55)
export type Intensity = "LOW" | "MEDIUM" | "HIGH" | "SEVERE";
export type ScenarioCategory = "ACCIDENT" | "INFRASTRUCTURE" | "URGENT_TASKING" | "WEATHER" | "LOGISTICS" | "EQUIPMENT"
  | "SURVEILLANCE" | "HOSTILE_ACTION";
export type ParamValue = string | number | string[];
export interface ScenarioParam { key: string; label?: string; kind: "base" | "bases" | "type" | "choice" | "text" | "hidden";
  options?: (string | number)[]; default: ParamValue; unit?: string }
export interface ScenarioRunBrief { id: number; started_sim: string; intensity: Intensity | null; params: Record<string, ParamValue>;
  elapsed_min: number }
export interface ScenarioCard { id: number; code: string; name: string; category: ScenarioCategory; intensity: Intensity;
  summary: string; description: string; params: ScenarioParam[]; intensity_presets: Partial<Record<Intensity, Record<string, ParamValue>>>;
  adds: { priority: Priority; label: string }[]; run: ScenarioRunBrief | null }
export interface ScenarioCatalogue { scenarios: ScenarioCard[]; ended: { id: number; name: string; started_sim: string; ended_sim: string }[];
  committed_plan_id: number | null; sim: { enabled: boolean; sim_now: string; speed: number; paused: boolean } | null;
  bases: { code: string; name: string }[]; types: string[] }
export interface LiveScenario { id: number; name: string; code: string | null; intensity: Intensity | null; started_sim: string; elapsed_min: number; need: number }
export interface When { kind: "window" | "airborne" | "on_station" | "done" | "at"; a: string; b?: string }
export type ImpactStatus = "in" | "proposed" | "apply" | "uncovered" | "waiting" | "info";
export interface Impact { sev: "c" | "w" | "y" | "n"; what: string; sub: string; rec: string; alts: string[]; when: When | null;
  status: ImpactStatus; mission?: string; priority?: Priority; mission_id?: number; fix?: Fix | null }
export interface Requirement { label: string; need: string; from: string; have: string; when: When | null;
  status: "met" | "approve" | "wait"; q: [number, number] | null; scenario?: string; run_id?: number }
export interface ScenarioResponse {
  run: { id: number; name: string; code: string | null; category: ScenarioCategory | null; intensity: Intensity | null;
    status: "RUNNING" | "ENDED"; started_sim: string; elapsed_min: number };
  lead: string; state: "live" | "decision" | "ended";
  timeline: { ts: string; label: string; state: "done" | "now" | "next" }[];
  decision: { plan_id: number; summary: string; also: string[] } | null;
  impacts: Impact[]; need: number; requirements: Requirement[]; counts: { met: number; approve: number; wait: number };
}

// ---------------------------------------------------------------- situation and inventory transfers (ARCHITECTURE D56)
export interface BaseRef { id: number; code: string; name: string }
export interface TransferMove { key: string; kind: "FUEL" | "STOCK"; category: string; label: string; qty: number; unit: string;
  from_base: BaseRef; to_base: BaseRef; distance_km: number; depart_ts: string; eta: string; needed_by: string | null; late: boolean;
  reason: string }
export interface TransferUnmet { kind: "FUEL" | "STOCK"; category: string; label: string; qty: number; unit: string; to_base: BaseRef; reason: string }
export interface TransferRow { id: number; kind: "FUEL" | "STOCK"; category: string; label: string; qty: number; unit: string;
  status: "IN_TRANSIT" | "DELIVERED" | "CANCELLED"; eta: string; distance_km: number; reason: string | null;
  from_code: string; to_code: string; from_name: string; to_name: string }
export interface SituationMission { mission_id: number; code: string; name: string; priority: Priority; mission_type: string;
  tag: string; run_id: number | null; package: string | null; base: string | null; when: When | null;
  status: "in" | "proposed" | "uncovered"; change: string | null; reason: string | null }
export interface ScenarioBlock { run: ScenarioResponse["run"]; lead: string; state: "live" | "decision" | "ended";
  timeline: ScenarioResponse["timeline"]; impacts: Impact[]; need: number; bases: number[];
  analysis: Assessment | null; over: boolean; over_since: string | null }
/** D62: a package as the impact assessment describes it. */
export interface PkgView { base_id: number; base: string; type: string; n: number; launch: string; transit_min: number; fuel_l: number; risk: number }
/** D62: one mission the scenario changes, comparing the plan without it and with it. */
export interface ImpactChange { mission_id: number; code: string; name: string; priority: Priority; window: [string, string];
  kind: "moved" | "dropped" | "added"; before?: PkgView; after?: PkgView | null; reason?: string | null; reason_code?: string; blocked?: string }
export interface PlanTotals { covered: number; missions: number; by_priority: Record<Priority, { covered: number; of: number }>;
  sorties?: number; flying_hours?: number; fuel_l?: number; risk_peak?: number }
/** D62: the scenario's impact, from planning the same moment without and with it. */
export interface Assessment { assessed_at: string; took_s: number; bases: string[]; aircraft_there: number; aircraft_by_type: Record<string, number>;
  qra: { base: string; type: string; required: number; have_before: number; have_after: number }[]; aircraft_removed: number;
  before: PlanTotals; with: PlanTotals; flights_there_before: number; kept_there: number; knock_on: number; changes: ImpactChange[];
  transit_added_min: number; brief: string[] }
/** GET /ops/plans/options (D61): the planner's choice for a mission, its other options, and every base and type to pick by hand. */
export interface MissionOptions {
  plan_id: number;
  mission: { id: number; code: string; name: string; priority: Priority; window_start: string; window_end: string; required: number; on_station_min: number };
  current: { item_id: number; base_id: number; type_id: number; launch: string } | null;
  alternatives: { base: string; type: string; launch: string; cost_delta: number; why_not: string; base_id: number; type_id: number;
    n?: number; base_name?: string; transit_min?: number; d_transit_min?: number; d_fuel_l?: number; risk?: number }[];
  manual: { base_id: number; base: string; base_name: string; type_id: number; type: string; aircraft: number }[];
}
export interface Situation {
  runs: LiveScenario[]; selected: number | null; now: string;
  scenarios: ScenarioBlock[];          // All view (D59): one box per live scenario
  plan: { id: number; kind: "PLAN" | "RETASK"; status: string; summary: string | null; covered: number | null; missions: number | null;
    why: string; created_at: string; committed_at: string | null } | null;
  in_force: { id: number; since: string; covered: number | null; missions: number | null; flying: number } | null;   // D60
  decision: { plan_id: number; kind: "PLAN" | "RETASK"; summary: string | null; also: string[] } | null;
  run: ScenarioResponse["run"] | null; lead: string | null; timeline: ScenarioResponse["timeline"]; state: "live" | "decision" | "ended";
  missions: SituationMission[]; routine_unchanged: number; impacts: (Impact & { scenario?: string })[]; need: number;
  requirements: Requirement[]; counts: { met: number; approve: number; wait: number };
  transfers: { moves: TransferMove[]; unmet: TransferUnmet[]; in_transit: TransferRow[] };
}
