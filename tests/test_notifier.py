from unittest.mock import MagicMock, patch

import pytest

from stock_analyzer.notifier import send_line_broadcast, split_message


def test_send_line_broadcast_posts_expected_payload():
    with patch("stock_analyzer.notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)

        send_line_broadcast("test message", "dummy-token")

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer dummy-token"
    assert kwargs["json"]["messages"][0]["text"] == "test message"


def test_split_message_breaks_at_line_boundaries_under_limit():
    text = "\n".join(["line"] * 10)  # each "line" = 4 chars + newline
    chunks = split_message(text, limit=12)
    assert all(len(c) <= 12 for c in chunks)
    assert "\n".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_split_message_hard_splits_an_overlong_line():
    chunks = split_message("x" * 25, limit=10)
    assert chunks == ["x" * 10, "x" * 10, "x" * 5]


def test_send_line_broadcast_batches_many_chunks_into_multiple_requests():
    # 6 lines each just under the limit -> 6 separate chunks -> 2 requests (5 + 1).
    long_text = "\n".join(["a" * 4800 for _ in range(6)])
    with patch("stock_analyzer.notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)

        send_line_broadcast(long_text, "dummy-token")

    # More than 5 chunks means more than one request, each with <= 5 message objects.
    assert mock_post.call_count >= 2
    for _, kwargs in mock_post.call_args_list:
        assert len(kwargs["json"]["messages"]) <= 5


def test_send_line_broadcast_raises_with_response_body_on_error():
    with patch("stock_analyzer.notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text='{"message":"bad"}')

        with pytest.raises(RuntimeError, match="LINE API error 400.*bad"):
            send_line_broadcast("hi", "dummy-token")
