import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { LiveEnrichment, RouteAirport, TrailPoint } from "./types";

/** Shared queries let the map and card describe the very same observed path and schedule. */
export function useLivePath(hex: string | null, callsign: string | null, enabled: boolean) {
  const trail = useQuery({
    queryKey: ["live-trail", hex], queryFn: () => api<TrailPoint[]>(`/live/aircraft/${hex}/trail`),
    enabled: enabled && hex != null,
  });
  const enrich = useQuery({
    queryKey: ["enrich", hex, callsign],
    queryFn: () => api<LiveEnrichment>(`/live/aircraft/${hex}/enrich?callsign=${encodeURIComponent(callsign ?? "")}`),
    enabled: enabled && hex != null, staleTime: 86400000,
  });
  return { trail, enrich };
}

const coordinates = (a?: RouteAirport): [number, number] | null =>
  typeof a?.longitude === "number" && Number.isFinite(a.longitude) && Math.abs(a.longitude) <= 180 &&
  typeof a.latitude === "number" && Number.isFinite(a.latitude) && Math.abs(a.latitude) <= 90 ? [a.longitude, a.latitude] : null;

/** adsbdb supplies scheduled airports, never a filed flight plan. Require both airport locations. */
export function scheduledDestination(route: LiveEnrichment["route"]): [number, number] | null {
  return coordinates(route?.origin) ? coordinates(route?.destination) : null;
}

/** "Kempegowda International Airport" → "Kempegowda": short enough for a map label. */
export const shortAirport = (name?: string) => (name ?? "").replace(/\s+(International\s+)?Airport$/i, "").replace(/\s+International$/i, "");

export interface RouteEnd { at: [number, number]; code: string; name: string }
/** Both scheduled airports, so the map can mark where the dotted legs end (D77); null unless both have a location. */
export function scheduledAirports(route: LiveEnrichment["route"]): { origin: RouteEnd; destination: RouteEnd } | null {
  const o = coordinates(route?.origin), d = coordinates(route?.destination);
  if (!o || !d) return null;
  const end = (a: RouteAirport | undefined, at: [number, number]): RouteEnd => ({ at, code: a?.iata_code ?? "", name: shortAirport(a?.name) });
  return { origin: end(route?.origin, o), destination: end(route?.destination, d) };
}
