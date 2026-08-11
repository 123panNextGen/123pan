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


def format_speed(bps):
    """将字节/秒格式化为可读速度字符串。

    Args:
        bps: 每秒传输字节数（<=0 时显示占位符 "--"）

    Returns:
        格式化后的速度字符串，如 "1.5 MB/s"、"256 KB/s"、"--"
    """
    if bps <= 0:
        return "--"
    return format_file_size(bps) + "/s"


def configure_resizable_header(table, stretch_column=0, default_widths=None):
    """配置表格表头：所有列可交互调整列宽，指定列吸收多余宽度。

    所有列默认可拖动调整宽度；表格变宽（窗口 resize）时，
    stretch_column 自动吸收多余宽度，避免右侧出现空白。
    使用该工具后无需再手动 setSectionResizeMode。

    Args:
        table: 表格控件（QTableWidget / qfluentwidgets.TableWidget）
        stretch_column: 吸收多余宽度的列号（默认 0）
        default_widths: {列号: 初始宽度}，设置部分列的初始宽度

    Returns:
        callable: stretch() 函数，可在界面 resize 时主动调用
        （内部已自动监听表格 resize，通常无需手动调用）
    """
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QHeaderView

    header = table.horizontalHeader()
    if header is None:
        return lambda: None

    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setMinimumSectionSize(40)
    if default_widths:
        for col, width in default_widths.items():
            try:
                header.resizeSection(int(col), int(width))
            except (TypeError, ValueError):
                pass

    def _stretch():
        try:
            if header is None or header.count() == 0:
                return
            total = sum(header.sectionSize(i) for i in range(header.count()))
            extra = header.viewport().width() - total
            if extra > 10:
                header.resizeSection(
                    stretch_column, header.sectionSize(stretch_column) + extra
                )
        except RuntimeError:
            # 表格销毁过程中 header 已被删除
            pass

    class _StretchFilter(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Resize:
                _stretch()
            return False

    table.installEventFilter(_StretchFilter(table))
    _stretch()
    return _stretch
