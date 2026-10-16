"""Generator policy (DATA_MODEL §8.16). All values are SIMULATED policy, tune freely.

ponytail: a Python module instead of config.yaml — no YAML dependency, same role.
"""

HISTORY_DAYS = 90
DETACHED_FRACTION = 0.06

COMMANDS = {  # code: (name, hq name, lon, lat, operational)
    "WAC": ("Western Air Command", "New Delhi (Subroto Park)", 77.16, 28.59, True),
    "SWAC": ("South Western Air Command", "Gandhinagar", 72.65, 23.22, True),
    "CAC": ("Central Air Command", "Prayagraj", 81.84, 25.44, True),
    "EAC": ("Eastern Air Command", "Shillong", 91.87, 25.55, True),
    "SAC": ("Southern Air Command", "Thiruvananthapuram", 76.95, 8.50, True),
    "TC": ("Training Command", "Bengaluru", 77.59, 12.97, False),
    "MC": ("Maintenance Command", "Nagpur", 79.09, 21.15, False),
}

ROLE_FAMILY = {  # aircraft_type.role -> (family, base role tag)
    "FIGHTER_MULTIROLE": ("fighter", "FIGHTER"), "AIR_SUPERIORITY": ("fighter", "FIGHTER"),
    "STRIKE": ("fighter", "FIGHTER"), "TRAINER_BASIC": ("trainer", "TRAINING"),
    "TRAINER_INTERMEDIATE": ("trainer", "TRAINING"), "TRAINER_ADVANCED": ("trainer", "TRAINING"),
    "TRANSPORT_STRATEGIC": ("transport", "TRANSPORT"), "TRANSPORT_TACTICAL": ("transport", "TRANSPORT"),
    "TRANSPORT_LIGHT": ("transport", "TRANSPORT"), "VIP_TRANSPORT": ("transport", "TRANSPORT"),
    "TANKER": ("transport", "TANKER"), "AEW_C": ("transport", "AEW"), "ISR": ("transport", "TRANSPORT"),
    "UTILITY_HELO": ("helo", "HELO"), "ATTACK_HELO": ("helo", "HELO"), "HEAVY_LIFT_HELO": ("helo", "HELO"),
    "LIGHT_HELO": ("helo", "HELO"), "UAV_MALE": ("uav", "UAV"), "UAV_TACTICAL": ("uav", "UAV"),
    "SMALL_UAS": ("uas", "FIGHTER"),
}
UE_CAP = {"fighter": 22, "trainer": 60, "transport": 18, "helo": 18, "uav": 10, "uas": 10}
ROLE_UE_CAP = {"TRANSPORT_STRATEGIC": 17, "TRANSPORT_LIGHT": 22, "TANKER": 6, "AEW_C": 3}

SERVICEABILITY = {"fighter": 0.66, "trainer": 0.76, "transport": 0.72, "helo": 0.68, "uav": 0.80, "uas": 0.90}
SERVICEABILITY_BY_TYPE = {"Rafale": 0.85, "Su-30MKI": 0.62}
ANNUAL_HOURS = {"fighter": (150, 200), "trainer": (300, 450), "transport": (400, 700), "helo": (250, 400),
                "uav": (800, 1200), "uas": (50, 100)}
SERVICE_WINDOW = {  # induction years
    "Su-30MKI": (2002, 2022), "Rafale": (2020, 2022), "Tejas Mk1": (2016, 2023), "MiG-29": (1987, 1990),
    "Mirage 2000": (1985, 2004), "Jaguar": (1979, 2008), "Il-78MKI": (2003, 2004), "A-50EI": (2009, 2011),
    "Netra EMB-145I": (2017, 2021), "C-17A": (2013, 2019), "Il-76MD": (1985, 1990), "C-130J-30": (2011, 2017),
    "C-295W": (2023, 2025), "An-32": (1984, 1991), "Do-228": (1990, 2018), "Mi-17V-5": (2011, 2016),
    "Dhruv": (2004, 2016), "Rudra": (2013, 2017), "Prachand LCH": (2022, 2023), "AH-64E": (2019, 2020),
    "Mi-35": (1990, 1992), "CH-47F": (2019, 2020), "Cheetah/Chetak": (1970, 1990), "Hawk 132": (2008, 2016),
    "Kiran": (1975, 1989), "PC-7 Mk II": (2013, 2015), "HTT-40": (2025, 2025), "Heron Mk II": (2021, 2023),
    "Searcher Mk II": (2002, 2006), "Small UAS (generic)": (2023, 2025),
}

