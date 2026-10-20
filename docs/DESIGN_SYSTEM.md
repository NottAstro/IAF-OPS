# DESIGN_SYSTEM: iaf-airops

| | |
|---|---|
| Status | Draft v0.2, 2026-10-16 (navy theme, MapLibre, crest) |
| Fixed by the team | Dark military theme, **navy + neon blue** (revised from olive + amber, 2026-10-16), fonts **B612 + B612 Mono**, APP-6 symbology, official IAF crest on the splash, login and top bar |
| Implements | [PRD](PRD.md) look and feel, FR-MAP-09, FR-BASE-14, FR-CMD, accessibility NFRs |

---

## 1. Concept: ops-room board and cockpit display
This app replaces a room full of status boards. Its look comes from two real objects in IAF operations.

**The ops-room status board.** A wall of perspex boards ruled into rows (aircraft, crews, fuel), with status written in by hand.
- Information sits in **ruled rows, not cards**. Tables, gauges and status rows share one horizontal rhythm.
- Panels are **smoked perspex over the map**: dark, slightly translucent, framed by a single ruled edge. They have no shadows and no rounded "cards".

**The cockpit multi-function display (MFD).** B612 was drawn by Airbus for exactly this screen.
- **The one bold element is the MFD bezel.** The mode switcher (Live / Weather / Terrain) and the side-panel tabs are drawn as **bezel soft-keys**: a column of short labels on the panel's edge with a neon-blue caret marking the selected key.
- Every other element is quiet and stays in the background so the map and data come first.

**Colour discipline from avionics:**
- Neon blue means *selected / where you are*.
- Red, orange, yellow and green mean *status*, and always come with a shape.
- Violet means *simulated*.
- Nothing is colourful for decoration.

---

## 2. Principles
1. **The map is the room.** Chrome is translucent, thin and docked to the edges. The map never becomes a thumbnail.
2. **Rows over cards.** Group with rules and alignment, not boxes. A side-panel section is a heading plus ruled rows.
3. **Status never by colour alone.** Every status has a shape glyph and a word.
4. **Real vs simulated is always visible.** Violet, a hatch pattern and a SIM tag are reserved for synthetic data and used nowhere else (§9).
5. **Night-ops legibility.** Low-luminance surfaces, no pure white, no large bright fills. The brightest thing on screen is data, never chrome.
6. **One orchestrated motion.** Selecting a base flies the camera and slides the panel in as one move (§11). Nothing else moves unless asked.
7. **Speak like the service.** Use real abbreviations (S, U/S, AOG, QRA, ICAO codes) in sentence-case labels. Codes stay uppercase because they are uppercase in real life. Labels and headings do not (§13).

---

## 3. Colour

### 3.1 Base palette (six named values)
Revised 2026-10-16 at the team's request: Indian Navy-style navy with neon blue replaces the original olive + amber.

| Name | Hex | Role |
|---|---|---|
| **Night navy** | `#050B16` | App background, map void outside the region |
| **Deep navy** | `#0A1528` | Panel surface (glass), at 86% opacity over the map |
| **Navy raised** | `#0F1E37` | Rows on hover, table header, inputs |
| **Ice** | `#E6F0FF` | Primary text (never pure white) |
| **Neon blue** | `#1FC8FF` | Selection, focus, active soft-key and switch, the India boundary, primary button |
| **Steel line** | `#4C7DB8` | Control borders, emphasised rules (≥ 3:1 on all surfaces) |

### 3.2 Full token set
The source of truth is `frontend/src/styles/tokens.css`; this lists the roles.

| Group | Tokens |
|---|---|
| Surfaces | `--bg #050b16`, `--surface-1 #0a1528`, `--surface-2 #0f1e37`, `--surface-3 #172a4b`, `--surface-glass rgb(8 18 34 / .86)`, `--rule #16294a`, `--line #4c7db8`, `--glow` (neon focus ring) |
| Text | `--text-1 #e6f0ff`, `--text-2 #9db2d3`, `--text-3 #7088ad` |
| Accent | `--accent #1fc8ff`, `--accent-strong #5ad8ff` (hover), `--accent-ink #00131f` (text on accent), `--accent-tint` |
| Status (always glyph + word) | `--ok #34d399` ●, `--caution #facc15` ▲, `--warning #fb923c` ◆, `--critical #f87171` ■, `--info #7dd3fc` ○, `--neutral #94a3b8` —; `--qra #2dd4bf` ◉ only for the QRA count on aircraft-type cards |
| Simulated | `--sim #b79cff`, `--sim-ink`, `--sim-hatch` |
| Map | `--map-land #0a1424`, `--map-land-2`, `--map-water #071a33`, `--map-road-major`, `--map-road`, `--map-rail`, `--map-runway`, `--map-label`, `--map-label-dim`, `--map-india-border #1fc8ff`, `--map-intl-border`, `--map-admin1`, `--map-admin2` |

### 3.3 Contrast (WCAG 2.1, computed)
| Foreground | on `--bg` | on `--surface-1` | on `--surface-2` | Use |
|---|---|---|---|---|
| `--text-1` | 17.1 | 15.9 | 14.5 | body ✔ |
| `--text-2` | 9.1 | 8.5 | 7.7 | labels ✔ |
| `--text-3` | 5.5 | 5.1 | 4.6 | hints, notes ✔ |
| `--accent` | 10.1 | 9.4 | 8.5 | ✔ |
| `--ok` | 10.2 | 9.5 | 8.7 | ✔ |
| `--caution` | 12.9 | 11.9 | 10.9 | ✔ |
| `--warning` | 8.7 | 8.1 | 7.4 | ✔ |
| `--critical` | 7.1 | 6.6 | 6.0 | ✔ |
| `--info` | 11.8 | 10.9 | 10.0 | ✔ |
| `--sim` | 8.6 | 8.0 | 7.3 | ✔ |
| `--line` (control border) | 4.6 | 4.3 | 3.9 | ≥ 3:1 ✔ |

- Accent ink on neon blue: **9.7** (✔).

### 3.4 Colour rules
- **Neon blue is never a status.** It means *selected / active*. Caution uses yellow `--caution` plus ▲. A row can be blue-selected and red-critical at the same time without ambiguity.
- **Violet is only for simulated data.** Never use it for real data or for decoration.
- Glow is reserved for neon-blue *active* things: the India boundary, the selected nav item / soft-key / switch, focus rings and the splash. Status colours never glow.

---

## 4. Typography
- **B612** (UI) and **B612 Mono** (data), SIL OFL 1.1, self-hosted via `@fontsource/b612` and `@fontsource/b612-mono`.
- Both families ship **Regular and Bold only** (plus italics). Hierarchy therefore comes from size, colour and position, never from weight 500/600.
- B612 has no Devanagari. The UI is English-only; add `Noto Sans Devanagari` as a fallback only if Hindi is ever needed.

