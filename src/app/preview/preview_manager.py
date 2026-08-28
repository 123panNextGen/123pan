"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""


from .image_preview import ImagePreviewWidget
from .video_preview import VideoPreviewWidget
from .audio_preview import AudioPreviewWidget
from .text_preview import TextPreviewWidget
from .pdf_preview import PdfPreviewWidget

from pathlib import Path


# 文件扩展名 → 预览器映射
_PREVIEWER_MAP = None


def _build_previewer_map():
    """构建扩展名到预览器类的映射表（懒加载）。"""
    if _PREVIEWER_MAP is not None:
        return _PREVIEWER_MAP

    previewer_map = {}

    # 图片格式
    for ext in ("png", "jpg", "jpeg", "webp", "gif", "bmp", "svg", "ico", "tiff", "tif"):
        previewer_map[ext] = ImagePreviewWidget

    # 视频格式
    for ext in ("mp4", "mkv", "webm", "avi", "mov", "flv", "wmv", "m4v", "3gp"):
        previewer_map[ext] = VideoPreviewWidget

    # 音频格式
    for ext in ("mp3", "wav", "flac", "ogg", "aac", "wma", "m4a", "opus", "ape"):
        previewer_map[ext] = AudioPreviewWidget

    # 文本格式
    for ext in (
        "txt", "log", "py", "json", "xml", "md", "csv", "ini", "cfg",
        "yml", "yaml", "toml", "sh", "bat", "ps1", "sql", "html", "css",
        "js", "ts", "c", "cpp", "h", "hpp", "java", "kt", "rs", "go",
        "rb", "php", "lua", "r", "swift", "scala", "conf", "env",
    ):
        previewer_map[ext] = TextPreviewWidget

    # PDF 格式
    for ext in ("pdf",):
        previewer_map[ext] = PdfPreviewWidget

    _PREVIEWER_MAP.update(previewer_map)
    return _PREVIEWER_MAP


def get_previewer_for_file(filename):
    """根据文件名获取对应的预览器类。

    Args:
        filename: 文件名（含扩展名）

    Returns:
        预览器 Widget 类，如果不支持则返回 None
    """
    if not filename:
        return None

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not ext:
        return None

    _build_previewer_map()
    return _PREVIEWER_MAP.get(ext)


def get_supported_extensions():
    """获取所有支持预览的文件扩展名列表。"""
    _build_previewer_map()
    return sorted(_PREVIEWER_MAP.keys())


def is_preview_supported(filename):
    """检查文件是否支持预览。"""
    return get_previewer_for_file(filename) is not None


def create_preview_widget(file_path, mime_type=""):  # pylint: disable=unused-argument
    """根据文件路径创建预览 Widget。

    Args:
        file_path: 本地文件路径
        mime_type: MIME 类型（可选，作为后备判断依据）

    Returns:
        (QWidget, error_message): 预览组件和错误信息元组。
        成功时 error_message 为空字符串。
        不支持时返回 (None, "不支持的文件格式")。
    """

    path = Path(file_path)
    if not path.exists():
        return None, f"文件不存在: {file_path}"

    filename = path.name
    previewer_cls = get_previewer_for_file(filename)

    if previewer_cls is None:
        return None, f"不支持预览的文件格式: {path.suffix or '(无扩展名)'}"

    try:
        widget = previewer_cls(str(path))
        return widget, ""
    except Exception as e:
        return None, f"创建预览器失败: {e}"
