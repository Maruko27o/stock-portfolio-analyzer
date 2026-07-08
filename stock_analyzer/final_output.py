"""⑥ 最終出力(表示専用): 分析内容・点数・順位・数値・判断を一切変更しない。

品質ゲートを通過した分析を、スマホ1画面で読み切れるコンパクトな1銘柄カードへ整形する
[カテゴリ16]。分析の内部ロジック・計算過程は一切削らず、表示テンプレートのみ重複を統合する。

削るのは「重複表示」だけ(結論/一言要約/推奨アクション/保有株コメントは1行へ、最重要
判断要因と根拠は1つの箇条書きへ)。スコア・適正価格・割安率・期待リターン・判断理由・
リスク・信頼度という分析上重要な要素は一切削除しない。目安は1銘柄6〜8行。
"""

from __future__ import annotations

from stock_analyzer.decision import SELL_ACTIONS, HoldingDecision, stars_from_score
from stock_analyzer.display import format_yen, should_show_allocation

# 6段階の内部アクション → 個別銘柄カード専用の推奨アクション語彙 [カテゴリ17]。
# 銘柄単体の技術・ファンダ評価のみに基づく語彙。ポート都合(比率調整・集中緩和)の
# 文言は一切含めない(=個別カードにポート由来の指示を混入させない)。
_ACTION_LABEL = {
    "強く買い増し": "今すぐ買う",
    "買い増し": "分割買い",
    "保有": "様子見",
    "様子見": "押し目待ち",
    "一部売却": "一部売却",
    "売却推奨": "損切り",
}

# 品質チェック未通過時に封じる即時アクション文言と、その代替(1段慎重側)。
_IMMEDIATE_LABELS = {"今すぐ買う"}
_GUARDED_LABEL = {"今すぐ買う": "分割買い・品質確認待ち"}


def _long_term(d: HoldingDecision):
    return next((h for h in d.expected_returns if h.label == "半年〜1年"), None)


def _horizon(d: HoldingDecision, label: str):
    return next((h for h in d.expected_returns if h.label == label), None)


def recommended_action(d: HoldingDecision, guarded: bool = False) -> str:
    """推奨アクション(サイズ調整・利益確定・決算待ち・品質ガードを反映)。

    guarded=True(品質ゲート未通過/整合違反あり)のときは「今すぐ買う」等の即時文言を
    封じ、1段慎重な表現へ差し替える [カテゴリ9b]。
    """
    label = _ACTION_LABEL.get(d.action, d.action)
    # 個別カードは銘柄単体評価のみ。利確/損切りは単体の売り理由(ポート比率調整ではない)。
    if not d.is_candidate and d.action == "一部売却" and (d.profit_pct or 0) > 0:
        label = "利益確定"
    if d.is_candidate and d.action == "保有":
        label = "押し目待ち"
    if guarded and label in _IMMEDIATE_LABELS:
        label = _GUARDED_LABEL.get(label, label)
    if d.earnings_alert:
        label += "・決算待ち"
    return label


def _pct(v, spec="{:+.1f}%"):
    return spec.format(v) if v is not None else "—"


def _price(v):
    # 金額表示は共通フォーマッタ(円・整数・カンマ) [カテゴリ15]。
    return format_yen(v)


def build_context(data) -> dict:
    """全体で共有する値(対平均アルファ基準・信頼度・品質ガード)を用意する。"""
    pool = list(getattr(data, "decisions", []))
    alloc = getattr(data, "allocation", None)
    if alloc is not None:
        seen = {id(x) for x in pool}
        pool += [x for x in alloc.ranking if id(x) not in seen]
    lts = [_long_term(d).pct for d in pool if _long_term(d) and _long_term(d).pct is not None]
    market_avg = sum(lts) / len(lts) if lts else None
    # 品質ゲート未通過 or 整合違反があれば、即時アクション文言を封じる [カテゴリ9b]。
    guarded = not getattr(data, "gate_passed", True) or bool(getattr(data, "violations", []))
    conf = getattr(data, "confidence", (0, "", []))
    return {"market_avg": market_avg, "guarded": guarded, "confidence_pct": conf[0]}


