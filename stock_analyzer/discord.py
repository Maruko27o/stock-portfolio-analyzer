from __future__ import annotations

import time

import requests

from stock_analyzer.allocation import SCORE_CAVEAT, AllocationPlan
from stock_analyzer.conclusion import DailyConclusion
from stock_analyzer.decision import HoldingDecision
from stock_analyzer.flex import SENTIMENT_COLOR
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.market import vix_regime_label
from stock_analyzer.rebalance import RebalancePlan
from stock_analyzer.summary import format_as_of

MAX_EMBEDS_PER_MESSAGE = 10

# 6段階アクション → 色付きマーカー(赤=強く買い増し〜黒=売却推奨)。
ACTION_EMOJI = {
    "強く買い増し": "🔴",
    "買い増し": "🟠",
    "保有": "🟡",
    "様子見": "⚪",
    "一部売却": "🔵",
    "売却推奨": "⚫",
}
ACTION_COLOR = {
    "強く買い増し": "#E74C3C",
    "買い増し": "#E67E22",
    "保有": "#F1C40F",
    "様子見": "#95A5A6",
    "一部売却": "#3498DB",
    "売却推奨": "#2C3E50",
}


def _color_int(hex_color: str) -> int:
    return int(hex_color.lstrip("#"), 16)


def _price(value: float | None) -> str:
    # 金額表示は共通フォーマッタに一本化(円・整数・カンマ) [カテゴリ15]。
    from stock_analyzer.display import format_yen

    return format_yen(value)


def _pct(value: float | None, spec: str = "{:+.1f}%") -> str:
    return spec.format(value) if value is not None else "—"


def _horizon_str(h: HorizonExpectation) -> str:
    """'1週 +2.8%(検証★★★★)' の形。データ不足なら '1週 —'。"""
    short_label = {"1週間": "1週", "1ヶ月": "1月", "半年〜1年": "半年〜1年"}.get(h.label, h.label)
    if h.pct is None:
        return f"{short_label} —"
    basis = "検証" if h.basis == "検証実績" else "推定"
    stars = h.stars or ""
    return f"{short_label} {h.pct:+.1f}%({basis}{stars})"


def market_embed(
    sentiment: str,
    snapshot: dict[str, tuple[float | None, float | None]],
    as_of=None,
    stance: str | None = None,
) -> dict:
    lines = []
    for name, (price, change) in snapshot.items():
        if name == "VIX":
            vix_text = f"{price:.1f}({vix_regime_label(price)})" if price is not None else "—"
            lines.append(f"{name}: {vix_text}")
            continue
        if name == "長期金利":
            # 米10年国債利回り。前日比%ではなく水準(利回り)で示す方が読みやすい。
            rate_text = f"{price:.2f}%" if price is not None else "—"
            lines.append(f"{name}(米10年): {rate_text}")
            continue
        change_text = f"{change:+.2f}%" if change is not None else "—"
        lines.append(f"{name}: {change_text}")
    as_of_note = format_as_of(as_of)
    if as_of_note:
        lines.append(as_of_note)
    headline = stance or sentiment  # 5段階(stance)があれば優先表示
    return {
        "title": f"📊 本日の市場：{headline}",
        "description": "\n".join(lines),
        "color": _color_int(SENTIMENT_COLOR.get(headline, SENTIMENT_COLOR.get(sentiment, "#7F8C8D"))),
    }


def conclusion_embed(conclusion: DailyConclusion) -> dict:
    """本日の結論(3行以内)+今日の売買候補。レポート先頭に置く行動サマリー。"""
    lines = list(conclusion.headline)
    if conclusion.buys:
        lines.append("")
        lines.append("**今日の買い候補**")
        for it in conclusion.buys:
            tag = "（新規）" if it.is_candidate else ""
            lines.append(f"🔴 {it.name or it.symbol}{tag} {it.action}（{it.reason}）")
    if conclusion.sells:
        lines.append("")
        lines.append("**今日の売り候補**")
        for it in conclusion.sells:
            lines.append(f"🔵 {it.name or it.symbol} {it.action}（{it.reason}）")
    if conclusion.rebalance_moves:
        lines.append("")
        lines.append("**比率の是正**")
        for it in conclusion.rebalance_moves:
            lines.append(f"▼ {it.name or it.symbol} {it.reason}")

    color = "#95A5A6" if conclusion.do_nothing else "#E74C3C"
    return {
        "title": "📌 本日の結論",
        "description": "\n".join(lines),
        "color": _color_int(color),
    }


