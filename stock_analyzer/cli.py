from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from datetime import date

from stock_analyzer.allocation import (
    AllocationPlan,
    format_allocation_lines,
    optimize_allocation,
    priority_value,
)
from stock_analyzer.analysis import HoldingAnalysis, analyze_holding
from stock_analyzer.conclusion import DailyConclusion, build_conclusion, format_conclusion_lines
from stock_analyzer.backtest_stats import (
    horizon_expectations,
    load_stats,
    load_strategy_stats,
    stats_for_score,
    stats_for_strategy,
)
from stock_analyzer.decision import HoldingDecision, build_decision, format_decision_lines
from stock_analyzer.horizon_model import expected_returns
from stock_analyzer.data_fetcher import (
    fetch_price_history,
    split_confirmed_history,
)
from stock_analyzer.discord import (
    conclusion_embed,
    failed_embed,
    holding_embed,
    manager_embed,
    market_embed,
    review_embed,
    revision_embed,
    swing_embed,
)
from stock_analyzer.fundamentals import (
    evaluate_current_ratio,
    evaluate_debt_to_equity,
    evaluate_dividend_yield,
    evaluate_growth,
    evaluate_payout_ratio,
    evaluate_pbr,
    evaluate_per,
    evaluate_roa,
    evaluate_roe,
)
from stock_analyzer.indicators import (
    evaluate_bollinger,
    evaluate_macd,
    evaluate_price_position,
    rate_of_change,
)
from stock_analyzer.flex import holding_bubble, market_bubble, swing_bubble, to_flex_messages
from stock_analyzer.market import (
    current_market_regime,
    evaluate_market_sentiment,
    fetch_market_snapshot,
    market_stance,
)
from stock_analyzer.portfolio import Holding, load_portfolio
from stock_analyzer.rebalance import RebalancePlan, build_rebalance, format_rebalance_lines
from stock_analyzer.review import format_review_lines, rule_based_review
from stock_analyzer import self_improve
from stock_analyzer.optimize import char_count, optimize_embeds, optimize_lines, reduction_pct
from stock_analyzer.screener import load_universe, prescreen_symbols
from stock_analyzer.scoring import evaluate_recommendation, total_score
from stock_analyzer.summary import (
    build_summary,
    format_ex_dividend,
    format_market_header,
)


def _fmt(value: float | None, spec: str = "{:.2f}") -> str:
    return spec.format(value) if value is not None else "データ不足"


def _pct(value: float | None, spec: str = "{:.1f}%") -> str:
    return _fmt(value * 100 if value is not None else None, spec)