def _reasons_line(d: HoldingDecision) -> str:
    """最重要判断要因TOP3を1行に集約(根拠と重複させない) [カテゴリ16]。"""
    seen: list[str] = []
    for r in d.reasons:
        if r not in seen:
            seen.append(r)
        if len(seen) >= 3:
            break
    return "／".join(seen) if seen else recommended_action(d)


def _risks_line(d: HoldingDecision) -> str | None:
    """リスクを1行に集約(該当時のみ)。決算接近は先頭に。"""
    risks: list[str] = []
    if d.days_to_earnings is not None and d.earnings_alert:
        risks.append(f"決算まで{d.days_to_earnings}日")
    for r in d.risks:
        if r not in risks:
            risks.append(r)
    return "／".join(risks[:3]) if risks else None


def final_card_lines(d: HoldingDecision, ctx: dict) -> list[str]:
    """1銘柄をコンパクトカード(6〜8行目安)へ整形する。表示のみ・数値は変更しない。

    ・結論/一言要約/推奨アクション/保有株コメント → 見出し1行に統合
    ・最重要判断要因/根拠 → 判断理由1行に統合
    """
    guarded = bool(ctx.get("guarded"))
    w = _horizon(d, "1週間")
    m = _horizon(d, "1ヶ月")
    lt = _long_term(d)
    name = d.name or d.symbol
    tag = "🔍監視 " if d.is_candidate else ""
    # [カテゴリ19] 信頼度は銘柄ごと(全銘柄一律にしない)。内訳も簡潔に添える。
    pct = getattr(d, "confidence_pct", 0) or ctx.get("confidence_pct", 0)
    breakdown = "／".join(getattr(d, "confidence_reasons", []) or [])

    lines: list[str] = []
    # 見出し行(結論・推奨アクションを1行に)
    lines.append(f"{tag}{name}（{d.symbol}）― {recommended_action(d, guarded)}")
    # スコア・順位・信頼度(★は決定的関数から) [カテゴリ12]
    rank = f"買い順位{d.rank}位" if d.rank else "買い順位—"
    conf = f"信頼度{pct}%" + (f"（{breakdown}）" if breakdown else "")
    lines.append(f"総合{d.overall_score}点 {stars_from_score(d.overall_score)} ／ {rank} ／ {conf}")
    # 適正価格・割安率・期間別期待リターン
    lines.append(
        f"適正価格{_price(d.fair_value)}（割安率{_pct(d.discount_pct)}）"
        f"／ 期待 短期{_pct(w.pct if w else None)} 中期{_pct(m.pct if m else None)} 長期{_pct(lt.pct if lt else None)}"
    )
    # 判断理由(TOP3を1行)
    lines.append(f"・判断理由：{_reasons_line(d)}")
    # リスク(あれば1行)
    risks = _risks_line(d)
    if risks:
        lines.append(f"・リスク：{risks}")
    # 資金配分(共通判定 should_show_allocation が真のときのみ) [カテゴリ13]
    if should_show_allocation(d.action, d.alloc_pct):
        lines.append(f"・資金配分：{d.alloc_pct:.0f}%")
    return lines


def final_embed(d: HoldingDecision, ctx: dict, confidence: tuple) -> dict:
    from stock_analyzer.discord import ACTION_COLOR, ACTION_EMOJI, _color_int

    guarded = bool(ctx.get("guarded"))
    heading = f"{d.name}（{d.symbol}）" if d.name else d.symbol
    tag = "🔍監視 " if d.is_candidate else ""
    # 見出しは title に集約し、本文は見出し行を除いたコンパクト行にする。
    body = final_card_lines(d, ctx)[1:]
    return {
        "title": f"{ACTION_EMOJI.get(d.action, '⚪')} {tag}{heading} ― {recommended_action(d, guarded)}",
        "description": "\n".join(body),
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


# 1銘柄カードの目標行数(スマホ1画面で複数銘柄が読めること) [カテゴリ16c]。
CARD_MIN_LINES = 4
CARD_MAX_LINES = 8


def card_line_count(d: HoldingDecision, ctx: dict) -> int:
    """1銘柄カードの表示行数(見出し込み)。行数チェックに使う。"""
    return len(final_card_lines(d, ctx))
