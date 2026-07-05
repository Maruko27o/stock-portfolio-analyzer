from datetime import date, datetime
from zoneinfo import ZoneInfo

from stock_analyzer.judgment_log import LOG_COLUMNS, append_judgments, read_log
from stock_analyzer.summary import HoldingSummary
from stock_analyzer.verify_log import evaluate_entries

TOKYO = ZoneInfo("Asia/Tokyo")


def _summary(**overrides) -> HoldingSummary:
    defaults = dict(
        symbol="7203.T",
        name="トヨタ自動車",
        current_price=3500.0,
        avg_cost=3000.0,
        profit_pct=16.7,
        score=88,
        raw_score=95,
        rating="◎◎",
        action="保有継続",
        take_profit=3700.0,
        stop_loss=3360.0,
        add_price=None,
    )
    defaults.update(overrides)
    return HoldingSummary(**defaults)


def test_append_creates_file_with_header_and_appends(tmp_path):
    path = str(tmp_path / "log.csv")
    now = datetime(2026, 7, 6, 13, 0, tzinfo=TOKYO)

    append_judgments(path, [_summary()], now=now)
    append_judgments(path, [_summary(symbol="1928.T", score=55, rating="○")], now=now)

    rows = read_log(path)
    assert len(rows) == 2
    assert list(rows[0].keys()) == LOG_COLUMNS
    assert rows[0]["symbol"] == "7203.T"
    assert rows[0]["date"] == "2026-07-06"
    assert rows[0]["time_jst"] == "13:00"
    assert rows[1]["symbol"] == "1928.T"
    assert rows[1]["score"] == "55"


def test_append_handles_missing_price_and_profit(tmp_path):
    path = str(tmp_path / "log.csv")
    append_judgments(path, [_summary(current_price=None, profit_pct=None)])
    row = read_log(path)[0]
    assert row["current_price"] == ""
    assert row["profit_pct"] == ""


def test_read_log_missing_file_returns_empty():
    assert read_log("no/such/file.csv") == []


def test_evaluate_entries_buckets_and_computes_change():
    entries = [
        # 10 days old, price 100 → 110 now: +10%, score 85 → 80点以上 bucket
        {"date": "2026-06-26", "symbol": "AAA", "score": "85", "rating": "◎◎", "current_price": "100.0"},
        # too recent → excluded
        {"date": "2026-07-05", "symbol": "AAA", "score": "85", "rating": "◎◎", "current_price": "100.0"},
        # no current price available → excluded
        {"date": "2026-06-26", "symbol": "ZZZ", "score": "30", "rating": "×", "current_price": "100.0"},
    ]
    results = evaluate_entries(entries, {"AAA": 110.0}, min_age_days=5, today=date(2026, 7, 6))
    assert results == [("80点以上", "◎◎", 10.000000000000002)] or results == [
        ("80点以上", "◎◎", 10.0)
    ]
