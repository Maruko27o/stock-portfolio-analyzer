"""期間別(1週間・1ヶ月・半年〜1年)の期待リターン。

短中期は検証済みバックテスト分布(backtest_stats)から、期待値をそのまま採用する。
半年〜1年はバックテスト対象外(最大30営業日・点在時点のファンダ入手不可)のため、
ファンダ由来の「モデル推定」とし、信頼度はサンプル件数ではなく
「根拠シグナルの数・符号の一致・データ充足度」から算出する(誠実ラベルの原則)。
"""

from __future__ import annotations

from dataclasses import dataclass

from stock_analyzer.analysis import HoldingAnalysis
from stock_analyzer.backtest_stats import horizon_expectations
from stock_analyzer.valuation import analyst_upside_pct, discount_pct


@dataclass
class HorizonExpectation:
    label: str  # "1週間" / "1ヶ月" / "半年〜1年"
    pct: float | None  # 期待リターン(%)。データ不足なら None
    stars: str | None  # 信頼度(★のみ。多いほど確度が高い)。None は表示なし
    confidence_label: str  # "高" / "中" / "低" / "データ不足"
    basis: str  # "検証実績" / "モデル推定"
    reason: str  # 1フレーズの理由


# 半年〜1年のモデル推定はサンプル検証が無いので、最大★★★★までに抑える。
LONG_TERM_MAX_STARS = 4


def _confidence_label(stars: str | None) -> str:
    n = stars.count("★") if stars else 0
    if n >= 3:
        return "高"
    if n == 2:
        return "中"
    if n >= 1:
        return "低"
    return "データ不足"


def _filled_stars(n: int) -> str | None:
    return "★" * n if n >= 1 else None


def _short_reason(analysis: HoldingAnalysis, pct: float | None) -> str:
    if pct is None:
        return "短期の検証データ不足"
    positive = pct >= 0
    if analysis.rsi is not None and analysis.rsi <= 30:
        return "売られすぎからの短期反発余地"
    if analysis.rsi is not None and analysis.rsi >= 70:
        return "短期は過熱で反落に注意"
    if positive:
        return "短期テクニカル良好"
    return "短期は調整含み"


def _mid_reason(analysis: HoldingAnalysis, pct: float | None) -> str:
    if pct is None:
        return "中期の検証データ不足"
    if "強い上昇" in analysis.volume_price_signal:
        return "出来高を伴う需給改善中"
    if "強い下落" in analysis.volume_price_signal:
        return "需給悪化に警戒"
    return "トレンド継続を想定" if pct >= 0 else "上値の重い展開を想定"


def _long_term_drivers(analysis: HoldingAnalysis) -> list[tuple[str, float, bool]]:
    """半年〜1年の期待リターンを構成するドライバー。

    各要素 = (ラベル, 寄与%, 方向性ドライバーか)。方向性=符号一致で信頼度を測る対象。
    データが無いドライバーは含めない。
    """
    drivers: list[tuple[str, float, bool]] = []

    # 割安是正: 適正価格へ半分ほど回帰すると仮定(割安なら上値、割高なら下値)
    disc = discount_pct(analysis)
    if disc is not None:
        drivers.append(("割安是正", max(-15.0, min(15.0, -disc * 0.4)), True))

    # 利益成長: 中長期の株価は概ね利益に追随。YoYを控えめに反映。
    # ただしトレーリングの急増(例: 前年比+50%)は一過性のことが多く、そのまま
    # 延長すると期待値を過大にする。30%を超える伸びは逓減させ、寄与も±14に抑える。
    if analysis.earnings_growth is not None:
        g = analysis.earnings_growth * 100
        if g > 30:
            g = 30 + (g - 30) * 0.3  # 30%超は割り引く(持続性が低い)
        elif g < -30:
            g = -30 + (g + 30) * 0.3
        drivers.append(("利益成長", max(-14.0, min(14.0, g * 0.5)), True))

    # 売上成長: 補助的
    if analysis.revenue_growth is not None:
        drivers.append(("売上成長", max(-8.0, min(8.0, analysis.revenue_growth * 100 * 0.2)), True))

    # 配当: 1年で受け取る利回り(方向性ドライバーではない)
    if analysis.dividend_yield is not None:
        drivers.append(("配当", max(0.0, min(8.0, analysis.dividend_yield)), False))

    # アナリスト目標: 上値余地を控えめに反映
    upside = analyst_upside_pct(analysis)
    if upside is not None:
        drivers.append(("アナリスト目標", max(-15.0, min(15.0, upside * 0.4)), True))

    return drivers


def _long_term_reason(drivers: list[tuple[str, float, bool]], total: float) -> str:
    if not drivers:
        return "長期判断に必要なデータ不足"
    labels = {
        "割安是正": "割安",
        "利益成長": "業績成長",
        "売上成長": "増収",
        "配当": "配当",
        "アナリスト目標": "アナリスト強気",
    }
    if total >= 0:
        positives = [labels[name] for name, pct, _ in drivers if pct > 0]
        if positives:
            return "＋".join(positives[:2])
        return "総合的に緩やかな上昇期待"
    return "割高・業績鈍化などで慎重"


