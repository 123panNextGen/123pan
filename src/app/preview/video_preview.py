"""
视频预览器。

使用 PyQt6.QtMultimediaWidgets 的 QMediaPlayer + QVideoWidget：
- 不需要额外依赖（PyQt6 内置）
- 支持常见视频格式（依赖系统编解码器）
- 播放/暂停、进度拖动、音量控制

注意：PyQt6 的 Qt Multimedia 使用系统后端（Windows: WMF, Linux: GStreamer）。
如果系统缺少编解码器，部分格式可能无法播放。
"""

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
)

from qfluentwidgets import TransparentToolButton, FluentIcon as FIF

from ..common.log import get_logger

logger = get_logger(__name__)

# 尝试导入 Qt Multimedia 模块
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget

    _HAS_MULTIMEDIA = True
except ImportError:
    _HAS_MULTIMEDIA = False
    logger.warning("PyQt6.QtMultimediaWidgets 不可用，视频预览将被禁用")


class VideoPreviewWidget(QWidget):
    """视频预览组件。

    支持格式：mp4, mkv, webm, avi, mov, flv, wmv（取决于系统编解码器）。
    """

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._player = None
        self._audio_output = None
        self._video_widget = None
        self._is_playing = False
        self._duration_ms = 0
        self._slider_dragging = False

        if not _HAS_MULTIMEDIA:
            self._show_error("PyQt6 多媒体模块不可用，无法预览视频。")
            return

        self._setup_ui()
        self._setup_player()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 视频显示区域
        self._video_widget = QVideoWidget(self)
        self._video_widget.setMinimumSize(320, 180)
        self._video_widget.setStyleSheet("background-color: #000;")
        layout.addWidget(self._video_widget, 1)

        # 控制栏
        control_layout = QVBoxLayout()
        control_layout.setContentsMargins(8, 4, 8, 8)
        control_layout.setSpacing(2)

        # 进度条
        self._progress_slider = QSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, 0)
        self._progress_slider.setTracking(True)
        self._progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self._progress_slider.sliderReleased.connect(self._on_slider_released)
        self._progress_slider.sliderMoved.connect(self._on_slider_moved)
        control_layout.addWidget(self._progress_slider)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self._play_btn = TransparentToolButton(FIF.PLAY.icon(), self)
        self._play_btn.setFixedSize(36, 36)
        self._play_btn.setToolTip("播放/暂停 (空格)")
        self._play_btn.clicked.connect(self._toggle_play)
        btn_layout.addWidget(self._play_btn)

        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setStyleSheet("color: #888; font-size: 12px;")
        self._time_label.setFixedWidth(120)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(self._time_label)

        btn_layout.addStretch()

        # 音量控制
        volume_label = QLabel("🔊")
        volume_label.setStyleSheet("font-size: 14px;")
        btn_layout.addWidget(volume_label)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedWidth(80)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        btn_layout.addWidget(self._volume_slider)

        control_layout.addLayout(btn_layout)
        layout.addLayout(control_layout)

    def _setup_player(self):
        """初始化 QMediaPlayer。"""
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(0.8)
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)

        # 连接信号
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.errorOccurred.connect(self._on_error)

        # 加载视频
        url = QUrl.fromLocalFile(self._file_path)
        self._player.setSource(url)

    def _toggle_play(self):
        if not self._player:
            return
        if self._is_playing:
            self._player.pause()
        else:
            self._player.play()

    def _on_state_changed(self, state):
        self._is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        self._update_play_button()

    def _update_play_button(self):
        if self._is_playing:
            self._play_btn.setIcon(FIF.PAUSE.icon())
        else:
            self._play_btn.setIcon(FIF.PLAY.icon())

    def _on_duration_changed(self, duration_ms):
        self._duration_ms = duration_ms
        self._progress_slider.setRange(0, duration_ms)
        self._update_time_label(0)

    def _on_position_changed(self, position_ms):
        if not self._slider_dragging:
            self._progress_slider.setValue(position_ms)
        self._update_time_label(position_ms)

    def _on_slider_pressed(self):
        self._slider_dragging = True

    def _on_slider_released(self):
        self._slider_dragging = False
        if self._player:
            self._player.setPosition(self._progress_slider.value())

    def _on_slider_moved(self, position):
        self._update_time_label(position)

    def _on_volume_changed(self, value):
        if self._audio_output:
            self._audio_output.setVolume(value / 100.0)

    def _on_error(self, error, error_string):
        logger.error("视频播放错误: %s: %s", error, error_string)
        self._show_error(f"播放失败: {error_string}")

    def _update_time_label(self, position_ms):
        def _fmt(ms):
            s = ms // 1000
            return f"{s // 60:02d}:{s % 60:02d}"

        self._time_label.setText(
            f"{_fmt(position_ms)} / {_fmt(self._duration_ms)}"
        )

    def _show_error(self, message):
        """显示错误信息。"""
        layout = self.layout()
        if layout:
            # 清空现有控件
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
            error_label = QLabel(message)
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet(
                "color: #e74c3c; font-size: 14px; padding: 40px;"
            )
            layout.addWidget(error_label)

    def cleanup(self):
        """清理播放器资源。"""
        if self._player:
            self._player.stop()
            self._player = None
        self._audio_output = None