### 4.1 Roles
| Family | Used for | Not used for |
|---|---|---|
| B612 | Headings, labels, body, buttons, table text | — |
| B612 Mono | **Values that are read or compared as figures**: KPI numbers, quantities, hours, fuel, coordinates, DTGs, ICAO codes, tail numbers, callsigns, squawks, METAR text | Small decorative labels. A label is a word, so it is set in B612 |

### 4.2 Scale (1.2 ratio, 14 px base)
| Token | Size / line height | Family / weight | Use |
|---|---|---|---|
| `--t-display` | 29 / 34 | B612 Bold | Screen title (Command overview), login |
| `--t-h1` | 24 / 30 | B612 Bold | Side-panel base name |
| `--t-h2` | 20 / 26 | B612 Bold | Section heading |
| `--t-h3` | 17 / 22 | B612 Bold | Subsection, table group |
| `--t-body` | 14 / 20 | B612 Regular | Default |
| `--t-small` | 12 / 16 | B612 Regular | Secondary labels, captions |
| `--t-micro` | 11 / 14 | B612 Regular | Map labels, legend (minimum size) |
| `--t-kpi` | 34 / 38 | B612 Mono Bold | KPI value |
| `--t-data` | 13 / 20 | B612 Mono Regular | Table numbers, codes (tabular by design) |
| `--t-hud` | 12 / 16 | B612 Mono Regular | HUD strip readouts |

- **Sentence case** for every heading, label and button ("Fuel and stores", "Mark unserviceable").
- **Uppercase only** where the real-world token is uppercase: ICAO codes, callsigns, tail numbers, status abbreviations (S, U/S, AOG, QRA, IFR).
- No tracked-out eyebrow labels above headings.
- Line length ≤ 75 characters in prose areas (alert detail, pilot notes).

---

## 5. Space, shape and screen layouts

### 5.1 Space and shape
- **Grid:** 4 px base. Steps: 2, 4, 8, 12, 16, 24, 32, 48.
- **Radius:** 0 for panels and tables (perspex sheets have square edges). 2 px for inputs, buttons and pills only, so controls read as controls.
- **Borders:** 1 px. Panels have **one ruled edge**, the edge facing the map, in `--line`. Other edges are borderless.
- **Elevation:** no drop shadows. Depth comes from surface steps (`--surface-1/2/3`) and the 88% glass over the map. Panels over the map use `backdrop-filter: blur(6px)`.
- **Z-order:** map < layer rail / HUD < side panel < modal < toast < opening shutter.

### 5.2 Main screen (`/map`)
```
┌────────────────────────── UNCLASSIFIED // SIMULATED DATA — SIH 2026 DEMO ──────────────────────────┐
│ iaf-airops   Map  Overview  Inventory  Pilots                    IST 14:32:05  Z 0902Z            │  top bar 44
├──────────┬──────────────────────────────────────────────────────────────┬──┬──────────────────────┤
│ Layers   │                                                              │▸ │ Adampur  VIAX        │
│ ▢ Bases  │                                                              │Ov│ Western Air Command  │
│ ▢ Bounds │                  FLAT MAP (MapLibre, Mercator)               │Ac│ ░░ SIMULATED ░░░░░░░ │
│ ▢ Infra  │                                                              │Cr│ Aircraft 18  S 14    │
│ ▢ Basemap│                                                              │Su│ ───────────────────  │
│ ▢ Live   │                                                              │De│ MiG-29   ●14 ■3 ▲1   │
│ ▢ Wx     │                                                              │Fu│ Fuel ATF ▕████▁▏ 62% │
│          │                                                              │In│ ...                  │
│ Legend   │                                                              │Wx│                      │
├──────────┴──────────────────────────────────────────────────────────────┴──┴──────────────────────┤
│ LIVE │ WX │ TER      31°25'58"N 75°45'32"E   zoom 6.2     adsb.lol ● adsb.fi ● OpenSky ▲          │  HUD 28
└────────────────────────── UNCLASSIFIED // SIMULATED DATA — SIH 2026 DEMO ──────────────────────────┘
```
- **Left dock (left edge, vertically centred):** Live, Weather, Infra, Ops, then a gear for **Map settings**. The selected section opens in a 288 px panel beside the strip. Map settings (D58, `.map-settings`, at least 304 px wide) has two quiet sections. **Map angle**: two picture tiles (`.angle-opt`: outline icon, label, sub-label: **Tilted** "3D terrain" · **Straight** "top-down"; selected = `--accent` outline on `--accent-tint`), then a one-line note. **Layers** "shown in every view": the **View** group (elevation colours and ramp, relief height, satellite imagery), Air bases, Boundaries & names and the symbol key, each a row with an `--accent` icon tile, title, an `x/y` count pill and a chevron that nudges right on hover. Map angle and relief height persist together in `airops.view.v1`. Weather disables Map angle with an explanation and restores the saved choice on exit. In Tilted, right-drag pitch remains temporary; Straight locks the map north-up and flat (no right-drag tilt). Clicking the open dock button again, or ×, closes the panel.
- **Map settings option windows:** View, Air bases, Boundaries & names and How to read the symbols open beside their headings on hover or click, without expanding the settings list. Only one window is open at a time. Hover uses a short open/close delay; clicking pins the window for interacting with switches and sliders. Outside clicks, the close button or Escape dismiss it; Escape returns focus. Windows flip or shift inside the viewport.
- **Wind model option panel:** the Weather flyout's trigger opens a compact list beside it on mouse hover (180 ms) or click; touch taps toggle it. A 200 ms close delay bridges the gap to the panel. Enter, Space or ArrowDown opens and focuses the listbox; arrows move, Enter selects, Escape closes and returns focus. Selection and outside clicks close it; it flips or shifts inside the viewport. GFS (NOAA) and IFS (ECMWF) keep their existing meaning. Non-map selects remain unchanged.
- **Right side panel:** 440 px. Its **left edge is the MFD bezel** (§7.1): a column of four vertical soft-keys with full names (Overview, Equipment, Crew, Base & weather; keys 1–4) and the neon-blue caret on the active key.
- **View switcher:** the dock buttons (keys 1–3 also switch). The HUD strip keeps only the cursor position, zoom and feed health.
- **Alignment:** text left-aligned; numbers right-aligned in tabular columns; panel headings aligned to the 16 px content inset.
- **Breakpoints:** 1366 (panel 400 px, rail collapsed by default), 1920 (primary), 2560 (panel 480 px).

