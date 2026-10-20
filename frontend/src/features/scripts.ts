// Scripted demo Planner (ARCHITECTURE D66). One fixed script per scenario: what happened, the missions it affects and
// the planner's recommendation for each, with two other options. The Planner pages and the Ops map both read these, so
// they always agree. Nothing here writes sorties; approval is a browser-side demo state. Every object is simulated.
// Targets are generator-placed mission points (inside India, clear of the border buffer, I8/I15); see scripts.test.ts.
import type { Intensity, LiveScenario, ParamValue, Priority } from "../api/types";

export type Kind = "added" | "moved" | "not flown";
/** What a mission does, shown as its map icon (D82). */
export type MissionType = "rescue" | "casevac" | "cap" | "isr" | "aew" | "strike" | "training" | "airlift" | "supply" | "relief";
export const MISSION_WORD: Record<MissionType, string> = { rescue: "Rescue", casevac: "Casualty evacuation", cap: "Combat air patrol",
  isr: "Surveillance", aew: "Airborne early warning", strike: "Strike", training: "Training", airlift: "Airlift", supply: "Supply drop", relief: "Flood relief" };
export interface Pkg {
  n: number; type: string; base: string;   // base code, see BASES
  free: number; crews: number;             // aircraft free and rested, qualified crews at that base
  lead: number; hours: number;             // launch this many minutes after approval; sortie length
  why: string[];                           // the recommendation's reasons, short
}
export interface Option { pkg: Pkg; tradeoff: string }
export interface ScriptMission {
  id: string; kind: Kind; mtype: MissionType; priority: Priority; name: string;
  reason: string;                          // why the situation affects it
  target: [number, number];                // lon, lat
  pkg: Pkg | null;                         // null: the planner can't fly it as asked
  options: Option[];
}
export interface Script {
  code: string; name: string; category: string; intensity: Intensity; summary: string; lead: string;
  params: Record<string, ParamValue>; facts: [string, string][];
  happened: { what: string; ends: number | null }[];      // ends: minutes after the event
  missions: ScriptMission[];
}

/** Bases the scripts use: name, lon, lat (public locations, `base` table). Free aircraft counts in the scripts follow the
 * seeded inventory (serviceable at that base, 2026-10-20). */
export const BASES: Record<string, [string, number, number]> = {
  VIAM: ["Ambala", 76.817, 30.368], VIBT: ["Bathinda", 74.756, 30.27], VIHX: ["Halwara", 75.63, 30.749], VISA: ["Sirsa", 75.006, 29.561],
  VIAX: ["Adampur", 75.759, 31.434], VOHK: ["Hakimpet", 78.525, 17.553], VOBR: ["Bidar", 77.487, 17.908], VILH: ["Leh", 77.547, 34.136],
  VI57: ["Thoise", 77.376, 34.653], VETZ: ["Tezpur", 92.785, 26.709], VECA: ["Chabua", 95.118, 27.462], VEJT: ["Jorhat", 94.175, 26.73],
  VEMN: ["Mohanbari", 95.017, 27.484], VIJO: ["Jodhpur", 73.049, 26.251], VIGR: ["Gwalior", 78.228, 26.293],
  VEDX: ["Kalaikunda", 87.215, 22.34], VIDX: ["Hindon", 77.359, 28.708],
};
export const baseName = (code: string) => BASES[code]?.[0] ?? code;

const p = (n: number, type: string, base: string, free: number, crews: number, lead: number, hours: number, ...why: string[]): Pkg =>
  ({ n, type, base, free, crews, lead, hours, why });
const o = (pkg: Pkg, tradeoff: string): Option => ({ pkg, tradeoff });

