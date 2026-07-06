from __future__ import annotations

import numpy as np

from stock_analyzer import validation
from stock_analyzer.research import audit_features, build_adopted_model


def _synthetic(n_days=800, per_day=10, seed=0):
    rng = np.random.default_rng(seed)
    n = n_days * per_day
    dates = np.repeat(np.arange(n_days), per_day)
    regimes = np.where((dates // 100) % 2 == 0, "上昇", "下落")
    # good: 成立時に一貫して +3% 上乗せ / noise: 無情報 / bad: 成立時に -3%
    good = rng.random(n) < 0.2
    noise = rng.random(n) < 0.2
    bad = rng.random(n) < 0.2
    base = rng.normal(0.0, 3.0, size=n)
    ret = base + good * 3.0 - bad * 3.0
    return dates, ret, regimes, {"good": good, "noise": noise, "bad": bad}


def test_feature_generalization_detects_edge_and_regimes():
    dates, ret, regimes, feats = _synthetic()
    gen = validation.feature_generalization(dates, ret, feats["good"], regimes, n_folds=5, embargo=5)
    assert gen["uplift_ci"]["low"] > 0  # OOSで有意にプラス
    assert set(gen["regime_uplifts"]) <= {"上昇", "下落"}


def test_audit_assigns_expected_verdicts():
    dates, ret, regimes, feats = _synthetic()
    audit = audit_features(dates, ret, feats, regimes, n_folds=5, embargo=5)
    verdicts = {a["feature"]: a["verdict"] for a in audit}
    assert verdicts["good"] == "keep"  # 全相場でプラス → 採用
    assert verdicts["bad"] == "drop"  # 一貫してマイナス → 棄却
    assert verdicts["noise"] in ("drop", "downweight")  # 無情報は採用されない(keepにはならない)
    assert verdicts["noise"] != "keep"


def test_build_adopted_model_shrinks_and_lists_rejected():
    dates, ret, regimes, feats = _synthetic()
    audit = audit_features(dates, ret, feats, regimes, n_folds=5, embargo=5)
    model = build_adopted_model(audit)
    assert "good" in model["features"]
    assert model["features"]["good"]["weight"] > 0
    assert model["features"]["good"]["verdict"] == "keep"
    # bad は rejected に理由付きで載る
    rejected_names = {r["feature"] for r in model["rejected"]}
    assert "bad" in rejected_names
    # メタに手法・除外事項が記録される
    assert "excluded" in model["metadata"]


def test_adopted_weights_shrunk_toward_mean():
    # 収縮により、生の上乗せ点推定よりも重みの散らばりが小さくなる
    dates, ret, regimes, feats = _synthetic()
    audit = audit_features(dates, ret, feats, regimes, n_folds=5, embargo=5)
    model = build_adopted_model(audit, shrink=0.5)
    kept = [a for a in audit if a["verdict"] in ("keep", "downweight")]
    if len(kept) >= 2:
        raw = np.array([(a["generalization"]["uplift_ci"]["point"] or 0.0) for a in kept])
        weights = np.array([model["features"][a["feature"]]["weight"] for a in kept])
        assert weights.std() <= raw.std() + 1e-9
