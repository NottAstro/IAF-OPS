"""Decision-support policy (PHASE2_IMPLEMENTATION_PLAN §7). Every value here is SIMULATED policy: tune freely.

Shared by the generator (loadout catalogue, mission templates) and the planner (minima, weights, limits).
"""

# ---------------------------------------------------------------- planning grid
HORIZON_H = 24
SLOT_MIN = 15
MIN_LEAD_MIN = 30          # nothing is planned to launch sooner than this after "now"
FREEZE_MIN = 30            # re-planning never moves a package launching within this window
TOP_K = 30                 # candidates kept per mission
LAUNCH_STEP_MIN = 30       # launch options are tried on this grid across the mission window
MAX_LAUNCH_OPTIONS = 6
SOLVER_TIME_S = 8.0        # per lexicographic stage
SOLVER_WORKERS = 8

PRIORITIES = ("P1", "P2", "P3", "P4")

# ---------------------------------------------------------------- aircraft / crew timing
PREP_MIN = 30              # aircraft busy before launch (arming, start-up)
BRIEF_MIN = 60             # crew busy before launch
DEBRIEF_MIN = 30           # crew busy after recovery
CREW_REST_H = 10.0         # crew rest after recovery, the simulator's rule (v_aircrew_fatigue: < 10 h rest = fatigued)
FUEL_RESERVE_FRACTION = 0.08   # of max fuel, kept on board at recovery
OVERHEAD_H = 0.25              # take-off, climb, approach
LAUNCH_CAP_PER_RUNWAY = 8
RELIEF_HANDOVER_MIN = 15       # D42: a relief arrives this long before the package it relieves leaves
RELIEF_MIN_SHIFT = 45          # shortest relief worth flying
SPLIT_MAX_PARTS = 4
MAX_WAVES = 3                  # D45: a package bigger than a slot's launch rate takes off in up to this many waves
SPLIT_HEADROOM = 0.8            # a base part takes at most this share of the base's free aircraft and crews
SNAG_AWARE = ("P1", "P2")      # these packages take the tails least likely to go U/S (D38)
SNAG_BAND = 0.02               # risk differences under 2 points don't override fleet-hours balancing
SNAG_CAUTION = 0.15            # package defect risk shown as a caution above this      # aircraft a runway can launch in one 15-minute slot (pairs every ~3 min)

# ---------------------------------------------------------------- air-to-air refuelling (ARCHITECTURE D36)
AAR_RECEIVERS = {"Su-30MKI", "Rafale", "Mirage 2000", "Tejas Mk1"}      # types with AAR_RECEIVER-qualified crews
AAR_MISSIONS = {"AIR_DEFENCE_PATROL", "INTERCEPT", "STRIKE_EXERCISE", "CAS_EXERCISE", "RECCE_ISR"}
AAR_TOP_UP = 0.8               # one refuelling adds this fraction of internal fuel
AAR_RADIUS_GAIN = 1.7          # combat radius multiplier with one refuelling
AAR_MAX_SORTIE_H = 5.0         # fighter crew limit for a refuelled sortie
AAR_RV_HOLD_MIN = 45           # tanker on the refuelling track: from 15 min before the receivers to 30 min after
AAR_PENALTY = 25.0             # cost of using a tanker (score units): prefer an unrefuelled package when both work

# pilots per aircraft by crew family (other positions are filled best-effort at assignment)
PILOTS_PER_AIRCRAFT = {"fighter": 1, "fighter2": 1, "transport": 2, "helo": 2, "trainer": 1, "uav": 1, "uas": 1}
PILOT_ROLE = {"uav": "RPA_PILOT", "uas": "RPA_PILOT"}   # everything else: PILOT
OTHER_POSITIONS = {
    "fighter2": [("WSO", "WSO")],
    "transport": [("NAVIGATOR", "NAVIGATOR"), ("FLIGHT_ENGINEER", "FLIGHT_ENGINEER"), ("LOADMASTER", "LOADMASTER")],
    "helo": [("FLIGHT_ENGINEER", "FLIGHT_ENGINEER")],
    "uav": [("PAYLOAD_OPERATOR", "PAYLOAD_OPERATOR")],
}

