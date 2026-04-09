"""二维码登录页面 widget。"""

import qrcode
from PIL.ImageQt import ImageQt

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..common.api import Pan123
from ..common.log import get_logger

logger = get_logger(__name__)

_MAX_POLL_ERRORS = 3


class QRLoginPage(QWidget):
    """二维码登录页面，展示二维码、轮询状态、处理登录成功。"""

    loginSuccess = Signal(object)  # 发射 Pan123 对象

    def __init__(self, parent=None):
        super().__init__(parent)
        self._uni_id = ""
        self._pan_temp = None
        self._consecutive_errors = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addStretch(1)

        # 二维码图片
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet(
            "QLabel { background: #FFFFFF; border: 1px solid #E0E0E0; border-radius: 4px; }"
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
        self.status_label = QLabel("请使用微信扫一扫")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("QLabel { font-size: 14px; }")
        layout.addWidget(self.status_label)

        layout.addSpacing(16)

        # "保持登录" checkbox（QR 页面独立实例，与密码页面通过信号同步）
        self.cb_stay_logged_in = QCheckBox("保持登录")
        cb_wrapper = QHBoxLayout()
        cb_wrapper.addStretch()
        cb_wrapper.addWidget(self.cb_stay_logged_in)
        cb_wrapper.addStretch()
        layout.addLayout(cb_wrapper)

        layout.addStretch(1)

        # 轮询定时器
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)
        self.poll_timer.timeout.connect(self._do_poll)

        # 过期定时器（singleShot）
        self.expiry_timer = QTimer(self)
        self.expiry_timer.setSingleShot(True)
        self.expiry_timer.setInterval(60000)
        self.expiry_timer.timeout.connect(self._on_expired)

    def start_qr_flow(self):
        """生成二维码并开始轮询。"""
        self.stop_polling()
        self.overlay.hide()
        self.status_label.setStyleSheet("QLabel { font-size: 14px; }")
        self.status_label.setText("正在获取二维码...")

        try:
            pan_temp = Pan123(readfile=True, user_name="", password="")
            data = pan_temp.qr_generate()
        except Exception as e:
            logger.error(f"获取二维码失败: {e}")
            self.status_label.setText("获取二维码失败，请重试")
            self._show_expired_overlay()
            return

        self._uni_id = data["uniID"]
        self._pan_temp = pan_temp

        # 生成二维码图片
        qr_content = (
            data["url"]
            + "?env=production&uniID=" + data["uniID"]
            + "&source=123pan&type=login"
        )
        qr_img = qrcode.make(qr_content, box_size=5, border=2)
        qt_image = ImageQt(qr_img.convert("RGB"))
        pixmap = QPixmap.fromImage(QImage(qt_image))
        self.qr_label.setPixmap(
            pixmap.scaled(
                200, 200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        self.status_label.setText("请使用微信或 123云盘 App 扫码")
        self._consecutive_errors = 0
        self.poll_timer.start()
        self.expiry_timer.start(60000)

    def stop_polling(self):
        """停止所有定时器。"""
        self.poll_timer.stop()
        self.expiry_timer.stop()

    def _do_poll(self):
        """轮询一次扫码状态。"""
        try:
            result = self._pan_temp.qr_poll(self._uni_id)
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors >= _MAX_POLL_ERRORS:
                self.stop_polling()
                self.status_label.setStyleSheet(
                    "QLabel { font-size: 14px; color: #CF222E; }"
                )
                self.status_label.setText("网络异常，请检查后重试")
                self._show_expired_overlay()
            return

        self._consecutive_errors = 0
        status = result.get("loginStatus", -1)

        if status == 0:
            # 等待扫码
            return
        elif status == 1:
            # 已扫码，待确认
            self.status_label.setText("扫码成功，请在手机上确认")
            self._show_scanned_overlay()
        elif status == 2:
            # 用户拒绝登录
            self.stop_polling()
            self.status_label.setText("登录已取消")
            self._show_expired_overlay()
        elif status == 3:
            # 用户确认登录
            self.stop_polling()
            self.status_label.setText("登录成功")
            scan_platform = result.get("scanPlatform", 0)
            token = result.get("token", "")
            self._handle_login_success(scan_platform, token)
        elif status == 4:
            # 二维码过期
            self.stop_polling()
            self.start_qr_flow()

    def _handle_login_success(self, scan_platform, token):
        """处理登录成功，根据扫码平台获取 token。"""
        if scan_platform == 4 and not token:
            # 微信扫码：需要额外请求 wx_code 换取 token
            try:
                wx_code = self._pan_temp.qr_wx_code(self._uni_id)
                # 当前 API 文档未提供 wxCode -> token 的完整接口
                logger.warning(f"微信扫码登录获取 wxCode: {wx_code}")
                self.status_label.setText("微信登录暂不支持，请使用 123云盘 App 扫码")
                self._show_expired_overlay()
                return
            except Exception as e:
                logger.error(f"获取 wxCode 失败: {e}")
                self.status_label.setText("登录失败，请重试")
                self._show_expired_overlay()
                return

        # App 扫码（scanPlatform=7）或已有 token
        if not token:
            self.status_label.setText("登录失败：未获取到凭证")
            self._show_expired_overlay()
            return

        try:
            pan = Pan123(
                readfile=True, user_name="", password="",
                authorization="Bearer " + token,
            )
            user_data = pan.user_info()
            if user_data is None:
                self.status_label.setText("登录验证失败，请重试")
                self._show_expired_overlay()
                return
            pan.user_name = user_data.get("Nickname", "")
            self.loginSuccess.emit(pan)
        except Exception as e:
            logger.error(f"QR 登录验证失败: {e}")
            self.status_label.setText("登录验证失败，请重试")
            self._show_expired_overlay()

    def _on_expired(self):
        """二维码过期，自动刷新。"""
        self.poll_timer.stop()
        self.start_qr_flow()

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
        self.overlay.setText("二维码已过期\n点击刷新")
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.mousePressEvent = lambda e: self.start_qr_flow()
        self.overlay.show()

    def hideEvent(self, event):
        self.stop_polling()
        super().hideEvent(event)
