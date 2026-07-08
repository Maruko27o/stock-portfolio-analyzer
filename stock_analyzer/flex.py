from __future__ import annotations

from stock_analyzer.market import vix_regime_label
from stock_analyzer.summary import (
    HoldingSummary,
    format_as_of,
    format_dividend_yield,
    format_ex_dividend,
)

# Header background color per rating (dark enough for white text).
RATING_COLOR = {
    "◎◎": "#C0392B",
    "◎": "#E67E22",
    "○": "#B7950B",
    "△": "#7F8C8D",
    "▲": "#2980B9",
    "×": "#34495E",
}
SENTIMENT_COLOR = {
    "強気": "#C0392B",
    "やや強気": "#E67E22",
    "弱気": "#2980B9",
    "やや弱気": "#5DADE2",
    "中立": "#7F8C8D",
}
PROFIT_UP_COLOR = "#C0392B"
PROFIT_DOWN_COLOR = "#2980B9"
MUTED = "#8899A6"

MAX_BUBBLES_PER_CAROUSEL = 10


def _price(value: float | None) -> str:
    # 金額表示は共通フォーマッタに一本化(円・整数・カンマ) [カテゴリ15]。
    from stock_analyzer.display import format_yen

    return format_yen(value)


def _text(text: str, **kwargs) -> dict:
    return {"type": "text", "text": text, "wrap": True, **kwargs}


def _sep() -> dict:
    return {"type": "separator", "margin": "md"}


def _kv_row(label: str, value: str, value_color: str | None = None) -> dict:
    value_comp = _text(value, size="sm", align="end", flex=3)
    if value_color:
        value_comp["color"] = value_color
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [_text(label, size="sm", color=MUTED, flex=2), value_comp],
    }


def _header(title_lines: list[dict], color: str) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": color,
        "paddingAll": "12px",
        "contents": title_lines,
    }


def holding_bubble(summary: HoldingSummary) -> dict:
    heading = f"{summary.symbol} {summary.name}" if summary.name else summary.symbol
    color = RATING_COLOR[summary.rating]

    # 点数表示はバックテストで判別力が無いと確認されたため出さず、
    # ヘッダーには具体的な行動(判断)を出す。
    header = _header(
        [
            _text(heading, color="#FFFFFF", weight="bold", size="md"),
            _text(summary.action, color="#FFFFFF", size="sm"),
        ],
        color,
    )

    profit = f"{summary.profit_pct:+.1f}%" if summary.profit_pct is not None else "—"
    profit_color = None
    if summary.profit_pct is not None:
        profit_color = PROFIT_UP_COLOR if summary.profit_pct >= 0 else PROFIT_DOWN_COLOR

    body_contents = [_kv_row("現在", _price(summary.current_price))]
    if summary.avg_cost > 0:
        # Watch-only symbols (on-demand analysis) have no position, so skip 取得/損益.
        body_contents.append(_kv_row("取得", _price(summary.avg_cost)))
        body_contents.append(_kv_row("損益", profit, profit_color))
    body_contents.append(
        _kv_row("配当", format_dividend_yield(summary.dividend_yield, summary.yield_on_cost))
    )
    body_contents.append(
        _kv_row(
            "権利落ち",
            format_ex_dividend(
                summary.ex_dividend_date, summary.days_to_ex_dividend, summary.ex_dividend_estimated
            ),
        )
    )
    body_contents.append(
        _text("※権利落ち日まで保有すると配当を受取。売却は権利後が基本", size="xxs", color=MUTED)
    )
    body_contents += [
        _sep(),
        _text("■ 判断", weight="bold", size="sm"),
        _text(summary.action, size="sm", weight="bold", color=color),
        _kv_row("損切", _price(summary.stop_loss)),
        _kv_row("第一目標", _price(summary.take_profit)),
    ]
    if summary.add_price is not None:
        body_contents.append(_kv_row("押し目買い", _price(summary.add_price)))
    body_contents.append(
        _text("※損切はこの銘柄の値動き幅(ATR)基準。終値で割れたら売却検討", size="xxs", color=MUTED)
    )

    if summary.strategy_stats:
        st = summary.strategy_stats
        scope = f"({st['regime']}相場)" if st.get("regime") else ""
        body_contents.append(_sep())
        body_contents.append(
            _text(f"■ 戦略シグナル: {st['strategy']}{scope}", weight="bold", size="sm")
        )
        body_contents.append(_kv_row("検証勝率", f"{st['win_rate']:.1f}%"))
        st_color = PROFIT_UP_COLOR if st["expectancy"] >= 0 else PROFIT_DOWN_COLOR
        body_contents.append(
            _kv_row("検証期待値", f"{st['expectancy']:+.1f}%({st['count']:,}件)", st_color)
        )
        body_contents.append(
            _text(
                "※銘柄の優劣でなく「買い時の型」の検知。下落・横ばい相場で特に有効",
                size="xxs",
                color=MUTED,
            )
        )

    if summary.horizons and summary.current_price is not None:
        price = summary.current_price
        detail = summary.horizons[-1]
        if "p25" in detail:
            rng = lambda lo, hi: (  # noqa: E731
                f"{_price(price * (1 + detail[lo] / 100))}〜{_price(price * (1 + detail[hi] / 100))}"
            )
            body_contents.append(_sep())
            body_contents.append(
                _text(
                    f"■ {detail['days']}日後の見通し(信頼度{detail['stars']})",
                    weight="bold",
                    size="sm",
                )
            )
            body_contents.append(
                _kv_row(
                    "期待価格",
                    f"{_price(price * (1 + detail['expectancy'] / 100))}({detail['expectancy']:+.1f}%)",
                )
            )
            body_contents.append(_kv_row("50%レンジ", rng("p25", "p75")))
            body_contents.append(_kv_row("80%レンジ", rng("p10", "p90")))
            body_contents.append(_kv_row("+5%以上の確率", f"{detail['prob_up_5']:.0f}%"))
            body_contents.append(
                _kv_row("-5%以下の確率", f"{detail['prob_down_5']:.0f}%", PROFIT_DOWN_COLOR)
            )
            body_contents.append(
                _text(
                    "※期待値の1点よりブレ幅(レンジ)を重視。レンジ外もあり得る",
                    size="xxs",
                    color=MUTED,
                )
            )

    body_contents.append(_sep())
    body_contents.append(_text("■ 判断理由", weight="bold", size="sm"))
    if summary.reasons:
        body_contents.extend(_text(f"・{reason}", size="sm") for reason in summary.reasons[:3])
    else:
        body_contents.append(_text("・明確なシグナルなし", size="sm", color=MUTED))

    if summary.risks:
        body_contents.append(_sep())
        body_contents.append(_text("■ 注意点", weight="bold", size="sm", color="#B7950B"))
        body_contents.extend(_text(f"・{risk}", size="sm", color="#B7950B") for risk in summary.risks)

    return {
        "type": "bubble",
        "size": "mega",
        "header": header,
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": body_contents},
    }


