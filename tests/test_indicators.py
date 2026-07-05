from stock_analyzer.indicators import (
    SupportResistance,
    average_true_range,
    bollinger_sigma,
    evaluate_bollinger,
    evaluate_macd,
    evaluate_price_position,
    evaluate_volume,
    evaluate_volume_price,
    macd,
    period_high_low,
    rate_of_change,
    relative_strength_index,
    simple_moving_average,
    support_resistance,
    volume_trend,
)


def test_average_true_range_uses_range_and_gaps():
    # Flat 10-point daily ranges, no gaps → ATR is exactly 10.
    n = 20
    highs = [110.0] * n
    lows = [100.0] * n
    closes = [105.0] * n
    assert average_true_range(highs, lows, closes, period=14) == 10.0


def test_average_true_range_counts_gap_over_prior_close():
    # A gap up beyond the day's own range widens the true range.
    highs = [110.0] * 15 + [130.0]
    lows = [100.0] * 15 + [125.0]
    closes = [105.0] * 15 + [128.0]
    atr = average_true_range(highs, lows, closes, period=14)
    # 13 normal days (TR 10) + gap day (TR = 130 - 105 = 25) averaged over 14.
    assert atr == (13 * 10.0 + 25.0) / 14


def test_average_true_range_needs_enough_data():
    assert average_true_range([1.0] * 5, [1.0] * 5, [1.0] * 5, period=14) is None


def test_simple_moving_average_computes_average_of_recent_window():
    assert simple_moving_average([1, 2, 3, 4, 5], 3) == 4.0


def test_simple_moving_average_returns_none_when_not_enough_data():
    assert simple_moving_average([1, 2], 3) is None


def test_relative_strength_index_returns_100_when_no_losses():
    prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
    assert relative_strength_index(prices, period=14) == 100.0


def test_relative_strength_index_returns_none_when_not_enough_data():
    assert relative_strength_index([1, 2, 3], period=14) is None


def test_macd_returns_none_when_not_enough_data():
    assert macd([1.0] * 10) is None


def test_evaluate_macd_returns_data_missing_when_none():
    assert evaluate_macd(None) == "データ不足"


def test_evaluate_macd_detects_uptrend():
    prices = [100.0 + i for i in range(40)]
    assert evaluate_macd(macd(prices)) == "上昇中"


def test_evaluate_macd_detects_downtrend():
    prices = [140.0 - i for i in range(40)]
    assert evaluate_macd(macd(prices)) == "下降中"


def test_bollinger_sigma_returns_none_when_not_enough_data():
    assert bollinger_sigma([1, 2, 3], window=20) is None


def test_bollinger_sigma_is_zero_when_price_equals_mean():
    assert bollinger_sigma([100.0] * 20) == 0.0


def test_evaluate_bollinger_buckets():
    assert evaluate_bollinger(None) == "データ不足"
    assert evaluate_bollinger(3.5) == "+3σ超(バンドウォーク)"
    assert evaluate_bollinger(0) == "中央線付近"
    assert evaluate_bollinger(-3.5) == "-3σ超(バンドウォーク)"


def test_evaluate_volume_detects_spike():
    volumes = [100.0] * 20 + [250.0]
    assert evaluate_volume(volumes) == "急増(平均比2.5倍)"


def test_evaluate_volume_returns_data_missing_when_not_enough():
    assert evaluate_volume([100.0, 100.0]) == "データ不足"


def test_evaluate_volume_normal():
    assert evaluate_volume([100.0] * 21) == "平常"


def test_support_resistance_returns_none_when_not_enough_data():
    assert support_resistance([1, 2], [1, 2], window=60) is None


def test_support_resistance_computes_window_high_low():
    highs = [10.0] * 59 + [15.0]
    lows = [5.0] * 59 + [3.0]
    levels = support_resistance(highs, lows, window=60)
    assert levels.resistance == 15.0
    assert levels.support == 3.0


def test_evaluate_price_position_breakout_and_breakdown():
    levels = SupportResistance(support=100.0, resistance=110.0)
    assert evaluate_price_position(111.0, levels) == "レジスタンスブレイク"
    assert evaluate_price_position(99.0, levels) == "サポート割れ"
    assert "レジスタンスまで" in evaluate_price_position(105.0, levels)


def test_evaluate_price_position_returns_data_missing_when_none():
    assert evaluate_price_position(100.0, None) == "データ不足"


def test_period_high_low_returns_max_and_min():
    assert period_high_low([10, 20, 15], [5, 8, 3]) == (20, 3)


def test_period_high_low_returns_none_when_empty():
    assert period_high_low([], []) == (None, None)


def test_volume_trend_returns_none_when_not_enough_data():
    assert volume_trend([100.0] * 10, long_window=25) is None


def test_volume_trend_above_one_when_recent_volume_higher():
    volumes = [100.0] * 20 + [300.0] * 5
    assert volume_trend(volumes, short_window=5, long_window=25) > 1.0


def test_volume_trend_below_one_when_recent_volume_lower():
    volumes = [300.0] * 20 + [100.0] * 5
    assert volume_trend(volumes, short_window=5, long_window=25) < 1.0


def test_evaluate_volume_price_strong_uptrend():
    closes = [100, 101, 102, 103, 104, 108]
    volumes = [100, 100, 100, 100, 100, 200, 200, 200, 200, 200]
    assert evaluate_volume_price(closes, volumes, window=5) == "価格上昇×出来高増加(強い上昇)"


def test_evaluate_volume_price_weak_uptrend():
    closes = [100, 101, 102, 103, 104, 108]
    volumes = [200, 200, 200, 200, 200, 100, 100, 100, 100, 100]
    assert evaluate_volume_price(closes, volumes, window=5) == "価格上昇×出来高減少(勢い弱い)"


def test_evaluate_volume_price_strong_downtrend():
    closes = [108, 104, 103, 102, 101, 100]
    volumes = [100, 100, 100, 100, 100, 200, 200, 200, 200, 200]
    assert evaluate_volume_price(closes, volumes, window=5) == "価格下落×出来高増加(強い下落)"


def test_evaluate_volume_price_returns_data_missing_when_not_enough():
    assert evaluate_volume_price([100, 101], [100, 100], window=5) == "データ不足"


def test_rate_of_change_returns_none_when_not_enough_data():
    assert rate_of_change([100, 101, 102], period=10) is None


def test_rate_of_change_computes_percentage():
    prices = [100.0] + [0.0] * 8 + [0.0, 110.0]  # 11 points, first is 100, last is 110
    assert rate_of_change(prices, period=10) == 10.0
