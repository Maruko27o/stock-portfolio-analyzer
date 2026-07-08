from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from datetime import date

from stock_analyzer.allocation import (
    AllocationPlan,
    format_allocation_lines,
    optimize_allocation,
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
from stock_analyzer.decision import HoldingDecision, build_decision
from stock_analyzer.horizon_model import expected_returns
from stock_analyzer.data_fetcher import (
    fetch_price_history,
    split_confirmed_history,
)
from stock_analyzer.discord import (
    conclusion_embed,
    failed_embed,
    manager_embed,
    market_embed,
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
from stock_analyzer.review import rule_based_review
from stock_analyzer import (
    aliases,
    consistency,
    ranking,
    self_improve,
    stability,
    quality_gate,
)
from stock_analyzer.final_output import (
    build_context,
    confidence_header_embed,
    final_card_lines,
    final_embed,
)
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
    # ⑥ 最終出力(表示専用): 分析信頼度ヘッダー + 9セクションの銘柄カード。
    pct, stars, reasons = data.confidence
    lines.append(f"✅ 分析信頼度 {pct}% {stars}")
    lines.extend(f"・{r}" for r in reasons)
    lines.append("")
    # 必須の最終自動検証(7項目)の結果を明示する。
    lines.extend(consistency.format_lines(data.violations))
    lines.append("")
    # 銘柄カードはコンパクト表示(見出しに信頼度を内包) [カテゴリ16]。
    ctx = build_context(data)
    for decision in data.decisions:
        lines.extend(final_card_lines(decision, ctx))
        lines.append("")
    # レビュー内容は表示しない(品質ゲートで内部保証済み)。
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
    review: list = field(default_factory=list)  # レビューAIの改善点(内部保持・非表示)
    revisions: list = field(default_factory=list)  # 自己改修AIが適用した修正のログ
    gate_passed: bool = False  # 品質ゲート通過フラグ
    gate_issues: list = field(default_factory=list)  # ゲートに残った問題(内部保持・非表示)
    confidence: tuple = (0, "☆☆☆☆☆", [])  # 分析信頼度(%,★,理由)
    concentration_caps: list = field(default_factory=list)  # [カテゴリ1]集中度で買い封じした記録
    stability_alerts: list = field(default_factory=list)  # [カテゴリ4]スコア急変の注意
    violations: list = field(default_factory=list)  # [必須検証]最終整合チェックの違反一覧

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
    """同一企業をまとめるキー。エイリアス表(別ティッカー紐付け)→銘柄名の順で正規化する。

    国内株(7203.T)と米ADR(TM)など、同じ会社が別コードで二重に並ぶのを防ぐ [カテゴリ6]。
    """
    return aliases.company_key(decision.symbol, decision.name)


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
        # [カテゴリ18] 候補ランキングも共通ソート(総合スコア降順)を必ず経由する。
        candidate_decisions = ranking.by_score(candidate_decisions)
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

    # 市場5段階スタンス(強気〜弱気)。[カテゴリ8] 現金比率レンジはこの表示スタンスに連動させる。
    stance = market_stance(snapshot, vix) if snapshot else None

    # 保有＋監視＋新規候補をまとめてポート最適化(買い優先順位・資金配分)。現金下限はスタンス由来。
    allocation = optimize_allocation(decisions + candidate_decisions, stance, vix)

    # 保有比率の是正(現在→推奨)と、本日の結論を組み立てる。
    # リバランスは保有(数量あり)のみが対象。監視・候補は is_candidate で自動的に外れる。
    quantities = {h.symbol: h.quantity for h in held}
    rebalance = build_rebalance(decisions, quantities)
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
    # ② レビューAI(論理・整合性チェック)。
    data.review = rule_based_review(data)
    # ③ 自己改修AI(レビュー反映): 矛盾のみ修正・点数/売買判定を再計算。
    data.revisions = self_improve.improve(decisions, candidate_decisions)

    def _recompute() -> None:
        # 判断/文章が変わったら配分・リバランス・結論・候補・レビューを取り直す。
        # [カテゴリ17] 個別カード(decisions)はここでリバランス由来の書き換えを一切しない。
        # ポート比率調整は rebalance / conclusion の専用セクションだけに出す(混入させない)。
        data.rebalance = build_rebalance(decisions, quantities)
        data.allocation = optimize_allocation(decisions + candidate_decisions, stance, vix)
        data.conclusion = build_conclusion(decisions, data.allocation, data.rebalance)
        data.swing_picks = _rebuild_swing_picks(candidate_decisions, decisions)
        data.review = rule_based_review(data)

    def _on_fix() -> None:
        # 品質ゲートからの差し戻し: 自己改修AI(③)が直し、再計算する(ゲートは書き換えない)。
        self_improve.improve(decisions, candidate_decisions)
        _recompute()

    _recompute()  # ③の初回改修を配分等へ反映
    # ⑤ 品質ゲートAI(最終品質保証): 問題があれば③へ差し戻し、最大3回。通過分のみ⑥へ。
    passed, _passes, issues = quality_gate.run_gate(data, _on_fix)
    data.gate_passed = passed
    data.gate_issues = issues
    # [カテゴリ4] スコア安定性の監査: 前回サブスコアと突き合わせ、ファンダ不変なのに
    # 総合が急変した銘柄へ「要目視確認」を付与し、監査ログへ今回値を追記する。
    _annotate_stability(data, as_of)
    # ⑤' 必須の最終自動検証(全銘柄): 7項目の整合を確認し、違反を保持する。
    # 違反があれば信頼度を引き下げ(下の confidence)、即時アクション文言を封じる(final_output)。
    # [カテゴリ19] 先に銘柄ごとの信頼度を算出して各カードに載せる(全銘柄一律を防ぐ)。
    # 整合チェック(信頼度ばらつき検証)より前に確定させる必要がある。
    for d in list(decisions) + list(candidate_decisions):
        d.confidence_pct, _stars, d.confidence_reasons = quality_gate.decision_confidence(d, data)
    data.violations = consistency.check_all(data)
    data.confidence = quality_gate.confidence(data)  # ヘッダー用(銘柄別の平均)
    return data


STABILITY_LOG_ENV_VAR = "SUBSCORE_LOG"


def _annotate_stability(data: "ReportData", as_of: date | None) -> None:
    """[カテゴリ4] 前回サブスコアと比較して急変を検知し、注意書き＋監査ログを付与する。

    環境変数 SUBSCORE_LOG が未設定なら何もしない(オフライン/テストを壊さない)。
    """
    import os

    path = os.environ.get(STABILITY_LOG_ENV_VAR)
    if not path:
        return
    entries = [
        stability.SubscoreRecord(d.symbol, d.overall_score, dict(d.subscores or {}))
        for d in data.decisions
    ]
    prev_map = stability.read_last_by_symbol(path)
    alerts = stability.check_entries(entries, prev_map)
    for d in data.decisions:
        note = alerts.get(d.symbol)
        if note and note not in d.risks:
            d.risks = list(d.risks) + [note]
    data.stability_alerts = [
        stability.StabilityAlert(sym, prev_map[sym].total, next(e.total for e in entries if e.symbol == sym), note)
        for sym, note in alerts.items()
    ]
    stability.append_records(path, entries, as_of)


def _rebuild_swing_picks(candidate_decisions: list, decisions: list) -> list[dict]:
    """自己改修でスコア/判断が変わった後、注目候補TOP3を作り直す。"""
    held_companies = {_company_key(d) for d in decisions}
    pool = [c for c in candidate_decisions if _company_key(c) not in held_companies]
    pool = ranking.by_score(pool)  # [カテゴリ18] 共通ソート(総合スコア降順)を経由
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
    # ⑥ 最終出力AI(表示専用): 9セクションの銘柄カード。数値・判断は変更しない。
    embeds.append(confidence_header_embed(data.confidence))
    # 必須の最終自動検証の結果(違反があれば警告として明示)。
    if data.violations:
        from stock_analyzer.discord import _color_int

        counts = consistency.summarize(data.violations)
        embeds.append(
            {
                "title": f"⚠️ 整合チェック: {len(data.violations)}件の違反(要確認)",
                "description": "\n".join(f"・[{r}] {n}件" for r, n in counts.items())
                + "\n※未解消の矛盾があるため、信頼度を引き下げ即時アクションは保留しています。",
                "color": _color_int("#E74C3C"),
            }
        )
    ctx = build_context(data)
    embeds.extend(final_embed(decision, ctx, data.confidence) for decision in data.decisions)
    if data.swing_picks:
        embeds.append(swing_embed(data.swing_picks))
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
