# Scenarios and the scenario-centred Planner: design

Date: 2026-10-18 · Status: implemented (ARCHITECTURE D55) · Mockups: `.superpowers/brainstorm/9846-1792320067/content/all-scenarios-v7.html` (switch between "Scenarios page" and "Planner" in the purple bar)

## 1. Intent

The Exercise page and the Planner are hard to follow in a demo. The team wants a judge to see, for one realistic incident at a time:

1. **what happened** (a scenario, started from a library of eight),
2. **what it broke** (impacts),
3. **what the planner recommends for each impact**, with the other options it weighed,
4. **what those recommendations need and where it comes from** (requirements by base and time window),

live, while the simulator runs, not as a finished report.

Two screens carry this: a renamed **Scenarios** page (pick and start an incident) and a **Planner** whose landing view is the live scenarios and their responses.

## 2. Goals, non-goals, anti-goals

**Goals**
- Eight seeded scenarios, one per category, each with an intensity (Low / Medium / High / Severe).
- A scenario is **one event**: starting it applies all its effects at once. No follow-on events, no if/then chains.
- Several scenarios can run at the same time.
- The Planner shows, per live scenario: one-sentence summary, a five-step live timeline, an **Impact → Recommendation** table (with "when" and status), and a **Requirements** panel.
- Every row on the Planner comes from the real decision engine (disruptions, re-task proposal, explanations, fixes, resources), never from hand-written text.

**Non-goals**
- Base-to-base logistics (ferrying aircraft, trucking fuel). The planner still only chooses which base flies each mission with that base's own stock. Raised in the session; not in the agreed mockups.
- If/then conditions and multi-event scripts (dropped by the team on 2026-10-18).
- Per-row partial commits (see §5.4).

**Anti-goals** (would make this a failure even if it works)
- A cluttered screen. The team rejected every version with repeated numbers, long paragraphs, a KPI strip or a Gantt. One sentence of description; reasons live in the impact rows only.
- A screen that looks finished. It must read as live: "now" marker, airborne states, countdowns, decisions waiting.
- Naming a real country as the attacker (ARCHITECTURE D31: generic threats only). The hostile scenario is "Western sector air attack".

## 3. Vocabulary (used in UI copy and code)

| Word | Meaning |
|---|---|
| Scenario | A named incident with a category, intensity and parameters. Started from the Scenarios page. One live run per scenario at a time. |
| Effect | One change to the synthetic world a scenario makes on start (runway closed, aircraft lost, radar offline, pop-up mission…). Existing inject kinds plus three new ones (§5.2). Not shown as separate events. |
| Impact | Something the scenario broke: a disruption the re-tasking monitor raised for it, or a direct effect worth stating (aircraft lost, base below minima). |
| Recommendation | The engine's answer to an impact: a changed package in the re-task proposal (moved, new, divert, swap, dropped), or a checked fix for an uncovered mission. |
| Requirement | What a recommendation needs (aircraft, crew, fuel, runway slots, tanker, sensor cover), from which base, when, against what is available there. |

## 4. Screens

### 4.1 Scenarios page (replaces Exercise; nav label "Scenarios", route `/scenarios`, `/exercise` redirects)

- Header: title, SIM tag, simulator clock speed (×1 / ×10 / ×60) and Pause (existing `/sim/*` endpoints).
- One-line lead: "Pick a scenario and start it. The Planner shows its impact and what to do about it."
- Grid of eight cards: category (small caps), name, one-line effect, intensity dots (1–4, coloured ok → caution → warning → critical), and `● live 9 min` or `ready`.
- Selected scenario panel (right): category · intensity, name, one-sentence description, parameter fields, intensity selector, effect summary, and **Start now** / **End scenario**, plus **Open in Planner →**.
- Below the cards: "Ended today" with links to the existing after-action report.
- If no plan is committed: a notice "Commit a theatre plan in the Planner first: scenarios break the committed plan" and Start is disabled.
- ADMIN (directing staff) starts and ends scenarios; everyone else sees the page read-only.

### 4.2 Planner, live scenarios view (landing view)

