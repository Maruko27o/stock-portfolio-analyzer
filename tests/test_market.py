from stock_analyzer.market import (
    NON_EQUITY_NAMES,
    evaluate_market_sentiment,
    market_stance,
)


def test_evaluate_market_sentiment_returns_bullish_when_majority_up():
    snapshot = {
        "日経平均": (39000.0, 1.2),
        "TOPIX": (2700.0, 0.8),
        "NYダウ": (40000.0, -0.3),
        "ドル円": (150.0, 0.1),
        "VIX": (14.0, -2.0),
    }
    assert evaluate_market_sentiment(snapshot) == "強気"


def test_evaluate_market_sentiment_returns_bearish_when_majority_down():
    snapshot = {
        "日経平均": (38000.0, -1.5),
        "TOPIX": (2650.0, -0.9),
        "NYダウ": (39500.0, 0.2),
    }
    assert evaluate_market_sentiment(snapshot) == "弱気"


def test_evaluate_market_sentiment_returns_neutral_when_tied():
    snapshot = {
        "日経平均": (38500.0, 1.0),
        "TOPIX": (2680.0, -1.0),
    }
    assert evaluate_market_sentiment(snapshot) == "中立"


def test_evaluate_market_sentiment_ignores_fx_and_vix():
    snapshot = {
        "ドル円": (150.0, 3.0),
        "VIX": (12.0, -5.0),
    }
    assert evaluate_market_sentiment(snapshot) == "データ不足"


def test_evaluate_market_sentiment_returns_data_missing_when_all_none():
    snapshot = {"日経平均": (None, None)}
    assert evaluate_market_sentiment(snapshot) == "データ不足"


def test_long_rate_excluded_from_breadth():
    # 長期金利は株価指数でないので breadth 判定から除外される
    assert "長期金利" in NON_EQUITY_NAMES
    snapshot = {
        "日経平均": (39000.0, 1.2),
        "TOPIX": (2700.0, 0.8),
        "長期金利": (4.2, 5.0),  # 大きな+でも株の強弱には数えない
    }
    assert evaluate_market_sentiment(snapshot) == "強気"


def test_market_stance_five_levels_strong_bull():
    snapshot = {
        "日経平均": (39000.0, 2.0),
        "TOPIX": (2700.0, 1.8),
        "NYダウ": (40000.0, 1.5),
        "NASDAQ": (18000.0, 2.2),
    }
    assert market_stance(snapshot, vix=13.0) == "強気"


def test_market_stance_weak_bear_when_broadly_down():
    snapshot = {
        "日経平均": (38000.0, -2.0),
        "TOPIX": (2650.0, -1.8),
        "NYダウ": (39500.0, -1.2),
    }
    assert market_stance(snapshot, vix=20.0) == "弱気"


def test_market_stance_high_vix_pulls_bearish():
    # 僅かにプラスでも VIX 高で弱気側へ寄る
    snapshot = {"日経平均": (38500.0, 0.2), "TOPIX": (2680.0, -0.1)}
    stance = market_stance(snapshot, vix=30.0)
    assert stance in ("中立", "やや弱気", "弱気")


def test_market_stance_empty_is_neutral():
    assert market_stance({"日経平均": (None, None)}, vix=None) == "中立"