# ---------------------------------------------------------------- weather minima (ceiling ft, visibility m)
# by aircrew instrument rating; UAVs use their own line. Categories follow the usual VFR/MVFR/IFR/LIFR split.
RATING_ORDER = ("WHITE", "GREEN", "MASTER_GREEN")
MINIMA = {"WHITE": (1500, 5000), "GREEN": (500, 1600), "MASTER_GREEN": (300, 800)}
UAV_MINIMA = (1000, 5000)
CROSSWIND_KT = {"fighter": 25, "fighter2": 25, "trainer": 15, "transport": 30, "helo": 30, "uav": 15, "uas": 12}

# ---------------------------------------------------------------- threat / risk
RISK_LEVELS = {"LOW": 0.25, "MED": 0.5, "HIGH": 0.85}   # maximum peak route risk a mission accepts
BORDER_BANDS = [(40, 0.55, "Border band, inner (generic)"), (100, 0.3, "Border band, outer (generic)")]  # km, risk

# ---------------------------------------------------------------- objective weights (secondary stage)
PRESETS = {
    "BALANCED": {"transit": 1.0, "risk": 1.0, "fuel": 1.0, "weather": 0.5, "reserve": 0.5, "home": 0.3, "traffic": 1.0},
    "MAX_COVERAGE": {"transit": 1.5, "risk": 0.5, "fuel": 0.5, "weather": 0.3, "reserve": 0.2, "home": 0.1, "traffic": 0.3},
    "MIN_RISK": {"transit": 0.5, "risk": 5.0, "fuel": 0.5, "weather": 1.0, "reserve": 0.5, "home": 0.1, "traffic": 2.0},
    "MIN_FUEL": {"transit": 0.5, "risk": 0.5, "fuel": 5.0, "weather": 0.5, "reserve": 0.5, "home": 0.1, "traffic": 0.5},
}
STABILITY_WEIGHT = 40      # re-plan: cost of moving a package away from its committed slot (score units)

# ---------------------------------------------------------------- generic loadouts (ARCHITECTURE D30)
# code: (name, families, items per aircraft, fuel penalty %, radius factor, description)
LOADOUTS = {
    "A2A_HEAVY": ("Air defence, heavy", ("fighter",), {"ARMAMENT_AAM_BVR": 4, "ARMAMENT_AAM_WVR": 2, "ARMAMENT_CHAFF_FLARE": 1},
                  8, 0.85, "Combat air patrol and intercept"),
    "A2A_LIGHT": ("Air defence, light", ("fighter",), {"ARMAMENT_AAM_BVR": 2, "ARMAMENT_AAM_WVR": 2, "ARMAMENT_CHAFF_FLARE": 1},
                  5, 0.95, "Escort and extended patrol"),
    "A2G_PGM": ("Precision strike (exercise)", ("fighter",), {"ARMAMENT_PGM": 2, "ARMAMENT_AAM_WVR": 2, "ARMAMENT_CHAFF_FLARE": 1},
                12, 0.75, "Precision attack on exercise ranges"),
    "A2G_GP": ("Unguided strike (exercise)", ("fighter",), {"ARMAMENT_BOMB_UNGUIDED": 4, "ARMAMENT_GUN_AMMO": 300,
                                                           "ARMAMENT_CHAFF_FLARE": 1}, 15, 0.7, "Area attack on exercise ranges"),
    "CAS_ROCKETS": ("Close air support (exercise)", ("fighter", "helo"), {"ARMAMENT_ROCKET": 2, "ARMAMENT_GUN_AMMO": 300,
                                                                        "ARMAMENT_CHAFF_FLARE": 1}, 10, 0.8, "Support to ground forces"),
    "RECCE_POD": ("Reconnaissance pod", ("fighter",), {"ARMAMENT_AAM_WVR": 2}, 6, 0.9, "Tactical reconnaissance"),
    "ISR_PAYLOAD": ("ISR payload", ("uav", "uas"), {}, 0, 1.0, "Electro-optical / radar surveillance"),
    "CARGO": ("Cargo and troops", ("transport", "helo"), {}, 0, 1.0, "Airlift, HADR, casualty evacuation"),
    "CLEAN": ("Clean (training)", ("fighter", "trainer", "transport", "helo", "uav", "uas"), {}, 0, 1.0, "Training, ferry"),
}
LOADOUT_ROLES = {  # restrict a loadout to some roles inside its family
    "A2G_PGM": {"FIGHTER_MULTIROLE", "STRIKE"}, "A2G_GP": {"FIGHTER_MULTIROLE", "STRIKE"},
    "CAS_ROCKETS": {"FIGHTER_MULTIROLE", "STRIKE", "ATTACK_HELO"}, "RECCE_POD": {"FIGHTER_MULTIROLE", "STRIKE"},
    "CARGO": {"TRANSPORT_STRATEGIC", "TRANSPORT_TACTICAL", "TRANSPORT_LIGHT", "UTILITY_HELO", "HEAVY_LIFT_HELO", "LIGHT_HELO"},
}
# default loadout when a mission doesn't name one: (mission_type, family) -> code
MISSION_LOADOUT = {
    ("AIR_DEFENCE_PATROL", "fighter"): "A2A_HEAVY", ("INTERCEPT", "fighter"): "A2A_HEAVY",
    ("STRIKE_EXERCISE", "fighter"): "A2G_PGM", ("CAS_EXERCISE", "fighter"): "CAS_ROCKETS",
    ("CAS_EXERCISE", "helo"): "CAS_ROCKETS", ("RECCE_ISR", "fighter"): "RECCE_POD", ("RECCE_ISR", "uav"): "ISR_PAYLOAD",
    ("RECCE_ISR", "uas"): "ISR_PAYLOAD",
}
CARGO_MISSIONS = {"AIRLIFT", "HADR", "CASEVAC", "PARA_DROP", "SAR"}

