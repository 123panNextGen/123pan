"""测试 Pan123 session 重试机制配置"""
from unittest.mock import patch, MagicMock

import pytest
import requests
from requests.adapters import HTTPAdapter

from src.app.common.api import Pan123


def _make_mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {"code": 0, "message": "success"}
    resp.headers = {}
    return resp


class TestSessionRetryConfig:
    """验证 Pan123.__init__ 创建的 session 带有正确的 Retry 配置"""

    def _create_pan_with_config(self, retry_max=3, backoff=0.5):
        db = MagicMock()
        db.get_config.side_effect = lambda k, d=None: {
                "retryMaxAttempts": retry_max, "retryBackoffFactor": backoff,
            }.get(k, d)
        with patch("src.app.common.api.Database.instance", return_value=db):
            with patch("requests.Session.get") as mock_get, \
                 patch("requests.Session.post") as mock_post:
                mock_get.return_value = _make_mock_response(200, {
                    "code": 0, "data": {"Total": 0, "InfoList": []}
                })
                mock_post.return_value = _make_mock_response(200, {
                    "code": 200, "data": {"token": "t"}, "message": "ok"
                })
                mock_post.return_value.headers = {"Set-Cookie": ""}

                p = Pan123(readfile=False, user_name="u", password="p")
                return p

    def test_session_has_retry_adapter(self):
        p = self._create_pan_with_config()
        adapter = p.session.get_adapter("https://www.123pan.com")
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == 3

    def test_session_retry_config_custom(self):
        """urllib3 Retry 固定为 3，不受 retryMaxAttempts 影响"""
        p = self._create_pan_with_config(retry_max=5, backoff=1.0)
        adapter = p.session.get_adapter("https://www.123pan.com")
        assert adapter.max_retries.total == 3

    def test_session_retry_zero_clamped_to_one(self):
        """urllib3 Retry 固定为 3，不受 retryMaxAttempts 影响"""
        p = self._create_pan_with_config(retry_max=0)
        adapter = p.session.get_adapter("https://www.123pan.com")
        assert adapter.max_retries.total == 3

    def test_session_retry_status_forcelist(self):
        """5xx 触发重试"""
        p = self._create_pan_with_config()
        adapter = p.session.get_adapter("https://www.123pan.com")
        forcelist = adapter.max_retries.status_forcelist
        assert set(forcelist) == {500, 502, 503, 504}

    def test_session_retry_allowed_methods(self):
        p = self._create_pan_with_config()
        adapter = p.session.get_adapter("https://www.123pan.com")
        methods = adapter.max_retries.allowed_methods
        for m in ("GET", "POST", "PUT", "HEAD"):
            assert m in methods

    def test_session_retry_raise_on_status_false(self):
        p = self._create_pan_with_config()
        adapter = p.session.get_adapter("https://www.123pan.com")
        assert adapter.max_retries.raise_on_status is False

    def test_both_http_https_mounted(self):
        p = self._create_pan_with_config()
        assert isinstance(p.session.get_adapter("https://x.com"), HTTPAdapter)
        assert isinstance(p.session.get_adapter("http://x.com"), HTTPAdapter)
