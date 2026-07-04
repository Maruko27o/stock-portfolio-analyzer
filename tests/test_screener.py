from unittest.mock import patch

import pandas as pd

from stock_analyzer.screener import (
    screen_universe,
    swing_score,
    top_swing_pick,
    top_swing_picks,
)


def _series(closes):
    return {
        "Open": closes,
        "High": [c + 1 for c in closes],
        "Low": [c - 1 for c in closes],
        "Close": closes,
        "Volume": [1000 + i * 10 for i in range(len(closes))],
    }


def test_swing_score_returns_none_when_not_enough_data():
    assert swing_score([100.0] * 10, [101.0] * 10, [99.0] * 10, [1000.0] * 10) is None


def test_swing_score_uptrend_scores_higher_than_downtrend():
    up = [100.0 + i for i in range(60)]
    down = [160.0 - i for i in range(60)]
    volumes = [1000.0 + i * 10 for i in range(60)]

    up_score, up_reasons = swing_score(up, [c + 1 for c in up], [c - 1 for c in up], volumes)
    down_score, _ = swing_score(down, [c + 1 for c in down], [c - 1 for c in down], volumes)

    assert up_score > down_score
    assert len(up_reasons) >= 1


def test_swing_candidate_display_score_is_clamped():
    from stock_analyzer.screener import SwingCandidate

    assert SwingCandidate("X.T", raw_score=130, reasons=[], current_price=1.0).score == 100
    assert SwingCandidate("Y.T", raw_score=-20, reasons=[], current_price=1.0).score == 0


def test_screen_universe_skips_missing_tickers_and_scores_the_rest():
    up = [100.0 + i for i in range(60)]
    down = [160.0 - i for i in range(60)]
    fake_data = {
        "AAA.T": pd.DataFrame(_series(up)),
        "BBB.T": pd.DataFrame(_series(down)),
    }

    with patch("stock_analyzer.screener._download_history", return_value=fake_data):
        candidates = screen_universe(["AAA.T", "BBB.T", "CCC.T"])

    symbols = {c.symbol for c in candidates}
    assert symbols == {"AAA.T", "BBB.T"}


def test_top_swing_pick_returns_highest_scoring():
    up = [100.0 + i for i in range(60)]
    down = [160.0 - i for i in range(60)]
    fake_data = {
        "AAA.T": pd.DataFrame(_series(up)),
        "BBB.T": pd.DataFrame(_series(down)),
    }

    with patch("stock_analyzer.screener._download_history", return_value=fake_data):
        pick = top_swing_pick(["AAA.T", "BBB.T"])

    assert pick is not None
    assert pick.symbol == "AAA.T"


def test_top_swing_pick_returns_none_when_no_candidates():
    with patch("stock_analyzer.screener._download_history", return_value={}):
        assert top_swing_pick(["AAA.T"]) is None


def test_top_swing_picks_returns_sorted_top_n():
    up_strong = [100.0 + i * 1.5 for i in range(60)]
    up_mild = [100.0 + i * 0.3 for i in range(60)]
    down = [160.0 - i for i in range(60)]
    fake_data = {
        "STRONG.T": pd.DataFrame(_series(up_strong)),
        "MILD.T": pd.DataFrame(_series(up_mild)),
        "DOWN.T": pd.DataFrame(_series(down)),
    }

    with patch("stock_analyzer.screener._download_history", return_value=fake_data):
        picks = top_swing_picks(["STRONG.T", "MILD.T", "DOWN.T"], n=2)

    assert len(picks) == 2
    assert [p.symbol for p in picks] == sorted(
        [p.symbol for p in picks], key=lambda s: {"STRONG.T": 0, "MILD.T": 1}[s]
    )
    assert picks[0].score >= picks[1].score