def _build_detailed_block(a: HoldingAnalysis) -> list[str]:
    """Render the full, everything-included detailed block for one holding (CLI use)."""
    price_position = (
        evaluate_price_position(a.current_price, a.levels) if a.current_price is not None else "データ不足"
    )
    score = total_score(a.rsi, a.per, a.pbr)
    return [
        f"■ {a.holding.symbol} {a.name or ''}".rstrip()
        + f" ({a.holding.quantity:.0f}株 @{a.holding.avg_cost:.2f})",
        f"現在値: {_fmt(a.current_price)}",
        f"SMA25: {_fmt(a.sma_mid)} / RSI14: {_fmt(a.rsi, '{:.1f}')}",
        f"MACD: {evaluate_macd(a.macd_result)}",
        f"ボリンジャーバンド: {evaluate_bollinger(a.bollinger)}",
        f"出来高: {a.volume_signal}",
        f"出来高トレンド: {_fmt(a.volume_trend_ratio, '{:.2f}倍')} / {a.volume_price_signal}",
        f"価格位置: {price_position}",
        f"52週高値/安値: {_fmt(a.period_high)} / {_fmt(a.period_low)}",
        f"PER: {_fmt(a.per, '{:.1f}')}({evaluate_per(a.per)}) / PBR: {_fmt(a.pbr, '{:.1f}')}({evaluate_pbr(a.pbr)})",
        f"ROE: {_pct(a.roe)}({evaluate_roe(a.roe)}) / ROA: {_pct(a.roa)}({evaluate_roa(a.roa)})",
        f"EPS: {_fmt(a.eps)} / BPS: {_fmt(a.bps)}",
        f"売上成長率: {_pct(a.revenue_growth, '{:+.1f}%')}({evaluate_growth(a.revenue_growth, '増収', '減収')}) "
        f"/ 利益成長率: {_pct(a.earnings_growth, '{:+.1f}%')}({evaluate_growth(a.earnings_growth, '増益', '減益')})",
        f"配当利回り: {_fmt(a.dividend_yield, '{:.2f}%')}({evaluate_dividend_yield(a.dividend_yield)}) "
        f"/ 配当性向: {_pct(a.payout_ratio)}({evaluate_payout_ratio(a.payout_ratio)})",
        f"取得比利回り: {_fmt(a.yield_on_cost, '{:.2f}%')} "
        f"/ 権利落ち日: {format_ex_dividend(a.ex_dividend_date, a.days_to_ex_dividend, a.ex_dividend_estimated)}",
        f"負債資本倍率: {_fmt(a.debt_to_equity, '{:.0f}%')}({evaluate_debt_to_equity(a.debt_to_equity)}) "
        f"/ 流動比率: {_fmt(a.current_ratio, '{:.2f}')}({evaluate_current_ratio(a.current_ratio)})",
        f"次回決算日: {a.next_earnings.isoformat() if a.next_earnings else 'データ不足'}"
        + (f" (あと{a.days_to_earnings}日)" if a.days_to_earnings is not None else ""),
        f"セクター: {a.sector or 'データ不足'} / 業種: {a.industry or 'データ不足'}",
        f"総合スコア: {score}/100 ({evaluate_recommendation(score)})",
    ]


def _market_section() -> tuple[str, list[str], dict]:
    """Return (sentiment, detailed market lines, snapshot)."""
    snapshot = fetch_market_snapshot()
    sentiment = evaluate_market_sentiment(snapshot)
    lines = ["【市場環境】", f"市場全体: {sentiment}"]
    for name, (price, change) in snapshot.items():
        lines.append(f"{name}: {_fmt(price)} ({_fmt(change, '{:+.2f}%')})")
    return sentiment, lines, snapshot


def generate_report(holdings: list[Holding]) -> list[str]:
    """Build the full detailed report (all indicators) — used for local CLI inspection."""
    sentiment, market_lines, _ = _market_section()
    lines: list[str] = [*market_lines, ""]
    for holding in holdings:
        lines.extend(_build_detailed_block(analyze_holding(holding)))
        lines.append("")
    return lines


def render_summary_text(data: "ReportData") -> list[str]:
    """収集済み ReportData を要約テキストへ整形する(再取得しない)。LLMレビュー等でも再利用。"""
    lines: list[str] = []
    if data.conclusion is not None:
        lines.extend(format_conclusion_lines(data.conclusion))
        lines.append("")
    lines.append(format_market_header(data.stance or data.sentiment))
    lines.append("")
    if data.allocation is not None:
        lines.extend(format_allocation_lines(data.allocation))
        lines.append("")
    if data.rebalance is not None and data.rebalance.items:
        lines.extend(format_rebalance_lines(data.rebalance))
        lines.append("")
    for decision in data.decisions:
        lines.extend(format_decision_lines(decision))
        lines.append("")
    if data.revisions:
        lines.extend(self_improve.format_revision_lines(data.revisions))
        lines.append("")
    lines.extend(format_review_lines(data.review))
    lines.append("")
    if data.failed_symbols:
        lines.append("⚠️ 取得できなかった銘柄: " + ", ".join(data.failed_symbols))

    # 最適化AI: 情報量を維持したまま圧縮(冗長表現の短縮・重複除去・箇条書き化)。
    before = char_count(lines)
    lines = optimize_lines(lines)
    after = char_count(lines)
    lines.append(f"⚙️ 最適化: {before}字→{after}字 (-{reduction_pct(before, after):.0f}%)")
    return lines


