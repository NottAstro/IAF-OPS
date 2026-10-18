"""Snag-risk model (ARCHITECTURE D38, PRD FR-FCT-03): the chance that a given tail develops a defect on a sortie, found
before, during or after it. Learned from the maintenance log (maintenance_event) joined to the sorties each tail flew
(sortie_aircraft.hsm_at_launch); it never reads the simulator's own law (sim/reliability.py).

Logistic regression, fitted by Newton's method with a small L2 penalty: deterministic, explainable (one coefficient
per feature), fast enough to retrain on demand. The newest `ml_model` row named "snag_risk" is the one in use; with no
row yet, the first caller trains and stores one. Metrics come from a time split (train on older sorties, test on the
newest 20 %), then the deployed model is refitted on everything.
"""
import bisect
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from generator import config as GC

from .. import models as M

log = logging.getLogger("decide.predict")
NAME = "snag_risk"
RECENT_DAYS = 30
FAMILIES = ("fighter", "helo", "uav", "uas", "trainer")      # transport is the reference family
FEATURES = ["wear", "wear_sq", "fresh", "age_30y", "sortie_h", "recent_defects", *[f"fam_{f}" for f in FAMILIES]]
LABEL = {"wear": "share of the inspection interval used", "wear_sq": "the same, squared (wear-out)",
         "fresh": "inside the first 5 % of the interval (just out of maintenance)", "age_30y": "airframe age (per 30 years)",
         "sortie_h": "planned sortie length (h)", "recent_defects": f"defects on this tail in the last {RECENT_DAYS} days",
         **{f"fam_{f}": f"{f} (vs transport)" for f in FAMILIES}}
WHY = {"wear": "well into its inspection interval", "wear_sq": "close to its next inspection", "fresh": "just out of maintenance",
       "age_30y": "older airframe", "sortie_h": "long sortie", "recent_defects": "recent defects on this tail",
       **{f"fam_{f}": f"{f} type" for f in FAMILIES}}
L2 = 1.0


def features(frac: float, age_y: float, dur_h: float, family: str, recent: int) -> list[float]:
    f = min(max(frac, 0.0), 1.2)
    return [f, f * f, 1.0 if f < 0.05 else 0.0, age_y / 30, dur_h, float(min(recent, 3)),
            *[1.0 if family == x else 0.0 for x in FAMILIES]]


@dataclass
class Model:
    id: int | None
    coef: np.ndarray            # intercept first, then one per FEATURES (on standardised inputs)
    mean: np.ndarray
    sd: np.ndarray
    metrics: dict
    data_until: datetime | None = None

    def p(self, frac: float, age_y: float, dur_h: float, family: str, recent: int = 0) -> float:
        x = (np.array(features(frac, age_y, dur_h, family, recent)) - self.mean) / self.sd
        z = float(self.coef[0] + x @ self.coef[1:])
        return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))

    def drivers(self, frac: float, age_y: float, dur_h: float, family: str, recent: int = 0, k: int = 2) -> list[str]:
        """The features pushing this tail's risk up the most (contribution vs the fleet average), in words."""
        x = (np.array(features(frac, age_y, dur_h, family, recent)) - self.mean) / self.sd
        contrib = x * self.coef[1:]
        out = []
        for i in np.argsort(-contrib)[:k]:
            if contrib[i] > 0.05 and WHY[FEATURES[i]] not in out:
                out.append(WHY[FEATURES[i]])
        return out


