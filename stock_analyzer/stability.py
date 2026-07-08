"""スコアの再現性・安定性の監査 [カテゴリ4]。

数時間〜1日で主要ファンダ入力が実質不変なのに総合スコアが大きく動き、アクションが
真逆になる問題に対応する。どのサブスコア(テクニカル/ファンダ/需給/市場/バリュエーション)
の変化でスコアが動いたかを内部監査ログとして保持し、ファンダが動いていないのに総合が
一定幅以上動いたら「短期シグナル急変あり、要目視確認」を自動付与する。

方針(ユーザー確認済み): サブスコアを機械的にクリップして急変自体を握り潰すのではなく、
急変を検知して注意書き＋監査ログで可視化する(本当の急変も潰さない)。

ログは判断ログ(judgment_log)と同様、CSV に追記し、GitHub Actions で銘柄別に
前回値と突き合わせられるようにする(環境にファイルが無ければ静かに無効化)。
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from stock_analyzer import config

# ファンダ入力が「実質不変」とみなすサブスコア変動の許容幅(この幅以内なら不変扱い)。
FUND_STABLE_DELTA = 2
# 監査ログに残すサブスコアのカテゴリ順(列固定)。
SUBSCORE_COLUMNS = ["technical", "fundamental", "supply_demand", "market", "valuation", "dividend"]
CAVEAT = "短期シグナル急変あり、要目視確認"


@dataclass
class StabilityAlert:
    symbol: str
    prev_total: int
    cur_total: int
    note: str


@dataclass
class SubscoreRecord:
    symbol: str
    total: int
    subscores: dict


def flag_jump(prev_total: int, prev_fund: int, cur_total: int, cur_fund: int) -> str | None:
    """総合がしきい値以上動き、かつファンダ入力が実質不変なら注意書きを返す。

    「ファンダは動いていないのに総合が急変」= 短期(テクニカル/需給)シグナルの振れが主因。
    """
    if abs(cur_total - prev_total) < config.SCORE_JUMP_ALERT_PT:
        return None
    if abs(cur_fund - prev_fund) > FUND_STABLE_DELTA:
        return None  # ファンダも動いている=急変とはみなさない(正当なスコア変化)
    return f"{CAVEAT}(総合{prev_total}→{cur_total}点／ファンダ変化{cur_fund - prev_fund:+d})"


def check_entries(
    entries: list[SubscoreRecord], prev_map: dict[str, SubscoreRecord]
) -> dict[str, str]:
    """今回のサブスコアを前回値と突き合わせ、{symbol: 注意書き} を返す。"""
    alerts: dict[str, str] = {}
    for cur in entries:
        prev = prev_map.get(cur.symbol)
        if prev is None:
            continue
        note = flag_jump(
            prev.total,
            int(prev.subscores.get("fundamental", 0)),
            cur.total,
            int(cur.subscores.get("fundamental", 0)),
        )
        if note:
            alerts[cur.symbol] = note
    return alerts


# ---------------------------------------------------------------------------
# 監査ログの読み書き(CSV)。ファイルが無ければ空=無効化(通知は落とさない)。
# ---------------------------------------------------------------------------
def read_last_by_symbol(path: str | os.PathLike) -> dict[str, SubscoreRecord]:
    """銘柄ごとの最終行(直近の総合・サブスコア)を返す。"""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, SubscoreRecord] = {}
    try:
        with p.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                sub = {c: int(row.get(c, 0) or 0) for c in SUBSCORE_COLUMNS}
                out[row["symbol"]] = SubscoreRecord(row["symbol"], int(row.get("total", 0) or 0), sub)
    except Exception:
        return {}
    return out


def append_records(
    path: str | os.PathLike, entries: list[SubscoreRecord], as_of: date | None = None
) -> None:
    """今回のサブスコアを監査ログへ追記する(ヘッダーが無ければ作成)。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = (as_of or date.today()).isoformat()
    write_header = not p.exists() or p.stat().st_size == 0
    with p.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["date", "symbol", "total", *SUBSCORE_COLUMNS])
        for e in entries:
            writer.writerow(
                [stamp, e.symbol, e.total, *[int(e.subscores.get(c, 0)) for c in SUBSCORE_COLUMNS]]
            )
