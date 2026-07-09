"""強化パイプライン: J-Quants 財務スクリーニング → pandas-ta モメンタム → ML スコアリング。

3段を1本に束ねる。J-Quants 認証が無い/失敗する環境では available()=False を返し、
呼び出し側はこのセクションを丸ごと省く(既存レポートは不変)。

各段は疎結合で単体テスト可能:
  1) fundamental_screen: J-Quants 財務でふるい分け(理由つき)
  2) momentum: pandas-ta(無ければ内製指標)で勢い特徴量
  3) ml_scoring: 財務＋勢いを ML(無ければ決定論)で 0-100 スコア化
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stock_analyzer import jquants, ml_scoring
from stock_analyzer.fundamental_screen import (
    ScreenCriteria,
    evaluate,
    latest_metrics,
    profit_growth,
)
from stock_analyzer.momentum import momentum_features


def to_jquants_code(symbol: str) -> str:
    """'7203.T' → '7203'。既に4桁ならそのまま。"""
    return (symbol or "").upper().replace(".T", "").strip()


@dataclass
class EnhancedPick:
    symbol: str
    code: str
    name: str | None
    ml_score: int
    screen_passed: bool
    screen_reasons: list[str] = field(default_factory=list)
    per: float | None = None
    roe: float | None = None

    def heading(self) -> str:
        return f"{self.name}（{self.symbol}）" if self.name else self.symbol


def available(client=None) -> bool:
    """強化パイプラインが使えるか(J-Quants 認証が通る)。"""
    client = client or jquants.JQuantsClient.from_env()
    return bool(client and client.available())


def run_for_symbols(
    symbols: list[str],
    client=None,
    scorer: ml_scoring.MLScorer | None = None,
    criteria: ScreenCriteria | None = None,
    names: dict[str, str] | None = None,
) -> list[EnhancedPick]:
    """銘柄群を 財務スクリーニング→モメンタム→MLスコア の順で評価し、並べて返す。

    client 未指定なら環境から生成。認証不可なら [](=セクション省略)。
    並びは「スクリーニング通過 > MLスコア降順」。
    """
    client = client or jquants.JQuantsClient.from_env()
    if not (client and client.available()):
        return []
    scorer = scorer or ml_scoring.MLScorer.load()
    criteria = criteria or ScreenCriteria()
    names = names or {}

    picks: list[EnhancedPick] = []
    for symbol in symbols:
        code = to_jquants_code(symbol)
        statements = client.financial_statements(code)
        metrics = latest_metrics(code, statements)
        if metrics is None:
            continue
        growth = profit_growth(statements)
        quotes = client.daily_quotes(code)
        closes, highs, lows, volumes = jquants.closes_from_quotes(quotes)
        price = closes[-1] if closes else None
        mom = momentum_features(closes, highs, lows, volumes) if closes else None
        features = ml_scoring.build_features(metrics, mom, growth)
        ml_score = scorer.score(features)
        screen = evaluate(metrics, criteria, price)
        picks.append(
            EnhancedPick(
                symbol=symbol,
                code=code,
                name=names.get(symbol),
                ml_score=ml_score,
                screen_passed=screen.passed,
                screen_reasons=screen.reasons,
                per=metrics.per(price),
                roe=metrics.roe,
            )
        )

    picks.sort(key=lambda p: (p.screen_passed, p.ml_score), reverse=True)
    return picks


def format_lines(picks: list[EnhancedPick], top_n: int = 5) -> list[str]:
    """CLI/テキスト用に強化パイプラインの結果を整形する。"""
    if not picks:
        return []
    lines = [f"🧪 J-Quants×ML 財務スクリーニング（{ml_scoring.MLScorer.load().backend}）"]
    for p in picks[:top_n]:
        mark = "✅" if p.screen_passed else "⚠️"
        extra = f" ROE{p.roe*100:.0f}%" if p.roe is not None else ""
        extra += f" PER{p.per:.1f}" if p.per is not None else ""
        note = "" if p.screen_passed else "（" + "・".join(p.screen_reasons[:2]) + "）"
        lines.append(f"{mark} {p.heading()} ML{p.ml_score}点{extra}{note}")
    return lines