# ---------------------------------------------------------------- data
def dataset(db: Session, until: datetime | None = None, with_ids: bool = False):
    """One row per tail per sortie that was flown (or lost a tail at pre-flight): features, label, time (and aircraft
    ids, for evaluation tools)."""
    rows = db.execute(text("""
        SELECT sa.aircraft_id, a.induction_year, t.maint_interval_h, t.role, sa.hsm_at_launch AS hsm, s.planned_launch_ts AS ts,
               coalesce(e.planned_h, extract(epoch FROM s.planned_recovery_ts - s.planned_launch_ts) / 3600) AS planned_h,
               e.id IS NOT NULL AS y
        FROM sortie_aircraft sa JOIN sortie s ON s.id = sa.sortie_id
        JOIN aircraft a ON a.id = sa.aircraft_id JOIN aircraft_type t ON t.id = a.aircraft_type_id
        LEFT JOIN LATERAL (SELECT id, planned_h FROM maintenance_event e WHERE e.sortie_id = s.id AND e.aircraft_id = sa.aircraft_id
                           AND e.kind <> 'SCHEDULED' ORDER BY id LIMIT 1) e ON true
        WHERE sa.hsm_at_launch IS NOT NULL AND (CAST(:u AS timestamptz) IS NULL OR s.planned_launch_ts < :u)
          AND (s.status IN ('COMPLETED', 'LANDED', 'ABORTED') OR s.cancel_reason = 'AIRCRAFT_US')
        UNION ALL   -- a tail that failed pre-flight and was swapped out is no longer on the sortie: its row comes from the log
        SELECT e.aircraft_id, a.induction_year, t.maint_interval_h, t.role, e.hours_since_maint, e.ts, e.planned_h, true
        FROM maintenance_event e JOIN aircraft a ON a.id = e.aircraft_id JOIN aircraft_type t ON t.id = a.aircraft_type_id
        WHERE e.kind = 'PREFLIGHT' AND (CAST(:u AS timestamptz) IS NULL OR e.ts < :u) AND NOT EXISTS (
              SELECT 1 FROM sortie_aircraft sa WHERE sa.sortie_id = e.sortie_id AND sa.aircraft_id = e.aircraft_id)"""),
        {"u": until}).all()
    defects = defaultdict(list)
    for aid, ts in db.execute(text("SELECT aircraft_id, ts FROM maintenance_event WHERE kind <> 'SCHEDULED' ORDER BY ts")):
        defects[aid].append(ts)
    X, y, ts, ids = [], [], [], []
    for r in rows:
        past = defects.get(r.aircraft_id, [])
        recent = bisect.bisect_left(past, r.ts - timedelta(hours=1)) - bisect.bisect_left(past, r.ts - timedelta(days=RECENT_DAYS))
        age = r.ts.year - (r.induction_year or r.ts.year - 10) + 0.5
        X.append(features(r.hsm / max(1.0, r.maint_interval_h), age, float(r.planned_h or 1.0),
                          GC.ROLE_FAMILY.get(r.role, ("transport",))[0], recent))
        y.append(1.0 if r.y else 0.0)
        ts.append(r.ts)
        ids.append(r.aircraft_id)
    return (np.array(X), np.array(y), ts, ids) if with_ids else (np.array(X), np.array(y), ts)


