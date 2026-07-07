"""チューニング可能な設定値の一元管理。

分析比率(期間別の重み)・カテゴリ上限・セクター別の割安基準・資金配分の制約を
ここに集約する。「分析比率は改善し続ける」ための調整点を一箇所にまとめ、
スコアリング/判断/配分ロジックからはここを参照する。

過去は summary.py に散在していた CATEGORY_CAPS とセクター別 PER/PBR 基準も
ここへ移し、summary.py は後方互換のため再エクスポートする。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# スコアリング(summary.build_signals)のカテゴリ上限
# ---------------------------------------------------------------------------
# トレンド系指標(移動平均の並び・MACD・モメンタム…)は同じことを別角度で測って
# いるだけで、放置すると上昇相場で±30以上に積み上がりファンダを飲み込む。
# カテゴリごとに上限を設け、一側面がスコアを支配しないようにする。
CATEGORY_CAPS = {"technical": 20, "fundamental": 18, "dividend": 6, "market": 8, "valuation": 20}

# ---------------------------------------------------------------------------
# セクター別の割安基準(yfinance のセクター名)
# ---------------------------------------------------------------------------
# 銀行は平時 PER<10/PBR<0.7、グロースははるかに高い水準で取引されるため、
# 一律 PER15/PBR1 の閾値は両者を取り違える。
SECTOR_PER_THRESHOLD = {
    "Financial Services": 10,
    "Energy": 10,
    "Utilities": 12,
    "Basic Materials": 12,
    "Real Estate": 12,
    "Industrials": 15,
    "Consumer Cyclical": 15,
    "Consumer Defensive": 18,
    "Communication Services": 18,
    "Healthcare": 22,
    "Technology": 25,
}
DEFAULT_PER_THRESHOLD = 15

SECTOR_PBR_THRESHOLD = {
    "Financial Services": 0.7,
    "Energy": 0.8,
    "Utilities": 0.8,
    "Basic Materials": 1.0,
    "Real Estate": 1.2,
    "Industrials": 1.3,
    "Consumer Cyclical": 1.3,
    "Consumer Defensive": 1.8,
    "Communication Services": 1.8,
    "Healthcare": 2.5,
    "Technology": 3.0,
}
DEFAULT_PBR_THRESHOLD = 1.0


def per_threshold(sector: str | None) -> float:
    return SECTOR_PER_THRESHOLD.get(sector, DEFAULT_PER_THRESHOLD)


def pbr_threshold(sector: str | None) -> float:
    return SECTOR_PBR_THRESHOLD.get(sector, DEFAULT_PBR_THRESHOLD)


# ---------------------------------------------------------------------------
# 期間別の分析比率(horizon_model が参照)
# ---------------------------------------------------------------------------
# ユーザー指定の初期値。短期ほどテクニカル/需給、長期ほどファンダ/業績を重視する。
# 「改善し続ける」対象なので値はここだけで調整できるようにしている。
#
# 注意: news(ニュース/SNSセンチメント)は現状データ源が無い。重みは意図の記録として
# 残すが、寄与は0として扱い、算出時に他カテゴリへ再正規化する(捏造しない方針)。
HORIZON_WEIGHTS = {
    "1週間": {"technical": 40, "supply_demand": 35, "news": 15, "fundamental": 10},
    "1ヶ月": {"technical": 30, "supply_demand": 25, "fundamental": 30, "news": 15},
    "半年〜1年": {
        "fundamental": 50,
        "earnings": 20,
        "macro": 15,
        "supply_demand": 10,
        "technical": 5,
    },
}

# 現状データ源が無く、寄与を0として再正規化するカテゴリ。
UNAVAILABLE_WEIGHT_CATEGORIES = {"news"}


def normalized_weights(horizon: str) -> dict[str, float]:
    """指定期間の重みから、データ源の無いカテゴリを除いて合計1.0に再正規化して返す。"""
    raw = HORIZON_WEIGHTS.get(horizon, {})
    usable = {k: v for k, v in raw.items() if k not in UNAVAILABLE_WEIGHT_CATEGORIES and v > 0}
    total = sum(usable.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in usable.items()}


# ---------------------------------------------------------------------------
# 資金配分(allocation)の制約
# ---------------------------------------------------------------------------
ALLOC_SECTOR_CAP = 0.35  # 1セクターへの最大配分(現金を除く投資分に対して)
ALLOC_NAME_CAP = 0.30  # 1銘柄への最大配分(現金を含む全体に対して)
ALLOC_MIN_SCORE = 45  # これ未満のスコアの銘柄は新規配分の対象外(保有継続はする)

# 相場環境ごとの現金下限(全体に対する比率)。リスクオフでは現金を厚く持つ。
CASH_FLOOR_BY_REGIME = {
    "上昇": 0.10,
    "横ばい": 0.20,
    "下落": 0.35,
}
DEFAULT_CASH_FLOOR = 0.20

# VIX がこの水準以上なら、相場環境に関わらず現金下限を引き上げる。
VIX_RISK_OFF = 30.0
VIX_RISK_OFF_CASH_FLOOR = 0.40


def cash_floor(regime: str | None, vix: float | None) -> float:
    """相場環境と VIX から現金下限を決める。"""
    floor = CASH_FLOOR_BY_REGIME.get(regime, DEFAULT_CASH_FLOOR)
    if vix is not None and vix >= VIX_RISK_OFF:
        floor = max(floor, VIX_RISK_OFF_CASH_FLOOR)
    return floor
