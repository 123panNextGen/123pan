#!/usr/bin/env python3

"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import platform
import sys

from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from qfluentwidgets import (
    FluentTranslator,
    Theme,
    SystemThemeListener,
    qconfig,
    setTheme,
)
from qfluentwidgets.common.style_sheet import updateStyleSheet

from app.common.log import get_logger, set_log_level
from app.common.config import ConfigManager
from app.common.i18n import init_i18n
from app.common import resource  # 注册 Qt 资源（qss 等，:/(prefix)/... 路径）
from app.view.main_window import MainWindow

logger = get_logger("123pan")


def main():
    # 从配置加载日志等级
    _level = ConfigManager.get_setting("logLevel", "DEBUG")
    set_log_level(_level)

    # 初始化国际化
    _lang = ConfigManager.get_setting("language", "zh_CN")
    i18n = init_i18n(_lang)
    logger.info("语言: %s", _lang)
    logger.info("日志等级: %s", _level)
    logger.info("=" * 60)
    logger.info("123pan 启动")
    logger.info("Python: %s", sys.version)
    logger.info("Platform: %s - %s", platform.system(), platform.release())
    logger.info("=" * 60)

    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QtWidgets.QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    app.setWindowIcon(QIcon(":/123pan/logo.ico"))

    # 限制 Qt 全局像素图缓存（图标/图片缩放等），降低内存占用
    # 默认 20MB，图标通常很小，10MB 足够且可避免缓存无限膨胀
    from PySide6.QtGui import QPixmapCache

    QPixmapCache.setCacheLimit(10 * 1024)  # 单位 KB
    logger.debug("QPixmapCache 限制为 10MB")
    logger.debug("QApplication 初始化完成")

    translator = FluentTranslator()
    app.installTranslator(translator)
    logger.debug("Fluent 翻译已安装")

    # 应用主题模式（跟随系统/浅色/深色），用户可在设置页切换
    theme_mode = ConfigManager.get_setting("themeMode", "auto")
    theme_map = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}
    setTheme(theme_map.get(theme_mode, Theme.AUTO))
    logger.info("主题模式: %s", theme_mode)
    listener = SystemThemeListener()

    def on_system_theme_changed():
        if qconfig.themeMode.value == Theme.AUTO:
            logger.debug("系统主题变更，自动切换")
            qconfig.theme = Theme.AUTO
            updateStyleSheet()
            qconfig.themeChangedFinished.emit()

    listener.systemThemeChanged.connect(on_system_theme_changed)
    listener.start()
    logger.debug("系统主题监听已启动")

    window = MainWindow()
    window.themeListener = listener
    window.show()
    logger.info("主窗口已显示")
    exit_code = app.exec()
    # 停止系统主题监听线程，避免退出时 "QThread: Destroyed while thread is still running"
    listener.requestInterruption()
    listener.wait(2000)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
