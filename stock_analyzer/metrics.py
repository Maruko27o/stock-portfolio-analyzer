"""トレード統計の単一の真実(single source of truth)。

バックテスト(backtest.py)と特徴量解析(research.py)が同じ定義で指標を計算するための
共有モジュール。期待値(EV)を最優先にしつつ、勝率だけで判断しないよう
PF/RR/Sharpe/Sortino/Calmar/MaxDD/保有日数/分位点までまとめて出す。

汎化性能の評価に使うため、点推定だけでなくブートストラップ信頼区間(CI)と
モンテカルロによるドローダウン分布も提供する。CIは同一エントリー日をブロックとして
リサンプルし、重複ホライズンによる時系列クラスタで過小評価しないようにする。
"""

from __future__ import annotations

from typing import Callable

import numpy as np


def _percentile(returns: np.ndarray, q: float) -> float:
    return round(float(np.percentile(returns, q)), 2)


def return_stats(returns: np.ndarray) -> dict:
    """期待値=単純平均リターンとする軽量統計(research.basic_stats 互換)。

    件数が少ない部分集合(特徴量の単独検証など)向け。EVは returns.mean()。
    """
    n = len(returns)
    if n == 0:
        return {"count": 0}
    wins = returns > 0
    losses = returns < 0
    win_rate = wins.mean() * 100
    avg_win = float(returns[wins].mean()) if wins.any() else 0.0
    avg_loss = float(abs(returns[losses].mean())) if losses.any() else 0.0
    total_win = float(returns[wins].sum()) if wins.any() else 0.0
    total_loss = float(abs(returns[losses].sum())) if losses.any() else 0.0
    return {
        "count": int(n),
        "win_rate": round(float(win_rate), 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "risk_reward": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        "profit_factor": round(total_win / total_loss, 2) if total_loss > 0 else None,
        "expectancy": round(float(returns.mean()), 2),
    }


def downside_deviation(returns: np.ndarray, target: float = 0.0) -> float:
    """下方偏差: 目標(既定0)を下回る乖離だけの二乗平均平方根。Sortino の分母。"""
    shortfall = np.minimum(returns - target, 0.0)
    return float(np.sqrt(np.mean(shortfall**2)))


def trade_stats(
    returns: np.ndarray,
    holds: np.ndarray,
    entry_dates: np.ndarray,
    years: float,
    sample_step: int,
) -> dict:
    """1つの(ルール, スコア帯)などの全指標を計算する。

    max_drawdown は「同一エントリー日のシグナルを等金額で平均したリターン」を日付順に
    累積した曲線のピークからの下落幅(%ポイント・非複利)。同日に多数の銘柄が重なる
    プール集計を連続複利にすると暴落日に非現実的な複利連鎖が起きるため、この定義を使う。
    """
    count = len(returns)
    if count == 0:
        return {"count": 0}

    wins = returns > 0
    losses = returns < 0
    win_rate = wins.mean() * 100
    avg_win = float(returns[wins].mean()) if wins.any() else 0.0
    avg_loss = float(abs(returns[losses].mean())) if losses.any() else 0.0
    total_win = float(returns[wins].sum()) if wins.any() else 0.0
    total_loss = float(abs(returns[losses].sum())) if losses.any() else 0.0
    expectancy = (win_rate / 100) * avg_win - (1 - win_rate / 100) * avg_loss

    unique_dates = np.unique(entry_dates)
    daily_means = np.array([returns[entry_dates == day].mean() for day in np.sort(unique_dates)])
    cumulative = np.cumsum(daily_means)
    running_peak = np.maximum.accumulate(np.concatenate([[0.0], cumulative]))[1:]
    max_drawdown = float((cumulative - running_peak).min()) if len(cumulative) else 0.0

    avg_hold = float(holds.mean())
    volatility = float(returns.std(ddof=0))
    down_dev = downside_deviation(returns)
    trades_per_year_equiv = 250 / avg_hold if avg_hold > 0 else 0
    ann = np.sqrt(trades_per_year_equiv)
    sharpe = float(returns.mean() / volatility * ann) if volatility > 0 else 0.0
    sortino = float(returns.mean() / down_dev * ann) if down_dev > 0 else 0.0
    annual_return = expectancy * trades_per_year_equiv
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0

    tail = returns[returns <= np.percentile(returns, 5)]
    cvar95 = round(float(tail.mean()), 2) if len(tail) else None
    prob = lambda mask: round(float(mask.mean() * 100), 1)  # noqa: E731

    return {
        "count": int(count),
        "win_rate": round(float(win_rate), 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "risk_reward": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        "profit_factor": round(total_win / total_loss, 2) if total_loss > 0 else None,
        "expectancy": round(float(expectancy), 2),
        "avg_hold_days": round(avg_hold, 1),
        "avg_hold_days_win": round(float(holds[wins].mean()), 1) if wins.any() else None,
        "avg_hold_days_loss": round(float(holds[losses].mean()), 1) if losses.any() else None,
        "max_win": round(float(returns.max()), 2),
        "max_loss": round(float(returns.min()), 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "calmar": round(calmar, 2),
        "volatility": round(volatility, 2),
        "downside_deviation": round(down_dev, 2),
        "signals_per_year": round(count * sample_step / years, 1),
        "median": _percentile(returns, 50),
        "p2_5": _percentile(returns, 2.5),
        "p10": _percentile(returns, 10),
        "p25": _percentile(returns, 25),
        "p75": _percentile(returns, 75),
        "p90": _percentile(returns, 90),
        "p97_5": _percentile(returns, 97.5),
        "var95": _percentile(returns, 5),
        "cvar95": cvar95,
        "prob_up_3": prob(returns >= 3),
        "prob_up_5": prob(returns >= 5),
        "prob_up_10": prob(returns >= 10),
        "prob_down_3": prob(returns <= -3),
        "prob_down_5": prob(returns <= -5),
        "prob_down_10": prob(returns <= -10),
    }


# ---------------------------------------------------------------------------
# 汎化性能の評価: ブートストラップCI・モンテカルロ
# ---------------------------------------------------------------------------


def expectancy_metric(returns: np.ndarray) -> float:
    return float(returns.mean()) if len(returns) else 0.0


def profit_factor_metric(returns: np.ndarray) -> float:
    total_win = returns[returns > 0].sum()
    total_loss = abs(returns[returns < 0].sum())
    return float(total_win / total_loss) if total_loss > 0 else float("inf")


def sharpe_metric(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    sd = returns.std(ddof=0)
    return float(returns.mean() / sd) if sd > 0 else 0.0


def bootstrap_ci(
    returns: np.ndarray,
    metric_fn: Callable[[np.ndarray], float] = expectancy_metric,
    entry_dates: np.ndarray | None = None,
    n: int = 1000,
    alpha: float = 0.05,
    seed: int = 0,
) -> dict:
    """指標のブートストラップ信頼区間。

    entry_dates を渡すと「同一エントリー日」をブロック単位でリサンプルし、重複ホライズンの
    時系列クラスタを尊重する(独立リサンプルより保守的で、CIを不当に狭めない)。
    返り値: {point, low, high, n} 。lowが0を上回れば「有意にプラス」の目安。
    """
    m = len(returns)
    if m == 0:
        return {"point": None, "low": None, "high": None, "n": 0}
    rng = np.random.default_rng(seed)
    point = float(metric_fn(returns))

    if entry_dates is not None:
        # 日付ごとのインデックス配列を作り、日付を重複ありでリサンプル
        order = np.argsort(entry_dates, kind="mergesort")
        sorted_dates = entry_dates[order]
        uniq, starts = np.unique(sorted_dates, return_index=True)
        groups = np.split(order, starts[1:])
        k = len(groups)
        samples = np.empty(n)
        for b in range(n):
            pick = rng.integers(0, k, size=k)
            idx = np.concatenate([groups[j] for j in pick])
            samples[b] = metric_fn(returns[idx])
    else:
        samples = np.empty(n)
        for b in range(n):
            idx = rng.integers(0, m, size=m)
            samples[b] = metric_fn(returns[idx])

    finite = samples[np.isfinite(samples)]
    if len(finite) == 0:
        return {"point": round(point, 3), "low": None, "high": None, "n": int(m)}
    low = float(np.percentile(finite, alpha / 2 * 100))
    high = float(np.percentile(finite, (1 - alpha / 2) * 100))
    return {
        "point": round(point, 3),
        "low": round(low, 3),
        "high": round(high, 3),
        "n": int(m),
    }


def monte_carlo_equity(
    returns: np.ndarray,
    n: int = 1000,
    seed: int = 0,
) -> dict:
    """トレード順序をシャッフルした等金額累積(非複利)の分布。

    実現した1本の資産曲線に依存せず、「順序が違えばどこまで悪化し得たか」を測る。
    返り値: 最大ドローダウンと終端リターンの分布(中央値・5/95%点)。
    """
    m = len(returns)
    if m == 0:
        return {"n": 0}
    rng = np.random.default_rng(seed)
    max_dds = np.empty(n)
    finals = np.empty(n)
    for b in range(n):
        seq = returns[rng.permutation(m)]
        cum = np.cumsum(seq)
        peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
        max_dds[b] = (cum - peak).min()
        finals[b] = cum[-1]
    return {
        "n": int(m),
        "max_drawdown_median": round(float(np.median(max_dds)), 2),
        "max_drawdown_p95_worst": round(float(np.percentile(max_dds, 5)), 2),
        "final_median": round(float(np.median(finals)), 2),
        "final_p5": round(float(np.percentile(finals, 5)), 2),
        "final_p95": round(float(np.percentile(finals, 95)), 2),
    }
