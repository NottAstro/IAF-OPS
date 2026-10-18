import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

export interface NearbyBase { id: number; code: string; name: string; lat: number; lon: number; distance_km: number | string }
export interface ConnectionSummary {
  base: { id: number; code: string; name: string; lat: number; lon: number };
  connectivity: { bases: NearbyBase[] };
}
export type RoadConnection = {
  source_id: number; destination_id: number; status: "available";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  road_distance_km: number; source: string; fetched_at: string;
} | { source_id: number; destination_id: number; status: "unavailable"; message: string };

export function useRoadConnection(sourceId: number | null, destinationId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["base-connection", sourceId, destinationId],
    queryFn: () => api<RoadConnection>(`/bases/${sourceId}/connections/${destinationId}`),
    enabled: enabled && sourceId != null && destinationId != null, staleTime: 600000, retry: false,
  });
}