export const SCRIPTS: Script[] = [
  {
    code: "trainer-crash", name: "Trainer jet crash at Bidar", category: "Accident", intensity: "LOW",
    summary: "1 Hawk lost, runway closed 4 h",
    lead: "A Hawk crashed on the runway at Bidar just after take-off. The pilot ejected and came down in fields 7 km south-east of the base; the runway is shut while the wreck is cleared.",
    params: { base: "VOBR", type: "Hawk 132", hours: 4, lost: 1 },
    facts: [["Base", "Bidar (VOBR)"], ["Aircraft lost", "1 Hawk 132"], ["Runway closed for", "4 h"]],
    happened: [{ what: "Hawk 132 crashed on the Bidar runway; pilot ejected", ends: null }, { what: "Bidar runway closed for wreck clearance", ends: 240 },
      { what: "1 Hawk written off; Bidar has 37 Hawks ready", ends: null }],
    missions: [
      { id: "tc-1", kind: "added", mtype: "rescue", priority: "P1", name: "Pick up the ejected pilot near Bidar", reason: "He came down 7 km south-east of the runway, in open fields",
        target: [77.535, 17.862], pkg: p(1, "Ambulance", "VOBR", 2, 2, 5, 1, "7 km by road from Bidar's crash bay", "Medical officer and crash crew already on standby", "Reaches him in about 15 minutes"),
        options: [o(p(1, "Cheetah/Chetak", "VOHK", 15, 9, 20, 1.5, "Hakimpet helicopter lifts him straight to hospital"), "Hakimpet is 110 km away: about 45 min later"),
          o(p(1, "Crash fire tender", "VOBR", 4, 4, 5, 1, "Paramedic rides the fire tender"), "No stretcher bay: slower to hospital")] },
      { id: "tc-2", kind: "moved", mtype: "training", priority: "P4", name: "Hawk training wave 2, Bidar", reason: "Runway closed: it can't launch at its planned time",
        target: [77.77, 18.512], pkg: p(2, "Hawk 132", "VOBR", 37, 16, 250, 1.5, "Flies once the runway reopens", "Same crews, same training area", "No other base needed"),
        options: [o(p(2, "Kiran", "VOHK", 27, 10, 60, 1.5, "Hakimpet Kirans fly the slot"), "Basic syllabus, not the Hawk lesson"),
          o(p(2, "Hawk 132", "VOBR", 37, 16, 1440, 1.5, "Tomorrow morning slot"), "A day later")] },
      { id: "tc-3", kind: "moved", mtype: "training", priority: "P4", name: "Hawk training wave 3, Bidar", reason: "Runway closed: it can't launch at its planned time",
        target: [77.77, 18.512], pkg: p(2, "Hawk 132", "VOBR", 35, 14, 340, 1.5, "Moves behind wave 2", "Crews rested by then", "Runway open with margin"),
        options: [o(p(2, "Hawk 132", "VOBR", 35, 14, 1440, 1.5, "Tomorrow morning slot"), "A day later"),
          o(p(2, "Kiran", "VOHK", 27, 10, 120, 1.5, "Hakimpet Kirans fly the slot"), "Basic syllabus, not the Hawk lesson")] },
    ],
  },
  {
    code: "runway-closure", name: "Runway closure at Halwara", category: "Infrastructure", intensity: "MEDIUM",
    summary: "Runway closed 6 h",
    lead: "Halwara's runway surface failed during the afternoon launch window. Nothing can launch or land there for 6 hours.",
    params: { base: "VIHX", hours: 6 }, facts: [["Base", "Halwara (VIHX)"], ["Runway closed for", "6 h"]],
    happened: [{ what: "Halwara runway surface failed", ends: 360 }, { what: "40 Su-30MKI held on the ground at Halwara", ends: 360 },
      { what: "Repair crews on the runway", ends: 360 }],
    missions: [
      { id: "rc-1", kind: "moved", mtype: "cap", priority: "P2", name: "Combat air patrol near Jalandhar", reason: "Was 2 × Su-30MKI from Halwara",
        target: [75.638, 31.195], pkg: p(2, "Su-30MKI", "VISA", 15, 9, 25, 3, "Sirsa has 15 Su-30MKI and 9 rested crews", "26 min to the patrol line", "Fuel at Sirsa stays above reserve"),
        options: [o(p(2, "MiG-29", "VIAX", 41, 18, 20, 2.5, "Adampur is 15 km from the patrol line"), "Shorter endurance: 30 min less on station"),
          o(p(2, "Rafale", "VIAM", 14, 9, 25, 3, "Ambala Rafales"), "Uses Ambala's quick-reaction reserve")] },
      { id: "rc-2", kind: "moved", mtype: "isr", priority: "P2", name: "ISR coverage near Jalandhar", reason: "Was 1 × Su-30MKI with a recce pod from Halwara",
        target: [75.196, 31.311], pkg: p(1, "Heron Mk II", "VIBT", 6, 6, 30, 5, "Bathinda has 6 Herons free", "Stays on station 3 h longer", "No crew rest limit"),
        options: [o(p(1, "Su-30MKI", "VISA", 15, 9, 30, 2, "Sirsa Su-30 with a recce pod"), "Shorter look: 1 h on station"),
          o(p(1, "Heron Mk II", "VIBT", 6, 6, 90, 5, "Later slot"), "1 h gap in coverage")] },
      { id: "rc-3", kind: "moved", mtype: "strike", priority: "P3", name: "Strike exercise near Jalandhar", reason: "Was 4 × Su-30MKI from Halwara",
        target: [76.576, 31.838], pkg: p(4, "Su-30MKI", "VIHX", 28, 14, 380, 2, "Flies from Halwara after the runway reopens", "Same squadron, same range slot", "No other base loaded"),
        options: [o(p(4, "Su-30MKI", "VISA", 15, 9, 60, 2, "Sirsa flies it now"), "Takes 4 of Sirsa's 15 free jets"),
          o(p(4, "Jaguar", "VIAM", 32, 14, 60, 2, "Ambala Jaguars"), "Different weapons profile")] },
    ],
  },
  {
    code: "avalanche", name: "Avalanche casualty in Ladakh", category: "Urgent tasking", intensity: "MEDIUM",
    summary: "Urgent P1 casualty evacuation",
    lead: "An avalanche hit a high post 30 km east of Thoise. Three casualties must reach hospital within 3 hours, and the post needs supplies.",
    params: { base: "VI57", casualties: 3, window_h: 3, required: 1 },
    facts: [["Nearest base", "Thoise (VI57)"], ["Casualties", "3"], ["Must reach hospital within", "3 h"]],
    happened: [{ what: "Avalanche at a high post 30 km east of Thoise", ends: null }, { what: "3 casualties need hospital", ends: 180 },
      { what: "Post cut off: food and shelter needed", ends: 360 }],
    missions: [
      { id: "av-1", kind: "added", mtype: "casevac", priority: "P1", name: "Casualty evacuation from the high post", reason: "3 casualties, hospital within 3 h",
        target: [77.66, 34.517], pkg: p(1, "Cheetah/Chetak", "VILH", 24, 11, 15, 2, "Leh has 24 Cheetahs, rated for high-altitude landing", "35 min to the post", "Back at Leh hospital inside the 3 h limit"),
        options: [o(p(1, "Cheetah/Chetak", "VI57", 4, 2, 10, 1.5, "Thoise is closest"), "Thoise has only 2 crews: leaves no standby"),
          o(p(1, "Mi-17V-5", "VILH", 11, 4, 25, 2, "Takes all 3 at once"), "Heavier: limited payload at that altitude")] },
      { id: "av-2", kind: "added", mtype: "supply", priority: "P2", name: "Supply drop to the avalanche post", reason: "Post cut off: food, fuel and shelter",
        target: [77.66, 34.517], pkg: p(1, "Mi-17V-5", "VILH", 11, 4, 40, 2.5, "Leh has 11 Mi-17V-5 free", "About 1 t per lift at that altitude", "Weather holds until evening"),
        options: [o(p(1, "Mi-17V-5", "VIDX", 15, 8, 300, 5, "Hindon Mi-17s, staging through Leh"), "5 h later"),
          o(p(2, "Cheetah/Chetak", "VILH", 24, 11, 40, 2.5, "Two light loads"), "Less than half the load")] },
    ],
  },
  {
    code: "monsoon-front", name: "Eastern monsoon front", category: "Weather", intensity: "MEDIUM",
    summary: "Assam bases below flying minima 8 h",
    lead: "Low cloud and heavy rain over Assam. Tezpur, Jorhat, Chabua and Mohanbari are below flying minima for 8 hours, and villages near Jorhat are flooding. Mohanbari gets a short break in the weather in about 2 hours.",
    params: { bases: ["VETZ", "VEJT", "VECA", "VEMN"], cat: "IFR", hours: 8 },
    facts: [["Bases", "Tezpur, Jorhat, Chabua, Mohanbari"], ["Conditions", "IFR (below minima)"], ["Lasts", "8 h"]],
    happened: [{ what: "Tezpur, Jorhat, Chabua, Mohanbari below flying minima", ends: 480 }, { what: "Heavy rain: villages south-west of Jorhat flooding", ends: null },
      { what: "Forecast: a 2 h break over Mohanbari", ends: 240 }],
    missions: [
      { id: "mf-1", kind: "added", mtype: "relief", priority: "P2", name: "Flood relief near Jorhat", reason: "Villages flooding south-west of Jorhat",
        target: [93.9, 26.5], pkg: p(2, "Mi-17V-5", "VEMN", 27, 14, 120, 2, "Flies in Mohanbari's 2 h weather break", "27 Mi-17V-5 free, winch crews rested", "Back before the cloud closes in"),
        options: [o(p(2, "Mi-17V-5", "VEMN", 27, 14, 480, 3, "Mohanbari, after the front"), "8 h later"),
          o(p(1, "An-32", "VEJT", 22, 12, 120, 2, "Air-drop from Jorhat in the same break"), "No winching: supplies only")] },
      { id: "mf-2", kind: "moved", mtype: "cap", priority: "P2", name: "Combat air patrol near Pasighat", reason: "Was 2 × Su-30MKI from Tezpur",
        target: [95.244, 28.264], pkg: p(2, "Su-30MKI", "VECA", 14, 6, 130, 3, "Chabua launches in the Mohanbari weather break", "14 Su-30MKI and 6 rested crews free", "20 min to the patrol line"),
        options: [o(p(2, "Su-30MKI", "VETZ", 27, 12, 490, 3, "Tezpur after the front"), "6 h gap in the patrol"),
          o(p(2, "Su-30MKI", "VECA", 14, 6, 490, 3, "Chabua after the front"), "6 h gap in the patrol")] },
      { id: "mf-3", kind: "moved", mtype: "airlift", priority: "P3", name: "Airlift to Tezpur", reason: "Was 1 × An-32 from Jorhat",
        target: [92.785, 26.709], pkg: p(1, "An-32", "VEJT", 22, 12, 500, 2, "Flies once Jorhat clears", "Cargo can wait 8 h", "Same crew"),
        options: [o(p(1, "Mi-17V-5", "VEMN", 27, 14, 120, 2, "Mohanbari in the weather break"), "A third of the cargo"),
          o(p(1, "An-32", "VEJT", 22, 12, 1440, 2, "Tomorrow"), "A day later")] },
    ],
  },
  {
    code: "fuel-disruption", name: "Fuel supply disruption", category: "Logistics", intensity: "MEDIUM",
    summary: "Western bases lose most of their usable fuel",
    lead: "A contaminated batch of fuel is quarantined and convoys are held. Halwara, Adampur and Sirsa lose 80% of their usable ATF until the next delivery in 24 hours.",
    params: { bases: ["VIHX", "VIAX", "VISA"], loss_pct: 80, hours: 24 },
    facts: [["Bases", "Halwara, Adampur, Sirsa"], ["Usable fuel lost", "80%"], ["Next delivery in", "24 h"]],
    happened: [{ what: "ATF batch quarantined at Halwara, Adampur and Sirsa", ends: 1440 }, { what: "Usable fuel there down 80%", ends: 1440 },
      { what: "Convoys held until the batch is cleared", ends: 1440 }],
    missions: [
      { id: "fd-1", kind: "moved", mtype: "cap", priority: "P2", name: "Combat air patrol near Jalandhar", reason: "Was 2 × Su-30MKI from Halwara: not enough fuel there",
        target: [75.239, 30.941], pkg: p(2, "Rafale", "VIAM", 14, 9, 25, 3, "Ambala's fuel is unaffected", "14 Rafale and 9 rested crews free", "30 min to the patrol line"),
        options: [o(p(2, "Su-30MKI", "VISA", 15, 9, 25, 3, "Sirsa's remaining fuel"), "Leaves Sirsa below its reserve"),
          o(p(2, "Jaguar", "VIAM", 32, 14, 25, 2, "Ambala Jaguars"), "Shorter time on station")] },
      { id: "fd-2", kind: "moved", mtype: "isr", priority: "P2", name: "ISR coverage near Jalandhar", reason: "Was 1 × Su-30MKI with a recce pod from Halwara",
        target: [75.196, 31.311], pkg: p(1, "Heron Mk II", "VIBT", 6, 6, 30, 5, "Bathinda has fuel and 6 Herons", "Burns a tenth of a fighter's fuel", "5 h on station"),
        options: [o(p(1, "Su-30MKI", "VISA", 15, 9, 30, 2, "Sirsa Su-30 with a recce pod"), "Uses Sirsa's scarce fuel: 1 h look"),
          o(p(1, "Heron Mk II", "VIBT", 6, 6, 120, 5, "Later slot"), "1.5 h gap in coverage")] },
      { id: "fd-3", kind: "not flown", mtype: "strike", priority: "P3", name: "Strike exercise near Jalandhar", reason: "Was 4 × MiG-29 from Adampur: fuel kept for operational sorties",
        target: [76.576, 31.838], pkg: null,
        options: [o(p(4, "Jaguar", "VIAM", 32, 14, 60, 2, "Ambala Jaguars fly it"), "Uses 18 kL of Ambala's fuel"),
          o(p(4, "MiG-29", "VIAX", 41, 18, 1500, 2, "After the delivery"), "A day later")] },
    ],
  },
  {
    code: "fleet-grounding", name: "Su-30MKI fleet grounding", category: "Equipment", intensity: "HIGH",
    summary: "One batch grounded 48 h at 3 bases",
    lead: "A defect was found in one production batch of Su-30MKI. Aircraft from that batch at Halwara, Sirsa and Tezpur are grounded for inspection for 48 hours.",
    params: { type: "Su-30MKI", bases: ["VIHX", "VISA", "VETZ"], hours: 48 },
    facts: [["Aircraft type", "Su-30MKI"], ["Bases", "Halwara, Sirsa, Tezpur"], ["Grounded for", "48 h"]],
    happened: [{ what: "Su-30MKI grounded at Halwara, Sirsa and Tezpur", ends: 2880 }, { what: "100 aircraft out of the plan", ends: 2880 },
      { what: "Inspection teams on the line", ends: 2880 }],
    missions: [
      { id: "fg-1", kind: "moved", mtype: "cap", priority: "P2", name: "Combat air patrol near Jalandhar", reason: "Was 2 × Su-30MKI from Halwara",
        target: [75.638, 31.195], pkg: p(2, "Rafale", "VIAM", 14, 9, 25, 3, "Ambala Rafales are not affected", "14 free, 9 rested crews", "28 min to the patrol line"),
        options: [o(p(2, "MiG-29", "VIAX", 41, 18, 20, 2.5, "Adampur MiG-29s"), "30 min less on station"),
          o(p(2, "Jaguar", "VIAM", 32, 14, 25, 2, "Ambala Jaguars"), "Built for strike: weaker air-to-air radar")] },
      { id: "fg-2", kind: "moved", mtype: "cap", priority: "P2", name: "Combat air patrol near Bikaner", reason: "Was 2 × Su-30MKI from Sirsa",
        target: [73.341, 28.34], pkg: p(2, "Su-30MKI", "VIJO", 15, 9, 25, 3, "Jodhpur's Su-30s are from another batch", "25 min to the patrol line", "15 free; Jodhpur's QRA pair untouched"),
        options: [o(p(2, "MiG-29", "VIAX", 41, 18, 30, 2.5, "Adampur MiG-29s"), "45 min to the patrol line, less time on station"),
          o(p(2, "Rafale", "VIAM", 14, 9, 30, 3, "Ambala Rafales"), "A second Rafale pair today")] },
      { id: "fg-3", kind: "moved", mtype: "cap", priority: "P2", name: "Combat air patrol near Pasighat", reason: "Was 2 × Su-30MKI from Tezpur",
        target: [95.244, 28.264], pkg: p(2, "Su-30MKI", "VECA", 14, 6, 30, 3, "Chabua's Su-30s are from another batch", "14 free, 6 rested crews", "20 min to the patrol line"),
        options: [o(p(2, "Su-30MKI", "VECA", 14, 6, 120, 3, "Chabua, a later slot"), "1.5 h gap in the patrol"),
          o(p(2, "Su-30MKI", "VETZ", 27, 12, 2900, 3, "Tezpur after the inspection"), "Two days later")] },
      { id: "fg-4", kind: "not flown", mtype: "strike", priority: "P3", name: "Strike exercise near Jalandhar", reason: "Was 4 × Su-30MKI from Halwara",
        target: [76.576, 31.838], pkg: null,
        options: [o(p(4, "Jaguar", "VIAM", 32, 14, 60, 2, "Ambala Jaguars"), "Ties up Ambala's strike reserve"),
          o(p(4, "Su-30MKI", "VIHX", 28, 14, 2900, 2, "After the inspection"), "Two days later")] },
    ],
  },
  {
    code: "radar-outage", name: "Radar network outage", category: "Surveillance", intensity: "HIGH",
    summary: "Bathinda radars offline",
    lead: "The radars at Bathinda went offline, opening a gap in the air picture over Punjab for 6 hours. Airborne early warning and a patrol fill it.",
    params: { base: "VIBT", hours: 6, window_h: 6 }, facts: [["Base", "Bathinda (VIBT)"], ["Offline for", "6 h"]],
    happened: [{ what: "Bathinda radars offline", ends: 360 }, { what: "Gap in low-level coverage over Punjab", ends: 360 },
      { what: "Repair team dispatched", ends: 360 }],
    missions: [
      { id: "ro-1", kind: "added", mtype: "aew", priority: "P1", name: "AEW&C orbit over the radar gap", reason: "Covers the gap until the radars are back",
        target: [75.3, 30.1], pkg: p(1, "Netra EMB-145I", "VIBT", 3, 5, 25, 6, "Bathinda's Netras are not affected", "On orbit in 25 min", "Covers the whole gap"),
        options: [o(p(1, "Netra EMB-145I", "VIBT", 3, 5, 90, 6, "Second crew"), "1 h later"),
          o(p(2, "Heron Mk II", "VIBT", 6, 6, 30, 6, "Two Herons"), "No airborne radar: optical only")] },
      { id: "ro-2", kind: "added", mtype: "cap", priority: "P2", name: "Combat air patrol in the radar gap", reason: "Intercept cover while the gap is open",
        target: [75.1, 30.55], pkg: p(2, "Rafale", "VIAM", 14, 9, 25, 3, "Ambala has 14 Rafale free", "24 min to the patrol line", "Works with the Netra's picture"),
        options: [o(p(2, "MiG-29", "VIAX", 41, 18, 20, 2.5, "Adampur MiG-29s"), "30 min less on station"),
          o(p(2, "Su-30MKI", "VIHX", 28, 14, 25, 3, "Halwara Su-30s"), "Uses Halwara's QRA pair")] },
    ],
  },
  {
    code: "air-attack", name: "Western sector air attack", category: "Hostile action", intensity: "SEVERE",
    summary: "Forward base hit: runway and radar out",
    lead: "Unknown aircraft struck Adampur. The runway is cratered for 24 hours, two radars are down, fuel is damaged and a threat zone covers the sector.",
    params: { base: "VIAX", hours: 24, fuel_loss_pct: 30 },
    facts: [["Base hit", "Adampur (VIAX)"], ["Runway out for", "24 h"], ["Fuel lost", "30%"]],
    happened: [{ what: "Adampur runway cratered", ends: 1440 }, { what: "2 radars offline at Adampur", ends: 1440 },
      { what: "Adampur fuel down 30%", ends: 1440 }, { what: "Threat zone over the western sector", ends: 360 }],
    missions: [
      { id: "aa-1", kind: "added", mtype: "cap", priority: "P1", name: "Combat air patrol over the western sector", reason: "Defend the sector after the strike",
        target: [75.496, 31.434], pkg: p(2, "Rafale", "VIAM", 14, 9, 20, 3, "Ambala has 14 Rafale and 9 rested crews free", "22 min to the patrol line", "Fuel at Ambala stays above reserve"),
        options: [o(p(2, "Su-30MKI", "VIHX", 28, 14, 20, 3, "Halwara Su-30s"), "Closer, but Halwara is in the threat zone"),
          o(p(2, "Mirage 2000", "VIGR", 33, 16, 30, 3, "Gwalior Mirages"), "70 min to the patrol line")] },
      { id: "aa-2", kind: "added", mtype: "aew", priority: "P2", name: "AEW&C orbit over the western sector", reason: "Replaces the two radars lost at Adampur",
        target: [76.131, 31.114], pkg: p(1, "Netra EMB-145I", "VIBT", 3, 5, 25, 4.5, "Bathinda has 3 Netras free", "On orbit in 24 min", "Clear of the threat zone"),
        options: [o(p(1, "Netra EMB-145I", "VIBT", 3, 5, 90, 4.5, "Second crew"), "1 h later"),
          o(p(2, "Heron Mk II", "VIBT", 6, 6, 30, 5, "Two Herons"), "No airborne radar")] },
      { id: "aa-3", kind: "added", mtype: "isr", priority: "P2", name: "ISR coverage over Adampur", reason: "Damage assessment of the base",
        target: [75.759, 31.434], pkg: p(1, "Heron Mk II", "VIBT", 6, 6, 30, 4, "Bathinda has 6 Herons free", "Stays 3 h over the base", "Unmanned: no crew risk in the threat zone"),
        options: [o(p(1, "Su-30MKI", "VIHX", 28, 14, 20, 1.5, "Halwara Su-30 with a recce pod"), "Crewed aircraft into the threat zone"),
          o(p(1, "Heron Mk II", "VIBT", 6, 6, 90, 4, "Later slot"), "1 h later")] },
      { id: "aa-4", kind: "moved", mtype: "cap", priority: "P2", name: "Combat air patrol near Jalandhar", reason: "Was 2 × MiG-29 from Adampur: runway out",
        target: [75.239, 30.941], pkg: p(2, "Su-30MKI", "VIHX", 28, 14, 45, 3, "Halwara has 28 Su-30MKI free", "15 min to the patrol line", "Keeps the routine patrol"),
        options: [o(p(2, "Rafale", "VIAM", 14, 9, 45, 3, "Ambala's second Rafale pair"), "Leaves Ambala no Rafale reserve"),
          o(p(2, "Su-30MKI", "VISA", 15, 9, 45, 3, "Sirsa Su-30s"), "35 min to the patrol line")] },
    ],
  },
];

