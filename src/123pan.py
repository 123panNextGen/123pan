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

    # 限制 Qt 全局像素图缓存（图标/图片缩放等），降低内存占用
    # 默认 20MB，图标通常很小，10MB 足够且可避免缓存无限膨胀
    from PySide6.QtGui import QPixmapCache

    QPixmapCache.setCacheLimit(10 * 1024)  # 单位 KB
    logger.debug("QPixmapCache 限制为 10MB")
    logger.debug("QApplication 初始化完成")

    translator = FluentTranslator()
    app.installTranslator(translator)
    logger.debug("Fluent 翻译已安装")

    setTheme(Theme.AUTO)
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