def holding_embed(decision: HoldingDecision) -> dict:
    """1銘柄の意思決定カード(最小表示・10秒で判断)。

    詳細シグナル/レンジ多行は載せず、結論に必要な項目だけを出す。
    裏側の全指標は CLI の詳細レポートに残す。
    """
    heading = f"{decision.symbol} {decision.name}" if decision.name else decision.symbol
    # 監視銘柄(未保有)は「監視」を明示。保有カードと区別する。
    watch_tag = "🔍監視 " if decision.is_candidate else ""
    rank = f"（買い順位 {decision.rank}位）" if decision.rank else ""

    # 総合スコア + ★
    parts = [f"総合スコア：{decision.overall_score}点 {decision.overall_stars}{rank}"]

    # 期待リターン(3期間)
    if decision.expected_returns:
        parts.append("期待リターン  " + " / ".join(_horizon_str(h) for h in decision.expected_returns))

    # RR・割安率・資金配分
    line3 = [f"RR {decision.risk_reward:.1f}" if decision.risk_reward is not None else "RR —"]
    if decision.discount_pct is not None:
        fair = _price(decision.fair_value)
        line3.append(f"割安率 {decision.discount_pct:+.1f}%（現在{_price(decision.current_price)}→適正{fair}）")
    if decision.alloc_pct:
        line3.append(f"資金配分 {decision.alloc_pct:.0f}%")
    parts.append(" ／ ".join(line3))

    # 決算・需給・配当
    line4 = []
    if decision.days_to_earnings is not None:
        alert = "⚠️" if decision.earnings_alert else ""
        line4.append(f"決算まで {decision.days_to_earnings}日{alert}")
    if decision.supply_demand_stars:
        line4.append(f"需給 {decision.supply_demand_stars}")
    line4.append(f"配当 {decision.dividend_stars}" if decision.dividend_stars else "配当 —")
    parts.append(" ／ ".join(line4))

    # 保有損益(保有銘柄のみ)
    if decision.profit_pct is not None:
        parts.append(f"保有損益 {decision.profit_pct:+.1f}%")

    # 税の観点(保有銘柄のみ)
    if decision.tax_note:
        parts.append(f"🧾 {decision.tax_note}")

    if decision.comment:
        parts.append(f"💬 {decision.comment}")

    return {
        "title": f"{ACTION_EMOJI.get(decision.action, '⚪')} {watch_tag}{heading} — {decision.action}",
        "description": "\n".join(parts),
        "color": _color_int(ACTION_COLOR.get(decision.action, "#95A5A6")),
    }


def manager_embed(
    allocation: AllocationPlan, rebalance: RebalancePlan | None = None, top_n: int = 5
) -> dict:
    """ポート全体の「AIファンドマネージャー判断」。買い優先順位と次の投資資金の配分。"""
    lines: list[str] = []

    ranking = allocation.ranking[:top_n]
    if ranking:
        lines.append("**買い優先順位**")
        for d in ranking:
            tag = "（新規）" if d.is_candidate else ""
            lines.append(f"{d.rank}位 {d.symbol} {d.name or ''}{tag} {d.overall_stars} {d.action}")
        # [カテゴリ3] 順位の付け方(根拠)を明記する。
        lines.append("※順位=総合スコア降順＋期待リターン×確度の加点")

    if allocation.weights:
        lines.append("")
        lines.append("**次の投資資金の配分**")
        ranked_syms = [d for d in allocation.ranking if d.symbol in allocation.weights]
        alloc_bits = [
            f"{d.name or d.symbol} {allocation.weights[d.symbol]:.0f}%" for d in ranked_syms
        ]
        lines.append(" ／ ".join(alloc_bits))
        lines.append(f"現金 {allocation.cash_pct:.0f}%")

    from stock_analyzer.allocation import cash_range_note

    stats = [cash_range_note(allocation)]
    if allocation.expected_dividend_yield is not None:
        stats.append(f"想定配当利回り {allocation.expected_dividend_yield:.1f}%")
    if allocation.portfolio_expected_return is not None:
        stats.append(f"期待リターン(半年〜1年) {allocation.portfolio_expected_return:+.1f}%")
    if allocation.portfolio_risk is not None:
        stats.append(f"日次変動率 {allocation.portfolio_risk:.1f}%")
    lines.append("")
    lines.append(" ／ ".join(stats))

    if allocation.sector_breakdown:
        sectors = sorted(allocation.sector_breakdown.items(), key=lambda kv: kv[1], reverse=True)
        lines.append("セクター: " + " / ".join(f"{s} {w:.0f}%" for s, w in sectors))
    lines.append(f"分散: {allocation.diversification_note}")

    # 保有比率の是正(現在比率→推奨比率)。
    if rebalance is not None and rebalance.items:
        lines.append("")
        lines.append("**リバランス(現在→推奨)**")
        for it in rebalance.items[:top_n]:
            arrow = {"買い増し": "▲", "売却": "▼", "維持": "＝"}.get(it.direction, "")
            shares = f"（約{it.approx_shares}株{it.direction}）" if it.approx_shares else ""
            lines.append(
                f"{arrow} {it.name or it.symbol}：{it.current_pct:.0f}%→{it.target_pct:.0f}%"
                f"（{it.diff_pct:+.0f}%）{shares}"
            )

    lines.append(SCORE_CAVEAT)

    return {
        "title": "🤖 AIファンドマネージャー判断",
        "description": "\n".join(lines),
        "color": _color_int("#5865F2"),
    }