### 5.3 Command overview (`/overview`)
```
┌ banner ──────────────────────────────────────────────────────────────────────────────┐
│ top bar                                                                              │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ Command overview SIM · one-line lead                                                 │
│ Readiness: serviceable 77% ▬ · QRA 14/17 ▬ · pilots 1071 ▬ · fuel below reserve 0 ·  │  six ruled tiles, each with a
│            air defence 87% ▬ · radar 87% ▬                                           │  thin fill bar in its tone
│ Situations now: ▌Runway closure · approved · 3 missions · 2 flying · Planner › Ops › │  one card per situation
│                 ▌Trainer crash · decide …   ▌Routine tasking · decide …              │  (left edge = intensity)
│ Commands: WAC │ SWAC │ CAC │ EAC │ SAC │ TC │ MC   (74% ▬ · QRA 4/4 · Pilots 445 · Fuel ok)│  seven cards
│ Bases (sortable): base │ command │ aircraft │ serviceable % ▬ │ QRA │ pilots │ fuel %  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```
**D79:** no alerts anywhere on the page (D69 removed the alert list). Readiness tiles: Aircraft serviceable, QRA met, Pilots available (fill bar `--accent`), Fuel below reserve, Air defence ready, Radar operational; tones from `sevTone`, the bar in the tile's tone. **Situations now** reads the same scripted state as the Planner and the Ops panel (`situationState()`): name, `.fl-pill` approved / decide, category · since HH:MM (or "today's tasking"), a summary ("3 missions · 2 flying · next launch 14:56" / "waiting for your decision"), "Planner ›" and, once approved, "Ops map ›"; a dashed "+ Start a scenario" card when none is running. **Command cards** (same order and facts in each, so they read across): code, "support" for TC / MC, base count, name, serviceability % large in its tone with a bar ("no aircraft" for MC), then QRA x/y, pilots, fuel ok / N low; a click filters the base table and centres the map; the selected card has an `--accent` border and glow. The **base table** drops alerts and shows a 60 px bar next to each serviceability %. Values only, no scores (FR-CMD-04).

### 5.4 Pilot profile (`/pilots/:id`)
```
│ Sqn Ldr R. Varma (fictional)  ░SIM░   "TALON"   SIM-2xxxx   47 Sqn, Adampur            │
├───────────────────────────────┬───────────────────────────────────────────────────────┤
│ Status rows                   │ Career timeline (horizontal ruled track):             │
│ Medical   ● Fit (full)  → 2027│ PC-7 ─ Kiran ─ Hawk ─ MiG-21 ─ MiG-29 (now)          │
│ Duty      ○ Standby           ├───────────────────────────────────────────────────────┤
│ Fatigue   ● 3.1 h / 24 h      │ Hours by type (table, mono numbers, right-aligned)    │
│ Currency  ▲ Night lapses 4 d  ├───────────────────────────────────────────────────────┤
│ Quals     QFI, NVG, FL-4      │ Sortie history (paged table)                          │
```
The career timeline is a real sequence, so it may use ordered markers. Nothing else does.

---

## 6. Iconography and symbology

### 6.1 Map symbols: rectangular tags (revised 2026-10-16, team choice over APP-6 and round badges)
All map icons are drawn on canvas by `map/symbols.ts`; the image id encodes the drawing parameters and `styleimagemissing` builds it on demand.

