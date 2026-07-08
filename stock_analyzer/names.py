"""証券コード⇔正式社名の正規マスタ検証 [カテゴリ22]。

銘柄マスタ(data/company_names.json)を正規のソースとして、表示前に「ティッカーと社名の
組み合わせ」を突き合わせる。マスタにあるコードは正式社名で上書きし、取得名がマスタと
食い違う場合は不一致として検出できるようにする(例: 8306 を『三菱USJ』と誤表示)。

マスタに無いコードは検証対象外(yfinance 等の取得名をそのまま使う)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

NAMES_FILE = Path(__file__).parent / "data" / "company_names.json"


def _load(path: Path = NAMES_FILE) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, str)}


OFFICIAL_NAMES = _load()


def official_name(symbol: str) -> str | None:
    """正規マスタにあれば正式社名を返す(無ければ None)。"""
    return OFFICIAL_NAMES.get((symbol or "").upper()) or OFFICIAL_NAMES.get(symbol or "")


def _norm(name: str) -> str:
    text = (name or "").strip().lower()
    for token in ("株式会社", "(株)", "グループ", "ホールディングス", "holdings", "group",
                  "inc.", "inc", "corporation", "corp.", "corp", "co.,ltd", "co., ltd",
                  "ltd.", "ltd", ",", ".", "・", " ", "　"):
        text = text.replace(token, "")
    return re.sub(r"\s+", "", text)


def name_matches(symbol: str, name: str | None) -> bool:
    """与えられた社名が正規マスタと整合するか。マスタに無いコードは常に True(検証対象外)。"""
    official = official_name(symbol)
    if official is None:
        return True
    if not name:
        return False
    return _norm(name) == _norm(official)


def resolve(symbol: str, name: str | None) -> str | None:
    """表示に使う社名。正規マスタがあればそれを優先(誤記を上書き)。"""
    return official_name(symbol) or name
