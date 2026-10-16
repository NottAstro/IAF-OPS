// 3D-style illustrations of ground equipment, air defence and radar systems, built from simple parts with the iso
// engine. Original drawings at typical proportions; they show what kind of equipment it is, not a specific make.
import { type Item, Scene, type V3, mul, norm } from "./iso";

const C = {
  iaf: "#56738f", iafLt: "#9fb2c4", olive: "#5d6a3b", oliveDk: "#434c2b", canvas: "#707453", red: "#c0392b", white: "#e3e8ed",
  yellow: "#e2a82a", orange: "#db7a2a", steel: "#aeb8c2", grey: "#7d8995", dark: "#2c3137", black: "#22262b", light: "#f4e8b4",
  sand: "#a8956b", car: "#3e566d", green: "#3f6f4c",
};
const rad = (d: number) => (d * Math.PI) / 180;

/** Plain-English line under each equipment card. */
export const DESCRIPTION: Record<string, string> = {
  FUEL_BOWSER: "Tanker truck that refuels aircraft on the flight line",
  TOW_TRACTOR: "Tug that tows aircraft between hangar, apron and runway",
  UTILITY_TRUCK: "General cargo and stores transport",
  CRASH_FIRE_TENDER: "Airfield fire-fighting and crash rescue vehicle",
  TROOP_CARRIER: "Moves personnel around the station",
  AMBULANCE: "Medical evacuation and crash rescue support",
  STAFF_CAR: "Light vehicle for officers and duty staff",
  RUNWAY_SWEEPER: "Clears debris (FOD) from runways and taxiways",
  MOBILE_ATC: "Mobile air traffic control tower",
  CARGO_LOADER: "Raises cargo pallets to transport aircraft doors",
  HYDRANT_DISPENSER: "Refuels aircraft from the underground fuel hydrant",
  SNOW_CLEARER: "Ploughs snow and ice off runways and taxiways",
  DEICER: "Sprays de-icing fluid on aircraft before take-off",
  GPU: "Supplies electrical power to parked aircraft",
  TOW_BAR: "Connects the tug to an aircraft's nose wheel",
  AIRCRAFT_JACK: "Lifts aircraft for wheel, tyre and undercarriage work",
  HYDRAULIC_RIG: "Powers aircraft hydraulics for ground checks",
  AIR_START_UNIT: "Supplies compressed air to start jet engines",
  WEAPON_LOADER: "Lifts missiles and bombs onto aircraft pylons",
  AC_COOLING_CART: "Cools cockpit and avionics while on the ground",
  ENGINE_STAND: "Holds and moves an engine removed for maintenance",
  OXYGEN_CART: "Refills aircraft breathing-oxygen systems",
  NITROGEN_CART: "Inflates tyres and charges struts with nitrogen",
  "S-400 Triumf (Sudarshan Chakra)": "Long-range surface-to-air missile launcher",
  "MR-SAM (Barak-8)": "Medium-range missile, launched vertically",
  "Akash": "Short-range surface-to-air missile on a tracked launcher",
  "Akash-NG": "Next-generation Akash missile in sealed canisters",
  "SPYDER-SR": "Quick-reaction short-range air defence missile",
  "SPYDER-MR": "Quick-reaction medium-range air defence missile",
  "S-125 Pechora (upgraded)": "Older short-range missile system, upgraded",
  "Igla-S": "Shoulder-fired missile against low-flying aircraft",
  "Counter-drone system (generic)": "Detects, jams and disables small drones",
  "L/70 40 mm AD gun": "40 mm anti-aircraft gun with fire control",
  "ZU-23-2 twin 23 mm": "Twin-barrel 23 mm anti-aircraft gun",
  "Arudhra (MPR)": "Long-range air surveillance radar",
  "THD-1955": "Long-range fixed surveillance radar",
  "Aslesha (LLLR)": "Lightweight low-level radar for gap filling",
  "Ashwini (LLTR)": "Transportable low-level surveillance radar",
  "EL/M-2084": "Multi-mission 3D radar on a trailer",
  "Rohini (3D CAR)": "Medium-range 3D surveillance radar",
  "Aerostat EL/M-2083": "Radar lifted on a tethered balloon",
  DATALINK_GS: "Ground station for the aircraft tactical data link",
  VUHF_RELAY: "Radio relay for air–ground voice on V/UHF",
  HF_STATION: "Long-range HF radio station",
  SATCOM_GS: "Satellite communications terminal",
  C2_NODE: "Command-and-control node linking sensors and shooters",
  NETWORK_HUB: "Air Force network hub for the station",
};

type Build = (s: Scene) => void;

/** Cab-over truck: chassis, wheels, cab with windscreen, side window, grille, lights and bumper. Returns the cab. */
function truck(s: Scene, o: { L: number; W: number; cabL: number; cabH: number; r: number; axles: number[]; cab: string; beacon?: string }): Item {
  const { L, W, cabL, cabH, r } = o;
  s.shadow(0, 0, L, W);
  for (const x of o.axles) { s.wheel([x, 0.2, r], r, 0.36); s.wheel([x, W - 0.2, r], r, 0.36); }
  s.ab(0.15, 0.4, r * 0.85, L - 0.4, W - 0.8, 0.38, C.dark);
  const cab = s.ab(L - cabL, 0, r * 1.1, cabL, W, cabH - r * 1.1, o.cab);
  s.glass(cab, "x", L, [0.1 * W, cabH - 1.0, 0.9 * W, cabH - 0.18]);
  s.glass(cab, "y", W, [L - cabL + 0.25, cabH - 0.95, L - 0.25, cabH - 0.25]);
  s.dec(cab, "x", L, [0.25 * W, r * 1.35, 0.75 * W, cabH - 1.15], C.dark);
  s.dec(cab, "x", L, [0.06 * W, r * 1.3, 0.18 * W, r * 1.3 + 0.18], C.light, { flat: true });
  s.dec(cab, "x", L, [0.82 * W, r * 1.3, 0.94 * W, r * 1.3 + 0.18], C.light, { flat: true });
  s.ab(L, 0.06, r * 0.9, 0.16, W - 0.12, 0.32, C.dark);
  if (o.beacon) s.ab(L - cabL * 0.6, W * 0.4, cabH, 0.25, W * 0.2, 0.14, o.beacon);
  return cab;
}

/** Small towed cart on four wheels with a tow bar. */
function cart(s: Scene, L: number, W: number, r = 0.26) {
  s.shadow(0, 0, L, W);
  for (const x of [0.45, L - 0.45]) { s.wheel([x, 0.08, r], r, 0.16); s.wheel([x, W - 0.08, r], r, 0.16); }
  s.line(null, [L - 0.1, W / 2, r + 0.15], [L + 0.9, W / 2, r * 0.9], C.dark, 0.07);
}

