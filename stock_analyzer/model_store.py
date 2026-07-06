"""スコアリングの重み・閾値の単一参照点、および採用モデルの読込。

ライブ(summary.build_signals)とバックテスト(backtest.technical_points)が
同じ重み・閾値を参照するための唯一の出所。従来は両ファイルに同じ数値が
散在していたが、ここへ集約し、片方だけ変わって不整合になるのを防ぐ
(パリティはテストで保証)。

`adopted_model.json`(research が生成する採用セット)は既定では読み込むだけで
ライブ挙動は変えない(証拠先行=検証済みの採用セットを人が確認してから有効化)。
環境変数 USE_ADOPTED_MODEL=1 のときだけ、採用セットで一部特徴量を無効化・
重み調整する。既定(フォールバック)は現行の数値と完全一致。
"""

from __future__ import annotations

import json
import os

# ---------------------------------------------------------------------------
# 既定の重み(=現行ロジックの点数。名前で参照できるよう集約)
# ---------------------------------------------------------------------------
# テクニカル(build_signals と technical_points で共有。パリティ対象)
TECHNICAL_WEIGHTS: dict[str, int] = {
    "sma25": 8,  # 25日線の上/下
    "ma_align": 5,  # 移動平均の上昇/下降配列
    "macd_cross": 10,  # ゴールデン/デッドクロス
    "macd_trend": 4,  # MACDの上/下(クロス以外)
    "rsi_extreme": 8,  # RSI売られすぎ/買われすぎ
    "vol_strong_up": 6,  # 出来高増を伴う上昇
    "vol_weak_up": 2,  # 上昇だが出来高細る(減点)
    "vol_strong_down": 6,  # 出来高増を伴う下落(減点)
    "vol_dip": 2,  # 下落だが出来高減(下げ渋り)
    "sr_break": 5,  # レジスタンス突破/サポート割れ
    "bb": 3,  # ボリンジャー±2σ
    "mom_strong": 6,  # 直近10日 ±10%
    "mom_mild": 3,  # 直近10日 ±3〜10%
    "rel": 4,  # 対ベンチマーク相対力 ±5%
}

DIVIDEND_WEIGHTS: dict[str, int] = {
    "high_yield": 3,  # 高配当利回り(>=3%)
    "ex_div_near": 4,  # 権利落ち接近(30日以内)
}

MARKET_WEIGHTS: dict[str, int] = {
    "sentiment": 5,  # 市場全体の強気/弱気
    "vix_high": 8,  # VIX>=30 リスクオフ
    "vix_warn": 4,  # VIX>=25 警戒
    "vix_calm": 2,  # VIX<=15 安定
}

# 固定閾値(=現行。動的化は dynamic_thresholds で候補評価→採用時のみ差し替え)
THRESHOLDS: dict[str, float] = {
    "rsi_oversold": 30.0,
    "rsi_overbought": 70.0,
    "bb_sigma": 2.0,
    "mom_strong": 10.0,
    "mom_mild": 3.0,
    "rel": 5.0,
    "high_yield": 3.0,
    "vix_high": 30.0,
    "vix_warn": 25.0,
    "vix_calm": 15.0,
}

DEFAULT_ADOPTED_PATH = "data/adopted_model.json"
ADOPTED_PATH_ENV = "ADOPTED_MODEL"
USE_ADOPTED_ENV = "USE_ADOPTED_MODEL"

REQUIRED_KEYS = {"metadata", "features"}


def load_adopted_model(path: str | None = None) -> dict | None:
    """adopted_model.json を読み込む。無い/壊れている/スキーマ不正なら None(=フォールバック)。"""
    path = path or os.environ.get(ADOPTED_PATH_ENV) or DEFAULT_ADOPTED_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or not REQUIRED_KEYS <= set(data):
        return None
    if not isinstance(data.get("features"), dict):
        return None
    return data


def adopted_active() -> bool:
    """採用セットをライブに反映するか。既定は False(証拠先行)。"""
    return os.environ.get(USE_ADOPTED_ENV) == "1"


def technical_weights() -> dict[str, int]:
    """テクニカル重みを返す。既定は現行値(フォールバック)。

    採用セットが有効かつ該当特徴量の判定があれば、drop された特徴量に対応する重みを0にする
    (＝ライブから外す)。マッピングが無いものは現行のまま(安全側)。
    """
    weights = dict(TECHNICAL_WEIGHTS)
    if not adopted_active():
        return weights
    model = load_adopted_model()
    if not model:
        return weights
    rejected = {r.get("feature") for r in model.get("rejected", [])}
    for research_name, weight_key in RESEARCH_TO_WEIGHT.items():
        if research_name in rejected and weight_key in weights:
            weights[weight_key] = 0
    return weights


# research の特徴量名 → ライブ重みキー(drop 反映用の対応表。分かるものだけ)
RESEARCH_TO_WEIGHT = {
    "25日線上": "sma25",
    "MA上昇配列": "ma_align",
    "MACD_GC": "macd_cross",
    "MACD_DC": "macd_cross",
    "MACD上": "macd_trend",
    "RSI30以下": "rsi_extreme",
    "RSI70以上": "rsi_extreme",
    "出来高増×上昇": "vol_strong_up",
    "60日高値更新": "sr_break",
    "60日安値割れ": "sr_break",
    "ボリンジャー-2σ以下": "bb",
    "ボリンジャー+2σ以上": "bb",
    "直近10日+3%以上": "mom_mild",
    "直近10日-3%以下": "mom_mild",
    "市場より強い": "rel",
    "市場より弱い": "rel",
}
