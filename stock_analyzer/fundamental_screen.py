"""財務スクリーニング [パイプライン第1段: J-Quants 財務でふるいにかける]。

J-Quants の財務諸表(/fins/statements)から健全性・収益性の指標を取り出し、明示的な
基準でユニバースを絞る。基準は透明・調整可能にし、どの条件で落ちたかを理由として返す。

J-Quants の数値フィールドは文字列で返ることが多いため、安全にパースする(不正値は None)。
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _num(value) -> float | None:
    """J-Quants の数値(文字列/空/None混在)を安全に float へ。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class FinancialMetrics:
    code: str
    fiscal_period: str | None = None
    net_sales: float | None = None
    operating_profit: float | None = None
    profit: float | None = None
    equity: float | None = None
    total_assets: float | None = None
    eps: float | None = None
    bps: float | None = None

    @property
    def roe(self) -> float | None:
        if self.profit is None or not self.equity:
            return None
        return self.profit / self.equity

    @property
    def operating_margin(self) -> float | None:
        if self.operating_profit is None or not self.net_sales:
            return None
        return self.operating_profit / self.net_sales

    @property
    def equity_ratio(self) -> float | None:
        if self.equity is None or not self.total_assets:
            return None
        return self.equity / self.total_assets

    def per(self, price: float | None) -> float | None:
        if price is None or not self.eps or self.eps <= 0:
            return None
        return price / self.eps

    def pbr(self, price: float | None) -> float | None:
        if price is None or not self.bps or self.bps <= 0:
            return None
        return price / self.bps


def metrics_from_statement(code: str, statement: dict) -> FinancialMetrics:
    """J-Quants の1財務諸表レコードを FinancialMetrics へ変換する。"""
    g = statement.get
    return FinancialMetrics(
        code=code,
        fiscal_period=g("TypeOfCurrentPeriod") or g("CurrentPeriodEndDate"),
        net_sales=_num(g("NetSales")),
        operating_profit=_num(g("OperatingProfit")),
        profit=_num(g("Profit") or g("ProfitAttributableToOwnersOfParent")),
        equity=_num(g("Equity")),
        total_assets=_num(g("TotalAssets")),
        eps=_num(g("EarningsPerShare")),
        bps=_num(g("BookValuePerShare")),
    )


def latest_metrics(code: str, statements: list[dict]) -> FinancialMetrics | None:
    """時系列の財務諸表から最新(通期優先)の指標を取り出す。"""
    if not statements:
        return None
    # 通期(FY)を優先し、無ければ末尾(最新)を採用。
    fy = [s for s in statements if (s.get("TypeOfCurrentPeriod") or "").upper() == "FY"]
    chosen = (fy or statements)[-1]
    return metrics_from_statement(code, chosen)


def profit_growth(statements: list[dict]) -> float | None:
    """通期利益の前年比(YoY)。2期分の通期が取れれば算出、無ければ None。"""
    fy = [s for s in statements if (s.get("TypeOfCurrentPeriod") or "").upper() == "FY"]
    if len(fy) < 2:
        return None
    cur = _num(fy[-1].get("Profit") or fy[-1].get("ProfitAttributableToOwnersOfParent"))
    prev = _num(fy[-2].get("Profit") or fy[-2].get("ProfitAttributableToOwnersOfParent"))
    if cur is None or not prev or prev == 0:
        return None
    return (cur - prev) / abs(prev)


@dataclass
class ScreenCriteria:
    """財務スクリーニングの基準(すべて任意・調整可能)。"""

    min_roe: float | None = 0.08
    min_equity_ratio: float | None = 0.30
    min_operating_margin: float | None = 0.03
    require_profitable: bool = True  # 当期黒字(Profit>0)
    max_per: float | None = 30.0  # price が与えられた時のみ評価
    max_pbr: float | None = 4.0


@dataclass
class ScreenResult:
    code: str
    passed: bool
    metrics: FinancialMetrics
    reasons: list[str] = field(default_factory=list)  # 落ちた/満たした条件の説明


def evaluate(metrics: FinancialMetrics, criteria: ScreenCriteria, price: float | None = None) -> ScreenResult:
    """1銘柄を基準で評価する。満たさない条件を reasons に列挙。"""
    fails: list[str] = []
    if criteria.require_profitable and (metrics.profit is None or metrics.profit <= 0):
        fails.append("当期赤字/利益欠損")
    if criteria.min_roe is not None and metrics.roe is not None and metrics.roe < criteria.min_roe:
        fails.append(f"ROE{metrics.roe*100:.1f}%<{criteria.min_roe*100:.0f}%")
    if (
        criteria.min_equity_ratio is not None
        and metrics.equity_ratio is not None
        and metrics.equity_ratio < criteria.min_equity_ratio
    ):
        fails.append(f"自己資本比率{metrics.equity_ratio*100:.0f}%<{criteria.min_equity_ratio*100:.0f}%")
    if (
        criteria.min_operating_margin is not None
        and metrics.operating_margin is not None
        and metrics.operating_margin < criteria.min_operating_margin
    ):
        fails.append(f"営業利益率{metrics.operating_margin*100:.1f}%<{criteria.min_operating_margin*100:.0f}%")
    per = metrics.per(price)
    if criteria.max_per is not None and per is not None and per > criteria.max_per:
        fails.append(f"PER{per:.1f}>{criteria.max_per:.0f}")
    pbr = metrics.pbr(price)
    if criteria.max_pbr is not None and pbr is not None and pbr > criteria.max_pbr:
        fails.append(f"PBR{pbr:.1f}>{criteria.max_pbr:.0f}")
    return ScreenResult(code=metrics.code, passed=not fails, metrics=metrics, reasons=fails)


def screen_codes(
    codes: list[str],
    client,
    criteria: ScreenCriteria | None = None,
    prices: dict[str, float] | None = None,
) -> list[ScreenResult]:
    """コード列を J-Quants 財務でスクリーニングし、結果(通過/理由)を返す。

    client は JQuantsClient。prices があれば PER/PBR も評価に使う。
    """
    criteria = criteria or ScreenCriteria()
    prices = prices or {}
    out: list[ScreenResult] = []
    for code in codes:
        statements = client.financial_statements(code)
        metrics = latest_metrics(code, statements)
        if metrics is None:
            out.append(ScreenResult(code, False, FinancialMetrics(code), ["財務データなし"]))
            continue
        out.append(evaluate(metrics, criteria, prices.get(code)))
    return out