function missile(s: Scene, a: V3, b: V3, r: number, body = C.white, tip = C.dark) {
  const u = norm([b[0] - a[0], b[1] - a[1], b[2] - a[2]]);
  s.cyl(a, b, r, body);
  s.cyl(b, [b[0] + u[0] * r * 3, b[1] + u[1] * r * 3, b[2] + u[2] * r * 3], r, tip, { r2: r * 0.15, bias: 0.01 });
}

/** Planar radar array: a tilted panel facing the near side, with element grid. */
function array(s: Scene, x: number, y: number, z: number, w: number, h: number, tilt = 15, color = C.olive) {
  const n: V3 = [0, Math.cos(rad(tilt)), Math.sin(rad(tilt))], up: V3 = [0, -Math.sin(rad(tilt)), Math.cos(rad(tilt))];
  const t = 0.3;
  const it = s.box([x, y, z], [w, 0, 0], mul(n, t), mul(up, h), color);
  const f = (i: number, j: number): V3 => [x + w * i, y + n[1] * t + up[1] * h * j, z + n[2] * t + up[2] * h * j];
  for (let i = 1; i < 8; i++) s.line(it, f(i / 8, 0.04), f(i / 8, 0.96), "rgba(20,26,18,.55)", 0.035);
  for (let j = 1; j < 5; j++) s.line(it, f(0.02, j / 5), f(0.98, j / 5), "rgba(20,26,18,.55)", 0.035);
  return it;
}

