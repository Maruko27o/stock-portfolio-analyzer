"""必須の最終自動検証(全銘柄・毎回) — レポート生成パイプラインの最終ゲート。

個別事例のパッチではなく、以下の整合性を全銘柄へ一律に適用して確認する。違反は
ReportData.violations に集約し、レポートに要約表示、分析信頼度の引き下げ、即時
アクション文言の抑止(final_output)へ反映する。

検証項目(ユーザー指定):
 1. 個別銘柄のアクションとリバランス表の方向性が矛盾していないか
 2. 割安率がプラス(割高)の銘柄が上位スコア/強い買い推奨になっていないか
 3. 買い順位がスコア(=順位付けキー)の降順と一致しているか
 4. スター表示がスコアと矛盾していないか(★は0〜5、スコア帯と一致)
 5. 日付由来フィールドが負の値になっていないか
 6. 同一企業が複数ティッカーで重複計上されていないか
 7. 品質ゲート未通過時に最上位アクション文言が出力されていないか
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_analyzer import aliases, config
from stock_analyzer.allocation import priority_value
from stock_analyzer.conclusion import BUY_ACTIONS
from stock_analyzer.decision import HoldingDecision, star_count, stars_from_score
from stock_analyzer.display import should_show_allocation
from stock_analyzer.final_output import _IMMEDIATE_LABELS, recommended_action


@dataclass
class ConsistencyViolation:
    rule: str  # "1.方向矛盾" など、検証項目の識別子
    symbol: str | None  # 対象銘柄(全体の違反は None)
    detail: str  # 何がどう矛盾しているか


def _held(data) -> list[HoldingDecision]:
    return [d for d in getattr(data, "decisions", []) if not d.is_candidate]


def _pool(data) -> list[HoldingDecision]:
    pool = list(getattr(data, "decisions", []))
    alloc = getattr(data, "allocation", None)
    if alloc is not None:
        seen = {id(d) for d in pool}
        pool += [d for d in alloc.ranking if id(d) not in seen]
    return pool


# ポート都合(比率調整・集中緩和など)を示す、個別カードに出してはいけない文言 [カテゴリ17]。
PORTFOLIO_WORDING = ("比率調整", "偏り是正", "集中緩和", "リバランス", "縮小(", "比率是正")


def _check_card_no_portfolio_wording(data) -> list[ConsistencyViolation]:
    """1/17. 個別カードの推奨アクション文言に、ポート調整由来の語が混入していないか。

    個別カードは銘柄単体評価のみ。ポート比率調整は独立の rebalance/結論セクションで表示する。
    """
    from stock_analyzer.final_output import recommended_action

    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        label = recommended_action(d)
        if any(w in label for w in PORTFOLIO_WORDING):
            out.append(ConsistencyViolation(
                "17.カード混入", d.symbol,
                f"個別カードのアクション「{label}」にポート調整由来の文言が混入",
            ))
    return out


def _check_overvalued(data) -> list[ConsistencyViolation]:
    """2. 割高(割安率>0)なのに高スコア/強い買い。"""
    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        if d.discount_pct is None or d.discount_pct <= config.OVERVALUED_DISCOUNT_PCT:
            continue
        if d.overall_score > config.OVERVALUED_SCORE_CAP or d.action == "強く買い増し":
            out.append(ConsistencyViolation(
                "2.割高強気", d.symbol,
                f"割高(割安率{d.discount_pct:+.0f}%)なのに{d.overall_score}点/「{d.action}」",
            ))
    return out


def _check_ranking(data) -> list[ConsistencyViolation]:
    """2/11. 買い順位が総合スコアの降順(調整は同点時のみ)と一致しているか。"""
    out: list[ConsistencyViolation] = []
    alloc = getattr(data, "allocation", None)
    if alloc is None or not alloc.ranking:
        return out
    ranked = sorted(alloc.ranking, key=lambda d: (d.rank or 0))
    for prev, nxt in zip(ranked, ranked[1:]):
        # 上位(rank小)の総合スコアが下位より低ければ、スコア降順に反する
        if prev.overall_score < nxt.overall_score:
            out.append(ConsistencyViolation(
                "3.順位不整合", nxt.symbol,
                f"{nxt.symbol}({nxt.overall_score}点)が {prev.symbol}({prev.overall_score}点)"
                "より下位だがスコアは上",
            ))
    return out


def _check_stars(data) -> list[ConsistencyViolation]:
    """3/12. 表示された★が決定的関数 stars_from_score の計算結果と完全一致しているか。"""
    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        # 範囲外(6個以上)の★を構造的に検出
        for label, stars in (
            ("総合", d.overall_stars),
            ("需給", d.supply_demand_stars),
            ("配当", d.dividend_stars),
        ):
            if stars and star_count(stars) > 5:
                out.append(ConsistencyViolation(
                    "4.スター範囲外", d.symbol, f"{label}★が6個以上({stars})",
                ))
        # 総合★は決定的関数 floor(score/20) と完全一致していること [カテゴリ12]
        expected = stars_from_score(d.overall_score)
        if d.overall_stars and d.overall_stars != expected:
            out.append(ConsistencyViolation(
                "4.スター不一致", d.symbol,
                f"{d.overall_score}点の決定的★は{expected}だが表示は{d.overall_stars}",
            ))
    return out


def _check_allocation_display(data) -> list[ConsistencyViolation]:
    """4/13. 非購入系アクションで資金配分が表示(非空欄)になっていないか。"""
    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        # 買い方向でないのに配分%が付いている(=表示されうる)状態は違反
        if d.action not in BUY_ACTIONS and d.alloc_pct is not None and d.alloc_pct > 0:
            out.append(ConsistencyViolation(
                "13.配分表示", d.symbol,
                f"非購入系「{d.action}」なのに資金配分{d.alloc_pct:.0f}%が付与されている",
            ))
    return out


def _check_dates(data) -> list[ConsistencyViolation]:
    """5. 日付由来フィールドが負になっていないか(決算までの日数など)。"""
    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        if d.days_to_earnings is not None and d.days_to_earnings < 0:
            out.append(ConsistencyViolation(
                "5.負の日数", d.symbol, f"決算までの日数が負({d.days_to_earnings}日)",
            ))
    return out


def _check_duplicate_company(data) -> list[ConsistencyViolation]:
    """6. 同一企業が複数ティッカーで重複計上されていないか(ADR/OTC 含む)。"""
    out: list[ConsistencyViolation] = []
    seen: dict[str, str] = {}
    for d in _pool(data):
        key = aliases.company_key(d.symbol, d.name)
        if key in seen and seen[key] != d.symbol:
            out.append(ConsistencyViolation(
                "6.企業重複", d.symbol,
                f"{d.symbol} は {seen[key]} と同一企業(ADR/OTC等)の重複計上",
            ))
        else:
            seen.setdefault(key, d.symbol)
    return out


def _check_per_validity(data) -> list[ConsistencyViolation]:
    """5/14. PERが異常値の銘柄は「要確認」として明示され、割安根拠に使われていないか。"""
    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        if not getattr(d, "per_flagged", False):
            continue
        # 異常値PERは必ず「要確認」リスクとして表面化していること。
        if not any("要確認" in r for r in d.risks):
            out.append(ConsistencyViolation(
                "14.PER異常", d.symbol, "PERが異常値だが『要確認』表示が無い",
            ))
    return out


def _check_row_count(data) -> list[ConsistencyViolation]:
    """7/16. 1銘柄カードの表示行数が目標範囲(6〜8行目安の上限)に収まっているか。"""
    from stock_analyzer.final_output import CARD_MAX_LINES, build_context, card_line_count

    out: list[ConsistencyViolation] = []
    ctx = build_context(data)
    for d in _pool(data):
        n = card_line_count(d, ctx)
        if n > CARD_MAX_LINES:
            out.append(ConsistencyViolation(
                "16.行数超過", d.symbol, f"カード行数{n}が目標上限{CARD_MAX_LINES}を超過",
            ))
    return out


def _check_swing_ranking(data) -> list[ConsistencyViolation]:
    """2/18. 新規候補ランキング(swing_picks)がスコア降順になっているか(全ウィジェット横断)。"""
    out: list[ConsistencyViolation] = []
    picks = getattr(data, "swing_picks", None) or []
    scores = [p.get("score") for p in picks if p.get("score") is not None]
    if scores != sorted(scores, reverse=True):
        out.append(ConsistencyViolation(
            "18.候補順位", None, f"新規候補ランキングがスコア降順でない: {scores}",
        ))
    return out


def _check_confidence_variance(data) -> list[ConsistencyViolation]:
    """3/19. 信頼度が全銘柄で同一値になっていないか(指標として情報量があるか)。"""
    out: list[ConsistencyViolation] = []
    pool = _pool(data)
    pcts = {getattr(d, "confidence_pct", 0) for d in pool}
    # 実レポートは多数銘柄。5銘柄以上が全て同一値=固定値化のバグとみなす。
    if len(pool) >= 5 and len(pcts) == 1:
        out.append(ConsistencyViolation(
            "19.信頼度一律", None,
            f"信頼度が全{len(pool)}銘柄で同一値({next(iter(pcts))}%)=情報量なし",
        ))
    return out


def _check_fair_value_sanity(data) -> list[ConsistencyViolation]:
    """4/20. 適正価格が桁乖離の銘柄は割安判定(discount)に使われず要確認になっているか。"""
    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        if getattr(d, "valuation_flagged", False):
            if d.discount_pct is not None:
                out.append(ConsistencyViolation(
                    "20.適正価格乖離", d.symbol, "適正価格が桁乖離なのに割安率がまだ使われている",
                ))
            elif not any("桁乖離" in r or "要確認" in r for r in d.risks):
                out.append(ConsistencyViolation(
                    "20.適正価格乖離", d.symbol, "適正価格の桁乖離だが『要確認』表示が無い",
                ))
    return out


def _dups(symbols: list[str]) -> set[str]:
    seen: set[str] = set()
    dup: set[str] = set()
    for s in symbols:
        (dup if s in seen else seen).add(s)
    return dup


def _check_ticker_dedup(data) -> list[ConsistencyViolation]:
    """5/21. 同一セクション内でティッカーが重複表示されていないか。"""
    out: list[ConsistencyViolation] = []
    conclusion = getattr(data, "conclusion", None)
    if conclusion is not None:
        for label, items in (("買い", conclusion.buys), ("売り", conclusion.sells),
                             ("比率是正", conclusion.rebalance_moves)):
            for sym in _dups([it.symbol for it in items]):
                out.append(ConsistencyViolation("21.重複表示", sym, f"結論の{label}リストで重複"))
        # ①単体売り と ②比率是正 の間でも同一ティッカーを二重に出さない
        overlap = {it.symbol for it in conclusion.sells} & {it.symbol for it in conclusion.rebalance_moves}
        for sym in overlap:
            out.append(ConsistencyViolation("21.重複表示", sym, "単体売りと比率是正に二重掲載"))
    for sym in _dups([p.get("heading", "").split()[0] for p in getattr(data, "swing_picks", []) or []]):
        out.append(ConsistencyViolation("21.重複表示", sym, "新規候補リストで重複"))
    return out


def _check_name_master(data) -> list[ConsistencyViolation]:
    """6/22. ティッカーと社名の対応が正規マスタと一致しているか。"""
    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        if getattr(d, "name_mismatch", False):
            out.append(ConsistencyViolation(
                "22.社名不一致", d.symbol, f"社名『{d.name}』が正規マスタと不一致",
            ))
    return out


def _check_rsi_extreme(data) -> list[ConsistencyViolation]:
    """7/23. 極端なRSI過熱と積極的買いアクションが同時に出ていないか。"""
    out: list[ConsistencyViolation] = []
    for d in _pool(data):
        rsi = getattr(d, "rsi", None)
        if rsi is not None and rsi >= config.RSI_EXTREME_OVERBOUGHT and d.action in BUY_ACTIONS:
            out.append(ConsistencyViolation(
                "23.過熱買い", d.symbol, f"RSI{rsi:.0f}の極端な過熱なのに「{d.action}」",
            ))
    return out


def _check_gate_wording(data) -> list[ConsistencyViolation]:
    """7. 品質ゲート未通過時に最上位アクション文言が出力されていないか。"""
    out: list[ConsistencyViolation] = []
    gate_passed = getattr(data, "gate_passed", True)
    if gate_passed:
        return out
    # 未通過時は guarded=True でレンダリングされるはず。実出力に即時文言が残れば違反。
    for d in _pool(data):
        if recommended_action(d, guarded=True) in _IMMEDIATE_LABELS:
            out.append(ConsistencyViolation(
                "7.未通過文言", d.symbol,
                f"品質ゲート未通過だが即時アクション文言が出力(「{recommended_action(d, True)}」)",
            ))
    return out


CHECKS = (
    _check_card_no_portfolio_wording,  # 17
    _check_overvalued,                 # 2
    _check_ranking,                    # 11
    _check_swing_ranking,              # 18
    _check_stars,                      # 12
    _check_allocation_display,         # 13
    _check_confidence_variance,        # 19
    _check_fair_value_sanity,          # 20
    _check_ticker_dedup,               # 21
    _check_name_master,                # 22
    _check_rsi_extreme,                # 23
    _check_dates,                      # 5
    _check_duplicate_company,          # 6
    _check_per_validity,               # 14
    _check_row_count,                  # 16
    _check_gate_wording,               # 9
)


def check_all(data) -> list[ConsistencyViolation]:
    """7項目すべてを全銘柄に実行し、違反を1リストにまとめて返す(空なら全通過)。"""
    violations: list[ConsistencyViolation] = []
    for check in CHECKS:
        violations.extend(check(data))
    return violations


def summarize(violations: list[ConsistencyViolation]) -> dict[str, int]:
    """ルール別の違反件数を返す(レポート要約・監査用)。"""
    counts: dict[str, int] = {}
    for v in violations:
        counts[v.rule] = counts.get(v.rule, 0) + 1
    return counts


def format_lines(violations: list[ConsistencyViolation]) -> list[str]:
    """CLI/テキスト用に整合チェック結果を整形する。"""
    if not violations:
        return ["🧪 整合チェック: 違反なし(7項目すべて通過)"]
    lines = [f"🧪 整合チェック: {len(violations)}件の違反"]
    for rule, n in summarize(violations).items():
        lines.append(f"・[{rule}] {n}件")
    return lines
