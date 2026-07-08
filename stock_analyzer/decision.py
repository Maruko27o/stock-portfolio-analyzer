"""銘柄ごとの「AIの最終判断」をまとめる決定層。

シグナル→スコア(summary)と期間別期待リターン(horizon_model)を受け取り、
画面表示に必要な結論だけを持つ HoldingDecision を組み立てる。
分析ロジック・スコアリングとは分離し、ここは「判断のまとめ」に徹する。

需給★は現状 yfinance で取れる範囲(出来高トレンド・出来高価格・モメンタム)の
プロキシで算出する。信用倍率・貸借倍率・空売り比率などの真の信用需給データは
未取得で、将来 fetcher を足したらここに加味する(捏造しない)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stock_analyzer import config, tax
from stock_analyzer.display import format_yen, should_show_allocation
from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.horizon_model import HorizonExpectation
from stock_analyzer.summary import HoldingSummary
from stock_analyzer.valuation import discount_pct, fair_value, per_is_plausible

# スコア帯 → (★評価, 6段階アクション)。境界は summary.rating_from_score と揃える。
SCORE_BANDS = [
    (85, "★★★★★", "強く買い増し"),
    (70, "★★★★☆", "買い増し"),
    (58, "★★★☆☆", "保有"),
    (43, "★★☆☆☆", "様子見"),
    (30, "★☆☆☆☆", "一部売却"),
    (0, "☆☆☆☆☆", "売却推奨"),
]

SELL_ACTIONS = {"一部売却", "売却推奨"}

# 決算がこの日数以内なら注意表示(暦日。yfinance の決算日は暦日ベース)。
EARNINGS_ALERT_DAYS = 5


@dataclass
class HoldingDecision:
    symbol: str
    name: str | None
    current_price: float | None
    overall_score: int  # 0-100(現在のシグナル整合度。勝率保証ではない)
    overall_stars: str  # ★評価
    action: str  # 6段階のいずれか
    fair_value: float | None
    discount_pct: float | None  # 負=割安
    risk_reward: float | None
    supply_demand_stars: str | None  # 需給★(プロキシ)
    dividend_stars: str | None  # 配当★
    dividend_yield: float | None
    days_to_earnings: int | None
    earnings_alert: bool
    expected_returns: list[HorizonExpectation]
    comment: str
    profit_pct: float | None = None
    volatility_pct: float | None = None  # ATR/現在価格(日次変動率%)。ポートのリスク算出に使う
    rank: int | None = None  # allocation 層で後埋め(買い優先順位)
    alloc_pct: float | None = None  # allocation 層で後埋め(資金配分%)
    is_candidate: bool = False  # True=新規候補(非保有)。買い優先順位/配分には含めるが保有カードには出さない
    sector: str | None = None
    account: str | None = None  # 口座区分("NISA"/"特定")。保有のみ
    unrealized_pl_yen: float | None = None  # 含み損益(円)。保有のみ
    tax_note: str | None = None  # 税の観点の一文(保有のみ)
    tax_sell_bias: int = 0  # 税から見た売却優先度補正: +1売りやすい/0中立/-1温存
    reasons: list[str] = field(default_factory=list)  # 裏付け(通知では原則非表示、CLI詳細用)
    risks: list[str] = field(default_factory=list)
    subscores: dict = field(default_factory=dict)  # [カテゴリ4]カテゴリ別サブスコア(安定性監査用)
    sizing_trim: bool = False  # [カテゴリ10]ポート最適化(リバランス)由来の縮小=サイズ調整の売り
    per_flagged: bool = False  # [カテゴリ14]PERが異常値=算出不可・要確認(割安判定から除外)


def _stars5(n_filled: int) -> str:
    n = max(0, min(5, n_filled))
    return "★" * n + "☆" * (5 - n)


def stars_from_score(score: float | None) -> str:
    """スコア(0-100)→★★★★★ を決定的に対応させる単純関数 [カテゴリ5]。

    star数 = min(5, floor(score/20)) を厳守し、範囲外(6個以上/負)を構造的に出さない。
    表示・検証はこの1関数に集約し、どこかで6個星が出るバグを再発させない。
    """
    if score is None:
        return "☆☆☆☆☆"
    n = int(score // 20)
    return _stars5(n)


def star_count(stars: str | None) -> int:
    """★の数を返す(表示検証用)。None/空は0。"""
    return stars.count("★") if stars else 0


def apply_overvalued_cap(score: int, discount: float | None) -> tuple[int, str, str]:
    """割高(割安率>0)ならスコアを上限でクリップし、強い買い/最上位を封じる [カテゴリ2]。

    割高銘柄は総合スコアが OVERVALUED_SCORE_CAP を超えられず、その結果アクションも
    「強く買い増し」(=85点以上が必要)になり得ない。ハード制約として一元適用する。
    戻り値: (クリップ後スコア, ★, 6段階アクション)。
    """
    if discount is not None and discount > config.OVERVALUED_DISCOUNT_PCT:
        score = min(score, config.OVERVALUED_SCORE_CAP)
    _, action = score_to_action(score)
    # ★は必ず決定的関数(floor(score/20))から。アクション帯の★では上書きしない [カテゴリ12]。
    return score, stars_from_score(score), action


def score_to_action(score: int) -> tuple[str, str]:
    """スコア→(★評価[アクション帯], 6段階アクション)。

    注意: 表示用の★は stars_from_score(=floor(score/20)) を使うこと。ここが返す★は
    アクション帯(SCORE_BANDS)の内部表現で、表示に使うと帯境界で+1個ズレる [カテゴリ12]。
    """
    for threshold, stars, action in SCORE_BANDS:
        if score >= threshold:
            return stars, action
    return SCORE_BANDS[-1][1], SCORE_BANDS[-1][2]


def risk_reward(
    price: float | None, take_profit: float | None, stop_loss: float | None
) -> float | None:
    """RR = (目標−現在) / (現在−損切)。分母が正でなければ None。"""
    if price is None or take_profit is None or stop_loss is None:
        return None
    downside = price - stop_loss
    upside = take_profit - price
    if downside <= 0 or upside <= 0:
        return None
    return upside / downside


def supply_demand_stars(analysis: HoldingAnalysis) -> str | None:
    """需給の強さを★で表す(取得可能なプロキシの合成)。

    出来高トレンド・出来高価格シグナル・直近モメンタムから 0-5 を組み立てる。
    真の信用/貸借データが無いため、あくまで需給の代理指標。
    """
    score = 3.0
    signal = analysis.volume_price_signal or ""
    if "強い上昇" in signal:
        score += 1.0
    elif "下げ渋り" in signal:
        score += 0.5
    elif "強い下落" in signal:
        score -= 1.0
    elif "勢い弱い" in signal:
        score -= 0.5

    if analysis.volume_trend_ratio is not None:
        if analysis.volume_trend_ratio >= 1.5:
            score += 0.5
        elif analysis.volume_trend_ratio <= 0.7:
            score -= 0.5

    if analysis.momentum is not None:
        if analysis.momentum >= 5:
            score += 0.5
        elif analysis.momentum <= -5:
            score -= 0.5

    return _stars5(round(score))


def dividend_stars(analysis: HoldingAnalysis) -> str | None:
    """配当の魅力・持続性を★で表す。無配は None(表示は「—」)。

    利回り・配当性向(持続性)・増益/減益の整合から算出。
    DOE・累進配当は現状データ源が無いため未反映(将来拡張点)。
    """
    if not analysis.dividend_yield:
        return None
    score = 3.0
    if analysis.dividend_yield >= 4:
        score += 1.0
    elif analysis.dividend_yield >= 3:
        score += 0.5

    if analysis.payout_ratio is not None:
        if analysis.payout_ratio <= 0.6:
            score += 0.5  # 余裕があり増配余地・持続性◎
        elif analysis.payout_ratio >= 0.8:
            score -= 1.0  # 高すぎて減配リスク

    if analysis.earnings_growth is not None:
        score += 0.5 if analysis.earnings_growth > 0 else -0.5

    return _stars5(round(max(1, min(5, score))))


def _comment(action: str, disc: float | None, earnings_alert: bool, long_term_pct: float | None) -> str:
    base = {
        "強く買い増し": "保有中で最も優先して追加購入したい銘柄",
        "買い増し": "追加購入を前向きに検討したい銘柄",
        "保有": "保有継続が妥当。無理な追加は不要",
        "様子見": "今は様子見。次のシグナル待ち",
        "一部売却": "利益の一部確定を検討したい局面",
        "売却推奨": "売却・撤退を検討したい局面",
    }.get(action, "")

    tail = []
    if disc is not None and disc <= -10:
        tail.append("割安圏")
    elif disc is not None and disc >= 10:
        tail.append("割高圏")
    if long_term_pct is not None and long_term_pct >= 15 and action in ("強く買い増し", "買い増し", "保有"):
        tail.append("中長期の伸びしろ大")
    if earnings_alert:
        tail.append("決算接近に注意")

    return base + ("。" + "・".join(tail) if tail else "")


DIVIDER = "━━━━━━━━━━━━"


def _price(value: float | None) -> str:
    # 金額表示は共通フォーマッタに一本化(円・整数・カンマ) [カテゴリ15]。
    return format_yen(value)


def _horizon_text(h: HorizonExpectation) -> str:
    label = {"1週間": "1週", "1ヶ月": "1月", "半年〜1年": "半年〜1年"}.get(h.label, h.label)
    if h.pct is None:
        return f"・{label} —（{h.reason}）"
    basis = "検証" if h.basis == "検証実績" else "推定"
    stars = h.stars or ""
    return f"・{label} {h.pct:+.1f}%（{basis}{stars}／{h.reason}）"


def format_decision_lines(decision: HoldingDecision) -> list[str]:
    """CLI/テキスト用に1銘柄の判断を最小表示で整形する(Discordカードと同内容)。"""
    heading = f"{decision.symbol} {decision.name}" if decision.name else decision.symbol
    rank = f"（買い順位 {decision.rank}位）" if decision.rank else ""
    lines = [
        DIVIDER,
        f"【{heading}】 {decision.overall_stars} {decision.action}",
        f"総合スコア：{decision.overall_score}点 {decision.overall_stars}{rank}",
        "期待リターン",
        *[_horizon_text(h) for h in decision.expected_returns],
    ]
    rr = f"RR {decision.risk_reward:.1f}" if decision.risk_reward is not None else "RR —"
    disc = (
        f"割安率 {decision.discount_pct:+.1f}%（現在{_price(decision.current_price)}→適正{_price(decision.fair_value)}）"
        if decision.discount_pct is not None
        else "割安率 —"
    )
    alloc = (
        f"資金配分 {decision.alloc_pct:.0f}%"
        if should_show_allocation(decision.action, decision.alloc_pct)
        else "資金配分 —"
    )
    lines.append(f"{rr} ／ {disc} ／ {alloc}")

    earn = (
        f"決算まで {decision.days_to_earnings}日{'⚠️' if decision.earnings_alert else ''}"
        if decision.days_to_earnings is not None
        else "決算 —"
    )
    supply = f"需給 {decision.supply_demand_stars}" if decision.supply_demand_stars else "需給 —"
    div = f"配当 {decision.dividend_stars}" if decision.dividend_stars else "配当 —"
    lines.append(f"{earn} ／ {supply} ／ {div}")

    if decision.profit_pct is not None:
        lines.append(f"保有損益 {decision.profit_pct:+.1f}%")
    if decision.tax_note:
        lines.append(f"🧾 {decision.tax_note}")
    if decision.comment:
        lines.append(f"💬 {decision.comment}")
    return lines


def build_decision(
    summary: HoldingSummary,
    analysis: HoldingAnalysis,
    horizons: list[HorizonExpectation],
) -> HoldingDecision:
    """summary(スコア) + horizons(期間別期待) から最終判断をまとめる。"""
    disc = discount_pct(analysis)
    # [カテゴリ2] 割高ならスコアを上限クリップ→強い買い/最上位を封じる(最初の起点で保証)。
    overall_score, stars, action = apply_overvalued_cap(summary.score, disc)
    # [カテゴリ14] PERが同業種目安から極端に外れる=異常値(算出不可・要確認)。
    per_value = analysis.forward_per if analysis.forward_per is not None else analysis.per
    per_flagged = (
        per_value is not None and per_value > 0
        and not per_is_plausible(per_value, analysis.sector)
    )
    rr = risk_reward(summary.current_price, summary.take_profit, summary.stop_loss)
    earnings_alert = (
        analysis.days_to_earnings is not None and 0 <= analysis.days_to_earnings <= EARNINGS_ALERT_DAYS
    )
    long_term_pct = next((h.pct for h in horizons if h.label == "半年〜1年"), None)

    # 税の観点(保有のみ。数量0の新規候補には付けない)。
    holding = analysis.holding
    tax_assessment = None
    if holding.quantity and holding.quantity > 0:
        tax_assessment = tax.assess(
            holding.account, holding.avg_cost, holding.quantity, analysis.current_price, action
        )

    return HoldingDecision(
        symbol=summary.symbol,
        name=summary.name,
        current_price=summary.current_price,
        overall_score=overall_score,
        overall_stars=stars,
        action=action,
        fair_value=fair_value(analysis),
        discount_pct=disc,
        risk_reward=rr,
        supply_demand_stars=supply_demand_stars(analysis),
        dividend_stars=dividend_stars(analysis),
        dividend_yield=analysis.dividend_yield,
        days_to_earnings=analysis.days_to_earnings,
        earnings_alert=earnings_alert,
        expected_returns=horizons,
        comment=_comment(action, disc, earnings_alert, long_term_pct),
        profit_pct=summary.profit_pct,
        volatility_pct=(
            analysis.atr / analysis.current_price * 100
            if analysis.atr and analysis.current_price
            else None
        ),
        sector=analysis.sector,
        account=tax_assessment.account if tax_assessment else None,
        unrealized_pl_yen=tax_assessment.unrealized_pl_yen if tax_assessment else None,
        tax_note=tax_assessment.note if tax_assessment else None,
        tax_sell_bias=tax_assessment.sell_bias if tax_assessment else 0,
        reasons=list(summary.reasons),
        risks=list(summary.risks),
        subscores=dict(getattr(summary, "subscores", {}) or {}),
        per_flagged=per_flagged,
    )
