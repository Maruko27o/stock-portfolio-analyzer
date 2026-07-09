"""ML スコアリングモデルの学習エントリポイント [パイプライン第3段の学習]。

各銘柄について「過去のある時点までの財務＋モメンタム特徴量」を入力、「その後20営業日で
上昇したか」を教師ラベルにして GradientBoosting を学習し、data/ml_model.joblib に保存する。

データ源は J-Quants(財務＋日足)。認証情報(JQUANTS_*)が必要。無い場合は何もしない。
学習は point-in-time を厳守: 特徴量は「予測時点まで」の系列だけから作り、ラベルはその先の
リターンで作る(未来リークを避ける)。

使い方:
    JQUANTS_REFRESH_TOKEN=... python -m scripts.train_ml_model --limit 300
"""

from __future__ import annotations

import argparse
import sys

from stock_analyzer import jquants, ml_scoring
from stock_analyzer.fundamental_screen import latest_metrics, profit_growth
from stock_analyzer.momentum import momentum_features
from stock_analyzer.screener import load_universe

HORIZON = 20  # ラベルの評価期間(営業日)


def build_dataset(client: jquants.JQuantsClient, codes: list[str]):
    rows: list[list[float | None]] = []
    labels: list[int] = []
    for symbol in codes:
        code = symbol.upper().replace(".T", "")
        statements = client.financial_statements(code)
        metrics = latest_metrics(code, statements)
        if metrics is None:
            continue
        growth = profit_growth(statements)
        closes, highs, lows, volumes = jquants.closes_from_quotes(client.daily_quotes(code))
        if len(closes) < HORIZON + 80:
            continue  # 特徴量＋ラベルに十分な長さが無い
        # point-in-time: 予測時点 = 末尾から HORIZON 日前。特徴量はそこまでで作る。
        cut = len(closes) - HORIZON
        feats = ml_scoring.build_features(
            metrics,
            momentum_features(closes[:cut], highs[:cut], lows[:cut], volumes[:cut]),
            growth,
        )
        label = 1 if closes[-1] > closes[cut - 1] else 0
        rows.append(feats)
        labels.append(label)
    return rows, labels


def main() -> None:
    parser = argparse.ArgumentParser(description="J-Quants×モメンタムでMLスコアモデルを学習")
    parser.add_argument("--limit", type=int, default=300, help="学習に使う最大銘柄数")
    args = parser.parse_args()

    if not ml_scoring.sklearn_available():
        print("scikit-learn が見つかりません。requirements を入れてください。", file=sys.stderr)
        raise SystemExit(1)

    client = jquants.JQuantsClient.from_env()
    if client is None or not client.available():
        print("J-Quants の認証情報がありません(JQUANTS_REFRESH_TOKEN 等)。学習をスキップ。", file=sys.stderr)
        raise SystemExit(1)

    codes = load_universe()[: args.limit]
    rows, labels = build_dataset(client, codes)
    n_pos = sum(labels)
    print(f"学習サンプル: {len(rows)}件(上昇 {n_pos} / 下落 {len(labels) - n_pos})")
    if len(rows) < 50 or n_pos == 0 or n_pos == len(labels):
        print("有効な学習データが不足しています(偏り/件数)。中止。", file=sys.stderr)
        raise SystemExit(1)

    model = ml_scoring.train(rows, labels)
    ml_scoring.save_model(model)
    print(f"モデルを保存しました: {ml_scoring.MODEL_PATH}")


if __name__ == "__main__":
    main()