Three columns: live-scenario rail (≈230 px) · response (flex) · requirements (≈370 px).

- **Rail:** every running scenario: intensity dot, name, and either running time or "N need you" (orange). Ended runs are not listed.
- **Decision line** (only while a re-task proposal touching this scenario waits): one line naming the proposal, **Reject** and **Commit** (existing approve/commit/reject endpoints).
- **Title** with `● live` (or `● waiting for you`) and SIM; **one sentence** describing what happened.
- **Timeline**, five steps, time + two or three words, with "now" highlighted: started → plan broke/updated → current step → next expected step → effect ends. Built from: run start, first disruption ts, proposal ts / commit ts, live sortie states, effect end (runway reopen, front clears…).
- **Impact and what we recommend** table, columns: severity glyph + what it broke (+ one dim sub-line) · → · recommended (bold) with "or: …" other options · **When** · status. Status values: `✓ in plan` (committed), `proposed` (in a proposal awaiting commit), **Apply** (a checked fix that can be applied on its own, §5.4), `no action`. The header counts rows that need a decision. Live "when" text: `airborne · lands 16:12`, `on station · 17:45 – 20:45`, `15:25 – 16:40`.
- **No Gantt** in this view.

### 4.3 Requirements panel

Header: "Requirements" and a count line (`4 available · 2 if approved · 1 waiting`). One block per requirement:

```
Runway to land 2 Hawks                 ✓ available
Need  2 landing slots
From  Hakimpet · 4 free 16:00–16:30
When  16:10–16:15
[====      ]   (need ÷ available there)
```

Status: `✓ available` (committed), `if approved` (in a pending proposal), `waiting` (blocked by time, e.g. a runway still closed). No bar when there is no countable supply.

### 4.4 Planner, theatre plan view

The existing plan workspace (generate, approve, commit, explanations, unmet fixes, ATO) stays reachable from the Planner as a second view, because a committed plan is what scenarios break. **Open question for the team (§8):** which of its tabs stay.

## 5. How it works

### 5.1 Data model

