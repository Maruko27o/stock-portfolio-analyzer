from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.backtest import (
    ExitRule,
    band_label,
    compute_scores,
    compute_stats,
    simulate_exit,
)
from stock_analyzer.indicators import (
    bollinger_sigma,
    evaluate_volume_price,
    macd,
    rate_of_change,
    relative_strength_index,
    simple_moving_average,
    support_resistance,
)
from stock_analyzer.portfolio import Holding
from stock_analyzer.summary import CATEGORY_CAPS, _capped_total, build_signals


def _synthetic_frame(n=300, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1.2, n)
    close = 100 + np.cumsum(steps)
    close = np.maximum(close, 5.0)
    high = close + rng.uniform(0.2, 1.5, n)
    low = close - rng.uniform(0.2, 1.5, n)
    volume = rng.uniform(1e5, 5e5, n)
    dividends = np.zeros(n)
    dividends[100] = 30.0  # 高利回りになる規模の配当を2回
    dividends[220] = 30.0
    index = pd.bdate_range("2024-01-04", periods=n)
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Volume": volume, "Dividends": dividends},
        index=index,
    )


def _analysis_at(frame: pd.DataFrame, i: int) -> HoldingAnalysis:
    """既存の(1日ずつの)関数群で i 日目時点の分析を組み立てる。"""
    closes = frame["Close"].iloc[: i + 1].tolist()
    highs = frame["High"].iloc[: i + 1].tolist()
    lows = frame["Low"].iloc[: i + 1].tolist()
    volumes = frame["Volume"].iloc[: i + 1].tolist()
    dividends = frame["Dividends"].iloc[: i + 1]

    trailing = float(dividends.iloc[-252:].sum())
    current = closes[-1]
    today = frame.index[i].date()
    future_ex = [ts.date() for ts in frame.index[frame["Dividends"] > 0] if ts.date() > today]
    days_to_ex = (future_ex[0] - today).days if future_ex else None

    return HoldingAnalysis(
        holding=Holding("TEST.T", 0, 0.0),
        name=None,
        current_price=current,
        sma_short=simple_moving_average(closes, 5),
        sma_mid=simple_moving_average(closes, 25),
        sma_long=simple_moving_average(closes, 75),
        rsi=relative_strength_index(closes, 14),
        momentum=rate_of_change(closes, 10),
        macd_result=macd(closes),
        bollinger=bollinger_sigma(closes),
        volume_signal="",
        volume_trend_ratio=None,
        volume_price_signal=evaluate_volume_price(closes, volumes),
        levels=support_resistance(highs, lows),
        period_high=max(highs),
        period_low=min(lows),
        per=None,
        pbr=None,
        dividend_yield=trailing / current * 100 if trailing else 0.0,
        roe=None,
        roa=None,
        eps=None,
        bps=None,
        revenue_growth=None,
        earnings_growth=None,
        payout_ratio=None,
        debt_to_equity=None,
        current_ratio=None,
        sector=None,
        industry=None,
        next_earnings=None,
        days_to_earnings=None,
        dividend_rate=trailing if trailing else None,
        ex_dividend_date=None,
        days_to_ex_dividend=days_to_ex,
    )


def test_vectorized_score_matches_build_signals():
    """ベクトル化スコアが既存build_signals(価格由来のみ)と完全一致すること。"""
    frame = _synthetic_frame()
    market_pts = pd.Series(0.0, index=frame.index)  # 中立・VIXなし
    scores = compute_scores(frame, market_pts, bench_roc10=None, warmup_bars=75)

    for i in (80, 120, 150, 221, 260, 299):
        analysis = _analysis_at(frame, i)
        signals = build_signals(analysis, "中立", vix=None, benchmark_momentum=None)
        price_signals = [s for s in signals if s.category in ("technical", "dividend", "market")]
        expected = max(0, min(100, 50 + _capped_total(price_signals)))
        assert scores.iloc[i] == expected, f"day {i}: vectorized={scores.iloc[i]} expected={expected}"


def test_scores_masked_during_warmup():
    frame = _synthetic_frame()
    scores = compute_scores(frame, pd.Series(0.0, index=frame.index), None, warmup_bars=75)
    assert scores.iloc[:75].isna().all()
    assert scores.iloc[80:].notna().all()


def test_simulate_exit_horizon():
    close = np.array([100.0, 101, 102, 103, 104, 110])
    high = close + 1
    low = close - 1
    atr = np.full(6, 2.0)
    rule = ExitRule("5d", "horizon", horizon=5)
    ret, hold = simulate_exit(rule, 0, close, high, low, atr)
    assert ret == pytest.approx(10.0)
    assert hold == 5
    # データ不足なら除外
    assert simulate_exit(rule, 1, close, high, low, atr) is None


def test_simulate_exit_tp_hit():
    close = np.array([100.0] * 10)
    high = np.array([100.0, 105, 111, 100, 100, 100, 100, 100, 100, 100])
    low = np.full(10, 99.0)
    rule = ExitRule("tp10sl5", "tp_sl", take_profit_pct=10, stop_loss_pct=5, max_days=5)
    ret, hold = simulate_exit(rule, 0, close, high, low, np.full(10, 1.0))
    assert ret == pytest.approx(10.0)
    assert hold == 2


