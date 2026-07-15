"""国际化（i18n）模块。

使用 JSON 翻译文件，支持动态切换语言。
所有视图通过 tr() 函数获取翻译后的文本。
"""

import json
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# 翻译文件目录
_TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "resource" / "i18n"


class TranslationManager(QObject):
    """翻译管理器（单例）。

    加载 JSON 翻译文件，提供 tr() 方法获取翻译字符串。
    语言切换时发出 language_changed 信号，视图刷新 UI。
    """

    language_changed = pyqtSignal(str)

    _instance: Optional["TranslationManager"] = None

    def __init__(self):
        if TranslationManager._instance is not None:
            raise RuntimeError("TranslationManager 已初始化，请使用 TranslationManager.instance()")
        super().__init__()
        self._translations: dict = {}
        self._current_language = "zh_CN"
        TranslationManager._instance = self

    @classmethod
    def instance(cls) -> "TranslationManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def current_language(self) -> str:
        return self._current_language

    def load_language(self, lang_code: str):
        """加载指定语言的翻译文件。

        Args:
            lang_code: 语言代码，如 'zh_CN', 'en_US'
        """
        file_path = _TRANSLATIONS_DIR / f"{lang_code}.json"
        if not file_path.exists():
            logger.warning("翻译文件不存在: %s，回退到 zh_CN", file_path)
            file_path = _TRANSLATIONS_DIR / "zh_CN.json"

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self._translations = json.load(f)
            self._current_language = lang_code
            logger.info("已加载翻译: %s (%d 条)", lang_code, len(self._translations))
        except Exception as e:
            logger.error("加载翻译文件失败: %s", e)
            self._translations = {}

    def tr(self, key: str, default: str = "") -> str:
        """获取翻译后的字符串。

        Args:
            key: 翻译键，如 'file.back_button'
            default: 未找到翻译时的默认值（中文）

        Returns:
            翻译后的字符串
        """
        return self._translations.get(key, default) if default else self._translations.get(key, key)

    def switch_language(self, lang_code: str):
        """切换语言并通知所有视图刷新。

        Args:
            lang_code: 语言代码
        """
        self.load_language(lang_code)
        self.language_changed.emit(lang_code)


# ---- 便捷函数 ----

# 全局翻译管理器实例（在应用启动时初始化）
_i18n: Optional[TranslationManager] = None


def init_i18n(lang_code: str = "zh_CN"):
    """初始化国际化模块。

    Args:
        lang_code: 初始语言代码
    """
    global _i18n
    _i18n = TranslationManager.instance()
    _i18n.load_language(lang_code)
    return _i18n


def tr(key: str, default: str = "") -> str:
    """获取翻译字符串（便捷函数）。

    用法:
        from ..common.i18n import tr
        label = QLabel(tr("file.back_button", "返回上一级"))

    Args:
        key: 翻译键
        default: 默认中文文本
    """
    if _i18n is None:
        return default if default else key
    return _i18n.tr(key, default)


def current_language() -> str:
    """获取当前语言代码。"""
    if _i18n is None:
        return "zh_CN"
    return _i18n.current_language
