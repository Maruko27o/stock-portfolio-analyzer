"""適正価格と割安率の推定。

「適正価格」はセクター別の標準PER×EPSと、アナリスト目標株価(平均)の合成。
どちらもヒューリスティックな目安であり、確定値ではない点に注意。
両者が欠損すれば None を返す(捏造しない)。
"""

from __future__ import annotations

from stock_analyzer import config
from stock_analyzer.analysis import HoldingAnalysis

# [カテゴリ14] PER妥当性チェックの許容レンジ(同業種の目安PERに対する倍率)。
# これを外れる(極端に小さい/大きい)PERは、EPSの単位/期間取り違えや欠損フォールバックの
# 疑いがあるため「PER算出不可・要確認」として割安判定の根拠から自動除外する。
PER_PLAUSIBLE_LOW_MULT = 1 / 3
PER_PLAUSIBLE_HIGH_MULT = 3.0


# [カテゴリ20] 適正価格が現在株価から桁でズレていれば、株式分割の調整不整合や
# 発行済株式数ベースの取り違えを疑い「要確認」として割安判定から除外する許容比率。
FAIR_VALUE_DIVERGENCE_HIGH = 5.0
FAIR_VALUE_DIVERGENCE_LOW = 0.2  # =1/5


def fair_value_is_sane(fv: float | None, current_price: float | None) -> bool:
    """適正価格が現在株価に対して桁でズレていないか [カテゴリ20]。

    分割調整の不整合(分割前EPS×分割後株価 等)は、適正価格を現在価格の数倍〜数分の一に
    飛ばす。現在価格の1/5〜5倍の範囲を「妥当」とし、外れたら False(要確認)。
    """
    if fv is None or current_price is None or current_price <= 0:
        return True  # 比較材料が無ければ判定しない(既存の欠損処理に委ねる)
    ratio = fv / current_price
    return FAIR_VALUE_DIVERGENCE_LOW <= ratio <= FAIR_VALUE_DIVERGENCE_HIGH


def per_is_plausible(per: float | None, sector: str | None) -> bool:
    """正のPERが同業種の目安レンジ(1/3〜3倍)に収まっていれば True [カテゴリ14]。

    None・非正(赤字/欠損)は「割安判定に使えない」ため False を返す(赤字は別経路で扱う)。
    """
    if per is None or per <= 0:
        return False
    typical = config.per_threshold(sector)
    return typical * PER_PLAUSIBLE_LOW_MULT <= per <= typical * PER_PLAUSIBLE_HIGH_MULT


def _implied_per(analysis: HoldingAnalysis) -> float | None:
    """現在価格とEPSから逆算した実効PER(EPS単位/期間の妥当性チェック用)。"""
    if analysis.eps is None or analysis.eps <= 0 or analysis.current_price is None:
        return None
    return analysis.current_price / analysis.eps


def eps_based_fair_value_usable(analysis: HoldingAnalysis) -> bool:
    """EPS由来の適正価格を使ってよいか(逆算PERが妥当レンジか) [カテゴリ14]。"""
    return per_is_plausible(_implied_per(analysis), analysis.sector)


def fair_value(analysis: HoldingAnalysis) -> float | None:
    """適正価格の目安。セクター標準PER×EPS と アナリスト目標株価平均の平均。

    どちらか一方しか取れなければそれを採用。両方欠損なら None。
    [カテゴリ14] 逆算PERが異常値のときは、EPS(単位/期間の疑い)由来の候補を除外する。
    """
    candidates: list[float] = []
    if analysis.eps is not None and analysis.eps > 0 and eps_based_fair_value_usable(analysis):
        per_based = config.per_threshold(analysis.sector) * analysis.eps
        # PERモデルはアナリストの最強気目標を超えて割安を主張しない(上限クリップ)。
        # 空運など構造的に低PERの業種で、一律のセクターPERが適正価格を過大にするのを防ぐ。
        if analysis.target_high_price is not None and analysis.target_high_price > 0:
            per_based = min(per_based, analysis.target_high_price)
        candidates.append(per_based)
    if analysis.target_mean_price is not None and analysis.target_mean_price > 0:
        candidates.append(analysis.target_mean_price)
    if not candidates:
        return None
    return sum(candidates) / len(candidates)


def discount_pct(analysis: HoldingAnalysis) -> float | None:
    """割安率 = (現在価格 − 適正価格) / 適正価格 × 100。

    負なら割安(現在が適正より安い)、正なら割高。例: 現在3445/適正3820 → −9.8%。
    """
    fv = fair_value(analysis)
    if fv is None or fv <= 0 or analysis.current_price is None:
        return None
    return (analysis.current_price - fv) / fv * 100


def analyst_upside_pct(analysis: HoldingAnalysis) -> float | None:
    """アナリスト目標株価(平均)までの上値余地 %。目標が無ければ None。"""
    tgt = analysis.target_mean_price
    if tgt is None or tgt <= 0 or analysis.current_price is None or analysis.current_price <= 0:
        return None
    return (tgt - analysis.current_price) / analysis.current_price * 100
