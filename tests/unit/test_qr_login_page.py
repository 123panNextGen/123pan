"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.view.qr_login_page import QRLoginPage, _MAX_QR_REFRESH

_app = QApplication.instance() or QApplication([])


class TestQRLoginPage:
    """二维码登录页面逻辑测试（直接调用方法，不依赖 Qt event loop）。"""

    def _make_page(self):
        page = QRLoginPage()
        page._pan_temp = MagicMock()
        page._uni_id = "test-uni-id"
        page._consecutive_errors = 0
        self._page_ref = page  # 保持 Python 引用防止 C++ 对象被过早删除
        return page

    def test_poll_waiting_no_signal(self):
        page = self._make_page()
        signals = []
        page.loginSuccess.connect(lambda obj: signals.append(obj))
        page._on_poll_result(page._qr_flow_id, {"loginStatus": 0})
        assert signals == []

    def test_poll_stale_flow_ignored(self):
        page = self._make_page()
        signals = []
        page.loginSuccess.connect(lambda obj: signals.append(obj))
        page._on_poll_result(page._qr_flow_id + 1, {"loginStatus": 3})
        assert signals == []

    def test_poll_rejected(self):
        page = self._make_page()
        with patch.object(page, "stop_polling") as mock_stop, patch.object(
            page, "_show_expired_overlay"
        ) as mock_overlay:
            page._on_poll_result(page._qr_flow_id, {"loginStatus": 2})
        mock_stop.assert_called_once()
        mock_overlay.assert_called_once()

    def test_poll_expired_refreshes(self):
        page = self._make_page()
        page._qr_refresh_count = 0
        with patch.object(page, "stop_polling"), patch.object(
            page, "start_qr_flow"
        ) as mock_start:
            page._on_poll_result(page._qr_flow_id, {"loginStatus": 4})
        mock_start.assert_called_once()

    def test_poll_expired_over_limit(self):
        page = self._make_page()
        page._qr_refresh_count = _MAX_QR_REFRESH + 1
        with patch.object(page, "stop_polling"), patch.object(
            page, "_show_expired_overlay"
        ) as mock_overlay:
            page._on_poll_result(page._qr_flow_id, {"loginStatus": 4})
        mock_overlay.assert_called_once()

    def test_qr_generated_stale_closes_pan(self):
        page = self._make_page()
        stale_pan = MagicMock()
        page._on_qr_generated(
            page._qr_flow_id + 1,
            {
                "_pan_temp": stale_pan,
                "uniID": "stale-uni",
                "url": "https://login.123pan.com/qr/stale",
            },
        )
        stale_pan.close.assert_called_once()

    def test_poll_error_consecutive_stops(self):
        page = self._make_page()
        page.poll_timer.start(1000)
        for _ in range(3):
            page._on_poll_error(page._qr_flow_id)
        assert not page.poll_timer.isActive()

    def test_do_poll_skips_when_in_flight(self):
        page = self._make_page()
        page._poll_in_flight = True
        with patch(
            "src.app.view.qr_login_page.QThreadPool.globalInstance"
        ) as mock_pool:
            page._do_poll()
        mock_pool.return_value.start.assert_not_called()

    def test_do_poll_starts_task(self):
        page = self._make_page()
        page._poll_in_flight = False
        with patch(
            "src.app.view.qr_login_page.QThreadPool.globalInstance"
        ) as mock_pool:
            page._do_poll()
        mock_pool.return_value.start.assert_called_once()

    def test_stop_polling_closes_pan(self):
        page = self._make_page()
        pan_temp = MagicMock()
        page._pan_temp = pan_temp
        page.poll_timer.start(1000)
        page.stop_polling()
        assert not page.poll_timer.isActive()
        pan_temp.close.assert_called_once()
        assert page._pan_temp is None
