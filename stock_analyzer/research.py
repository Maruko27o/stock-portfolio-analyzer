"""第2フェーズ: 特徴量の寄与分析とスコア再設計の検証。

学習期間(既定2016〜2022)で各特徴量・組み合わせ・戦略タイプの成績を解析し、
検証期間(2023〜)で汎化性能を確認する。結果は data/feature_analysis.json に
保存し、通知には戦略タイプ別の実績統計(data/strategy_stats.json)を渡す。

実行(重いので手動のみ):
    python -m stock_analyzer.research --period 10y --step 5
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from stock_analyzer.backtest import (
    BacktestConfig,
    ExitRule,
    build_market_features,
    clean_price_frame,
    download_universe,
    simulate_exit,
)
from stock_analyzer.screener import load_universe

TOKYO = ZoneInfo("Asia/Tokyo")

TRAIN_END = pd.Timestamp("2022-12-31")
FORWARD_DAYS = 20  # 特徴量分析の基準リターン(20営業日先の終値)
TRAILING_RULE = ExitRule("トレーリング8%(最長60日)", "trailing", trail_pct=8, max_days=60)

# 戦略タイプ判定(通知側と共有するため関数はここに集約)
STRATEGY_PRIORITY = ["ブレイクアウト", "順張り", "逆張り", "レンジ"]


# ---------------------------------------------------------------------------
# 特徴量(バックテストと同じ定義。列ごとにTrue/Falseで持つ)
# ---------------------------------------------------------------------------


def feature_frame(frame: pd.DataFrame, bench_roc10: pd.Series | None) -> pd.DataFrame:
    close, high, low, vol = frame["Close"], frame["High"], frame["Low"], frame["Volume"]
    f = pd.DataFrame(index=frame.index)

    sma5 = close.rolling(5).mean()
    sma25 = close.rolling(25).mean()
    sma75 = close.rolling(75).mean()
    f["25日線上"] = (close > sma25) & sma25.notna()
    f["MA上昇配列"] = (sma5 > sma25) & (sma25 > sma75) & sma75.notna()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_valid = pd.Series(np.arange(len(frame)) >= 35, index=frame.index)
    f["MACD上"] = macd_valid & (macd_line > signal_line)
    f["MACD_GC"] = (
        macd_valid & (macd_line.shift(1) <= signal_line.shift(1)) & (macd_line > signal_line)
    )
    f["MACD_DC"] = (
        macd_valid & (macd_line.shift(1) >= signal_line.shift(1)) & (macd_line < signal_line)
    )

    diff = close.diff()
    gains = diff.clip(lower=0).rolling(14).sum() / 14
    losses = (-diff).clip(lower=0).rolling(14).sum() / 14
    rsi = pd.Series(np.where(losses == 0, 100.0, 100 - 100 / (1 + gains / losses)), index=frame.index)
    rsi[gains.isna()] = np.nan
    f["RSI30以下"] = rsi <= 30
    f["RSI70以上"] = rsi >= 70

    mean20 = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    sigma = pd.Series(np.where(std20 == 0, 0.0, (close - mean20) / std20), index=frame.index)
    sigma[mean20.isna()] = np.nan
    f["ボリンジャー-2σ以下"] = sigma <= -2
    f["ボリンジャー+2σ以上"] = sigma >= 2
    f["_sigma_abs1未満"] = sigma.abs() < 1

    recent_vol = vol.rolling(5).mean()
    prev_vol = vol.shift(5).rolling(5).mean()
    price_change5 = close - close.shift(5)
    f["出来高増×上昇"] = (price_change5 > 0) & (recent_vol > prev_vol) & prev_vol.notna()
    vol_avg20 = vol.shift(1).rolling(20).mean()
    f["出来高2倍以上"] = (vol >= 2 * vol_avg20) & vol_avg20.notna()

    f["60日高値更新"] = (close >= high.rolling(60).max()) & high.rolling(60).max().notna()
    f["60日安値割れ"] = (close <= low.rolling(60).min()) & low.rolling(60).min().notna()
    f["52週高値更新"] = (close >= high.rolling(252).max()) & high.rolling(252).max().notna()

    roc10 = (close / close.shift(10) - 1) * 100
    f["直近10日+3%以上"] = roc10 >= 3
    f["直近10日-3%以下"] = roc10 <= -3
    if bench_roc10 is not None:
        rel = roc10 - bench_roc10.reindex(frame.index).ffill()
        f["市場より強い"] = rel >= 5
        f["市場より弱い"] = rel <= -5

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr_ratio = tr.rolling(14).mean() / close
    f["高ボラ(ATR比上位)"] = atr_ratio > atr_ratio.expanding(min_periods=100).median()

    div = frame["Dividends"] if "Dividends" in frame else pd.Series(0.0, index=frame.index)
    trailing_div = div.rolling(252, min_periods=1).sum()
    f["配当利回り3%以上"] = trailing_div / close * 100 >= 3

    f["_sma25_flat"] = (sma25 / sma25.shift(10) - 1).abs() < 0.01

    return f


def numeric_feature_frame(frame: pd.DataFrame, bench_roc10: pd.Series | None) -> pd.DataFrame:
    """類似局面検索用の連続値特徴量(すべて水準に依存しない比率・乖離)。"""
    close, high, low, vol = frame["Close"], frame["High"], frame["Low"], frame["Volume"]
    n = pd.DataFrame(index=frame.index)

    sma25 = close.rolling(25).mean()
    sma75 = close.rolling(75).mean()
    diff = close.diff()
    gains = diff.clip(lower=0).rolling(14).sum() / 14
    losses = (-diff).clip(lower=0).rolling(14).sum() / 14
    rsi = pd.Series(np.where(losses == 0, 100.0, 100 - 100 / (1 + gains / losses)), index=frame.index)
    rsi[gains.isna()] = np.nan
    n["RSI"] = rsi

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    n["MACD相対"] = (macd_line - signal_line) / close * 100

    n["25日線乖離"] = (close / sma25 - 1) * 100
    n["25vs75日線"] = (sma25 / sma75 - 1) * 100

    roc10 = (close / close.shift(10) - 1) * 100
    n["10日騰落"] = roc10
    if bench_roc10 is not None:
        n["対市場10日"] = roc10 - bench_roc10.reindex(frame.index).ffill()
    else:
        n["対市場10日"] = 0.0

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    n["ATR比"] = tr.rolling(14).mean() / close * 100
    n["出来高比"] = vol.rolling(5).mean() / vol.shift(5).rolling(5).mean()

    div = frame["Dividends"] if "Dividends" in frame else pd.Series(0.0, index=frame.index)
    n["配当利回り"] = div.rolling(252, min_periods=1).sum() / close * 100
    return n


def knn_study(obs: pd.DataFrame, k: int = 200, max_test: int = 12000, seed: int = 0) -> dict | None:
    """類似局面検索(kNN)の有効性を検証期間で評価する。

    学習期間の観測を「過去の局面データベース」とし、検証期間の各観測に
    ついて特徴量が最も近いk件の平均リターンを予測値とする。予測値の高い
    群が実際に高リターンなら、スコア帯平均を超える判別力があると言える。
    """
    cols = [c for c in obs.columns if c.startswith("数値:")]
    if not cols:
        return None
    data = obs.dropna(subset=cols)
    train = data[data["is_train"]]
    test = data[~data["is_train"]]
    if len(train) < 5000 or len(test) < 2000:
        return None

    rng = np.random.default_rng(seed)
    if len(test) > max_test:
        test = test.iloc[np.sort(rng.choice(len(test), max_test, replace=False))]

    X_tr = train[cols].to_numpy(dtype=np.float32)
    mu, sd = X_tr.mean(axis=0), X_tr.std(axis=0)
    sd[sd == 0] = 1.0
    X_tr = (X_tr - mu) / sd
    y_tr = train["ret"].to_numpy(dtype=np.float32)
    X_te = (test[cols].to_numpy(dtype=np.float32) - mu) / sd

    preds = np.empty(len(X_te), dtype=np.float32)
    win_preds = np.empty(len(X_te), dtype=np.float32)
    tr_sq = (X_tr**2).sum(axis=1)
    wins_tr = (y_tr > 0).astype(np.float32)
    for start in range(0, len(X_te), 1000):
        chunk = X_te[start : start + 1000]
        d2 = tr_sq[None, :] - 2 * chunk @ X_tr.T + (chunk**2).sum(axis=1)[:, None]
        idx = np.argpartition(d2, k, axis=1)[:, :k]
        preds[start : start + 1000] = y_tr[idx].mean(axis=1)
        win_preds[start : start + 1000] = wins_tr[idx].mean(axis=1)

    actual = test["ret"].to_numpy()
    order = pd.qcut(pd.Series(preds).rank(method="first"), 10, labels=False, duplicates="drop")
    deciles = []
    for q in range(10):
        mask = (order == q).to_numpy()
        deciles.append(
            {
                "predicted": round(float(preds[mask].mean()), 2),
                **basic_stats(actual[mask]),
            }
        )
    mono = spearman_monotonicity(list(range(10)), [d["expectancy"] for d in deciles if d.get("count")])
    top = actual[preds >= np.quantile(preds, 0.8)]
    bottom = actual[preds <= np.quantile(preds, 0.2)]
    return {
        "k": k,
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "features": [c.replace("数値:", "") for c in cols],
        "auc": auc_score(preds, actual > 0),
        "pred_actual_corr": round(float(np.corrcoef(preds, actual)[0, 1]), 4),
        "monotonicity_expectancy": mono,
        "deciles(低→高)": deciles,
        "top20pct": basic_stats(top),
        "bottom20pct": basic_stats(bottom),
        "win_rate_calibration_corr": round(
            float(np.corrcoef(win_preds, (actual > 0).astype(float))[0, 1]), 4
        ),
    }


def strategy_frame(f: pd.DataFrame) -> pd.DataFrame:
    """特徴量から4つの戦略タイプの成立フラグを作る(通知側の判定と同一定義)。"""
    s = pd.DataFrame(index=f.index)
    s["順張り"] = f["25日線上"] & f["MA上昇配列"] & f["MACD上"]
    s["逆張り"] = f["RSI30以下"] | f["ボリンジャー-2σ以下"]
    s["ブレイクアウト"] = f["60日高値更新"] & f["出来高増×上昇"]
    s["レンジ"] = f["_sma25_flat"] & f["_sigma_abs1未満"] & ~s["順張り"] & ~s["ブレイクアウト"]
    return s


# ---------------------------------------------------------------------------
# 統計ユーティリティ
# ---------------------------------------------------------------------------


def basic_stats(returns: np.ndarray) -> dict:
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


def auc_score(scores: np.ndarray, wins: np.ndarray) -> float | None:
    """AUC = 勝ちトレードのスコアが負けより高い確率(Mann-Whitney)。"""
    pos = scores[wins]
    neg = scores[~wins]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    # 同順位は平均ランクに補正
    combined = np.concatenate([pos, neg])
    sorted_vals = combined[order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        if j > i:
            avg = (i + j + 2) / 2
            for k in range(i, j + 1):
                ranks[order[k]] = avg
        i = j + 1
    rank_sum_pos = ranks[: len(pos)].sum()
    u = rank_sum_pos - len(pos) * (len(pos) + 1) / 2
    return round(float(u / (len(pos) * len(neg))), 4)


def spearman_monotonicity(band_order: list[float], values: list[float]) -> float | None:
    """スコア帯の並びと成績の単調性(スピアマン相関)。1に近いほど理想。"""
    if len(values) < 3:
        return None
    x = pd.Series(band_order).rank()
    y = pd.Series(values).rank()
    if y.std() == 0 or x.std() == 0:
        return None
    return round(float(np.corrcoef(x, y)[0, 1]), 3)


# 相場環境判定は通知側と共有するためmarket.pyに置く(後方互換の再エクスポート)
from stock_analyzer.market import classify_regime  # noqa: E402


def classify_symbol_types(meta: dict) -> list[str]:
    """現在の属性から銘柄タイプを分類(過去時点の属性は入手不可のため静的)。"""
    types = []
    mcap = meta.get("market_cap")
    if mcap:
        if mcap >= 1e12:
            types.append("大型株")
        elif mcap >= 2e11:
            types.append("中型株")
        else:
            types.append("小型株")
    pbr = meta.get("pbr")
    if pbr is not None:
        types.append("バリュー株" if pbr <= 1.2 else "グロース株")
    dy = meta.get("dividend_yield")
    if dy is not None and dy >= 3.5:
        types.append("高配当株")
    return types


def fetch_symbol_meta(tickers: list[str], cache_path: str) -> dict:
    """業種・時価総額など(現在値)を取得しキャッシュする。"""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        if set(cached) >= set(tickers):
            return cached
    meta: dict[str, dict] = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            price = info.get("currentPrice") or info.get("previousClose")
            rate = info.get("dividendRate")
            meta[ticker] = {
                "sector": info.get("sector"),
                "market_cap": info.get("marketCap"),
                "pbr": info.get("priceToBook"),
                "dividend_yield": (rate / price * 100) if (rate and price) else None,
            }
        except Exception:
            meta[ticker] = {}
    directory = os.path.dirname(cache_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    return meta


# ---------------------------------------------------------------------------
# 解析本体
# ---------------------------------------------------------------------------


def run_research(period: str, step: int, out_path: str, strategy_out_path: str, limit: int = 0, extra: str = "") -> dict:
    config = BacktestConfig(period=period, sample_step=step)
    tickers = load_universe()
    for sym in extra.split(","):
        sym = sym.strip().upper()
        if sym and sym not in tickers:
            tickers.append(sym)
    if limit:
        tickers = tickers[:limit]
    print(f"対象: {len(tickers)}銘柄 / 期間: {period} / 学習≦{TRAIN_END.date()} / 検証>{TRAIN_END.date()}")

    data = download_universe(tickers, period)
    meta = fetch_symbol_meta(tickers, "data/symbol_meta.json")
    print("銘柄メタ情報取得完了")

    frames: dict[str, pd.DataFrame] = {}
    all_dates: set = set()
    wanted = ["Close", "High", "Low", "Volume", "Dividends"]
    for ticker in tickers:
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
        if len(frame) < 300:
            continue
        if frame.index.tz is not None:
            frame.index = frame.index.tz_localize(None)
        frames[ticker] = frame
        all_dates.update(frame.index)
    master_index = pd.DatetimeIndex(sorted(all_dates))
    print(f"データ取得完了: {len(frames)}銘柄")

    _, _, bench_roc10 = build_market_features(period, master_index)
    n225 = yf.download("^N225", period=period, auto_adjust=True, progress=False)["Close"]
    if isinstance(n225, pd.DataFrame):
        n225 = n225.iloc[:, 0]
    if n225.index.tz is not None:
        n225.index = n225.index.tz_localize(None)
    regime_series = classify_regime(n225).reindex(master_index, method="ffill").fillna("横ばい")

    sample_dates = set(master_index[::step])

    # 観測テーブルを構築: 1行 = (銘柄, サンプル日)
    rows = []
    feature_names: list[str] = []
    for ticker, frame in frames.items():
        f = feature_frame(frame, bench_roc10)
        s = strategy_frame(f)
        nf = numeric_feature_frame(frame, bench_roc10)
        fwd = (frame["Close"].shift(-FORWARD_DAYS) / frame["Close"] - 1) * 100

        close = frame["Close"].to_numpy()
        high = frame["High"].to_numpy()
        low = frame["Low"].to_numpy()
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        tr = np.nanmax(np.vstack([high - low, np.abs(high - prev_close), np.abs(low - prev_close)]), axis=0)
        atr = pd.Series(tr, index=frame.index).rolling(14).mean().to_numpy()

        if not feature_names:
            feature_names = [c for c in f.columns if not c.startswith("_")]

        symbol_types = classify_symbol_types(meta.get(ticker, {}))
        sector = (meta.get(ticker) or {}).get("sector")
        for i, ts in enumerate(frame.index):
            if ts not in sample_dates or i < 260:
                continue
            r = fwd.iloc[i]
            if np.isnan(r) or abs(r) > config.max_abs_return_pct:
                continue
            trail = simulate_exit(TRAILING_RULE, i, close, high, low, atr)
            rows.append(
                {
                    "ticker": ticker,
                    "date": ts,
                    "ret": float(r),
                    "trail_ret": float(trail[0]) if trail and abs(trail[0]) <= config.max_abs_return_pct else np.nan,
                    "regime": regime_series.get(ts, "横ばい"),
                    "sector": sector,
                    "types": symbol_types,
                    **{name: bool(f[name].iloc[i]) for name in feature_names},
                    **{f"戦略:{name}": bool(s[name].iloc[i]) for name in s.columns},
                    **{f"数値:{name}": float(nf[name].iloc[i]) for name in nf.columns},
                }
            )
    obs = pd.DataFrame(rows)
    obs["is_train"] = obs["date"] <= TRAIN_END
    train = obs[obs["is_train"]]
    test = obs[~obs["is_train"]]
    print(f"観測: {len(obs)}件 (学習{len(train)} / 検証{len(test)})")

    baseline_train = basic_stats(train["ret"].to_numpy())
    baseline_test = basic_stats(test["ret"].to_numpy())

    # --- 単独検証 ---
    singles = {}
    for name in feature_names:
        singles[name] = {
            "train": basic_stats(train.loc[train[name], "ret"].to_numpy()),
            "test": basic_stats(test.loc[test[name], "ret"].to_numpy()),
        }

    # --- 相関分析(学習期間・特徴量同士のφ係数) ---
    corr_matrix = train[feature_names].astype(float).corr()
    high_corr_pairs = []
    for i, a in enumerate(feature_names):
        for b in feature_names[i + 1 :]:
            value = corr_matrix.loc[a, b]
            if abs(value) >= 0.5:
                high_corr_pairs.append({"a": a, "b": b, "corr": round(float(value), 3)})
    high_corr_pairs.sort(key=lambda p: -abs(p["corr"]))

    # --- 特徴量削減候補 ---
    prune = []
    for name in feature_names:
        st = singles[name]["train"]
        if st.get("count", 0) < 200:
            prune.append({"feature": name, "reason": f"学習期間の件数不足({st.get('count', 0)}件)"})
            continue
        uplift = st["expectancy"] - baseline_train["expectancy"]
        partner = next(
            (p for p in high_corr_pairs if name in (p["a"], p["b"])),
            None,
        )
        if uplift <= 0.05 and partner:
            other = partner["b"] if partner["a"] == name else partner["a"]
            prune.append(
                {
                    "feature": name,
                    "reason": f"期待値上乗せ{uplift:+.2f}%でベースライン並み、かつ{other}と相関{partner['corr']}で情報重複",
                }
            )
        elif uplift <= -0.3:
            prune.append({"feature": name, "reason": f"期待値がベースライン比{uplift:+.2f}%と悪化要因"})

    # --- 組み合わせ検証(学習期間の期待値上位から選抜) ---
    ranked = sorted(
        [n for n in feature_names if singles[n]["train"].get("count", 0) >= 500],
        key=lambda n: -(singles[n]["train"]["expectancy"]),
    )
    top = ranked[:6]
    combos = {}
    from itertools import combinations

    for r in (2, 3, 4):
        for combo in combinations(top, r):
            mask_train = np.logical_and.reduce([train[c] for c in combo])
            mask_test = np.logical_and.reduce([test[c] for c in combo])
            tr_stats = basic_stats(train.loc[mask_train, "ret"].to_numpy())
            if tr_stats.get("count", 0) < 100:
                continue
            combos[" + ".join(combo)] = {
                "train": tr_stats,
                "test": basic_stats(test.loc[mask_test, "ret"].to_numpy()),
            }

    # --- 戦略タイプ別 × 相場環境別 ---
    strategies = {}
    for strat in STRATEGY_PRIORITY:
        col = f"戦略:{strat}"
        entry = {
            "train": basic_stats(train.loc[train[col], "ret"].to_numpy()),
            "test": basic_stats(test.loc[test[col], "ret"].to_numpy()),
            "test_trailing": basic_stats(test.loc[test[col], "trail_ret"].dropna().to_numpy()),
            "regimes": {},
        }
        for regime in ("上昇", "下落", "横ばい"):
            sub_train = train[(train[col]) & (train["regime"] == regime)]
            sub_test = test[(test[col]) & (test["regime"] == regime)]
            entry["regimes"][regime] = {
                "train": basic_stats(sub_train["ret"].to_numpy()),
                "test": basic_stats(sub_test["ret"].to_numpy()),
            }
        strategies[strat] = entry

    # --- 相場環境別ベースライン ---
    regimes_out = {}
    for regime in ("上昇", "下落", "横ばい"):
        regimes_out[regime] = {
            "train": basic_stats(train.loc[train["regime"] == regime, "ret"].to_numpy()),
            "test": basic_stats(test.loc[test["regime"] == regime, "ret"].to_numpy()),
        }

    # --- 業種別・銘柄タイプ別 ---
    sectors_out = {}
    for sector, group in obs.groupby("sector"):
        if sector and len(group) >= 500:
            sectors_out[sector] = basic_stats(group["ret"].to_numpy())
    types_out = {}
    for type_name in ("大型株", "中型株", "小型株", "グロース株", "バリュー株", "高配当株"):
        mask = obs["types"].apply(lambda ts: type_name in ts)
        if mask.sum() >= 500:
            types_out[type_name] = basic_stats(obs.loc[mask, "ret"].to_numpy())

    # --- スコア案 A/B/C の構築と検証 ---
    def evaluate_score(scores_train: pd.Series, scores_test: pd.Series, label: str) -> dict:
        result = {}
        for split_name, split_df, scores in (
            ("train", train, scores_train),
            ("test", test, scores_test),
        ):
            if len(split_df) < 50:
                result[split_name] = None
                continue
            returns = split_df["ret"].to_numpy()
            wins = returns > 0
            auc = auc_score(scores.to_numpy(), wins)
            quintile = pd.qcut(scores.rank(method="first"), 5, labels=False, duplicates="drop")
            band_stats = []
            for q in range(5):
                band_stats.append(basic_stats(returns[quintile == q]))
            mono_wr = spearman_monotonicity(
                list(range(5)), [b["win_rate"] for b in band_stats if b.get("count")]
            )
            mono_exp = spearman_monotonicity(
                list(range(5)), [b["expectancy"] for b in band_stats if b.get("count")]
            )
            result[split_name] = {
                "auc": auc,
                "quintiles(低→高)": band_stats,
                "monotonicity_win_rate": mono_wr,
                "monotonicity_expectancy": mono_exp,
            }
        result["label"] = label
        return result

    # A: 学習期間の期待値上乗せを重みにした加点式
    weights = {}
    for name in feature_names:
        st = singles[name]["train"]
        if st.get("count", 0) >= 500:
            weights[name] = round(st["expectancy"] - baseline_train["expectancy"], 3)

    def score_a(df: pd.DataFrame) -> pd.Series:
        total = pd.Series(0.0, index=df.index)
        for name, w in weights.items():
            total += df[name].astype(float) * w
        return total

    # B: 戦略タイプ(学習期間の期待値をそのままスコアに)
    strat_train_exp = {
        s: strategies[s]["train"].get("expectancy", 0) or 0 for s in STRATEGY_PRIORITY
    }

    def score_b(df: pd.DataFrame) -> pd.Series:
        total = pd.Series(0.0, index=df.index)
        for s in STRATEGY_PRIORITY:
            total = np.maximum(total, df[f"戦略:{s}"].astype(float) * strat_train_exp[s])
        return pd.Series(total, index=df.index)

    # C: 削減後の特徴量だけを均等加点
    pruned_names = {p["feature"] for p in prune}
    kept = [
        n
        for n in feature_names
        if n not in pruned_names and (singles[n]["train"]["expectancy"] - baseline_train["expectancy"]) > 0.05
    ]

    def score_c(df: pd.DataFrame) -> pd.Series:
        total = pd.Series(0.0, index=df.index)
        for name in kept:
            total += df[name].astype(float)
        return total

    versions = {
        "A(期待値重み加点式)": evaluate_score(score_a(train), score_a(test), "A"),
        "B(戦略タイプ別)": evaluate_score(score_b(train), score_b(test), "B"),
        "C(削減後均等加点)": evaluate_score(score_c(train), score_c(test), "C"),
    }
    versions["A(期待値重み加点式)"]["weights"] = weights
    versions["C(削減後均等加点)"]["kept_features"] = kept

    # --- ウォークフォワード(境界を3通りに動かして安定性確認) ---
    walk_forward = {}
    for boundary in ("2020-12-31", "2022-12-31", "2024-12-31"):
        b = pd.Timestamp(boundary)
        wf_train = obs[obs["date"] <= b]
        wf_test = obs[obs["date"] > b]
        if len(wf_train) < 1000 or len(wf_test) < 1000:
            continue
        wf_weights = {}
        wf_base = basic_stats(wf_train["ret"].to_numpy())["expectancy"]
        for name in feature_names:
            sub = wf_train.loc[wf_train[name], "ret"]
            if len(sub) >= 500:
                wf_weights[name] = float(sub.mean()) - wf_base
        wf_scores = pd.Series(0.0, index=wf_test.index)
        for name, w in wf_weights.items():
            wf_scores += wf_test[name].astype(float) * w
        returns = wf_test["ret"].to_numpy()
        walk_forward[boundary] = {
            "auc": auc_score(wf_scores.to_numpy(), returns > 0),
            "top20pct": basic_stats(returns[wf_scores >= wf_scores.quantile(0.8)]),
            "bottom20pct": basic_stats(returns[wf_scores <= wf_scores.quantile(0.2)]),
        }

    print("類似局面検索(kNN)を評価中…")
    knn_result = knn_study(obs)

    output = {
        "knn_similarity": knn_result,
        "metadata": {
            "run_at": datetime.now(TOKYO).isoformat(timespec="seconds"),
            "period": period,
            "sample_step": step,
            "forward_days": FORWARD_DAYS,
            "train_end": str(TRAIN_END.date()),
            "symbols_used": len(frames),
            "observations": len(obs),
            "excluded_items": [
                "ニュース/IR/自社株買い/増配イベント: 過去時点の履歴が無料データに存在しないため対象外",
                "金利・グロース指数: 同上(将来データ源が確保できれば追加可能)",
                "PER/ROE等のファンダ時系列: 過去時点の値が入手不可のため対象外",
                "業種・時価総額・PBR・配当分類は現在値による静的分類(限界として明記)",
            ],
        },
        "baseline": {"train": baseline_train, "test": baseline_test},
        "features_single": singles,
        "correlation_pairs": high_corr_pairs,
        "prune_candidates": prune,
        "combos": combos,
        "strategies": strategies,
        "regimes_baseline": regimes_out,
        "sectors": sectors_out,
        "symbol_types": types_out,
        "score_versions": versions,
        "walk_forward": walk_forward,
    }

    directory = os.path.dirname(out_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=1)

    # 通知用: 戦略タイプ別の検証期間実績(件数=信頼度として表示)
    strategy_stats = {
        "metadata": {
            "run_at": output["metadata"]["run_at"],
            "train_end": str(TRAIN_END.date()),
            "basis": f"{FORWARD_DAYS}営業日先リターン(検証期間2023年以降)",
            "min_count": 200,
        },
        "strategies": {
            s: {
                "test": strategies[s]["test"],
                "train": strategies[s]["train"],
                "regimes_test": {
                    regime: strategies[s]["regimes"][regime]["test"]
                    for regime in ("上昇", "下落", "横ばい")
                },
            }
            for s in STRATEGY_PRIORITY
        },
        "baseline_test": baseline_test,
    }
    with open(strategy_out_path, "w", encoding="utf-8") as fh:
        json.dump(strategy_stats, fh, ensure_ascii=False, indent=1)
    print(f"保存: {out_path} / {strategy_out_path}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="特徴量寄与分析とスコア再設計の検証")
    parser.add_argument("--period", default="10y")
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--out", default="data/feature_analysis.json")
    parser.add_argument("--strategy-out", default="data/strategy_stats.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--extra", default="")
    args = parser.parse_args()
    run_research(args.period, args.step, args.out, args.strategy_out, args.limit, args.extra)


if __name__ == "__main__":
    main()
