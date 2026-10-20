import { describe, expect, it } from "vitest";
import { BASES, MISSION_WORD, ROUTINE, SCRIPTS, chosen, isGround, packageState, planFocus, slotOffset, statusAt, statusWord, timesOf, validRun } from "./scripts";

const MIN = 60e3;
const at = (t0: string, m: number) => new Date(Date.parse(t0) + m * MIN).toISOString();

describe("scripted Planner (D66)", () => {
  it("every scenario reads the same way", () => {
    expect(SCRIPTS.map((s) => s.code).sort()).toEqual(["air-attack", "avalanche", "fleet-grounding", "fuel-disruption", "monsoon-front",
      "radar-outage", "runway-closure", "trainer-crash"]);
    for (const s of [...SCRIPTS, ROUTINE]) {
      expect(s.happened.length, s.code).toBeGreaterThanOrEqual(2);
      expect(s.missions.length, s.code).toBeGreaterThanOrEqual(2);
      for (const m of s.missions) {
        expect(m.options, m.id).toHaveLength(2);
        for (const p of [m.pkg, ...m.options.map((o) => o.pkg)]) if (p) {
          expect(BASES[p.base], `${m.id} ${p.base}`).toBeDefined();
          expect(p.why.length).toBeGreaterThan(0);
        }
      }
    }
  });

  it("a package moves through its sortie on the sim clock", () => {
    const pkg = SCRIPTS.find((x) => x.code === "avalanche")!.missions[0].pkg!;   // Cheetah: lead 15 min, 2 h
    const t0 = "2026-10-20T00:00:00Z";
    expect(statusAt(pkg, null, t0)).toBe("waiting");
    expect(statusAt(pkg, t0, at(t0, 10))).toBe("approved");
    expect(statusAt(pkg, t0, at(t0, 20))).toBe("airborne");        // 20% of 120 min = 24 min outbound
    expect(statusAt(pkg, t0, at(t0, 60))).toBe("on station");
    expect(statusAt(pkg, t0, at(t0, 120))).toBe("returning");
    expect(statusAt(pkg, t0, at(t0, 136))).toBe("landed");
    expect(timesOf(pkg, t0, at(t0, 999)).launch).toBe(Date.parse(t0) + 15 * MIN);   // fixed once approved
    expect(statusAt(null, t0, t0)).toBe("not flown");
  });

  it("a package waits at its base, flies to its target, holds there on station and comes home", () => {
    const m = SCRIPTS.find((x) => x.code === "avalanche")!.missions[0], pkg = m.pkg!;
    const t0 = "2026-10-20T00:00:00Z", home = [BASES[pkg.base][1], BASES[pkg.base][2]];
    const at_ = (min: number) => packageState(m, pkg, t0, at(t0, min))!;
    expect(at_(5)).toMatchObject({ st: "approved", atBase: true, pos: home });
    const [x, y] = at_(pkg.lead + pkg.hours * 30).pos;                          // mid-sortie: on station
    expect(Math.abs(x - m.target[0])).toBeLessThan(0.1);
    expect(Math.abs(y - m.target[1])).toBeLessThan(0.1);
    expect(at_(1000)).toMatchObject({ st: "landed", atBase: true, pos: home });
  });

  it("decisions pick the package; old records from a reused run id are ignored", () => {
    const m = SCRIPTS[0].missions[0];
    expect(chosen(m, undefined)).toBe(m.pkg);
    expect(chosen(m, 1)).toBe(m.options[1].pkg);
    expect(chosen(m, "accept")).toBeNull();
    const rec = { started: "2026-10-20T00:00:00Z", dec: {}, approvedAt: null };
    expect(validRun(rec, "2026-10-20T00:00:30Z")).toBe(rec);
    expect(validRun(rec, "2026-10-21T00:00:00Z")).toBeUndefined();
  });

  it("a focused package (D71) sits at its base until launch, then flies the route in formation", () => {
    const s = SCRIPTS.find((x) => x.code === "air-attack")!;
    const m = s.missions.find((x) => (x.pkg?.n ?? 0) >= 2)!, home = [BASES[m.pkg!.base][1], BASES[m.pkg!.base][2]];
    const t0 = "2026-10-20T00:00:00Z", runs = [{ id: 7, code: "air-attack", started_sim: t0 }];
    const demo = { "7": { started: t0, dec: {}, approvedAt: t0 } };
    const before = planFocus(runs, demo, "7", m.id, at(t0, 1))!;
    expect(before.st).toBe("approved");
    expect(before.ps!.atBase).toBe(true);
    expect(before.ps!.pos).toEqual(home);
    const out = planFocus(runs, demo, "7", m.id, at(t0, m.pkg!.lead + 5))!;
    expect(out.st).toBe("airborne");
    expect(out.ps!.pos).not.toEqual(home);
    for (const atBase of [false, true]) {                                     // every aircraft has its own place
      expect(new Set(Array.from({ length: 4 }, (_, i) => slotOffset(i, 4, atBase).join())).size).toBe(4);
    }
    expect(slotOffset(0, 2)).toEqual([0, 0]);                                   // the leader flies the route
    const [hx, hy] = home, [px, py] = out.ps!.pos, [tx, ty] = m.target;   // in transit it is on the line base → target
    expect(Math.abs((tx - hx) * (py - hy) - (ty - hy) * (px - hx))).toBeLessThan(1e-9);
    expect(planFocus(runs, {}, "7", m.id, t0)!.st).toBe("waiting");
    expect(planFocus([], demo, "7", m.id, t0)).toBeNull();                  // the scenario has ended
  });

  it("every mission says what it does, and a ground package drives (D82)", () => {
    for (const sc of [...SCRIPTS, ROUTINE]) for (const m of sc.missions) expect(MISSION_WORD[m.mtype], m.id).toBeTruthy();
    const pick = SCRIPTS.find((x) => x.code === "trainer-crash")!.missions[0];
    expect(pick.mtype).toBe("rescue");
    expect(isGround(pick.pkg!.type)).toBe(true);                               // the base ambulance, not a helicopter
    expect(isGround("Cheetah/Chetak")).toBe(false);
    expect(statusWord("airborne", "Ambulance")).toBe("en route");
    expect(statusWord("on station", "Ambulance")).toBe("on scene");
    expect(statusWord("airborne", "Su-30MKI")).toBe("airborne");
    const t0 = "2026-10-20T00:00:00Z", mid = pick.pkg!.lead + pick.pkg!.hours * 30;   // half-way: on scene
    const a = packageState(pick, pick.pkg!, t0, at(t0, mid))!, b = packageState(pick, pick.pkg!, t0, at(t0, mid + 5))!;
    expect(a.st).toBe("on station");
    expect(a.pos).toEqual(b.pos);                                               // waits at the pilot; aircraft orbit instead
  });
});
