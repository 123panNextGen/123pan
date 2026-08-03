"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import QObject, pyqtSignal


class _LoadListSignals(QObject):
    finished = pyqtSignal(list, str)


class _OpFinishedSignals(QObject):
    finished = pyqtSignal(bool, str, str, str, list, list)


class _QRGenerateSignals(QObject):
    finished = pyqtSignal(dict)  # 二维码生成成功（uniID/url/_pan_temp）
    error = pyqtSignal(str)      # 失败原因


class _QRPollSignals(QObject):
    result = pyqtSignal(dict)    # 轮询结果 {loginStatus, scanPlatform, token?}
    error = pyqtSignal()         # 网络错误


class _QRVerifySignals(QObject):
    success = pyqtSignal(object)  # Pan123 对象
    error = pyqtSignal(str)       # 失败原因
