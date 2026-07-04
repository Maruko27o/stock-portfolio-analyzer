from __future__ import annotations

from stock_analyzer.summary import RATING_LABEL, HoldingSummary

# Header background color per rating (dark enough for white text).
RATING_COLOR = {
    "◎◎": "#C0392B",
    "◎": "#E67E22",
    "○": "#B7950B",
    "△": "#7F8C8D",
    "▲": "#2980B9",
    "×": "#34495E",
}
SENTIMENT_COLOR = {"強気": "#C0392B", "弱気": "#2980B9", "中立": "#7F8C8D"}
PROFIT_UP_COLOR = "#C0392B"
PROFIT_DOWN_COLOR = "#2980B9"
MUTED = "#8899A6"

MAX_BUBBLES_PER_CAROUSEL = 10


def _price(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}円"
    return f"{value:,.2f}"


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

    header = _header(
        [
            _text(heading, color="#FFFFFF", weight="bold", size="md"),
            _text(
                f"{summary.rating} {RATING_LABEL[summary.rating]}　{summary.score}点",
                color="#FFFFFF",
                size="sm",
            ),
        ],
        color,
    )

    profit = f"{summary.profit_pct:+.1f}%" if summary.profit_pct is not None else "—"
    profit_color = None
    if summary.profit_pct is not None:
        profit_color = PROFIT_UP_COLOR if summary.profit_pct >= 0 else PROFIT_DOWN_COLOR

    body_contents = [
        _kv_row("現在", _price(summary.current_price)),
        _kv_row("取得", _price(summary.avg_cost)),
        _kv_row("損益", profit, profit_color),
        _sep(),
        _text("■ 判断", weight="bold", size="sm"),
        _text(summary.action, size="sm", weight="bold", color=color),
        _kv_row("第一目標", _price(summary.take_profit)),
        _kv_row("損切", _price(summary.stop_loss)),
    ]
    if summary.add_price is not None:
        body_contents.append(_kv_row("押し目買い", _price(summary.add_price)))

    body_contents.append(_sep())
    body_contents.append(_text("■ 判断理由", weight="bold", size="sm"))
    if summary.reasons:
        body_contents.extend(_text(f"・{reason}", size="sm") for reason in summary.reasons)
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


def market_bubble(sentiment: str, snapshot: dict[str, tuple[float | None, float | None]]) -> dict:
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
        change_text = f"{change:+.2f}%" if change is not None else "—"
        change_color = None
        if change is not None:
            change_color = PROFIT_UP_COLOR if change >= 0 else PROFIT_DOWN_COLOR
        rows.append(_kv_row(name, change_text, change_color))

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