const B: Record<string, Build> = {
  FUEL_BOWSER: (s) => {
    const W = 2.5;
    truck(s, { L: 9.5, W, cabL: 2.2, cabH: 3.0, r: 0.5, axles: [1.3, 2.6, 7.7], cab: C.iaf, beacon: C.orange });
    s.cyl([0.35, W / 2, 2.15], [7.05, W / 2, 2.15], 1.05, C.steel);
    s.ab(1.0, W / 2 - 0.3, 3.18, 5.2, 0.6, 0.06, C.grey);
    const cab2 = s.ab(6.95, 0.1, 1.0, 0.3, W - 0.2, 1.7, C.iaf);
    s.dec(cab2, "y", W - 0.1, [6.95, 1.4, 7.25, 2.4], C.yellow, { flat: true });
    s.line(null, [0.3, W - 0.4, 0.9], [0.3, W - 0.4, 3.1], C.grey, 0.06);
  },
  TOW_TRACTOR: (s) => {
    const L = 4.6, W = 2.3;
    s.shadow(0, 0, L, W);
    for (const x of [0.95, 3.6]) { s.wheel([x, 0.22, 0.55], 0.55, 0.42); s.wheel([x, W - 0.22, 0.55], 0.55, 0.42); }
    const b = s.ab(0.1, 0, 0.45, L - 0.2, W, 0.85, C.yellow);
    for (let i = 0; i < 6; i++) s.dec(b, "x", L - 0.1, [i * (W / 6), 0.55, (i + 0.5) * (W / 6), 1.15], C.black, { flat: true });
    s.ab(0.45, 0.2, 1.3, 1.55, 1.35, 1.05, "#38566f");
    s.ab(0.4, 0.15, 2.35, 1.65, 1.45, 0.1, C.yellow);
    s.ab(L - 0.05, W / 2 - 0.15, 0.55, 0.4, 0.3, 0.25, C.dark);
    s.line(null, [0.3, 0.25, 1.3], [0.3, 0.25, 2.6], C.dark, 0.08);
  },
  UTILITY_TRUCK: (s) => {
    const W = 2.4;
    truck(s, { L: 7.4, W, cabL: 2.3, cabH: 2.9, r: 0.5, axles: [1.4, 5.9], cab: C.iaf });
    s.ab(0.1, 0, 1.0, 4.9, W, 0.18, C.dark);
    s.ab(0.1, 0, 1.18, 4.9, 0.08, 0.7, C.iaf);
    s.ab(0.1, 0, 1.18, 0.08, W, 0.7, C.iaf);
    s.ab(0.6, 0.35, 1.18, 1.2, 0.9, 0.85, C.sand);
    s.ab(2.1, 0.45, 1.18, 1.0, 1.0, 0.6, C.sand);
    s.ab(0.7, 1.35, 1.18, 1.4, 0.8, 0.5, C.olive);
    s.ab(4.92, 0, 1.18, 0.08, W, 1.0, C.iaf);
    s.ab(0.1, W - 0.08, 1.18, 4.9, 0.08, 0.7, C.iaf);
  },
  CRASH_FIRE_TENDER: (s) => {
    const L = 11, W = 2.9;
    s.shadow(0, 0, L, W);
    for (const x of [1.5, 3.1, 9.0]) { s.wheel([x, 0.22, 0.62], 0.62, 0.42); s.wheel([x, W - 0.22, 0.62], 0.62, 0.42); }
    const body = s.ab(0.2, 0, 1.0, 8.3, W, 2.45, C.red);
    s.dec(body, "y", W, [0.2, 1.75, 8.5, 1.95], C.white, { flat: true });
    for (let x = 0.5; x < 8.2; x += 1.55) s.dec(body, "y", W, [x, 2.15, x + 1.35, 3.25], C.red);
    for (let x = 0.5; x < 8.2; x += 1.55) s.line(body, [x + 0.15, W, 2.3], [x + 1.2, W, 2.3], "rgba(0,0,0,.25)", 0.03);
    const cab = s.ab(8.55, 0, 0.9, 2.3, W, 2.55, C.red);
    s.glass(cab, "x", 10.85, [0.15, 2.2, W - 0.15, 3.3]);
    s.glass(cab, "y", W, [8.75, 2.2, 10.6, 3.25]);
    s.dec(cab, "y", W, [8.55, 1.75, 10.85, 1.95], C.white, { flat: true });
    s.ab(10.85, 0.06, 0.8, 0.18, W - 0.12, 0.4, C.dark);
    s.ab(9.3, 0.4, 3.45, 0.3, W - 0.8, 0.14, "#e74c3c");
    s.ab(9.3, 0.9, 3.45, 0.3, 0.4, 0.15, "#3b82f6", 0.01);
    s.cyl([7.6, W / 2, 3.45], [7.6, W / 2, 3.85], 0.32, C.grey);
    s.cyl([7.6, W / 2, 3.8], [9.4, W / 2, 4.05], 0.1, C.steel);
    s.ab(0.9, 0.35, 3.45, 5.5, 0.5, 0.08, C.steel);
  },
  TROOP_CARRIER: (s) => {
    const W = 2.5;
    truck(s, { L: 8.0, W, cabL: 2.3, cabH: 2.8, r: 0.52, axles: [1.4, 6.4], cab: C.olive });
    s.ab(0.1, 0, 1.0, 5.5, W, 0.28, C.oliveDk);
    const can = s.ab(0.1, 0, 1.28, 5.5, W, 1.85, C.canvas);
    for (let x = 0.9; x < 5.6; x += 1.15) { s.line(can, [x, W, 1.3], [x, W, 3.13], "rgba(30,32,20,.45)", 0.05); s.line(can, [x, 0, 3.13], [x, W, 3.13], "rgba(30,32,20,.45)", 0.05); }
  },
  AMBULANCE: (s) => {
    const L = 6.0, W = 2.2;
    s.shadow(0, 0, L, W);
    for (const x of [1.1, 4.8]) { s.wheel([x, 0.18, 0.42], 0.42, 0.3); s.wheel([x, W - 0.18, 0.42], 0.42, 0.3); }
    const body = s.ab(0.1, 0, 0.5, 4.4, W, 2.35, C.white);
    s.dec(body, "y", W, [0.1, 1.35, 4.5, 1.6], C.red, { flat: true });
    s.dec(body, "y", W, [1.8, 1.85, 2.4, 2.6], C.red, { flat: true });
    s.dec(body, "y", W, [1.72, 2.08, 2.48, 2.38], C.red, { flat: true });
    s.glass(body, "y", W, [3.0, 1.85, 4.2, 2.6]);
    const hood = s.ab(4.5, 0, 0.5, 1.45, W, 0.95, C.white);
    s.dec(hood, "x", 5.95, [0.08 * W, 0.7, 0.2 * W, 0.85], C.light, { flat: true });
    s.dec(hood, "x", 5.95, [0.8 * W, 0.7, 0.92 * W, 0.85], C.light, { flat: true });
    const cab = s.box([4.5, 0, 1.45], [0.75, 0, 0], [0, W, 0], [0, 0, 1.0], C.white);
    s.glass(cab, "x", 5.25, [0.15, 1.5, W - 0.15, 2.3]);
    s.ab(4.0, 0.3, 2.85, 0.25, W - 0.6, 0.12, "#e74c3c");
    s.ab(4.0, 0.95, 2.85, 0.25, 0.3, 0.13, "#3b82f6", 0.01);
    s.ab(5.95, 0.05, 0.4, 0.12, W - 0.1, 0.28, C.dark);
  },
  STAFF_CAR: (s) => {
    const L = 4.7, W = 1.85;
    s.shadow(0, 0, L, W);
    for (const x of [0.9, 3.8]) { s.wheel([x, 0.12, 0.36], 0.36, 0.24); s.wheel([x, W - 0.12, 0.36], 0.36, 0.24); }
    const body = s.ab(0.05, 0, 0.32, L - 0.1, W, 0.72, C.car);
    s.dec(body, "x", L - 0.05, [0.1, 0.55, 0.3, 0.7], C.light, { flat: true });
    s.dec(body, "x", L - 0.05, [W - 0.3, 0.55, W - 0.1, 0.7], C.light, { flat: true });
    const cabin = s.ab(1.0, 0.1, 1.04, 2.45, W - 0.2, 0.62, C.car);
    s.glass(cabin, "y", W - 0.1, [1.15, 1.1, 2.15, 1.58]);
    s.glass(cabin, "y", W - 0.1, [2.3, 1.1, 3.3, 1.58]);
    s.glass(cabin, "x", 3.45, [0.18, 1.08, W - 0.38, 1.6]);
  },
  RUNWAY_SWEEPER: (s) => {
    const W = 2.5;
    truck(s, { L: 7.2, W, cabL: 2.2, cabH: 2.9, r: 0.48, axles: [1.0, 5.6], cab: C.yellow, beacon: C.orange });
    s.cyl([2.9, 0.15, 0.45], [2.9, W - 0.15, 0.45], 0.42, "#3a3530");
    const hop = s.ab(0.2, 0, 1.05, 4.6, W, 1.75, C.yellow);
    s.dec(hop, "y", W, [0.4, 1.3, 4.6, 1.45], C.black, { flat: true });
    s.cyl([6.9, W - 0.1, 0.12], [6.9, W - 0.1, 0.2], 0.45, "#3a3530", { bias: 1 });
  },
  MOBILE_ATC: (s) => {
    const W = 2.5;
    truck(s, { L: 8.2, W, cabL: 2.3, cabH: 2.9, r: 0.5, axles: [1.4, 6.6], cab: C.iaf });
    const sh = s.ab(0.2, 0, 1.05, 5.5, W, 2.15, C.iafLt);
    s.dec(sh, "y", W, [0.5, 1.4, 1.4, 2.9], C.grey);
    s.ab(1.2, 0.3, 3.2, 1.9, 1.9, 1.15, "#35556f");
    s.ab(1.1, 0.2, 4.35, 2.1, 2.1, 0.12, C.white);
    s.line(null, [4.8, 0.5, 3.2], [4.8, 0.5, 6.4], C.grey, 0.07);
    s.cyl([4.8, 0.5, 5.6], [4.95, 0.75, 5.8], 0.42, C.white);
  },
  CARGO_LOADER: (s) => {
    const L = 8.5, W = 3.6;
    s.shadow(0, 0, L, W);
    for (const x of [1.3, 7.1]) { s.wheel([x, 0.25, 0.45], 0.45, 0.36); s.wheel([x, W - 0.25, 0.45], 0.45, 0.36); }
    s.ab(0.3, 0.3, 0.4, 7.9, W - 0.6, 0.45, C.yellow);
    for (const x of [1.5, 3.6]) { s.line(null, [x, W - 0.4, 0.85], [x + 1.8, W - 0.4, 1.95], C.dark, 0.09); s.line(null, [x, W - 0.4, 1.95], [x + 1.8, W - 0.4, 0.85], C.dark, 0.09); }
    const deck = s.ab(0.2, 0, 1.95, 6.2, W, 0.28, C.grey);
    for (let y = 0.3; y < W; y += 0.4) s.line(deck, [0.4, y, 2.23], [6.2, y, 2.23], "rgba(0,0,0,.35)", 0.04);
    s.ab(6.4, 0.6, 1.95, 1.9, W - 1.2, 0.22, C.grey);
    const cab = s.ab(6.6, 0, 0.85, 1.6, 1.3, 1.85, C.yellow);
    s.glass(cab, "x", 8.2, [0.1, 1.5, 1.2, 2.55]);
    s.glass(cab, "y", 1.3, [6.75, 1.5, 8.05, 2.55]);
  },
  HYDRANT_DISPENSER: (s) => {
    const W = 2.4;
    truck(s, { L: 6.4, W, cabL: 2.0, cabH: 2.7, r: 0.45, axles: [1.0, 5.1], cab: C.white, beacon: C.orange });
    const body = s.ab(0.2, 0, 1.0, 4.0, W, 1.4, C.white);
    s.dec(body, "y", W, [0.2, 1.7, 4.2, 1.9], C.yellow, { flat: true });
    s.cyl([2.6, 0.3, 2.85], [2.6, W - 0.3, 2.85], 0.45, C.dark);
    s.ab(0.1, 0.2, 2.45, 1.7, W - 0.4, 0.12, C.grey);
    s.line(null, [0.15, W - 0.2, 2.57], [0.15, W - 0.2, 3.3], C.yellow, 0.05);
    s.line(null, [1.75, W - 0.2, 2.57], [1.75, W - 0.2, 3.3], C.yellow, 0.05);
    s.line(null, [0.15, W - 0.2, 3.3], [1.75, W - 0.2, 3.3], C.yellow, 0.05);
  },
  SNOW_CLEARER: (s) => {
    const L = 8.4, W = 2.5;
    truck(s, { L, W, cabL: 2.3, cabH: 2.9, r: 0.52, axles: [1.3, 6.8], cab: C.orange, beacon: C.yellow });
    const body = s.ab(0.2, 0, 1.05, 5.2, W, 1.5, C.orange);
    s.dec(body, "y", W, [0.4, 1.3, 5.2, 1.45], C.black, { flat: true });
    const th = rad(22), Lb = 3.6;
    s.line(null, [L + 0.15, W / 2, 0.7], [L + 0.75, W / 2, 0.7], C.dark, 0.12);
    s.box([L + 0.95 + Math.sin(th) * Lb / 2, W / 2 - Math.cos(th) * Lb / 2, 0.2], [0.16, 0.06, 0], [-Math.sin(th) * Lb, Math.cos(th) * Lb, 0], [0, 0, 1.05], C.yellow);
  },
  DEICER: (s) => {
    const W = 2.5;
    truck(s, { L: 9.0, W, cabL: 2.3, cabH: 2.9, r: 0.5, axles: [1.3, 7.4], cab: C.orange });
    const t = s.ab(0.2, 0, 1.0, 4.7, W, 1.65, C.white);
    s.dec(t, "y", W, [0.2, 1.4, 4.9, 1.6], C.orange, { flat: true });
    s.cyl([1.0, W / 2, 2.65], [1.0, W / 2, 3.0], 0.45, C.grey);
    s.cyl([1.0, W / 2, 2.95], [5.4, W / 2, 5.6], 0.14, C.orange);
    const bk = s.ab(5.2, W / 2 - 0.6, 5.0, 1.0, 1.2, 0.9, C.orange);
    s.glass(bk, "y", W / 2 + 0.6, [5.3, 5.4, 6.1, 5.8]);
  },
  GPU: (s) => {
    const L = 3.0, W = 1.6;
    cart(s, L, W, 0.28);
    const b = s.ab(0.15, 0.05, 0.5, L - 0.3, W - 0.1, 1.25, C.yellow);
    for (let i = 0; i < 7; i++) s.dec(b, "y", W - 0.05, [0.35 + i * 0.22, 0.75, 0.45 + i * 0.22, 1.45], C.dark);
    s.dec(b, "x", L - 0.15, [0.35, 1.0, 1.25, 1.55], C.dark);
    s.dec(b, "x", L - 0.15, [0.45, 1.3, 0.6, 1.42], "#34d399", { flat: true });
    s.dec(b, "x", L - 0.15, [0.7, 1.3, 0.85, 1.42], "#f87171", { flat: true });
    s.cyl([0.8, 0.3, 2.0], [0.8, W - 0.3, 2.0], 0.3, C.dark);
    s.line(null, [0.9, W - 0.3, 1.8], [1.6, W + 0.4, 0.9], C.black, 0.06);
  },
  TOW_BAR: (s) => {
    const W = 0.9;
    s.shadow(0, 0, 5, W);
    s.wheel([2.8, 0.06, 0.22], 0.22, 0.12);
    s.cyl([0.3, W / 2, 0.5], [4.7, W / 2, 0.5], 0.08, C.yellow);
    s.line(null, [2.8, 0.06, 0.22], [2.8, W - 0.06, 0.22], C.dark, 0.06);
    s.line(null, [2.8, W / 2, 0.25], [2.8, W / 2, 0.45], C.dark, 0.06);
    s.wheel([2.8, W - 0.06, 0.22], 0.22, 0.12);
    s.cyl([0.05, W / 2, 0.45], [0.05, W / 2, 0.55], 0.22, C.dark);
    s.ab(4.6, W / 2 - 0.2, 0.35, 0.45, 0.4, 0.3, C.dark);
  },
  AIRCRAFT_JACK: (s) => {
    const c: V3 = [0.8, 0.8, 0];
    s.shadow(0, 0, 1.6, 1.6);
    for (const a of [90, 210, 330]) {
      const f: V3 = [c[0] + 0.85 * Math.cos(rad(a)), c[1] + 0.85 * Math.sin(rad(a)), 0.05];
      s.cyl(f, [c[0], c[1], 0.9], 0.07, C.yellow);
      s.ab(f[0] - 0.12, f[1] - 0.12, 0, 0.24, 0.24, 0.08, C.dark);
    }
    s.cyl([c[0], c[1], 0.3], [c[0], c[1], 1.5], 0.2, C.yellow);
    s.cyl([c[0], c[1], 1.5], [c[0], c[1], 2.15], 0.12, C.steel);
    s.cyl([c[0], c[1], 2.15], [c[0], c[1], 2.25], 0.2, C.dark);
    s.line(null, [c[0] + 0.15, c[1] + 0.15, 0.7], [c[0] + 0.9, c[1] + 0.6, 1.1], C.dark, 0.05);
  },
  HYDRAULIC_RIG: (s) => {
    const L = 2.6, W = 1.4;
    cart(s, L, W, 0.25);
    const b = s.ab(0.1, 0.05, 0.45, L - 0.2, W - 0.1, 1.1, C.yellow);
    s.dec(b, "y", W - 0.05, [0.3, 0.9, 1.3, 1.4], C.dark);
    for (const x of [0.45, 0.8, 1.15]) { const it = b; s.disc(it, [x, W - 0.04, 1.15], [1, 0, 0], [0, 0, 1], 0.12, "#e5e7eb", true); }
    s.cyl([0.6, 0.25, 1.75], [0.6, W - 0.25, 1.75], 0.2, C.dark);
    s.cyl([1.5, 0.25, 1.75], [1.5, W - 0.25, 1.75], 0.2, C.red);
  },
  AIR_START_UNIT: (s) => {
    const L = 3.6, W = 1.8;
    cart(s, L, W, 0.3);
    const b = s.ab(0.1, 0.05, 0.5, L - 0.2, W - 0.1, 1.4, C.yellow);
    for (let i = 0; i < 6; i++) s.dec(b, "z", 1.9, [0.3 + i * 0.3, 0.3, 0.45 + i * 0.3, W - 0.3], C.dark);
    s.dec(b, "x", L - 0.1, [0.3, 1.2, 1.0, 1.7], C.dark);
    s.cyl([1.6, W - 0.05, 1.1], [1.7, W + 0.6, 0.95], 0.22, C.dark);
    s.cyl([1.7, W + 0.6, 0.95], [2.6, W + 1.1, 0.35], 0.22, C.dark);
  },
  WEAPON_LOADER: (s) => {
    const L = 3.6, W = 1.8;
    s.shadow(0, 0, L + 0.8, W);
    for (const x of [0.5, 2.9]) { s.wheel([x, 0.15, 0.26], 0.26, 0.2); s.wheel([x, W - 0.15, 0.26], 0.26, 0.2); }
    s.ab(0.2, 0.1, 0.3, 3.0, W - 0.2, 0.42, C.yellow);
    s.ab(0.35, 0.45, 0.72, 0.5, 0.7, 0.45, C.dark);
    s.line(null, [0.95, W / 2, 0.72], [0.95, W / 2, 1.25], C.dark, 0.06);
    s.cyl([1.1, W / 2, 0.8], [3.1, W / 2, 1.25], 0.13, C.yellow);
    s.ab(2.6, 0.45, 1.22, 1.3, 0.9, 0.12, C.grey);
    missile(s, [2.2, W / 2, 1.5], [4.1, W / 2, 1.5], 0.1);
    s.ab(2.25, W / 2 - 0.02, 1.5, 0.3, 0.04, 0.25, C.dark, 0.02);
  },
  AC_COOLING_CART: (s) => {
    const L = 3.0, W = 1.6;
    cart(s, L, W, 0.27);
    const b = s.ab(0.15, 0.05, 0.48, L - 0.3, W - 0.1, 1.2, "#c9d1d8");
    s.disc(b, [1.0, W / 2, 1.68], [1, 0, 0], [0, 1, 0], 0.48, C.dark, true);
    s.disc(b, [1.0, W / 2, 1.681], [1, 0, 0], [0, 1, 0], 0.16, C.grey, true);
    s.dec(b, "y", W - 0.05, [1.7, 0.75, 2.5, 1.45], C.grey);
    s.cyl([2.2, W - 0.05, 1.0], [2.4, W + 0.7, 0.6], 0.18, "#3d6f9e");
  },
  ENGINE_STAND: (s) => {
    const L = 4.2, W = 1.8;
    s.shadow(0, 0, L, W);
    for (const x of [0.25, L - 0.25]) { s.wheel([x, 0.15, 0.17], 0.17, 0.12); s.wheel([x, W - 0.15, 0.17], 0.17, 0.12); }
    s.ab(0.1, 0.1, 0.32, L - 0.2, 0.14, 0.14, C.yellow);
    s.ab(0.1, W - 0.24, 0.32, L - 0.2, 0.14, 0.14, C.yellow);
    for (const x of [0.9, 3.1]) s.ab(x, 0.1, 0.32, 0.14, W - 0.2, 0.14, C.yellow);
    for (const x of [1.0, 3.1]) { s.ab(x, 0.25, 0.46, 0.12, 0.12, 0.55, C.yellow); s.ab(x, W - 0.37, 0.46, 0.12, 0.12, 0.55, C.yellow); }
    const e = s.cyl([0.5, W / 2, 1.3], [3.8, W / 2, 1.3], 0.52, C.steel, { cap: C.dark });
    s.disc(e, [3.8, W / 2, 1.3], [0, 1, 0], [0, 0, 1], 0.2, C.grey, true);
    s.ab(1.6, W / 2 - 0.25, 0.62, 0.9, 0.5, 0.25, C.grey);
  },
  OXYGEN_CART: (s) => gasCart(s, C.black, C.white),
  NITROGEN_CART: (s) => gasCart(s, C.grey, C.black),
  // ---------------------------------------------------------------- air defence
  "S-400 Triumf (Sudarshan Chakra)": (s) => {
    const W = 3.1;
    truck(s, { L: 12, W, cabL: 2.8, cabH: 3.0, r: 0.6, axles: [1.6, 3.0, 8.0, 9.4], cab: C.olive });
    s.ab(0.2, 0.25, 1.15, 8.6, W - 0.5, 0.4, C.oliveDk);
    for (const z of [2.1, 3.05]) for (const y of [0.8, 2.3]) s.cyl([0.2, y, z], [8.7, y, z], 0.46, C.olive);
  },
  "MR-SAM (Barak-8)": (s) => {
    const W = 2.8;
    truck(s, { L: 10.5, W, cabL: 2.6, cabH: 3.0, r: 0.55, axles: [1.4, 2.8, 9.0], cab: C.olive });
    s.ab(0.1, 0, 1.05, 7.7, W, 0.3, C.oliveDk);
    for (const y of [0.1, W - 0.1]) s.line(null, [0.4, y, 1.1], [0.4, y, 0.05], C.dark, 0.1);
    const l = s.ab(0.2, 0.25, 1.35, 1.9, 2.3, 5.4, C.olive);
    for (let i = 0; i < 2; i++) for (let j = 0; j < 4; j++) s.disc(l, [0.65 + i * 1.0, 0.55 + j * 0.57, 6.75], [1, 0, 0], [0, 1, 0], 0.22, C.oliveDk);
    s.dec(l, "y", 2.55, [0.3, 2.0, 2.0, 2.15], C.oliveDk);
  },
  "Akash": (s) => {
    const L = 7.4, W = 3.3;
    s.shadow(0, 0, L, W);
    s.ab(0, 0, 0.05, L, 0.6, 0.95, C.dark);
    s.ab(0.3, 0.5, 0.45, L - 0.6, W - 1.0, 1.25, C.olive);
    const tr = s.ab(0, W - 0.6, 0.05, L, 0.6, 0.95, C.dark);
    for (let x = 0.7; x < L - 0.4; x += 1.0) s.disc(tr, [x, W, 0.45], [1, 0, 0], [0, 0, 1], 0.36, C.grey);
    s.cyl([3.4, W / 2, 1.7], [3.4, W / 2, 2.05], 0.95, C.oliveDk);
    s.box([1.4, 0.85, 2.0], [3.9, 0, 1.4], [0, W - 1.7, 0], [0, 0, 0.25], C.oliveDk);
    for (const y of [1.05, W / 2, W - 1.05]) missile(s, [1.1, y, 2.55], [5.4, y, 4.1], 0.19);
  },
  "Akash-NG": (s) => {
    const W = 2.6, t = rad(28);
    truck(s, { L: 9.6, W, cabL: 2.5, cabH: 2.9, r: 0.52, axles: [1.3, 2.6, 8.2], cab: C.olive });
    s.ab(0.1, 0, 1.0, 6.9, W, 0.3, C.oliveDk);
    const ex: V3 = [5.6 * Math.cos(t), 0, 5.6 * Math.sin(t)], ez: V3 = [-1.25 * Math.sin(t), 0, 1.25 * Math.cos(t)];
    const o: V3 = [0.6, 0.25, 1.4];
    const l = s.box(o, ex, [0, W - 0.5, 0], ez, C.olive);
    const u: V3 = [0, 1, 0], v = norm(ez);
    for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++)
      s.disc(l, [o[0] + ex[0] + ez[0] * (0.27 + j * 0.46) + 0.001, 0.6 + i * 0.7, o[2] + ex[2] + ez[2] * (0.27 + j * 0.46)], u, v, 0.2, C.oliveDk);
  },
  "SPYDER-SR": (s) => spyder(s),
  "SPYDER-MR": (s) => spyder(s),
  "S-125 Pechora (upgraded)": (s) => {
    const L = 6.5, W = 4.5;
    s.shadow(0, 0, L, W);
    s.wheel([2.2, 0.55, 0.42], 0.42, 0.3);
    s.ab(0.8, 0.6, 0.6, 4.6, W - 1.2, 0.4, C.oliveDk);
    for (const [x, y] of [[0.9, 0.2], [0.9, W - 0.2], [5.2, 0.2], [5.2, W - 0.2]] as [number, number][]) s.line(null, [x, W / 2, 0.7], [x, y, 0.05], C.dark, 0.1);
    s.wheel([2.2, W - 0.55, 0.42], 0.42, 0.3);
    s.cyl([3.1, W / 2, 1.0], [3.1, W / 2, 1.5], 0.85, C.olive);
    for (const [y, dz] of [[1.25, 0], [W - 1.25, 0], [1.25, 0.75], [W - 1.25, 0.75]] as [number, number][]) {
      s.cyl([0.6, y, 1.7 + dz], [2.3, y, 2.4 + dz], 0.27, C.green);
      missile(s, [2.3, y, 2.4 + dz], [5.6, y, 3.75 + dz], 0.18);
    }
  },
  "Igla-S": (s) => {
    s.shadow(0, 0, 1.8, 0.6);
    s.line(null, [0.6, 0.3, 0.05], [0.7, 0.3, 0.85], C.dark, 0.035);
    s.line(null, [0.6, 0.05, 0.05], [0.7, 0.3, 0.85], C.dark, 0.035);
    s.line(null, [0.6, 0.55, 0.05], [0.7, 0.3, 0.85], C.dark, 0.035);
    s.cyl([0, 0.3, 0.7], [1.7, 0.3, 1.05], 0.075, C.olive);
    s.ab(0.75, 0.32, 0.72, 0.12, 0.05, 0.22, C.dark, 0.01);
    s.ab(0.35, 0.35, 0.68, 0.22, 0.12, 0.14, C.oliveDk, 0.01);
    s.ab(0.9, 0.22, 0.98, 0.2, 0.08, 0.1, C.dark, 0.01);
  },
  "Counter-drone system (generic)": (s) => {
    const W = 2.4;
    truck(s, { L: 6.5, W, cabL: 2.1, cabH: 2.7, r: 0.46, axles: [1.1, 5.4], cab: C.olive });
    const sh = s.ab(0.2, 0, 1.0, 4.1, W, 1.8, C.olive);
    s.dec(sh, "y", W, [0.5, 1.3, 1.3, 2.5], C.oliveDk);
    s.cyl([1.6, W / 2, 2.8], [1.6, W / 2, 4.7], 0.09, C.grey);
    s.box([1.15, W / 2 - 0.05, 4.7], [0.9, 0, 0], [0, 0.12, 0.05], [0, -0.05, 0.65], C.oliveDk);
    for (const x of [2.6, 3.0, 3.4]) s.line(null, [x, 0.4, 2.8], [x, 0.4, 3.9], C.dark, 0.05);
    s.cyl([3.6, W - 0.5, 2.8], [3.6, W - 0.5, 3.1], 0.22, C.dark);
    s.cyl([3.6, W - 0.5, 3.1], [3.6, W - 0.5, 3.4], 0.2, C.grey);
  },
  "L/70 40 mm AD gun": (s) => {
    const W = 2.3;
    s.shadow(-0.2, -1.0, 7.3, W + 1.0);
    for (const x of [1.6, 5.4]) s.wheel([x, 0.2, 0.45], 0.45, 0.3);
    s.ab(2.7, -1.0, 0.12, 0.3, W + 2.0, 0.12, C.oliveDk);
    s.ab(1.0, 0.45, 0.55, 5.0, W - 0.9, 0.45, C.olive);
    s.cyl([3.6, W / 2, 1.0], [3.6, W / 2, 1.35], 0.75, C.oliveDk);
    const g = s.ab(2.7, 0.7, 1.35, 1.8, W - 1.4, 0.85, C.olive);
    s.dec(g, "y", W - 0.7, [2.9, 1.5, 3.6, 2.0], C.oliveDk);
    s.cyl([4.3, W / 2, 1.95], [7.4, W / 2, 3.45], 0.075, C.dark);
    s.cyl([7.25, W / 2, 3.38], [7.6, W / 2, 3.55], 0.11, C.dark);
    for (const x of [1.6, 5.4]) s.wheel([x, W - 0.2, 0.45], 0.45, 0.3);
  },
  "ZU-23-2 twin 23 mm": (s) => {
    const W = 2.9;
    s.shadow(0.2, 0, 5, W);
    s.wheel([2.0, 0.15, 0.45], 0.45, 0.25);
    s.ab(0.8, 0.6, 0.48, 2.7, W - 1.2, 0.22, C.olive);
    for (const [x, y] of [[0.6, 0.3], [0.6, W - 0.3], [3.8, 0.3], [3.8, W - 0.3]] as [number, number][]) s.line(null, [x < 2 ? 1.0 : 3.3, W / 2, 0.55], [x, y, 0.05], C.dark, 0.07);
    s.ab(1.6, 0.95, 0.7, 1.2, 1.0, 0.65, C.olive);
    for (const y of [1.2, 1.7]) s.cyl([2.3, y, 1.25], [5.0, y, 2.5], 0.05, C.dark);
    s.ab(2.0, 0.75, 1.3, 0.4, 0.25, 0.4, C.oliveDk, 0.01);
    s.ab(2.0, 1.9, 1.3, 0.4, 0.25, 0.4, C.oliveDk, 0.01);
    s.ab(1.0, 1.2, 1.0, 0.4, 0.5, 0.18, C.dark);
    s.wheel([2.0, W - 0.15, 0.45], 0.45, 0.25);
  },
  // ---------------------------------------------------------------- radars
  "Arudhra (MPR)": (s) => {
    const W = 3.0;
    truck(s, { L: 11, W, cabL: 2.6, cabH: 3.0, r: 0.55, axles: [1.4, 2.9, 9.4], cab: C.olive });
    s.ab(0.2, 0, 1.05, 7.8, W, 1.0, C.olive);
    s.cyl([3.8, 1.4, 2.05], [3.8, 1.4, 2.3], 0.7, C.oliveDk);
    array(s, 1.4, 1.2, 2.3, 4.8, 3.6, 15);
  },
  "THD-1955": (s) => {
    s.shadow(1.5, 1.5, 8.5, 7.5);
    s.ab(0.3, 0.3, 0, 3.2, 2.3, 2.4, C.sand);
    s.cyl([5, 4.5, 0], [5, 4.5, 2.2], 1.2, C.grey);
    s.cyl([5, 4.5, 2.2], [5, 4.5, 2.6], 0.6, C.dark);
    const a = rad(-35), wv: V3 = [Math.cos(a) * 9, Math.sin(a) * 9, 0], n: V3 = [-Math.sin(a), Math.cos(a), 0];
    const t = rad(14), up: V3 = [-n[0] * Math.sin(t), -n[1] * Math.sin(t), Math.cos(t)];
    const o: V3 = [5 - wv[0] / 2, 4.5 - wv[1] / 2, 2.6];
    const r = s.box(o, wv, mul(n, 0.35), mul(up, 2.6), C.white);
    for (let i = 1; i < 10; i++) {
      const p0: V3 = [o[0] + wv[0] * i / 10 + n[0] * 0.36, o[1] + wv[1] * i / 10 + n[1] * 0.36, o[2] + 0.1];
      s.line(r, p0, [p0[0] + up[0] * 2.4, p0[1] + up[1] * 2.4, p0[2] + up[2] * 2.4], "rgba(0,0,0,.18)", 0.04);
    }
  },
  "Aslesha (LLLR)": (s) => {
    const c: V3 = [1.3, 1.3, 0];
    s.shadow(0, 0, 2.6, 2.6);
    for (const a of [90, 210, 330]) s.cyl([c[0] + 1.2 * Math.cos(rad(a)), c[1] + 1.2 * Math.sin(rad(a)), 0], [c[0], c[1], 1.3], 0.035, C.dark);
    s.cyl([c[0], c[1], 1.2], [c[0], c[1], 1.55], 0.08, C.grey);
    array(s, c[0] - 0.65, c[1] - 0.1, 1.5, 1.3, 0.85, 10);
  },
  "Ashwini (LLTR)": (s) => {
    const W = 2.8;
    truck(s, { L: 10, W, cabL: 2.5, cabH: 3.0, r: 0.55, axles: [1.4, 2.8, 8.5], cab: C.olive });
    s.ab(0.2, 0, 1.05, 7.0, W, 1.1, C.olive);
    s.cyl([3.4, 1.3, 2.15], [3.4, 1.3, 2.45], 0.6, C.oliveDk);
    array(s, 1.6, 1.15, 2.45, 3.6, 2.6, 12);
  },
  "EL/M-2084": (s) => {
    const L = 9, W = 3.2;
    s.shadow(-0.8, 0, L, W);
    for (const x of [2.0, 3.2]) { s.wheel([x, 0.2, 0.48], 0.48, 0.35); s.wheel([x, W - 0.2, 0.48], 0.48, 0.35); }
    s.ab(0.2, 0.1, 0.9, L - 0.4, W - 0.2, 0.35, C.olive);
    s.line(null, [L - 0.2, W / 2, 1.0], [L + 0.7, W / 2, 0.5], C.dark, 0.1);
    s.ab(6.0, 0.25, 1.25, 2.4, W - 0.5, 1.3, C.oliveDk);
    s.cyl([3.4, 1.4, 1.25], [3.4, 1.4, 1.55], 0.75, C.oliveDk);
    array(s, 1.2, 1.25, 1.55, 4.4, 3.4, 18);
  },
  "Rohini (3D CAR)": (s) => {
    const W = 2.8;
    truck(s, { L: 9, W, cabL: 2.5, cabH: 3.0, r: 0.55, axles: [1.3, 2.6, 7.6], cab: C.olive });
    s.ab(0.2, 0, 1.05, 6.2, W, 1.6, C.olive);
    s.cyl([3.2, W / 2, 2.65], [3.2, W / 2, 3.3], 0.3, C.grey);
    const a = rad(-30), wv: V3 = [Math.cos(a) * 4.8, Math.sin(a) * 4.8, 0], n: V3 = [-Math.sin(a), Math.cos(a), 0];
    s.box([3.2 - wv[0] / 2, W / 2 - wv[1] / 2, 3.3], wv, mul(n, 0.3), [0, 0, 1.4], C.oliveDk);
  },
  "Aerostat EL/M-2083": (s) => {
    s.shadow(4, 2, 30, 9);
    s.ab(7, 3.6, 0, 7, 3.8, 1.4, C.olive);
    s.line(null, [10.5, 5.5, 1.4], [16, 5.5, 9], "#cbd5e1", 0.08);
    s.box([31, 5.3, 14], [-5, 0, 0], [0, 0.4, 0], [-1.5, 0, 6.5], C.white);
    for (const sg of [1, -1]) s.box([31, 5.5, 13.2], [-5, 0, 0], [0, 0, 0.35], [-1.2, sg * 5.5, -3.3], C.white);
    s.blob([17, 5.5, 14], [16, 0, 0], 5.6, C.white);
    s.ab(13.5, 4.6, 7.1, 3.5, 1.8, 1.4, C.grey);
  },
};

