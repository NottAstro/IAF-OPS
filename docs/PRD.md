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

> Phase 2 (decision support built on this data) is out of scope for this document set.

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
- Any decision-support, scoring, ranking, recommendation or predictive logic.
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
| FR-LIVE-09 | S | Track trails (last N positions), toggleable. |
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
| FR-TER-02 | M | Tilt toggle: oblique −35° ↔ top-down −89°. Free tilt with the right-drag or Ctrl-drag gesture. |
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
| FR-INV-01 | M | One table per entity: aircraft, aircrew, ground crew strength, ground assets, fuel storage, fuel transactions, warehouses and stock, AD batteries, radars, comms nodes, runways, parking, squadrons, sorties, missions. Server-side paging, sort, filter (base, command, type, status) and search. |
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
| Weapon loads | **Partial**: generic armament stock by category in base warehouses; no per-aircraft loadouts |
| Airspace | Live ADS-B picture, civil airports, radar and SAM coverage rings, region lock |
| Weather | METAR/TAF, point forecast, OWM overlays, GFS/IFS wind, IR clouds, below-minima alerts |
| Threats | Neighbour air bases (hostile/neutral symbology), live military ADS-B, simulated unknown tracks and QRA response, own AD/radar coverage |
| Mission priorities | `mission.priority` P1–P4 and sortie mission types, displayed and filterable |

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
