"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import requests
import responses

from src.app.api.model import ApiCode
from src.app.api.session import LOGIN_BASE_URL, NetSession

QR_GENERATE_URL = LOGIN_BASE_URL + "/api/user/qr-code/generate"
QR_POLL_URL = LOGIN_BASE_URL + "/api/user/qr-code/result"
QR_WX_URL = LOGIN_BASE_URL + "/api/user/qr-code/wx_code"


class TestQRGenerate:
    @responses.activate
    def test_success(self):
        responses.get(
            QR_GENERATE_URL,
            json={
                "code": 0,
                "data": {
                    "uniID": "uni-abc-123",
                    "url": "https://login.123pan.com/qr/xxx",
                },
            },
            status=200,
        )
        session = NetSession()
        result = session.qr_generate("loginuuid-test")
        assert result.code == 0
        assert result.api_code_enum == ApiCode.success
        assert result.data["uniID"] == "uni-abc-123"
        assert result.data["url"] == "https://login.123pan.com/qr/xxx"

    @responses.activate
    def test_failure(self):
        responses.get(
            QR_GENERATE_URL,
            json={"code": 500, "message": "server error"},
            status=200,
        )
        session = NetSession()
        result = session.qr_generate("loginuuid-test")
        assert result.code == 500
        assert result.api_code_enum == ApiCode.fail
        assert result.msg == "server error"

    @responses.activate
    def test_network_error(self):
        responses.get(
            QR_GENERATE_URL,
            body=requests.exceptions.ConnectionError("connection refused"),
        )
        session = NetSession()
        result = session.qr_generate("loginuuid-test")
        assert result.code == -1
        assert result.api_code_enum == ApiCode.fail
        assert "connection refused" in result.msg.lower()


class TestQRPoll:
    @responses.activate
    def test_waiting(self):
        responses.get(
            QR_POLL_URL,
            json={"code": 0, "data": {"loginStatus": 0, "scanPlatform": 0}},
            status=200,
        )
        session = NetSession()
        result = session.qr_poll("uni-abc-123", "loginuuid-test")
        assert result.code == 0
        assert result.data["loginStatus"] == 0
        assert "token" not in result.data

    @responses.activate
    def test_scanned_waiting_confirm(self):
        responses.get(
            QR_POLL_URL,
            json={"code": 0, "data": {"loginStatus": 1, "scanPlatform": 0}},
            status=200,
        )
        session = NetSession()
        result = session.qr_poll("uni-abc-123", "loginuuid-test")
        assert result.data["loginStatus"] == 1

    @responses.activate
    def test_app_confirmed(self):
        responses.get(
            QR_POLL_URL,
            json={
                "code": 200,
                "data": {"login_type": 7, "token": "eyJhbGciOiJIUzI1NiJ9.test"},
            },
            status=200,
        )
        session = NetSession()
        result = session.qr_poll("uni-abc-123", "loginuuid-test")
        assert result.code == 0
        assert result.data["loginStatus"] == 3
        assert result.data["scanPlatform"] == 7
        assert result.data["token"] == "eyJhbGciOiJIUzI1NiJ9.test"

    @responses.activate
    def test_wechat_confirmed(self):
        responses.get(
            QR_POLL_URL,
            json={
                "code": 200,
                "data": {"login_type": 4, "token": "wx-jwt-token"},
            },
            status=200,
        )
        session = NetSession()
        result = session.qr_poll("uni-abc-123", "loginuuid-test")
        assert result.data["loginStatus"] == 3
        assert result.data["scanPlatform"] == 4
        assert result.data["token"] == "wx-jwt-token"

    @responses.activate
    def test_expired(self):
        responses.get(
            QR_POLL_URL,
            json={"code": 0, "data": {"loginStatus": 4, "scanPlatform": 0}},
            status=200,
        )
        session = NetSession()
        result = session.qr_poll("uni-abc-123", "loginuuid-test")
        assert result.data["loginStatus"] == 4

    @responses.activate
    def test_error_code(self):
        responses.get(
            QR_POLL_URL,
            json={"code": 500, "message": "poll error"},
            status=200,
        )
        session = NetSession()
        result = session.qr_poll("uni-abc-123", "loginuuid-test")
        assert result.code == 500
        assert result.api_code_enum == ApiCode.fail

    @responses.activate
    def test_network_error(self):
        responses.get(
            QR_POLL_URL,
            body=requests.exceptions.ReadTimeout("timeout"),
        )
        session = NetSession()
        result = session.qr_poll("uni-abc-123", "loginuuid-test")
        assert result.code == -1
        assert result.api_code_enum == ApiCode.fail


class TestQRWxCode:
    @responses.activate
    def test_success(self):
        responses.post(
            QR_WX_URL,
            json={"code": 0, "data": {"wxCode": "wx-code-123"}},
            status=200,
        )
        session = NetSession()
        result = session.qr_wx_code("uni-abc-123", "loginuuid-test")
        assert result.code == 0
        assert result.api_code_enum == ApiCode.success
        assert result.data["wxCode"] == "wx-code-123"

    @responses.activate
    def test_failure(self):
        responses.post(
            QR_WX_URL,
            json={"code": 500, "message": "wx error"},
            status=200,
        )
        session = NetSession()
        result = session.qr_wx_code("uni-abc-123", "loginuuid-test")
        assert result.code == 500
        assert result.api_code_enum == ApiCode.fail


class TestNetSessionClose:
    def test_close(self):
        session = NetSession()
        session.close()
        # 关闭后再次调用不应抛异常
        session.close()