/** Equipment shelter (cabin on skids) with a door and an air-conditioner. */
function shelter(s: Scene, x: number, y: number, l: number, w: number, h: number, color = C.olive) {
  const it = s.ab(x, y, 0.15, l, w, h, color);
  s.ab(x + 0.2, y + 0.1, 0, 0.3, w - 0.2, 0.15, C.dark);
  s.ab(x + l - 0.5, y + 0.1, 0, 0.3, w - 0.2, 0.15, C.dark);
  s.dec(it, "y", y + w, [x + 0.4, 0.3, x + 1.2, h - 0.15], shade2(color));
  s.dec(it, "y", y + w, [x + l - 1.2, h - 0.9, x + l - 0.4, h - 0.35], C.grey);
  return it;
}
const shade2 = (c: string) => (c === C.olive ? C.oliveDk : C.grey);

function mast(s: Scene, x: number, y: number, h: number, guys = true) {
  s.cyl([x, y, 0], [x, y, h], 0.07, C.grey);
  if (guys) for (const [dx, dy] of [[1.6, 1.2], [-1.6, 1.2], [0, -1.8]]) s.line(null, [x, y, h * 0.8], [x + dx, y + dy, 0], "rgba(200,210,220,.5)", 0.025);
}

Object.assign(B, {
  DATALINK_GS: (s: Scene) => {
    s.shadow(0, 0, 6, 4);
    shelter(s, 0.3, 0.6, 4.0, 2.3, 2.3);
    mast(s, 5.2, 2.6, 6.5);
    s.box([4.75, 2.5, 6.0], [0.9, 0, 0], [0, 0.12, 0.05], [0, -0.04, 0.8], C.white);
    s.ab(4.6, 0.3, 0, 1.0, 0.9, 0.9, C.oliveDk);
  },
  VUHF_RELAY: (s: Scene) => {
    s.shadow(0, 0, 5, 4);
    shelter(s, 0.3, 0.5, 2.8, 2.0, 2.1);
    mast(s, 4.0, 2.3, 9);
    for (const z of [6.5, 7.6, 8.7]) s.line(null, [3.3, 2.3, z], [4.7, 2.3, z], C.white, 0.06);
    for (const z of [6.5, 7.6, 8.7]) for (const x of [3.3, 4.7]) s.line(null, [x, 2.3, z], [x, 2.3, z + 0.7], C.white, 0.04);
  },
  HF_STATION: (s: Scene) => {
    s.shadow(0, 0, 10, 4);
    shelter(s, 3.2, 1.6, 3.2, 2.2, 2.2);
    mast(s, 0.4, 1.0, 9, false);
    mast(s, 9.4, 1.0, 9, false);
    s.line(null, [0.4, 1.0, 8.8], [9.4, 1.0, 8.8], "#e5e7eb", 0.04);
    s.line(null, [4.9, 1.0, 8.8], [4.6, 2.2, 2.35], "#e5e7eb", 0.035);
  },
  SATCOM_GS: (s: Scene) => {
    s.shadow(0, 0, 6, 4.5);
    shelter(s, 0.2, 0.3, 3.2, 2.2, 2.2);
    s.ab(4.0, 1.6, 0, 1.2, 1.2, 0.5, C.grey);
    s.cyl([4.6, 2.2, 0.5], [4.6, 2.2, 1.9], 0.18, C.grey);
    const t = rad(35), u: V3 = [Math.sin(t), 0, Math.cos(t)];
    const it = s.cyl([4.6, 2.2, 2.4], [4.6 + u[0] * 0.35, 2.2, 2.4 + u[2] * 0.35], 1.5, C.white, { r2: 1.6 });
    s.disc(it, [4.6 + u[0] * 0.36, 2.2, 2.4 + u[2] * 0.36], [0, 1, 0], norm([Math.cos(t), 0, -Math.sin(t)]), 1.25, "#d7dde3");
    s.line(it, [4.6 + u[0] * 0.36, 2.2, 2.4 + u[2] * 0.36], [4.6 + u[0] * 1.5, 2.2, 2.4 + u[2] * 1.5], C.dark, 0.06);
  },
  C2_NODE: (s: Scene) => {
    s.shadow(0, 0, 8, 5);
    shelter(s, 0.3, 0.3, 3.6, 2.3, 2.3);
    shelter(s, 4.3, 0.3, 3.6, 2.3, 2.3);
    s.ab(3.9, 0.8, 0.15, 0.4, 1.3, 2.0, C.canvas);
    mast(s, 2.0, 3.6, 7.5);
    for (const x of [5.2, 6.0, 6.8]) s.line(null, [x, 1.0, 2.45], [x, 1.0, 3.6], C.dark, 0.04);
  },
  NETWORK_HUB: (s: Scene) => {
    s.shadow(0, 0, 7, 4.5);
    const it = shelter(s, 0.3, 0.4, 5.0, 2.5, 2.6, C.iafLt);
    for (const x of [1.6, 2.2, 2.8]) s.dec(it, "y", 2.9, [x, 0.6, x + 0.45, 2.1], C.dark);
    mast(s, 6.2, 2.4, 7);
    s.box([5.8, 2.3, 6.3], [0.8, 0, 0], [0, 0.1, 0.04], [0, -0.04, 0.7], C.white);
    s.line(null, [5.3, 1.5, 2.2], [6.2, 2.4, 1.0], C.dark, 0.05);
  },
});

