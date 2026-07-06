from __future__ import annotations

import numpy as np
import pytest

from stock_analyzer import validation


def test_time_series_folds_no_leakage():
    """全fold で 学習日 < 検証日 を厳守(未来データのリーク無し)。"""
    dates = np.repeat(np.arange(60), 3)  # 60営業日 × 各3トレード
    folds = validation.time_series_folds(dates, n_folds=4, scheme="expanding")
    assert len(folds) == 4
    for train_idx, test_idx in folds:
        assert dates[train_idx].max() < dates[test_idx].min()


def test_time_series_folds_embargo_excludes_recent_train():
    dates = np.arange(50)
    no_emb = validation.time_series_folds(dates, n_folds=4, scheme="expanding", embargo=0)
    emb = validation.time_series_folds(dates, n_folds=4, scheme="expanding", embargo=3)
    # embargo付きは各foldで学習の最終日が検証開始より さらに手前
    for (tr0, te0), (tr1, te1) in zip(no_emb, emb):
        assert dates[tr1].max() <= dates[te1].min() - 3
        assert dates[tr1].max() <= dates[tr0].max()


def test_rolling_scheme_trains_only_on_previous_block():
    dates = np.arange(50)
    folds = validation.time_series_folds(dates, n_folds=4, scheme="rolling")
    # rolling は直前ブロックのみ学習 → expanding より学習件数が少ない
    exp = validation.time_series_folds(dates, n_folds=4, scheme="expanding")
    assert len(folds[-1][0]) < len(exp[-1][0])
    for train_idx, test_idx in folds:
        assert dates[train_idx].max() < dates[test_idx].min()


def test_purged_kfold_excludes_embargo_around_test():
    dates = np.arange(100)
    folds = validation.purged_kfold_folds(dates, k=5, embargo=2)
    assert len(folds) == 5
    for train_idx, test_idx in folds:
        lo, hi = dates[test_idx].min(), dates[test_idx].max()
        # 学習は検証ブロックの前後 embargo を含まない
        assert not ((dates[train_idx] >= lo - 2) & (dates[train_idx] <= hi + 2)).any()


def test_rolling_walk_forward_detects_real_edge():
    """スコアが将来リターンと真に相関するとき、上位群のOOS期待値がベースを上回る。"""
    rng = np.random.default_rng(0)
    n = 6000
    dates = np.repeat(np.arange(600), 10)
    signal = rng.normal(0, 1, size=n)
    ret = signal * 2.0 + rng.normal(0, 3.0, size=n)  # signalが高いほど高リターン

    # fit_predict は学習窓の情報のみ使う想定(ここでは signal をそのまま返すだけ)
    def fit_predict(train_idx, test_idx):
        return signal[test_idx]

    result = validation.rolling_walk_forward(
        dates, ret, fit_predict, n_folds=5, top_quantile=0.2, seed=1
    )
    assert result["n_folds"] == 5
    assert result["oos_top_ev"] > result["oos_baseline_ev"]
    assert result["oos_top_ev_ci"]["low"] > 0  # 有意にプラス
    assert result["oos_uplift_positive_fraction"] >= 0.8


def test_rolling_walk_forward_no_edge_ci_includes_zero():
    """スコアが無情報(乱数)なら上乗せは有意にならない。"""
    rng = np.random.default_rng(2)
    n = 6000
    dates = np.repeat(np.arange(600), 10)
    ret = rng.normal(0.0, 3.0, size=n)
    noise = rng.normal(0, 1, size=n)

    def fit_predict(train_idx, test_idx):
        return noise[test_idx]

    result = validation.rolling_walk_forward(dates, ret, fit_predict, n_folds=5, seed=3)
    assert result["oos_top_ev_ci"]["low"] <= 0  # 0を含む/下回る＝有意でない


def test_sensitivity_and_is_flat():
    # 平坦な曲面
    flat = validation.sensitivity([0, 1, 2, 3], lambda p: 1.0 + 0.01 * p)
    assert validation.is_flat(flat, tolerance=0.1)
    # 尖った曲面(1点だけ跳ねる)
    spike = validation.sensitivity([0, 1, 2, 3], lambda p: 5.0 if p == 2 else 1.0)
    assert not validation.is_flat(spike, tolerance=0.1)
    assert spike["best_param"] == 2


def test_evaluate_gate_keep_downweight_drop():
    # keep: CI下限>margin・相場2個以上・感度平坦
    keep = validation.evaluate_gate(
        {"low": 0.5, "point": 1.0, "high": 1.5},
        {"上昇": 1.2, "下落": 0.3, "横ばい": -0.1},
        sensitivity_flat=True,
    )
    assert keep["verdict"] == "keep"

    # downweight: CI下限は正だが相場1個 or 感度尖り
    dw = validation.evaluate_gate(
        {"low": 0.2, "point": 0.6, "high": 1.0},
        {"上昇": 1.0, "下落": -0.2, "横ばい": -0.3},
        sensitivity_flat=False,
    )
    assert dw["verdict"] == "downweight"

    # drop: CI下限が0以下
    drop = validation.evaluate_gate(
        {"low": -0.3, "point": 0.4, "high": 1.1},
        {"上昇": 0.5},
        sensitivity_flat=True,
    )
    assert drop["verdict"] == "drop"

    # drop: CIなし(標本不足)
    none = validation.evaluate_gate(None, {}, sensitivity_flat=True)
    assert none["verdict"] == "drop"


def test_folds_empty_when_too_few_dates():
    assert validation.time_series_folds(np.array([1, 2]), n_folds=5) == []
    assert validation.purged_kfold_folds(np.array([1, 2]), k=5) == []
