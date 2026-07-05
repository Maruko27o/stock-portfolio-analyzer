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


FAKE_STRATEGY_STATS = {
    "metadata": {"min_count": 200, "basis": "20営業日先リターン"},
    "strategies": {
        "順張り": {
            "test": {"count": 5000, "win_rate": 55.3, "expectancy": 1.9, "profit_factor": 1.6},
            "regimes_test": {
                "上昇": {"count": 3000, "win_rate": 63.0, "expectancy": 3.2},
                "下落": {"count": 50, "win_rate": 47.0, "expectancy": -1.7},
            },
        },
        "逆張り": {"test": {"count": 150, "win_rate": 60.0, "expectancy": 2.5}},
    },
}


def test_stats_for_strategy_uses_priority_and_min_count():
    from stock_analyzer.backtest_stats import stats_for_strategy

    # 逆張りは件数不足(150<200)なので順張りが選ばれる
    entry = stats_for_strategy(FAKE_STRATEGY_STATS, ["逆張り", "順張り"])
    assert entry["strategy"] == "順張り"
    assert entry["win_rate"] == 55.3
    # 成立戦略なし・統計なしはNone
    assert stats_for_strategy(FAKE_STRATEGY_STATS, []) is None
    assert stats_for_strategy(None, ["順張り"]) is None
    assert stats_for_strategy(FAKE_STRATEGY_STATS, ["レンジ"]) is None


def test_stats_for_strategy_prefers_current_regime_when_enough_samples():
    from stock_analyzer.backtest_stats import stats_for_strategy

    up = stats_for_strategy(FAKE_STRATEGY_STATS, ["順張り"], regime="上昇")
    assert up["regime"] == "上昇" and up["win_rate"] == 63.0
    # 下落相場は件数不足(50<200)なので全体実績にフォールバック
    down = stats_for_strategy(FAKE_STRATEGY_STATS, ["順張り"], regime="下落")
    assert down["regime"] is None and down["win_rate"] == 55.3


def test_format_strategy_compact():
    from stock_analyzer.backtest_stats import format_strategy_compact, stats_for_strategy

    entry = stats_for_strategy(FAKE_STRATEGY_STATS, ["順張り"])
    text = format_strategy_compact(entry)
    assert "戦略: 順張り" in text
    assert "勝率55.3%" in text
    assert "期待値+1.9%" in text
    assert "n=5,000" in text


FAKE_HORIZON_STATS = {
    "metadata": {"min_band_count": 30},
    "adopted": {"bands": {}},
    "rules": {
        "5営業日後売却": {"bands": {"75-79": {"count": 900, "expectancy": 0.4, "win_rate": 54.0}}},
        "10営業日後売却": {"bands": {"75-79": {"count": 900, "expectancy": 0.5, "win_rate": 53.5}}},
        "20営業日後売却": {"bands": {"75-79": {"count": 900, "expectancy": 0.9, "win_rate": 55.0}}},
        "30営業日後売却": {"bands": {"75-79": {"count": 10, "expectancy": 9.9, "win_rate": 99.0}}},
    },
}


def test_horizon_expectations_returns_periods_with_enough_samples():
    from stock_analyzer.backtest_stats import horizon_expectations

    result = horizon_expectations(FAKE_HORIZON_STATS, 77)
    assert [h["days"] for h in result] == [5, 10, 20]  # 30日は件数不足で除外
    assert result[0] == {"days": 5, "expectancy": 0.4, "win_rate": 54.0, "band": "75-79"}
    assert horizon_expectations(FAKE_HORIZON_STATS, None) == []
    assert horizon_expectations(None, 77) == []
    assert horizon_expectations(FAKE_HORIZON_STATS, 30) == []  # 帯データなし


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
