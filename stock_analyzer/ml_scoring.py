"""機械学習スコアリング [パイプライン第3段: scikit-learn]。

財務指標(第1段)＋モメンタム特徴量(第2段)を1本の特徴ベクトルにまとめ、学習済みモデル
(あれば)で 0-100 のスコアを出す。モデルが無い環境でも動くよう、特徴量の重み付き合成に
よる決定論的フォールバックを用意する(=scikit-learn 未学習でも破綻しない)。

学習: 履歴(判断ログ/バックテスト)から「一定期間後に上昇したか」を教師ラベルにして
GradientBoosting を学習し joblib で保存する。予測は上昇確率×100 をスコアにする。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from stock_analyzer.fundamental_screen import FinancialMetrics
from stock_analyzer.momentum import MomentumFeatures

MODEL_PATH = Path(__file__).parent / "data" / "ml_model.joblib"

# 特徴量の並び(学習・推論で共有する唯一の定義)。財務→モメンタムの順。
FINANCIAL_FEATURES = ["roe", "operating_margin", "equity_ratio", "profit_growth"]
MOMENTUM_FEATURES = [
    "rsi14", "roc5", "roc20", "roc60", "macd_hist",
    "sma25_ratio", "sma_align", "atr_pct", "vol_ratio",
]
FEATURE_ORDER = FINANCIAL_FEATURES + MOMENTUM_FEATURES


def build_features(
    metrics: FinancialMetrics | None,
    momentum: MomentumFeatures | None,
    profit_growth: float | None = None,
) -> list[float | None]:
    """財務＋モメンタムを FEATURE_ORDER の順に並べた特徴ベクトルを作る(欠損は None)。"""
    fin = {
        "roe": metrics.roe if metrics else None,
        "operating_margin": metrics.operating_margin if metrics else None,
        "equity_ratio": metrics.equity_ratio if metrics else None,
        "profit_growth": profit_growth,
    }
    mom = momentum.as_dict() if momentum else {}
    return [fin.get(k) if k in fin else mom.get(k) for k in FEATURE_ORDER]


# ---------------------------------------------------------------------------
# フォールバック(決定論): 学習済みモデルが無いときの合成スコア 0-100
# ---------------------------------------------------------------------------
# 各特徴量の「良い方向」への寄与重み。値は緩やかに正規化してから合成する。
_FALLBACK_WEIGHTS = {
    "roe": 1.2, "operating_margin": 1.0, "equity_ratio": 0.6, "profit_growth": 1.0,
    "roc20": 0.8, "roc60": 0.8, "sma25_ratio": 0.6, "sma_align": 0.6,
    "macd_hist": 0.4, "vol_ratio": 0.3,
    "rsi14": 0.0,  # 過熱/売られすぎは別処理(下で調整)
}


def _squash(x: float) -> float:
    """緩やかな飽和(tanh)で外れ値の影響を抑える。"""
    return math.tanh(x)


def rule_fallback(features: list[float | None]) -> int:
    """特徴量から決定論的に 0-100 スコアを出す(モデル不在時)。"""
    fv = dict(zip(FEATURE_ORDER, features))
    score = 0.0
    total_w = 0.0
    for key, w in _FALLBACK_WEIGHTS.items():
        if w == 0:
            continue
        v = fv.get(key)
        if v is None:
            continue
        # スケールを大まかに揃える(比率系は×5、%系は/10)。
        if key in ("roe", "operating_margin", "equity_ratio", "profit_growth", "sma_align"):
            norm = _squash(v * 3)
        else:
            norm = _squash(v / 10.0)
        score += w * norm
        total_w += w
    base = 50.0 + (score / total_w * 50.0 if total_w else 0.0)
    # RSI 過熱は減点、売られすぎは小加点(短期の反転を考慮)。
    rsi = fv.get("rsi14")
    if rsi is not None:
        if rsi >= 80:
            base -= 8
        elif rsi >= 70:
            base -= 4
        elif rsi <= 30:
            base += 3
    return int(max(0, min(100, round(base))))


# ---------------------------------------------------------------------------
# 学習・保存・読込(scikit-learn)
# ---------------------------------------------------------------------------
def _build_pipeline():
    """欠損補完→標準化→勾配ブースティングのパイプライン。"""
    from sklearn.compose import ColumnTransformer  # noqa: F401  (将来拡張余地)
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("clf", GradientBoostingClassifier(random_state=0)),
        ]
    )


def train(rows: list[list[float | None]], labels: list[int]):
    """特徴ベクトル列と2値ラベル(1=上昇)からモデルを学習して返す。"""
    import numpy as np

    X = np.array([[float("nan") if v is None else float(v) for v in r] for r in rows], dtype=float)
    y = np.array(labels, dtype=int)
    model = _build_pipeline()
    model.fit(X, y)
    return model


def save_model(model, path: Path = MODEL_PATH) -> None:
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURE_ORDER}, path)


def load_model(path: Path = MODEL_PATH):
    """保存済みモデルを読む。無い/壊れている/sklearn未導入なら None。"""
    if not Path(path).exists():
        return None
    try:
        import joblib

        payload = joblib.load(path)
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("features") != FEATURE_ORDER:
        return None  # 特徴量の並びが変わったモデルは使わない(不整合防止)
    return payload.get("model")


def model_score(model, features: list[float | None]) -> int:
    """学習済みモデルで 0-100 スコア(上昇確率×100)を出す。"""
    import numpy as np

    X = np.array([[float("nan") if v is None else float(v) for v in features]], dtype=float)
    proba = model.predict_proba(X)[0]
    # クラス1(上昇)の確率。二値でない場合は最大確率。
    classes = list(getattr(model, "classes_", [0, 1]))
    idx = classes.index(1) if 1 in classes else int(np.argmax(proba))
    return int(round(proba[idx] * 100))


@dataclass
class MLScorer:
    """学習済みモデルがあれば使い、無ければ決定論フォールバックでスコアする。"""

    model: object | None = None

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "MLScorer":
        return cls(model=load_model(path))

    @property
    def backend(self) -> str:
        return "sklearn-model" if self.model is not None else "rule-fallback"

    def score(self, features: list[float | None]) -> int:
        if self.model is not None:
            try:
                return model_score(self.model, features)
            except Exception:
                pass  # 推論失敗時はフォールバックへ
        return rule_fallback(features)


def sklearn_available() -> bool:
    try:
        import sklearn  # noqa: F401

        return True
    except Exception:
        return False