def generate_summary(holdings: list[Holding], include_swing_pick: bool = True) -> list[str]:
    """Build the concise decision report (AIファンドマネージャー判断) as plain text.

    ポート全体の判断(買い優先順位・資金配分)を先頭に、各銘柄の最小カードを続ける。
    Discord の意思決定UIと同じ内容をローカル確認できるようにする。
    """
    return render_summary_text(collect_report_data(holdings, include_swing_pick=include_swing_pick))


def _analyze_with_retry(holding: Holding, attempts: int = 2, delay: float = 8.0) -> HoldingAnalysis:
    """Analyze a holding, retrying once after a pause to ride out transient rate limits."""
    for attempt in range(attempts):
        try:
            return analyze_holding(holding)
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
    raise RuntimeError("unreachable")


@dataclass
class ReportData:
    """Channel-neutral analysis result, fetched once and rendered to any medium."""

    sentiment: str
    snapshot: dict[str, tuple[float | None, float | None]] | None
    summaries: list  # list[HoldingSummary], ordered by raw_score desc
    swing_picks: list[dict]
    failed_symbols: list[str]
    as_of: date | None = None  # date of the latest price bar ("prices as of")
    decisions: list = field(default_factory=list)  # list[HoldingDecision](保有分、買い順位順)
    allocation: AllocationPlan | None = None  # ポート全体の配分計画(保有+新規候補)
    stance: str | None = None  # 市場の5段階スタンス(強気〜弱気)
    rebalance: RebalancePlan | None = None  # 保有比率の是正(現在→推奨)
    conclusion: DailyConclusion | None = None  # 本日の結論(3行)+何もしない判定
    review: list = field(default_factory=list)  # レビューAIの改善点(改修後の残指摘。空=改善不要)
    revisions: list = field(default_factory=list)  # 自己改修AIが適用した修正のログ

    def is_empty(self) -> bool:
        return not self.snapshot and not self.summaries and not self.swing_picks


BENCHMARK_TICKER = "1306.T"  # TOPIX ETF: baseline to separate stock strength from market tide


def _benchmark_context() -> tuple[float | None, date | None]:
    """Return (benchmark 10-day rate of change, date of the latest price bar).

    The latest bar date doubles as the "prices as of" stamp for the whole
    report, so the reader can always tell how fresh the numbers are.
    """
    try:
        history = fetch_price_history(BENCHMARK_TICKER)
        as_of = history.index[-1].date() if len(history) else None
        confirmed, _ = split_confirmed_history(history)
        return rate_of_change(confirmed["Close"].tolist(), 10), as_of
    except Exception:
        return None, None


# スイング候補の本格分析ファネルの規模。第1段(安価スクリーン)は全銘柄、第2段
# (ファンダ取得を伴う本格分析)は上位この数だけに絞り、取得回数・実行時間を抑える。
SCREEN_STAGE2_LIMIT = 24
SWING_TOP_N = 3


def _enriched_summary(
    analysis: HoldingAnalysis,
    sentiment: str,
    vix: float | None,
    benchmark_momentum: float | None,
    backtest: dict | None,
    strategy_stats: dict | None,
    regime: str | None,
):
    """保有・監視・新規候補を問わず、1銘柄の要約(スコア+統計+期間別実績)を作る。"""
    summary = build_summary(analysis, sentiment, vix, benchmark_momentum)
    summary.backtest = stats_for_score(backtest, summary.price_score)
    summary.strategy_stats = stats_for_strategy(strategy_stats, summary.strategies_active, regime)
    summary.horizons = horizon_expectations(backtest, summary.price_score)
    return summary


def _decision_from(summary, analysis: HoldingAnalysis, backtest: dict | None) -> HoldingDecision:
    """要約+分析から最終判断(HoldingDecision)を組み立てる。保有株と同じロジック。"""
    return build_decision(summary, analysis, expected_returns(summary, analysis, backtest))


def _company_key(decision: HoldingDecision) -> str:
    """同一企業をまとめるキー。銘柄名(無ければコード)を正規化して使う。

    国内株(9202.T)と米ADRなど、同じ会社が別コードで二重に並ぶのを防ぐ。
    """
    return (decision.name or decision.symbol).strip().lower()


