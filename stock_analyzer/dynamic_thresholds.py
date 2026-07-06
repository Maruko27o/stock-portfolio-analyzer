"""動的閾値の候補(固定 vs ボラティリティ/相場条件付き)。

過学習を避けるため自由度(DoF)は1〜2に厳しく制限する。各閾値は
「基準値 + 係数 × (ボラ百分位 − 0.5)」の形だけを許し、係数k=0なら固定値に一致する
(＝フォールバックが常に既存挙動になる)。採用はウォークフォワード検証の結果次第で、
安易に動的化しない。

vol_pct は実現ボラティリティの百分位(0〜1)。0.5が中央値で、高ボラほど1に近い。
"""

from __future__ import annotations


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def dynamic_threshold(base: float, k: float, vol_pct: float | None, span: float, lo: float, hi: float) -> float:
    """基準値をボラ百分位で線形に動かす(DoF=1: k)。

    k=0 または vol_pct=None のとき base を返す(固定値フォールバック)。
    span は vol_pct が 0→1 に動くときの最大振れ幅。lo/hi でクランプ。
    """
    if k == 0 or vol_pct is None:
        return _clamp(base, lo, hi)
    return _clamp(base + k * (vol_pct - 0.5) * span, lo, hi)


# 各閾値の既定(固定値=現行ロジックと一致)。kを0にしておけば挙動不変。
def rsi_oversold(vol_pct: float | None = None, base: float = 30.0, k: float = 0.0) -> float:
    """RSI売られすぎ閾値。高ボラでは深めを要求(k>0で下げる)。範囲20〜40。"""
    return dynamic_threshold(base, -k, vol_pct, span=20.0, lo=20.0, hi=40.0)


def rsi_overbought(vol_pct: float | None = None, base: float = 70.0, k: float = 0.0) -> float:
    """RSI買われすぎ閾値。高ボラでは高めを許容(k>0で上げる)。範囲60〜80。"""
    return dynamic_threshold(base, k, vol_pct, span=20.0, lo=60.0, hi=80.0)


def bollinger_sigma(vol_pct: float | None = None, base: float = 2.0, k: float = 0.0) -> float:
    """ボリンジャー逸脱の σ 閾値。高ボラでは広め。範囲1.5〜3.0。"""
    return dynamic_threshold(base, k, vol_pct, span=1.5, lo=1.5, hi=3.0)


def atr_stop_mult(vol_pct: float | None = None, base: float = 2.0, k: float = 0.0) -> float:
    """損切のATR倍率。高ボラでは広め。範囲1.0〜4.0。"""
    return dynamic_threshold(base, k, vol_pct, span=2.0, lo=1.0, hi=4.0)


def momentum_threshold(vol_pct: float | None = None, base: float = 3.0, k: float = 0.0) -> float:
    """モメンタム判定の%閾値。高ボラでは大きめの動きを要求。範囲1〜8。"""
    return dynamic_threshold(base, k, vol_pct, span=6.0, lo=1.0, hi=8.0)


def volume_surge_mult(vol_pct: float | None = None, base: float = 2.0, k: float = 0.0) -> float:
    """出来高急増の倍率閾値。範囲1.5〜3.0。"""
    return dynamic_threshold(base, k, vol_pct, span=1.5, lo=1.5, hi=3.0)
