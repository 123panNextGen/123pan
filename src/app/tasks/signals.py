"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtCore import QObject, Signal


class _LoadListSignals(QObject):
    finished = Signal(list, str)


class _OpFinishedSignals(QObject):
    finished = Signal(bool, str, str, str, list, list)


class _StorageInfoSignals(QObject):
    """云盘空间信息加载完成信号。"""
    finished = Signal(object, str)  # (user_info, error)


class _TrashListSignals(QObject):
    """回收站列表加载完成信号。"""
    finished = Signal(list, str)  # (items, error)


class _ShareListSignals(QObject):
    """分享列表加载完成信号（免费/付费两组）。"""
    finished = Signal(object, str, object, str)  # (free_data, free_err, pay_data, pay_err)


class _UserInfoSignals(QObject):
    """云盘用户信息加载完成信号。"""
    finished = Signal(object, str)  # (user_info, error)


class _DeviceListSignals(QObject):
    """登录设备列表加载完成信号。"""
    finished = Signal(object, str)  # (device_data, error)


class _FolderListSignals(QObject):
    """目录树子文件夹列表加载完成信号。"""
    finished = Signal(int, list, str)  # (dir_id, folder_items, error)


class _AutoLoginSignals(QObject):
    """后台自动登录完成信号。"""
    finished = Signal(object, str)  # (pan, error)


class _CheckVersionSignals(QObject):
    """版本检查完成信号。"""
    finished = Signal(bool)  # 是否最新版本


class _PasswordLoginSignals(QObject):
    """密码登录完成信号。"""
    finished = Signal(object, int, str)  # (pan, code, error)


class _DeleteSharesSignals(QObject):
    """批量删除分享完成信号。"""
    finished = Signal(int, int, str)  # (success_count, fail_count, last_error)


class _TrashOpSignals(QObject):
    """回收站恢复/永久删除完成信号。"""
    finished = Signal(bool, str)  # (success, msg)


class _DownloadLinkSignals(QObject):
    """下载链接获取完成信号。"""
    finished = Signal(str, str)  # (url, error)


class _ShareCreateSignals(QObject):
    """分享链接创建完成信号。"""
    finished = Signal(str, str)  # (url, error)


class _QRGenerateSignals(QObject):
    finished = Signal(dict)  # 二维码生成成功（uniID/url/_pan_temp）
    error = Signal(str)      # 失败原因


class _QRPollSignals(QObject):
    result = Signal(dict)    # 轮询结果 {loginStatus, scanPlatform, token?}
    error = Signal()         # 网络错误


class _QRVerifySignals(QObject):
    success = Signal(object)  # Pan123 对象
    error = Signal(str)       # 失败原因


class _SyncJobSignals(QObject):
    """文件夹同步运行状态信号。"""
    # (job_id, phase_text) 阶段/状态文本
    status = Signal(int, str)
    # (job_id, rel_path, current, total) 文件级进度
    file_progress = Signal(int, str, int, int)
    # (job_id, rel_path, success, error) 单个文件处理完成
    file_done = Signal(int, str, bool, str)
    # (job_id, success, summary, stats) 运行结束
    finished = Signal(int, bool, str, dict)