| Entity | Far out (compact) | Closer in (full tag) |
|---|---|---|
| IAF air base | Neon-blue block (`--base-iaf`) with a dark jet, soft glow | From zoom 5.5: blue jet cell + dark code panel (`VIAM`) + QRA end-cap ("Q", blue met / red short) |
| Navy / Army / Coast Guard | Grey block (`--base-other`) | From zoom 6.5: grey tag with code |
| Pakistan / China | Red block (`--base-hostile`) | From zoom 6.5: red tag with code |
| Other neighbours | Green block (`--base-neutral`) | From zoom 6.5: green tag with code |
| Advanced landing ground | Small blue block with a runway glyph | From zoom 8: small tag with code |
| Civil airport | Light tile (#e3ecf8) with a dark airliner | Large from zoom 6, medium from 8: light tag with IATA / ICAO; name under it from 9.5 |
| Railway station | Small gold square; major junctions carry a dark track bar | name from zoom 7 (major) / 11 (all) |
| Telecom tower (Infra only, default off) | Mast and signal arcs on a dark outlined tile, `--map-tower`, from zoom 9 | 20–24 px canvas hit box; size grows through zoom 15. Symbol collision declutters the MVT layer; MVT sources cannot use GeoJSON clustering. |
| Air defence site (Ops only, default off) | Violet `--sim` shield with an upward chevron; SIM tag drawn under it in the icon | Code from zoom 7. Hovering or selecting it pops its dashed `--accent` ring (fill 8%) with "code · system · range" at the north edge. Hover says “(simulated)”; the SIM card shows only existing system/category/status, launcher counts, range, protected base and coordinates. No description field exists. |
| Radar site (Ops only, default off) | Violet `--sim` round tile with a scope (sweep line, two range arcs); SIM tag in the icon | As AD: code from zoom 7, dotted `--info` ring pops on hover / select, card with type, category, status, range, base. Longer range wins collisions far out; from zoom 9 every site is drawn, even beside a base tag (comms and point defence sit 1–8 km from their base). |
| Comms node (Ops only, default off) | Violet `--sim` diamond with a mast; SIM tag in the icon | From zoom 5.5, code from 7; no ring; card with node type, status, base. Simulated sites in maintenance, offline or down are drawn at 45% opacity. |
| City / capital | Dot / ringed dot next to the name | — |

- **Serviceability:** a bar under every IAF tag (full width = 100%; green ≥ 70, yellow 45–69, red < 45).
- **Alert dot:** orange (warning) or red (critical) on the tag's top-right corner. Nothing floats around the symbol.
- **Base names** appear under the tag from zoom 8.5; hover always shows name, code, serviceability, QRA and alert.
- **Collision:** IAF tags always draw; airports sit above city names so a label never hides its airport; other bases and stations yield.

### 6.1b Equipment pictures (base side panel, Inventory)
- **Aircraft:** top views from real proportions, so a type is recognised by its planform, painted to look real (D68): matte paint per family (fighters mid grey, transports and AEW&C light grey, propeller trainers white, helicopters olive grey, UAVs light grey) shaded like a cylinder on bodies and nacelles, light panel lines (spars, control surfaces, spine, access panels), dark tinted glazing with a glint, a lighter radome and dark nozzles. Colours are `--ac-*` tokens. **No national markings**: no roundel, fin flash or ensign (AGENTS.md §8).
- **Vehicles, ground support equipment, air defence and radars:** 3D-style illustrations (3/4 view, lit faces, shaded cylinders, wheels with hubs, glass with reflections, soft ground shadow) built from parts by `frontend/src/equipment/iso.tsx` + `models.tsx`, in realistic colours: GSE yellow, fire tender red, ambulance white, IAF vehicles blue-grey, military systems olive.
- **Cards** (two columns): picture, name, one line on what the equipment does, "16 of 17 ready" in large type, a readiness bar, and what isn't ready in plain words ("1 out of service", "3 in scheduled maintenance"). Opening a type shows one card per item with its serial or tail number, a plain-word status ("Ready", "Out of service") and key facts; base commanders can mark aircraft serviceable / unserviceable.
- **Inventory page:** the same pictures as row thumbnails on Aircraft, Aircraft types, Vehicles & GSE, AD batteries and Radars.
- **Inventory navigation:** six main categories replace the flat list of 22 entity tabs: Fleet; Personnel; Operations; Logistics & support; Defence & communications; Bases & infrastructure. A second row shows only the selected category's records. Reference types are labelled Specifications in Fleet, and AD specifications / Radar specifications under Defence & communications; fuel transactions are labelled Fuel activity. **Two rows (D80, D81, D83):** row 1 is a tab header (`.inv-tab`) under a `--rule` line: icon, category name and a count chip ("Fleet 1,822", "Personnel 7,037", "Logistics & support 4,599", "Defence & comms 225", "Bases & infrastructure 75"; the chip's title says what it counts); the active tab is bold `--accent-strong` with a 2 px `--accent` underline and a tinted chip. Row 2 is one toolbar strip (`.inv-bar`, D84: `--surface-1`, 10 px radius, every control 32 px high): the records as a segmented control on a `--bg` track (active `--surface-3`, bold, `--accent` underline), a divider, a search box with a magnifier icon (`--accent` border and glow while focused), chip filters (`.inv-filter`, `--accent` border and tint while in use), "× Clear" whenever a filter or search is set, then Export CSV (download icon) and New (plus icon, `--accent`) grouped on the right so they wrap together; read-only lists show a small "read only" tag. **Tables (D81):** no Id or geometry columns, and a column that is empty on the current page is left out; linked columns (base, warehouse, type) read left-aligned as text; headers are words with units in brackets ("Capacity (kL)", "Burn (kg/h)", "ICAO type", "Time"); litres show as kL; codes read as words (FUEL_BOWSER → Fuel bowser, roles as "Multirole fighter", statuses spelled out); Edit / Retire / Delete appear on row hover. **Fuel and stock (D81):** fuel storage opens with one card per grade (ATF, Avgas, Diesel HSD: percent full, a bar in `--ok` / `--caution` / `--critical`, "on hand of capacity kL", tank count, how many at reorder or below reserve); fuel storage and stock levels replace their four number columns with a Level gauge (reserve tick `--critical`, reorder tick `--caution`, "on hand / max", percent) and a State (OK / Reorder / Below reserve). Fuel activity names the tank's base ("VABJ · ATF") and signs quantities in kL (receipts `+` in `--ok`, issues and transfers out `−`). Direct entity and aircraft-type URLs select the correct category. Tables, cards, permissions and SIM labels remain unchanged; base and command filters carry across navigation, while record search, pagination, sorting and editing reset on entity changes.
- **Inventory → Aircraft type cards** (2026-10-17): the Aircraft tab opens on a grid of cards, one per aircraft type, grouped Aircraft / Helicopters / UAVs & drones (5 per row on wide screens, then 4, 3, 2, 1). Card: top-view picture, name, total (accent-tint badge), role · squadrons, a stacked status bar and counts with glyph + word: ● Serviceable `--ok`, ◉ QRA `--qra` (teal, a subset of serviceable), ▲ Maintenance `--caution`, ◆ U/S `--warning`, — Depot `--neutral` (only when non-zero); footer "View aircraft ›". Hover/focus: accent border, glow, 2 px lift. Opening a card shows a breadcrumb (Inventory › Aircraft › type), a "‹ Back to aircraft types" button, a header with the same bar and counts, then the standard table.

### 6.1c Base side panel: four sections (revised 2026-10-16)
1. **Overview:** readiness tiles (Aircraft ready, Pilots available, Vehicles & support equipment ready, Air defence & radars), a quick-reaction-alert line, **Needs attention** (open alerts, worst first), and **Fuel**: one card per grade with a gauge (reserve and reorder ticks), stock vs capacity, daily use, how many days it lasts at that rate, reserve and tank count, next delivery; then recent fuel movements.
2. **Equipment:** every type at the base as picture tiles grouped into Aircraft, Helicopters, UAVs & drones, Air defence & artillery, Radars, Vehicles, Ground support equipment, Communications (ready / total and a bar). Clicking a tile shows that type with one card per item (tail number or serial, plain-word status, facts; base commanders can mark aircraft out of service / ready). Below the tiles: Stores (warehouses, generic armament stock, items below reorder level).
3. **Crew:** summary tiles, a search box (name, callsign, squadron) and role filter, then every aircrew member grouped by rank, highest first (Air Commodore → Flying Officer), each row opening the profile; ground crew by trade at the end.
4. **Base & weather:** current METAR / TAF and a 48-hour forecast button, runways, parking and shelters, connections (railheads, airports, national highways, nearby IAF bases), landing grounds within 300 km, zoom to field.
- Aircraft readiness excludes small quadcopter drones everywhere (database view `v_aircraft_serviceability`), so the tile, the map, the command overview and the alerts give the same number. Drones are listed under UAVs & drones.

### 6.2 Civil ADS-B glyphs
Custom monochrome top-down silhouettes (`public/glyphs/*.svg`) in `--text-2`:
- airliner, cargo (same silhouette with a box notch), helicopter, UAV, drone
- military ADS-B uses the APP-6 unknown air track

Each glyph is rotated to `track_deg`. Emergency squawk draws a `--critical` square outline.

### 6.3 UI icons
Lucide (ISC), 16/20 px, 1.5 px stroke, `currentColor`. Icons always come with a text label or `aria-label`.

---

## 7. Components

### 7.1 Bezel soft-keys (the signature element)
- **Anatomy:** a column (side panel) or row (mode switcher) of keys. Each key is a 2–3 letter label in B612 Bold 11 px on `--surface-1`.
- **Separators:** 1 px `--rule` between keys, like the physical gaps on an MFD bezel.
- **Active key:** a **neon-blue caret** (a 6 px triangle pointing into the content) and glowing neon-blue text. Inactive keys are `--text-2`.
- **Behaviour:**
  - Keys are buttons with the full name in `aria-label` and a tooltip ("Fuel and stores").
  - Arrow keys move between keys; Enter activates.
  - Number keys `1–8` jump to side-panel tabs while the panel has focus.
- **Used in:** the base side-panel tabs (Overview, Equipment, Crew, Base & weather). Nowhere else; the element stays special.

