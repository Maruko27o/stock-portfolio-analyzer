"""判断ログの答え合わせ: 記録時点のスコアとその後の株価変動を突き合わせる。

使い方:
    python -m stock_analyzer.verify_log [--log data/judgment_log.csv] [--min-days 5]

「スコア帯ごと・評価ごとに、記録時点から現在までの平均騰落率」を表示する。
スコアが機能していれば高スコア帯ほど平均騰落率が高くなるはずで、
そうなっていなければ重み付けを見直す根拠になる。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from zoneinfo import ZoneInfo

import yfinance as yf

from stock_analyzer.judgment_log import read_log

TOKYO = ZoneInfo("Asia/Tokyo")

SCORE_BUCKETS = [(80, 101, "80点以上"), (60, 80, "60〜79点"), (40, 60, "40〜59点"), (0, 40, "40点未満")]


def _fetch_current_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch the latest close for each symbol in one bulk request."""
    if not symbols:
        return {}
    data = yf.download(symbols, period="5d", group_by="ticker", auto_adjust=True, progress=False)
    prices: dict[str, float] = {}
    for symbol in symbols:
        try:
            closes = data[symbol]["Close"].dropna()
            if len(closes):
                prices[symbol] = float(closes.iloc[-1])
        except (KeyError, TypeError):
            continue
    return prices


def evaluate_entries(entries: list[dict], prices: dict[str, float], min_age_days: int, today: date):
    """Return per-entry (bucket_label, rating, change_pct) for old-enough, priceable rows."""
    results = []
    for row in entries:
        try:
            logged = date.fromisoformat(row["date"])
            score = int(row["score"])
            logged_price = float(row["current_price"])
        except (KeyError, ValueError):
            continue
        if (today - logged).days < min_age_days or logged_price <= 0:
            continue
        current = prices.get(row["symbol"])
        if current is None:
            continue
        change_pct = (current - logged_price) / logged_price * 100
        bucket = next(label for low, high, label in SCORE_BUCKETS if low <= score < high)
        results.append((bucket, row.get("rating", "?"), change_pct))
    return results


def _print_group(title: str, groups: dict[str, list[float]]) -> None:
    print(f"\n■ {title}")
    if not groups:
        print("  (対象データなし)")
        return
    for label, changes in groups.items():
        avg = sum(changes) / len(changes)
        wins = sum(1 for c in changes if c > 0)
        print(f"  {label}: 平均{avg:+.2f}% / 勝率{wins / len(changes) * 100:.0f}% ({len(changes)}件)")


def main() -> None:
    parser = argparse.ArgumentParser(description="判断ログとその後の株価を突き合わせて検証します")
    parser.add_argument("--log", default="data/judgment_log.csv", help="判断ログCSVのパス")
    parser.add_argument(
        "--min-days", type=int, default=5, help="この日数以上経過した記録だけを評価する(既定: 5)"
    )
    args = parser.parse_args()

    entries = read_log(args.log)
    if not entries:
        print(f"判断ログがまだありません: {args.log}")
        print("(定時実行が走るたびに自動で蓄積されます)")
        return

    today = datetime.now(TOKYO).date()
    symbols = sorted({row["symbol"] for row in entries if row.get("symbol")})
    prices = _fetch_current_prices(symbols)
    results = evaluate_entries(entries, prices, args.min_days, today)

    print(f"判断ログ検証: 全{len(entries)}件中、{args.min_days}日以上経過した{len(results)}件を評価")
    if not results:
        print("評価できる記録がまだありません。日数が経ってから再実行してください。")
        return

    by_bucket: dict[str, list[float]] = {}
    by_rating: dict[str, list[float]] = {}
    for bucket, rating, change in results:
        by_bucket.setdefault(bucket, []).append(change)
        by_rating.setdefault(rating, []).append(change)

    ordered_buckets = {
        label: by_bucket[label] for _, _, label in SCORE_BUCKETS if label in by_bucket
    }
    _print_group("スコア帯別(記録時→現在の騰落率)", ordered_buckets)
    _print_group("評価別", by_rating)
    print(
        "\n※高スコア帯ほど平均騰落率が高ければスコアは機能しています。"
        "逆転している場合は重み付けの見直し材料になります。"
    )


if __name__ == "__main__":
    main()
