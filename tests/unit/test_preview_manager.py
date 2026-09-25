"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from src.app.preview import preview_manager
from src.app.preview import audio_preview


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class TestPreviewManager:
    def test_map_is_built_without_crashing(self):
        """_PREVIEWER_MAP 初始化后必须可构建（回归：None.update 崩溃）。"""
        assert preview_manager.get_previewer_for_file("a.png") is not None
        assert preview_manager._PREVIEWER_MAP is not None

    def test_known_extensions_resolve(self):
        for name in ("a.png", "a.txt", "a.mp3", "a.pdf", "a.mp4"):
            assert preview_manager.get_previewer_for_file(name) is not None

    def test_unsupported_extension(self):
        assert preview_manager.get_previewer_for_file("a.unknownext") is None
        assert preview_manager.get_previewer_for_file("") is None

    def test_supported_extensions_nonempty(self):
        exts = preview_manager.get_supported_extensions()
        assert "png" in exts
        assert "mp3" in exts
        assert "pdf" in exts


class TestAudioPreview:
    def test_error_shown_when_multimedia_missing(self, qapp, monkeypatch, tmp_path):
        """多媒体不可用时错误提示必须真正显示出来。"""
        monkeypatch.setattr(audio_preview, "_HAS_MULTIMEDIA", False)
        widget = audio_preview.AudioPreviewWidget(str(tmp_path / "a.mp3"))
        texts = [lbl.text() for lbl in widget.findChildren(QLabel)]
        assert any("多媒体" in t for t in texts)

    def test_state_labels(self, qapp, tmp_path):
        if not audio_preview._HAS_MULTIMEDIA:
            pytest.skip("QtMultimedia 不可用")
        widget = audio_preview.AudioPreviewWidget(str(tmp_path / "a.mp3"))
        states = audio_preview.QMediaPlayer.PlaybackState
        widget._on_state_changed(states.PlayingState)
        assert widget._status_label.text() == "正在播放"
        widget._on_state_changed(states.PausedState)
        assert widget._status_label.text() == "已暂停"
        widget._on_state_changed(states.StoppedState)
        assert widget._status_label.text() == "准备就绪"
        widget.cleanup()
