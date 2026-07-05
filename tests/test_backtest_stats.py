from stock_analyzer.backtest_stats import (
    format_backtest_compact,
    format_backtest_lines,
    load_stats,
    stats_for_score,
)

FAKE_STATS = {
    "metadata": {"min_band_count": 30},
    "adopted": {
        "rule": "テスト",
        "bands": {
            "90-94": {
                "count": 120,
                "win_rate": 68.4,
                "avg_win": 7.3,
                "avg_loss": 3.2,
                "risk_reward": 2.28,
                "profit_factor": 2.11,
                "expectancy": 2.8,
                "avg_hold_days": 14.0,
                "signals_per_year": 18.0,
            },
            "50-54": {"count": 5, "win_rate": 50.0},
        },
    },
}


def test_stats_for_score_returns_matching_band():
    entry = stats_for_score(FAKE_STATS, 92)
    assert entry["band"] == "90-94"
    assert entry["win_rate"] == 68.4


def test_stats_for_score_hides_small_samples_and_missing():
    assert stats_for_score(FAKE_STATS, 52) is None  # count 5 < 30
    assert stats_for_score(FAKE_STATS, 77) is None  # 帯データなし
    assert stats_for_score(None, 92) is None
    assert stats_for_score(FAKE_STATS, None) is None


def test_load_stats_missing_file_returns_none(tmp_path):
    assert load_stats(str(tmp_path / "nope.json")) is None


def test_format_backtest_outputs_required_metrics():
    entry = stats_for_score(FAKE_STATS, 92)
    compact = format_backtest_compact(entry)
    assert "勝率68.4%" in compact
    assert "期待値+2.8%" in compact
    assert "利+7.3%" in compact
    assert "損-3.2%" in compact
    assert "RR2.28" in compact
    assert "PF2.11" in compact
    assert "平均14日" in compact
    assert "年18回" in compact

    lines = format_backtest_lines(entry)
    assert any("実績勝率：68.4%" in line for line in lines)
    assert any("期待値：+2.8%" in line for line in lines)