### 7.2 Other components
| Component | Spec |
|---|---|
| **TopBar** | 44 px. Product name (text only), nav, alert counter (critical count in `--critical` ■), IST clock (primary, `--t-hud` 14 px), Zulu clock (secondary), simulator clock with speed and pause state, user and role |
| **LayerRail / LayerToggle** | Group heading + rows: checkbox, label, live count (mono, right), opacity slider on expand. Disabled rows say why ("Needs OWM key", "Not broadcast on public ADS-B") |
| **Legend** | Generated from the active layers; symbol + label rows |
| **SidePanel** | Glass surface, neon-blue left edge with a soft glow with the bezel. Header: base name (`--t-h1`), ICAO (mono), command, wing; status row (ops status, METAR flight category, QRA). Body: ruled sections |
| **StatusRow** | label (B612, `--text-2`) · glyph + word (status colour) · value (mono, right). The primary building block of the panel |
| **KpiTile** | No card box. A ruled cell: label (sentence case, `--t-small`), value (`--t-kpi`), a delta or "of N" (mono, small), and a 3 px status edge on the left only when not normal |
| **StatusPill** | 2 px radius, 1 px border in status colour, glyph + word: `● S`, `■ U/S`, `◆ AOG`, `▲ Lapsing`, `○ Standby`. Fill only for critical |
| **FuelGauge** | Horizontal bar 8 px tall, `--surface-3` track, fill `--text-1`. Fill switches to the status colour below thresholds. **Reserve tick** in `--critical`, reorder tick in `--caution`. Value and days of supply in mono |
| **DataTable** | 32 px rows, `--rule` hairlines, sticky header on `--surface-2`. Text left, numbers right (mono). Selected row: `--surface-3` + 2 px neon-blue left edge. Row actions appear on hover/focus only. Server-side paging footer |
| **EntityForm** | Labels above fields; inputs `--surface-2` with a 1 px `--line` border and 2 px radius. Errors below the field in `--critical` with ■ and a sentence that says how to fix it. Point picker opens the map in a modal |
| **Buttons** | Primary: neon-blue fill, `--accent-ink` text ("Save changes"). Secondary: 1 px `--line` outline, `--text-1`. Ghost: text only. Danger: 1 px `--critical` outline, critical fill on confirm |
| **Toast** | Bottom-right stack, max 2 (D67). Severity glyph + message. Warnings close after 6 s, critical after 12 s; open alerts stay on the base tags, the base panel's "Needs attention" and the Overview tile (the Alerts page was removed, D69) |
| **Modal / ConfirmDialog** | Centred, `--surface-1`, neon-blue top rule. Destructive actions name the object ("Retire SIM-K9012?") |
| **HUD strip** | 28 px, `--t-hud`: cursor coords (DMS ↔ DD toggle), camera altitude, feed chips, SIM chip |
| **FeedChip** | Provider name + state glyph: ● live, ▲ stale, ■ off, ○ disabled (no key). Tooltip shows last update and error |
| **SimBadge** | `SIM` in B612 Bold 10 px, `--sim-ink` on `--sim`, 2 px radius |
| **MetarCard** | Raw METAR (mono, wrapped) above decoded StatusRows; flight-category pill (VFR ● / MVFR ○ / IFR ▲ / LIFR ■); "nearest: VIAR, 38 km" note when using a fallback |
| **InfoCard** (map) | Small anchored card for non-base features: title, 3–6 StatusRows, source line, licence credit |
| **Empty / Error / Skeleton states** | Empty: says what would appear and the next action ("No aircraft at this base. Add aircraft"). Error: what failed and what to do ("adsb.fi did not respond. Showing adsb.lol only.") Skeleton: ruled rows at `--surface-2`, no shimmer |

---

## 8. Map styling
Engine: **MapLibre GL JS**, flat Web Mercator (no globe). Style in `frontend/src/map/style.ts`, colours from tokens via `map/colors.ts`.

**Views.** The dock switches between Live, Weather, Infra and Ops (keys 1–4). Live, Infra and Ops retain 3D terrain and apply the saved **Map angle** (Tilted 42°, Straight 0° north-up with rotate and tilt gestures off) on load and after Weather; changing it eases pitch without moving centre or zoom. Manual right-drag pitch (Tilted only) does not overwrite the choice. **Weather is always flat** (no terrain, pitch 0). Map settings holds Map angle at the top, then View: elevation colours, relief height and satellite imagery. Layers remain exclusive to their views; synthetic sites appear only in Ops.

**Connectivity focus (Infra).** The Infra flyout has a Connectivity focus switch, disabled until an IAF base is selected. When on, hide normal base/infrastructure layers, elevation colours, hillshade, place labels and the old spotlight; keep official boundaries and the chosen normal or satellite basemap, kept flat. Connectivity focus follows the global Satellite imagery preference in Map settings, which remains editable during focus; switching preserves the source, destination and route. Infra has no separate satellite control. Dedicated public base tags carry names/codes only, without synthetic readiness indicators. The source and selected destination have accent rings; direct connections are dashed accent lines with distance labels (other destinations fade on selection), and the road route is solid teal with a soft glow. Dotted neutral connectors join the road endpoints to public base coordinates and are explicitly described as estimated, not verified entrances. The compact Base connectivity card replaces the inventory panel: nearby bases ordered by direct distance, destination selection, Direct / Shortest road route, Fit connections and Exit focus. Missing road data gets a message and retry button; no fabricated geometry or travel time is shown. Closing the source/card, changing view, or leaving the map exits focus, restoring the previous saved layer/tilt settings. This is public information, not a simulated planning surface or a validated flight path.

**Selected live flight paths.** A `--map-trail` ring highlights the dead-reckoned icon and a solid 2.2 px line shows up to 120 recorded positions, joined to that icon. The card reports the recorded point count and that history starts when this server first sees the aircraft. When adsbdb provides both airport locations, dashed 1.8 px `--map-schedule` great-circle legs run from the origin airport to the first recorded point and from the aircraft to the destination; the destination leg is labelled “Scheduled route (adsbdb, may differ from actual)”. **Leg ends (D77):** the destination is a 7 px `--bg` ring with a 2.5 px `--map-schedule` stroke and a filled core, labelled bold “DEL · Indira Gandhi” with “arriving” below; the origin is a 5.5 px ring labelled “MAA · Chennai” / “departed”; the first recorded point is a 3.5 px `--map-trail` ring labelled “first seen HH:MM” in `--text-2`. The card's Route row shows the IATA pair and both short airport names. It is schedule data, not a filed flight plan; heading is never projected as a route. Missing history and schedule show **Flight path unavailable**. Selection changes replace the path; clearing selection, leaving Live or the map, hiding the category, or losing the aircraft removes it. None of these actions moves the camera.

