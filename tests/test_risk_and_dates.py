from __future__ import annotations

from types import SimpleNamespace

from stock_analyzer import config
from stock_analyzer.summary import detect_risks


def _analysis(**kw):
    base = dict(
        days_to_earnings=None, rsi=None, bollinger=None, payout_ratio=None,
        profit_pct=None, volume_price_signal="", current_ratio=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --- カテゴリ7: リスク表示条件(明文化) ---
def test_rsi_overbought_shows_risk():
    risks = detect_risks(_analysis(rsi=config.RISK_RSI_OVERBOUGHT))
    assert any("過熱" in r for r in risks)


def test_rsi_oversold_shows_risk():
    risks = detect_risks(_analysis(rsi=config.RISK_RSI_OVERSOLD))
    assert any("売られすぎ" in r for r in risks)


def test_low_current_ratio_shows_risk():
    risks = detect_risks(_analysis(current_ratio=1.1))  # <1.2
    assert any("流動比率" in r for r in risks)
    # 1.2以上は非該当=省略
    assert detect_risks(_analysis(current_ratio=1.5)) == []


def test_payout_over_200_flagged_strongly():
    risks = detect_risks(_analysis(payout_ratio=2.5))
    assert any("200%超" in r for r in risks)


def test_no_conditions_no_risks():
    assert detect_risks(_analysis()) == []


# --- カテゴリ5: 過去日(負の日数)ガード ---
_FUND_KEYS = [
    "ex_dividend_date", "dividend_rate", "name", "per", "pbr", "dividend_yield",
    "roe", "roa", "eps", "bps", "revenue_growth", "earnings_growth", "payout_ratio",
    "debt_to_equity", "current_ratio", "sector", "industry", "forward_per",
    "target_mean_price", "target_median_price", "target_high_price", "target_low_price",
    "num_analysts", "recommendation_mean",
]


def test_stale_earnings_date_yields_no_negative(monkeypatch):
    from datetime import date, timedelta
    from stock_analyzer import analysis as analysis_mod
    from stock_analyzer.portfolio import Holding

    past = date.today() - timedelta(days=74)
    fundamentals = {k: None for k in _FUND_KEYS}
    fundamentals["name"] = "テスト"

    monkeypatch.setattr(analysis_mod, "fetch_price_history", lambda *_: None)
    monkeypatch.setattr(analysis_mod, "split_confirmed_history", lambda h: (None, None))
    monkeypatch.setattr(analysis_mod, "fetch_fundamentals", lambda *_: fundamentals)
    monkeypatch.setattr(analysis_mod, "fetch_next_earnings_date", lambda *_: past)

    result = analysis_mod.analyze_holding(Holding(symbol="7203.T", quantity=0, avg_cost=0.0))
    # 過去日は更新待ちとして扱い、負の日数を下流へ流さない
    assert result.earnings_stale is True
    assert result.days_to_earnings is None
    assert result.next_earnings is None
