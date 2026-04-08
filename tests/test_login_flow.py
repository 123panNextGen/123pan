from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from src.app.common import database as database_module
from src.app.common.database import Database
from src.app.view.login_window import (
    has_saved_credentials,
    try_token_probe,
)

# QRLoginPage 等 Qt widget 需要 QApplication 实例
app = QApplication.instance() or QApplication([])


def _use_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "123pan-open.db"
    monkeypatch.setattr(database_module, "_get_db_path", lambda: db_path)
    Database.reset()
    return Database.instance()


class TestHasSavedCredentials:
    def test_returns_true_when_both_present(self, tmp_path, monkeypatch):
        db = _use_temp_db(tmp_path, monkeypatch)
        db.set_many_config({"userName": "alice", "passWord": "secret"})
        assert has_saved_credentials(db) is True

    def test_returns_false_when_no_password(self, tmp_path, monkeypatch):
        db = _use_temp_db(tmp_path, monkeypatch)
        db.set_many_config({"userName": "alice", "passWord": ""})
        assert has_saved_credentials(db) is False

    def test_returns_false_when_no_username(self, tmp_path, monkeypatch):
        db = _use_temp_db(tmp_path, monkeypatch)
        db.set_many_config({"userName": "", "passWord": "secret"})
        assert has_saved_credentials(db) is False


class TestTryTokenProbe:
    def test_returns_none_when_no_token(self, tmp_path, monkeypatch):
        db = _use_temp_db(tmp_path, monkeypatch)
        db.set_config("authorization", "")
        assert try_token_probe(db) is None

    def test_returns_pan_when_token_valid(self, tmp_path, monkeypatch):
        db = _use_temp_db(tmp_path, monkeypatch)
        db.set_config("authorization", "valid-token")
        mock_pan = MagicMock()
        mock_pan.user_info.return_value = {"user": "alice"}
        with patch("src.app.view.login_window.Pan123", return_value=mock_pan):
            result = try_token_probe(db)
        assert result is mock_pan

    def test_clears_token_when_invalid(self, tmp_path, monkeypatch):
        db = _use_temp_db(tmp_path, monkeypatch)
        db.set_config("authorization", "expired-token")
        mock_pan = MagicMock()
        mock_pan.user_info.return_value = None
        with patch("src.app.view.login_window.Pan123", return_value=mock_pan):
            result = try_token_probe(db)
        assert result is None
        assert db.get_config("authorization", "") == ""

    def test_clears_token_on_exception(self, tmp_path, monkeypatch):
        db = _use_temp_db(tmp_path, monkeypatch)
        db.set_config("authorization", "bad-token")
        with patch("src.app.view.login_window.Pan123", side_effect=Exception("connection error")):
            result = try_token_probe(db)
        assert result is None
        assert db.get_config("authorization", "") == ""


class TestQRLoginPage:
    """QR 登录页面逻辑测试（直接调用方法，不依赖 Qt event loop）。"""

    def _make_page(self):
        from src.app.view.qr_login_page import QRLoginPage
        page = QRLoginPage()
        # 模拟已初始化状态
        page._pan_temp = MagicMock()
        page._uni_id = "test-uni-id"
        page._consecutive_errors = 0
        # 保持 Python 引用防止 C++ 对象被过早删除
        self._page_ref = page
        return page

    def test_poll_login_success_emits_signal(self):
        page = self._make_page()
        page._pan_temp.qr_poll.return_value = {"loginStatus": 3, "token": "jwt-token"}
        mock_pan = MagicMock()
        mock_pan.user_info.return_value = {"user": "alice"}
        signals = []
        page.loginSuccess.connect(lambda obj: signals.append(obj))
        with patch("src.app.view.qr_login_page.Pan123", return_value=mock_pan):
            page._do_poll()
        assert len(signals) == 1
        assert signals[0] is mock_pan

    def test_poll_waiting_no_signal(self):
        page = self._make_page()
        page._pan_temp.qr_poll.return_value = {"loginStatus": 0}
        signals = []
        page.loginSuccess.connect(lambda obj: signals.append(obj))
        page._do_poll()
        assert len(signals) == 0

    def test_poll_consecutive_errors_stops(self):
        page = self._make_page()
        page._pan_temp.qr_poll.side_effect = Exception("network error")
        page.poll_timer.start(1000)
        for _ in range(3):
            page._do_poll()
        assert not page.poll_timer.isActive()


class TestQRLoginSuccess:
    """LoginDialog._on_qr_login_success 配置持久化测试。"""

    def _make_dialog(self, tmp_path, monkeypatch):
        db = _use_temp_db(tmp_path, monkeypatch)
        from src.app.view.login_window import LoginDialog
        dialog = LoginDialog()
        return dialog, db

    def test_saves_token_when_stay_logged_in(self, tmp_path, monkeypatch):
        dialog, db = self._make_dialog(tmp_path, monkeypatch)
        dialog.cb_stay_logged_in.setChecked(True)
        mock_pan = MagicMock()
        mock_pan.authorization = "Bearer test-jwt"
        mock_pan.user_name = "test-user"
        mock_pan.devicetype = "test-device"
        mock_pan.osversion = "test-os"
        mock_pan.loginuuid = "test-uuid"
        # Prevent dialog.accept() from actually closing
        with patch.object(dialog, "accept"):
            dialog._on_qr_login_success(mock_pan)
        assert db.get_config("authorization", "") == "Bearer test-jwt"
        assert db.get_config("userName", "") == "test-user"
        assert dialog.pan is mock_pan

    def test_clears_token_when_stay_logged_in_unchecked(self, tmp_path, monkeypatch):
        dialog, db = self._make_dialog(tmp_path, monkeypatch)
        dialog.cb_stay_logged_in.setChecked(False)
        mock_pan = MagicMock()
        mock_pan.authorization = "Bearer test-jwt"
        mock_pan.user_name = "test-user"
        mock_pan.devicetype = "test-device"
        mock_pan.osversion = "test-os"
        mock_pan.loginuuid = "test-uuid"
        with patch.object(dialog, "accept"):
            dialog._on_qr_login_success(mock_pan)
        assert db.get_config("authorization", "") == ""
