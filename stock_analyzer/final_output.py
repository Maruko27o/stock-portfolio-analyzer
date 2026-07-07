"""⑥ 最終出力AI: 表示専用。分析内容・点数・順位・数値・判断を一切変更しない。

品質ゲート(⑤)を通過した分析を、ユーザーが3〜10秒で「買う/様子見/売る」を判断できる
9セクションの決まった書式へ整形するだけ。数値の再計算や判断の変更は禁止(必要なら
品質ゲートへ差し戻す=呼び出し側の責務)。重要情報を上に、簡潔・箇条書き・1項目100字以内。
"""

from __future__ import annotations

from stock_analyzer.decision import SELL_ACTIONS, HoldingDecision

# 6段階の内部アクション → ユーザー指定の推奨アクション語彙。
_ACTION_LABEL = {
    "強く買い増し": "今すぐ買う",
    "買い増し": "分割買い",
    "保有": "様子見",
    "様子見": "押し目待ち",
    "一部売却": "一部売却",
    "売却推奨": "売却",
}


def _long_term(d: HoldingDecision):
    return next((h for h in d.expected_returns if h.label == "半年〜1年"), None)


def _horizon(d: HoldingDecision, label: str):
    return next((h for h in d.expected_returns if h.label == label), None)


def recommended_action(d: HoldingDecision) -> str:
    """推奨アクション(必要なら決算待ちを付す)。"""
    label = _ACTION_LABEL.get(d.action, d.action)
    if not d.is_candidate and d.action == "一部売却" and (d.profit_pct or 0) > 0:
        label = "利益確定"
    if d.is_candidate and d.action == "保有":
        label = "押し目待ち"
    if d.earnings_alert:
        label += "・決算待ち"
    return label


def _pct(v, spec="{:+.1f}%"):
    return spec.format(v) if v is not None else "—"


def _price(v):
    if v is None:
        return "—"
    return f"{v:,.0f}円" if abs(v) >= 1000 else f"{v:,.2f}"


def build_context(data) -> dict:
    """全体で共有する値(対平均アルファの基準・信頼度)を用意する。"""
    pool = list(getattr(data, "decisions", []))
    alloc = getattr(data, "allocation", None)
    if alloc is not None:
        seen = {id(x) for x in pool}
        pool += [x for x in alloc.ranking if id(x) not in seen]
    lts = [_long_term(d).pct for d in pool if _long_term(d) and _long_term(d).pct is not None]
    market_avg = sum(lts) / len(lts) if lts else None
    return {"market_avg": market_avg}


def final_card_lines(d: HoldingDecision, ctx: dict) -> list[str]:
    """1銘柄を9セクションへ整形(表示のみ・数値は変更しない)。"""
    held = not d.is_candidate
    w = _horizon(d, "1週間")
    m = _horizon(d, "1ヶ月")
    lt = _long_term(d)
    lines: list[str] = []

    # ① 結論
    name = d.name or d.symbol
    rank = f"買い順位{d.rank}位" if d.rank else "買い順位—"
    lines.append(f"① 結論")
    lines.append(f"・{d.symbol} {name}")
    lines.append(f"・総合評価 {d.overall_score}点 {d.overall_stars}")
    lines.append(f"・{rank} ／ 最終判断 {d.overall_stars}")
    lines.append(
        f"・期間 短期{_pct(w.pct if w else None)}／中期{_pct(m.pct if m else None)}／長期{_pct(lt.pct if lt else None)}"
    )

    # ② 一言要約(20〜40字目安)
    summary = d.comment or ("・".join(d.reasons[:2]) if d.reasons else recommended_action(d))
    lines.append("② 一言要約")
    lines.append(f"・{summary[:40]}")

    # ③ 推奨アクション
    lines.append("③ 推奨アクション")
    lines.append(f"・{recommended_action(d)}")

    # ④ 投資判断(重要度順)
    alpha = None
    if lt and lt.pct is not None and ctx.get("market_avg") is not None:
        alpha = lt.pct - ctx["market_avg"]
    lines.append("④ 投資判断")
    lines.append(f"・期待リターン(長期) {_pct(lt.pct if lt else None)}")
    lines.append(f"・適正価格 {_price(d.fair_value)} ／ 割安率 {_pct(d.discount_pct)}")
    rr = f"{d.risk_reward:.1f}" if d.risk_reward is not None else "—"
    lines.append(f"・RR {rr} ／ 期待α(対平均) {_pct(alpha)}")
    lines.append(f"・資金配分 {d.alloc_pct:.0f}%" if d.alloc_pct else "・資金配分 —")

    # ⑤ 最重要判断要因TOP3
    top = d.reasons[:3] if d.reasons else []
    if top:
        lines.append("⑤ 最重要判断要因TOP3")
        for i, r in enumerate(top, 1):
            lines.append(f"{i}. {r}")

    # ⑥ 根拠
    lines.append("⑥ 根拠")
    if d.reasons:
        lines.append("・買い理由 " + "／".join(d.reasons[:3]))
    if d.action in SELL_ACTIONS and d.risks:
        lines.append("・売り理由 " + "／".join(d.risks[:2]))
    if d.risks:
        lines.append("・注意点 " + "／".join(d.risks[:2]))

    # ⑦ リスク(最大3件)
    risks = list(d.risks)
    if d.days_to_earnings is not None and d.earnings_alert:
        risks = [f"決算まで{d.days_to_earnings}日", *risks]
    if risks:
        lines.append("⑦ リスク")
        for r in risks[:3]:
            lines.append(f"・{r}")

    # ⑧ 保有株コメント(保有中のみ)
    if held:
        hold_map = {
            "強く買い増し": "買い増し", "買い増し": "買い増し", "保有": "様子見",
            "様子見": "様子見", "一部売却": "利益確定", "売却推奨": "売却",
        }
        reason = (d.comment or (d.reasons[0] if d.reasons else ""))[:50]
        lines.append("⑧ 保有株コメント")
        lines.append(f"・{hold_map.get(d.action, d.action)}：{reason}")

    return lines


def final_embed(d: HoldingDecision, ctx: dict, confidence: tuple) -> dict:
    from stock_analyzer.discord import ACTION_COLOR, ACTION_EMOJI, _color_int

    pct, stars, _reasons = confidence
    heading = f"{d.symbol} {d.name}" if d.name else d.symbol
    tag = "🔍監視 " if d.is_candidate else ""
    lines = final_card_lines(d, ctx)
    # ⑨ 分析信頼度(数値+★)
    lines.append("⑨ 分析信頼度")
    lines.append(f"・{pct}% {stars}")
    return {
        "title": f"{ACTION_EMOJI.get(d.action, '⚪')} {tag}{heading} — {recommended_action(d)}",
        "description": "\n".join(lines),
        "color": _color_int(ACTION_COLOR.get(d.action, "#95A5A6")),
    }


def confidence_header_embed(confidence: tuple) -> dict:
    from stock_analyzer.discord import _color_int

    pct, stars, reasons = confidence
    return {
        "title": f"✅ 分析信頼度 {pct}% {stars}",
        "description": "\n".join(f"・{r}" for r in reasons),
        "color": _color_int("#27AE60"),
    }
