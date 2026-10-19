# PRD: IAF Air Operations Common Operating Picture & Inventory System (Phase 1)

> **Update 2026-10-16:** the map engine is now **MapLibre GL** (flat map), the theme is navy + neon blue with the official IAF crest, and the tick simulator is switched off for Phase 1. See ARCHITECTURE §18 D19–D21. Where this document still describes CesiumJS, Cesium ion, the olive/amber theme or live simulation on the map, D19–D21 take precedence.


| | |
|---|---|
| Hackathon | Smart India Hackathon 2026 |
| Problem statement | **SIH26250**: Air Power: Dynamic Air Operations & Resource Optimisation |
| Organisation | Ministry of Defence (MoD), Defence Services Staff College |
| Category / theme | Software / Transportation & Logistics |
| Product codename | `iaf-airops` (placeholder) |
| Doc status | Draft v0.1, 2026-10-16 |
| Related docs | [DATA_MODEL](DATA_MODEL.md) · [ARCHITECTURE](ARCHITECTURE.md) · [API](API.md) · [DESIGN_SYSTEM](DESIGN_SYSTEM.md) · [IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md) · [AGENTS.md](../AGENTS.md) |

---

## 1. Overview

### 1.1 Problem statement (summary of SIH26250)
Planning and re-tasking air operations is complex in contested, fast-changing environments. The data needed for it sits across separate systems, including:

- aircraft availability
- crew status
- weapon loads
- airspace
- weather
- threats
- mission priorities

There is no common, real-time decision-support picture. Planning takes longer, and scarce air power is used poorly. No official dataset is provided.

### 1.2 What we build in Phase 1
Phase 1 is a single place where planners can see the real-time state of air power.

1. **A synthetic but realistic dataset.** Real public base locations and the public order of battle (ORBAT), with every operational number generated and visibly labelled **SIMULATED**.
2. **An inventory management system of record.** Full CRUD with roles and an audit trail.
3. **A dark, military-grade dashboard around a 3D map** of the Indian subcontinent and its neighbours. It has:
   - a live air picture
   - weather
   - terrain
   - infrastructure layers
   - a base drill-down side panel
   - command overview, inventory, pilot and alert screens
4. **A live tick simulator.** It makes the picture move: sorties launch and recover, fuel burns, crews rotate, aircraft go in and out of maintenance.

> Phase 2 (decision support built on this data) is specified in §17 and built per [PHASE2_IMPLEMENTATION_PLAN](PHASE2_IMPLEMENTATION_PLAN.md).

### 1.3 Why this matters to judges
Phase 1 fuses six of the seven data categories in the problem statement into one view (mapping in §12). It also produces the clean, structured, live data foundation any later decision-support layer needs.

---

## 2. Scope