# crew per aircraft by family: list of (aircrew_role, ratio per aircraft)
CREW_RATIO = {
    "fighter": [("PILOT", 1.25)], "fighter2": [("PILOT", 1.2), ("WSO", 1.2)],
    "transport": [("PILOT", 2.0), ("NAVIGATOR", 0.6), ("FLIGHT_ENGINEER", 0.8), ("LOADMASTER", 0.6)],
    "helo": [("PILOT", 2.0), ("FLIGHT_ENGINEER", 1.0)], "trainer": [("PILOT", 0.5)],
    "uav": [("RPA_PILOT", 2.0), ("PAYLOAD_OPERATOR", 2.0)], "uas": [("RPA_PILOT", 0.5)],
}
STREAM = {"fighter": "FIGHTER", "fighter2": "FIGHTER", "transport": "TRANSPORT", "helo": "HELICOPTER",
          "trainer": "FIGHTER", "uav": "RPA", "uas": "RPA"}
HOURS_PER_YEAR = {"FIGHTER": 150, "TRANSPORT": 350, "HELICOPTER": 250, "RPA": 400}
YEARS_BY_RANK = {"FG_OFFR": (0.3, 2), "FLT_LT": (2, 6), "SQN_LDR": (6, 13), "WG_CDR": (13, 20), "GP_CAPT": (20, 26)}
DUTY_MIX = [("ON_DUTY", 40), ("STANDBY", 10), ("OFF_DUTY", 35), ("CREW_REST", 5), ("LEAVE", 6), ("COURSE", 3),
            ("SICK", 1)]
MEDICAL_MIX = [("FIT_FULL", 90), ("FIT_RESTRICTED", 5), ("TEMP_UNFIT", 3), ("FIT_FULL_EXPIRING", 2)]

SORTIE_RATE = {"fighter": 0.5, "trainer": 1.1, "transport": 0.45, "helo": 0.6, "uav": 0.3, "uas": 0.5}  # per aircraft-day
SORTIE_HOURS = {"fighter": (0.75, 1.5), "trainer": (0.75, 1.25), "transport": (2, 6), "helo": (1, 2),
                "uav": (8, 20), "uas": (0.3, 0.6)}
MISSION_MIX = {
    "fighter": [("TRAINING", 60), ("AIR_DEFENCE_PATROL", 20), ("STRIKE_EXERCISE", 10), ("CAS_EXERCISE", 5),
                ("FUNCTIONAL_CHECK", 5)],
    "trainer": [("TRAINING", 100)],
    "transport": [("AIRLIFT", 60), ("TRAINING", 20), ("PARA_DROP", 10), ("HADR", 5), ("CASEVAC", 5)],
    "helo": [("TRAINING", 40), ("AIRLIFT", 30), ("CASEVAC", 10), ("SAR", 10), ("HADR", 10)],
    "uav": [("RECCE_ISR", 100)], "uas": [("RECCE_ISR", 100)],
}
PRIORITY_MIX = [("P1", 5), ("P2", 20), ("P3", 50), ("P4", 25)]

GROUND_PER_AIRCRAFT = {"AIRFRAME": 1.5, "ENGINE": 1.2, "AVIONICS": 1.0, "ELECTRICAL": 0.6, "ARMAMENT": 0.6}
GROUND_FIXED = {"POL": 12, "ATC": 12, "MET": 6, "MT": 20, "FIRE_CRASH_RESCUE": 30, "STORES": 15, "MEDICAL": 10,
                "SECURITY": 60, "RADAR_TECH": 8, "COMMS_TECH": 10}

ATF_CAPACITY_ML = {  # (base kind) -> (min, max) million litres
    "fighter_L": (3, 6), "fighter": (2, 4), "transport_L": (5, 10), "transport": (1.5, 3), "helo": (0.5, 1.5),
    "training": (1, 3), "maint": (1, 2), "alg": (0.1, 0.5), "other": (0.5, 1.5),
}
FUEL_RESERVE, FUEL_REORDER = 0.15, 0.40
ATF_DENSITY = 0.8  # kg/L

DEMO_BASE_COMMANDERS = ["VIAX", "VETZ", "VIJO"]