| View | Own layers |
|---|---|
| Live (1) | Air traffic: Civil aircraft, Military aircraft, UAVs & drones |
| Weather (2) | Cloud cover from satellite IR (rendered as white cloud), rain (OWM), animated wind flow (GFS / IFS), airfield METAR dots with flight category; wind-speed and flight-category legends |
| Infra (3) | National highways (with NH numbers), main roads, railway lines, railway stations, civil airports, telecom towers; then **Defence & comms** with a SIM badge (D75): simulated radar, air defence and comms sites (counts, default off), "Show all coverage" once radar or AD sites are on, and the note "Simulated sites placed by the generator, not real deployments". Hovering a radar / AD site pops its ring (radar `--info` dotted, AD `--accent` dashed); a click keeps it and opens the site card. Selecting a base spotlights a 60 km circle and draws labelled links to the nearest railhead, airport and IAF bases (straight-line distance) |

**Framing:** opens with India filling the frame; panning is held to 50–115°E, 1–39.5°N so Central Asia and Russia never show.

- **Basemap:** OpenFreeMap vector tiles (OpenMapTiles schema), used for terrain features only: land cover (ice, sand, wood), urban land use, water, rivers, runways, roads, rail. Land `--map-land`, water `--map-water`.
- **Never used from OpenFreeMap:** `boundary`, `place`, `poi`, `mountain_peak`, `aerodrome_label`, `transportation_name`. Every boundary and every name comes from our own tiles (`/api/v1/gis/tiles`, GoI depiction). The one exception is ocean/sea names (`water_name` ocean/sea only), which carry no sovereignty.
- **Region:** opens framed on India; the camera is held inside 52–113°E, 6°S–46°N; minimum zoom 3.
- **Boundaries:**

  | Feature | Style |
  |---|---|
  | India (official) | `--map-india-border` 1.3–2.2 px plus a blurred neon glow underneath |
  | International (neighbours) | `--map-intl-border`, 0.9–1.6 px |
  | States / provinces | `--map-admin1`, 0.5–1.3 px; neighbours at 55% |
  | Districts (from zoom 5.5) | `--map-admin2`, 0.7 px, dashed 3–3; neighbours at 50% |

  The straight edges where the pipeline clipped neighbour polygons to the region are removed in the tile query; they are not borders.
- **Labels** (Noto Sans glyphs from OpenFreeMap; B612 has no glyph PBFs):
  - Countries: uppercase, Bold, tracked 0.3 em, `--map-label-dim`, up to zoom 7.
  - States: uppercase, Bold, tracked 0.14 em, zoom 4–9. Districts: Regular 10 px from zoom 6.5.
  - Cities: GeoNames, thinned by population per zoom (≥ 3 M at zoom 3 down to all at zoom 9), Bold above 1 M.
  - Collision handles the budget; larger areas and populations win.
- **Relief:** hillshade from AWS Terrain Tiles (terrarium), navy shadows and steel highlights, on by default ("Terrain shading").
- **Satellite imagery** (off by default): Esri World Imagery at brightness 0.6, saturation −0.35.
- **Transport:** motorway/trunk `--map-road-major` from zoom 4.5; primary `--map-road` from 6; secondary/tertiary from 8; rail `--map-rail` dashed 3–2 from 5.
- **Live air:** top-down glyphs rotated to track, 0.62× at theatre zoom to 1.15× close in (22–24 px images); civil yellow `--caution`, military neon blue `--accent` (fighter silhouette), UAVs and drones orange `--warning`, emergencies `--critical`. Positions are dead-reckoned every second between 10 s polls. Callsigns from zoom 7.5.
- **Alert halo:** a static ring (with a faint fill) in the alert colour around IAF bases with an open WARNING or CRITICAL alert.
- **Weather overlays:** default opacity 0.6, inserted under the labels.
- **3D terrain:** on in Live and Infra (relief 1–3× from Map settings, sky and horizon fog); off in Weather.

---

## 9. SIMULATED labelling rule
Synthetic data must be recognisable as synthetic on every surface.

