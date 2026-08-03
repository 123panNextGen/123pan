"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import QRunnable

from ..common.api import Pan123
from ..common.i18n import tr
from ..common.log import get_logger
from .signals import _QRGenerateSignals, _QRPollSignals, _QRVerifySignals

logger = get_logger(__name__)


class QRGenerateTask(QRunnable):
    """异步生成二维码登录会话。"""

    def __init__(self):
        super().__init__()
        self.signals = _QRGenerateSignals()
        self.setAutoDelete(True)

    def run(self):
        pan_temp = None
        try:
            pan_temp = Pan123(anonymous=True)
            data = pan_temp.qr_generate()
            data["_pan_temp"] = pan_temp
            self.signals.finished.emit(data)
        except Exception as e:
            if pan_temp is not None:
                pan_temp.close()
            logger.error("获取二维码失败: %s", e)
            self.signals.error.emit(str(e))


class QRPollTask(QRunnable):
    """异步轮询一次扫码状态。"""

    def __init__(self, pan_temp, uni_id):
        super().__init__()
        self.signals = _QRPollSignals()
        self._pan_temp = pan_temp
        self._uni_id = uni_id
        self.setAutoDelete(True)

    def run(self):
        try:
            result = self._pan_temp.qr_poll(self._uni_id)
            self.signals.result.emit(result)
        except Exception as e:
            logger.error("轮询扫码状态失败: %s", e)
            self.signals.error.emit()


class QRLoginVerifyTask(QRunnable):
    """异步验证扫码登录 token 并获取用户信息。"""

    def __init__(self, token, scan_platform, pan_temp, uni_id):
        super().__init__()
        self.signals = _QRVerifySignals()
        self._token = token
        self._scan_platform = scan_platform
        self._pan_temp = pan_temp
        self._uni_id = uni_id
        self.setAutoDelete(True)

    def run(self):
        try:
            # 微信扫码：即使取得 wxCode 也暂不支持，提示改用 123云盘 App
            if self._scan_platform == 4 and not self._token:
                try:
                    self._pan_temp.qr_wx_code(self._uni_id)
                    logger.info("微信扫码登录获取 wxCode 成功")
                except Exception as e:
                    self.signals.error.emit(str(e))
                    return
                self.signals.error.emit(
                    tr("qr_login.wechat_unsupported", "微信登录暂不支持，请使用 123云盘 App 扫码")
                )
                return

            if not self._token:
                self.signals.error.emit(
                    tr("qr_login.no_credential", "登录失败：未获取到凭证")
                )
                return

            pan = Pan123(
                readfile=False,
                user_name="",
                password="",
                authorization="Bearer " + self._token,
            )
            pan.apply_saved_device()
            result = pan.get_user_info()
            if result.code != 0 or result.data is None:
                self.signals.error.emit(
                    tr("qr_login.verify_failed", "登录验证失败，请重试")
                )
                return
            pan.user_name = result.data.nickname or str(result.data.uid)
            logger.info("扫码登录验证成功: user=%s", pan.user_name)
            self.signals.success.emit(pan)
        except Exception as e:
            logger.error("扫码登录验证异常: %s", e)
            self.signals.error.emit(str(e))
        finally:
            if self._pan_temp is not None:
                self._pan_temp.close()
                self._pan_temp = None
