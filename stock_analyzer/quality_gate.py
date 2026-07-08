"""⑤ 品質ゲートAI: 分析結果の最終品質保証(検査のみ・書き換えは行わない)。

役割は「最終品質保証」だけ。分析はしないし、内容も書き換えない。問題を見つけたら
自己改修AI(③)へ差し戻し、修正後に再度ゲートを通す。最大3回まで。通過した分析のみ
最終出力AI(⑥)へ渡す。責務分離のため、修正は必ず self_improve 側に委ねる。

チェック項目(ユーザー指定):
数値の矛盾/スコアと判断の一致/強い買いなのに極端な割高/売却なのに期待が高すぎ/
保有コメントと判断の一致/根拠不足/説明と結論の一致/説明の繰り返し/重要情報が上から/
RRと期待の矛盾/リスクと買い判断の整合/期待が現実的か/不自然な100点/データ欠損。
"""

from __future__ import annotations

from stock_analyzer import config
from stock_analyzer.conclusion import BUY_ACTIONS
from stock_analyzer.decision import SELL_ACTIONS, HoldingDecision
from stock_analyzer.review import rule_based_review

MAX_GATE_PASSES = 3
# 「極端な割高」「期待が高すぎ」の閾値。
EXTREME_OVERVALUED = 12.0
UNREALISTIC_RETURN = 40.0
# [カテゴリ9] 品質ゲート未通過/整合違反があるとき、分析信頼度をこの上限まで引き下げる。
GATE_FAIL_CONFIDENCE_CAP = 60


def _long_term(d: HoldingDecision):
    return next((h for h in d.expected_returns if h.label == "半年〜1年"), None)


def _pool(data) -> list[HoldingDecision]:
    pool = list(getattr(data, "decisions", []))
    alloc = getattr(data, "allocation", None)
    if alloc is not None:
        seen = {id(d) for d in pool}
        for d in alloc.ranking:
            if id(d) not in seen:
                pool.append(d)
    return pool


def gate_check(data) -> list[str]:
    """品質上の問題を文字列で列挙する(空なら合格)。内容は一切書き換えない。"""
    issues: list[str] = []

    # 論理・整合系はレビューAIの検査を借用(検出のみ)。
    for f in rule_based_review(data):
        issues.append(f"{f.symbol or '全体'}: {f.issue}")

    for d in _pool(data):
        tag = d.symbol
        lt = _long_term(d)
        # データ欠損
        if d.current_price is None:
            issues.append(f"{tag}: 現在値が欠損")
        if not d.expected_returns:
            issues.append(f"{tag}: 期待リターンが欠損")
        # 強い買いなのに極端な割高
        if d.action == "強く買い増し" and d.discount_pct is not None and d.discount_pct >= EXTREME_OVERVALUED:
            issues.append(f"{tag}: 強い買いだが極端に割高({d.discount_pct:+.0f}%)")
        # [カテゴリ2] 割高(割安率>0)のハード制約: スコア上限超 or 強い買い
        if d.discount_pct is not None and d.discount_pct > config.OVERVALUED_DISCOUNT_PCT and (
            d.overall_score > config.OVERVALUED_SCORE_CAP or d.action == "強く買い増し"
        ):
            issues.append(
                f"{tag}: 割高だが{d.overall_score}点/「{d.action}」(上限{config.OVERVALUED_SCORE_CAP}点)"
            )
        # 売却なのに期待リターンが高すぎ(サイズ調整=sizing_trim は「質は高いが比率過大」で対象外)
        if (
            d.action in SELL_ACTIONS and lt is not None and lt.pct is not None
            and lt.pct >= 15 and not getattr(d, "sizing_trim", False)
        ):
            issues.append(f"{tag}: 売却判断だが期待リターンが高い({lt.pct:+.0f}%)")
        # 期待が非現実的
        if lt is not None and lt.pct is not None and lt.pct > UNREALISTIC_RETURN:
            issues.append(f"{tag}: 期待リターンが非現実的({lt.pct:+.0f}%)")
        # 保有コメントと最終判断の一致(買い方向コメントで売り判断など)
        if d.comment:
            buy_words = ("買い", "追加", "最優先")
            if d.action in SELL_ACTIONS and any(w in d.comment for w in buy_words):
                issues.append(f"{tag}: 保有コメントと判断が不一致")
        # 根拠不足(買い判断だが理由も数値根拠も無い)
        if d.action in BUY_ACTIONS and not d.reasons and d.discount_pct is None and not d.dividend_yield:
            issues.append(f"{tag}: 買い判断の根拠不足")
        # 説明の繰り返し(同一理由の重複)
        if d.reasons and len(d.reasons) != len(set(d.reasons)):
            issues.append(f"{tag}: 説明の繰り返しあり")

    # 重要情報が上から並んでいるか(スコア降順で並んでいるか)
    decisions = list(getattr(data, "decisions", []))
    scores = [d.overall_score for d in decisions]
    if scores != sorted(scores, reverse=True):
        issues.append("全体: 銘柄がスコア降順に並んでいない(重要情報が上に来ていない)")

    return issues


