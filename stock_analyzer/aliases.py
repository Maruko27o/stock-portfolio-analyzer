"""同一企業の別ティッカー正規化 [カテゴリ6]。

同じ会社が国内本体(例 7203.T)と米ADR/OTC(例 TM)で別コードとして二重に並び、
スコアリング・ランキング・資金配分で二重計上されるのを防ぐ。

data/ticker_aliases.json の紐付け表を第一の根拠に、無ければ銘柄名(正規化)を
フォールバックの企業キーにする。統合できない場合でも、名寄せキーが一致した
ペアは consistency 側で「同一企業のADR/OTC」として警告できる。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ALIAS_FILE = Path(__file__).parent / "data" / "ticker_aliases.json"


def _load_aliases(path: Path = ALIAS_FILE) -> dict[str, str]:
    """{ティッカー(大文字): 正規企業キー} を読む。壊れていれば空(既定動作)。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(k).upper(): str(v).strip().lower()
        for k, v in raw.items()
        if not str(k).startswith("_") and isinstance(v, str)
    }


TICKER_ALIASES = _load_aliases()


def _normalize_name(name: str) -> str:
    """企業名の表記ゆれを吸収(空白・法人格・記号を落として小文字化)。"""
    text = name.strip().lower()
    for token in ("株式会社", "(株)", "co.,ltd", "co., ltd", "corporation", "corp.", "corp",
                  "inc.", "inc", "ltd.", "ltd", "adr", "の"):
        text = text.replace(token, "")
    return re.sub(r"[\s\.,・/()（）]+", "", text)


def company_key(symbol: str, name: str | None = None) -> str:
    """同一企業をまとめる正規キー。エイリアス表を最優先、無ければ銘柄名→コード。"""
    alias = TICKER_ALIASES.get((symbol or "").upper())
    if alias:
        return alias
    if name and name.strip():
        return _normalize_name(name)
    return (symbol or "").strip().lower()


def is_alias_pair(symbol_a: str, symbol_b: str) -> bool:
    """2つのティッカーがエイリアス表で同一企業に紐付いていれば True。"""
    a = TICKER_ALIASES.get((symbol_a or "").upper())
    b = TICKER_ALIASES.get((symbol_b or "").upper())
    return a is not None and a == b
