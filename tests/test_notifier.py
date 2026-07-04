from unittest.mock import MagicMock, patch

from stock_analyzer.notifier import send_line_broadcast


def test_send_line_broadcast_posts_expected_payload():
    with patch("stock_analyzer.notifier.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)

        send_line_broadcast("test message", "dummy-token")

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer dummy-token"
    assert kwargs["json"]["messages"][0]["text"] == "test message"
