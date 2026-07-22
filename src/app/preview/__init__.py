"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
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