/** Routine tasking, shown beside every scenario: the day's requests the planner flies another way. */
export const ROUTINE: Script = {
  code: "routine", name: "Routine tasking", category: "Daily tasking", intensity: "LOW", summary: "56 missions today",
  lead: "Daily patrols, training, airlift and ISR. 53 of today's 56 missions fly as usual; the planner flies the other 3 another way, for your call.",
  params: {}, facts: [],
  happened: [{ what: "56 missions requested for today", ends: null }, { what: "53 planned on their usual bases", ends: null },
    { what: "3 can't fly from their usual base", ends: null }],
  missions: [
    { id: "rt-1", kind: "moved", mtype: "training", priority: "P3", name: "Mountain flying training near Srinagar", reason: "No fighters free at the usual base",
      target: [76.139, 33.581], pkg: p(2, "Su-30MKI", "VIHX", 28, 14, 60, 2, "Halwara is 400 km away: 40 min each way", "Enough fuel for 40 min in the area, no tanker", "Training slot kept"),
      options: [o(p(2, "MiG-29", "VIAX", 41, 18, 90, 1.5, "Adampur MiG-29s"), "20 min less in the area"),
        o(p(2, "Su-30MKI", "VIHX", 28, 14, 1440, 2, "Tomorrow"), "A day later")] },
    { id: "rt-2", kind: "moved", mtype: "training", priority: "P3", name: "Training near Bareilly", reason: "No crews rested in time at the usual base",
      target: [79.106, 28.087], pkg: p(2, "Mirage 2000", "VIGR", 33, 16, 60, 2, "Gwalior has 33 Mirages and 16 rested crews", "40 min transit each way", "Same training area"),
      options: [o(p(2, "Jaguar", "VIAM", 32, 14, 90, 2, "Ambala Jaguars"), "1.5 h later"),
        o(p(2, "Mirage 2000", "VIGR", 33, 16, 1440, 2, "Tomorrow"), "A day later")] },
    { id: "rt-3", kind: "moved", mtype: "airlift", priority: "P3", name: "Airlift to Uttarlai", reason: "No transport crew rested in time at the usual base",
      target: [71.482, 25.813], pkg: p(1, "C-130J-30", "VIDX", 6, 4, 120, 4, "Hindon has 6 C-130J and a rested crew", "Carries the whole load", "Lands before dark"),
      options: [o(p(1, "C-17A", "VIDX", 4, 3, 90, 4, "Hindon C-17"), "Far bigger than the load needs"),
        o(p(1, "C-130J-30", "VIDX", 6, 4, 1440, 4, "Tomorrow"), "A day later")] },
  ],
};

