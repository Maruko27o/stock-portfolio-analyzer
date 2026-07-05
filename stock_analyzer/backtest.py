"""AIスコアの過去実績を検証するバックテストエンジン。

各営業日について「その日までの情報のみ」で価格ベースのAIスコア
(テクニカル+配当+市場環境。ファンダ指標は過去時点の値が入手不可能な
ため除外)を算出し、複数の売却ルールで仮想売買した結果をスコア帯別に
集計する。結果はJSONに保存し、通知処理はそれを参照するだけにする。

使い方(バックテストは重いので手動実行のみ):
    python -m stock_analyzer.backtest --period 10y --step 5
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from stock_analyzer.screener import load_universe

TOKYO = ZoneInfo("Asia/Tokyo")

# 現行スコアリングと同じカテゴリ上限(summary.CATEGORY_CAPSに対応)
TECH_CAP = 20
DIVIDEND_CAP = 6
MARKET_CAP = 8

SCORE_BANDS = [
    (95, 101, "95-100"),
    (90, 95, "90-94"),
    (85, 90, "85-89"),
    (80, 85, "80-84"),
    (75, 80, "75-79"),
    (70, 75, "70-74"),
    (65, 70, "65-69"),
    (60, 65, "60-64"),
    (55, 60, "55-59"),
    (50, 55, "50-54"),
    (-(10**9), 50, "50未満"),
]

EQUITY_INDEX_TICKERS = ["^N225", "1306.T", "^DJI", "^IXIC", "^GSPC"]
VIX_TICKER = "^VIX"
BENCHMARK_TICKER = "1306.T"


@dataclass
class ExitRule:
    """売却ルール。kindごとに使うパラメータが異なる(未使用は0)。"""

    name: str
    kind: str  # "horizon" | "tp_sl" | "trailing" | "atr"
    horizon: int = 0
    take_profit_pct: float = 0.0
    stop_loss_pct: float = 0.0
    trail_pct: float = 0.0
    atr_stop_mult: float = 0.0
    atr_tp_mult: float = 0.0
    max_days: int = 0


DEFAULT_RULES = [
    ExitRule("5営業日後売却", "horizon", horizon=5),
    ExitRule("10営業日後売却", "horizon", horizon=10),
    ExitRule("20営業日後売却", "horizon", horizon=20),
    ExitRule("30営業日後売却", "horizon", horizon=30),
    ExitRule("利確10%/損切5%(最長30日)", "tp_sl", take_profit_pct=10, stop_loss_pct=5, max_days=30),
    ExitRule("トレーリング8%(最長60日)", "trailing", trail_pct=8, max_days=60),
    ExitRule("ATR損切2倍/利確3倍(最長30日)", "atr", atr_stop_mult=2, atr_tp_mult=3, max_days=30),
]


@dataclass
class BacktestConfig:
    period: str = "10y"
    sample_step: int = 5  # 何営業日ごとにエントリーを観測するか(重複緩和)
    warmup_bars: int = 75  # 指標が揃うまでの除外本数(SMA75)
    min_band_count: int = 30  # これ未満の帯は通知に使わない
    adoption_min_score: int = 70  # ルール採用判定に使う下限スコア
    max_daily_change_pct: float = 50.0  # これ超の日次変動はデータ破損とみなす
    max_abs_return_pct: float = 150.0  # これ超のトレードは異常値として除外
    rules: list = field(default_factory=lambda: list(DEFAULT_RULES))


def clean_price_frame(frame: pd.DataFrame, max_daily_change_pct: float) -> pd.DataFrame:
    """破損した価格データを除去する。

    非正の株価を落とし、日次変動が閾値(既定50%)を超える箇所は調整破綻
    (上場廃止→再上場の継ぎ目など。例: 8303.TはYahoo上で約2000万倍の
    ジャンプと負の株価が混入)とみなし、最後の破綻箇所以降の連続した
    正常区間だけを使う。
    """
    frame = frame[frame["Close"] > 0]
    if len(frame) < 2:
        return frame
    change = frame["Close"].pct_change().abs()
    breaks = np.where(change > max_daily_change_pct / 100)[0]
    if len(breaks):
        frame = frame.iloc[breaks[-1] :]
    return frame


def band_label(score: float) -> str:
    for low, high, label in SCORE_BANDS:
        if low <= score < high:
            return label
    return "50未満"


# ---------------------------------------------------------------------------
# 特徴量とスコア(build_signalsのベクトル化版。ロジック一致はテストで保証)
# ---------------------------------------------------------------------------


def technical_points(frame: pd.DataFrame, bench_roc10: pd.Series | None) -> pd.Series:
    """テクニカルシグナルの合計点(上限適用前)。build_signalsと同一ロジック。"""
    close, high, low, vol = frame["Close"], frame["High"], frame["Low"], frame["Volume"]
    zeros = pd.Series(0.0, index=frame.index)
    pts = zeros.copy()

    sma5 = close.rolling(5).mean()
    sma25 = close.rolling(25).mean()
    sma75 = close.rolling(75).mean()

    # 25日線
    valid = sma25.notna()
    pts += np.where(valid & (close > sma25), 8, 0)
    pts += np.where(valid & ~(close > sma25), -8, 0)

    # 移動平均の配列
    valid = sma5.notna() & sma25.notna() & sma75.notna()
    pts += np.where(valid & (sma5 > sma25) & (sma25 > sma75), 5, 0)
    pts += np.where(valid & (sma5 < sma25) & (sma25 < sma75), -5, 0)

    # MACD(existing _ema_series と同じ再帰式: ewm(adjust=False))
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    prev_macd = macd_line.shift(1)
    prev_signal = signal_line.shift(1)
    macd_valid = pd.Series(np.arange(len(frame)) >= 35, index=frame.index)  # len>=36
    crossed_up = macd_valid & (prev_macd <= prev_signal) & (macd_line > signal_line)
    crossed_down = macd_valid & (prev_macd >= prev_signal) & (macd_line < signal_line)
    residual = macd_valid & ~crossed_up & ~crossed_down
    pts += np.where(crossed_up, 10, 0)
    pts += np.where(crossed_down, -10, 0)
    pts += np.where(residual & (macd_line > signal_line), 4, 0)
    pts += np.where(residual & ~(macd_line > signal_line), -4, 0)

    # RSI(直近14変化の単純平均。既存実装と同式)
    diff = close.diff()
    gains = diff.clip(lower=0).rolling(14).sum() / 14
    losses = (-diff).clip(lower=0).rolling(14).sum() / 14
    rsi = pd.Series(np.where(losses == 0, 100.0, 100 - 100 / (1 + gains / losses)), index=frame.index)
    rsi[gains.isna() | losses.isna()] = np.nan
    pts += np.where(rsi <= 30, 8, 0)
    pts += np.where(rsi >= 70, -8, 0)

    # 価格×出来高
    price_change = close - close.shift(5)
    recent_vol = vol.rolling(5).mean()
    prev_vol = vol.shift(5).rolling(5).mean()
    vp_valid = price_change.notna() & recent_vol.notna() & prev_vol.notna()
    rising = recent_vol > prev_vol
    pts += np.where(vp_valid & (price_change > 0) & rising, 6, 0)
    pts += np.where(vp_valid & (price_change > 0) & ~rising, -2, 0)
    pts += np.where(vp_valid & (price_change < 0) & rising, -6, 0)
    # 残り(下落×出来高減、または横ばい)は「下げ渋り」+2
    pts += np.where(vp_valid & ~(price_change > 0) & ~((price_change < 0) & rising), 2, 0)

    # サポート/レジスタンス(直近60日)
    resistance = high.rolling(60).max()
    support = low.rolling(60).min()
    sr_valid = resistance.notna() & support.notna()
    pts += np.where(sr_valid & (close >= resistance), 5, 0)
    pts += np.where(sr_valid & ~(close >= resistance) & (close <= support), -5, 0)

    # ボリンジャー(population std)
    mean20 = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    sigma = pd.Series(np.where(std20 == 0, 0.0, (close - mean20) / std20), index=frame.index)
    sigma[mean20.isna()] = np.nan
    pts += np.where(sigma >= 2, -3, 0)
    pts += np.where(sigma <= -2, 3, 0)

    # モメンタム(10日騰落率)
    roc10 = (close / close.shift(10) - 1) * 100
    pts += np.where(roc10 >= 10, 6, 0)
    pts += np.where((roc10 >= 3) & (roc10 < 10), 3, 0)
    pts += np.where(roc10 <= -10, -6, 0)
    pts += np.where((roc10 <= -3) & (roc10 > -10), -3, 0)

    # 対ベンチマーク相対力
    if bench_roc10 is not None:
        bench = bench_roc10.reindex(frame.index).ffill()
        rel = roc10 - bench
        pts += np.where(rel >= 5, 4, 0)
        pts += np.where(rel <= -5, -4, 0)

    return pts


def dividend_points(frame: pd.DataFrame) -> pd.Series:
    """配当シグナル: 高利回り(直近252日実績÷終値)と権利落ち接近(30日以内)。"""
    close = frame["Close"]
    dividends = frame["Dividends"] if "Dividends" in frame else pd.Series(0.0, index=frame.index)
    trailing = dividends.rolling(252, min_periods=1).sum()
    yield_pct = trailing / close * 100

    pts = pd.Series(0.0, index=frame.index)
    pts += np.where(yield_pct >= 3.0, 3, 0)

    ex_dates = frame.index[dividends > 0]
    if len(ex_dates):
        ex_values = ex_dates.values
        positions = np.searchsorted(ex_values, frame.index.values, side="right")
        days_to_next = np.full(len(frame), np.nan)
        has_next = positions < len(ex_values)
        next_dates = ex_values[np.clip(positions, 0, len(ex_values) - 1)]
        deltas = (next_dates - frame.index.values) / np.timedelta64(1, "D")
        days_to_next[has_next] = deltas[has_next]
        near = (days_to_next >= 1) & (days_to_next <= 30) & (trailing.values > 0)
        pts += np.where(near, 4, 0)
    return pts


def build_market_features(period: str, master_index: pd.DatetimeIndex):
    """営業日ごとの(センチメント点, VIX点, ベンチ10日騰落率)を作る。

    米国指数・VIXは日本の日付dに対して「前営業日終値」(=その時点で既知)を使う。
    """
    tickers = sorted(set(EQUITY_INDEX_TICKERS + [VIX_TICKER]))
    data = yf.download(tickers, period=period, group_by="ticker", auto_adjust=True, progress=False)

    pos = pd.Series(0, index=master_index)
    neg = pd.Series(0, index=master_index)
    for ticker in EQUITY_INDEX_TICKERS:
        try:
            closes = data[ticker]["Close"].dropna()
        except (KeyError, TypeError):
            continue
        change = closes.pct_change() * 100
        if change.index.tz is not None:
            change.index = change.index.tz_localize(None)
        aligned = change.reindex(master_index, method="ffill")
        pos += (aligned > 0).astype(int)
        neg += (aligned < 0).astype(int)
    sentiment_pts = pd.Series(np.where(pos > neg, 5, np.where(neg > pos, -5, 0)), index=master_index)

    vix_pts = pd.Series(0.0, index=master_index)
    try:
        vix = data[VIX_TICKER]["Close"].dropna()
        if vix.index.tz is not None:
            vix.index = vix.index.tz_localize(None)
        level = vix.reindex(master_index, method="ffill")
        vix_pts = pd.Series(
            np.where(level >= 30, -8, np.where(level >= 25, -4, np.where(level <= 15, 2, 0))),
            index=master_index,
        )
        vix_pts[level.isna()] = 0
    except (KeyError, TypeError):
        pass

    bench_roc10 = None
    try:
        bench = data[BENCHMARK_TICKER]["Close"].dropna()
        if bench.index.tz is not None:
            bench.index = bench.index.tz_localize(None)
        bench_roc10 = (bench / bench.shift(10) - 1) * 100
    except (KeyError, TypeError):
        pass

    return sentiment_pts, vix_pts, bench_roc10


def compute_scores(frame: pd.DataFrame, market_pts: pd.Series, bench_roc10, warmup_bars: int) -> pd.Series:
    """1銘柄の全営業日について価格ベースAIスコア(0-100)を返す。"""
    tech = technical_points(frame, bench_roc10).clip(-TECH_CAP, TECH_CAP)
    div = dividend_points(frame).clip(-DIVIDEND_CAP, DIVIDEND_CAP)
    market = market_pts.reindex(frame.index).fillna(0).clip(-MARKET_CAP, MARKET_CAP)
    score = (50 + tech + div + market).clip(0, 100)
    score.iloc[: min(warmup_bars, len(score))] = np.nan  # 指標が揃うまでは判定しない
    return score


# ---------------------------------------------------------------------------
# 仮想売買
# ---------------------------------------------------------------------------


def simulate_exit(rule: ExitRule, entry: int, close: np.ndarray, high: np.ndarray, low: np.ndarray, atr: np.ndarray):
    """1エントリーの(騰落率%, 保有日数)を返す。データ不足ならNone。

    エントリーは当日終値。TP/SLは高値・安値で判定し、同日に両方触れた
    場合は損切を優先(保守的)。保有期間がデータ末尾を超える場合は除外して
    Look Ahead/打ち切りバイアスを避ける。
    """
    n = len(close)
    price = close[entry]

    if rule.kind == "horizon":
        exit_idx = entry + rule.horizon
        if exit_idx >= n:
            return None
        return (close[exit_idx] / price - 1) * 100, rule.horizon

    if rule.kind in ("tp_sl", "atr"):
        if rule.kind == "tp_sl":
            tp = price * (1 + rule.take_profit_pct / 100)
            sl = price * (1 - rule.stop_loss_pct / 100)
        else:
            if np.isnan(atr[entry]):
                return None
            tp = price + rule.atr_tp_mult * atr[entry]
            sl = price - rule.atr_stop_mult * atr[entry]
        last = entry + rule.max_days
        if last >= n:
            return None
        for j in range(entry + 1, last + 1):
            if low[j] <= sl:
                return (sl / price - 1) * 100, j - entry
            if high[j] >= tp:
                return (tp / price - 1) * 100, j - entry
        return (close[last] / price - 1) * 100, rule.max_days

    if rule.kind == "trailing":
        last = entry + rule.max_days
        if last >= n:
            return None
        peak = price
        for j in range(entry + 1, last + 1):
            if close[j] > peak:
                peak = close[j]
            elif close[j] <= peak * (1 - rule.trail_pct / 100):
                return (close[j] / price - 1) * 100, j - entry
        return (close[last] / price - 1) * 100, rule.max_days

    raise ValueError(f"unknown rule kind: {rule.kind}")


# ---------------------------------------------------------------------------
# 統計
# ---------------------------------------------------------------------------


def compute_stats(returns: np.ndarray, holds: np.ndarray, entry_dates: np.ndarray, years: float, sample_step: int) -> dict:
    """1つの(ルール, スコア帯)の全要求指標を計算する。

    max_drawdownは「同一エントリー日のシグナルを等金額で平均したリターン」を
    日付順に累積した曲線のピークからの下落幅(%ポイント・非複利)。同日に
    多数の銘柄が重なるプール集計を連続複利にすると暴落日に非現実的な
    複利連鎖が起きるため、この定義を使う。
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
    daily_means = np.array(
        [returns[entry_dates == day].mean() for day in np.sort(unique_dates)]
    )
    cumulative = np.cumsum(daily_means)
    running_peak = np.maximum.accumulate(np.concatenate([[0.0], cumulative]))[1:]
    max_drawdown = float((cumulative - running_peak).min()) if len(cumulative) else 0.0

    avg_hold = float(holds.mean())
    volatility = float(returns.std(ddof=0))
    trades_per_year_equiv = 250 / avg_hold if avg_hold > 0 else 0
    sharpe = (
        float(returns.mean() / volatility * np.sqrt(trades_per_year_equiv)) if volatility > 0 else 0.0
    )
    annual_return = expectancy * trades_per_year_equiv
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0

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
        "calmar": round(calmar, 2),
        "volatility": round(volatility, 2),
        "signals_per_year": round(count * sample_step / years, 1),
    }


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------


