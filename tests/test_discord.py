from unittest.mock import MagicMock, patch

import pytest

from stock_analyzer.discord import (
    failed_embed,
    holding_embed,
    market_embed,
    send_discord,
    swing_embed,
)
from stock_analyzer.summary import HoldingSummary


def _summary(**overrides) -> HoldingSummary:
    defaults = dict(
        symbol="7203.T",
        name="トヨタ自動車",
        current_price=3500.0,
        avg_cost=3000.0,
        profit_pct=16.7,
        score=88,
        raw_score=95,
        rating="◎◎",
        action="保有継続",
        take_profit=3700.0,
        stop_loss=3360.0,
        add_price=3400.0,
        reasons=["25日線を上抜け"],
        risks=["決算まであと3日"],
    )
    defaults.update(overrides)
    return HoldingSummary(**defaults)


def test_holding_embed_has_color_and_title():
    embed = holding_embed(_summary())
    assert "7203.T トヨタ自動車" in embed["title"]
    assert isinstance(embed["color"], int)
    assert "判断" in embed["description"]
    assert "注意点" in embed["description"]


def test_holding_embed_hides_cost_for_watch_only_symbols():
    embed = holding_embed(_summary(avg_cost=0.0, profit_pct=None))
    assert "現在" in embed["description"]
    assert "取得" not in embed["description"]
    assert "損益" not in embed["description"]


def test_market_embed_lists_changes():
    embed = market_embed("強気", {"日経平均": (39000.0, 1.2)})
    assert "強気" in embed["title"]
    assert "日経平均" in embed["description"]


def test_swing_embed_numbers_picks_and_has_disclaimer():
    embed = swing_embed(
        [{"heading": "1721.T A", "score": 100, "current_price": 5000.0, "reasons": ["r"]}]
    )
    assert "1. 1721.T A" in embed["description"]
    assert "保証するものではありません" in embed["description"]


def test_failed_embed_lists_symbols():
    assert "AAA, BBB" in failed_embed(["AAA", "BBB"])["description"]


def test_send_discord_posts_embeds_in_batches_of_ten():
    embeds = [{"title": str(i)} for i in range(23)]
    with patch("stock_analyzer.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        send_discord("https://hook", embeds)

    assert mock_post.call_count == 3  # 10 + 10 + 3
    for _, kwargs in mock_post.call_args_list:
        assert len(kwargs["json"]["embeds"]) <= 10


def test_send_discord_raises_on_error():
    with patch("stock_analyzer.discord.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text="bad")
        with pytest.raises(RuntimeError, match="Discord webhook error 400"):
            send_discord("https://hook", [{"title": "x"}])