function gasCart(s: Scene, body: string, top: string) {
  const L = 2.6, W = 1.4;
  cart(s, L, W, 0.22);
  s.ab(0.1, 0.05, 0.35, L - 0.2, W - 0.1, 0.12, C.yellow);
  for (const x of [0.5, 1.3, 2.1]) for (const y of [0.4, 1.0]) {
    s.cyl([x, y, 0.47], [x, y, 1.65], 0.21, body);
    s.cyl([x, y, 1.65], [x, y, 1.85], 0.21, top, { r2: 0.1 });
  }
  s.line(null, [0.2, W - 0.1, 0.47], [0.2, W - 0.1, 1.5], C.yellow, 0.06);
  s.line(null, [2.4, W - 0.1, 0.47], [2.4, W - 0.1, 1.5], C.yellow, 0.06);
  s.line(null, [0.2, W - 0.1, 1.5], [2.4, W - 0.1, 1.5], C.yellow, 0.06);
}

function spyder(s: Scene) {
  const W = 2.6;
  truck(s, { L: 9.2, W, cabL: 2.5, cabH: 2.9, r: 0.52, axles: [1.3, 2.6, 7.8], cab: C.olive });
  s.ab(0.1, 0, 1.0, 6.5, W, 0.3, C.oliveDk);
  s.box([1.0, 0.3, 1.3], [3.6, 0, 1.6], [0, W - 0.6, 0], [0, 0, 0.3], C.olive);
  for (const y of [0.6, 1.1, 1.55, 2.0]) s.cyl([0.6, y, 1.85], [5.6, y, 4.05], 0.21, C.olive);
}

const cache = new Map<string, JSX.Element>();
/** 3D-style picture for an equipment type key (ground asset type, AD system or radar name). */
export function equipmentSvg(type: string): JSX.Element | null {
  if (!B[type]) return null;
  if (!cache.has(type)) {
    const s = new Scene(`eq${type.replace(/[^a-z0-9]/gi, "")}-`);
    B[type](s);
    cache.set(type, s.render(type));
  }
  return cache.get(type)!;
}
