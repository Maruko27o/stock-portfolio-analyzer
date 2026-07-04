from stock_analyzer.indicators import relative_strength_index, simple_moving_average


def test_simple_moving_average_computes_average_of_recent_window():
    assert simple_moving_average([1, 2, 3, 4, 5], 3) == 4.0


def test_simple_moving_average_returns_none_when_not_enough_data():
    assert simple_moving_average([1, 2], 3) is None


def test_relative_strength_index_returns_100_when_no_losses():
    prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
    assert relative_strength_index(prices, period=14) == 100.0


def test_relative_strength_index_returns_none_when_not_enough_data():
    assert relative_strength_index([1, 2, 3], period=14) is None
