"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QCoreApplication

from src.app.api.model import ApiCode, ApiReturnModel, CloudUserInfoModel
from src.app.tasks.qr_login_tasks import (
    QRGenerateTask,
    QRLoginVerifyTask,
    QRPollTask,
)

# 信号发射需要 QCoreApplication 实例
_app = QCoreApplication.instance() or QCoreApplication([])


def _ok(data=None):
    return ApiReturnModel(
        code=0, api_code=0, api_code_enum=ApiCode.success, msg="", data=data
    )


def _fail(code=500, msg="error"):
    return ApiReturnModel(
        code=code, api_code=code, api_code_enum=ApiCode.fail, msg=msg
    )


class TestQRGenerateTask:
    def test_success(self):
        mock_pan = MagicMock()
        mock_pan.qr_generate.return_value = {
            "uniID": "uni-1",
            "url": "https://login.123pan.com/qr/1",
        }
        received = {}
        errors = []

        with patch("src.app.tasks.qr_login_tasks.Pan123", return_value=mock_pan):
            task = QRGenerateTask()
            task.signals.finished.connect(lambda data: received.update(data))
            task.signals.error.connect(lambda e: errors.append(e))
            task.run()

        assert received["uniID"] == "uni-1"
        assert received["url"] == "https://login.123pan.com/qr/1"
        assert received["_pan_temp"] is mock_pan
        assert errors == []

    def test_error_closes_pan(self):
        mock_pan = MagicMock()
        mock_pan.qr_generate.side_effect = RuntimeError("boom")
        errors = []

        with patch("src.app.tasks.qr_login_tasks.Pan123", return_value=mock_pan):
            task = QRGenerateTask()
            task.signals.error.connect(lambda e: errors.append(e))
            task.run()

        assert errors == ["boom"]
        mock_pan.close.assert_called_once()


class TestQRPollTask:
    def test_result(self):
        mock_pan = MagicMock()
        mock_pan.qr_poll.return_value = {
            "loginStatus": 3,
            "scanPlatform": 7,
            "token": "jwt",
        }
        results = []

        task = QRPollTask(mock_pan, "uni-1")
        task.signals.result.connect(lambda r: results.append(r))
        task.run()

        assert results == [{"loginStatus": 3, "scanPlatform": 7, "token": "jwt"}]
        mock_pan.qr_poll.assert_called_once_with("uni-1")

    def test_error(self):
        mock_pan = MagicMock()
        mock_pan.qr_poll.side_effect = RuntimeError("boom")
        errors = []

        task = QRPollTask(mock_pan, "uni-1")
        task.signals.error.connect(lambda: errors.append(True))
        task.run()

        assert errors == [True]


class TestQRLoginVerifyTask:
    def test_success(self):
        mock_pan = MagicMock()
        mock_pan.get_user_info.return_value = _ok(
            CloudUserInfoModel(
                uid=123,
                nickname="test-user",
                space_used=0,
                space_total=0,
                space_temp=0,
                file_count=0,
                vip=False,
                vip_expire="",
                vip_level=0,
                head_image="",
                direct_traffic=0,
                share_traffic=0,
                passport=0,
            )
        )
        successes = []

        with patch("src.app.tasks.qr_login_tasks.Pan123", return_value=mock_pan):
            task = QRLoginVerifyTask("jwt-token", 7, MagicMock(), "uni-1")
            task.signals.success.connect(lambda p: successes.append(p))
            task.run()

        assert successes == [mock_pan]
        assert mock_pan.user_name == "test-user"
        mock_pan.apply_saved_device.assert_called_once()
        mock_pan.get_user_info.assert_called_once()

    def test_wechat_unsupported(self):
        mock_pan_temp = MagicMock()
        errors = []

        task = QRLoginVerifyTask("", 4, mock_pan_temp, "uni-1")
        task.signals.error.connect(lambda e: errors.append(e))
        task.run()

        assert any("暂不支持" in e for e in errors)
        mock_pan_temp.qr_wx_code.assert_called_once_with("uni-1")
        mock_pan_temp.close.assert_called_once()

    def test_no_token(self):
        errors = []

        with patch("src.app.tasks.qr_login_tasks.Pan123") as mock_cls:
            task = QRLoginVerifyTask("", 0, MagicMock(), "uni-1")
            task.signals.error.connect(lambda e: errors.append(e))
            task.run()

        assert any("凭证" in e for e in errors)
        mock_cls.assert_not_called()

    def test_verify_failed(self):
        mock_pan = MagicMock()
        mock_pan.get_user_info.return_value = _fail(401, "token 无效")
        errors = []

        with patch("src.app.tasks.qr_login_tasks.Pan123", return_value=mock_pan):
            task = QRLoginVerifyTask("jwt-token", 7, MagicMock(), "uni-1")
            task.signals.error.connect(lambda e: errors.append(e))
            task.run()

        assert any("验证失败" in e for e in errors)

    def test_exception_emits_error(self):
        mock_pan = MagicMock()
        mock_pan.get_user_info.side_effect = RuntimeError("boom")
        errors = []

        with patch("src.app.tasks.qr_login_tasks.Pan123", return_value=mock_pan):
            task = QRLoginVerifyTask("jwt-token", 7, MagicMock(), "uni-1")
            task.signals.error.connect(lambda e: errors.append(e))
            task.run()

        assert errors == ["boom"]
