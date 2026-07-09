"""モメンタム特徴量の算出 [パイプライン第2段: pandas-ta]。

pandas-ta が使える環境ではそれで指標を計算し、無い環境(Python版制約など)では
numpy/既存 indicators による同等のフォールバックで計算する。どちらの経路でも同じ
キーの特徴量 dict を返すので、下流(ML スコアリング)は実装差を意識しない。

返す特徴量(すべて float、算出不能は None):
  rsi14, roc5, roc20, roc60, macd_hist, sma25_ratio, sma_align, atr_pct, vol_ratio
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

try:  # pandas-ta は任意依存。無ければフォールバックする。
    import pandas as pd
    import pandas_ta as ta  # noqa: F401

    _HAS_PANDAS_TA = True
except Exception:  # pragma: no cover - 環境依存
    _HAS_PANDAS_TA = False

from stock_analyzer.indicators import (
    average_true_range,
    macd,
    rate_of_change,
    relative_strength_index,
    simple_moving_average,
    volume_trend,
)


@dataclass
class MomentumFeatures:
    rsi14: float | None = None
    roc5: float | None = None
    roc20: float | None = None
    roc60: float | None = None
    macd_hist: float | None = None
    sma25_ratio: float | None = None  # 現在値 / 25日線 − 1 (%)
    sma_align: float | None = None  # 上昇配列=+1 / 下降配列=−1 / それ以外=0
    atr_pct: float | None = None  # ATR / 現在値 (%)
    vol_ratio: float | None = None  # 直近出来高トレンド倍率

    def as_dict(self) -> dict:
        return asdict(self)


FEATURE_KEYS = list(MomentumFeatures().as_dict().keys())


def _sma_align(closes: list[float]) -> float | None:
    s = simple_moving_average(closes, 5)
    m = simple_moving_average(closes, 25)
    lng = simple_moving_average(closes, 75)
    if s is None or m is None or lng is None:
        return None
    if s > m > lng:
        return 1.0
    if s < m < lng:
        return -1.0
    return 0.0


def _fallback(closes, highs, lows, volumes) -> MomentumFeatures:
    """pandas-ta が無い環境向けの、既存 indicators による同等計算。"""
    price = closes[-1] if closes else None
    sma25 = simple_moving_average(closes, 25)
    macd_res = macd(closes)
    atr = average_true_range(highs, lows, closes)
    return MomentumFeatures(
        rsi14=relative_strength_index(closes, 14),
        roc5=rate_of_change(closes, 5),
        roc20=rate_of_change(closes, 20),
        roc60=rate_of_change(closes, 60),
        macd_hist=macd_res.histogram if macd_res is not None else None,
        sma25_ratio=((price / sma25 - 1) * 100) if price and sma25 else None,
        sma_align=_sma_align(closes),
        atr_pct=((atr / price) * 100) if atr and price else None,
        vol_ratio=volume_trend(volumes) if volumes else None,
    )


def _with_pandas_ta(closes, highs, lows, volumes) -> MomentumFeatures:  # pragma: no cover - 環境依存
    """pandas-ta で主要指標を計算する。数値が取れない項目はフォールバック値で補う。"""
    df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": volumes})
    price = closes[-1] if closes else None

    def _last(series):
        try:
            val = series.dropna().iloc[-1]
            return float(val)
        except Exception:
            return None

    rsi = _last(df.ta.rsi(length=14)) if len(df) >= 15 else None
    roc5 = _last(df.ta.roc(length=5)) if len(df) >= 6 else None
    roc20 = _last(df.ta.roc(length=20)) if len(df) >= 21 else None
    roc60 = _last(df.ta.roc(length=60)) if len(df) >= 61 else None
    macd_hist = None
    if len(df) >= 35:
        macd_df = df.ta.macd()
        if macd_df is not None and macd_df.shape[1] >= 2:
            macd_hist = _last(macd_df.iloc[:, 1])  # ヒストグラム列
    sma25 = _last(df.ta.sma(length=25)) if len(df) >= 25 else None
    atr = _last(df.ta.atr(length=14)) if len(df) >= 15 else None

    # フォールバックで欠損を埋める(pandas-ta で取れない短系列など)。
    fb = _fallback(closes, highs, lows, volumes)
    return MomentumFeatures(
        rsi14=rsi if rsi is not None else fb.rsi14,
        roc5=roc5 if roc5 is not None else fb.roc5,
        roc20=roc20 if roc20 is not None else fb.roc20,
        roc60=roc60 if roc60 is not None else fb.roc60,
        macd_hist=macd_hist if macd_hist is not None else fb.macd_hist,
        sma25_ratio=((price / sma25 - 1) * 100) if price and sma25 else fb.sma25_ratio,
        sma_align=_sma_align(closes),
        atr_pct=((atr / price) * 100) if atr and price else fb.atr_pct,
        vol_ratio=fb.vol_ratio,
    )


def momentum_features(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
) -> MomentumFeatures:
    """終値(必須)＋高値/安値/出来高から、モメンタム特徴量を計算する。

    pandas-ta があればそれを使い、無ければ numpy/既存indicatorsで同等計算する。
    """
    closes = list(closes or [])
    highs = list(highs or closes)
    lows = list(lows or closes)
    volumes = list(volumes or [])
    if _HAS_PANDAS_TA:
        return _with_pandas_ta(closes, highs, lows, volumes)
    return _fallback(closes, highs, lows, volumes)


def backend() -> str:
    """使用中のモメンタム計算バックエンド名(表示・診断用)。"""
    return "pandas-ta" if _HAS_PANDAS_TA else "fallback(indicators)"
