from __future__ import annotations

import requests

LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"


def send_line_broadcast(message: str, channel_access_token: str) -> None:
    """Send a text message to all friends of the LINE bot via the Broadcast API."""
    response = requests.post(
        LINE_BROADCAST_URL,
        headers={
            "Authorization": f"Bearer {channel_access_token}",
            "Content-Type": "application/json",
        },
        json={"messages": [{"type": "text", "text": message}]},
        timeout=10,
    )
    response.raise_for_status()
