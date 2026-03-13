import sys
from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt
from qfluentwidgets import FluentTranslator, setTheme, Theme
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

    # 跟随系统深色/浅色
    setTheme(Theme.AUTO)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()