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


class _StorageInfoSignals(QObject):
    """云盘空间信息加载完成信号。"""
    finished = pyqtSignal(object, str)  # (user_info, error)


class _TrashListSignals(QObject):
    """回收站列表加载完成信号。"""
    finished = pyqtSignal(list, str)  # (items, error)


class _ShareListSignals(QObject):
    """分享列表加载完成信号（免费/付费两组）。"""
    finished = pyqtSignal(object, str, object, str)  # (free_data, free_err, pay_data, pay_err)


class _UserInfoSignals(QObject):
    """云盘用户信息加载完成信号。"""
    finished = pyqtSignal(object, str)  # (user_info, error)


class _DeviceListSignals(QObject):
    """登录设备列表加载完成信号。"""
    finished = pyqtSignal(object, str)  # (device_data, error)


class _FolderListSignals(QObject):
    """目录树子文件夹列表加载完成信号。"""
    finished = pyqtSignal(int, list, str)  # (dir_id, folder_items, error)


class _AutoLoginSignals(QObject):
    """后台自动登录完成信号。"""
    finished = pyqtSignal(object, str)  # (pan, error)


class _QRGenerateSignals(QObject):
    finished = pyqtSignal(dict)  # 二维码生成成功（uniID/url/_pan_temp）
    error = pyqtSignal(str)      # 失败原因


class _QRPollSignals(QObject):
    result = pyqtSignal(dict)    # 轮询结果 {loginStatus, scanPlatform, token?}
    error = pyqtSignal()         # 网络错误


class _QRVerifySignals(QObject):
    success = pyqtSignal(object)  # Pan123 对象
    error = pyqtSignal(str)       # 失败原因
