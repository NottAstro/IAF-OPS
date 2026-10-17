"""Writes docs/MODEL_CARD_SNAG_RISK.md (ARCHITECTURE D38). An evaluation tool, not part of the planner: it is the one
place allowed to compare the snag-risk model with the simulated world's own defect law (sim/reliability.py), which
gives the best ranking any model could reach on this data.

    python -m app.decide.model_card [path]
"""
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from ..db import SessionLocal
from ..sim import reliability as REL
from . import predict as PR


def oracle(X: np.ndarray, ids: list, tails: dict) -> np.ndarray:
    """The simulator's true defect probability for each row (features carry everything except the hidden lemon factor)."""
    fam = {i: f for i, f in enumerate(PR.FAMILIES)}
    out = []
    for x, aid in zip(X, ids):
        hot = [k for k in range(len(PR.FAMILIES)) if x[6 + k] > 0.5]
        family = fam[hot[0]] if hot else "transport"
        out.append(REL.p_defect(x[0], x[3] * 30, x[4], family, tails.get(aid, "")))
    return np.array(out)


def build(path: Path) -> dict:
    from sqlalchemy import text
    with SessionLocal() as db:
        X, y, ts, ids = PR.dataset(db, with_ids=True)
        tails = dict(db.execute(text("SELECT id, tail_no FROM aircraft")).all())
        m = PR.train(db, store=False)
    order = np.argsort(np.array([t.timestamp() for t in ts]))
    cut = int(len(order) * 0.8)
    tr, te = order[:cut], order[cut:]
    w, mean, sd = PR.fit(X[tr], y[tr])
    p = PR.predict_all(w, mean, sd, X[te])
    yt = y[te]
    base = float(y[tr].mean())
    rule = X[te][:, 1]                                   # "hours since maintenance" rule: rank by wear alone
    o = oracle(X[te], [ids[i] for i in te], tails)
    rows = {"model": PR.evaluate(yt, p, base), "oracle": PR.evaluate(yt, o, base), "rule": {"auc": round(PR.auc(yt, rule), 3)}}
    t = rows["model"]
    co = m.metrics["coefficients"]
    truth = {"wear_sq": REL.WEAR, "fresh": REL.FRESH, "age_30y": REL.AGE, "sortie_h": REL.HOURS,
             **{f"fam_{f}": REL.FAMILY[f] - REL.FAMILY["transport"] for f in PR.FAMILIES}}
    lines = [
        "# Model card — snag-risk (ARCHITECTURE D38)", "",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M} by `python -m app.decide.model_card` from the seeded database. "
        "Everything here is SIMULATED: synthetic aircraft, synthetic maintenance history._", "",
        "## What it does",
        "Predicts the chance that a given tail develops a defect on a sortie: found at pre-flight (the tail is swapped or "
        "the sortie cancelled), in flight (abort, RTB) or at the post-flight inspection (rectification before the next "
        "sortie). The planner gives P1/P2 packages the free tails with the lowest predicted risk (in 2-point bands, so "
        "fleet-hours balancing still decides between near-equal tails), shows the risk per tail and per package in the "
        "explanation, totals expected defects per plan, and subtracts expected defects in the base forecast.", "",
        "**Intended use:** decision support for the duty planner and the station's engineering officer. "
        "**Not for:** grounding or releasing an aircraft; the engineering officer's serviceability call stands.", "",
        "## Data",
        f"- {len(y):,} tail-sorties ({int(y.sum()):,} with a defect, {100 * y.mean():.1f} %) from the generator's 90-day history "
        "plus anything the simulator has flown since (`sortie_aircraft.hsm_at_launch` joined to `maintenance_event`).",
        f"- Time split: train on sorties before {ts[tr[-1]]:%Y-%m-%d %H:%M}Z ({len(tr):,}), test on the newest 20 % ({len(te):,}). "
        "The deployed model is then refitted on everything.",
        "- Label: any PREFLIGHT, AIRBORNE or POSTFLIGHT maintenance event for that tail on that sortie. Sorties cancelled "
        "for crew or weather are left out (the aircraft was never tested).", "",
        "## Method",
        "Logistic regression on standardised features, fitted by Newton's method with an L2 penalty of 1.0 (intercept "
        "unpenalised). Deterministic, about a second to train, one readable coefficient per feature.", "",
        "| Feature | Meaning | Learned (log-odds per unit) | Simulated truth |", "|---|---|---:|---:|",
    ]
    for f in PR.FEATURES:
        tv = truth.get(f)
        lines.append(f"| `{f}` | {PR.LABEL[f]} | {co[f]:+.3f} | {'' if tv is None else f'{tv:+.2f}'} |")
    lines += [
        "", "`wear` and `wear_sq` together describe one curve (the truth is purely quadratic). `recent_defects` has no "
        "direct truth: it stands in for each tail's hidden reliability (\"lemon\" factor, SD "
        f"{REL.LEMON_SD}), which only shows up as a history of defects.", "",
        "## Results on held-out sorties", "",
        "| | AUC | Brier | Brier skill | Log loss | Top-10 % lift |", "|---|---:|---:|---:|---:|---:|",
        f"| **Snag-risk model** | **{t['auc']:.3f}** | {t['brier']:.4f} | {t['brier_skill']:.3f} | {t['log_loss']:.4f} | {t['top_decile_lift']:.2f}× |",
        f"| Base rate only | 0.500 | {t['brier_base_rate']:.4f} | 0 | | 1.00× |",
        f"| Rule: hours since maintenance | {rows['rule']['auc']:.3f} | | | | |",
        f"| Ceiling: the simulator's own law | {rows['oracle']['auc']:.3f} | {rows['oracle']['brier']:.4f} | {rows['oracle']['brier_skill']:.3f} | "
        f"{rows['oracle']['log_loss']:.4f} | {rows['oracle']['top_decile_lift']:.2f}× |", "",
        f"The model reaches {100 * (t['auc'] - 0.5) / max(1e-9, rows['oracle']['auc'] - 0.5):.0f} % of the achievable ranking gain "
        "over guessing. Defects are rare and mostly random, so Brier skill is small for any model, the true law included.", "",
        "### Calibration (tenths of predicted risk)", "", "| Tenth | Predicted | Seen | Sorties |", "|---:|---:|---:|---:|",
    ]
    for i, d in enumerate(t["calibration"]):
        lines.append(f"| {i + 1} | {100 * d['predicted']:.1f} % | {100 * d['observed']:.1f} % | {d['n']:,} |")
    lines += [
        "", "## Limits",
        "- Synthetic: the defect law was written for this prototype (`backend/app/sim/reliability.py`). The model card "
        "shows the method recovers a known law; it says nothing about real IAF fleets.",
        "- Static features only: no component-level data, no environment (heat, dust, salt), no maintenance-crew effects.",
        "- Drift: the simulator keeps adding to the log; retrain from Admin → Snag-risk model (or `POST "
        "/api/v1/ops/models/snag-risk/train`). Each model is stored in `ml_model` with its metrics; the newest is used.", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return rows


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "docs" / "MODEL_CARD_SNAG_RISK.md"
    r = build(out)
    print(f"{out}: model AUC {r['model']['auc']}, ceiling {r['oracle']['auc']}, rule {r['rule']['auc']}")
