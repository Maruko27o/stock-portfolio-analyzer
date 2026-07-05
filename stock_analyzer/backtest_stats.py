"""保存済みバックテスト統計の読み込みと参照。

通知処理はバックテストを実行せず、このモジュール経由で
data/backtest_stats.json のスコア帯別統計を参照するだけにする。
"""

from __future__ import annotations

import json
import os

DEFAULT_STATS_PATH = "data/backtest_stats.json"
STATS_PATH_ENV_VAR = "BACKTEST_STATS"
DEFAULT_STRATEGY_STATS_PATH = "data/strategy_stats.json"
STRATEGY_STATS_PATH_ENV_VAR = "STRATEGY_STATS"

# research.STRATEGY_PRIORITYと同順(通知を軽く保つためここに複製。テストで一致を保証)
STRATEGY_PRIORITY = ["ブレイクアウト", "順張り", "逆張り", "レンジ"]


def load_stats(path: str | None = None) -> dict | None:
    """統計JSONを読み込む。無ければNone(通知は実績表示なしで動く)。"""
    path = path or os.environ.get(STATS_PATH_ENV_VAR) or DEFAULT_STATS_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def band_label_for(score: float) -> str:
    from stock_analyzer.backtest import band_label

    return band_label(score)


def stats_for_score(stats: dict | None, score: float | None) -> dict | None:
    """スコアに対応する帯の実績統計を返す。件数不足・データ無しはNone。"""
    if stats is None or score is None:
        return None
    label = band_label_for(score)
    band = stats.get("adopted", {}).get("bands", {}).get(label)
    if not band or band.get("count", 0) < stats.get("metadata", {}).get("min_band_count", 30):
        return None
    entry = {"band": label, **band}
    symbols = stats.get("metadata", {}).get("symbols_used")
    if symbols and entry.get("signals_per_year") is not None:
        # ユニバース全体の頻度を1銘柄あたりに換算(カード表示用)
        entry["signals_per_year_per_symbol"] = round(entry["signals_per_year"] / symbols, 1)
    return entry


def load_strategy_stats(path: str | None = None) -> dict | None:
    """戦略タイプ別統計(research出力)を読み込む。無ければNone。"""
    path = path or os.environ.get(STRATEGY_STATS_PATH_ENV_VAR) or DEFAULT_STRATEGY_STATS_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def stats_for_strategy(
    stats: dict | None, active: list[str], regime: str | None = None
) -> dict | None:
    """成立中の戦略のうち最優先のものの検証期間実績を返す。

    現在の相場環境(上昇/下落/横ばい)の実績が十分な件数あればそれを優先し、
    無ければ全期間の検証実績を使う。検証期間(学習に使っていない期間)の
    成績のみ表示し、件数を信頼度としてそのまま出す。件数不足はNone。
    """
    if not stats or not active:
        return None
    min_count = stats.get("metadata", {}).get("min_count", 200)
    for name in STRATEGY_PRIORITY:
        if name not in active:
            continue
        strategy = stats.get("strategies", {}).get(name, {})
        if regime:
            regime_entry = strategy.get("regimes_test", {}).get(regime)
            if regime_entry and regime_entry.get("count", 0) >= min_count:
                return {"strategy": name, "regime": regime, **regime_entry}
        entry = strategy.get("test")
        if entry and entry.get("count", 0) >= min_count:
            return {"strategy": name, "regime": None, **entry}
    return None


def format_strategy_compact(entry: dict) -> str:
    """1行の戦略実績表示(Discord用)。"""
    pf = entry.get("profit_factor")
    scope = f"({entry['regime']}相場)" if entry.get("regime") else ""
    return (
        f"戦略: {entry['strategy']}{scope}｜検証実績 勝率{entry['win_rate']:.1f}%"
        f" / 期待値{entry['expectancy']:+.1f}%"
        + (f" / PF{pf:.2f}" if pf is not None else "")
        + f" / 信頼度n={entry['count']:,}"
    )


def format_backtest_compact(entry: dict) -> str:
    """1行の実績サマリー(Discord/テキスト用)。"""
    rr = entry.get("risk_reward")
    pf = entry.get("profit_factor")
    return (
        f"実績({entry['band']}帯): 勝率{entry['win_rate']:.1f}% / 期待値{entry['expectancy']:+.1f}%"
        f" / 利+{entry['avg_win']:.1f}% / 損-{entry['avg_loss']:.1f}%"
        + (f" / RR{rr:.2f}" if rr is not None else "")
        + (f" / PF{pf:.2f}" if pf is not None else "")
        + f" / 平均{entry['avg_hold_days']:.0f}日"
        + f" / 年{entry.get('signals_per_year_per_symbol', entry['signals_per_year']):.0f}回"
    )


def format_backtest_lines(entry: dict) -> list[str]:
    """LINEテキスト要約用の複数行表示。"""
    lines = [
        f"実績勝率：{entry['win_rate']:.1f}%（{entry['band']}帯・{entry['count']}件）",
        f"期待値：{entry['expectancy']:+.1f}%（利+{entry['avg_win']:.1f}%／損-{entry['avg_loss']:.1f}%）",
    ]
    rr = entry.get("risk_reward")
    pf = entry.get("profit_factor")
    detail = []
    if rr is not None:
        detail.append(f"RR{rr:.2f}")
    if pf is not None:
        detail.append(f"PF{pf:.2f}")
    detail.append(f"平均保有{entry['avg_hold_days']:.0f}日")
    detail.append(
        f"年約{entry.get('signals_per_year_per_symbol', entry['signals_per_year']):.0f}回/銘柄"
    )
    lines.append("／".join(detail))
    return lines
