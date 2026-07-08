"""表示の共通ルール(金額フォーマット・資金配分の表示可否)を一元管理する。

銘柄ごとに表示処理が分岐して不統一・不整合が生じるのを防ぐため、全出力箇所が
ここの共通関数を経由する。個別のテンプレート側で直接フォーマットしない。

- format_yen: 金額系フィールドの唯一のフォーマッタ(円・整数・カンマ区切り) [カテゴリ15]
- should_show_allocation: 資金配分%を表示してよいアクションかの唯一の判定 [カテゴリ13]
"""

from __future__ import annotations

# 資金配分(新規資金の配分)を表示してよいアクション = 買い方向のみ。
# 保有・様子見・押し目待ち・売却系では新規配分を出さない(非購入系は空欄に統一)。
ALLOCATION_ACTIONS = {"強く買い増し", "買い増し"}


def format_yen(value: float | None, dash: str = "—") -> str:
    """金額の唯一の表示フォーマット: 円・整数・カンマ区切り [カテゴリ15]。

    銘柄や価格帯によって小数点桁数が変わる不統一を無くす。None は dash。
    """
    if value is None:
        return dash
    return f"{round(value):,}円"


def should_show_allocation(action: str | None, alloc_pct: float | None) -> bool:
    """資金配分%を表示してよいか(唯一の判定) [カテゴリ13]。

    買い方向アクションで、かつ配分が実際に付いている(>0)場合のみ True。
    非購入系アクション(保有/様子見/押し目待ち/売却系)は常に False。
    """
    if action not in ALLOCATION_ACTIONS:
        return False
    return alloc_pct is not None and alloc_pct > 0
