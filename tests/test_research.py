import numpy as np
import pandas as pd

from stock_analyzer.research import (
    auc_score,
    basic_stats,
    classify_regime,
    classify_symbol_types,
    feature_frame,
    spearman_monotonicity,
    strategy_frame,
)


def test_auc_perfect_separation():
    scores = np.array([1.0, 2.0, 3.0, 10.0, 11.0, 12.0])
    wins = np.array([False, False, False, True, True, True])
    assert auc_score(scores, wins) == 1.0


def test_auc_symmetric_is_half():
    scores = np.array([1.0, 2.0, 3.0, 4.0])
    wins = np.array([True, False, False, True])  # 勝ち{1,4} 負け{2,3} → 対称
    assert auc_score(scores, wins) == 0.5


def test_auc_handles_ties_and_degenerate():
    scores = np.array([1.0, 1.0, 1.0, 1.0])
    wins = np.array([True, False, True, False])
    assert auc_score(scores, wins) == 0.5
    assert auc_score(np.array([1.0]), np.array([True])) is None


def test_spearman_monotonicity():
    assert spearman_monotonicity([0, 1, 2, 3], [40, 45, 50, 55]) == 1.0
    assert spearman_monotonicity([0, 1, 2, 3], [55, 50, 45, 40]) == -1.0
    assert spearman_monotonicity([0, 1], [1, 2]) is None


def test_classify_regime_labels():
    n = 400
    index = pd.bdate_range("2023-01-04", periods=n)
    rising = pd.Series(np.linspace(100, 200, n), index=index)
    regime = classify_regime(rising)
    assert regime.iloc[-1] == "上昇"
    falling = pd.Series(np.linspace(200, 80, n), index=index)
    assert classify_regime(falling).iloc[-1] == "下落"
    flat = pd.Series(np.full(n, 100.0), index=index)
    assert classify_regime(flat).iloc[-1] == "横ばい"


def test_classify_symbol_types():
    assert "大型株" in classify_symbol_types({"market_cap": 5e12})
    assert "小型株" in classify_symbol_types({"market_cap": 1e10})
    assert "バリュー株" in classify_symbol_types({"pbr": 0.8})
    assert "グロース株" in classify_symbol_types({"pbr": 4.0})
    assert "高配当株" in classify_symbol_types({"dividend_yield": 4.2})
    assert classify_symbol_types({}) == []


def _frame(n=400, seed=3):
    rng = np.random.default_rng(seed)
    close = np.maximum(100 + np.cumsum(rng.normal(0, 1.0, n)), 5)
    index = pd.bdate_range("2023-01-04", periods=n)
    return pd.DataFrame(
        {
            "Close": close,
            "High": close + 1,
            "Low": close - 1,
            "Volume": rng.uniform(1e5, 5e5, n),
            "Dividends": np.zeros(n),
        },
        index=index,
    )


def test_feature_and_strategy_frames_are_boolean_and_aligned():
    frame = _frame()
    f = feature_frame(frame, None)
    s = strategy_frame(f)
    assert len(f) == len(frame) and len(s) == len(frame)
    for col in f.columns:
        assert f[col].dtype == bool, col
    # 戦略の定義: 順張りは3条件のAND
    manual = f["25日線上"] & f["MA上昇配列"] & f["MACD上"]
    assert (s["順張り"] == manual).all()
    # レンジは順張り/ブレイクアウトと重複しない
    assert not (s["レンジ"] & (s["順張り"] | s["ブレイクアウト"])).any()