export const scriptFor = (code: string | null | undefined) => (code === "routine" ? ROUTINE : SCRIPTS.find((s) => s.code === code));

// ---------------------------------------------------------------- decisions, times, status, map
export type Decision = "keep" | "accept" | number;          // number: index into the mission's options
export interface DemoRun { started: string; dec: Record<string, Decision>; approvedAt: string | null }

/** Routine tasking's "start" is the IST day, so its decisions reset each simulated day. */
export const routineStart = (now: string) => `${new Date(Date.parse(now) + 5.5 * 3600e3).toISOString().slice(0, 10)}T00:00:00+05:30`;
/** A saved record belongs to this run only if it was made for the same start (run ids restart after a reseed). */
export const validRun = (rec: DemoRun | undefined, started: string): DemoRun | undefined =>
  rec && Math.abs(Date.parse(rec.started) - Date.parse(started)) < 60e3 ? rec : undefined;

/** The package a decision flies: the recommendation, an option, or none. */
export function chosen(m: ScriptMission, d: Decision | undefined): Pkg | null {
  if (typeof d === "number") return m.options[d]?.pkg ?? null;
  if (d === "accept") return null;
  return m.pkg;
}

export type Status = "waiting" | "approved" | "airborne" | "on station" | "returning" | "landed" | "not flown";
const MIN = 60e3;

