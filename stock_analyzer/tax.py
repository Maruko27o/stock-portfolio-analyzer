"""税効率の評価層。

保有の口座区分(NISA/特定)・取得単価・現在値から、売買判断に効く税の観点を
「注記」と「売却優先度の補正」として算出する。分析・スコアリングとは分離し、
ここは税の損得だけを扱う。捏造しない: 取れない情報(他銘柄の実現損益・年間の
確定申告状況など)は前提にせず、口座区分と含み損益から言える範囲に留める。

方針(ユーザー要件):
- NISA: 非課税。売却しても税メリットが無く、枠は再利用できないため「温存」を基本に
  し、期待値低下が明確なときだけ売る(=売却をやや後ろ倒し)。
- 特定: 実現益に約20.315%課税。含み損は損益通算(他の利益と相殺)に使える。
  利益が小さい(20万円以下)うちは税負担も軽く、売却の心理的ハードルが低い。
"""

from __future__ import annotations

from dataclasses import dataclass

# 上場株式の譲渡益課税(所得税15.315%+住民税5%)。
TAX_RATE = 0.20315

# 「利益が小さいうちは売りやすい」の目安。給与所得者の申告不要ライン(年20万円)に合わせる。
SMALL_PROFIT_YEN = 200_000

SELL_ACTIONS = {"一部売却", "売却推奨"}


@dataclass
class TaxAssessment:
    account: str  # "NISA" | "特定"
    unrealized_pl_yen: float | None  # 含み損益(円)。取得単価/数量が無ければ None
    tax_if_sold_yen: float | None  # 全株売却時の概算税額(特定・含み益時のみ)
    note: str  # 表示用の一文(※見方付き)
    sell_bias: int  # 売却優先度の補正: +1=売りやすい / 0=中立 / -1=温存(後ろ倒し)


def unrealized_pl_yen(
    avg_cost: float | None, quantity: float | None, current_price: float | None
) -> float | None:
    """含み損益(円) = (現在値 − 取得単価) × 数量。データ不足なら None。"""
    if avg_cost is None or quantity is None or current_price is None:
        return None
    if quantity <= 0 or avg_cost <= 0:
        return None
    return (current_price - avg_cost) * quantity


def _yen(value: float) -> str:
    return f"{value:,.0f}円"


def assess(
    account: str,
    avg_cost: float | None,
    quantity: float | None,
    current_price: float | None,
    action: str,
) -> TaxAssessment:
    """口座区分・含み損益・アクションから税の観点をまとめる。"""
    account = "NISA" if account == "NISA" else "特定"
    pl = unrealized_pl_yen(avg_cost, quantity, current_price)
    is_sell = action in SELL_ACTIONS

    if account == "NISA":
        # 非課税。売却しても税メリットが無く、枠は再利用不可 → 温存が基本。
        if is_sell:
            note = "NISA(非課税)。枠は再利用できないため、売却は期待値低下が明確な時のみ ※税メリットは無い"
            bias = -1  # 売りを後ろ倒し(温存)
        else:
            note = "NISA(非課税)。配当・値上がり益に課税されないため長期保有向き ※枠は温存"
            bias = 0
        return TaxAssessment(account, pl, None, note, bias)

    # 特定口座(課税)
    if pl is None:
        return TaxAssessment(account, None, None, "特定口座 ※取得単価が無く含み損益を算出できません", 0)

    if pl < 0:
        # 含み損 → 損益通算(他の利益と相殺)に使える。売却でも税負担は発生しない。
        note = f"特定口座・含み損 {_yen(pl)}。売却すれば損益通算(他の利益と相殺)に使える ※他益がある時に有効"
        bias = 1 if is_sell else 0
        return TaxAssessment(account, pl, None, note, bias)

    # 含み益
    tax = pl * TAX_RATE
    if pl <= SMALL_PROFIT_YEN:
        note = (
            f"特定口座・含み益 {_yen(pl)}(概算税 {_yen(tax)})。利益が小さく税負担も軽いので売却しやすい "
            "※20万円以下の目安"
        )
        bias = 1
    else:
        note = (
            f"特定口座・含み益 {_yen(pl)}(売却時 概算税 {_yen(tax)})。売却は税負担を考慮 "
            "※利益確定は分割やNISA枠移管も検討"
        )
        bias = 0
    return TaxAssessment(account, pl, tax, note, bias)
