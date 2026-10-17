// Unit tests for the package timeline layout (timeline.ts): bars per package and tanker leg, lane packing. `npm test`.
import { describe, expect, it } from "vitest";
import type { PlanItemView } from "../api/types";
import { barsOf, packLanes, type Bar } from "./timeline";

const T0 = Date.parse("2026-10-17T06:00:00Z");
const at = (min: number) => new Date(T0 + min * 60e3).toISOString();

function item(id: number, base: string, from: number, to: number, extra: Partial<PlanItemView> = {}): PlanItemView {
  return {
    id, status: "PROPOSED", change: null, n_aircraft: 2, launch_ts: at(from), recovery_ts: at(to),
    mission: { id: 100 + id, code: `SIM-CAP-WAC-${String(id).padStart(3, "0")}`, priority: "P2" },
    base: { id: 1, code: base, name: base }, type: { id: 1, name: "Su-30MKI", role: "FIGHTER_MULTIROLE", category: "FIXED_WING" },
    support: null, ...extra,
  } as unknown as PlanItemView;
}

const px = (iso: string) => (Date.parse(iso) - T0) / 60e3;    // 1 px per minute

describe("barsOf", () => {
  it("makes one bar per package, on its base row, with the SIM- prefix dropped", () => {
    const bars = barsOf([item(1, "VIAX", 0, 120)]);
    expect(bars).toHaveLength(1);
    expect(bars[0]).toMatchObject({ key: "1", itemId: 1, row: "VIAX", label: "CAP-WAC-001", support: false, changed: false });
  });

  it("adds the tanker leg on the tanker's own base and links it to the same item", () => {
    const it = item(2, "VIAX", 30, 200, {
      support: { kind: "AAR", base: { id: 9, code: "VIAG", name: "Agra" }, type: { id: 5, name: "Il-78MKI", role: "TANKER", category: "FIXED_WING" },
        launch_ts: at(10), recovery_ts: at(150), rv: [75, 30], rv_start: at(60), rv_end: at(80), fuel_l: 1, transit_min: 40,
        aircraft: [], crew: [], sortie: null },
    });
    const bars = barsOf([it]);
    expect(bars.map((b) => [b.key, b.row, b.support])).toEqual([["2", "VIAX", false], ["2#AAR", "VIAG", true]]);
    expect(bars[1].itemId).toBe(2);
    expect(bars[0].title).toContain("+ tanker");
  });

  it("marks anything but KEPT as changed", () => {
    expect(barsOf([item(3, "VIAX", 0, 60, { change: "KEPT" })])[0].changed).toBe(false);
    for (const c of ["SWAP", "MOVED", "NEW", "DIVERT", "REROLE"])
      expect(barsOf([item(3, "VIAX", 0, 60, { change: c })])[0].changed).toBe(true);
  });
});

describe("packLanes", () => {
  const bar = (key: string, row: string, from: number, to: number): Bar =>
    ({ key, itemId: 0, row, start: at(from), end: at(to), label: key, title: key, priority: "P2", changed: false, support: false });

  it("keeps non-overlapping bars in one lane and stacks overlapping ones", () => {
    const { lane, lanes } = packLanes([bar("a", "VIAX", 0, 100), bar("b", "VIAX", 200, 300), bar("c", "VIAX", 50, 150)], px);
    expect(lane.get("a")).toBe(0);
    expect(lane.get("b")).toBe(0);
    expect(lane.get("c")).toBe(1);
    expect(lanes.get("VIAX")).toBe(2);
  });

  it("gives a short bar room for its label (minW) so labels never collide", () => {
    // b starts 20 px after a short 10-px bar: free by time, but a's label needs 50 px
    const { lane } = packLanes([bar("a", "R", 0, 10), bar("b", "R", 30, 40)], px, 50, 4);
    expect(lane.get("b")).toBe(1);
    const roomy = packLanes([bar("a", "R", 0, 10), bar("b", "R", 60, 70)], px, 50, 4);
    expect(roomy.lane.get("b")).toBe(0);
  });

  it("packs rows independently, sorted, and is stable for equal starts", () => {
    const { rows, lane, lanes } = packLanes([bar("z", "VIDP", 0, 50), bar("y", "VIAX", 0, 50), bar("x", "VIAX", 0, 50)], px);
    expect(rows).toEqual(["VIAX", "VIDP"]);
    expect([lane.get("x"), lane.get("y")]).toEqual([0, 1]);         // ties broken by key
    expect(lanes.get("VIDP")).toBe(1);
  });

  it("never puts two overlapping bars in the same lane", () => {
    const bars = Array.from({ length: 40 }, (_, i) => bar(`k${i}`, "VIAX", (i * 37) % 600, ((i * 37) % 600) + 30 + (i % 7) * 25));
    const { lane } = packLanes(bars, px, 0, 0);
    for (const a of bars)
      for (const b of bars)
        if (a.key < b.key && lane.get(a.key) === lane.get(b.key))
          expect(px(a.end) <= px(b.start) || px(b.end) <= px(a.start)).toBe(true);
  });
});