/** Launch and recovery for a package: launch is `lead` minutes after approval (or after now, while it waits). */
export function timesOf(pkg: Pkg, approvedAt: string | null, now: string): { launch: number; back: number } {
  const launch = Date.parse(approvedAt ?? now) + pkg.lead * MIN;
  return { launch, back: launch + pkg.hours * 60 * MIN };
}

/** Where a package is in its sortie: 20% outbound, 60% on station, 20% back. */
export function statusAt(pkg: Pkg | null, approvedAt: string | null, now: string): Status {
  if (!pkg) return "not flown";
  if (!approvedAt) return "waiting";
  const { launch, back } = timesOf(pkg, approvedAt, now), t = Date.parse(now), d = back - launch;
  return t < launch ? "approved" : t < launch + 0.2 * d ? "airborne" : t < launch + 0.8 * d ? "on station" : t < back ? "returning" : "landed";
}

/** Statuses in which a package is in the air. */
export const FLYING: Status[] = ["airborne", "on station", "returning"];
/** One situation at a glance (Ops panel, Overview): each mission's package, status and times; how many fly; the next launch. */
export function situationState(script: Script, rec: DemoRun | undefined, now: string) {
  const approvedAt = rec?.approvedAt ?? null;
  const rows = script.missions.map((m) => {
    const pkg = chosen(m, rec?.dec[m.id]), st = statusAt(pkg, approvedAt, now), t = pkg ? timesOf(pkg, approvedAt, now) : null;
    return { m, pkg, st, launch: t?.launch ?? 0, back: t?.back ?? 0 };
  });
  const next = rows.filter((r) => r.st === "approved").map((r) => r.launch).sort((a, b) => a - b)[0];
  return { approvedAt, rows, flying: rows.filter((r) => FLYING.includes(r.st)).length, next: next ?? null };
}