def run_gate(data, on_fix) -> tuple[bool, int, list[str]]:
    """ゲートを通す。問題があれば on_fix()(=③自己改修へ差し戻し)を呼び、最大3回まで再検査。

    on_fix は「自己改修＋配分/結論の再計算」を行うコールバック(quality_gate は書き換えない)。
    戻り値: (通過したか, 実施した差し戻し回数, 残った問題)。
    """
    issues = gate_check(data)
    passes = 0
    while issues and passes < MAX_GATE_PASSES:
        on_fix()  # 差し戻し(自己改修AIが修正)
        passes += 1
        issues = gate_check(data)
    return (not issues), passes, issues


def _fill_rate(d: HoldingDecision) -> float:
    """データ充足率(欠損項目の割合の裏返し)。"""
    fields = [
        d.current_price is not None,
        d.discount_pct is not None or bool(d.dividend_yield),
        _long_term(d) is not None and _long_term(d).pct is not None,
        bool(d.supply_demand_stars),
        d.risk_reward is not None or d.action not in BUY_ACTIONS,
    ]
    return sum(1 for x in fields if x) / len(fields)


def _coherence(d: HoldingDecision) -> float:
    """サブスコア間の整合度。各カテゴリ(テクニカル/ファンダ/需給/市場…)が同じ方向を
    向いているほど高い。全会一致=1.0、拮抗=0付近。データ無しは0.5(中立)。"""
    subs = [v for v in (getattr(d, "subscores", {}) or {}).values() if v]
    total = sum(abs(v) for v in subs)
    if total == 0:
        return 0.5
    net = sum(subs)
    sign = 1 if net >= 0 else -1
    agree = sum(abs(v) for v in subs if (1 if v > 0 else -1) == sign)
    return agree / total


# [カテゴリ19] 信頼度の算出要素と重み(合計1.0)。レポートにも内訳を出す。
CONFIDENCE_WEIGHTS = {
    "fill": 0.40,        # データ充足率
    "coherence": 0.25,   # サブスコア整合度
    "gate": 0.15,        # 品質ゲート通過(全体)
    "stable": 0.10,      # 直近スコアが急変していない
    "per_ok": 0.10,      # PER異常値でない
}


def decision_confidence(d: HoldingDecision, data) -> tuple[int, str, list[str]]:
    """銘柄ごとの分析信頼度(%)・★・内訳 [カテゴリ19]。全銘柄一律にならないよう、
    銘柄固有の要素(充足率・整合度・急変・PER異常)から算出する。"""
    gate_passed = bool(getattr(data, "gate_passed", False))
    jumped = any(getattr(a, "symbol", None) == d.symbol for a in getattr(data, "stability_alerts", []) or [])
    fill = _fill_rate(d)
    coh = _coherence(d)
    w = CONFIDENCE_WEIGHTS
    frac = (
        w["fill"] * fill
        + w["coherence"] * coh
        + w["gate"] * (1.0 if gate_passed else 0.0)
        + w["stable"] * (0.0 if jumped else 1.0)
        + w["per_ok"] * (0.0 if getattr(d, "per_flagged", False) else 1.0)
    )
    pct = round(100 * frac)
    reasons = [f"充足{fill*100:.0f}%", f"整合{coh*100:.0f}%",
               "ゲート✓" if gate_passed else "ゲート未通過"]
    if jumped:
        reasons.append("スコア急変")
    if getattr(d, "per_flagged", False):
        reasons.append("PER要確認")
    # [カテゴリ9] 品質ゲート未通過なら参考値として上限を掛ける(改善は維持)。
    # 整合違反(violations)は信頼度算出より後に確定するため、ここではゲート状況のみで判定する。
    if not gate_passed:
        pct = min(pct, GATE_FAIL_CONFIDENCE_CAP)
        reasons.append("参考値")
    pct = max(0, min(100, pct))
    filled = min(5, max(0, round(pct / 20)))
    stars = "★" * filled + "☆" * (5 - filled)
    return pct, stars, reasons


def confidence(data) -> tuple[int, str, list[str]]:
    """レポート全体(ヘッダー用)の分析信頼度。銘柄別信頼度の平均＋通過状況の要約。"""
    pool = _pool(data)
    if not pool:
        return 0, "☆☆☆☆☆", ["分析対象なし"]
    pcts = [decision_confidence(d, data)[0] for d in pool]
    avg = round(sum(pcts) / len(pcts))
    gate_passed = getattr(data, "gate_passed", False)
    reasons = [
        f"銘柄別信頼度の平均{avg}%(銘柄ごとに変動)",
        "品質ゲート通過" if gate_passed else "品質ゲート未通過",
    ]
    if not gate_passed or (getattr(data, "violations", []) or []):
        reasons.append("品質チェック未完了のため参考値")
    filled = min(5, max(1, round(avg / 20)))
    stars = "★" * filled + "☆" * (5 - filled)
    return avg, stars, reasons