def download_universe(tickers: list[str], period: str):
    return yf.download(
        tickers, period=period, group_by="ticker", auto_adjust=True, actions=True, progress=False, threads=True
    )


def run_backtest(config: BacktestConfig, tickers: list[str] | None = None, out_path: str = "data/backtest_stats.json") -> dict:
    universe = tickers if tickers is not None else load_universe()
    print(f"対象: {len(universe)}銘柄 / 期間: {config.period} / サンプル間隔: {config.sample_step}営業日")

    data = download_universe(universe, config.period)

    # マスター営業日カレンダー: 全銘柄の和集合
    all_dates = set()
    frames: dict[str, pd.DataFrame] = {}
    wanted = ["Close", "High", "Low", "Volume", "Dividends"]
    for ticker in universe:
        try:
            raw = data[ticker]
        except (KeyError, TypeError):
            continue
        columns = [c for c in wanted if c in raw.columns]
        if "Close" not in columns:
            continue
        frame = raw[columns].copy()
        frame = frame[frame["Close"].notna()]
        frame = clean_price_frame(frame, config.max_daily_change_pct)
        if len(frame) < config.warmup_bars + 40:
            continue
        if frame.index.tz is not None:
            frame.index = frame.index.tz_localize(None)
        frames[ticker] = frame
        all_dates.update(frame.index)
    if not frames:
        raise RuntimeError("価格データを取得できませんでした")
    master_index = pd.DatetimeIndex(sorted(all_dates))
    print(f"データ取得完了: {len(frames)}銘柄 / {master_index[0].date()}〜{master_index[-1].date()}")

    sentiment_pts, vix_pts, bench_roc10 = build_market_features(config.period, master_index)
    market_pts = (sentiment_pts + vix_pts).clip(-MARKET_CAP, MARKET_CAP)

    sample_dates = set(master_index[:: config.sample_step])
    years = max((master_index[-1] - master_index[0]).days / 365.25, 0.1)

    # エントリー抽出: (ルール非依存) 銘柄×サンプル日×スコア
    per_rule: dict[str, dict[str, list]] = {
        rule.name: {"returns": [], "holds": [], "dates": [], "scores": []} for rule in config.rules
    }
    for ticker, frame in frames.items():
        scores = compute_scores(frame, market_pts, bench_roc10, config.warmup_bars)
        close = frame["Close"].to_numpy()
        high = frame["High"].to_numpy()
        low = frame["Low"].to_numpy()
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        tr = np.nanmax(
            np.vstack([high - low, np.abs(high - prev_close), np.abs(low - prev_close)]), axis=0
        )
        atr = pd.Series(tr, index=frame.index).rolling(14).mean().to_numpy()

        entry_positions = [
            i
            for i, (ts, score) in enumerate(zip(frame.index, scores))
            if ts in sample_dates and not np.isnan(score)
        ]
        for rule in config.rules:
            bucket = per_rule[rule.name]
            for i in entry_positions:
                result = simulate_exit(rule, i, close, high, low, atr)
                if result is None:
                    continue
                ret, hold = result
                if abs(ret) > config.max_abs_return_pct:
                    continue  # 分割未調整などの異常値を統計から除外
                bucket["returns"].append(ret)
                bucket["holds"].append(hold)
                bucket["dates"].append(frame.index[i].value)
                bucket["scores"].append(float(scores.iloc[i]))
    print("仮想売買完了。集計中…")

    rules_output: dict[str, dict] = {}
    adoption: list[tuple[float, str]] = []
    for rule in config.rules:
        bucket = per_rule[rule.name]
        returns = np.array(bucket["returns"])
        holds = np.array(bucket["holds"])
        dates = np.array(bucket["dates"])
        scores = np.array(bucket["scores"])

        bands_output = {}
        for lowb, highb, label in SCORE_BANDS:
            mask = (scores >= lowb) & (scores < highb)
            bands_output[label] = compute_stats(
                returns[mask], holds[mask], dates[mask], years, config.sample_step
            )

        high_mask = scores >= config.adoption_min_score
        high_stats = compute_stats(
            returns[high_mask], holds[high_mask], dates[high_mask], years, config.sample_step
        )
        rules_output[rule.name] = {"bands": bands_output, "high_score_overall": high_stats}
        adoption.append((high_stats.get("expectancy") or -999, rule.name))

    adoption.sort(reverse=True)
    adopted_rule = adoption[0][1]

    output = {
        "metadata": {
            "run_at": datetime.now(TOKYO).isoformat(timespec="seconds"),
            "period": config.period,
            "start": str(master_index[0].date()),
            "end": str(master_index[-1].date()),
            "years": round(years, 2),
            "universe_size": len(universe),
            "symbols_used": len(frames),
            "sample_step": config.sample_step,
            "warmup_bars": config.warmup_bars,
            "min_band_count": config.min_band_count,
            "adoption_min_score": config.adoption_min_score,
            "max_daily_change_pct": config.max_daily_change_pct,
            "max_abs_return_pct": config.max_abs_return_pct,
            "entry": "シグナル当日終値で購入",
            "adopted_rule": adopted_rule,
            "adoption_criterion": f"スコア{config.adoption_min_score}以上の期待値が最大のルール",
            "rules": [asdict(rule) for rule in config.rules],
            "score_scope": "価格由来スコアのみ(テクニカル+配当+市場環境)。ファンダ指標は過去時点の値が入手不可のため除外",
            "limitations": [
                "サバイバーシップバイアス: 現在の日経225構成銘柄のみ(上場廃止銘柄の履歴は無料データに存在しない)",
                "エントリーは当日終値(通知を見て翌日売買する場合は乖離あり)",
                "権利落ち日は実際の配当実績日を使用(発表前でも日程はほぼ確定的なため)",
                "データソース: Yahoo Finance(実行日時点、分割・配当調整済み)",
            ],
        },
        "rules": rules_output,
        "adopted": {"rule": adopted_rule, "bands": rules_output[adopted_rule]["bands"]},
    }

    directory = os.path.dirname(out_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=1)
    print(f"保存しました: {out_path} (採用ルール: {adopted_rule})")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="AIスコアのバックテストを実行して統計を保存します")
    parser.add_argument("--period", default="10y", help="対象期間(yfinance形式: 3y/5y/10y/max)")
    parser.add_argument("--step", type=int, default=5, help="エントリー観測の間隔(営業日)")
    parser.add_argument("--out", default="data/backtest_stats.json", help="統計の保存先")
    parser.add_argument("--limit", type=int, default=0, help="銘柄数の上限(動作確認用)")
    parser.add_argument("--extra", default="", help="ユニバースに追加する銘柄(カンマ区切り)")
    args = parser.parse_args()

    tickers = load_universe()
    for symbol in args.extra.split(","):
        symbol = symbol.strip().upper()
        if symbol and symbol not in tickers:
            tickers.append(symbol)
    if args.limit:
        tickers = tickers[: args.limit]

    config = BacktestConfig(period=args.period, sample_step=args.step)
    run_backtest(config, tickers, args.out)


if __name__ == "__main__":
    main()