export const GLYPH = (type: string) => /Ambulance|tender|truck|bowser|vehicle/i.test(type) ? "vehicle" : /Heron|UAS|Searcher/.test(type) ? "uav"
  : /Cheetah|Mi-17|Mi-35|Dhruv|Chetak|Rudra|Prachand|Chinook|CH-47|AH-64/.test(type) ? "helicopter"
  : /An-32|C-130|C-17|C-295|Do-228|Netra|Il-|A-50/.test(type) ? "airliner" : "fighter";
/** Ground packages (an ambulance, a fire tender) drive: their states read en route / on scene / back (D82). */
export const isGround = (type: string | undefined) => !!type && GLYPH(type) === "vehicle";
const GROUND_WORD: Partial<Record<Status, string>> = { airborne: "en route", "on station": "on scene", landed: "back" };
export const statusWord = (st: Status, type?: string) => (isGround(type) && GROUND_WORD[st]) || st;
const bearingOf = (a: [number, number], b: [number, number]) =>
  (Math.atan2((b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180), b[1] - a[1]) * 180) / Math.PI;

/** Where a package is (D71): 20% out, 60% orbiting on station, 20% back; at the base before launch and after landing.
 * Its aircraft share the leader's point and fly in formation as screen offsets (`slotOffset`), so a pair reads as two
 * jets at every zoom. */
