"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from src.app.common.config import ConfigManager

_app = QApplication.instance() or QApplication([])


class TestThemeMode:
    def test_default_theme_mode(self, tmp_db):
        """默认主题模式为跟随系统。"""
        assert ConfigManager.get_setting("themeMode", "auto") == "auto"

    def test_theme_mode_persist(self, tmp_db):
        """主题模式可持久化读写。"""
        ConfigManager.set_setting("themeMode", "dark")
        assert ConfigManager.get_setting("themeMode", "auto") == "dark"
        # 重新加载配置
        ConfigManager.load_config()
        assert ConfigManager.get_setting("themeMode", "auto") == "dark"


class TestSettingInterfaceTheme:
    def test_theme_card_created(self, tmp_db):
        """设置页包含主题模式卡片。"""
        from src.app.view.setting_interface import SettingInterface

        panel = SettingInterface()
        assert hasattr(panel, "themeModeCard")
        # 默认 index 对应 auto（跟随系统）
        assert panel.themeModeCard.currentIndex() == 0
        panel.deleteLater()

    def test_apply_theme_modes(self, tmp_db):
        """三种主题模式切换不抛异常。"""
        from src.app.view.setting_interface import SettingInterface

        for mode in ("auto", "light", "dark"):
            SettingInterface._apply_theme(mode)
            assert ConfigManager.get_setting("themeMode", "auto") == "auto"  # 不持久化于静态方法

    def test_on_theme_changed_persists(self, tmp_db):
        """切换主题时持久化配置并应用。"""
        from src.app.view.setting_interface import SettingInterface

        panel = SettingInterface()
        with patch.object(SettingInterface, "_apply_theme") as mock_apply:
            panel._SettingInterface__onThemeModeChanged("浅色")
        mock_apply.assert_called_once_with("light")
        assert ConfigManager.get_setting("themeMode", "auto") == "light"
        panel.deleteLater()
