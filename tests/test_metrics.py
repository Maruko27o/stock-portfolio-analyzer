from __future__ import annotations

import numpy as np
import pytest

from stock_analyzer import metrics


def test_return_stats_expectancy_is_mean():
    stats = metrics.return_stats(np.array([10.0, -5.0, 10.0, -5.0]))
    assert stats["expectancy"] == 2.5
    assert stats["win_rate"] == 50.0
    assert stats["risk_reward"] == 2.0
    assert stats["profit_factor"] == 2.0


def test_return_stats_empty():
    assert metrics.return_stats(np.array([])) == {"count": 0}


def test_trade_stats_matches_known_values():
    returns = np.array([10.0, -5.0, 10.0, -5.0])
    holds = np.array([5.0, 3.0, 5.0, 3.0])
    dates = np.array([1, 2, 3, 4])
    s = metrics.trade_stats(returns, holds, dates, years=1.0, sample_step=5)
    assert s["count"] == 4
    assert s["expectancy"] == pytest.approx(2.5)
    assert s["max_drawdown"] == -5.0
    assert s["signals_per_year"] == 20.0
    assert s["risk_reward"] == 2.0
    # Sortino が追加され、下方偏差>0 なので有限の正値
    assert "sortino" in s and s["sortino"] > 0
    assert "sharpe" in s and "calmar" in s


def test_downside_deviation_only_counts_losses():
    # 上振れは分母に入らない。損失 -5,-5 → sqrt(mean(0,25,0,25))=sqrt(12.5)
    dd = metrics.downside_deviation(np.array([10.0, -5.0, 10.0, -5.0]))
    assert dd == pytest.approx(np.sqrt(12.5))
    # 全勝なら下方偏差0
    assert metrics.downside_deviation(np.array([1.0, 2.0, 3.0])) == 0.0


def test_sortino_zero_when_no_downside():
    returns = np.array([1.0, 2.0, 3.0, 4.0])
    holds = np.full(4, 5.0)
    dates = np.arange(4)
    s = metrics.trade_stats(returns, holds, dates, years=1.0, sample_step=5)
    assert s["sortino"] == 0.0  # 下方偏差0はガードして0


def test_bootstrap_ci_is_seed_reproducible_and_brackets_point():
    rng = np.random.default_rng(1)
    returns = rng.normal(1.0, 5.0, size=2000)
    a = metrics.bootstrap_ci(returns, metrics.expectancy_metric, n=500, seed=42)
    b = metrics.bootstrap_ci(returns, metrics.expectancy_metric, n=500, seed=42)
    assert a == b  # seed 固定で再現
    assert a["low"] <= a["point"] <= a["high"]


def test_bootstrap_ci_detects_positive_edge():
    rng = np.random.default_rng(0)
    # 明確にプラスのEV。CI下限が0を上回るはず
    returns = rng.normal(2.0, 3.0, size=3000)
    ci = metrics.bootstrap_ci(returns, metrics.expectancy_metric, n=800, seed=7)
    assert ci["low"] > 0


def test_bootstrap_ci_block_resample_with_dates():
    rng = np.random.default_rng(3)
    returns = rng.normal(0.5, 4.0, size=1000)
    dates = np.repeat(np.arange(100), 10)  # 100日 × 各10トレード(クラスタ)
    ci = metrics.bootstrap_ci(returns, metrics.expectancy_metric, entry_dates=dates, n=400, seed=5)
    assert ci["low"] <= ci["point"] <= ci["high"]
    assert ci["n"] == 1000


def test_monte_carlo_equity_drawdown_is_nonpositive():
    rng = np.random.default_rng(9)
    returns = rng.normal(0.3, 3.0, size=500)
    mc = metrics.monte_carlo_equity(returns, n=300, seed=11)
    assert mc["max_drawdown_median"] <= 0
    assert mc["max_drawdown_p95_worst"] <= mc["max_drawdown_median"]
    assert mc["final_p5"] <= mc["final_median"] <= mc["final_p95"]
