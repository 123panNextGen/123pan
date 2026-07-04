import platform
import sys

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt
from qfluentwidgets import FluentTranslator, Theme, SystemThemeListener, qconfig, setTheme
from qfluentwidgets.common.style_sheet import updateStyleSheet

from app.common.log import get_logger
from app.view.main_window import MainWindow

logger = get_logger("123pan")


def main():
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
