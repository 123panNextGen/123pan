"""
预览模块。

提供多媒体文件预览能力：
- 图片预览（ImagePreviewWidget）
- 视频预览（VideoPreviewWidget）
- 音频预览（AudioPreviewWidget）
- 文本预览（TextPreviewWidget）

使用 preview_manager 根据文件类型自动选择合适的预览器。
"""

from .preview_manager import (
    get_previewer_for_file,
    get_supported_extensions,
    is_preview_supported,
    create_preview_widget,
)
from .image_preview import ImagePreviewWidget
from .video_preview import VideoPreviewWidget
from .audio_preview import AudioPreviewWidget
from .text_preview import TextPreviewWidget

__all__ = [
    "get_previewer_for_file",
    "get_supported_extensions",
    "is_preview_supported",
    "create_preview_widget",
    "ImagePreviewWidget",
    "VideoPreviewWidget",
    "AudioPreviewWidget",
    "TextPreviewWidget",
]