### 2.1 In scope
- Synthetic data generation, deterministic and seeded (see [DATA_MODEL §8](DATA_MODEL.md#8-synthetic-data-generation-spec)).
- Inventory CRUD for every own-force entity, with role-based access control (RBAC), optimistic locking and an audit log.
- **3D map**:
  - region-locked to South Asia
  - India's boundaries as officially depicted by the Government of India
  - states and districts appear as you zoom in
  - place labels
- **Map layers**:
  - air bases (IAF, neighbours, other Indian military)
  - airstrips and advanced landing grounds (ALGs)
  - civil airports
  - radars
  - air defence (AD) batteries / interceptors
  - comms infrastructure
  - roads and railways
- **Live air picture**: real ADS-B plus simulated IAF tracks and simulated unknown tracks, with category toggles.
- **Weather**: METAR/TAF, point forecast, overlay tiles, animated wind and IR clouds.
- **Terrain view**: tilt, click an area for a close-up, elevation readout.
- **Screens**: base side panel, command overview, inventory tables and forms, pilot profiles, alerts, audit log, admin.
- **Live tick simulator** pushing updates over WebSocket.

### 2.2 Out of scope (Phase 1)
- ~~Any decision-support, scoring, ranking, recommendation or predictive logic.~~ In scope since Phase 2 (§17). Overview screens stay values-only.
- Real, classified or operational data; integration with any real IAF/MoD system.
- Inventory for foreign forces. Neighbour bases show public information only.
- Weapon loadouts and store-compatibility rules. Phase 1 holds generic armament stock only.
- Air traffic control, flight-plan filing, NOTAM authoring.
- Mobile apps, multi-tenant cloud scale, Hindi localisation.

---

## 3. Goals and non-goals

| ID | Goal | Measured by |
|---|---|---|
| G1 | One fused view of the problem statement's data categories | 6/7 categories visible on map + panels (§12) |
| G2 | Answer readiness questions fast | Each scripted question in §11 answered in < 30 s |
| G3 | Trustworthy system of record | 100% of create/update/delete (CUD) and simulator changes audited; role matrix tests pass |
| G4 | Believable live picture | Simulator soak test: 0 invariant violations; tracks launch/recover at the right bases |
| G5 | Defence-grade presentation | Official GoI borders; dark military theme; APP-6 symbology; SIMULATED always visible |
| G6 | Built for extension | Clean schema and API; every entity has typed endpoints |

**Non-goals:**
- photorealistic 3D cities
- world-wide coverage
- real-time collaboration (co-editing)
- weapon effects or engagement simulation
- i18n

---

## 4. Users, roles and permissions

### 4.1 Personas mapped to roles

| Persona | Role | Main jobs |
|---|---|---|
| Air Ops staff officer (Wg Cdr) at Air HQ or a Command HQ | `COMMAND_HQ` | Theatre and command KPIs, base drill-down, alert acknowledgement, audit review |
| Station Commander (Gp Capt) of an Air Force Station | `BASE_COMMANDER` | Keep own-base inventory, crew, pilots and sorties current |
| Exercise controller / system administrator (directing staff) | `ADMIN` | Users, reseeding, simulator controls, everything else |
| Student officer / SIH judge / observer | `VIEWER` | Explore the map and screens read-only |

A `COMMAND_HQ` user has an optional `command_id`:
- **Null** means Air HQ: they can see and acknowledge everything.
- **Set** means they still read everything, but can acknowledge only that command's alerts.

### 4.2 Permission matrix

| Capability | ADMIN | COMMAND_HQ | BASE_COMMANDER | VIEWER |
|---|---|---|---|---|
| Map, live air, weather, terrain | ✔ | ✔ | ✔ | ✔ |
| Command overview | ✔ | ✔ | ✔ | ✔ |
| Base side panel (read) | ✔ | ✔ | ✔ | ✔ |
| Inventory tables (read) | ✔ | ✔ | ✔ | ✔ |
| Inventory create / update / delete | ✔ all | ✘ | ✔ own base only | ✘ |
| Pilot profiles (read) | ✔ | ✔ | ✔ | ✔ |
| Pilot edit | ✔ | ✘ | ✔ pilots posted to own base | ✘ |
| Sortie create / edit / cancel | ✔ | ✘ | ✔ own-base sorties | ✘ |
| Alerts (read) | ✔ | ✔ | ✔ | ✔ |
| Alert acknowledge | ✔ | ✔ (own command, or all if Air HQ) | ✔ own base *(proposed)* | ✘ |
| Audit log (read) | ✔ | ✔ | ✔ own base *(proposed)* | ✘ |
| CSV export | ✔ | ✔ | ✔ *(proposed)* | ✘ *(proposed)* |
| User management | ✔ | ✘ | ✘ | ✘ |
| Simulator controls (pause, speed, reseed) | ✔ | ✘ | ✘ | ✘ |

Cells marked *(proposed)* were not explicitly decided. They are listed in §14.

---

## 5. Demo narrative (the 6-minute story)

1. Log in as **Command HQ (Air HQ)**. The login card states that all operational data is simulated.
2. **Command overview**. Western Air Command shows an amber serviceability KPI. Open the alert list: "Fuel below reserve" at one station.
3. Click the base. The map flies to it, region-locked, with official borders and district labels appearing as we zoom.
4. The **side panel** shows:
   - jets by type and status
   - QRA posture
   - crew availability
   - fuel gauge below its reserve line
   - SAM and radar coverage rings on the map
5. Switch to **Live**:
   - real civil traffic over India
   - the military toggle
   - simulated IAF sorties as exercise symbols
   - a simulated **unknown** track approaching the border. It triggers a **QRA scramble**, and the interceptor launches from the nearest QRA base.
6. **Weather** mode:
   - METAR flight-category rings at bases; one base is IFR.
   - Click any point for a forecast.
   - Turn on wind streamlines.
7. **Terrain** mode: tilt, then click near Leh for a 3D close-up of high-altitude terrain.
8. Switch user to **Base Commander**. Mark an aircraft unserviceable, then create a sortie. Show the **audit diff**.
9. The simulator flies the new sortie. Panels update live.

---

## 6. User stories

**MAP**
- As any user, I want India's boundaries as officially depicted, so that the product is acceptable to MoD reviewers.
- As any user, I want states, then districts, and place names to appear as I zoom, so that I know where I am around a base.
- As any user, I want to search a base by name or ICAO code and fly to it.
- As any user, I want to toggle layer groups and see counts, so that the map stays readable.

**LIVE**
- As a staff officer, I want to filter air traffic by category (civil, cargo, military, helicopter, UAV, drone, simulated IAF), so that I see only what matters.
- As a staff officer, I want real feeds clearly separated from simulated tracks, so that I never confuse them.
- As a staff officer, I want to know when a feed is stale or down.

**WX**
- As a station commander, I want my base's current METAR/TAF and flight category at a glance.
- As a planner, I want a forecast for any clicked location, including winds aloft, cloud and visibility.
- As a planner, I want animated wind and cloud overlays for the region.

**TER**
- As a planner, I want to tilt the map and inspect terrain around a high-altitude landing ground in 3D.

**BASE**
- As a staff officer, I want one panel that shows a base's whole readiness picture: aircraft, crew, fuel, defences and infrastructure.

**INV**
- As a station commander, I want to update aircraft, crew, fuel and equipment records for my base, with validation, so that the picture stays accurate.
- As a staff officer, I want filterable tables and CSV export.

**PIL**
- As a station commander, I want a pilot's flying hours, qualifications, currency, medical status and fatigue before tasking them.

**CMD**
- As Air HQ, I want to compare readiness across the five operational commands.

**ALR**
- As any user, I want alerts for low fuel, low serviceability, QRA shortfall and crew fatigue, so that problems surface without searching.
- As Command HQ, I want to acknowledge alerts and see who changed what.

**AUTH**
- As an admin, I want role-scoped accounts, so that each user edits only what they own.

**SIM**
- As an exercise controller, I want to pause, speed up or reseed the simulation.

---

## 7. Functional requirements

Priority: **M** = must, **S** = should, **C** = could. Entities are defined in [DATA_MODEL](DATA_MODEL.md).

### FR-MAP: map shell, boundaries, layers

| ID | P | Requirement |
|---|---|---|
| FR-MAP-01 | M | CesiumJS 3D globe opens framed on India. The camera is locked to **60°E–105°E, 0°N–42°N**: render limit rectangle, camera clamp, maximum zoom-out distance. |
| FR-MAP-02 | M | Area outside the region renders as the background colour. Imagery and terrain requests are limited to the region. |
| FR-MAP-03 | M | Basemap: Esri World Imagery, darkened and tinted per the theme (default). Alternatives: raw Esri; Cesium's bundled offline NaturalEarthII. No third-party labelled or bordered basemaps (no Bing labels, no OSM-rendered tiles). |
| FR-MAP-04 | M | India's external boundary per the official Government of India / Survey of India depiction is always on. Neighbour country outlines are always on. |
| FR-MAP-05 | M | India states/UTs appear below ~4,000 km camera height, and districts below ~800 km. |
| FR-MAP-06 | M | Neighbour first- and second-level divisions (ADM1/ADM2) appear below ~3,000 km and ~600 km respectively. They are clipped so no neighbour polygon overlaps India's official territory. |
| FR-MAP-07 | M | Place labels are ranked by population and shown progressively with zoom. Labels are always shown around the selected base and the viewport centre. At most 150 labels on screen. |
| FR-MAP-08 | M | Layer panel: groups, per-layer toggle, live count, opacity (for overlays), legend. State persists per user in localStorage. |
| FR-MAP-09 | M | HUD strip: cursor lat/lon (DD and DMS), camera altitude, **IST clock (primary) + Zulu clock**, simulator clock, feed-status chips. |
| FR-MAP-10 | M | Search (base name, ICAO, tail number, pilot) flies to the result. Targets outside the region are rejected. |
| FR-MAP-11 | M | Mode switcher: **Live / Weather / Terrain**. Only the active mode's heavy layers run. Static layers stay available in every mode. |
| FR-MAP-12 | M | Clicking an IAF base opens the base side panel (FR-BASE). Clicking any other feature opens an info card. |
| FR-MAP-13 | M | Static layers as specified in [ARCHITECTURE §10](ARCHITECTURE.md#10-map-layer-specification): IAF bases, ALGs/airstrips, neighbour air bases, other Indian military air stations, civil airports, radars with coverage rings, AD batteries with engagement rings, OSM telecom towers, synthetic military comms nodes, roads, railways. |
| FR-MAP-14 | M | Neighbour air bases use APP-6 **hostile** frames for Pakistan and China and **neutral** frames for other countries. Their cards show public information only, with the note "Public information only — no inventory held". |
| FR-MAP-15 | M | Navy, Army Aviation and Coast Guard air stations appear as "Other Indian military" markers with a public-info card and no inventory. |
| FR-MAP-16 | M | A credits panel lists every data source, licence and attribution string ([API §10](API.md#10-attribution-strings)). |
| FR-MAP-17 | S | Infra has a temporary Connectivity focus toggle for a selected IAF base. It hides unrelated layers and inventory, lays the map flat, and shows the source and four nearby public IAF bases, ordered by direct distance. Selecting a destination keeps the source selected; Direct shows geographic arcs, while Shortest road route requests a distance-based public-road estimate on demand. Fit connections frames the endpoints. Both normal and satellite backgrounds support focus; the existing saved Satellite imagery preference remains editable without clearing connections. Exit, changing view, clearing/changing the source, or leaving the map restores ordinary layers and the saved tilt without rewriting preferences. Road-network endpoints are distinguished from unverified base-access connectors; failures never invent a road route. |

### FR-LIVE: live air picture

| ID | P | Requirement |
|---|---|---|
| FR-LIVE-01 | M | The backend fetches real ADS-B for the region. It **queries adsb.lol and adsb.fi in parallel and merges the results, de-duplicated by hex**; their coverage over India differs widely (see [API §1](API.md#1-live-aircraft)). OpenSky provides a theatre-wide snapshot and fallback. airplanes.live is optional, only if access is granted. Query strategy: viewport point queries plus the global military feeds, filtered to the region. |
| FR-LIVE-02 | M | All providers are normalised to one track schema ([ARCHITECTURE §6](ARCHITECTURE.md#6-live-air-subsystem)). |
| FR-LIVE-03 | M | Each track gets one display category. Precedence: **Simulated IAF > Simulated Unknown > Military > UAV > Drone > Helicopter > Cargo > Civilian**. |
| FR-LIVE-04 | M | Toggles with live counts: Civilian, Cargo, Military, Helicopters, UAVs (fixed-wing), Drones (small/rotary), Simulated IAF, Simulated Unknowns. If a category has no source data, it says "0 — not broadcast on public ADS-B" rather than hiding the toggle. |
| FR-LIVE-05 | M | Track card fields: callsign, registration, type and operator (from adsbdb enrichment, fetched on click), altitude, ground speed, heading, squawk, source, age. Emergency squawks 7500/7600/7700 are highlighted. |
| FR-LIVE-06 | M | Staleness: tracks fade at 60 s and are removed at 120 s. Feed chip shows LIVE / STALE / OFF per provider. |
| FR-LIVE-07 | M | Simulated IAF tracks arrive over WebSocket. They use the APP-6 exercise-friend symbol and a SIM tag. Clicking one opens its sortie, aircraft and crew. |
| FR-LIVE-08 | M | Simulated unknown tracks use the APP-6 exercise-unknown symbol and a SIM tag. They approach no closer than the configured border buffer and never cross into Indian territory. |
| FR-LIVE-09 | S | Implemented for selected live aircraft: last 120 observed positions per hex, retained in memory since the server first saw the aircraft and expired with the track. A solid trail joins the last recorded position to the dead-reckoned icon. Selection highlights the icon; clearing selection, changing view, leaving the map or losing the track removes the path. Where adsbdb supplies both airport coordinates, a distinct dashed great-circle leg to the scheduled destination is labelled as schedule data that may differ from actual. No upstream history or filed flight plan is implied. |
| FR-LIVE-10 | M | API keys and credentials live on the server only. Provider order and poll intervals are configurable. |
| FR-LIVE-11 | C | Record ADS-B snapshots to disk and replay them, for unreliable networks. |

### FR-WX: weather view

| ID | P | Requirement |
|---|---|---|
| FR-WX-01 | M | METAR/TAF for all reporting stations in the region, refreshed every 5 min. Base symbols get a flight-category ring (VFR/MVFR/IFR/LIFR). The base Weather tab shows raw and decoded METAR/TAF. Bases without their own METAR (most Air Force-only stations) fall back to the nearest METAR within 50 km, then to Open-Meteo, and the fallback is labelled. |
| FR-WX-02 | M | Click anywhere in Weather mode for a popover with the Open-Meteo forecast: current conditions plus 48 h of temperature, wind/gusts, winds at 850/700/500/300 hPa, low/mid/high cloud, visibility, precipitation, freezing level. |
| FR-WX-03 | M | OpenWeatherMap tile overlays: clouds, precipitation, wind, temperature, pressure. One overlay at a time, opacity slider, tiles fetched through a backend proxy (the key never reaches the browser). |
| FR-WX-04 | M | Animated wind streamlines from NOAA GFS (default) or ECMWF IFS, served by the wind sidecar (port of God's Eye). |
| FR-WX-05 | M | Global infrared cloud mosaic overlay (NOAA nowCOAST). |
| FR-WX-06 | M | Every weather layer shows its source, valid time and legend. |
| FR-WX-07 | S | Below-minima weather at a base raises a `WX_BELOW_MINIMA` alert. |
| FR-WX-08 | M | Zoom in and out freely within the region. Overlays keep their resolution limits and show a notice past their maximum zoom. |

### FR-TER: terrain view

| ID | P | Requirement |
|---|---|---|
| FR-TER-01 | M | Terrain mode turns on 3D terrain. Provider order: Cesium ion World Terrain (free token) → Re:Earth keyless terrain → flat ellipsoid (with a notice). |
| FR-TER-02 | M | **Map angle** setting in Map settings (D58): Tilted (oblique) ↔ Straight (top-down, north-up). Free tilt with the right-drag or Ctrl-drag gesture while Tilted; Straight locks the map flat. |
| FR-TER-03 | M | Clicking the map flies to an oblique close-up of a ~30 km box around the clicked point. |
| FR-TER-04 | M | Elevation readout under the cursor and at the clicked point (m and ft). |
| FR-TER-05 | S | Vertical exaggeration 1×–3×. |
| FR-TER-06 | M | Camera never goes below the terrain surface. "Back" returns to the previous view. |

### FR-BASE: base side panel (IAF bases)
The full field list, mapped to your element list, is in §8.

| ID | P | Requirement |
|---|---|---|
| FR-BASE-01 | M | Header: station name, ICAO, command, wing, base type, coordinates, elevation, operational status, METAR flight category, SIMULATED stripe. |
| FR-BASE-02 | M | Fixed-wing jets grouped by class (fighter, trainer, transport, tanker, AEW&C, ISR/special), then by type × status; serviceability %. |
| FR-BASE-03 | M | Aircraft capacity: hardened aircraft shelters (HAS), hangars, aprons and helipads, as total vs occupied slots by size class. |
| FR-BASE-04 | M | Crew status and availability: aircrew by duty status (on duty, standby, QRA, airborne, crew rest, off duty, leave, sick, course); available-to-fly count; fatigue flags. |
| FR-BASE-05 | M | Standby: aircraft on standby and **QRA posture** (required vs actual, readiness minutes, QRA crews matched). |
| FR-BASE-06 | M | Ground support: vehicles and ground-support equipment (GSE) by type and serviceability; ground-support crew strength by trade and shift. |
| FR-BASE-07 | M | Ground artillery / air defence: AD guns and SAM batteries protecting the base (system, launchers ready / total, status, readiness). |
| FR-BASE-08 | M | Radar systems at or near the base (type, status, range). |
| FR-BASE-09 | M | Fuel: capacity, current level, % gauge with reserve line, and days of supply, per grade (ATF, AVGAS, diesel); last 10 transactions. |
| FR-BASE-10 | M | Infrastructure status: runways (count, designators, length, status), nearby ALGs/airstrips, interceptors (QRA jets + AD batteries), warehouses (count, utilisation, low-stock items, generic armament stock). |
| FR-BASE-11 | M | Helicopters, UAVs and drones sections, same structure as jets. |
| FR-BASE-12 | M | Pilots: list of pilots and other aircrew posted to the base, linking to profiles. |
| FR-BASE-13 | M | Sorties airborne now, and the next launches. |
| FR-BASE-14 | M | Tabs: **Overview \| Aircraft \| Crew \| Support \| Defence \| Fuel & Stores \| Infra \| Weather**. |
| FR-BASE-15 | M | The panel refreshes live from WebSocket events without losing scroll position or active tab. |
| FR-BASE-16 | M | Edit actions appear only where the user's role allows (§4.2). |
| FR-BASE-17 | M | Neighbour and other-military bases open a read-only public card instead (FR-MAP-14/15). |
| FR-BASE-18 | M | The panel opens in < 500 ms. |

### FR-INV: inventory management

| ID | P | Requirement |
|---|---|---|
| FR-INV-01 | M | One table per entity: aircraft, aircrew, ground crew strength, ground assets, fuel storage, fuel transactions, warehouses and stock, AD batteries, radars, comms nodes, runways, parking, squadrons, sorties, missions. Server-side paging, sort, filter (base, command, type, status) and search. Navigation groups these tables into Fleet, Personnel, Operations, Logistics & support, Defence & communications, and Bases & infrastructure; only the active category's sections are shown. Existing entity URLs and permissions remain unchanged. |
| FR-INV-02 | M | Create and edit forms with server validation messages. Site entities get a map point-picker. |
| FR-INV-03 | M | Delete asks for confirmation. If other records reference the item, delete is blocked and **Retire** is offered instead. |
| FR-INV-04 | M | Role scoping per §4.2, enforced server-side. |
| FR-INV-05 | M | Every create, update and delete, and every simulator mutation, writes an audit row (before/after diff) in the same transaction. |
| FR-INV-06 | M | Optimistic locking via a `version` field. A conflict (HTTP 409) shows "Changed by simulator/user — reload". |
| FR-INV-07 | S | CSV export of the filtered view, with a `# SIMULATED DATA` header line. |
| FR-INV-08 | M | Tables refresh when the WebSocket reports changes. |
| FR-INV-09 | M | Validation rules: <br>• fuel current ≤ capacity <br>• inventory only at own-side bases <br>• unique tail numbers <br>• aircraft type matches the squadron <br>• no status edit while an aircraft is airborne <br>• the full list is in [DATA_MODEL §6](DATA_MODEL.md#6-integrity-rules-and-invariants) |
| FR-INV-10 | M | Sortie CRUD for authorised roles. A human-created sortie goes through the same lifecycle as simulator-generated ones, and the simulator flies it (FR-SIM-03). Validation rejects unserviceable aircraft, unavailable crew and routes that come within the border buffer. |
| FR-INV-11 | S | Inventory → Aircraft opens on one card per aircraft type that has aircraft (picture, total, serviceable, QRA, maintenance, U/S, status bar), honouring the base and command filters. A card opens that type's aircraft table (breadcrumb Inventory › Aircraft › type, back to the cards) with the usual search, filters, CSV export, create, edit, retire and delete. Counts refresh with every aircraft change. |

### FR-PIL: pilot profiles

| ID | P | Requirement |
|---|---|---|
| FR-PIL-01 | M | Pilot / aircrew list with filters: base, squadron, type, rank, duty status, medical status, currency. |
| FR-PIL-02 | M | Identity: **fictional** name, rank, service number, callsign, squadron, stream, SIM badge, initials avatar. No photos. |
| FR-PIL-03 | M | Experience: <br>• total hours, by type <br>• day / night / instrument hours <br>• captain hours <br>• hours in the last 30, 90 and 365 days |
| FR-PIL-04 | M | Qualifications with award and expiry dates, e.g. QFI, night, NVG, aerial refuelling, formation lead, mountain flying. |
| FR-PIL-05 | M | Currency per type (current / lapsing ≤ 7 d / lapsed), with the rule shown. |
| FR-PIL-06 | M | Sortie history (paged): date, type, mission, duration, position. |
| FR-PIL-07 | M | Medical category and validity, duty status, fatigue (hours in last 24 h / 7 d / 30 d, rest since last duty). |
| FR-PIL-08 | M | Posting history timeline (career path: training types to current type). |
| FR-PIL-09 | M | Edit is role-scoped (§4.2). |

### FR-CMD: command overview

| ID | P | Requirement |
|---|---|---|
| FR-CMD-01 | M | KPI tiles for the theatre and for each operational command: **WAC, SWAC, CAC, EAC, SAC**. A separate strip covers Training Command and Maintenance Command. |
| FR-CMD-02 | M | KPIs: <br>• bases <br>• aircraft and serviceable % <br>• airborne now <br>• QRA posture met (x / y) <br>• aircrew available <br>• bases below fuel reserve <br>• radar / AD operational % <br>• open alerts by severity |
| FR-CMD-03 | M | Clicking a command flies the map to its bases and filters the inventory tables. |
| FR-CMD-04 | M | Per-base KPI table, sortable by any column. It shows values only, with no composite scores. |
| FR-CMD-05 | S | 24 h trend sparklines from KPI snapshots. |

### FR-ALR: alerts and audit

| ID | P | Requirement |
|---|---|---|
| FR-ALR-01 | M | Alert rules are evaluated every simulator tick. Thresholds are in config ([DATA_MODEL §9.4](DATA_MODEL.md#94-alert-rules-and-default-thresholds)). |
| FR-ALR-02 | M | Alert list with filters (severity, kind, command, base, status). Duplicates are merged. Alerts clear automatically when the condition resolves. |
| FR-ALR-03 | M | Acknowledgement per §4.2. |
| FR-ALR-04 | M | A toast appears for WARNING and above. A counter badge in the top bar shows open alerts. |
| FR-ALR-05 | M | Map: an alert halo on the base symbol, coloured by highest severity. |
| FR-ALR-06 | M | Audit log view: filters (actor incl. `SIMULATOR`, entity, base, action, time) and a before/after diff viewer. |
| FR-ALR-07 | M | The audit log is append-only, enforced in the database. |

### FR-AUTH: authentication and authorisation

| ID | P | Requirement |
|---|---|---|
| FR-AUTH-01 | M | Username/password login. Seeded demo users for each role ([DATA_MODEL §8.14](DATA_MODEL.md#814-demo-users)). |
| FR-AUTH-02 | M | Passwords hashed with Argon2id. Session is a JWT in an httpOnly, SameSite=Strict cookie with an 8 h expiry. Logout supported. |
| FR-AUTH-03 | M | Role checks on every API route, server-side. The UI hides disallowed actions, but the server is authoritative. |
| FR-AUTH-04 | M | Base Commander scope: own base's assets, pilots posted there, and that base's sorties. |
| FR-AUTH-05 | S | Lockout for 15 min after 5 failed logins. |
| FR-AUTH-06 | M | Admin user management (create, disable, reset password, assign role, base and command). |
| FR-AUTH-07 | M | WebSocket connections are authenticated with the session cookie at handshake. |
| FR-AUTH-08 | M | The login page shows the SIMULATED-data disclaimer. |

### FR-SIM: live tick simulator

| ID | P | Requirement |
|---|---|---|
| FR-SIM-01 | M | In-process ticker every `SIM_TICK_SECONDS` (default 5 s). Speed 1×/10×/60×. Admin can pause, single-step and reseed. |
| FR-SIM-02 | M | Generates a **daily flying programme** of sorties per squadron at sim midnight. |
| FR-SIM-03 | M | Sortie lifecycle (simulator- and human-created alike): PLANNED → CREWED → READY → AIRBORNE → ON_STATION → RTB → LANDED → COMPLETED. CANCELLED and ABORTED are possible, each with a reason. |
| FR-SIM-04 | M | Fuel burns while airborne. Turnarounds refuel from base storage, with a transaction. Bowser and convoy replenishment arrives after a lead time. |
| FR-SIM-05 | M | Crew follow shifts, crew rest after landing and fatigue counters. Rare leave and sickness events. |
| FR-SIM-06 | M | Maintenance: hours accumulate. Aircraft move to scheduled maintenance when due, and snags cause unscheduled maintenance. Out-of-stock spares cause AOG (aircraft on ground awaiting parts). Repairs complete back to AVAILABLE. |
| FR-SIM-07 | M | QRA posture is kept up to date. A **simulated unknown track** spawns occasionally outside the border, heads toward it and turns away at the buffer. It triggers a QRA scramble from the nearest QRA base, which intercepts, escorts and recovers. |
| FR-SIM-08 | M | Random faults on radar, AD and comms, with repair times. |
| FR-SIM-09 | M | Each tick evaluates alerts and writes audit rows (actor `SIMULATOR`). |
| FR-SIM-10 | M | WebSocket deltas carry sequence numbers. On a gap, the client resyncs over REST. |
| FR-SIM-11 | M | Deterministic for the same seed and tick count when there are no human edits. |
| FR-SIM-12 | M | The simulator clock is shown separately from the real clock. |

---

## 8. Base side panel: field checklist
Your required elements, mapped to where each is shown and the entity it comes from.

| Required element | Panel location | Source (DATA_MODEL) |
|---|---|---|
| Number of jets and their classification | Overview, Aircraft | `aircraft` × `aircraft_type.role` |
| Capacity of jets | Overview, Infra | `parking_facility` (slots by size) vs occupancy view |
| Crew status and availability | Overview, Crew | `aircrew.duty_status`, `v_aircrew_availability` |
| Crew standby | Crew | `aircrew.duty_status = STANDBY/QRA`, `duty_roster_entry` |
| Aircraft standby | Overview, Aircraft | `aircraft.status = STANDBY/QRA`, `qra_posture` |
| Ground support: vehicles | Support | `ground_asset (asset_class = VEHICLE)` |
| Ground support crew | Support | `ground_crew_strength` |
| Ground artillery | Defence | `air_defence_battery` (category AD_GUN / VSHORADS) |
| Radar systems | Defence | `radar_site` |
| Fuel capacity of the base | Overview, Fuel & Stores | `fuel_storage.capacity_l / current_l` |
| Infrastructure: airstrips | Infra | `runway`, nearby `base (base_type = ALG)` |
| Infrastructure: artillery | Defence, Infra | `air_defence_battery` |
| Infrastructure: interceptors | Defence, Overview | `qra_posture` + QRA aircraft + SAM batteries |
| Infrastructure: warehouses | Fuel & Stores | `warehouse`, `stock_level` (incl. generic armament) |
| Pilot history and information | Crew, then Pilot profile | `aircrew`, `aircrew_type_hours`, `aircrew_qualification`, `aircrew_posting`, `sortie_crew` |
| Helicopters | Aircraft (Rotary) | `aircraft` where `category = ROTARY_WING` |
| UAVs | Aircraft (UAV) | `aircraft` where `category = UAV_FIXED_WING` |
| Drones | Aircraft (UAV) | `aircraft` where `category = UAV_ROTARY_SMALL` |
| Weapon stock (problem-statement category) | Fuel & Stores | `stock_item.category = ARMAMENT_*` (generic) |

---

## 9. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance (reference: 16 GB laptop, Chrome) | Map interactive in < 5 s; ≥ 30 fps with ≤ 3,000 live tracks and all static layers on; side panel < 500 ms; API p95 < 200 ms; WebSocket delta < 1 s after a tick; database seed < 2 min |
| Availability | If an upstream feed fails, the app keeps working: stale-while-error caching, feed chips show the state, no blank screens |
| Network | Internet is assumed at the demo. Offline mode (bundled basemap, ellipsoid terrain, ADS-B replay, cached weather) is a **could** item |
| Security | <br>• Secrets only in env <br>• No provider keys in the frontend bundle, except the Cesium ion token, which is public by design and URL-restricted <br>• CORS allow-list and CSP header <br>• Parameterised SQL via the ORM <br>• Least-privilege DB role <br>• Append-only audit <br>• Pinned dependencies <br>• No telemetry |
| Data sensitivity | <br>• All people fictional <br>• Every synthetic value carries `is_simulated` and is visibly labelled <br>• No foreign inventory <br>• Synthetic sites are never derived from OSM `military=*` data <br>• No real classification markings |
| Accessibility | <br>• WCAG 2.1 AA contrast for text <br>• Full keyboard access to panels, tables and forms <br>• Status never shown by colour alone (shape + text) <br>• `prefers-reduced-motion` respected <br>• Tables give a non-visual alternative to the map |
| Compatibility | Chrome/Edge (WebGL2); 1366×768 minimum, 1920×1080 primary |
| Licences | `THIRD_PARTY_NOTICES.md` with every ported file and dataset; credits panel in the UI |
| Maintainability | Typed API (OpenAPI → TS types); one schema source; tests per [AGENTS.md](../AGENTS.md) |

---

## 10. Acceptance criteria (Given / When / Then)

- **Borders**:
  - Given any zoom level, the whole of Jammu & Kashmir, including PoK, Gilgit-Baltistan and Aksai Chin, and the whole of Arunachal Pradesh render inside India.
  - No neighbour ADM polygon intersects the India polygon (SQL test).
- **Region lock**: given a drag or zoom attempt, the camera centre cannot leave 60–105°E / 0–42°N.
- **Base panel**: given any IAF base, every row in §8 is present and populated, and the SIMULATED stripe is visible.
- **RBAC**: the role × action × entity matrix test passes for all cells in §4.2.
- **Audit**: every create, update or delete through the API produces exactly one audit row with a correct before/after diff.
- **Sortie CRUD**: given a Base Commander creates a sortie for an available aircraft and crew, then the simulator launches it at the planned time, a track appears, and it recovers at the recovery base.
- **Simulator soak**: given 60 simulated minutes at 60×, then there are 0 invariant violations ([DATA_MODEL §6](DATA_MODEL.md#6-integrity-rules-and-invariants)).
- **Unknown track**: given a simulated unknown spawns, then a QRA scramble launches from the nearest base with QRA met. The unknown never crosses the border buffer.
- **Live air**: given adsb.lol is down, then tracks continue from adsb.fi (and OpenSky) within one poll cycle, and the adsb.lol chip shows OFF.
- **Weather**: given an Air Force-only base without a METAR, then the Weather tab shows the nearest-station METAR with a "nearest: XXXX, NN km" label.
- **Secrets**: a grep of the production JS bundle finds no OWM, OpenSky or other provider key.

---

## 11. Success metrics for judging
- Five scripted questions each answered in < 30 s from login, for example:
  1. "How many serviceable Su-30MKI are in WAC right now?"
  2. "Which bases are below fuel reserve?"
  3. "Is QRA met at every border base in EAC?"
  4. "Which pilots at Station X are current on type and rested?"
  5. "What is the weather and flight category at Leh?"
- Problem-statement categories covered: 6 of 7 (§12).
- Live public sources integrated: about 8 (ADS-B ×2–3, adsbdb, METAR/TAF, Open-Meteo, OWM, GFS/IFS, nowCOAST IR).
- Synthetic scale: about 60 IAF stations, about 1,400 aircraft, about 3,000 aircrew, 90 days of sortie history.
- 0 invariant violations in the soak run; 100% of mutations audited.

---

## 12. Problem-statement categories vs Phase-1 coverage

| Problem-statement category | Phase-1 coverage |
|---|---|
| Aircraft availability | Aircraft status, serviceability %, standby/QRA, parking occupancy, maintenance due |
| Crew status | Aircrew duty/medical/currency/fatigue, duty roster, ground-crew strength |
| Weapon loads | Generic loadouts per aircraft (category counts), reserved from base stock when a plan is committed (Phase 2, D30) |
| Airspace | Live ADS-B picture, civil airports, radar and SAM coverage rings, region lock |
| Weather | METAR/TAF, point forecast, OWM overlays, GFS/IFS wind, IR clouds, below-minima alerts |
| Threats | Neighbour air bases (hostile/neutral symbology), live military ADS-B, simulated unknown tracks and QRA response, own AD/radar coverage |
| Mission priorities | Mission requests P1–P4 with windows, areas and requirements; the planner covers them lexicographically by priority (Phase 2) |

---

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Military aircraft, UAVs and drones rarely broadcast ADS-B over India | Live toggles look empty | Simulated IAF tracks; honest "0 — not broadcast" counts; explain in demo |
| Border depiction (Criminal Law Amendment Act 1961; National Geospatial Policy 2022) | Disqualification or embarrassment | <br>• GoI depiction only (DataMeet `india-soi`/composite) <br>• Neighbour polygons clipped <br>• No third-party border or label layers <br>• Boundary acceptance tests |
| Real public ORBAT, real AD system names and per-country hostile symbology in an MoD context | Perceived as collating sensitive information or as politically pointed | <br>• Open sources only, with a source URL per row <br>• All placements and numbers synthetic and labelled <br>• No real serials of specific airframes <br>• **Confirm acceptability with organisers before the finale** |
| Rate limits and non-commercial terms (OpenSky, adsb.fi, Cesium ion, OWM) | Throttling during demo | Caching, request coalescing, Retry-After backoff, viewport-driven queries, failover chain |
| **Network firewalls** (the team's campus FortiGate blocks `terrain.reearth.land`; it may block others) | Terrain or feeds missing on site | Cesium ion terrain first; ellipsoid fallback; feed failover; pre-demo network check script |
| METAR gaps at Air Force-only stations | Empty weather tab | Nearest-station and Open-Meteo fallback with a label |
| Cesium performance with district polygons | Low fps | Pre-simplified geometry per zoom bucket; primitives over entities; label budget |
| React StrictMode double-mounting the Cesium Viewer | Leaks, duplicate viewers | Single viewer owner with idempotent init/destroy |
| Simulator vs human edit conflicts | Lost updates | `version` column, 409, the simulator retries next tick |
| Licence compliance (ODbL share-alike, CC BY attribution, MIT headers) | Rework | `THIRD_PARTY_NOTICES.md` and credits panel from day one |
| Scope | Unfinished demo | Cut list in [IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md#cut-list) |

---

## 14. Assumptions and open items

**Assumptions:**
- English-only UI.
- ~~No IAF crest in the UI~~ Superseded 2026-10-16: the team asked for the official IAF crest (splash, login, top bar). No roundel, fin flash or ensign.
- Internet available at the demo.
- `iaf-airops` is a placeholder name.

**Open items to confirm:**
1. Product name and branding.
2. The permission cells marked *(proposed)* in §4.2: Base Commander acknowledges own-base alerts and reads the own-base audit; export rights.
3. Organisers' view on real ORBAT and AD system names (Risk table).
4. District vintage: DataMeet districts are Census-2011 based. Decide whether current district boundaries are needed (post-2019 J&K/Ladakh reorganisation).
5. Whether airplanes.live access will be requested (it now requires contacting them; see [API §1](API.md#1-live-aircraft)).

---

## 15. Decision log (agreed with the team, 2026-10-16)

| Topic | Decision |
|---|---|
| Data realism | Real public base names and coordinates. Everything inside a base is synthetic and labelled SIMULATED. Pilot names are fictional. |
| Squadrons and serials | Real public ORBAT (squadron numbers, names, home bases from open sources, source URL per row). Tail numbers are generated in the real serial format, without copying real airframe serials. |
| Air defence and radars | Real system names (S-400, MR-SAM, Akash, SPYDER, Igla-S…; Arudhra, Rohini, Ashwini, Aslesha…) at **synthetic** positions near real bases and border sectors, with range rings, tagged SIMULATED. |
| Weapon loads | Generic armament stock categories in warehouses (AAM-BVR, AAM-WVR, PGM, bombs, rockets, gun ammo, chaff/flare). No loadout model. |
| Foreign bases | Public info only. APP-6 hostile for Pakistan and China, neutral for other neighbours. |
| Other Indian military | Navy, Army Aviation and Coast Guard air stations are markers with public info only. |
| Live air | Real ADS-B + simulated IAF tracks. Toggles: Civilian, Cargo, Military, Helicopters, UAVs, Drones, Simulated IAF (+ Simulated Unknowns). |
| Threats | Occasional simulated unknown tracks approach the border (never cross) and trigger QRA scrambles. |
| Interceptors | SAM/AD batteries with rings, plus QRA interceptor jets as base badges. |
| Comms infrastructure | Real OSM telecom towers + synthetic military comms nodes (data link, SATCOM, V/UHF). |
| Stack | React + TypeScript + Vite + CesiumJS 1.138 (no Resium); FastAPI + PostgreSQL/PostGIS (Docker); Python generator; Node sidecar for wind (God's Eye port). |
| Auth | Login + roles: Admin, Command HQ, Base Commander, Viewer. Command HQ acknowledges alerts. Viewer sees pilot profiles but not the audit log. Base Commander edits own-base equipment, pilots and sorties. |
| Editing | Full CRUD with optimistic locking. Audit covers human **and** simulator changes. |
| Sorties | The simulator generates the daily programme. Humans can also create, edit and cancel sorties, which the simulator then flies. |
| Simulation | Live tick simulation over WebSocket. |
| Modelling | One `aircraft` table for jets, helicopters, UAVs and drones. Ground crew as counts per base × trade × shift. Simulated tracks derived, not stored. |
| Map extent | Locked to ~60–105°E, 0–42°N. |
| Borders | Official GoI depiction. Neighbour ADM1/ADM2 from geoBoundaries, clipped against the India polygon. No third-party border or label layers. |
| Weather | METAR/TAF, Open-Meteo point forecast, OWM overlays, GFS/ECMWF wind + IR clouds. |
| Screens | Map + side panel, Command overview, Inventory tables, Pilot profiles, Alerts & audit. |
| Theme | Tactical olive + amber; B612 + B612 Mono; APP-6 via milsymbol; banner `UNCLASSIFIED // SIMULATED DATA — SIH 2026 DEMO`. |
| Theme (revised 2026-10-16) | Navy + neon blue (Indian Navy colours); official IAF crest on an opening shutter, the login and the top bar; proper on/off switches in the layer rail. |
| Map (revised 2026-10-16) | Flat MapLibre vector map instead of the Cesium globe; smaller, decluttered symbols. |
| Banner (revised 2026-10-16) | Remove the `UNCLASSIFIED // SIMULATED DATA — SIH 2026 DEMO` banner. |
| Simulation (revised 2026-10-16) | Remove all simulation from the map and stop the tick simulator for now: the map shows only real/public data. Simulation and optimisation come later (Phase 2). |
| Time | IST primary, Zulu secondary; METAR/TAF in Zulu. |
| Network | Internet assumed; offline mode is a could item. |

---

## 16. Glossary

| Term | Meaning |
|---|---|
| AD | Air defence |
| ADS-B | Automatic Dependent Surveillance–Broadcast (aircraft position broadcasts) |
| ALG | Advanced Landing Ground (forward airstrip) |
| AOG | Aircraft On Ground: grounded awaiting parts |
| APP-6 | NATO joint military symbology standard (≈ MIL-STD-2525) |
| ATF | Aviation turbine fuel |
| BRD | Base Repair Depot |
| FBSU | Forward Base Support Unit |
| GSE | Ground support equipment |
| HAS | Hardened Aircraft Shelter |
| METAR / TAF | Aviation routine weather report / terminal aerodrome forecast |
| ORBAT | Order of battle: units, their equipment and locations |
| QFI | Qualified Flying Instructor |
| QRA | Quick Reaction Alert: armed aircraft and crew on short-notice standby |
| S / U/S | Serviceable / unserviceable |
| SIDC | Symbol identification code (APP-6 / 2525) |
| WAC, SWAC, CAC, EAC, SAC | Western, South Western, Central, Eastern, Southern Air Command |

---

## 17. Phase 2: decision support (SIH26250 "dynamic air operations and resource optimisation")
Design and rationale: [PHASE2_IMPLEMENTATION_PLAN](PHASE2_IMPLEMENTATION_PLAN.md). Decision records: ARCHITECTURE D28–D47.
Measured results: [BENCHMARK](BENCHMARK.md), [MODEL_CARD_SNAG_RISK](MODEL_CARD_SNAG_RISK.md).
Everything is advisory: a person approves every change, and every approval is audited.

### FR-MSN: missions
| ID | P | Requirement |
|---|---|---|
| FR-MSN-01 | M | Missions carry type, priority P1–P4, time window, target area (inside India, clear of the border buffer and on the Indian-administered side of the LoC / LAC) or destination base, aircraft required, time on station, eligible roles, optional loadout, crew qualifications and the highest acceptable route risk. |
| FR-MSN-02 | M | Command HQ requests missions for its command; Air HQ and the directing staff create approved missions; Air HQ approves requests. Cancel cancels any planned sortie. Audited. |
| FR-MSN-03 | M | The generator creates two days of realistic mission requests per operational command (CAP, ISR, AEW&C, AAR, airlift, HADR, casualty evacuation, strike and CAS exercises, training). |
| FR-MSN-04 | S | A mission's area can be picked on the map. |
| FR-MSN-05 | C | Public airspace (prohibited, restricted, danger areas and civil terminal airspace) can be imported from OpenAIP next to the synthetic zones; prohibited areas are never routed through (D44). |
| FR-MSN-06 | S | A mission can depend on another (an AEW&C orbit) being on station for its whole time on station (D41). |

### FR-PLN: planning
| ID | P | Requirement |
|---|---|---|
| FR-PLN-01 | M | Generate a plan for the next 24 h (theatre, or one command) that assigns base, aircraft type, tails, crew and a generic loadout to each mission. |
| FR-PLN-02 | M | Hard rules: aircraft serviceable and not QRA (the QRA posture is kept), hours to inspection, crew current on type, medically fit, rested (10 h after recovery), qualified (night / NVG / mountain / formation lead) and instrument-rated for the forecast weather; range and endurance; weather minima at launch and recovery; runway open; route clear of the border buffer and of restricted airspace; route risk within the mission's limit; weapons and fuel above reserve; airspace capacity. |
| FR-PLN-03 | M | Lexicographic objective: maximise P1 coverage, then P2, P3, P4; then the chosen preset (balanced, max coverage, min risk, min fuel). |
| FR-PLN-04 | M | An independent validator re-checks every plan before it is proposed and before it is committed. |
| FR-PLN-05 | M | Commit creates, keeps, swaps, moves or cancels sorties to match the plan, reserves weapons, and is audited. Packages whose tails or crew went unavailable since the plan was made are repaired at commit or skipped with a reason. |
| FR-PLN-06 | M | Base commanders can swap tails or crew inside their own base's package; the swap is re-validated. |
| FR-PLN-07 | M | Theatre plan for the seeded day in < 10 s on the reference laptop; same snapshot and seed give the same plan. |
| FR-PLN-08 | S | Air-to-air refuelling: a package that can't reach or hold without fuel gets a tanker leg (tanker base, rendezvous, crew, fuel) when its type and mission allow it; receiver crews must be AAR-qualified; the tanker becomes its own sortie at commit (D36). |
| FR-PLN-09 | M | Launch rate: no more than 8 aircraft launch from one open runway in a 15-minute slot (D36). |
| FR-PLN-10 | S | P1/P2 packages are given the free tails least likely to develop a defect (snag-risk model, FR-FCT-03); the risk per tail and per package is shown (D38). |
| FR-PLN-12 | S | Split missions: a mission no single package can fly is offered a checked split, as reliefs in time (continuous cover, 15 min handovers) or as parts from different bases on station together; applying it is a human action; parts are covered all or nothing (D42). |
| FR-PLN-13 | M | Manual planning baseline: a timed manual session on the same snapshot, judged by the same rules, stored beside the optimiser's result and reported in the benchmark (PS-8, D43). |
| FR-PLN-14 | M | Air tasking order: a printable order (and CSV) for a plan, theatre-wide or per base, one briefing entry per package (callsigns, tails, crew, times, waypoints, loadout, tanker meeting point, notes); DRAFT until committed (D46). |
| FR-PLN-15 | S | Packages bigger than a base's launch rate take off in up to three waves and join up (D45). |
| FR-PLN-11 | S | Civil traffic: routes through busy civil airspace (airport terminal areas, live ADS-B density for near-term launches) cost more, so quieter options win when otherwise close; the explanation names the busy spot (D39). |

### FR-RTK: dynamic re-tasking
| ID | P | Requirement |
|---|---|---|
| FR-RTK-01 | M | The committed plan is re-checked against live (simulated) data every 12 s. A broken rule becomes a deduplicated disruption, whatever caused it (simulator, human edit, weather, exercise inject, new mission). |
| FR-RTK-02 | M | A re-task proposal is ready in ≤ 15 s (target; measured < 1 s): local tail/crew swap first, then a partial re-solve of the affected missions, then a full re-solve with a stability bonus for committed slots. |
| FR-RTK-03 | M | The proposal shows each package as kept, swapped, moved, new, dropped or diverted, with the reason. Air HQ commits or rejects it. |
| FR-RTK-04 | S | An airborne package whose recovery base becomes unusable gets a divert recommendation (runway open, weather within the crew's minima, inside fuel range). |
| FR-RTK-05 | S | In-flight re-role: an urgent P1/P2 mission the ground can't cover in time is offered to an airborne package on a lower-priority mission with the right role and load that can reach it, hold and recover with reserve fuel; commit re-tasks the sortie in place and releases its old mission (D37). |
| FR-RTK-06 | S | A re-roled or diverted package's knock-on effects (later packages on the same tails or crew) are repaired in the same proposal. |

### FR-XPL: explanations
| ID | P | Requirement |
|---|---|---|
| FR-XPL-01 | M | Each package explains itself: transit, weather at launch and recovery, route risk, night and qualification needs, fuel and weapons impact, binding constraints, and the top alternatives with why they lost. |
| FR-XPL-03 | S | Package explanations also show the tanker leg, the predicted snag risk (worst tail, package, main drivers) and civil traffic along the route. |
| FR-XPL-02 | M | Each uncovered mission lists its reasons, nearest base first (e.g. "can't reach the area inside the time window", "resources taken by P1 CAP-WAC-003"), and checked fixes ("move the window 60 min later", "+2 Su-30MKI at Halwara", "accept risk HIGH"). |

### FR-FCT, FR-WIF: forecasts, what-if and COA comparison
| ID | P | Requirement |
|---|---|---|
| FR-FCT-01 | M | 72 h outlook per base: aircraft free by type (maintenance returns, planned sorties × each tail's predicted defect risk), pilots free, ATF level and reserve breach, weather by hour. Shown in the base panel. |
| FR-FCT-03 | S | Snag-risk model trained on the maintenance log only (never the simulator's law), with held-out metrics (AUC, Brier, calibration, lift), a model card, and a retrain action for Air HQ; the base panel lists its riskiest serviceable tails (D38). |
| FR-FCT-02 | M | Base weather for planning: Open-Meteo hourly where reachable, synthetic otherwise, exercise overrides on top. |
| FR-WIF-01 | M | What-if: ground aircraft of a type, close a runway, weather front, threat zone, mission surge, fuel shortfall, base attack; re-plan on a copy and compare with the baseline. Nothing is written. |
| FR-WIF-02 | M | COA comparison: the same picture planned with two or three presets side by side. |

### FR-EXR: scenarios (directing staff)
| ID | P | Requirement |
|---|---|---|
| FR-EXR-01 | M | **The situation is the starting point (D56).** Scenarios page (replaces Exercise control, D55): eight scenarios, one per category (accident, infrastructure, urgent tasking, weather, logistics, equipment, surveillance, hostile action). A scenario is **one incident**: starting it applies its effects on supply (runway closed, aircraft lost, fuel down…) **and creates the missions it demands** (e.g. air attack → P1 patrol, P2 early-warning orbit, P2 reconnaissance), tagged with the scenario; routine tasking is the baseline they compete with. Each has an intensity (low / medium / high / severe, a preset of its parameters) and a short form; the page lists the missions each adds. Several scenarios may be live at once, one run per scenario; no plan has to exist first. Ending a scenario withdraws its missions not yet flying. Clock pause and speed (×1, ×10, ×60). |
| FR-EXR-02 | M | Effects: runway closed, weather front, threat zone (generic, D31), aircraft grounding (by base list), aircraft lost, base strike (runway, radars, fuel), pop-up mission (at a base or a point near one), fuel delay (by base list), radar down, unknown track. Scripted effects can target "AUTO" (the busiest tasked base). |
| FR-EXR-03 | M | After-action report: injects, disruptions with proposal time and decision time, plans and approvals, mission outcomes (met / partial / missed), KPI samples; CSV with the SIMULATED header and a print view. |
| FR-EXR-04 | M | The Ops map view shows simulated sorties flying their routes, unknown tracks, planned and proposed routes, mission areas, generic threat zones, airspace, radar / AD coverage and weather impact. |
| FR-EXR-05 | M | **Planner → Situation** (since D61: one card per situation; opening one walks it through Situation → Plan → Decide → Mission, where in Plan a person keeps the planner's recommendation, takes one of its other options, applies a fix or picks a base, aircraft and time of their own, which the planner's rules check before it enters the plan; Mission approves it; the expert views are under "Details & tools"). When the situation changes the planner proposes automatically: a full plan when nothing is committed, else a re-task. One screen: the situation strip (All · each live scenario), the decision line (Commit / Reject the plan as one), for a selected scenario its sentence and five-step live timeline, **Missions and plan** (tag Routine / scenario, priority, package, when, status), **Impact and what we recommend** (what it broke or displaced, the recommendation and the options weighed, when, status), **Requirements** by base and **Inventory transfers** (FR-EXR-07). Every row comes from the engine; no Gantt. |
| FR-EXR-07 | M | **Inventory optimisation (D56):** for the plan under review, recommend moves of fuel (ATF), weapons and spares between bases so its packages can draw what they need and bases return to their fuel reserve and spares reorder level: a min-cost flow over road distance, donors never below their own reserve or reorder level, ETA by convoy, late arrivals flagged, needs no base can meet listed. A person approves each move (or all); the donor is debited at once, the receiver credited when the convoy arrives, both audited; the planner counts stock on the road. Shown in the Situation view and on the Ops map. |
| FR-EXR-06 | M | Commit tolerates the time a decision takes: a new or moved package whose preparation should already have started slips by that delay when its mission window still holds, then is re-validated; otherwise it is repaired or skipped as before (FR-PLN-05). |

### Phase 2 demo questions (each < 30 s)
1. "Plan the next 24 hours: is every P1 covered?"
2. "Why was this base chosen for CAP-WAC-003, and what lost?"
3. "Which missions are uncovered and what would fix them?"
4. "A runway just closed: what changes?" (Scenarios → start *Runway closure at Halwara* → Planner → Live scenarios → commit)
5. "What if 20 Su-30MKI are grounded tomorrow?" (what-if)
6. "A P1 pop-up 20 minutes away: can anyone already airborne take it?" (in-flight re-role → commit)
7. "Which of my tails are most likely to go unserviceable, and did the P1 packages get the reliable ones?" (base panel snag risk, package explanation)
8. "Nobody can hold a 6-hour CAP: what now?" (uncovered → "Split into 2 reliefs" → apply → re-plan)
9. "How much faster is this than planning by hand?" (Planner → Details & tools → Plan by hand, then BENCHMARK.md)
10. "Give Halwara its orders for tomorrow." (Planner → Air tasking order → base VIHX → Print)

