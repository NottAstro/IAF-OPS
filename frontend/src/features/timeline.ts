// Pure layout for the package timeline (features/ops.tsx Timeline). No React, so it is unit-tested (timeline.test.ts).
import type { PlanItemView, Priority } from "../api/types";

export interface Bar {
  key: string;            // unique per bar ("123" package, "123#AAR" its tanker leg)
  itemId: number;         // the plan item it selects
  row: string;            // base code the bar sits on
  start: string;          // ISO launch
  end: string;            // ISO recovery
  label: string;
  title: string;
  priority: Priority;
  changed: boolean;
  support: boolean;
}

/** One bar per package, plus one per tanker leg on the tanker's own base row. */
export function barsOf(items: PlanItemView[]): Bar[] {
  const out: Bar[] = [];
  for (const i of items) {
    const code = i.mission.code.replace(/^SIM-/, "");
    out.push({
      key: String(i.id), itemId: i.id, row: i.base.code, start: i.launch_ts, end: i.recovery_ts, label: code,
      title: `${i.mission.code} ${i.mission.priority} · ${i.n_aircraft} × ${i.type.name}${i.support ? " + tanker" : ""}`,
      priority: i.mission.priority, changed: !!i.change && i.change !== "KEPT", support: false,
    });
    if (i.support?.base)
      out.push({
        key: `${i.id}#AAR`, itemId: i.id, row: i.support.base.code, start: i.support.launch_ts, end: i.support.recovery_ts,
        label: `AAR ${code}`, title: `Tanker ${i.support.type?.name ?? ""} for ${i.mission.code}`, priority: i.mission.priority,
        changed: !!i.change && i.change !== "KEPT", support: true,
      });
  }
  return out;
}

/** Greedy interval packing: bars that overlap on one row go to separate lanes. `x` maps time to pixels; `minW` is the
 * width a bar label needs, so labels never collide either. Returns lane per bar key and lane count per row. */
export function packLanes(bars: Bar[], x: (iso: string) => number, minW = 50, gap = 4) {
  const lane = new Map<string, number>();
  const lanes = new Map<string, number>();
  const rows = [...new Set(bars.map((b) => b.row))].sort();
  for (const r of rows) {
    const ends: number[] = [];
    for (const b of bars.filter((v) => v.row === r).sort((p, q) => p.start.localeCompare(q.start) || p.key.localeCompare(q.key))) {
      const a = x(b.start);
      let k = ends.findIndex((e) => e + gap <= a);
      if (k < 0) k = ends.push(0) - 1;
      ends[k] = Math.max(a + minW, x(b.end));
      lane.set(b.key, k);
    }
    lanes.set(r, Math.max(1, ends.length));
  }
  return { rows, lane, lanes };
}
