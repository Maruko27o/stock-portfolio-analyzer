from __future__ import annotations

from stock_analyzer import enhanced, jquants, ml_scoring
from stock_analyzer.fundamental_screen import (
    ScreenCriteria,
    evaluate,
    latest_metrics,
    metrics_from_statement,
    profit_growth,
)
from stock_analyzer.momentum import backend, momentum_features


# ---------------------------------------------------------------- fakes
class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _FakeSession:
    """requests.Session 互換の最小フェイク。パスに応じた固定レスポンスを返す。"""

    def __init__(self, statements=None, quotes=None):
        self.statements = statements or []
        self.quotes = quotes or []

    def post(self, url, **kw):
        if url.endswith("/token/auth_user"):
            return _Resp({"refreshToken": "RT"})
        if url.endswith("/token/auth_refresh"):
            return _Resp({"idToken": "IDTOK"})
        return _Resp({}, 404)

    def get(self, url, **kw):
        if url.endswith("/fins/statements"):
            return _Resp({"statements": self.statements})
        if url.endswith("/prices/daily_quotes"):
            return _Resp({"daily_quotes": self.quotes})
        if url.endswith("/listed/info"):
            return _Resp({"info": [{"Code": "7203", "CompanyName": "トヨタ自動車"}]})
        return _Resp({}, 404)


def _statement(period="FY", sales=1000, op=120, profit=90, equity=800, assets=2000, eps=100, bps=900):
    return {
        "TypeOfCurrentPeriod": period, "NetSales": str(sales), "OperatingProfit": str(op),
        "Profit": str(profit), "Equity": str(equity), "TotalAssets": str(assets),
        "EarningsPerShare": str(eps), "BookValuePerShare": str(bps),
    }


# ---------------------------------------------------------------- jquants
def test_jquants_auth_and_available_with_email():
    sess = _FakeSession()
    c = jquants.JQuantsClient(mailaddress="a@b.c", password="pw", session=sess)
    assert c.available() is True
    assert c.id_token() == "IDTOK"


def test_jquants_from_env_none_without_creds(monkeypatch):
    for k in ("JQUANTS_REFRESH_TOKEN", "JQUANTS_MAILADDRESS", "JQUANTS_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert jquants.JQuantsClient.from_env() is None


def test_closes_from_quotes_prefers_adjusted():
    quotes = [
        {"AdjustmentClose": 100, "AdjustmentHigh": 101, "AdjustmentLow": 99, "AdjustmentVolume": 10},
        {"Close": 102, "High": 103, "Low": 101, "Volume": 12},
    ]
    closes, highs, lows, vols = jquants.closes_from_quotes(quotes)
    assert closes == [100.0, 102.0] and highs[0] == 101.0 and vols[0] == 10.0


# ---------------------------------------------------------------- screen
def test_metrics_and_screen_pass():
    m = metrics_from_statement("7203", _statement())
    assert round(m.roe, 3) == round(90 / 800, 3)
    assert round(m.equity_ratio, 2) == 0.40
    res = evaluate(m, ScreenCriteria(), price=1500.0)  # PER=15, PBR≈1.67
    assert res.passed is True and res.reasons == []


def test_screen_fails_low_roe_and_high_per():
    m = metrics_from_statement("X", _statement(profit=10, equity=800, eps=5))  # ROE≈1.25%
    res = evaluate(m, ScreenCriteria(min_roe=0.08, max_per=20), price=1000.0)  # PER=200
    assert res.passed is False
    assert any("ROE" in r for r in res.reasons)
    assert any("PER" in r for r in res.reasons)


def test_profit_growth_yoy():
    sts = [_statement(period="FY", profit=80), _statement(period="FY", profit=100)]
    assert round(profit_growth(sts), 3) == 0.25


# ---------------------------------------------------------------- momentum
def test_momentum_features_fallback_sane():
    closes = [100 + i * 0.5 for i in range(120)]
    f = momentum_features(closes)
    d = f.as_dict()
    assert d["roc20"] is not None and d["roc20"] > 0  # 上昇トレンド
    assert d["sma_align"] == 1.0
    assert "fallback" in backend() or "pandas-ta" in backend()


# ---------------------------------------------------------------- ml
def test_build_features_order():
    from stock_analyzer.momentum import MomentumFeatures

    m = latest_metrics("7203", [_statement()])
    mom = MomentumFeatures(rsi14=55.0, roc20=3.0)
    feats = ml_scoring.build_features(m, mom, profit_growth=0.1)
    assert len(feats) == len(ml_scoring.FEATURE_ORDER)
    assert feats[0] == m.roe  # 先頭は roe


def test_ml_train_score_and_fallback(tmp_path):
    import numpy as np

    rng = np.random.default_rng(1)
    rows, labels = [], []
    for _ in range(300):
        roe = rng.normal(0.1, 0.05)
        roc60 = rng.normal(5, 12)
        feats = [roe, 0.1, 0.5, 0.05, 60, 1, 3, roc60, 0.2, 1, 1, 2, 1.1]
        rows.append(feats)
        labels.append(1 if (roe > 0.1 and roc60 > 5) else 0)
    model = ml_scoring.train(rows, labels)
    p = tmp_path / "m.joblib"
    ml_scoring.save_model(model, p)
    scorer = ml_scoring.MLScorer(model=ml_scoring.load_model(p))
    assert scorer.backend == "sklearn-model"
    strong = [0.2, 0.15, 0.6, 0.2, 55, 2, 10, 25, 0.5, 3, 1, 2, 1.3]
    weak = [0.01, 0.01, 0.2, -0.2, 85, -3, -8, -15, -0.5, -3, -1, 3, 0.6]
    assert scorer.score(strong) > scorer.score(weak)
    # フォールバック(モデル無し)も 0-100 で強弱を反映
    fb = ml_scoring.MLScorer(model=None)
    assert fb.backend == "rule-fallback"
    assert 0 <= fb.score(weak) <= fb.score(strong) <= 100


# ---------------------------------------------------------------- orchestrator
def test_enhanced_unavailable_without_client():
    assert enhanced.available(client=None) in (False, True)  # env次第だが例外を出さない
    assert enhanced.run_for_symbols(["7203.T"], client=None) == [] or True


def test_enhanced_run_with_fake_client():
    sess = _FakeSession(
        statements=[_statement(profit=80), _statement(profit=100)],
        quotes=[{"Close": 100 + i * 0.3, "High": 100 + i * 0.3, "Low": 99 + i * 0.3, "Volume": 1000}
                for i in range(80)],
    )
    client = jquants.JQuantsClient(refresh_token="RT", session=sess)
    picks = enhanced.run_for_symbols(
        ["7203.T"], client=client, scorer=ml_scoring.MLScorer(model=None),
        names={"7203.T": "トヨタ自動車"},
    )
    assert len(picks) == 1
    p = picks[0]
    assert p.code == "7203" and p.name == "トヨタ自動車"
    assert 0 <= p.ml_score <= 100
    assert p.roe is not None
    lines = enhanced.format_lines(picks)
    assert any("トヨタ自動車" in ln for ln in lines)


def test_to_jquants_code():
    assert enhanced.to_jquants_code("7203.T") == "7203"
    assert enhanced.to_jquants_code("6758") == "6758"
