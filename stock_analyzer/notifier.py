from __future__ import annotations

import requests

LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

# LINE limits: a text message object is max 5000 chars, and one request may
# carry up to 5 message objects. Keep a margin below 5000.
LINE_TEXT_LIMIT = 4900
MESSAGES_PER_REQUEST = 5


def split_message(text: str, limit: int = LINE_TEXT_LIMIT) -> list[str]:
    """Split `text` into chunks no longer than `limit`, breaking at line boundaries."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0

    for line in text.split("\n"):
        # A single over-long line is hard-split so no chunk exceeds the limit.
        while len(line) > limit:
            if current:
                chunks.append("\n".join(current))
                current, length = [], 0
            chunks.append(line[:limit])
            line = line[limit:]

        if current and length + len(line) + 1 > limit:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1

    if current:
        chunks.append("\n".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def send_line_broadcast(message: str, channel_access_token: str) -> None:
    """Send a text message to all friends of the LINE bot via the Broadcast API.

    Long messages are split into multiple text objects (max 5 per request), so the
    notification never exceeds LINE's per-message character limit.
    """
    chunks = split_message(message) or [message]
    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": "application/json",
    }

    for start in range(0, len(chunks), MESSAGES_PER_REQUEST):
        batch = chunks[start : start + MESSAGES_PER_REQUEST]
        response = requests.post(
            LINE_BROADCAST_URL,
            headers=headers,
            json={"messages": [{"type": "text", "text": chunk} for chunk in batch]},
            timeout=10,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"LINE API error {response.status_code}: {response.text}")
