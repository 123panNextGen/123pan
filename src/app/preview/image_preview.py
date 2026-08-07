"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""


from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QSize, QTimer
from PySide6.QtGui import (
    QPixmap,
    QImageReader,
    QMovie,
    QPainter,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QLabel
)

from qfluentwidgets import TransparentToolButton, FluentIcon as FIF

from ..common.log import get_logger

logger = get_logger(__name__)

# 大图阈值：超过此尺寸使用 QImageReader 的 scaledSize 预缩放
_LARGE_IMAGE_THRESHOLD = 20 * 1024 * 1024  # 20MB
_MAX_PREVIEW_PIXELS = 4096  # 最大预览边长（像素）


def _get_image_size(file_path):
    """快速获取图片尺寸（不加载完整图片）。"""
    reader = QImageReader(file_path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        return size.width(), size.height()
    return None, None


class _ScalableGraphicsView(QGraphicsView):
    """支持滚轮缩放的自定义 QGraphicsView。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(Qt.GlobalColor.transparent)

        self._zoom_factor = 1.0
        self._min_zoom = 0.05
        self._max_zoom = 10.0

    def reset_zoom(self):
        """重置缩放并适应窗口。"""
        self._zoom_factor = 1.0
        self.resetTransform()
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_in(self):
        self._apply_zoom(1.25)

    def zoom_out(self):
        self._apply_zoom(0.8)

    def _apply_zoom(self, factor):
        new_zoom = self._zoom_factor * factor
        if new_zoom < self._min_zoom or new_zoom > self._max_zoom:
            return
        self._zoom_factor = new_zoom
        self.scale(factor, factor)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        if self._zoom_factor == 1.0:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class ImagePreviewWidget(QWidget):
    """图片预览组件。

    支持格式：PNG, JPG, JPEG, WebP, GIF, BMP, SVG, ICO, TIFF
    """

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._movie = None
        self._pixmap_item = None
        self._is_gif = Path(file_path).suffix.lower() == ".gif"

        self._setup_ui()
        self._load_image()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 4)
        toolbar.setSpacing(4)

        self._info_label = QLabel()
        self._info_label.setStyleSheet("color: #888; font-size: 12px;")
        toolbar.addWidget(self._info_label)

        toolbar.addStretch()

        self._zoom_out_btn = TransparentToolButton(FIF.ZOOM_OUT.icon(), self)
        self._zoom_out_btn.setFixedSize(32, 32)
        self._zoom_out_btn.setToolTip("缩小 (Ctrl+滚轮)")
        toolbar.addWidget(self._zoom_out_btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(48)
        self._zoom_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self._zoom_label.setStyleSheet("color: #888; font-size: 12px;")
        toolbar.addWidget(self._zoom_label)

        self._zoom_in_btn = TransparentToolButton(FIF.ZOOM_IN.icon(), self)
        self._zoom_in_btn.setFixedSize(32, 32)
        self._zoom_in_btn.setToolTip("放大 (Ctrl+滚轮)")
        toolbar.addWidget(self._zoom_in_btn)

        self._fit_btn = TransparentToolButton(FIF.FIT_PAGE.icon(), self)
        self._fit_btn.setFixedSize(32, 32)
        self._fit_btn.setToolTip("适应窗口")
        toolbar.addWidget(self._fit_btn)

        layout.addLayout(toolbar)

        # 图形视图
        self._scene = QGraphicsScene(self)
        self._view = _ScalableGraphicsView(self)
        self._view.setScene(self._scene)
        layout.addWidget(self._view)

        # 连接信号
        self._zoom_in_btn.clicked.connect(self._view.zoom_in)
        self._zoom_out_btn.clicked.connect(self._view.zoom_out)
        self._fit_btn.clicked.connect(self._view.reset_zoom)

    def _load_image(self):
        """加载图片：GIF 使用 QMovie，其他使用 QPixmap。"""
        try:
            if self._is_gif:
                self._load_gif()
            else:
                self._load_static_image()
        except Exception as e:
            logger.error("图片加载失败: %s: %s", self._file_path, e)
            self._show_error(f"图片加载失败: {e}")

    def _load_static_image(self):
        """加载静态图片，大图自动预缩放。"""
        file_size = Path(self._file_path).stat().st_size
        w, h = _get_image_size(self._file_path)

        pixmap = QPixmap()
        if file_size > _LARGE_IMAGE_THRESHOLD and w and h:
            # 大图：使用预缩放加载，降低内存占用
            max_dim = max(w, h)
            if max_dim > _MAX_PREVIEW_PIXELS:
                scale = _MAX_PREVIEW_PIXELS / max_dim
                scaled_size = QSize(int(w * scale), int(h * scale))
                reader = QImageReader(self._file_path)
                reader.setScaledSize(scaled_size)
                reader.setAutoTransform(True)
                img = reader.read()
                if img.isNull():
                    raise RuntimeError(reader.errorString())
                pixmap = QPixmap.fromImage(img)
                logger.debug("大图预缩放: %dx%d → %dx%d", w, h, scaled_size.width(), scaled_size.height())
            else:
                pixmap.load(self._file_path)
        else:
            pixmap.load(self._file_path)

        if pixmap.isNull():
            raise RuntimeError("无法解析图片文件")

        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(QRectF(pixmap.rect()))

        actual_w = pixmap.width()
        actual_h = pixmap.height()
        self._info_label.setText(
            f"{Path(self._file_path).name}  ({actual_w}×{actual_h})"
        )

        # 适应窗口
        QTimer.singleShot(50, self._view.reset_zoom)

    def _load_gif(self):
        """加载 GIF 动画。"""
        self._movie = QMovie(self._file_path)
        self._movie.setCacheMode(QMovie.CacheMode.CacheAll)

        # 使用第一帧作为占位，后续帧通过 QMovie 更新
        self._movie.jumpToFrame(0)
        first_frame = self._movie.currentPixmap()
        if first_frame.isNull():
            raise RuntimeError("无法解析 GIF 文件")

        self._pixmap_item = QGraphicsPixmapItem(first_frame)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(QRectF(first_frame.rect()))

        self._info_label.setText(
            f"{Path(self._file_path).name}  (GIF动画)"
        )

        # 连接帧更新
        self._movie.frameChanged.connect(self._on_gif_frame_changed)
        self._movie.start()

        QTimer.singleShot(50, self._view.reset_zoom)

    def _on_gif_frame_changed(self, frame_num):
        if self._pixmap_item and self._movie:
            self._pixmap_item.setPixmap(self._movie.currentPixmap())

    def _show_error(self, message):
        """显示错误信息。"""
        error_label = QLabel(message)
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setStyleSheet("color: #e74c3c; font-size: 14px; padding: 20px;")
        # 替换视图内容
        layout = self.layout()
        if layout:
            # 移除旧的 view
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget() is self._view:
                    layout.removeWidget(self._view)
                    self._view.hide()
                    break
            layout.addWidget(error_label)

    def cleanup(self):
        """清理资源（GIF 动画停止等）。"""
        if self._movie:
            self._movie.stop()
            self._movie = None