# ---------------------------------------------------------------- mission templates for the generator
FIGHTER_AD = ["FIGHTER_MULTIROLE", "AIR_SUPERIORITY"]
FIGHTER_STRIKE = ["FIGHTER_MULTIROLE", "STRIKE"]
TRANSPORTS = ["TRANSPORT_STRATEGIC", "TRANSPORT_TACTICAL", "TRANSPORT_LIGHT"]
HELOS = ["UTILITY_HELO", "HEAVY_LIFT_HELO", "LIGHT_HELO"]
# type: (priority weights P1..P4, eligible roles, required aircraft (min, max), on-station min, per operational command per day)
MISSION_TEMPLATES = {
    "AIR_DEFENCE_PATROL": ((30, 50, 20, 0), FIGHTER_AD, (2, 2), 60, 4),
    "RECCE_ISR": ((5, 45, 50, 0), ["UAV_MALE", "UAV_TACTICAL", "FIGHTER_MULTIROLE"], (1, 1), 120, 2),
    "AEW_SUPPORT": ((40, 60, 0, 0), ["AEW_C"], (1, 1), 180, 0.6),
    "AAR_SUPPORT": ((0, 60, 40, 0), ["TANKER"], (1, 1), 90, 0.6),
    "AIRLIFT": ((0, 40, 50, 10), TRANSPORTS + ["HEAVY_LIFT_HELO", "UTILITY_HELO"], (1, 2), 45, 2),
    "HADR": ((20, 60, 20, 0), TRANSPORTS + HELOS, (2, 2), 60, 0.5),
    "CASEVAC": ((60, 40, 0, 0), ["UTILITY_HELO", "LIGHT_HELO"], (1, 1), 20, 0.8),
    "STRIKE_EXERCISE": ((0, 10, 60, 30), FIGHTER_STRIKE, (2, 4), 20, 1.2),
    "CAS_EXERCISE": ((0, 10, 60, 30), ["FIGHTER_MULTIROLE", "STRIKE", "ATTACK_HELO"], (2, 2), 30, 0.8),
    "TRAINING": ((0, 0, 40, 60), FIGHTER_AD + FIGHTER_STRIKE + ["TRAINER_ADVANCED"], (2, 2), 40, 3),
}
MISSION_LABEL = {
    "AIR_DEFENCE_PATROL": ("CAP", "Combat air patrol"), "RECCE_ISR": ("ISR", "ISR coverage"),
    "AEW_SUPPORT": ("AEW", "AEW&C orbit"), "AAR_SUPPORT": ("AAR", "Air-to-air refuelling track"),
    "AIRLIFT": ("ALT", "Airlift"), "HADR": ("HADR", "Disaster relief"), "CASEVAC": ("CEV", "Casualty evacuation"),
    "STRIKE_EXERCISE": ("STX", "Strike exercise"), "CAS_EXERCISE": ("CAS", "CAS exercise"),
    "TRAINING": ("TRG", "Training"), "INTERCEPT": ("INT", "Intercept"), "SAR": ("SAR", "Search and rescue"),
    "PARA_DROP": ("PDR", "Para drop"),
}
MOUNTAIN_ELEVATION_M = 2500     # targets above this need MOUNTAIN_FLYING crew
