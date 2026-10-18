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
