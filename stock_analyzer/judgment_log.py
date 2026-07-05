"""毎回の分析結果(スコア・判断・価格)をCSVに蓄積する判断ログ。

後から「スコア80以上の銘柄は実際に上がったか」を検証し、シグナルの
重み付けを事実に基づいて調整するための土台。ワークフローが実行のたびに
追記し、リポジトリにコミットして履歴を残す。
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

TOKYO = ZoneInfo("Asia/Tokyo")

LOG_COLUMNS = [
    "date",
    "time_jst",
    "symbol",
    "score",
    "raw_score",
    "rating",
    "action",
    "current_price",
    "profit_pct",
]


def append_judgments(path: str, summaries: list, now: datetime | None = None) -> None:
    """Append one row per holding summary to the CSV log, creating it with a header."""
    now = now or datetime.now(TOKYO)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    is_new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(LOG_COLUMNS)
        for s in summaries:
            writer.writerow(
                [
                    now.date().isoformat(),
                    now.strftime("%H:%M"),
                    s.symbol,
                    s.score,
                    s.raw_score,
                    s.rating,
                    s.action,
                    f"{s.current_price:.2f}" if s.current_price is not None else "",
                    f"{s.profit_pct:.2f}" if s.profit_pct is not None else "",
                ]
            )


def read_log(path: str) -> list[dict]:
    """Read the judgment log as a list of dicts (empty if the file is missing)."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
