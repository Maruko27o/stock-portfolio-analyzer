from stock_analyzer.scoring import (
    evaluate_recommendation,
    fundamental_score,
    technical_score,
    total_score,
)


def test_technical_score_is_high_when_oversold():
    assert technical_score(25) == 50


def test_technical_score_is_low_when_overbought():
    assert technical_score(80) == 0


def test_technical_score_is_neutral_between_thresholds():
    assert technical_score(50) == 25


def test_technical_score_is_neutral_when_missing():
    assert technical_score(None) == 25


def test_fundamental_score_is_high_when_both_cheap():
    assert fundamental_score(per=10.0, pbr=0.8) == 50


def test_fundamental_score_is_low_when_both_expensive():
    assert fundamental_score(per=30.0, pbr=3.0) == 0


def test_fundamental_score_is_partial_when_missing():
    assert fundamental_score(per=None, pbr=None) == 24


def test_total_score_combines_technical_and_fundamental():
    assert total_score(rsi=25, per=10.0, pbr=0.8) == 100


def test_evaluate_recommendation_buy_when_score_high():
    assert evaluate_recommendation(70) == "買い"


def test_evaluate_recommendation_sell_when_score_low():
    assert evaluate_recommendation(30) == "売り"


def test_evaluate_recommendation_hold_when_score_mid():
    assert evaluate_recommendation(50) == "様子見"
