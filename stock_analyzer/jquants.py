"""J-Quants API クライアント [パイプライン第1段: 財務データ取得]。

日本株の財務諸表・上場情報・日足を取得する。認証は
  1) JQUANTS_REFRESH_TOKEN があればそれを使う(推奨)
  2) 無ければ JQUANTS_MAILADDRESS / JQUANTS_PASSWORD で refresh token を取得
のどちらか。認証情報が無い/取得に失敗した場合は available()=False となり、上位は
既存の yfinance 経路へフォールバックする(通知は落とさない)。

無料プランは12週間の遅延データだが、財務スクリーニングには十分。ネットワーク不通・
レート制限は例外にせず None/空を返し、フォールバックに委ねる。
"""

from __future__ import annotations

import os
from typing import Any

BASE_URL = "https://api.jquants.com/v1"

REFRESH_TOKEN_ENV = "JQUANTS_REFRESH_TOKEN"
MAIL_ENV = "JQUANTS_MAILADDRESS"
PASSWORD_ENV = "JQUANTS_PASSWORD"


class JQuantsClient:
    """薄い J-Quants クライアント。id token を遅延取得してキャッシュする。"""

    def __init__(
        self,
        refresh_token: str | None = None,
        mailaddress: str | None = None,
        password: str | None = None,
        session: Any | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._refresh_token = refresh_token
        self._mail = mailaddress
        self._password = password
        self._timeout = timeout
        self._id_token: str | None = None
        self._session = session  # requests.Session 互換(テストで差し替え可能)

    # ------------------------------------------------------------------ auth
    @classmethod
    def from_env(cls) -> "JQuantsClient | None":
        """環境変数から生成。認証材料が無ければ None(=無効)。"""
        rt = os.environ.get(REFRESH_TOKEN_ENV)
        mail = os.environ.get(MAIL_ENV)
        pw = os.environ.get(PASSWORD_ENV)
        if not rt and not (mail and pw):
            return None
        return cls(refresh_token=rt, mailaddress=mail, password=pw)

    def _sess(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _refresh(self) -> str | None:
        """refresh token を確保する(メール/パスワードからの取得を含む)。"""
        if self._refresh_token:
            return self._refresh_token
        if not (self._mail and self._password):
            return None
        try:
            res = self._sess().post(
                f"{BASE_URL}/token/auth_user",
                json={"mailaddress": self._mail, "password": self._password},
                timeout=self._timeout,
            )
            if res.status_code >= 400:
                return None
            self._refresh_token = res.json().get("refreshToken")
        except Exception:
            return None
        return self._refresh_token

    def id_token(self) -> str | None:
        """id token を取得(キャッシュ)。失敗時は None。"""
        if self._id_token:
            return self._id_token
        rt = self._refresh()
        if not rt:
            return None
        try:
            res = self._sess().post(
                f"{BASE_URL}/token/auth_refresh",
                params={"refreshtoken": rt},
                timeout=self._timeout,
            )
            if res.status_code >= 400:
                return None
            self._id_token = res.json().get("idToken")
        except Exception:
            return None
        return self._id_token

    def available(self) -> bool:
        """認証が通り、API が使える状態か。"""
        return self.id_token() is not None

    # ------------------------------------------------------------------ fetch
    def _get(self, path: str, params: dict | None = None) -> dict | None:
        token = self.id_token()
        if not token:
            return None
        try:
            res = self._sess().get(
                f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
                timeout=self._timeout,
            )
            if res.status_code >= 400:
                return None
            return res.json()
        except Exception:
            return None

    def listed_info(self, code: str | None = None) -> list[dict]:
        """上場銘柄情報(コード⇔社名・業種等)。code 省略で全銘柄。"""
        data = self._get("/listed/info", {"code": code} if code else None)
        return (data or {}).get("info", []) if data else []

    def financial_statements(self, code: str) -> list[dict]:
        """財務諸表(直近から時系列)。空なら []。"""
        data = self._get("/fins/statements", {"code": code})
        return (data or {}).get("statements", []) if data else []

    def daily_quotes(self, code: str, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        """日足(OHLCV)。from/to は 'YYYY-MM-DD'。空なら []。"""
        params = {"code": code}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        data = self._get("/prices/daily_quotes", params)
        return (data or {}).get("daily_quotes", []) if data else []


def closes_from_quotes(quotes: list[dict]) -> tuple[list[float], list[float], list[float], list[float]]:
    """daily_quotes のリストを (closes, highs, lows, volumes) へ整形する。

    分割調整済み列(AdjustmentClose 等)があれば優先し、無ければ素の列を使う。
    """
    def pick(row: dict, *keys):
        for k in keys:
            v = row.get(k)
            if v is not None:
                return v
        return None

    closes, highs, lows, volumes = [], [], [], []
    for row in quotes:
        c = pick(row, "AdjustmentClose", "Close")
        h = pick(row, "AdjustmentHigh", "High")
        low = pick(row, "AdjustmentLow", "Low")
        v = pick(row, "AdjustmentVolume", "Volume")
        if c is None:
            continue
        closes.append(float(c))
        highs.append(float(h) if h is not None else float(c))
        lows.append(float(low) if low is not None else float(c))
        volumes.append(float(v) if v is not None else 0.0)
    return closes, highs, lows, volumes
