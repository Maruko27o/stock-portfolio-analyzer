from stock_analyzer.fundamentals import (
    evaluate_growth,
    evaluate_payout_ratio,
    evaluate_pbr,
    evaluate_per,
    evaluate_roa,
    evaluate_roe,
)


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


def test_evaluate_roe_returns_good_when_at_or_above_threshold():
    assert evaluate_roe(0.08, threshold=0.08) == "良好"


def test_evaluate_roe_returns_low_when_below_threshold():
    assert evaluate_roe(0.03, threshold=0.08) == "低い"


def test_evaluate_roe_returns_data_missing_when_none():
    assert evaluate_roe(None) == "データ不足"


def test_evaluate_roa_returns_good_when_at_or_above_threshold():
    assert evaluate_roa(0.05, threshold=0.05) == "良好"


def test_evaluate_roa_returns_low_when_below_threshold():
    assert evaluate_roa(0.01, threshold=0.05) == "低い"


def test_evaluate_growth_returns_positive_label_when_positive():
    assert evaluate_growth(0.05, "増収", "減収") == "増収"


def test_evaluate_growth_returns_negative_label_when_zero_or_negative():
    assert evaluate_growth(0.0, "増収", "減収") == "減収"
    assert evaluate_growth(-0.02, "増収", "減収") == "減収"


def test_evaluate_growth_returns_data_missing_when_none():
    assert evaluate_growth(None, "増収", "減収") == "データ不足"


def test_evaluate_payout_ratio_returns_appropriate_when_below_threshold():
    assert evaluate_payout_ratio(0.4, threshold=0.8) == "適正"


def test_evaluate_payout_ratio_returns_high_when_at_or_above_threshold():
    assert evaluate_payout_ratio(0.9, threshold=0.8) == "高い(要注意)"


def test_evaluate_payout_ratio_returns_data_missing_when_none():
    assert evaluate_payout_ratio(None) == "データ不足"
