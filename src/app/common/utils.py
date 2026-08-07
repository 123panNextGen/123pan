"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

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
