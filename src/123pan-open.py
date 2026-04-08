import platform
import sys

from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from qfluentwidgets import FluentTranslator, Theme, setTheme

from app.view.main_window import MainWindow


def main():
    # 高 DPI 支持
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QtWidgets.QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)

    # macOS 下用苹方替代 Segoe UI，消除字体查找耗时警告
    if platform.system() == "Darwin":
        font = QFont("PingFang SC")
        font.insertSubstitution("Segoe UI", "PingFang SC")
        font.insertSubstitution("Segoe UI Semibold", "PingFang SC")
        app.setFont(font)

    # 安装 Fluent 中文翻译
    translator = FluentTranslator()
    app.installTranslator(translator)

    # # 跟随系统深色/浅色
    # 临时使用 浅色
    setTheme(Theme.LIGHT)

    window = MainWindow()
    if not window.login_success:
        sys.exit(0)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
