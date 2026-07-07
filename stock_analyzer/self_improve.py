"""自己改修AI: レビュー結果を分析に100%反映して「最終分析」を作る。

レビュー(review.py)が見つけた矛盾・過大評価・説明不足を、分析結果側で修正する。
ルール(ユーザー指定):
- 分析の方向性は維持し、矛盾のみ修正
- 点数の再計算・買い売り判定の再計算
- 理由を追加・根拠不足を補足・不要な文章は削除
- レビューで指摘されなかった箇所は変更しない

レビューの指摘と同じ条件を各銘柄で判定し、対応する補正を当てる(=指摘を確実に解消)。
無料・決定論的。ANTHROPIC_API_KEY があれば llm_revise でLLM版も使える(任意)。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from stock_analyzer.conclusion import BUY_ACTIONS
from stock_analyzer.decision import SCORE_BANDS, SELL_ACTIONS, HoldingDecision, _comment
from stock_analyzer.review import EXPECTED_RETURN_CAP, HIGH_SCORE, MAX_HIGH_SCORES

# 強い順のアクション列(SCORE_BANDS と一致)。
ACTION_ORDER = [action for _, _, action in SCORE_BANDS]


@dataclass
class Revision:
    symbol: str | None
    category: str
    change: str  # 何を→何に変えたか
    reason: str  # なぜ(レビュー反映)


def _long_term(d: HoldingDecision):
    for h in d.expected_returns:
        if h.label == "半年〜1年":
            return h
    return None


def _band_range(action: str) -> tuple[int, int, str]:
    """アクションに対応するスコア帯 (low, high, stars) を返す。"""
    for i, (threshold, stars, act) in enumerate(SCORE_BANDS):
        if act == action:
            high = 100 if i == 0 else SCORE_BANDS[i - 1][0] - 1
            return threshold, high, stars
    return 0, 100, SCORE_BANDS[-1][1]


def _set_action(d: HoldingDecision, action: str, reason: str, category: str, revisions: list) -> None:
    """アクションを変更し、点数を新しい帯へ再計算、コメントを刷新、理由を追加する。"""
    if d.action == action:
        return
    low, high, stars = _band_range(action)
    before = f"{d.action}({d.overall_score}点)"
    d.action = action
    d.overall_stars = stars
    d.overall_score = max(low, min(high, d.overall_score))  # 点数の再計算(帯に整合)
    lt = _long_term(d)
    # 不要になった強気コメントを捨て、新アクションのコメントに刷新
    d.comment = _comment(action, d.discount_pct, d.earnings_alert, lt.pct if lt else None)
    if reason not in d.reasons:
        d.reasons = list(d.reasons) + [reason]
    revisions.append(Revision(d.symbol, category, f"{before}→{action}({d.overall_score}点)", reason))


def _downgrade_one(d: HoldingDecision, reason: str, category: str, revisions: list, floor: str = "様子見") -> None:
    """アクションを1段だけ弱める(floor より下げない)。"""
    idx = ACTION_ORDER.index(d.action) if d.action in ACTION_ORDER else 0
    floor_idx = ACTION_ORDER.index(floor)
    target = ACTION_ORDER[min(idx + 1, floor_idx)]
    _set_action(d, target, reason, category, revisions)


def _improve_decision(d: HoldingDecision, revisions: list) -> None:
    """1銘柄にレビュー指摘と同条件の補正を当てる。方向性は維持し矛盾のみ直す。"""
    lt = _long_term(d)

    # 7.スコア: 半年〜1年の期待リターンが高すぎ → アナリスト水準へ抑制(点数=期待の再計算)
    if lt is not None and lt.pct is not None and lt.pct > EXPECTED_RETURN_CAP:
        before = lt.pct
        lt.pct = EXPECTED_RETURN_CAP
        note = "期待リターンをアナリスト目標水準(上限)へ再計算"
        if note not in d.reasons:
            d.reasons = list(d.reasons) + [note]
        revisions.append(
            Revision(d.symbol, "7.スコア", f"半年〜1年 {before:+.0f}%→{lt.pct:+.0f}%", note)
        )

    # 1.ロジック矛盾: RR<1 なのに買い → 買いを見送り(様子見)
    if d.action in BUY_ACTIONS and d.risk_reward is not None and d.risk_reward < 1.0:
        _set_action(d, "様子見", "RRが1未満(下値>上値)のため買いを見送り", "1.ロジック矛盾", revisions)

    # 1.ロジック矛盾: 割高なのに買い → 1段弱める
    if d.discount_pct is not None and d.discount_pct >= 10 and d.action in BUY_ACTIONS:
        _downgrade_one(d, "割高圏のため買いの強さを一段弱める", "1.ロジック矛盾", revisions)

    # 1.ロジック矛盾: 半年〜1年の期待がマイナスなのに買い → 保有へ
    if lt is not None and lt.pct is not None and lt.pct < 0 and d.action in BUY_ACTIONS:
        _set_action(d, "保有", "半年〜1年の期待がマイナスのため据え置き", "1.ロジック矛盾", revisions)

    # 6.説明性: 「強く買い増し」だが長期の確度が低い → 買い増しへ一段
    if d.action == "強く買い増し" and lt is not None and (lt.stars is None or lt.stars.count("★") <= 1):
        _set_action(d, "買い増し", "長期の確度が低いため最上位判断を一段下げる", "6.説明性", revisions)

    # 6.説明性: 買いだが割安・配当の数値根拠が無い → 様子見(据え置き)
    if d.action in BUY_ACTIONS and d.discount_pct is None and not (d.dividend_yield or 0):
        _set_action(d, "様子見", "適正価格・配当の数値根拠が無いため据え置き", "6.説明性", revisions)

    # 5.ポートフォリオ: NISA(非課税)の売却提案(温存推奨) → 保有で温存
    if getattr(d, "account", None) == "NISA" and d.action in SELL_ACTIONS and d.tax_sell_bias < 0:
        _set_action(d, "保有", "NISA(非課税)は枠温存を優先し据え置き", "5.ポートフォリオ", revisions)

    # 1.ロジック矛盾: 高スコアなのに売り(税理由なし) → 保有へ整合
    if d.overall_score >= 85 and d.action in SELL_ACTIONS and not d.tax_note:
        _set_action(d, "保有", "高スコアと最終判断の整合", "1.ロジック矛盾", revisions)


def _normalize_high_scores(all_decisions: list, revisions: list) -> None:
    """総合95点以上が出すぎている場合、上位 MAX_HIGH_SCORES 以外を94へ抑える(相対序列は維持)。"""
    high = sorted(
        [d for d in all_decisions if d.overall_score >= HIGH_SCORE],
        key=lambda d: d.overall_score,
        reverse=True,
    )
    for d in high[MAX_HIGH_SCORES:]:
        before = d.overall_score
        d.overall_score = HIGH_SCORE - 1  # 94(アクションの帯[85-100]は不変)
        revisions.append(
            Revision(d.symbol, "7.スコア", f"{before}→{d.overall_score}点", "高スコア多発の抑制(判別力確保・序列は維持)")
        )


def improve(decisions: list, candidates: list | None = None) -> list[Revision]:
    """保有/監視/候補の判断にレビュー反映の補正を当て、変更ログを返す(その場で書き換え)。"""
    candidates = candidates or []
    revisions: list[Revision] = []
    seen = set()
    ordered = []
    for d in list(decisions) + list(candidates):
        if id(d) not in seen:
            seen.add(id(d))
            ordered.append(d)
    for d in ordered:
        _improve_decision(d, revisions)
    _normalize_high_scores(ordered, revisions)
    return revisions


def format_revision_lines(revisions: list[Revision]) -> list[str]:
    """CLI/テキスト用に自己改修の変更点を整形する。"""
    if not revisions:
        return ["🔧 自己改修", "レビュー指摘なし(修正不要)"]
    lines = ["🔧 自己改修(レビュー反映済み)"]
    for r in revisions:
        head = f"[{r.category}]" + (f" {r.symbol}" if r.symbol else "")
        lines.append(f"・{head} {r.change}（{r.reason}）")
    return lines


# ---------------------------------------------------------------------------
# LLM 版(任意): ANTHROPIC_API_KEY があれば、レビューを反映した最終分析をClaudeに作らせる。
# ---------------------------------------------------------------------------
IMPROVE_SYSTEM_PROMPT = """あなたは分析システム改善AIです。
レビュー結果を読み、分析内容を修正してください。
ルール: ・分析の方向性は維持 ・矛盾のみ修正 ・点数の再計算 ・買い売り判定の再計算 ・理由を追加 ・根拠不足を補足 ・必要なら評価項目を追加 ・不要な文章は削除
目的はレビュー内容を100%反映した分析結果を生成すること。レビューで指摘されなかった箇所は変更しない。出力は最終分析のみ。"""


def llm_revise(
    analysis_text: str, review_text: str, api_key: str | None = None, model: str = "claude-sonnet-5"
) -> str | None:
    """Claude にレビュー反映後の最終分析を作らせる。キーが無い/失敗時は None(無料運用を壊さない)。"""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import requests

    user = f"# レビュー結果\n{review_text}\n\n# 現在の分析結果\n{analysis_text}"
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2000,
                "system": IMPROVE_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=90,
        )
        if res.status_code >= 400:
            return None
        parts = res.json().get("content", [])
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return text.strip() or None
    except Exception:
        return None
