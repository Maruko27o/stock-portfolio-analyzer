"""チューニング可能な設定値の一元管理。

分析比率(期間別の重み)・カテゴリ上限・セクター別の割安基準・資金配分の制約を
ここに集約する。「分析比率は改善し続ける」ための調整点を一箇所にまとめ、
スコアリング/判断/配分ロジックからはここを参照する。

過去は summary.py に散在していた CATEGORY_CAPS とセクター別 PER/PBR 基準も
ここへ移し、summary.py は後方互換のため再エクスポートする。
"""

from __future__ import annotations

import json
from pathlib import Path

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


# ---------------------------------------------------------------------------
# 市場スタンス(表示される5段階)と推奨現金比率レンジの連動 [カテゴリ8]
# ---------------------------------------------------------------------------
# レポートに出す「本日の市場」タグ(強気〜弱気)を、そのまま現金比率へ反映する。
# これまで現金下限は長期レジーム(200日線)由来で、表示スタンス(短期ブレッドス)とは
# 別変数だったため「弱気でも現金10%固定」の乖離が起きていた。ここで一本化する。
# 値は (下限, 上限)。allocation は下限を現金フロアに使い、レポートにレンジを明記する。
CASH_RANGE_BY_STANCE = {
    "強気": (0.05, 0.10),
    "やや強気": (0.08, 0.13),
    "中立": (0.10, 0.15),
    "やや弱気": (0.13, 0.20),
    "弱気": (0.15, 0.25),
}
DEFAULT_CASH_RANGE = (0.10, 0.15)


def cash_range_for_stance(stance: str | None) -> tuple[float, float]:
    """表示スタンスに対応する推奨現金比率レンジ (下限, 上限) を返す。"""
    return CASH_RANGE_BY_STANCE.get(stance, DEFAULT_CASH_RANGE)


def cash_floor_for_stance(stance: str | None, vix: float | None) -> float:
    """表示スタンス由来の現金下限。VIX が高い局面ではさらに引き上げる。"""
    floor = cash_range_for_stance(stance)[0]
    if vix is not None and vix >= VIX_RISK_OFF:
        floor = max(floor, VIX_RISK_OFF_CASH_FLOOR)
    return floor


# ---------------------------------------------------------------------------
# 割高銘柄のハード制約 [カテゴリ2]
# ---------------------------------------------------------------------------
# 独自の適正価格計算で割高(割安率がプラス)なら、テクニカルが強くても
# 「総合スコアが一定点を超えない」「強い買い/今すぐ買いになり得ない」を保証する。
OVERVALUED_SCORE_CAP = 80  # 割高銘柄の総合スコア上限
OVERVALUED_DISCOUNT_PCT = 0.0  # これを超える割安率(=割高)を制約対象にする

# ---------------------------------------------------------------------------
# 集中度(保有比率超過)のハード制約 [カテゴリ1]
# ---------------------------------------------------------------------------
# 現在比率が推奨(目標)比率を「相対+30% かつ 絶対+5pt」超過した銘柄は、
# ファンダ/テクニカルが高くても最終アクションを買い増し系にできない。
OVERWEIGHT_REL_THRESHOLD = 0.30  # 目標比 +30%(相対)
OVERWEIGHT_ABS_THRESHOLD_PT = 5.0  # 目標比 +5pt(絶対)

# ---------------------------------------------------------------------------
# スコア安定性(急変検知) [カテゴリ4]
# ---------------------------------------------------------------------------
# 主要ファンダ入力が実質不変なのに総合スコアがこの点数以上動いたら、
# 「短期シグナル急変あり、要目視確認」を自動付与する(内部監査ログも保持)。
SCORE_JUMP_ALERT_PT = 20

# ---------------------------------------------------------------------------
# リスク欄の表示条件 [カテゴリ7]
# ---------------------------------------------------------------------------
# 明文化した条件のいずれかに該当したらリスク欄を必ず表示、非該当なら省略する。
RISK_RSI_OVERBOUGHT = 70.0
RISK_RSI_OVERSOLD = 30.0
RISK_PAYOUT_RATIO_MAX = 2.0  # 配当性向200%超(=2.0)
RISK_CURRENT_RATIO_MIN = 1.2  # 流動比率1.2未満


# ---------------------------------------------------------------------------
# tuning.json による上書き(iPhoneからでもGitHub上でこの1ファイルを編集して調整可能)
# ---------------------------------------------------------------------------
# 分析のしきい値・重み・上限を、Pythonを書かずに JSON 1枚で調整できるようにする。
# 例(stock_analyzer/data/tuning.json):
#   {"ALLOC_NAME_CAP": 0.25, "CATEGORY_CAPS": {"valuation": 25}}
# 誤設定で壊さないよう、上書きできるキーは許可リストに限定。壊れたJSONは無視して既定値。
TUNING_FILE = Path(__file__).parent / "data" / "tuning.json"

_OVERRIDABLE_KEYS = {
    "CATEGORY_CAPS",
    "SECTOR_PER_THRESHOLD",
    "DEFAULT_PER_THRESHOLD",
    "SECTOR_PBR_THRESHOLD",
    "DEFAULT_PBR_THRESHOLD",
    "HORIZON_WEIGHTS",
    "ALLOC_SECTOR_CAP",
    "ALLOC_NAME_CAP",
    "ALLOC_MIN_SCORE",
    "CASH_FLOOR_BY_REGIME",
    "DEFAULT_CASH_FLOOR",
    "VIX_RISK_OFF",
    "VIX_RISK_OFF_CASH_FLOOR",
    "CASH_RANGE_BY_STANCE",
    "DEFAULT_CASH_RANGE",
    "OVERVALUED_SCORE_CAP",
    "OVERVALUED_DISCOUNT_PCT",
    "OVERWEIGHT_REL_THRESHOLD",
    "OVERWEIGHT_ABS_THRESHOLD_PT",
    "SCORE_JUMP_ALERT_PT",
    "RISK_RSI_OVERBOUGHT",
    "RISK_RSI_OVERSOLD",
    "RISK_PAYOUT_RATIO_MAX",
    "RISK_CURRENT_RATIO_MIN",
}


def apply_tuning_overrides(path: Path = TUNING_FILE) -> dict:
    """tuning.json があれば許可キーのみ上書きする。適用した内容を返す(無ければ空)。

    dict 型の設定は部分更新(既存キーを保ちつつ上書き)、スカラーは置き換え。
    JSON が壊れていても例外にせず既定値のまま動く(通知を落とさない)。
    """
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    applied: dict = {}
    g = globals()
    for key, value in data.items():
        if key not in _OVERRIDABLE_KEYS or key not in g:
            continue
        current = g[key]
        if isinstance(current, dict) and isinstance(value, dict):
            current.update(value)  # 部分上書き(セクター基準などを一部だけ変えられる)
            applied[key] = value
        elif not isinstance(current, dict) and not isinstance(value, dict):
            g[key] = value
            applied[key] = value
    return applied


# import 時に一度だけ適用する。
TUNING_APPLIED = apply_tuning_overrides()