export function packageState(m: ScriptMission, pkg: Pkg, approvedAt: string, now: string):
  { st: Status; home: [number, number]; pos: [number, number]; rot: number; atBase: boolean } | null {
  const b = BASES[pkg.base];
  if (!b) return null;
  const home: [number, number] = [b[1], b[2]], st = statusAt(pkg, approvedAt, now);
  const { launch, back } = timesOf(pkg, approvedAt, now), d = back - launch, t = Date.parse(now) - launch;
  const atBase = !(st === "airborne" || st === "on station" || st === "returning");
  let pos = home, rot = bearingOf(home, m.target);
  if (!atBase) {
    const f = st === "airborne" ? t / (0.2 * d) : st === "returning" ? 1 - (t - 0.8 * d) / (0.2 * d) : 1;
    const orbit = st === "on station" && !isGround(pkg.type) ? (t / MIN) * 0.05 : 0;   // a slow circle on station (vehicles wait on scene)
    // the circle on station starts and ends at the target; in transit the package stays on its route
    pos = [home[0] + (m.target[0] - home[0]) * f + 0.06 * Math.sin(orbit), home[1] + (m.target[1] - home[1]) * f + 0.04 * (Math.cos(orbit) - 1)];
    rot = st === "returning" ? bearingOf(m.target, home) : st === "on station" && orbit ? (orbit * 180) / Math.PI + 90 : rot;
  }
  return { st, home, pos, rot, atBase };
}