| Surface | Treatment |
|---|---|
| Login | Disclaimer paragraph: "All operational data in this system is simulated for SIH 2026. Base locations are from public sources. No real personnel are shown." |
| Side panel (IAF base) | No stripe (removed at the team's request, 2026-10-16); SIM badges remain on synthetic sections |
| Tables | All-synthetic view: one SIM badge next to the title. Mixed view (e.g. bases: public location + synthetic status): per-cell SIM badge on synthetic columns |
| Pilot profile | SIM badge next to the name; name followed by "(fictional)" on first appearance |
| Map | Live contains real/public data only. Ops contains synthetic tracks, mission objects and generator-placed AD, radar and comms sites: violet site symbols carry a SIM tag drawn into the icon (never dropped by symbol collision), hover says “(simulated)”, and detail cards carry a SIM badge. Base symbols show public identity/location; their synthetic serviceability, alerts and QRA are explained in the layer rail key. |
| CSV export | First line `# SIMULATED DATA — SIH 2026 DEMO — NOT REAL` |
| API | `"simulated": true` on every synthetic object |

Never use violet for real data. Never drop the SIM marker to make a screenshot look cleaner.

---

## 10. Classification markings and emblems
- **No classification banner** (removed at the team's request, 2026-10-16; ARCHITECTURE D22). The simulated nature of the data is still shown by the login disclaimer and SIM badges (§9).
- **Never** display RESTRICTED, CONFIDENTIAL, SECRET, TOP SECRET or caveats such as NOFORN / SI-TK. God's Eye's `src/hud.js` banner strings must not be reused.
- **IAF crest:** used, at the team's explicit request (2026-10-16), on the opening splash, the login card, the top bar and the browser tab. The file is the Government of India crest from Wikimedia Commons (GODL-India). It is not altered, recoloured or combined with other marks. The roundel, fin flash and ensign are still not used. The team owns the Emblems and Names Act clearance for any use beyond the SIH demo.

---

## 11. Motion
- **Opening shutter:** on every app load the IAF crest sits centred in a slowly turning neon ring for 2 s, then two blast-door halves (grid texture, hazard-striped neon edges) slide apart over 0.9 s onto the login or the map. A click skips it; with reduced motion it opens after 0.6 s with no movement.
- **The one in-app orchestrated moment:** selecting a base flies the map to it (1.2 s, offset so the base stays clear of the panel) and slides the side panel in (220 ms, ease-out).
- **Feedback motion only:** toggles 120 ms; soft-key caret 120 ms; toast enter 200 ms; switches 150 ms.
- **Never:** entrance animations on page sections, hover lifts, shimmer skeletons, parallax.
- **Wind streamlines** are paused by default and start when the layer is toggled.
- **`prefers-reduced-motion: reduce`:** camera flights become instant jumps; no slides, flashes or pulses; wind animation stays off.

---

## 12. Accessibility
- **Contrast** per §3.3. Text ≥ 4.5:1; control boundaries and focus indicators ≥ 3:1.
- **Focus:** 2 px `--accent` outline, 2 px offset, on every interactive element. Never removed.
- **Status redundancy:** glyph (● ▲ ◆ ■ ○ —) + word + colour on every status; dash patterns on rings.
- **Keyboard map:**

  | Key | Action |
  |---|---|
  | `/` | search |
  | `L` | layer rail |
  | `1` / `2` / `3` | Live / Weather / Terrain (map focused) |
  | `Esc` | close panel or card |
  | `[` / `]` | previous / next base in the current list |
  | `1–8` | side-panel tabs (panel focused) |
- **Screen readers:**
  - polite `aria-live` region announcing new WARNING+ alerts, throttled to one per 10 s
  - map selections announced ("Adampur selected, 14 of 18 aircraft serviceable")
- **The tables are the accessible version of the map.** Every datum on the map is reachable through a table or panel.
- **Minimum text size** 11 px (map labels), 12 px (UI).

---

## 13. Content, voice, units and time
- **Voice:**
  - Plain, active, sentence case. Buttons say what happens: "Mark unserviceable", "Create sortie", "Acknowledge alert".
  - The confirmation repeats the verb: "Alert acknowledged".
- **Errors** say what happened and how to fix it, without apology: "Fuel can't exceed tank capacity (240,000 L). Enter a lower amount."
- **Time:**
  - IST is primary: `16 Oct 2026, 14:32 IST`.
  - Zulu is secondary and used in DTGs: `160902Z OCT 26`.
  - METAR/TAF always Zulu.
  - Durations as `1 h 25 min`.
- **Coordinates:** DMS by default (`31°25'58"N 75°45'32"E`), DD on toggle (`31.4328, 75.7589`).
- **Units:**
  - altitude ft (FL above transition: FL350)
  - speed kt
  - distance NM on map tools, km elsewhere
  - fuel L / kL
  - mass kg
  - temperature °C
- **Status vocabulary:**
  - aircraft: S (serviceable), U/S, AOG, Maint (sched/unsched), QRA, Standby, Airborne
  - crew: On duty, Standby, QRA, Crew rest, Off duty, Leave, Sick, Course
  - Tooltips always give the long form.
- **Ranks:** standard IAF abbreviations (Fg Offr, Flt Lt, Sqn Ldr, Wg Cdr, Gp Capt, Air Cmde).

---

## 14. Token implementation
- `frontend/src/styles/tokens.css` is the single source (§3.2, §4.2, §5.1 values as CSS custom properties).
- `frontend/src/map/colors.ts` reads tokens via `getComputedStyle(document.documentElement)` and normalises them (including CSS4 `rgb(r g b / a)`) for MapLibre. Map code never hard-codes hex.
- No CSS-in-JS. Use CSS modules per feature plus the global tokens. Selectors stay at single-class specificity so feature styles never fight.
- One stylelint rule blocks raw hex outside `tokens.css`.

---

## 15. Phase 2 screens (decision support)
Built only from the existing tokens and components (§3, §7); no new hues, fonts or libraries. Bezel soft-keys stay in the base panel.

| Screen | Layout | Notes |
|---|---|---|
| **Planner** (`/planner`) | situation cards, then four steps per situation (D61); content scripted per scenario (D66, `features/scripts.ts`) | **Landing (D70):** one sentence ("N situations wait for your decision") and `.sit-list`, one full-width `.sit-row` per situation (waiting for a decision first, Routine tasking after the scenarios; left edge in the intensity colour), every row the same three columns: intensity dot and name, one meta line (category · intensity dots · since HH:MM, or "today" for Routine tasking) and the lead clamped to 2 lines; up to three "what happened" bullets; a state line (◆ "N recommendations wait for your decision" `--warning` / ✓ "Approved · N airborne" / ✓ "Done: every mission flown" `--ok`); foot "N missions affected" and "Open →"; then a dashed full-width "+ Start a scenario" row; then "Details & tools" folded (real planner). **Inside a situation** (`?run=<id|routine>&step=1..4`): "← All situations", `.steps4` (badges "N to decide", "N decided", "waiting" / "approved"), the header (name, live, since, SIM), the lead and the mini timeline (event → planner ready → your decision / approved → first launch → back to normal). 1 Situation: a "What happened" `.sbox` (each fact, "until HH:MM" when it ends), then "Missions affected · N" `.r4` rows (pill added `--info` / moved `--warning` / not flown `--critical` · priority and mission with why it's affected · package and launch – back · ◆ recommendation ready / ✓ decided / live status once approved), then "Plan it →". No cost table (D66). 2 Plan: "✓ Keep all N", then numbered `.tk` cards (priority and mission, kind and reason, kind pill; "Planner's recommendation" or "Your choice": package and times; "Why:" three reasons, or the chosen option's trade-off; ✓ Keep / ✓ Accept and a ghost "Other options ▾" listing two options with "Use this instead"); side "What this situation needs": per package need, from base · free and rested, when, "once approved" / "✓ committed". 3 Decide: "What you decided · N" `.r4` rows (Keep / Your choice / Not flown · launch time), then "N not decided yet" (undecided follow the recommendation) or "Next: mission →". 4 Mission: `.approve-box` with Reject / Approve missions until approved, then "✓ Approved at HH:MM … Map → Ops"; "Missions for this situation · N" `.r4` rows with a live status pill (waiting, approved, airborne, on station, returning, landed, not flown) and launch / lands / landed time. Each row is a button (D71): hover tints it `--accent-tint` and shows "on map ›"; a click opens Map → Ops focused on that package. Approval is demo state in this browser; nothing writes sorties. |
| **Missions** (`/missions`) | standard table + filters; "New mission request" modal | "Pick on map" hands the one map the click and returns (no second map, AGENTS §5) |
| **Scenarios** (`/scenarios`; ADMIN and COMMAND_HQ start / end, only ADMIN changes the clock, other roles read-only; `/exercise` redirects) | clock speed + Pause; card grid (category, name, one-line effect, intensity dots 1–4 in `--ok` / `--caution` / `--warning` / `--critical`, `● live 9 min` or "ready"); selected-scenario panel: category · intensity, description, form (base / type selects, choice segments, base chips), "Adds missions" (priority pill + type), intensity segments, Start now / End scenario / Open in Planner →; no committed plan needed; ended runs with their AAR | AAR (`/exercise/runs/:id`): KPI row, injects, plans, disruptions with proposal and decision time, mission outcomes; CSV + print stylesheet D66: each scenario's side panel shows its script's lead and fixed facts (base, hours, intensity) instead of parameter controls, and "Missions it affects" from the script; Start sends the script's parameters. |
| **Ops map view** (dock key 4) | flyout: simulator clock; **Missions** (D72, cards D74, caption "click one to see it on the map"): one `.msn-card` per live scenario (`--surface-2`, 6 px radius, 3 px left edge in its intensity colour, `--accent` for Routine tasking), Routine tasking once approved; every card starts closed (D78). Card head: bold name, `.fl-pill` "approved" `--ok` or "decide" `--warning`, a `›` that turns down when open, and a micro summary ("3 missions · 2 flying · next launch 07:46", "all back", or "3 missions · waiting for your decision"). Each mission is a `.msn-row`: a priority badge (outlined, mono, P1 `--critical`, P2 `--warning`, P3 `--caution`, P4 `--neutral`), the mission name, then a micro line with a 13 px top-view icon (jet, helicopter or drone, tinted by state), "2 × Su-30MKI" and the status on the right ("airborne" `--sim`, "launch 07:46" `--ok`, "waiting" `--warning`, "landed" dim, "not flown" `--critical`), and a 3 px `--sim` progress bar while it flies. Hover `--surface-3`; the focused row `--accent-tint` with an `--accent` inset bar; a click focuses the package on the map (D71) and a second click re-frames it. Card foot: "Open in Planner ›"; then "On the map", a key styled like the map (a ring "Mission area" with "waiting · approved · flying · done" in their tones; a hatched square "Threat zone (generic)" with "hatched band: higher risk"), and "SIM Everything here is simulated." (D73, D76, D78) | **Only two things are drawn (D76), styled per D78:** mission areas are a soft ring (8 → 15 px, fill 16 %, 1.5 px stroke) with a solid 2.4 → 3.6 px core, in the panel's state tones (`--warning` waiting, `--ok` approved, `--sim` airborne / on station / returning, `--neutral` landed or not flown), labelled from zoom 5.5 with "P2 Combat air patrol near Jalandhar" in `--text-1` and a smaller state line ("launch 07:51", "airborne") in the same tone; hover "P2 · … · click to follow it", a click focuses the package. Threat zones (`--base-hostile`): a tint of 3 % + 12 % × risk, a diagonal hatch at 32 % when risk ≥ 0.5, a 7 px soft glow, a crisp 1.6 px solid edge (risk ≥ 0.5) or a 1.2 px dashed one, and the band name along the edge from zoom 5. No sortie tracks, unknown tracks, routes, scenario-effect rings or stock lines; a package's aircraft and route appear only when it is focused. Training areas and weather impact are not drawn in Ops (D73); defence sites are in Infra (D75). **Mission symbols (D82):** every mission area (and a focused package's target) shows its type as a 26 px disc ringed in the state tone: parachute = rescue of an ejected pilot, cross = casualty evacuation, racetrack = combat air patrol, eye = surveillance, radar arcs = airborne early warning, crosshair = strike, T = training, crate = airlift, crate under a canopy = supply drop, waves = flood relief; the hover and card name the type ("Rescue · Trainer jet crash at Bidar"). Ground packages (ambulance, fire tender) use a vehicle glyph (top view with a windscreen), read en route / on scene / back and leaves / back, wait on scene, and "From Bidar · by road". **Package focus (D71):** a planner mission opened from step 4, or a click on a scripted flight, frames its base and target; the route is a dotted `--sim` line (round dots, 3 px, soft glow) to a 14 px `--sim` target ring; base and target names in bold `--text-1` above their marks; the aircraft are `--sim` glyphs, staggered behind the leader in the air (label "2 × Su-30MKI SIM" ahead of it) or lined up abreast ahead of the base badge before launch (base label "Halwara · 4 × Su-30MKI"); every other Ops layer fades to 25 %. The card: priority and mission, SIM, scenario name, Package, Status pill, Launch / lands (IST), a 4 px `--sim` progress bar, "Why:" reasons, "Open in Planner ›". |
| Top bar | adds Missions, Planner, Scenarios (not for viewers) and the **simulator clock** chip (§7.2): `SIM 14:32 ×60` in `--sim` | |
| Base panel → Overview | "Tasking today" rows, the "Outlook" (expected defects predicted per tail) and "Snag risk": the five riskiest serviceable tails here with their drivers; values ≥ 2× the base average in `--caution` text | `Row`, `ToneText`, `Sim` badge; always with the "decision support only" line |
| Planner → package detail | adds "Air-to-air refuelling" (tanker, times, rendezvous, tail, captain, sortie), predicted defect risk beside the tails, "Snag risk" and "Civil traffic" explanation rows; KPI strip adds "Expected defects" and "incl. N tanker sorties" | the swap modal lists each tail's predicted risk |
| Air tasking order (`/planner/ato/:id`) | title + DRAFT pill when not committed, base select, CSV, Print, back; one `.card` per package: details table (task, callsigns, tails, crew, times Zulu / IST, fuel and risk, tanker) beside a waypoint table (DEP / WPn / ARR, degrees-minutes, nearest place), then the planner's notes; "Not tasked" list | print stylesheet hides the chrome; cards avoid page breaks |
| Planner → Details & tools → Plan by hand (tab) | intro + "Start a timed session"; while running: KPI row (time, covered by hand, checks), one table row per mission with base · type and time selects and a verdict (`--ok` "Flies" / `--caution` reason); after Finish: the optimiser's result on the same snapshot; past sessions table | standard table, `Kpi`, `ToneText`, no new components |
| Planner → uncovered mission | split fixes carry an "Apply split" button (confirm dialog); parts show "Part of" in the explanation; dependents show "Depends on" | Missions table shows "needs X on station", "relief k of n · parent", "split into n …"; mission form adds "Needs AEW&C cover from" |
| Admin | "Snag-risk model" card: held-out sorties, AUC, top-10 % lift, Brier vs base rate, calibration table (gaps > 3 points in `--caution`), coefficients in words, retrain button | standard table, `Row`, no chart library |
| Overview | "Missions, next 24 hours": covered / requested by command and priority, values only (FR-CMD-04) | |

Priority vocabulary (urgency, always glyph + word): `■ P1` critical, `◆ P2` warning, `▲ P3` caution, `— P4` neutral.
Change vocabulary: `— Kept`, `○ Tails / crew swapped`, `▲ Moved`, `● New`, `■ Dropped`, `◆ Divert`, `◆ Re-roled in flight`.

Timeline: tanker legs are separate bars on the tanker's base row with a dotted outline on `--surface-1`; package bars
dashed when changed. Ops map: tanker tracks dotted `--sim` (`ops-routes-support`). Keyboard: timeline bars, clickable
rows (`Row` with `onClick`, table rows in Overview / Pilots) take focus and activate on Enter or Space; a focused
bar gets an `--accent` outline; modals move focus in, keep Tab inside and return it to the opener on close.
