import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { type ConnectionSummary, useRoadConnection } from "../api/connectivity";
import { ErrorText, Loading, Row } from "../components/ui";
import { istTime, num } from "../lib/format";
import { useStore } from "../store";
import "./ConnectivityPanel.css";

/** Public base locations and distances only; operational inventory stays in the normal base panel. */
export function ConnectivityPanel() {
  const focus = useStore((s) => s.connectivityFocus);
  const set = useStore((s) => s.set);
  const summary = useQuery({ queryKey: ["base-connectivity", focus?.sourceId], queryFn: () => api<ConnectionSummary>(`/bases/${focus?.sourceId}/connections`), enabled: !!focus, staleTime: 300000 });
  const road = useRoadConnection(focus?.sourceId ?? null, focus?.destinationId ?? null, focus?.mode === "road");
  if (!focus) return null;
  const bases = summary.data?.connectivity.bases ?? [];
  const destination = bases.find((b) => b.id === focus.destinationId);
  return <aside className="card connectivity-card" aria-label="Base connectivity">
    <div className="card-title"><span>Base connectivity</span><button className="close" aria-label="Exit connectivity focus" onClick={() => set({ connectivityFocus: null })}>×</button></div>
    {summary.isLoading && <Loading />}
    {summary.error && <ErrorText error={summary.error} />}
    {summary.data && <>
      <p className="connectivity-source"><b>{summary.data.base.code}</b> {summary.data.base.name.replace(/^Air Force Station /, "")}</p>
      <div className="connectivity-actions">
        <button className="btn btn-sm" onClick={() => set({ connectivityFocus: { ...focus, fitSeq: focus.fitSeq + 1 } })}>Fit connections</button>
        <button className="btn btn-sm btn-ghost" onClick={() => set({ connectivityFocus: null })}>Exit focus</button>
      </div>
      <p className="dim">Nearby bases · ordered by direct distance</p>
      <div className="connectivity-destinations" aria-label="Destination base">
        {bases.map((b) => <button key={b.id} className={`connectivity-destination${b.id === focus.destinationId ? " on" : ""}`}
          aria-pressed={b.id === focus.destinationId} onClick={() => set({ connectivityFocus: { ...focus, destinationId: b.id } })}>
          <span><b>{b.code}</b> {b.name.replace(/^Air Force Station /, "")}</span><span className="mono">{num(b.distance_km, 1)} km</span>
        </button>)}
        {!bases.length && <div className="empty">No nearby bases available.</div>}
      </div>
      <div className="connectivity-actions" role="group" aria-label="Connection type">
        <button className={`btn btn-sm${focus.mode === "direct" ? " btn-primary" : ""}`} aria-pressed={focus.mode === "direct"}
          onClick={() => set({ connectivityFocus: { ...focus, mode: "direct" } })}>Direct</button>
        <button className={`btn btn-sm${focus.mode === "road" ? " btn-primary" : ""}`} aria-pressed={focus.mode === "road"} disabled={!destination}
          onClick={() => set({ connectivityFocus: { ...focus, mode: "road" } })}>Shortest road route</button>
      </div>
      {!destination && <p className="dim">Select a destination here or on the map. Your source base stays selected.</p>}
      {destination && <>
        <Row label="Connection" value={`${summary.data.base.code} → ${destination.code}`} />
        <Row label="Direct distance" value={`${num(destination.distance_km, 1)} km`} />
        {focus.mode === "road" && <div aria-live="polite">
          {road.isFetching && <p className="dim">Finding the shortest road route…</p>}
          {road.error && <ErrorText error={road.error} />}
          {road.data?.status === "unavailable" && <p className="notice">{road.data.message}</p>}
          {(road.error || road.data?.status === "unavailable") && <button className="btn btn-sm" disabled={road.isFetching} onClick={() => void road.refetch()}>Try road routing again</button>}
          {road.data?.status === "available" && <>
            <Row label="Road distance" value={`${num(road.data.road_distance_km, 1)} km`} />
            <p className="dim">Road distance is between road-network endpoints. Dotted links to base locations are estimated connections, not verified entrances.</p>
            <p className="dim">Distance-based route; provider search limits and map completeness can affect the result. No live traffic or verified access information.</p>
            <p className="dim">Retrieved {istTime(road.data.fetched_at, true)}</p>
          </>}
        </div>}
      </>}
      <p className="dim">Direct lines are geographic connections, not validated flight paths. Your normal map settings return when you exit focus.</p>
      <div className="connectivity-credit">Routing: <a href="https://valhalla.openstreetmap.de/" target="_blank" rel="noreferrer">Valhalla / FOSSGIS</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a> · <a href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noreferrer">Fix the map</a></div>
    </>}
  </aside>;
}
