from stock_analyzer.indicators import (
    SupportResistance,
    bollinger_sigma,
    evaluate_bollinger,
    evaluate_macd,
    evaluate_price_position,
    evaluate_volume,
    macd,
    period_high_low,
    relative_strength_index,
    simple_moving_average,
    support_resistance,
)


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
