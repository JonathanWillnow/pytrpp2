"""Tests for pytr/account.py."""

from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import HTTPError


def _make_http_error(status_code):
    response = MagicMock()
    response.status_code = status_code
    err = HTTPError(response=response)
    return err


class TestLogin429:
    def test_429_exits_with_friendly_message(self, capsys):
        """Regression: HTTP 429 from initiate_weblogin should print a rate-limit message, not a raw traceback."""
        mock_tr = MagicMock()
        mock_tr.resume_websession.return_value = False
        mock_tr.initiate_weblogin.side_effect = _make_http_error(429)

        with patch("pytr.account.TradeRepublicApi", return_value=mock_tr):
            with pytest.raises(SystemExit) as exc_info:
                from pytr.account import login

                login(phone_no="+49123456789", pin="1234")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "429" in captured.out or "rate-limit" in captured.out.lower() or "rate-limit" in captured.err.lower()

    def test_non_429_http_error_exits(self, capsys):
        """Other HTTP errors still cause a clean exit (not a raw traceback)."""
        mock_tr = MagicMock()
        mock_tr.resume_websession.return_value = False
        mock_tr.initiate_weblogin.side_effect = _make_http_error(503)

        with patch("pytr.account.TradeRepublicApi", return_value=mock_tr):
            with pytest.raises(SystemExit) as exc_info:
                from pytr.account import login

                login(phone_no="+49123456789", pin="1234")

        assert exc_info.value.code == 1
