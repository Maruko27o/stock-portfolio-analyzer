"""汎化性能の検証エンジン(過学習を避けるための中核)。

未知相場での期待値を測るため、学習に使っていない期間(OOS)でのみ評価する。
- ローリング/拡張ウォークフォワード: 重みは学習窓だけから導出し、次の期間で検証
- 時系列クロスバリデーション: purged/embargo で重複ホライズンのリークを遮断
- 感度分析: 閾値を振って期待値曲面が平坦か(＝頑健か)を見る
- 採用ゲート: OOS上乗せのCI下限・相場横断の符号一致・感度平坦を満たすものだけ採用

すべて「学習日 < 検証日」を厳守し、未来データのリーケージを起こさない。
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from stock_analyzer import metrics


def time_series_folds(
    dates: np.ndarray,
    n_folds: int,
    scheme: str = "expanding",
    embargo: float = 0.0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """時系列を n_folds 個の検証ブロックに分け、(train_idx, test_idx) を返す。

    scheme="expanding": 各foldは「その時点までの全データ」で学習し次ブロックで検証。
    scheme="rolling":   直前ブロックのみで学習(相場変化への追随を見る)。
    embargo: 検証ブロック開始の直前 embargo(日付単位)を学習から除外し、重複ホライズンの
             リークを防ぐ。返す train は必ず test より過去(リーク無し)。
    """
    dates = np.asarray(dates)
    uniq = np.unique(dates)
    if n_folds < 1 or len(uniq) < n_folds + 1:
        return []

    segments = np.array_split(uniq, n_folds + 1)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(1, n_folds + 1):
        test_dates = segments[i]
        test_lo = test_dates[0]
        cutoff = test_lo - embargo
        if scheme == "rolling":
            train_pool = segments[i - 1]
        else:  # expanding
            train_pool = np.concatenate(segments[:i])
        train_dates = train_pool[train_pool < cutoff]
        if len(train_dates) == 0:
            continue
        train_idx = np.where(np.isin(dates, train_dates))[0]
        test_idx = np.where(np.isin(dates, test_dates))[0]
        if len(train_idx) and len(test_idx):
            folds.append((train_idx, test_idx))
    return folds


def purged_kfold_folds(
    dates: np.ndarray,
    k: int,
    embargo: float = 0.0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """purged/embargo 付き時系列K分割。

    各検証ブロックの前後 embargo を学習から除外(前方参照ラベルが検証ブロックと重なるのを防ぐ)。
    通常のK-Foldと違い時間順の連続ブロックを検証に使う。
    """
    dates = np.asarray(dates)
    uniq = np.unique(dates)
    if k < 2 or len(uniq) < k:
        return []
    segments = np.array_split(uniq, k)
    folds = []
    for i in range(k):
        test_dates = segments[i]
        lo, hi = test_dates[0], test_dates[-1]
        purge_lo, purge_hi = lo - embargo, hi + embargo
        train_mask_dates = uniq[(uniq < purge_lo) | (uniq > purge_hi)]
        train_idx = np.where(np.isin(dates, train_mask_dates))[0]
        test_idx = np.where(np.isin(dates, test_dates))[0]
        if len(train_idx) and len(test_idx):
            folds.append((train_idx, test_idx))
    return folds


def rolling_walk_forward(
    dates: np.ndarray,
    ret: np.ndarray,
    fit_predict: Callable[[np.ndarray, np.ndarray], np.ndarray],
    n_folds: int = 5,
    scheme: str = "expanding",
    embargo: float = 0.0,
    top_quantile: float = 0.2,
    regimes: np.ndarray | None = None,
    ci_n: int = 500,
    seed: int = 0,
) -> dict:
    """ウォークフォワードで「上位スコア群のOOS期待値」を評価する。

    fit_predict(train_idx, test_idx) は学習窓だけを使って test 各行のスコアを返す
    (重みの導出に検証データを使わないのは呼び出し側の責任)。
    上位 top_quantile のトレードのOOSリターンを全fold横断でプールし、期待値とその
    ブートストラップCI、ベースライン比の上乗せ、相場別の上乗せを返す。
    """
    ret = np.asarray(ret, dtype=float)
    folds = time_series_folds(dates, n_folds, scheme, embargo)

    fold_reports = []
    pooled_top: list[np.ndarray] = []
    pooled_base: list[np.ndarray] = []
    top_regime_labels: list[np.ndarray] = []
    for train_idx, test_idx in folds:
        scores = np.asarray(fit_predict(train_idx, test_idx), dtype=float)
        test_ret = ret[test_idx]
        if len(test_ret) == 0 or len(scores) != len(test_ret):
            continue
        thr = np.quantile(scores, 1 - top_quantile)
        sel = scores >= thr
        top_ret = test_ret[sel]
        base_ev = float(test_ret.mean())
        top_ev = float(top_ret.mean()) if len(top_ret) else base_ev
        fold_reports.append(
            {
                "n_test": int(len(test_ret)),
                "n_top": int(sel.sum()),
                "baseline_ev": round(base_ev, 3),
                "top_ev": round(top_ev, 3),
                "uplift": round(top_ev - base_ev, 3),
            }
        )
        pooled_top.append(top_ret)
        pooled_base.append(test_ret)
        if regimes is not None:
            top_regime_labels.append(np.asarray(regimes)[test_idx][sel])

    if not fold_reports:
        return {"scheme": scheme, "n_folds": 0, "folds": [], "oos_top_ev_ci": None}

    top_all = np.concatenate(pooled_top)
    base_all = np.concatenate(pooled_base)
    uplifts = np.array([f["uplift"] for f in fold_reports])
    result = {
        "scheme": scheme,
        "n_folds": len(fold_reports),
        "folds": fold_reports,
        "oos_top_ev": round(float(top_all.mean()), 3),
        "oos_baseline_ev": round(float(base_all.mean()), 3),
        "oos_top_ev_ci": metrics.bootstrap_ci(top_all, metrics.expectancy_metric, n=ci_n, seed=seed),
        "oos_uplift_mean": round(float(uplifts.mean()), 3),
        "oos_uplift_positive_fraction": round(float((uplifts > 0).mean()), 3),
    }
    if top_regime_labels:
        labels = np.concatenate(top_regime_labels)
        by_regime = {}
        for reg in np.unique(labels):
            reg_ret = top_all[labels == reg]
            by_regime[str(reg)] = {
                "count": int(len(reg_ret)),
                "top_ev": round(float(reg_ret.mean()), 3) if len(reg_ret) else None,
            }
        result["oos_top_ev_by_regime"] = by_regime
    return result


def feature_generalization(
    dates: np.ndarray,
    ret: np.ndarray,
    feature: np.ndarray,
    regimes: np.ndarray | None = None,
    n_folds: int = 5,
    scheme: str = "expanding",
    embargo: float = 0.0,
    ci_n: int = 500,
    seed: int = 0,
) -> dict:
    """ブール特徴量(シグナル)がOOSでベースラインを上回るかを検証する。

    fold ごとに「シグナル成立時のリターン」対「全体ベースライン」を比較し、fold横断で
    プールしたシグナル群の期待値とCIを出す。上乗せ(uplift)のCI下限が0を上回れば
    「未知期間でも有効」の目安。相場別の上乗せも返す。採用ゲートの入力に使う。
    """
    ret = np.asarray(ret, dtype=float)
    feature = np.asarray(feature).astype(bool)
    folds = time_series_folds(dates, n_folds, scheme, embargo)

    regime_arr = np.asarray(regimes) if regimes is not None else None
    fold_reports = []
    pooled_on: list[np.ndarray] = []
    pooled_base: list[np.ndarray] = []
    on_regime_labels: list[np.ndarray] = []
    base_regime_labels: list[np.ndarray] = []
    for train_idx, test_idx in folds:
        on = feature[test_idx]
        test_ret = ret[test_idx]
        on_ret = test_ret[on]
        if len(on_ret) == 0:
            continue
        base_ev = float(test_ret.mean())
        on_ev = float(on_ret.mean())
        fold_reports.append(
            {
                "n_test": int(len(test_ret)),
                "n_on": int(on.sum()),
                "baseline_ev": round(base_ev, 3),
                "on_ev": round(on_ev, 3),
                "uplift": round(on_ev - base_ev, 3),
            }
        )
        pooled_on.append(on_ret)
        pooled_base.append(test_ret)
        if regime_arr is not None:
            on_regime_labels.append(regime_arr[test_idx][on])
            base_regime_labels.append(regime_arr[test_idx])

    if not fold_reports:
        return {"n_folds": 0, "uplift_ci": None, "folds": []}

    on_all = np.concatenate(pooled_on)
    base_all = np.concatenate(pooled_base)
    base_ev_all = float(base_all.mean())
    on_ci = metrics.bootstrap_ci(on_all, metrics.expectancy_metric, n=ci_n, seed=seed)
    # 上乗せCI = シグナルEVのCI から固定ベースラインEVを差し引く(保守的近似)
    uplift_ci = {
        "point": round(on_ci["point"] - base_ev_all, 3) if on_ci["point"] is not None else None,
        "low": round(on_ci["low"] - base_ev_all, 3) if on_ci["low"] is not None else None,
        "high": round(on_ci["high"] - base_ev_all, 3) if on_ci["high"] is not None else None,
        "n": on_ci["n"],
    }
    uplifts = np.array([f["uplift"] for f in fold_reports])

    regime_uplifts: dict[str, float | None] = {}
    if on_regime_labels:
        labels = np.concatenate(on_regime_labels)
        base_labels = np.concatenate(base_regime_labels)
        for reg in np.unique(labels):
            on_reg = on_all[labels == reg]
            base_reg = base_all[base_labels == reg]
            if len(on_reg) and len(base_reg):
                regime_uplifts[str(reg)] = round(float(on_reg.mean() - base_reg.mean()), 3)

    return {
        "n_folds": len(fold_reports),
        "folds": fold_reports,
        "on_ev": round(float(on_all.mean()), 3),
        "baseline_ev": round(base_ev_all, 3),
        "uplift_ci": uplift_ci,
        "uplift_mean": round(float(uplifts.mean()), 3),
        "uplift_positive_fraction": round(float((uplifts > 0).mean()), 3),
        "regime_uplifts": regime_uplifts,
    }


def sensitivity(param_values, eval_fn: Callable[[float], float]) -> dict:
    """閾値などを格子で振って指標(例: OOS EV)の曲面を得る。平坦なほど頑健。"""
    grid = [{"param": p, "metric": round(float(eval_fn(p)), 3)} for p in param_values]
    vals = np.array([g["metric"] for g in grid])
    if len(vals) == 0:
        return {"grid": [], "spread": 0.0, "best_param": None, "mean": None}
    return {
        "grid": grid,
        "spread": round(float(vals.max() - vals.min()), 3),
        "best_param": grid[int(np.argmax(vals))]["param"],
        "mean": round(float(vals.mean()), 3),
    }


def is_flat(sens: dict, tolerance: float) -> bool:
    """感度曲面が平坦(＝最適値が孤立したスパイクでない)か。"""
    return sens.get("spread", 0.0) <= tolerance


def evaluate_gate(
    oos_uplift_ci: dict | None,
    regime_uplifts: dict[str, float | None],
    sensitivity_flat: bool,
    min_margin: float = 0.0,
    min_regimes: int = 2,
) -> dict:
    """採用ゲート: OOS上乗せCI下限・相場横断の符号一致・感度平坦で keep/downweight/drop を判定。

    勝率ではなく期待値(のCI下限)で判断する。標本不足でCIが出ないものは採用しない。
    """
    if not oos_uplift_ci or oos_uplift_ci.get("low") is None:
        return {"verdict": "drop", "reason": "OOS標本不足でCIが算出不能"}
    low = oos_uplift_ci["low"]
    n_pos = sum(1 for v in regime_uplifts.values() if v is not None and v > 0)

    if low > min_margin and n_pos >= min_regimes and sensitivity_flat:
        return {
            "verdict": "keep",
            "reason": f"OOS上乗せCI下限{low:+.3f}>{min_margin}・有効相場{n_pos}個・感度平坦",
        }
    if low > 0:
        return {
            "verdict": "downweight",
            "reason": f"OOS上乗せCI下限{low:+.3f}は正だが相場{n_pos}個/感度平坦={sensitivity_flat}で確度不足",
        }
    return {"verdict": "drop", "reason": f"OOS上乗せCI下限{low:+.3f}が0以下"}
