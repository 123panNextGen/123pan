"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""


from pathlib import Path


def format_file_size(size):
    """将字节数格式化为人类可读的文件大小字符串。

    Args:
        size: 文件大小（字节）

    Returns:
        格式化后的字符串，如 "1.5 GB"、"256 KB"
    """
    if size < 0:
        return "0 B"
    if size == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    value = float(size)
    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1

    # B 级别显示整数，其他级别保留一位小数（兼容旧版行为）
    rounded = round(value, 2)
    if unit_index == 0:
        return f"{int(rounded)} {units[unit_index]}"
    return f"{rounded} {units[unit_index]}"


class FileDataManager:
    """文件数据处理器 - 处理与文件相关的业务逻辑，不涉及 UI。"""

    @staticmethod
    def get_file_type_name(file_type):
        """根据文件类型返回类型名称。"""
        return "文件夹" if file_type == 1 else "文件"

    @staticmethod
    def get_file_extension(filename):
        """获取文件扩展名（小写）。"""
        return Path(filename).suffix.lower()

    @staticmethod
    def validate_file_exists(file_path):
        """验证文件是否存在。"""
        return Path(file_path).is_file()

    @staticmethod
    def is_duplicate_filename(pan_instance, filename):
        """检查是否存在同名文件。"""
        return any(item.get("FileName") == filename for item in pan_instance.list)

    @staticmethod
    def format_file_size_value(size):
        """格式化文件大小（format_file_size 的别名）。"""
        return format_file_size(size)
