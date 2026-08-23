"""网络行为设置测试。"""

from unittest.mock import Mock

from PySide6.QtWidgets import QApplication, QWidget

from src.app.common.config import ConfigManager

_app = QApplication.instance() or QApplication([])


class TestNetworkBehaviorSettings:
    def test_cards_default_enabled(self, tmp_db):
        from src.app.view.setting_interface import SettingInterface

        panel = SettingInterface()
        assert panel.clientSimulationCard.isChecked() is True
        assert panel.errorBackoffRetryCard.isChecked() is True
        panel.deleteLater()

    def test_changes_persist_and_apply(self, tmp_db):
        from src.app.view.setting_interface import SettingInterface

        window = QWidget()
        window.pan = Mock()
        panel = SettingInterface(window)

        panel._SettingInterface__onClientSimulationChanged(False)
        panel._SettingInterface__onErrorBackoffRetryChanged(False)

        assert ConfigManager.get_setting("clientSimulationEnabled") is False
        assert ConfigManager.get_setting("errorBackoffRetryEnabled") is False
        window.pan.set_client_simulation.assert_called_once_with(False)
        window.pan.set_error_backoff_retry.assert_called_once_with(False)
        window.deleteLater()