def market_bubble(
    sentiment: str,
    snapshot: dict[str, tuple[float | None, float | None]],
    as_of=None,
) -> dict:
    color = SENTIMENT_COLOR.get(sentiment, MUTED)
    header = _header(
        [
            _text("📊 本日の市場", color="#FFFFFF", size="sm"),
            _text(sentiment, color="#FFFFFF", weight="bold", size="xl"),
        ],
        color,
    )

    rows = []
    for name, (price, change) in snapshot.items():
        if name == "VIX":
            # For VIX the level (risk regime) matters more than the daily change.
            vix_text = f"{price:.1f}({vix_regime_label(price)})" if price is not None else "—"
            rows.append(_kv_row(name, vix_text))
            continue
        change_text = f"{change:+.2f}%" if change is not None else "—"
        change_color = None
        if change is not None:
            change_color = PROFIT_UP_COLOR if change >= 0 else PROFIT_DOWN_COLOR
        rows.append(_kv_row(name, change_text, change_color))

    as_of_note = format_as_of(as_of)
    if as_of_note:
        rows.append(_sep())
        rows.append(_text(as_of_note, size="xxs", color=MUTED))

    return {
        "type": "bubble",
        "size": "mega",
        "header": header,
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows},
    }


def swing_bubble(picks: list[dict]) -> dict:
    """picks: list of {'heading': str, 'score': int, 'current_price': float|None, 'reasons': list[str]}."""
    header = _header(
        [
            _text("🔎 注目候補", color="#FFFFFF", size="sm"),
            _text("スイング TOP3", color="#FFFFFF", weight="bold", size="lg"),
        ],
        "#16A085",
    )

    body_contents: list[dict] = []
    for index, pick in enumerate(picks, start=1):
        if index > 1:
            body_contents.append(_sep())
        body_contents.append(
            _text(f"{index}. {pick['heading']}　{pick['score']}点", weight="bold", size="sm")
        )
        body_contents.append(_kv_row("現在", _price(pick["current_price"])))
        body_contents.extend(_text(f"・{reason}", size="sm") for reason in pick["reasons"])

    body_contents.append(_sep())
    body_contents.append(
        _text(
            "※保有していない銘柄です。機械的スコアによる候補で、値上がりを保証するものではありません。",
            size="xxs",
            color=MUTED,
        )
    )

    return {
        "type": "bubble",
        "size": "mega",
        "header": header,
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": body_contents},
    }


def to_flex_messages(bubbles: list[dict], alt_text: str) -> list[dict]:
    """Pack bubbles into carousels (max 10 each) as LINE flex message objects."""
    messages = []
    for start in range(0, len(bubbles), MAX_BUBBLES_PER_CAROUSEL):
        chunk = bubbles[start : start + MAX_BUBBLES_PER_CAROUSEL]
        messages.append(
            {
                "type": "flex",
                "altText": alt_text,
                "contents": {"type": "carousel", "contents": chunk},
            }
        )
    return messages
