from stock_analyzer.market import evaluate_market_sentiment


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