# アナリスト合意へのアンカリング設定。
MIN_ANALYSTS_FOR_ANCHOR = 3  # これ未満のカバレッジではアンカリングしない
DIVERGENCE_SCALE = 40.0  # モデルとアナリスト平均の乖離をこの%で正規化して信頼配分に使う
MODEL_WEIGHT_MIN = 0.2  # 乖離が大きいほどモデルの重みを下げる下限
MODEL_WEIGHT_MAX = 0.8  # 一致しているほどモデルを信頼する上限
LARGE_DIVERGENCE = 20.0  # これ以上乖離したら信頼度を1段下げる


def _upside_pct(target: float | None, price: float | None) -> float | None:
    if target is None or target <= 0 or price is None or price <= 0:
        return None
    return (target - price) / price * 100


def _anchor_to_analysts(
    model_total: float, analysis: HoldingAnalysis
) -> tuple[float, bool, float]:
    """モデルの長期期待をアナリスト合意へ引き戻す。

    プロのアナリストは減益ガイダンスや政策リスク等を織り込んで目標株価を出す。
    モデルがアナリスト平均から乖離するほど、アナリスト寄りに補正する
    (=モデルとアナリストが一致していればモデルを信頼、食い違えばアナリストを信頼)。
    戻り値: (補正後total, アンカリングしたか, モデルとアナリスト平均の乖離%)。
    """
    mean_up = _upside_pct(analysis.target_mean_price, analysis.current_price)
    if mean_up is None or (analysis.num_analysts or 0) < MIN_ANALYSTS_FOR_ANCHOR:
        return model_total, False, 0.0

    high_up = _upside_pct(analysis.target_high_price, analysis.current_price)
    low_up = _upside_pct(analysis.target_low_price, analysis.current_price)
    hi = high_up if high_up is not None else mean_up + 20
    lo = low_up if low_up is not None else mean_up - 20

    clamped = max(lo, min(hi, model_total))  # 最強気〜最弱気のレンジ内に収める
    divergence = abs(model_total - mean_up)
    weight = max(MODEL_WEIGHT_MIN, min(MODEL_WEIGHT_MAX, 1 - divergence / DIVERGENCE_SCALE))
    total = weight * clamped + (1 - weight) * mean_up
    return total, True, divergence


def long_term_estimate(analysis: HoldingAnalysis) -> tuple[float | None, str | None, str]:
    """半年〜1年の期待リターン(%)・信頼度★・理由を返す(モデル推定)。

    ファンダ由来のモデル推定を、アナリスト合意でアンカリングして過大評価を防ぐ。
    """
    drivers = _long_term_drivers(analysis)
    if not drivers:
        return None, None, "長期判断に必要なデータ不足"

    model_total = sum(pct for _, pct, _ in drivers)
    total, anchored, divergence = _anchor_to_analysts(model_total, analysis)

    directional = [(name, pct) for name, pct, is_dir in drivers if is_dir]
    n_data = len(drivers)
    base = 3 if n_data >= 5 else 2 if n_data >= 3 else 1
    # 方向性ドライバーが2つ以上あり全て同符号なら+1(根拠の全会一致)
    if len(directional) >= 2 and model_total != 0:
        sign = 1 if model_total > 0 else -1
        if all((1 if pct > 0 else -1 if pct < 0 else sign) == sign for _, pct in directional):
            base += 1
    # モデルとアナリストが大きく食い違う=見立てが不確か。信頼度を1段下げる。
    if anchored and divergence >= LARGE_DIVERGENCE:
        base -= 1
    stars = _filled_stars(max(1, min(LONG_TERM_MAX_STARS, base)))

    reason = _long_term_reason(drivers, total)
    if anchored and divergence >= LARGE_DIVERGENCE:
        mean_up = _upside_pct(analysis.target_mean_price, analysis.current_price)
        if mean_up is not None and mean_up < model_total:
            reason = "アナリスト目標は控えめ(強気は限定的)"
    return total, stars, reason


def expected_returns(
    summary,
    analysis: HoldingAnalysis,
    backtest_stats: dict | None,
) -> list[HorizonExpectation]:
    """3期間(1週間・1ヶ月・半年〜1年)の期待リターンを返す。

    summary は HoldingSummary(price_score でバックテスト帯を照会)。
    """
    by_days = {d["days"]: d for d in horizon_expectations(backtest_stats, summary.price_score)}

    out: list[HorizonExpectation] = []

    five = by_days.get(5)
    if five is not None:
        reason = _short_reason(analysis, five["expectancy"])
        out.append(
            HorizonExpectation(
                "1週間", five["expectancy"], five["stars"], _confidence_label(five["stars"]),
                "検証実績", reason,
            )
        )
    else:
        out.append(
            HorizonExpectation("1週間", None, None, "データ不足", "検証実績", _short_reason(analysis, None))
        )

    twenty = by_days.get(20)
    if twenty is not None:
        reason = _mid_reason(analysis, twenty["expectancy"])
        out.append(
            HorizonExpectation(
                "1ヶ月", twenty["expectancy"], twenty["stars"], _confidence_label(twenty["stars"]),
                "検証実績", reason,
            )
        )
    else:
        out.append(
            HorizonExpectation("1ヶ月", None, None, "データ不足", "検証実績", _mid_reason(analysis, None))
        )

    pct, stars, reason = long_term_estimate(analysis)
    out.append(
        HorizonExpectation("半年〜1年", pct, stars, _confidence_label(stars), "モデル推定", reason)
    )

    return out