def test_detect_strategies_matches_strategy_frame_definitions():
    """通知側detect_strategiesとresearch側strategy_frameが同じ判定になること。"""
    from stock_analyzer.analysis import HoldingAnalysis
    from stock_analyzer.indicators import (
        bollinger_sigma,
        evaluate_volume_price,
        macd,
        relative_strength_index,
        simple_moving_average,
        support_resistance,
    )
    from stock_analyzer.portfolio import Holding
    from stock_analyzer.summary import detect_strategies

    frame = _frame(seed=11)
    f = feature_frame(frame, None)
    s = strategy_frame(f)

    for i in (120, 200, 280, 399):
        closes = frame["Close"].iloc[: i + 1].tolist()
        highs = frame["High"].iloc[: i + 1].tolist()
        lows = frame["Low"].iloc[: i + 1].tolist()
        volumes = frame["Volume"].iloc[: i + 1].tolist()
        analysis = HoldingAnalysis(
            holding=Holding("T.T", 0, 0.0),
            name=None,
            current_price=closes[-1],
            sma_short=simple_moving_average(closes, 5),
            sma_mid=simple_moving_average(closes, 25),
            sma_long=simple_moving_average(closes, 75),
            rsi=relative_strength_index(closes, 14),
            momentum=None,
            macd_result=macd(closes),
            bollinger=bollinger_sigma(closes),
            volume_signal="",
            volume_trend_ratio=None,
            volume_price_signal=evaluate_volume_price(closes, volumes),
            levels=support_resistance(highs, lows),
            period_high=None,
            period_low=None,
            per=None,
            pbr=None,
            dividend_yield=None,
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
            sma_mid_prev10=simple_moving_average(closes[:-10], 25),
        )
        live = set(detect_strategies(analysis))
        vectorized = {name for name in s.columns if bool(s[name].iloc[i])}
        assert live == vectorized, f"day {i}: live={live} vectorized={vectorized}"


def test_strategy_priority_matches_notification_side():
    from stock_analyzer.backtest_stats import STRATEGY_PRIORITY as NOTIFY_PRIORITY
    from stock_analyzer.research import STRATEGY_PRIORITY as RESEARCH_PRIORITY

    assert NOTIFY_PRIORITY == RESEARCH_PRIORITY


def test_knn_study_finds_signal_when_feature_predicts_returns():
    """特徴量がリターンを決めるデータでは、kNN予測の上位群が実際に高リターンになること。"""
    from stock_analyzer.research import knn_study

    rng = np.random.default_rng(0)
    n_train, n_test = 6000, 2500
    x_train = rng.normal(0, 1, n_train)
    x_test = rng.normal(0, 1, n_test)
    # リターン = 特徴量×2 + ノイズ
    obs = pd.DataFrame(
        {
            "数値:f1": np.concatenate([x_train, x_test]),
            "数値:f2": rng.normal(0, 1, n_train + n_test),  # 無関係な特徴量
            "ret": np.concatenate(
                [x_train * 2 + rng.normal(0, 1, n_train), x_test * 2 + rng.normal(0, 1, n_test)]
            ),
            "is_train": [True] * n_train + [False] * n_test,
        }
    )
    result = knn_study(obs, k=100, max_test=2500)
    assert result is not None
    assert result["auc"] > 0.7
    assert result["monotonicity_expectancy"] == 1.0
    assert result["top20pct"]["expectancy"] > result["bottom20pct"]["expectancy"] + 1.0


def test_knn_study_returns_none_when_insufficient_data():
    from stock_analyzer.research import knn_study

    obs = pd.DataFrame({"数値:f1": [1.0] * 100, "ret": [0.0] * 100, "is_train": [True] * 100})
    assert knn_study(obs) is None


def test_numeric_feature_frame_columns_and_scale_independence():
    from stock_analyzer.research import numeric_feature_frame

    frame = _frame()
    nf = numeric_feature_frame(frame, None)
    assert list(nf.columns) == [
        "RSI",
        "MACD相対",
        "25日線乖離",
        "25vs75日線",
        "10日騰落",
        "対市場10日",
        "ATR比",
        "出来高比",
        "配当利回り",
    ]
    # 株価水準に依存しない(10倍しても同じ値になる)特徴量であること
    scaled = frame.copy()
    for col in ("Close", "High", "Low"):
        scaled[col] = scaled[col] * 10
    nf10 = numeric_feature_frame(scaled, None)
    pd.testing.assert_frame_equal(nf, nf10, check_exact=False, atol=1e-6)


def test_basic_stats_expectancy_is_mean_return():
    stats = basic_stats(np.array([10.0, -5.0, 10.0, -5.0]))
    assert stats["expectancy"] == 2.5
    assert stats["win_rate"] == 50.0
    assert stats["profit_factor"] == 2.0