- `scenario` gains `code` (stable key), `category` (enum: ACCIDENT, INFRASTRUCTURE, URGENT_TASKING, WEATHER, LOGISTICS, EQUIPMENT, SURVEILLANCE, HOSTILE_ACTION), `intensity` (LOW…SEVERE), `summary` (card one-liner), `params` (JSONB schema: field key, label, kind `base|type|choice|text`, options, default), `intensity_presets` (JSONB: intensity → param values), `lead` (the Planner's one-sentence summary, a template filled from the resolved params, e.g. "A Hawk crashed on the runway at {base}. Runway closed about {hours} h.") and `version`. `injects` stays: the list of effects, all at offset 0, with `{param}` placeholders.
- `exercise_run` gains `params` (resolved values), `footprint` (JSONB: base ids, aircraft ids, mission ids, radar ids, zone codes, effect end times) written as effects apply. **Several runs may be RUNNING**; at most one per scenario (partial unique index on `scenario_id` where status = RUNNING).
- `disruption` gains `exercise_run_id` (nullable), set when the monitor stores a disruption that matches a running run's footprint (§5.3).
- Enums flow to TypeScript through OpenAPI as today. All new rows `is_simulated = true`.

### 5.2 Effects (decide/exercise.py)

Existing kinds are reused; three are added; two existing ones learn base lists.

| Scenario | Effects on start (defaults; intensity presets scale hours / counts) |
|---|---|
| Trainer jet crash at Bidar | `AIRCRAFT_LOST` (1 Hawk 132 at the base, status written off) + `RUNWAY_CLOSED` 4 h + `MISSION_POPUP` P1 CASEVAC 18 km from the base (the ejected pilot) |
| Runway closure at Halwara | `RUNWAY_CLOSED` 6 h |
| Avalanche casualty in Ladakh | `MISSION_POPUP` P1 CASEVAC at a high post near Thoise, 3 h window |
| Eastern monsoon front | `WX_FRONT` IFR, Tezpur/Jorhat/Chabua/Mohanbari, 8 h |
| Fuel supply disruption | `FUEL_DELAY` on Halwara, Adampur, Sirsa (base list), 40 %, 24 h |
| Su-30MKI fleet grounding | `AIRCRAFT_GROUNDING` type Su-30MKI at Halwara, Sirsa, Tezpur (base list, all of the type), 48 h |
| Radar network outage | `RADAR_DOWN` Bathinda 6 h + `MISSION_POPUP` P1 AEW_SUPPORT over the gap |
| Western sector air attack | `BASE_STRIKE` (runway closed 12 h, radars offline, fuel −30 %) at Adampur + `THREAT_ZONE` generic, 6 h + `MISSION_POPUP` P1 AIR_DEFENCE_PATROL over the sector |

New kinds: `AIRCRAFT_LOST` and `BASE_STRIKE` (a composite of existing writes). Each effect appends to the run's footprint. Effects are audited as today (`INJECT`). Simulated placement rules still apply: no synthetic site or threat inside `border_buffer_km`, threat zones only on the Indian-administered side (D33).

### 5.3 Attribution (which impacts belong to which scenario)

A disruption belongs to a run when, after the run started, its `base_id` is in the run's footprint bases, its entity is in the footprint aircraft/radars, or its mission is a footprint pop-up. `THREAT_ACTIVATED` disruptions go to the run that created the active zone. A re-task item belongs to a run when its mission is in that run's disruptions or pop-ups; knock-on changes (e.g. a Kiran sortie moved to free Hakimpet's runway) go to the run whose footprint or divert base matches the item's base. Anything unmatched is shown under "Other changes" on the theatre view, not hidden. `ponytail:` footprint matching, not causal tracing; upgrade path is tagging validator violations with the effect that caused them.

### 5.4 Recommendations and applying them

- Impacts = the run's disruptions + direct-effect rows from the footprint (aircraft lost, aircraft grounded, bases below minima, fuel below reserve).
- Recommendation for an impact = the proposal item for that mission (`MOVED`, `NEW`, `DIVERT`, `SWAP`, `REROLE`) or, for `DROPPED`/unmet, its top checked fix. "Other options" = the item's top two explanation alternatives (`alternatives[].base/type/why_not`) or the next two fixes.
- **Commit stays atomic per proposal.** The validator checks a plan as a whole (D40), so a re-task proposal is committed or rejected as one, from the decision line. Rows in a pending proposal show `proposed`; after commit, `✓ in plan`. Only fixes that already apply on their own (split, today; window move if the endpoint exists) get a per-row **Apply**. The mockup's per-row Apply on proposed packages is replaced by this (team saw per-row Apply; this is the builder's call, flagged in §9).
- Live "when"/state from the sortie the item created: PLANNED → time window; AIRBORNE / ON_STATION / RTB → `airborne · lands HH:MM` or `on station · …`.

### 5.5 Requirements (decide/requirements.py, new)

Computed from the run's attributed items against an `OpsState` (snapshot) at the item's launch: aircraft by (base, type) vs free and usable of that type at the base (`resources.aircraft_free`), crew by base vs eligible and free (`resources.crew_free`), fuel by base vs ATF stock and reserve, launch slots vs the runway's launch rate (8 per 15 min, D36) and runway status, tanker legs, AEW&C cover. Status from the item's plan status (committed → available, proposed → if approved) or from a footprint end time (waiting). Reuses `resources.py`; no second definition of "free".

### 5.6 API (routers/exercise.py renamed scenarios, thin; logic in decide/)

- `GET /ops/scenarios` → cards: code, name, category, intensity, summary, params schema, presets, live run (id, started, elapsed) or null.
- `POST /ops/scenarios/{code}/start` {params, intensity} (ADMIN, audited) · `POST /ops/scenarios/runs/{id}/end` (ADMIN, audited).
- `GET /ops/scenarios/live` → rail: running runs with intensity, elapsed, need-you count.
- `GET /ops/scenarios/runs/{id}/response` → {summary sentence, timeline[5], impacts[], requirements[], pending_proposal_id}.
- Existing `/ops/exercise/*` routes stay as aliases until the frontend no longer calls them. The after-action report filters disruptions by `exercise_run_id` instead of the time window, so overlapping runs don't share rows.
- One pending proposal can carry changes for two live scenarios; its decision line then shows on both, and committing it applies both. The line says so ("also changes: Radar network outage").

### 5.7 Frontend

- `pages/Scenarios.tsx` replaces `pages/Exercise.tsx` (AfterAction stays). `pages/Planner.tsx` gains the live view; the existing workspace moves into a `TheatrePlan` component. Old `Timeline` Gantt is removed from the live view.
- Tokens only from `styles/tokens.css`; B612 / B612 Mono; SIM tag on every synthetic surface (DESIGN_SYSTEM §9); copy in sentence case (§13).
- TanStack Query polling (5 s) plus the existing WebSocket `entity.changed` / `retask.proposal` events to refresh.

### 5.8 Seed data (generator, deterministic)

- Eight scenarios replace the two in `generator/phase2.py`.
- Add a small set of P3/P4 Hawk 132 training missions near Bidar and Kiran missions near Hakimpet inside the first 24 h, so the crash has packages to break (today's dry-run plan puts nothing at Bidar or Adampur).
- Post-generation checks, denylist and determinism tests stay green.

## 6. Constraints (from AGENTS.md and the docs)

- Decision code in `backend/app/decide/`; routers thin; sortie writes only through plan commit (`store.py` / `services/sorties.py`).
- `decide/` never imports `sim/reliability.py`.
- Every mutation RBAC-checked and audited in the same transaction; PATCH needs `version`.
- Docs updated in the same change: PRD (FR-EXR rows rewritten, FR-EXR-05/06 added), DATA_MODEL (scenario, exercise_run, disruption columns), ARCHITECTURE §18 row D55 (scenario-centred Planner, concurrent runs, attribution), DESIGN_SYSTEM (two screens), README demo script.
- Tests: concurrent runs start/end; each new effect; attribution; requirements numbers on a small fixture; RBAC matrix and audit-per-mutation for the new routes; generator determinism with the new scenarios. No live network.
- `make check` green before calling it done.

## 7. Builder's calls (made during design, open to correction)

1. Intensity selects a preset of the scenario's parameters (e.g. crash: Low = 2 h, Severe = 8 h and 2 aircraft lost). It is also the card's rating.
2. One run per scenario at a time; several different scenarios may run together.
3. Starting a scenario requires a committed plan.
4. Scenarios are started and ended by ADMIN or COMMAND_HQ (Air HQ); the simulator clock stays ADMIN-only. (Changed 2026-10-18 after the team couldn't start one as Air HQ.)
5. Commit is atomic per proposal (§5.4).
6. The old free-form "Inject now" form is removed; Start is the inject.
7. Mockup numbers are illustrative; the live screen shows whatever the engine proposes.

## 8. Decided after review

The existing Planner workspace stays as the **Theatre plan** view (generate / approve / commit, ATO, What-if, Compare COAs, Manual baseline); only its theatre Gantt is removed. The live scenarios view is the Planner's landing view while any scenario runs. (Builder's call on the recommended option, 2026-10-18; open to the team's correction.)

Found while testing and added:
- **Commit slip** (PRD FR-EXR-06): at ×10 every urgent package was skipped at commit, because the planner proposes the earliest launch and a minute of human thought is ten simulated minutes; commit now slips such a package by the delay if its mission window holds.
- **Attribution by cause first**: with several scenarios on one base, a runway disruption goes to the scenario that closed that runway, a grounded tail to the grounding; base-only matching is the fallback.
- **Training waves** at Bidar (Hawk) and Hakimpet (Kiran), including evening waves, so the crash breaks something whenever it is started.

## 9. Things the team saw that changed in this document

- Per-row **Apply** on proposed packages becomes one **Commit** per proposal (§5.4).
- The crash's "pilot pickup" appears because the crash effect creates a P1 casualty pop-up; the recommendation is whatever helicopter the engine picks.

## 10. Situation-first flow and inventory transfers (ARCHITECTURE D56, decided with the team 2026-10-18)

The team found the plan-first order confusing: a theatre plan had to exist before a scenario could start, and scenarios only broke it. The order is now the one an air operations centre works in: **the situation comes first**.

**Flow.** Scenarios (0..n live; routine tasking is always the baseline) → missions (routine plus each scenario's own, **tagged**) → the planner **proposes automatically** (a full plan if nothing is committed, else the minimal-change re-task) → impacts → requirements by base → **inventory transfers** → a person commits the plan and approves transfers → the simulator flies it and the Ops map shows it → **End scenario** withdraws the scenario's open missions → after-action report.

**Decisions taken with the team:**
- **Missions** come from routine tasking and from scenarios. Each carries a tag: `mission.exercise_run_id` (NULL means Routine). The Missions page has a Tag column and filter; the Ops map outlines scenario missions in the warning colour.
- **Plan update:** automatic proposal. Starting or ending a scenario, or approving a transfer, triggers it; nothing changes until a person commits. The "commit a theatre plan first" gate on the Scenarios page is gone.
- **Inventory optimisation** recommends **transfers of fuel, weapons and spares** between bases, with no aircraft redeployment. A person approves each one.

**What each scenario adds** (generator injects):
| Scenario | Missions it adds |
|---|---|
| Trainer crash | P1 casualty evacuation |
| Avalanche | P1 casualty evacuation, P2 supply drop |
| Monsoon front | P2 flood relief |
| Radar outage | P1 early-warning orbit, P2 patrol |
| Air attack | P1 patrol, P2 early-warning orbit, P2 reconnaissance of the struck base |
| Runway closure, fuel disruption, fleet grounding | none: the response is re-planning and transfers |

The Scenarios page lists these under "Adds missions".

**Inventory optimiser** (`decide/logistics.py`):
- **Method:** one OR-Tools min-cost flow per commodity, with arc cost = great-circle km × road factor.
- **Fuel:** a receiver needs the plan's draw plus whatever brings it back to reserve. A donor offers what is left above its reserve, its own planned use and a 10 % keep.
- **Weapons:** a base needs what its unreserved packages load beyond its free stock.
- **Spares:** these count only at bases a live scenario touched or flies from, up to their reorder level.
- **Results:** needs nobody within 900 km can meet are listed as unmet. Each move carries an ETA (loading + km ÷ convoy speed) and the time it is needed by (the first launch that draws on it); a move that arrives after that is flagged late.
- **Policy:** these limits are SIMULATED policy in `decide/config.py`.

**Transfers** (`inventory_transfer`, `services/transfers.py`, `POST /ops/transfers`):
- **Approve (Air HQ and admin only, audited):** debits the donor at once. Fuel uses `TRANSFER_OUT` and stock uses `qty_on_hand`, and a donor can never drop below its reserve or reorder level.
- **Deliver:** the simulator credits the receiver at the ETA.
- **Planning:** while a transfer is on the road the snapshot counts it as arriving, so the planner and the validator agree (D40).

**Planner → Situation** (landing view; the old Theatre plan view becomes **Plan details & tools**, unchanged):
- **Situation strip:** All, then each live scenario.
- **Decision line:** the proposal under review, with Commit and Reject.
- **Scenario header:** the selected scenario's sentence and steps.
- **Missions & plan:** tag, priority, mission, package, when and status. Unchanged routine rows are counted rather than listed.
- **Impacts:** what the scenario broke or displaced, and the fix for each.
- **Side panel:** inventory transfers (Approve / Approve all, unmet, in transit), then requirements.

**Ops map only:** two new layers in the Operations group, **Scenario effects** (rings on affected bases) and **Inventory transfers** (dashed when recommended, solid when on the road). The Ops status panel lists live scenarios and links to a proposal waiting for a decision. Live, Weather, Infra and Map settings are unchanged.

**Tuned while testing:**
- **Fuel disruption:** the loss is a "contaminated batch quarantined" at 60 / 80 / 90 % (seeded stocks are large, so smaller losses produced no transfers).
- **Air attack:** threat zone risk 0.8, so the P1 patrol (`max_risk` HIGH) can be covered.
