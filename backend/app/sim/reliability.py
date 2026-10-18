"""Ground truth for defects in the simulated world (ARCHITECTURE D38). The generator and the simulator draw defects
from this law; the planner never sees it. decide/predict.py has to learn the risk from the maintenance log, the way a
real squadron would, so its model card reports how well it recovers this law on held-out sorties.

Per tail per sortie, the chance of a defect rises with the share of the inspection interval used (squared: wear-out),
is higher just after maintenance (maintenance-induced faults), with airframe age, with sortie length and by type
family, plus a hidden per-tail "lemon" factor that only shows up as a history of defects.
"""
import math
import random

BASE = -5.0
WEAR = 2.4            # x (hours since maintenance / interval) squared
FRESH = 0.9           # within the first 5 % of the interval
AGE = 0.8             # per 30 years since induction
HOURS = 0.18          # per sortie hour
FAMILY = {"fighter": 0.3, "helo": 0.4, "transport": 0.0, "uav": 0.2, "uas": 0.3, "trainer": -0.1}
LEMON_SD = 0.5
# where a defect shows up
STAGES = (("PREFLIGHT", 0.2), ("AIRBORNE", 0.2), ("POSTFLIGHT", 0.6))


def lemon(tail: str) -> float:
    return random.Random(f"lemon:{tail}").gauss(0, LEMON_SD)


def p_defect(frac: float, age_y: float, dur_h: float, family: str, tail: str) -> float:
    z = BASE + WEAR * min(frac, 1.2) ** 2 + (FRESH if frac < 0.05 else 0) + AGE * age_y / 30 + HOURS * dur_h + \
        FAMILY.get(family, 0) + lemon(tail)
    return 1 / (1 + math.exp(-z))


def stage(u: float) -> str:
    """Which stage a defect appears at, from a uniform draw."""
    acc = 0.0
    for name, share in STAGES:
        acc += share
        if u < acc:
            return name
    return STAGES[-1][0]
