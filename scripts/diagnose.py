"""1銘柄の分析入力と出力を並べて表示する診断ツール(分析ロジック調整の検証用)。

使い方: python scripts/diagnose.py 9202 4519
出力を見ながらロジックを改修し、評価が実態に近づくまで反復する。ハードコードで
出力を合わせるのではなく、入力(株価位置・アナリスト目標・成長・財務)から妥当な
結論が導かれているかを確認するための計器。
"""

from __future__ import annotations

import sys

from stock_analyzer.analysis import analyze_holding
from stock_analyzer.backtest_stats import load_stats
from stock_analyzer.decision import build_decision
from stock_analyzer.horizon_model import expected_returns, long_term_estimate
from stock_analyzer.portfolio import Holding, normalize_symbol
from stock_analyzer.summary import build_summary
from stock_analyzer.valuation import analyst_upside_pct, discount_pct, fair_value


def _pct_pos(a) -> str:
    if a.period_high and a.period_low and a.current_price and a.period_high > a.period_low:
        pos = (a.current_price - a.period_low) / (a.period_high - a.period_low) * 100
        off_low = (a.current_price / a.period_low - 1) * 100
        off_high = (a.current_price / a.period_high - 1) * 100
        return f"52w内位置 {pos:.0f}%（安値から{off_low:+.0f}% / 高値から{off_high:+.0f}%）"
    return "52w内位置 —"


def diagnose(code: str) -> None:
    symbol = normalize_symbol(code)
    a = analyze_holding(Holding(symbol=symbol, quantity=0, avg_cost=0.0))
    backtest = load_stats()
    summary = build_summary(a, "中立", None, None)
    summary.horizons = []
    decision = build_decision(summary, a, expected_returns(summary, a, backtest))
    lt_pct, lt_stars, lt_reason = long_term_estimate(a)

    print(f"\n===== {symbol}  {a.name or ''} ({a.sector}) =====")
    print(f"現在値 {a.current_price} / {_pct_pos(a)}")
    print(f"SMA25/75/200: {a.sma_mid} / {a.sma_long} / {getattr(a,'sma_200',None)}  RSI {a.rsi}")
    print(f"PER {a.per} / PBR {a.pbr} / EPS {a.eps} / ROE {a.roe}")
    print(f"売上成長 {a.revenue_growth} / 利益成長 {a.earnings_growth} / 配当利回り {a.dividend_yield}")
    print(
        f"アナリスト目標 mean {a.target_mean_price} / median {a.target_median_price} "
        f"/ high {a.target_high_price} / low {a.target_low_price} / n {a.num_analysts} "
        f"/ rec {a.recommendation_mean}"
    )
    print(f"適正価格 {fair_value(a)} / 割安率 {discount_pct(a)} / アナリスト上値 {analyst_upside_pct(a)}")
    print(f"長期期待(モデル) {lt_pct} {lt_stars} 〔{lt_reason}〕")
    print(f"総合スコア {summary.score}（raw {summary.raw_score}）→ {decision.overall_stars} {decision.action}")
    print("期待リターン:", [(h.label, h.pct, h.stars) for h in decision.expected_returns])


def main() -> None:
    codes = sys.argv[1:] or ["9202", "4519"]
    for code in codes:
        try:
            diagnose(code)
        except Exception as e:
            print(f"[{code}] 失敗: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