/** Icon offset of aircraft `i` of `n`, in icon pixels with the nose up (MapLibre turns it with the icon). In the air the
 * leader is in front and the others stagger behind it left and right; at the base they line up abreast just ahead of the
 * base badge, facing the target. */
export function slotOffset(i: number, n: number, atBase = false): [number, number] {
  if (atBase) return [(i - (n - 1) / 2) * 26, -50];
  const rank = Math.ceil(i / 2), side = i % 2 ? 1 : -1;
  return [rank ? side * 22 * rank : 0, 26 * rank];
}

/** One planner mission as the focused map view and its card see it (D71). `run` is a live run id or "routine". */
export interface PlanFocus { script: Script; m: ScriptMission; pkg: Pkg | null; st: Status; approvedAt: string | null;
  launch: number | null; back: number | null; ps: ReturnType<typeof packageState> }
export function planFocus(runs: Pick<LiveScenario, "id" | "code" | "started_sim">[] | undefined, demo: Record<string, DemoRun>,
  run: string, mission: string, now: string): PlanFocus | null {
  const r = run === "routine" ? null : runs?.find((x) => String(x.id) === run);
  const script = run === "routine" ? ROUTINE : scriptFor(r?.code);
  const m = script?.missions.find((x) => x.id === mission);
  if (!script || !m || (run !== "routine" && !r)) return null;
  const rec = validRun(demo[run], r ? r.started_sim : routineStart(now));
  const pkg = chosen(m, rec?.dec[m.id]), approvedAt = rec?.approvedAt ?? null;
  const t = pkg ? timesOf(pkg, approvedAt, now) : null;
  return { script, m, pkg, st: statusAt(pkg, approvedAt, now), approvedAt, launch: t?.launch ?? null, back: t?.back ?? null,
    ps: pkg ? packageState(m, pkg, approvedAt ?? now, now) : null };
}
