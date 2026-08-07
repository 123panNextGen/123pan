"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""


from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
)
from qfluentwidgets import TransparentToolButton, FluentIcon as FIF

from ..common.log import get_logger

logger = get_logger(__name__)

# 尝试导入 QtPdfWidgets 模块
try:
    from PySide6.QtPdfWidgets import QPdfView
    from PySide6.QtPdf import QPdfDocument

    _HAS_PDF = True
except ImportError:
    _HAS_PDF = False
    logger.warning("PySide6.QtPdfWidgets 不可用，PDF 预览将被禁用")


class PdfPreviewWidget(QWidget):
    """PDF 预览组件。

    使用 QtPdf 模块渲染 PDF 文档，支持缩放、页面导航。
    """

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._pdf_doc = None
        self._pdf_view = None

        if not _HAS_PDF:
            self._show_error("PySide6 PDF 模块不可用，无法预览 PDF。")
            return

        self._setup_ui()
        self._load_pdf()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(4)

        # 文件信息
        filename = Path(self._file_path).name
        self._title_label = QLabel(f"  {filename}")
        self._title_label.setStyleSheet("color: #888; font-size: 12px;")
        toolbar.addWidget(self._title_label)

        toolbar.addStretch()

        # 页面导航
        self._prev_page_btn = TransparentToolButton(FIF.CARE_LEFT_SOLID.icon(), self)
        self._prev_page_btn.setFixedSize(32, 32)
        self._prev_page_btn.setToolTip("上一页")
        toolbar.addWidget(self._prev_page_btn)

        self._page_label = QLabel("0 / 0")
        self._page_label.setFixedWidth(64)
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setStyleSheet("color: #888; font-size: 12px;")
        toolbar.addWidget(self._page_label)

        self._next_page_btn = TransparentToolButton(FIF.CARE_RIGHT_SOLID.icon(), self)
        self._next_page_btn.setFixedSize(32, 32)
        self._next_page_btn.setToolTip("下一页")
        toolbar.addWidget(self._next_page_btn)

        toolbar.addSpacing(12)

        # 缩放控制
        self._zoom_out_btn = TransparentToolButton(FIF.ZOOM_OUT.icon(), self)
        self._zoom_out_btn.setFixedSize(32, 32)
        self._zoom_out_btn.setToolTip("缩小")
        toolbar.addWidget(self._zoom_out_btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(48)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet("color: #888; font-size: 12px;")
        toolbar.addWidget(self._zoom_label)

        self._zoom_in_btn = TransparentToolButton(FIF.ZOOM_IN.icon(), self)
        self._zoom_in_btn.setFixedSize(32, 32)
        self._zoom_in_btn.setToolTip("放大")
        toolbar.addWidget(self._zoom_in_btn)

        self._fit_width_btn = TransparentToolButton(FIF.FIT_PAGE.icon(), self)
        self._fit_width_btn.setFixedSize(32, 32)
        self._fit_width_btn.setToolTip("适合宽度")
        toolbar.addWidget(self._fit_width_btn)

        layout.addLayout(toolbar)

        # PDF 视图
        self._pdf_view = QPdfView(self)
        self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        layout.addWidget(self._pdf_view)

        # 连接信号
        self._prev_page_btn.clicked.connect(self._prev_page)
        self._next_page_btn.clicked.connect(self._next_page)
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        self._fit_width_btn.clicked.connect(self._fit_width)

    def _load_pdf(self):
        """加载 PDF 文件。"""
        try:
            self._pdf_doc = QPdfDocument(self)
            self._pdf_doc.load(QUrl.fromLocalFile(self._file_path))

            if self._pdf_doc.status() != QPdfDocument.Status.Ready:
                self._show_error("PDF 文件加载失败或已损坏。")
                return

            self._pdf_view.setDocument(self._pdf_doc)

            # 更新页面信息
            total = self._pdf_doc.pageCount()
            self._page_label.setText(f"1 / {total}")

            # 监听页面变化更新标签
            self._pdf_view.pageNavigator().currentPageChanged.connect(
                self._on_page_changed
            )

            # 默认适合宽度
            self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

            logger.debug("PDF 加载成功: %s (%d 页)", self._file_path, total)

        except Exception as e:
            logger.error("PDF 加载失败: %s: %s", self._file_path, e)
            self._show_error(f"PDF 加载失败: {e}")

    def _on_page_changed(self, page):
        """页面切换时更新标签。"""
        total = self._pdf_doc.pageCount() if self._pdf_doc else 0
        self._page_label.setText(f"{page + 1} / {total}")

    def _prev_page(self):
        """跳转到上一页。"""
        nav = self._pdf_view.pageNavigator()
        if nav.currentPage() > 0:
            nav.jump(nav.currentPage() - 1, nav.currentLocation())

    def _next_page(self):
        """跳转到下一页。"""
        if not self._pdf_doc:
            return
        nav = self._pdf_view.pageNavigator()
        total = self._pdf_doc.pageCount()
        if nav.currentPage() < total - 1:
            nav.jump(nav.currentPage() + 1, nav.currentLocation())

    def _zoom_in(self):
        """放大。"""
        factor = self._pdf_view.zoomFactor()
        self._pdf_view.setZoomFactor(factor * 1.25)
        self._update_zoom_label()

    def _zoom_out(self):
        """缩小。"""
        factor = self._pdf_view.zoomFactor()
        self._pdf_view.setZoomFactor(factor * 0.8)
        self._update_zoom_label()

    def _fit_width(self):
        """适合宽度显示。"""
        self._pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self._update_zoom_label()

    def _update_zoom_label(self):
        """更新缩放百分比标签。"""
        pct = int(self._pdf_view.zoomFactor() * 100)
        self._zoom_label.setText(f"{pct}%")

    def _show_error(self, message):
        """显示错误信息。"""
        layout = self.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().hide()

        error_layout = QVBoxLayout(self)
        error_layout.setContentsMargins(20, 20, 20, 20)
        error_layout.addStretch()

        icon_label = QLabel("📄")
        icon_label.setStyleSheet("font-size: 48px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_layout.addWidget(icon_label)

        error_label = QLabel(message)
        error_label.setStyleSheet("color: #999; font-size: 14px;")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setWordWrap(True)
        error_layout.addWidget(error_label)

        error_layout.addStretch()

    def cleanup(self):
        """清理资源。"""
        if self._pdf_doc:
            self._pdf_doc.close()
            self._pdf_doc = None
