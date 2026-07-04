from stock_analyzer.fundamentals import evaluate_pbr, evaluate_per


def test_evaluate_per_returns_cheap_when_at_or_below_threshold():
    assert evaluate_per(15.0, threshold=15.0) == "割安"


def test_evaluate_per_returns_expensive_when_above_threshold():
    assert evaluate_per(20.0, threshold=15.0) == "割高"


def test_evaluate_per_returns_data_missing_when_none():
    assert evaluate_per(None) == "データ不足"


def test_evaluate_pbr_returns_cheap_when_at_or_below_threshold():
    assert evaluate_pbr(1.0, threshold=1.0) == "割安"


def test_evaluate_pbr_returns_expensive_when_above_threshold():
    assert evaluate_pbr(2.5, threshold=1.0) == "割高"


def test_evaluate_pbr_returns_data_missing_when_none():
    assert evaluate_pbr(None) == "データ不足"