def _dedup_pref(decision: HoldingDecision) -> tuple:
    """同一企業で残す1件を選ぶ優先度。保有 > 東証(.T) > スコア高。"""
    return (
        0 if decision.is_candidate else 1,  # 保有/監視カードを候補より優先
        1 if decision.symbol.upper().endswith(".T") else 0,  # 本国(東証)上場を優先
        decision.overall_score or 0,
    )


def _dedup_by_company(decisions: list[HoldingDecision]) -> list[HoldingDecision]:
    """同一企業(名寄せ)は最優先の1件だけ残す。入力順は保つ。"""
    best: dict[str, HoldingDecision] = {}
    for d in decisions:
        key = _company_key(d)
        if key not in best or _dedup_pref(d) > _dedup_pref(best[key]):
            best[key] = d
    keep = set(id(d) for d in best.values())
    return [d for d in decisions if id(d) in keep]


def _candidate_reasons(decision: HoldingDecision) -> list[str]:
    """注目候補カードに出す、保有株と同じ観点(割安・成長・期待リターン)の根拠。"""
    bits = [f"{decision.overall_stars} {decision.action}"]
    if decision.discount_pct is not None:
        bits.append(f"割安率 {decision.discount_pct:+.1f}%")
    long_term = next(
        (h for h in decision.expected_returns if h.label == "半年〜1年" and h.pct is not None),
        None,
    )
    if long_term is not None:
        basis = "検証" if long_term.basis == "検証実績" else "推定"
        bits.append(f"半年〜1年 期待 {long_term.pct:+.1f}%({basis})")
    return bits


