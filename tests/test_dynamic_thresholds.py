from __future__ import annotations

import pytest

from stock_analyzer import dynamic_thresholds as dt


def test_fixed_when_k_zero_or_no_vol():
    # k=0 は固定値=現行挙動(フォールバック)
    assert dt.rsi_oversold(vol_pct=0.9, k=0.0) == 30.0
    assert dt.rsi_overbought(vol_pct=0.1, k=0.0) == 70.0
    # vol_pct=None も固定値
    assert dt.bollinger_sigma(vol_pct=None, k=1.0) == 2.0


def test_rsi_oversold_deeper_in_high_vol():
    # 高ボラ(vol_pct>0.5)では売られすぎ閾値が下がる(より深い押しを要求)
    low_vol = dt.rsi_oversold(vol_pct=0.1, k=1.0)
    high_vol = dt.rsi_oversold(vol_pct=0.9, k=1.0)
    assert high_vol < 30.0 < low_vol


def test_thresholds_are_clamped():
    # 極端な vol_pct でも範囲内にクランプ
    assert 20.0 <= dt.rsi_oversold(vol_pct=1.0, k=5.0) <= 40.0
    assert 60.0 <= dt.rsi_overbought(vol_pct=1.0, k=5.0) <= 80.0
    assert 1.0 <= dt.atr_stop_mult(vol_pct=1.0, k=5.0) <= 4.0


def test_dynamic_threshold_continuity_at_median():
    # vol_pct=0.5 では基準値に一致(中央で連続)
    assert dt.momentum_threshold(vol_pct=0.5, k=2.0) == pytest.approx(3.0)