def revision_embed(revisions: list) -> dict:
    """自己改修AI(レビュー反映済み)の変更点。無ければ表示しない側で判断。"""
    lines: list[str] = []
    for r in revisions[:12]:
        head = f"**[{r.category}]**" + (f" {r.symbol}" if r.symbol else "")
        lines.append(f"{head} {r.change}")
        lines.append(f"　理由: {r.reason}")
    extra = f"\n…ほか{len(revisions) - 12}件" if len(revisions) > 12 else ""
    return {
        "title": f"🔧 自己改修(レビュー反映済み)｜{len(revisions)}件修正",
        "description": "\n".join(lines) + extra,
        "color": _color_int("#9B59B6"),
    }


def review_embed(findings: list) -> dict:
    """レビューAI(自己点検)の改善点。指摘が無ければ「改善不要」。"""
    if not findings:
        return {
            "title": "🔍 レビュー(自己点検)",
            "description": "改善不要",
            "color": _color_int("#2ECC71"),
        }
    lines: list[str] = []
    for f in findings[:10]:  # 多すぎると読めないので上位のみ
        head = f"**[{f.category}]**" + (f" {f.symbol}" if f.symbol else "")
        lines.append(f"{head} {f.issue}")
        lines.append(f"　なぜ: {f.why}")
        lines.append(f"　直し方: {f.fix}")
    extra = f"\n…ほか{len(findings) - 10}件" if len(findings) > 10 else ""
    return {
        "title": f"🔍 レビュー(自己点検)｜改善点 {len(findings)}件",
        "description": "\n".join(lines) + extra,
        "color": _color_int("#E67E22"),
    }


def swing_embed(picks: list[dict]) -> dict:
    blocks = []
    for index, pick in enumerate(picks, start=1):
        reasons = "\n".join(f"・{r}" for r in pick["reasons"])
        blocks.append(
            f"**{index}. {pick['heading']}　{pick['score']}点**\n"
            f"現在: {_price(pick['current_price'])}\n{reasons}"
        )
    disclaimer = (
        "※保有していない銘柄です。多数の銘柄を絞り込み、保有株と同じ観点(割安×成長×期待リターン)で"
        "分析した上位候補ですが、値上がりを保証するものではありません。"
    )
    return {
        "title": "🔎 新規の買い候補（割安×成長）TOP3",
        "description": "\n\n".join(blocks) + "\n\n" + disclaimer,
        "color": _color_int("#16A085"),
    }


def failed_embed(symbols: list[str]) -> dict:
    return {
        "title": "⚠️ 取得できなかった銘柄",
        "description": ", ".join(symbols),
        "color": _color_int("#B7950B"),
    }


def send_discord(webhook_url: str, embeds: list[dict]) -> None:
    """Post embeds to a Discord webhook, max 10 per message, honoring rate limits."""
    for start in range(0, len(embeds), MAX_EMBEDS_PER_MESSAGE):
        batch = embeds[start : start + MAX_EMBEDS_PER_MESSAGE]
        for attempt in range(2):
            response = requests.post(webhook_url, json={"embeds": batch}, timeout=10)
            if response.status_code == 429 and attempt == 0:
                retry_after = response.json().get("retry_after", 1)
                time.sleep(float(retry_after))
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"Discord webhook error {response.status_code}: {response.text}")
            break