# ---------------------------------------------------------------- fit + metrics
def fit(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean, sd = X.mean(0), X.std(0)
    sd[sd < 1e-9] = 1.0
    Z = np.hstack([np.ones((len(X), 1)), (X - mean) / sd])
    w = np.zeros(Z.shape[1])
    w[0] = math.log(max(y.mean(), 1e-6) / max(1 - y.mean(), 1e-6))
    pen = np.full(Z.shape[1], L2)
    pen[0] = 0.0                                  # intercept not penalised
    for _ in range(25):
        p = 1 / (1 + np.exp(-np.clip(Z @ w, -30, 30)))
        g = Z.T @ (y - p) - pen * w
        H = (Z * (p * (1 - p))[:, None]).T @ Z + np.diag(pen)
        step = np.linalg.solve(H, g)
        w += step
        if np.abs(step).max() < 1e-7:
            break
    return w, mean, sd


def predict_all(w, mean, sd, X) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(w[0] + ((X - mean) / sd) @ w[1:], -30, 30)))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve (Mann-Whitney, ties averaged)."""
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    ps = p[order]
    i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    n1 = y.sum()
    n0 = len(y) - n1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / max(1.0, n1 * n0))


def evaluate(y: np.ndarray, p: np.ndarray, base_rate: float) -> dict:
    eps = 1e-12
    brier = float(np.mean((p - y) ** 2))
    brier0 = float(np.mean((base_rate - y) ** 2))
    deciles = []
    order = np.argsort(p)
    for chunk in np.array_split(order, 10):
        if len(chunk):
            deciles.append({"predicted": round(float(p[chunk].mean()), 4), "observed": round(float(y[chunk].mean()), 4),
                            "n": int(len(chunk))})
    top = order[-max(1, len(order) // 10):]
    return {"n": int(len(y)), "defects": int(y.sum()), "base_rate": round(float(y.mean()), 4), "auc": round(auc(y, p), 3),
            "brier": round(brier, 5), "brier_base_rate": round(brier0, 5), "brier_skill": round(1 - brier / brier0, 3) if brier0 else 0,
            "log_loss": round(float(-np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))), 4),
            "top_decile_lift": round(float(y[top].mean() / max(y.mean(), eps)), 2), "calibration": deciles}


def train(db: Session, until: datetime | None = None, store: bool = True) -> Model:
    X, y, ts = dataset(db, until)
    if len(y) < 500 or y.sum() < 20:
        raise ValueError(f"not enough history to train ({len(y)} sorties, {int(y.sum())} defects)")
    order = np.argsort(np.array([t.timestamp() for t in ts]))
    cut = int(len(order) * 0.8)
    tr, te = order[:cut], order[cut:]
    w, mean, sd = fit(X[tr], y[tr])
    test = evaluate(y[te], predict_all(w, mean, sd, X[te]), float(y[tr].mean()))
    train_m = evaluate(y[tr], predict_all(w, mean, sd, X[tr]), float(y[tr].mean()))
    w, mean, sd = fit(X, y)                       # deploy: refit on all of it
    data_until = max(ts)
    metrics = {"test": test, "train": {k: train_m[k] for k in ("n", "defects", "auc", "brier", "brier_skill")},
               "split": {"train_until": ts[tr[-1]].isoformat(), "test_from": ts[te[0]].isoformat()},
               "coefficients": {FEATURES[i]: round(float(w[i + 1] / sd[i]), 4) for i in range(len(FEATURES))},
               "intercept": round(float(w[0] - (w[1:] * mean / sd).sum()), 4), "labels": LABEL}
    mid = None
    if store:
        row = M.MlModel(name=NAME, data_until=data_until, features=FEATURES, coef=[float(v) for v in w],
                        scale={"mean": [float(v) for v in mean], "sd": [float(v) for v in sd]}, metrics=metrics)
        db.add(row)
        db.flush()
        mid = row.id
        log.info("snag-risk model %s: test AUC %.3f, Brier skill %.3f on %d sorties", mid, test["auc"], test["brier_skill"], test["n"])
    return Model(mid, w, mean, sd, metrics, data_until)


_CACHE: dict[int, Model] = {}


def current(db: Session, train_if_missing: bool = True) -> Model | None:
    row = db.scalars(select(M.MlModel).where(M.MlModel.name == NAME).order_by(M.MlModel.id.desc())).first()
    if row is None or row.features != FEATURES:   # none yet, or stored by an older feature set
        return _train_apart() if train_if_missing else None
    if row.id not in _CACHE:
        _CACHE[row.id] = Model(row.id, np.array(row.coef), np.array(row.scale["mean"]), np.array(row.scale["sd"]),
                               row.metrics, row.data_until)
    return _CACHE[row.id]


def _train_apart() -> Model | None:
    """Train and store in a session of its own, so a caller's open transaction is never committed by accident."""
    from ..db import SessionLocal
    with SessionLocal() as s:
        try:
            m = train(s)
            s.commit()
            _CACHE[m.id] = m
            return m
        except ValueError as e:
            log.warning("snag-risk model not trained: %s", e)
            return None


def card(db: Session) -> dict:
    """The model card served by GET /ops/models/snag-risk."""
    m = current(db)
    if m is None:
        return {"name": NAME, "trained": False}
    row = db.get(M.MlModel, m.id) if m.id else None
    return {"name": NAME, "trained": True, "id": m.id, "trained_at": row.trained_at.isoformat() if row else None,
            "data_until": m.data_until.isoformat() if m.data_until else None, "features": FEATURES, "metrics": m.metrics,
            "method": "Logistic regression (Newton's method, L2 1.0) on the maintenance log; time split 80/20 for the "
                      "metrics, then refitted on all of it.", "simulated": True,
            "intended_use": "Rank tails by defect risk for priority packages and expected-defect forecasts. Decision "
                            "support only: the maintenance officer's serviceability call stands.",
            "limits": "Trained on SIMULATED history from a synthetic defect law; says nothing about real aircraft."}


def tail_risk(st, a, dur_h: float) -> float:
    """Predicted defect chance for an AircraftInfo on a sortie of dur_h hours (0 without a model)."""
    m = getattr(st, "snag", None)
    return m.p(a.frac, a.age_y, dur_h, a.family, a.recent) if m else 0.0
