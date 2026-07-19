"""
音频预览器。

复用 QMediaPlayer（与视频预览共享同一套 API），仅使用音频输出：
- 不需要额外依赖
- 播放/暂停、进度显示、音量控制
- 不显示视频画面（纯音频模式）
"""

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
)

from qfluentwidgets import TransparentToolButton, FluentIcon as FIF, StrongBodyLabel

from ..common.log import get_logger

logger = get_logger(__name__)

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    _HAS_MULTIMEDIA = True
except ImportError:
    _HAS_MULTIMEDIA = False


class AudioPreviewWidget(QWidget):
    """音频预览组件。

    支持格式：mp3, wav, flac, ogg, aac, wma, m4a（取决于系统编解码器）。
    """

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._player = None
        self._audio_output = None
        self._is_playing = False
        self._duration_ms = 0
        self._slider_dragging = False
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(200)

        if not _HAS_MULTIMEDIA:
            self._show_error("PyQt6 多媒体模块不可用，无法预览音频。")
            return

        self._setup_ui()
        self._setup_player()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 文件信息
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        filename = Path(self._file_path).name
        self._title_label = StrongBodyLabel(filename)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        info_layout.addWidget(self._title_label)

        self._status_label = QLabel("准备就绪")
        self._status_label.setStyleSheet("color: #888; font-size: 13px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self._status_label)

        layout.addLayout(info_layout)
        layout.addStretch()

        # 进度条
        self._progress_slider = QSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setRange(0, 0)
        self._progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self._progress_slider.sliderReleased.connect(self._on_slider_released)
        layout.addWidget(self._progress_slider)

        # 时间标签
        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setStyleSheet("color: #888; font-size: 12px;")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._time_label)

        # 控制按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self._play_btn = TransparentToolButton(FIF.PLAY.icon(), self)
        self._play_btn.setFixedSize(56, 56)
        self._play_btn.setToolTip("播放/暂停")
        self._play_btn.clicked.connect(self._toggle_play)
        btn_layout.addWidget(self._play_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()

        # 音量行
        vol_layout = QHBoxLayout()
        vol_layout.setSpacing(8)
        vol_layout.addStretch()

        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("font-size: 14px;")
        vol_layout.addWidget(vol_icon)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedWidth(120)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        vol_layout.addWidget(self._volume_slider)

        vol_layout.addStretch()
        layout.addLayout(vol_layout)

        self.setMinimumSize(350, 280)

    def _setup_player(self):
        """初始化音频播放器。"""
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(0.8)
        self._player.setAudioOutput(self._audio_output)

        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.errorOccurred.connect(self._on_error)

        self._position_timer.timeout.connect(self._update_position)

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
        if self._is_playing:
            self._status_label.setText("正在播放")
        else:
            self._status_label.setText("已暂停")

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

    def _update_position(self):
        if self._player and not self._slider_dragging:
            pos = self._player.position()
            self._update_time_label(pos)

    def _on_slider_pressed(self):
        self._slider_dragging = True

    def _on_slider_released(self):
        self._slider_dragging = False
        if self._player:
            self._player.setPosition(self._progress_slider.value())

    def _on_volume_changed(self, value):
        if self._audio_output:
            self._audio_output.setVolume(value / 100.0)

    def _on_error(self, error, error_string):
        logger.error("音频播放错误: %s: %s", error, error_string)
        self._show_error(f"播放失败: {error_string}")

    def _update_time_label(self, position_ms):
        def _fmt(ms):
            s = ms // 1000
            return f"{s // 60:02d}:{s % 60:02d}"

        self._time_label.setText(
            f"{_fmt(position_ms)} / {_fmt(self._duration_ms)}"
        )

    def _show_error(self, message):
        layout = self.layout()
        if layout:
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
        self._position_timer.stop()