def collect_report_data(holdings: list[Holding], include_swing_pick: bool = True) -> ReportData:
    """Fetch and compute everything once, tolerating individual failures."""
    snapshot: dict | None = None
    try:
        snapshot = fetch_market_snapshot()
        sentiment = evaluate_market_sentiment(snapshot)
    except Exception:
        sentiment = "中立"  # neutral fallback so holding scores can still be computed

    vix = snapshot.get("VIX", (None, None))[0] if snapshot else None
    benchmark_momentum, as_of = _benchmark_context()
    backtest = load_stats()  # 保存済み統計の参照のみ(ここでバックテストは走らない)
    strategy_stats = load_strategy_stats()
    regime = current_market_regime() if strategy_stats else None

    # 保有(数量あり)と監視銘柄(数量なし=未保有だが分析だけしたい)を分けて扱う。
    held = [h for h in holdings if not h.is_watch]
    watch = [h for h in holdings if h.is_watch]

    summaries = []  # 保有のみ(判断ログ・LINEに使う)
    decisions: list[HoldingDecision] = []  # 保有カード+監視カードとして表示する分
    failed_symbols = []
    for holding in held:
        try:
            analysis = _analyze_with_retry(holding)
            summary = _enriched_summary(
                analysis, sentiment, vix, benchmark_momentum, backtest, strategy_stats, regime
            )
        except Exception:
            failed_symbols.append(holding.symbol)
            continue
        summaries.append(summary)  # 要約は先に確定(判断生成に失敗しても保有は表示する)
        try:
            decisions.append(_decision_from(summary, analysis, backtest))
        except Exception:
            pass

    # 監視銘柄も保有株と同じロジックで判断化する。カードは出すが保有損益・税は付かない。
    for holding in watch:
        try:
            analysis = _analyze_with_retry(holding)
            summary = _enriched_summary(
                analysis, sentiment, vix, benchmark_momentum, backtest, strategy_stats, regime
            )
            decision = _decision_from(summary, analysis, backtest)
        except Exception:
            failed_symbols.append(holding.symbol)
            continue
        decision.is_candidate = True  # 未保有=候補扱い(リバランス/売却対象からは外れる)
        decisions.append(decision)

    summaries.sort(key=lambda s: s.raw_score, reverse=True)
    decisions.sort(key=lambda d: d.overall_score, reverse=True)
    decisions = _dedup_by_company(decisions)  # 同一企業(例: 国内株とADR)の二重掲載を防ぐ

    # スイング(新規)候補: 全銘柄を安価にスクリーン→上位のみ保有株と同じ本格分析(ファネル)。
    swing_picks: list[dict] = []
    candidate_decisions: list[HoldingDecision] = []
    if include_swing_pick:
        exclude = {h.symbol.upper() for h in holdings}
        try:
            symbols = prescreen_symbols(load_universe(), n=SCREEN_STAGE2_LIMIT, exclude=exclude)
        except Exception:
            symbols = []
        for symbol in symbols:
            try:
                analysis = _analyze_with_retry(Holding(symbol=symbol, quantity=0, avg_cost=0.0))
                cand_summary = _enriched_summary(
                    analysis, sentiment, vix, benchmark_momentum, backtest, strategy_stats, regime
                )
                cand_decision = _decision_from(cand_summary, analysis, backtest)
                cand_decision.is_candidate = True
                candidate_decisions.append(cand_decision)
            except Exception:
                pass
        # 同一企業の重複を排除し、保有/監視で既に出ている企業は候補から外す。
        held_companies = {_company_key(d) for d in decisions}
        candidate_decisions = [
            c for c in _dedup_by_company(candidate_decisions)
            if _company_key(c) not in held_companies
        ]
        # 保有株と同じ「割安×成長×期待リターン」の優先度で並べ、TOP3を注目候補に。
        candidate_decisions.sort(key=priority_value, reverse=True)
        for cand in candidate_decisions[:SWING_TOP_N]:
            heading = f"{cand.symbol} {cand.name}" if cand.name else cand.symbol
            swing_picks.append(
                {
                    "heading": heading,
                    "score": cand.overall_score,
                    "current_price": cand.current_price,
                    "reasons": _candidate_reasons(cand),
                }
            )

    # 保有＋監視＋新規候補をまとめてポート最適化(買い優先順位・資金配分)。
    allocation = optimize_allocation(decisions + candidate_decisions, regime, vix)

    # 保有比率の是正(現在→推奨)と、市場5段階スタンス、本日の結論を組み立てる。
    # リバランスは保有(数量あり)のみが対象。監視・候補は is_candidate で自動的に外れる。
    quantities = {h.symbol: h.quantity for h in held}
    rebalance = build_rebalance(decisions, quantities)
    stance = market_stance(snapshot, vix) if snapshot else None
    conclusion = build_conclusion(decisions, allocation, rebalance)

    data = ReportData(
        sentiment,
        snapshot,
        summaries,
        swing_picks,
        failed_symbols,
        as_of,
        decisions=decisions,
        allocation=allocation,
        stance=stance,
        rebalance=rebalance,
        conclusion=conclusion,
    )
    # レビューAI(自己点検): 分析結果の矛盾・過大評価・説明不足を洗い出す(無料・決定論的)。
    data.review = rule_based_review(data)
    # 自己改修AI: レビュー指摘を分析へ反映(矛盾のみ修正・点数/売買判定を再計算)。
    data.revisions = self_improve.improve(decisions, candidate_decisions)
    if data.revisions:
        # 判断が変わったので配分・リバランス・結論を再計算し、整合を取り直す。
        data.allocation = optimize_allocation(decisions + candidate_decisions, regime, vix)
        data.rebalance = build_rebalance(decisions, quantities)
        data.conclusion = build_conclusion(decisions, data.allocation, data.rebalance)
        # スイングTOP3(swing_picks)も改修後の並びで作り直す。
        data.swing_picks = _rebuild_swing_picks(candidate_decisions, decisions)
        # 改修後に残る指摘(理想は「改善不要」)を最終レビューとして持つ。
        data.review = rule_based_review(data)
    return data


