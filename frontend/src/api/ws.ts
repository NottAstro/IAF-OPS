import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useStore } from "../store";

const TYPE_KEYS: Record<string, string[][]> = {
  aircraft: [["base-status"], ["summary"], ["overview"], ["inv"]],
  aircrew: [["summary"], ["overview"], ["inv"], ["pilot"]],
  sortie: [["summary"], ["inv"]],
  fuel_storage: [["summary"], ["overview"], ["inv"]],
  radar_site: [["sites"], ["summary"], ["overview"]],
  air_defence_battery: [["sites"], ["summary"], ["overview"]],
  comms_node: [["sites"], ["summary"]],
  stock_level: [["summary"], ["inv"]],
  ground_crew_strength: [["summary"], ["inv"]],
  plan: [["plans"], ["plan"], ["ops-summary"], ["ops-routes"], ["tasking"], ["scenarios"], ["scenario-response"]],
  disruption: [["disruptions"], ["ops-summary"], ["scenarios"], ["scenario-response"]],
  mission: [["missions"], ["ops-summary"], ["ops-missions"], ["plan"]],
  runway: [["summary"], ["ops-wx"], ["scenario-response"]],
  scenario: [["scenarios"], ["scenario-response"]],
};

/** One WebSocket per session: entity changes invalidate queries, new alerts raise toasts (FR-SIM-10). */
export function useLiveSocket(enabled: boolean) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    let ws: WebSocket | null = null;
    let lastSeq = 0;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;
    let ping: ReturnType<typeof setInterval>;
    let lastInvalidate = 0;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/v1/ws`);
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (lastSeq && msg.seq > lastSeq + 1) qc.invalidateQueries(); // gap: resync over REST
        lastSeq = msg.seq;
        const st = useStore.getState();
        if (msg.topic === "tracks.sim") return st.set({ simTracks: msg.data });
        if (msg.topic === "sim.clock") return st.set({ simClock: msg.data });
        if (msg.topic === "retask.proposal") {
          ["plans", "plan", "disruptions", "ops-summary", "scenarios", "scenario-response"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
          return st.toast(`A change to the plan is waiting for your decision (${msg.data.summary}). Open the Planner.`, "WARNING");
        }
        if (msg.topic === "plan.ready" || msg.topic === "disruption") {
          ["plans", "disruptions", "ops-summary"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
          return;
        }
        if (msg.topic === "exercise.inject") {
          ["exercise", "scenarios", "scenario-response", "summary", "ops-wx", "ops-zones", "missions"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
          return st.toast(`Scenario: ${msg.data.message}`, "WARNING");
        }
        if (msg.topic === "entity.changed") {
          const now = Date.now();
          if (now - lastInvalidate < 2500) return; // throttle refetch storms
          lastInvalidate = now;
          const keys = new Set<string>();
          for (const t of msg.data.types as string[]) for (const k of TYPE_KEYS[t] ?? []) keys.add(k[0]);
          keys.add("alerts");
          keys.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
        } else if (msg.topic === "alert") {
          const a = msg.data;
          qc.invalidateQueries({ queryKey: ["alerts"] });
          qc.invalidateQueries({ queryKey: ["base-status"] });
          if ((a.event === "raised" || a.event === "escalated") && (a.severity === "WARNING" || a.severity === "CRITICAL"))
            st.toast(a.message, a.severity);
        }
      };
      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 3000);
      };
    };
    connect();
    ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(ping);
      ws?.close();
    };
  }, [enabled, qc]);
}
