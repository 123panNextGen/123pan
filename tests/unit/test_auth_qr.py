"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from unittest.mock import MagicMock

import pytest

from src.app.api.model import ApiCode, ApiReturnModel
from src.app.common.config import ConfigManager
from src.app.service.auth_service import AuthService


def _ok(data):
    return ApiReturnModel(
        code=0, api_code=0, api_code_enum=ApiCode.success, msg="", data=data
    )


def _fail(code=500, msg="error"):
    return ApiReturnModel(
        code=code, api_code=code, api_code_enum=ApiCode.fail, msg=msg
    )


class TestAuthQR:
    def _make(self):
        session = MagicMock()
        auth = AuthService(session)
        return auth, session

    def test_qr_generate_success(self):
        auth, session = self._make()
        session.qr_generate.return_value = _ok(
            {"uniID": "uni-1", "url": "https://login.123pan.com/qr/1"}
        )
        result = auth.qr_generate()
        assert result["uniID"] == "uni-1"
        assert result["url"] == "https://login.123pan.com/qr/1"
        session.qr_generate.assert_called_once_with(auth.loginuuid)

    def test_qr_generate_failure_raises(self):
        auth, session = self._make()
        session.qr_generate.return_value = _fail(500, "server error")
        with pytest.raises(RuntimeError):
            auth.qr_generate()

    def test_qr_poll_success(self):
        auth, session = self._make()
        session.qr_poll.return_value = _ok(
            {"loginStatus": 0, "scanPlatform": 0}
        )
        result = auth.qr_poll("uni-1")
        assert result["loginStatus"] == 0
        session.qr_poll.assert_called_once_with("uni-1", auth.loginuuid)

    def test_qr_poll_failure_raises(self):
        auth, session = self._make()
        session.qr_poll.return_value = _fail(500, "poll error")
        with pytest.raises(RuntimeError):
            auth.qr_poll("uni-1")

    def test_qr_wx_code_success(self):
        auth, session = self._make()
        session.qr_wx_code.return_value = _ok({"wxCode": "wx-code-1"})
        result = auth.qr_wx_code("uni-1")
        assert result == "wx-code-1"
        session.qr_wx_code.assert_called_once_with("uni-1", auth.loginuuid)

    def test_qr_wx_code_failure_raises(self):
        auth, session = self._make()
        session.qr_wx_code.return_value = _fail(500, "wx error")
        with pytest.raises(RuntimeError):
            auth.qr_wx_code("uni-1")


class TestAuthLoadSavedDevice:
    def test_load_saved_device(self, tmp_db):
        ConfigManager.save_account(
            "test-user",
            {
                "userName": "test-user",
                "passWord": "",
                "authorization": "",
                "deviceType": "android_tablet",
                "osVersion": "Android 13",
                "loginuuid": "saved-uuid",
            },
        )
        auth = AuthService(MagicMock())
        auth.load_saved_device()
        assert auth.devicetype == "android_tablet"
        assert auth.osversion == "Android 13"
        assert auth.loginuuid == "saved-uuid"

    def test_load_saved_device_no_account(self, tmp_db):
        auth = AuthService(MagicMock())
        original = (auth.devicetype, auth.osversion, auth.loginuuid)
        auth.load_saved_device()
        assert (auth.devicetype, auth.osversion, auth.loginuuid) == original
