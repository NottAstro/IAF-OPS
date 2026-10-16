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
