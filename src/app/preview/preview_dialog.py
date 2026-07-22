"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""


import shutil
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    PushButton,
    ProgressBar,
    MessageBox,
    StrongBodyLabel,
    BodyLabel,
)

from .preview_manager import is_preview_supported, create_preview_widget
from ..common.log import get_logger

logger = get_logger(__name__)


class _DownloadPreviewThread(QThread):
    """后台线程：下载文件到临时目录。"""

    progress = pyqtSignal(int)  # 0-100
    finished = pyqtSignal(str, str)  # (local_path, error_message)
    status = pyqtSignal(str)

    def __init__(self, pan, file_info):
        super().__init__()
        self.pan = pan
        self.file_info = file_info

    def run(self):
        try:
            file_name = self.file_info.get("FileName", "unknown")
            self.status.emit(f"正在获取下载链接...")

            # 1. 获取下载链接
            download_url = self.pan.link_by_fileDetail(
                self.file_info, showlink=False
            )
            if isinstance(download_url, int):
                self.finished.emit("", f"获取下载链接失败 (code={download_url})")
                return

            self.status.emit(f"正在下载 {file_name}...")

            # 2. 下载到临时文件
            tmp_dir = tempfile.mkdtemp(prefix="123pan_preview_")
            tmp_path = Path(tmp_dir) / file_name

            file_size = int(self.file_info.get("Size", 0) or 0)

            if file_size > 0:
                self.pan.download_file(
                    download_url,
                    tmp_path,
                    file_size,
                    progress_callback=self._on_progress,
                )
            else:
                # 未知大小的简单下载
                self.pan.download_file(
                    download_url, tmp_path, file_size
                )

            if tmp_path.exists() and tmp_path.stat().st_size > 0:
                self.progress.emit(100)
                self.finished.emit(str(tmp_path), "")
            else:
                self.finished.emit("", "下载失败：文件为空")

        except Exception as e:
            logger.error("预览下载失败: %s", e)
            self.finished.emit("", str(e))

    def _on_progress(self, downloaded, total):
        if total > 0:
            pct = int(downloaded * 100 / total)
            self.progress.emit(pct)


class PreviewDialog(QDialog):
    """文件预览对话框。

    使用方式：
        dlg = PreviewDialog(pan, file_info, parent)
        dlg.exec()
    """

    def __init__(self, pan, file_info, parent=None):
        super().__init__(parent)
        self._pan = pan
        self._file_info = file_info
        self._tmp_dir = None
        self._tmp_file = None
        self._preview_widget = None
        self._download_thread = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(100)

        file_name = file_info.get("FileName", "文件预览")
        self.setWindowTitle(f"预览 - {file_name}")
        self.resize(900, 650)
        self.setMinimumSize(400, 300)

        self._setup_ui()
        self._start_download()

    def _setup_ui(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # 进度区域（下载时显示）
        self._progress_widget = QWidget()
        self._progress_widget.setObjectName("previewProgressWidget")
        progress_layout = QVBoxLayout(self._progress_widget)
        progress_layout.setContentsMargins(40, 40, 40, 40)
        progress_layout.setSpacing(16)

        self._status_label = StrongBodyLabel("准备下载...")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self._status_label)

        progress_layout.addSpacing(8)

        self._progress_bar = ProgressBar(self._progress_widget)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(24)
        progress_layout.addWidget(self._progress_bar)

        progress_layout.addSpacing(12)

        cancel_layout = QHBoxLayout()
        cancel_layout.addStretch()
        cancel_btn = PushButton("取消")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        cancel_layout.addWidget(cancel_btn)
        cancel_layout.addStretch()
        progress_layout.addLayout(cancel_layout)

        progress_layout.addStretch()
        self._main_layout.addWidget(self._progress_widget)

        # 预览内容区域（下载完成后显示，初始隐藏）
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._content_widget.hide()
        self._main_layout.addWidget(self._content_widget)

    def _start_download(self):
        """启动后台下载线程。"""
        file_name = self._file_info.get("FileName", "")

        if not is_preview_supported(file_name):
            MessageBox(
                "不支持预览",
                f"不支持预览此文件类型: {file_name}\n\n"
                "支持的格式包括：\n"
                "图片 (png/jpg/gif/webp/...) 、\n"
                "视频 (mp4/mkv/avi/...) 、\n"
                "音频 (mp3/wav/flac/...) 、\n"
                "文本 (txt/py/json/md/...)",
                self,
            ).exec()
            self.reject()
            return

        self._download_thread = _DownloadPreviewThread(self._pan, self._file_info)
        self._download_thread.progress.connect(self._on_download_progress)
        self._download_thread.status.connect(self._on_download_status)
        self._download_thread.finished.connect(self._on_download_finished)
        self._download_thread.start()

    def _on_download_progress(self, pct):
        self._progress_bar.setValue(pct)

    def _on_download_status(self, msg):
        self._status_label.setText(msg)

    def _on_download_finished(self, local_path, error):
        """下载完成回调。"""
        if error:
            self._status_label.setText(f"下载失败: {error}")
            self._status_label.setStyleSheet("color: #e74c3c;")
            return

        if not local_path:
            self._status_label.setText("下载失败: 文件为空")
            self._status_label.setStyleSheet("color: #e74c3c;")
            return

        self._tmp_file = local_path
        # 记下临时目录以便清理
        self._tmp_dir = str(Path(local_path).parent)

        logger.info("预览文件已下载: %s", local_path)

        # 隐藏进度区域
        self._progress_widget.hide()

        # 创建预览组件
        try:
            widget, err = create_preview_widget(local_path)
            if widget is None:
                self._show_content_error(f"无法预览: {err}")
                return

            self._preview_widget = widget
            self._content_layout.addWidget(widget)
            self._content_widget.show()

            # 延迟调整对话框大小以适应内容
            self._resize_timer.timeout.connect(self._auto_resize)
            self._resize_timer.start()

        except Exception as e:
            logger.error("创建预览组件失败: %s", e)
            self._show_content_error(f"创建预览失败: {e}")

    def _show_content_error(self, message):
        """在内容区域显示错误。"""
        self._progress_widget.hide()
        error_label = BodyLabel(message)
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setStyleSheet(
            "color: #e74c3c; padding: 40px;"
        )
        self._content_layout.addWidget(error_label)
        self._content_widget.show()

    def _auto_resize(self):
        """根据屏幕大小自动调整窗口。"""
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            screen_size = screen.availableSize()
            self.resize(
                min(int(screen_size.width() * 0.75), 1200),
                min(int(screen_size.height() * 0.8), 900),
            )

    def reject(self):
        """关闭对话框时清理资源。"""
        self._cleanup()
        super().reject()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

    def _cleanup(self):
        """清理预览资源。"""
        # 停止下载线程
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.terminate()
            self._download_thread.wait(2000)

        # 清理预览组件
        if self._preview_widget:
            try:
                self._preview_widget.cleanup()
            except Exception:
                pass
            self._preview_widget = None

        # 清理临时文件
        if self._tmp_dir:
            try:
                shutil.rmtree(self._tmp_dir, ignore_errors=True)
                logger.debug("临时预览文件已清理: %s", self._tmp_dir)
            except Exception as e:
                logger.warning("清理临时文件失败: %s", e)
            self._tmp_dir = None
            self._tmp_file = None
