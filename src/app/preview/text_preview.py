"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPlainTextEdit,
)

from qfluentwidgets import BodyLabel

from ..common.log import get_logger

logger = get_logger(__name__)

# 大文件阈值（超过此大小使用分块加载）
_LARGE_TEXT_THRESHOLD = 5 * 1024 * 1024  # 5MB
# 每次加载的块大小
_CHUNK_SIZE = 1024 * 1024  # 1MB

# 编码检测顺序（UTF-8 优先，然后是常见中文编码）
_ENCODINGS = ("utf-8", "gbk", "gb2312", "gb18030", "latin-1")


def _detect_encoding(file_path):
    """检测文件编码（简单 BOM + 尝试解码）。"""
    with open(file_path, "rb") as f:
        raw = f.read(3)

    # BOM 检测
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"

    # 尝试解码
    for enc in _ENCODINGS:
        try:
            with open(file_path, "r", encoding=enc) as f:
                f.read(4096)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue

    return "latin-1"  # 最终回退


class TextPreviewWidget(QWidget):
    """文本预览组件。

    支持格式：txt, log, py, json, xml, md, csv, cfg, 及常见代码文件。
    """

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self._file_path = file_path

        self._setup_ui()
        self._load_text()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 文件信息栏
        file_size = Path(self._file_path).stat().st_size
        size_str = self._format_size(file_size)
        info_label = BodyLabel(
            f"  {Path(self._file_path).name}  ({size_str})"
        )
        info_label.setStyleSheet("padding: 4px 8px;")
        layout.addWidget(info_label)

        # 文本编辑器
        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        # 等宽字体
        font = QFont("Consolas, Monaco, 'Courier New', monospace", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._editor.setFont(font)

        # 样式
        self._editor.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                selection-background-color: #264f78;
            }
            """
        )

        layout.addWidget(self._editor)

    def _load_text(self):
        """加载文本文件内容。"""
        try:
            encoding = _detect_encoding(self._file_path)
            logger.debug("文本编码检测: %s → %s", self._file_path, encoding)

            file_size = Path(self._file_path).stat().st_size

            if file_size <= _LARGE_TEXT_THRESHOLD:
                # 小文件：直接全部加载
                with open(self._file_path, "r", encoding=encoding) as f:
                    content = f.read()
                self._editor.setPlainText(content)
            else:
                # 大文件：分块加载
                logger.debug(
                    "大文件分块加载: %s (%.1f MB)",
                    self._file_path,
                    file_size / 1024 / 1024,
                )
                self._load_large_file(encoding)

        except Exception as e:
            logger.error("文本加载失败: %s: %s", self._file_path, e)
            self._editor.setPlainText(f"[加载失败] {e}")

    def _load_large_file(self, encoding):
        """分块加载大文件，避免 UI 卡顿。"""
        try:
            with open(self._file_path, "r", encoding=encoding) as f:
                chunk = f.read(_CHUNK_SIZE)
                while chunk:
                    self._editor.insertPlainText(chunk)
                    # 让 Qt 处理事件循环
                    from PySide6.QtWidgets import QApplication
                    QApplication.processEvents()
                    chunk = f.read(_CHUNK_SIZE)
        except Exception as e:
            self._editor.appendPlainText(f"\n[读取中断] {e}")

    @staticmethod
    def _format_size(size):
        """格式化文件大小。"""
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def cleanup(self):
        """清理资源。"""
        pass