def _rebuild_swing_picks(candidate_decisions: list, decisions: list) -> list[dict]:
    """自己改修でスコア/判断が変わった後、注目候補TOP3を作り直す。"""
    held_companies = {_company_key(d) for d in decisions}
    pool = [c for c in candidate_decisions if _company_key(c) not in held_companies]
    pool.sort(key=priority_value, reverse=True)
    picks = []
    for cand in pool[:SWING_TOP_N]:
        heading = f"{cand.symbol} {cand.name}" if cand.name else cand.symbol
        picks.append(
            {
                "heading": heading,
                "score": cand.overall_score,
                "current_price": cand.current_price,
                "reasons": _candidate_reasons(cand),
            }
        )
    return picks


def flex_messages_from(data: ReportData) -> list[dict]:
    """Render collected data into LINE Flex message objects."""
    bubbles: list[dict] = []
    if data.snapshot:
        bubbles.append(market_bubble(data.sentiment, data.snapshot, data.as_of))
    bubbles.extend(holding_bubble(summary) for summary in data.summaries)
    if data.swing_picks:
        bubbles.append(swing_bubble(data.swing_picks))

    if not bubbles:
        raise RuntimeError("分析データを取得できませんでした（全銘柄・市場データの取得に失敗）")

    messages = to_flex_messages(bubbles, alt_text="株ポートフォリオ分析")
    if data.failed_symbols:
        messages.append(
            {"type": "text", "text": "⚠️ 取得できなかった銘柄: " + ", ".join(data.failed_symbols)}
        )
    return messages


def discord_embeds_from(data: ReportData) -> list[dict]:
    """Render collected data into Discord embed objects (意思決定UI)."""
    embeds: list[dict] = []
    # 最優先: 本日の結論(今日買う/売る/現金比率/「何もしない」)。
    if data.conclusion is not None:
        embeds.append(conclusion_embed(data.conclusion))
    if data.snapshot:
        embeds.append(market_embed(data.sentiment, data.snapshot, data.as_of, data.stance))
    # ポート全体の判断(買い優先順位・資金配分・リバランス)。銘柄カードはその後に続く。
    if data.allocation is not None and (data.decisions or data.allocation.weights):
        embeds.append(manager_embed(data.allocation, data.rebalance))
    embeds.extend(holding_embed(decision) for decision in data.decisions)
    if data.swing_picks:
        embeds.append(swing_embed(data.swing_picks))
    # 自己改修AIが直した内容(あれば)→ 反映後のレビュー(理想は「改善不要」)。
    if data.revisions:
        embeds.append(revision_embed(data.revisions))
    embeds.append(review_embed(data.review))
    if data.failed_symbols:
        embeds.append(failed_embed(data.failed_symbols))

    if not embeds:
        raise RuntimeError("分析データを取得できませんでした（全銘柄・市場データの取得に失敗）")
    # 最適化AI: 情報量を維持したまま各カードの説明文を圧縮(トークン/文字数削減)。
    return optimize_embeds(embeds)


def generate_flex_messages(holdings: list[Holding], include_swing_pick: bool = True) -> list[dict]:
    """Convenience: collect data and render LINE Flex messages in one call."""
    return flex_messages_from(collect_report_data(holdings, include_swing_pick))


def generate_discord_embeds(holdings: list[Holding], include_swing_pick: bool = True) -> list[dict]:
    """Convenience: collect data and render Discord embeds in one call."""
    return discord_embeds_from(collect_report_data(holdings, include_swing_pick))


def main() -> None:
    parser = argparse.ArgumentParser(description="保有銘柄の分析レポートを表示します")
    parser.add_argument("--portfolio", default="portfolio.sample.csv", help="保有銘柄CSVのパス")
    parser.add_argument(
        "--summary", action="store_true", help="LINE通知用の要約レポートを表示する(既定は詳細レポート)"
    )
    args = parser.parse_args()

    # Windows の既定コンソール(cp932)は絵文字/罫線でクラッシュするため UTF-8 に寄せる。
    # 通知経路(Discord/LINE は HTTP/JSON=UTF-8)には無関係で、ローカル表示だけの保険。
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

    holdings = load_portfolio(args.portfolio)
    report = generate_summary(holdings) if args.summary else generate_report(holdings)
    for line in report:
        print(line)


if __name__ == "__main__":
    main()
