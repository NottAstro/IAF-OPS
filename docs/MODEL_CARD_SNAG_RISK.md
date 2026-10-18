# Model card — snag-risk (ARCHITECTURE D38)

_Generated 2026-10-17 20:23 by `python -m app.decide.model_card` from the seeded database. Everything here is SIMULATED: synthetic aircraft, synthetic maintenance history._

## What it does
Predicts the chance that a given tail develops a defect on a sortie: found at pre-flight (the tail is swapped or the sortie cancelled), in flight (abort, RTB) or at the post-flight inspection (rectification before the next sortie). The planner gives P1/P2 packages the free tails with the lowest predicted risk (in 2-point bands, so fleet-hours balancing still decides between near-equal tails), shows the risk per tail and per package in the explanation, totals expected defects per plan, and subtracts expected defects in the base forecast.

**Intended use:** decision support for the duty planner and the station's engineering officer. **Not for:** grounding or releasing an aircraft; the engineering officer's serviceability call stands.

## Data
- 90,699 tail-sorties (5,618 with a defect, 6.2 %) from the generator's 90-day history plus anything the simulator has flown since (`sortie_aircraft.hsm_at_launch` joined to `maintenance_event`).
- Time split: train on sorties before 2026-09-28 13:35Z (72,559), test on the newest 20 % (18,140). The deployed model is then refitted on everything.
- Label: any PREFLIGHT, AIRBORNE or POSTFLIGHT maintenance event for that tail on that sortie. Sorties cancelled for crew or weather are left out (the aircraft was never tested).

## Method
Logistic regression on standardised features, fitted by Newton's method with an L2 penalty of 1.0 (intercept unpenalised). Deterministic, about a second to train, one readable coefficient per feature.

| Feature | Meaning | Learned (log-odds per unit) | Simulated truth |
|---|---|---:|---:|
| `wear` | share of the inspection interval used | +0.806 |  |
| `wear_sq` | the same, squared (wear-out) | +1.559 | +2.40 |
| `fresh` | inside the first 5 % of the interval (just out of maintenance) | +0.865 | +0.90 |
| `age_30y` | airframe age (per 30 years) | +0.717 | +0.80 |
| `sortie_h` | planned sortie length (h) | +0.157 | +0.18 |
| `recent_defects` | defects on this tail in the last 30 days | +0.172 |  |
| `fam_fighter` | fighter (vs transport) | +0.249 | +0.30 |
| `fam_helo` | helo (vs transport) | +0.308 | +0.40 |
| `fam_uav` | uav (vs transport) | +0.281 | +0.20 |
| `fam_uas` | uas (vs transport) | +0.311 | +0.30 |
| `fam_trainer` | trainer (vs transport) | -0.173 | -0.10 |

`wear` and `wear_sq` together describe one curve (the truth is purely quadratic). `recent_defects` has no direct truth: it stands in for each tail's hidden reliability ("lemon" factor, SD 0.5), which only shows up as a history of defects.

## Results on held-out sorties

| | AUC | Brier | Brier skill | Log loss | Top-10 % lift |
|---|---:|---:|---:|---:|---:|
| **Snag-risk model** | **0.740** | 0.0542 | 0.061 | 0.2077 | 3.37× |
| Base rate only | 0.500 | 0.0577 | 0 | | 1.00× |
| Rule: hours since maintenance | 0.675 | | | | |
| Ceiling: the simulator's own law | 0.759 | 0.0531 | 0.080 | 0.2027 | 3.61× |

The model reaches 93 % of the achievable ranking gain over guessing. Defects are rare and mostly random, so Brier skill is small for any model, the true law included.

### Calibration (tenths of predicted risk)

| Tenth | Predicted | Seen | Sorties |
|---:|---:|---:|---:|
| 1 | 1.3 % | 1.4 % | 1,814 |
| 2 | 1.8 % | 1.7 % | 1,814 |
| 3 | 2.3 % | 2.0 % | 1,814 |
| 4 | 2.9 % | 2.8 % | 1,814 |
| 5 | 3.6 % | 4.2 % | 1,814 |
| 6 | 4.6 % | 4.5 % | 1,814 |
| 7 | 5.9 % | 6.0 % | 1,814 |
| 8 | 7.9 % | 7.7 % | 1,814 |
| 9 | 11.3 % | 10.4 % | 1,814 |
| 10 | 20.8 % | 20.7 % | 1,814 |

## Limits
- Synthetic: the defect law was written for this prototype (`backend/app/sim/reliability.py`). The model card shows the method recovers a known law; it says nothing about real IAF fleets.
- Static features only: no component-level data, no environment (heat, dust, salt), no maintenance-crew effects.
- Drift: the simulator keeps adding to the log; retrain from Admin → Snag-risk model (or `POST /api/v1/ops/models/snag-risk/train`). Each model is stored in `ml_model` with its metrics; the newest is used.
