import sys

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt
from qfluentwidgets import FluentTranslator, Theme, SystemThemeListener, qconfig, setTheme
from qfluentwidgets.common.style_sheet import updateStyleSheet

from app.view.main_window import MainWindow


def main():
    # 高 DPI 支持
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QtWidgets.QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)

    # 安装 Fluent 中文翻译
    translator = FluentTranslator()
    app.installTranslator(translator)

    # 跟随系统深色/浅色主题
    setTheme(Theme.AUTO)
    listener = SystemThemeListener()

    def on_system_theme_changed():
        if qconfig.themeMode.value == Theme.AUTO:
            qconfig.theme = Theme.AUTO
            updateStyleSheet()
            qconfig.themeChangedFinished.emit()

    listener.systemThemeChanged.connect(on_system_theme_changed)
    listener.start()

    window = MainWindow()
    window.themeListener = listener
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