def test_simulate_exit_stop_takes_priority_same_day():
    close = np.array([100.0] * 10)
    high = np.array([100.0, 112, 100, 100, 100, 100, 100, 100, 100, 100])
    low = np.array([100.0, 94, 100, 100, 100, 100, 100, 100, 100, 100])
    rule = ExitRule("tp10sl5", "tp_sl", take_profit_pct=10, stop_loss_pct=5, max_days=5)
    ret, hold = simulate_exit(rule, 0, close, high, low, np.full(10, 1.0))
    assert ret == pytest.approx(-5.0)  # 同日に両方触れたら損切優先(保守的)
    assert hold == 1


def test_simulate_exit_trailing():
    close = np.array([100.0, 110, 120, 110, 100, 100, 100])
    rule = ExitRule("trail8", "trailing", trail_pct=8, max_days=6)
    ret, hold = simulate_exit(rule, 0, close, close + 1, close - 1, np.full(7, 1.0))
    assert ret == pytest.approx(10.0)  # ピーク120→110.4割れ(110)で売却
    assert hold == 3


def test_simulate_exit_atr_rule():
    close = np.array([100.0] * 10)
    high = np.array([100.0, 100, 116, 100, 100, 100, 100, 100, 100, 100])
    low = np.full(10, 98.0)
    atr = np.full(10, 5.0)
    rule = ExitRule("atr", "atr", atr_stop_mult=2, atr_tp_mult=3, max_days=5)
    ret, hold = simulate_exit(rule, 0, close, high, low, atr)
    assert ret == pytest.approx(15.0)  # TP=100+3*5=115
    assert hold == 2


def test_compute_stats_all_requested_metrics():
    returns = np.array([10.0, -5.0, 10.0, -5.0])
    holds = np.array([5.0, 3.0, 5.0, 3.0])
    dates = np.array([1, 2, 3, 4])  # 別々のエントリー日
    stats = compute_stats(returns, holds, dates, years=1.0, sample_step=5)
    assert stats["count"] == 4
    assert stats["win_rate"] == 50.0
    assert stats["avg_win"] == 10.0
    assert stats["avg_loss"] == 5.0
    assert stats["risk_reward"] == 2.0
    assert stats["profit_factor"] == 2.0
    assert stats["expectancy"] == pytest.approx(2.5)
    assert stats["avg_hold_days_win"] == 5.0
    assert stats["avg_hold_days_loss"] == 3.0
    assert stats["max_win"] == 10.0
    assert stats["max_loss"] == -5.0
    assert stats["max_drawdown"] == -5.0  # 累積10→5(ピーク比-5ポイント)
    assert stats["signals_per_year"] == 20.0
    # 分布統計
    assert stats["median"] == 2.5
    assert stats["p25"] == -5.0
    assert stats["p75"] == 10.0
    assert stats["var95"] == -5.0
    assert stats["cvar95"] == -5.0
    assert stats["prob_up_5"] == 50.0
    assert stats["prob_down_5"] == 50.0
    assert stats["prob_up_10"] == 50.0
    assert stats["prob_down_10"] == 0.0


def test_compute_stats_same_day_signals_averaged_for_drawdown():
    # 同じ日の多数シグナルは平均され、非現実的な複利連鎖にならない
    returns = np.array([-8.0] * 100)
    holds = np.full(100, 5.0)
    dates = np.full(100, 1)  # 全部同じエントリー日
    stats = compute_stats(returns, holds, dates, years=1.0, sample_step=5)
    assert stats["max_drawdown"] == -8.0  # -8%が100回複利(-99.97%)にはならない
    assert "sharpe" in stats and "calmar" in stats and "volatility" in stats


def test_clean_price_frame_drops_corrupt_segments():
    from stock_analyzer.backtest import clean_price_frame

    n = 100
    index = pd.bdate_range("2024-01-04", periods=n)
    close = np.full(n, 100.0)
    close[40] = -5.0  # 負の株価(データ破損)
    close[60] = 100.0 * 5000  # 調整破綻ジャンプ
    close[61:] = 100.0  # 破綻後は正常水準に戻る
    frame = pd.DataFrame(
        {"Close": close, "High": close, "Low": close, "Volume": np.ones(n), "Dividends": np.zeros(n)},
        index=index,
    )
    cleaned = clean_price_frame(frame, max_daily_change_pct=50)
    # 最後の破綻箇所(61日目の急落)以降の正常区間だけが残る
    assert (cleaned["Close"] > 0).all()
    assert cleaned["Close"].pct_change().abs().max() < 0.5 or len(cleaned) == 1
    assert cleaned.index[-1] == index[-1]


def test_band_label_boundaries():
    assert band_label(100) == "95-100"
    assert band_label(95) == "95-100"
    assert band_label(94) == "90-94"
    assert band_label(50) == "50-54"
    assert band_label(49) == "50未満"


def test_category_caps_match_backtest_constants():
    from stock_analyzer.backtest import DIVIDEND_CAP, MARKET_CAP, TECH_CAP

    assert CATEGORY_CAPS["technical"] == TECH_CAP
    assert CATEGORY_CAPS["dividend"] == DIVIDEND_CAP
    assert CATEGORY_CAPS["market"] == MARKET_CAP
