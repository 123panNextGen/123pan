"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import io

import qrcode
from PySide6 import shiboken6
from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import CheckBox

from ..common.i18n import tr
from ..common.log import get_logger
from ..tasks.qr_login_tasks import QRGenerateTask, QRPollTask, QRLoginVerifyTask

logger = get_logger(__name__)

_MAX_POLL_ERRORS = 3
_QR_POLL_INTERVAL_MS = 1000
_QR_EXPIRY_MS = 60000
_MAX_QR_REFRESH = 5


def _widget_alive(widget) -> bool:
    """检查 Qt 控件是否仍有效（回调可能在控件销毁后触发）。"""
    try:
        return shiboken6.isValid(widget)
    except Exception:
        return False


class QRLoginPage(QWidget):
    """二维码登录页面，展示二维码、轮询状态、处理登录成功。"""

    loginSuccess = Signal(object)  # 发射 Pan123 对象

    def __init__(self, parent=None):
        super().__init__(parent)
        self._uni_id = ""
        self._pan_temp = None
        self._consecutive_errors = 0
        self._qr_flow_id = 0
        self._poll_in_flight = False
        self._qr_refresh_count = 0
        self._pending_task = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addStretch(1)

        # 二维码图片
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet(
            "QLabel { background: #FFFFFF; border: 1px solid #E0E0E0;"
            " border-radius: 4px; }"
        )
        layout.addWidget(self.qr_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 遮罩层（覆盖在 qr_label 上）
        self.overlay = QLabel(self.qr_label)
        self.overlay.setFixedSize(200, 200)
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay.hide()

        layout.addSpacing(8)

        # 状态文字
        self.status_label = QLabel(
            tr("qr_login.status_hint", "请使用微信或 123云盘 App 扫码")
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("QLabel { font-size: 14px; }")
        layout.addWidget(self.status_label)

        layout.addSpacing(12)

        # "保持登录" checkbox（与密码页面通过信号同步）
        self.cb_stay_logged_in = CheckBox(tr("login.stay_logged_in", "保持登录"))
        cb_wrapper = QHBoxLayout()
        cb_wrapper.addStretch()
        cb_wrapper.addWidget(self.cb_stay_logged_in)
        cb_wrapper.addStretch()
        layout.addLayout(cb_wrapper)

        layout.addStretch(1)

        # 轮询定时器
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(_QR_POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._do_poll)

        # 过期定时器（singleShot）
        self.expiry_timer = QTimer(self)
        self.expiry_timer.setSingleShot(True)
        self.expiry_timer.setInterval(_QR_EXPIRY_MS)
        self.expiry_timer.timeout.connect(self._on_expired)

    # ---- 流程控制 ----

    def start_qr_flow(self):
        """异步生成二维码并开始轮询。"""
        self.stop_polling()
        flow_id = self._qr_flow_id
        self.overlay.hide()
        self.status_label.setStyleSheet("QLabel { font-size: 14px; }")
        self.status_label.setText(tr("qr_login.status_fetching", "正在获取二维码..."))

        task = QRGenerateTask()
        task.signals.finished.connect(
            lambda data, fid=flow_id: self._on_qr_generated(fid, data)
        )
        task.signals.error.connect(
            lambda error_msg, fid=flow_id: self._on_qr_generate_error(fid, error_msg)
        )
        self._pending_task = task  # 防止 GC 回收 signals
        QThreadPool.globalInstance().start(task)

    def stop_polling(self):
        """停止所有定时器并释放临时会话。"""
        self._stop_polling_timers(close_pan_temp=True, invalidate=True)

    def _stop_polling_timers(self, *, close_pan_temp, invalidate):
        self.poll_timer.stop()
        self.expiry_timer.stop()
        self._poll_in_flight = False
        if close_pan_temp and self._pan_temp:
            self._pan_temp.close()
            self._pan_temp = None
        if invalidate:
            self._qr_flow_id += 1

    # ---- 二维码生成 ----

    def _on_qr_generated(self, flow_id, data):
        """二维码生成成功回调。"""
        pan_temp = data.pop("_pan_temp", None)
        if not _widget_alive(self) or flow_id != self._qr_flow_id:
            if pan_temp is not None:
                pan_temp.close()
            return
        self._uni_id = data["uniID"]
        self._pan_temp = pan_temp

        # 生成二维码图片
        qr_content = (
            data["url"]
            + "?env=production&uniID=" + data["uniID"]
            + "&source=123pan&type=login"
        )
        try:
            qr_img = qrcode.make(qr_content, box_size=5, border=2)
            buf = io.BytesIO()
            qr_img.save(buf, format="PNG")
            pixmap = QPixmap()
            if not pixmap.loadFromData(buf.getvalue()):
                raise RuntimeError("二维码图片加载失败")
        except Exception as e:
            logger.error("生成二维码图片失败: %s", e)
            self._on_qr_generate_error(flow_id, str(e))
            return

        self.qr_label.setPixmap(
            pixmap.scaled(
                200,
                200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        self.status_label.setText(
            tr("qr_login.status_hint", "请使用微信或 123云盘 App 扫码")
        )
        self._consecutive_errors = 0
        self.poll_timer.start()
        self.expiry_timer.start()

    def _on_qr_generate_error(self, flow_id, error_msg):
        """二维码生成失败回调。"""
        if not _widget_alive(self) or flow_id != self._qr_flow_id:
            return
        logger.error("获取二维码失败: %s", error_msg)
        self.status_label.setText(
            tr("qr_login.status_generate_failed", "获取二维码失败，请重试")
        )
        self._show_expired_overlay()

    # ---- 轮询 ----

    def _do_poll(self):
        """异步轮询一次扫码状态。"""
        if not self._pan_temp or not self._uni_id or self._poll_in_flight:
            return
        self._poll_in_flight = True
        flow_id = self._qr_flow_id
        task = QRPollTask(self._pan_temp, self._uni_id)
        task.signals.result.connect(
            lambda result, fid=flow_id: self._on_poll_result(fid, result)
        )
        task.signals.error.connect(
            lambda fid=flow_id: self._on_poll_error(fid)
        )
        self._pending_task = task  # 防止 GC 回收 signals
        QThreadPool.globalInstance().start(task)

    def _on_poll_error(self, flow_id):
        """轮询网络错误回调。"""
        if not _widget_alive(self) or flow_id != self._qr_flow_id:
            return
        self._poll_in_flight = False
        self._consecutive_errors += 1
        if self._consecutive_errors >= _MAX_POLL_ERRORS:
            self.stop_polling()
            self.status_label.setStyleSheet(
                "QLabel { font-size: 14px; color: #CF222E; }"
            )
            self.status_label.setText(
                tr("qr_login.status_network_error", "网络异常，请检查后重试")
            )
            self._show_expired_overlay()

    def _on_poll_result(self, flow_id, result):
        """轮询结果回调。"""
        if not _widget_alive(self) or flow_id != self._qr_flow_id:
            return
        self._poll_in_flight = False
        self._consecutive_errors = 0

        status = result.get("loginStatus", -1)

        if status == 0:
            # 等待扫码
            return
        if status == 1:
            # 已扫码，待确认
            self.status_label.setText(
                tr("qr_login.status_scanned", "扫码成功，请在手机上确认")
            )
            self._show_scanned_overlay()
        elif status == 2:
            # 用户拒绝登录
            self.stop_polling()
            self.status_label.setText(tr("qr_login.status_cancelled", "登录已取消"))
            self._show_expired_overlay()
        elif status == 3:
            # 用户确认登录
            pan_temp = self._pan_temp  # 在 stop 置空前保存引用
            self._stop_polling_timers(close_pan_temp=False, invalidate=False)
            self._pan_temp = None
            self.status_label.setText(tr("qr_login.status_success", "登录成功"))
            scan_platform = result.get("scanPlatform", 0)
            token = result.get("token", "")
            self._handle_login_success(flow_id, scan_platform, token, pan_temp)
        elif status == 4:
            # 二维码过期
            self.stop_polling()
            self._qr_refresh_count += 1
            if self._qr_refresh_count > _MAX_QR_REFRESH:
                self.status_label.setText(
                    tr("qr_login.status_expired_close", "二维码已过期，请关闭后重试")
                )
                self._show_expired_overlay()
                return
            self.start_qr_flow()
        else:
            logger.warning("未知 QR 登录状态: %s", status)

    # ---- 登录成功 ----

    def _handle_login_success(self, flow_id, scan_platform, token, pan_temp=None):
        """异步处理登录成功，验证 token 并获取用户信息。"""
        pan_temp = pan_temp or self._pan_temp
        task = QRLoginVerifyTask(token, scan_platform, pan_temp, self._uni_id)
        task.signals.success.connect(
            lambda pan, fid=flow_id: self._on_login_verified(fid, pan)
        )
        task.signals.error.connect(
            lambda error_msg, fid=flow_id: self._on_login_verify_error(fid, error_msg)
        )
        self._pending_task = task  # 防止 GC 回收 signals
        QThreadPool.globalInstance().start(task)

    def _on_login_verified(self, flow_id, pan):
        """登录验证成功回调。"""
        if not _widget_alive(self) or flow_id != self._qr_flow_id:
            return
        self.loginSuccess.emit(pan)

    def _on_login_verify_error(self, flow_id, error_msg):
        """登录验证失败回调。"""
        if not _widget_alive(self) or flow_id != self._qr_flow_id:
            return
        if "暂不支持" in error_msg or "未获取到凭证" in error_msg:
            self.status_label.setText(error_msg)
        else:
            logger.error("QR 登录验证失败: %s", error_msg)
            self.status_label.setText(
                tr("qr_login.status_verify_failed", "登录验证失败，请重试")
            )
        self._show_expired_overlay()

    # ---- 过期 ----

    def _on_expired(self):
        """二维码过期，自动刷新（受 _qr_refresh_count 限制）。"""
        self.poll_timer.stop()
        self._qr_refresh_count += 1
        if self._qr_refresh_count > _MAX_QR_REFRESH:
            self.status_label.setText(
                tr("qr_login.status_expired_manual", "二维码已过期，请手动刷新")
            )
            self._show_expired_overlay()
            return
        self.start_qr_flow()

    # ---- 遮罩 ----

    def _show_scanned_overlay(self):
        """显示已扫码绿色遮罩。"""
        self.overlay.setStyleSheet(
            "QLabel { background: rgba(76, 175, 80, 0.6);"
            " color: white; font-size: 48px; border-radius: 4px; }"
        )
        self.overlay.setText("\u2713")
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.show()

    def _show_expired_overlay(self):
        """显示过期遮罩，点击刷新。"""
        self.overlay.setStyleSheet(
            "QLabel { background: rgba(0, 0, 0, 0.65);"
            " color: white; font-size: 14px; border-radius: 4px; }"
        )
        self.overlay.setText(tr("qr_login.status_expired", "二维码已过期\n点击刷新"))
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.mousePressEvent = lambda e: self.start_qr_flow()
        self.overlay.show()

    def hideEvent(self, event):
        self.stop_polling()
        super().hideEvent(event)
