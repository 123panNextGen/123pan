"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

from qfluentwidgets import FluentIcon as FIF

from ..common.i18n import tr
from .icons import icon


def format_date_text(ts):
    """将时间戳格式化为 'YYYY-MM-DD HH:MM'，非法值返回空串。"""
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return ""


class FileTableManager:
    """文件列表表格管理器。

    职责：渲染行、客户端排序、搜索过滤、空状态提示、按 ID 查找。
    不直接发起网络请求，由 FileInterface 驱动。
    """

    # 排序模式（与表头列号一致）
    SORT_NAME = 0
    SORT_SIZE = 2
    SORT_DATE = 3

    def __init__(self, table, state_label):
        self.table = table
        self.state_label = state_label
        # 当前目录完整列表（搜索过滤的基准数据）
        self.current_items = []
        # file_id -> 文件详情 索引（O(1) 查找）
        self.index_by_id = {}
        # 排序模式与方向
        self.sort_mode = self.SORT_NAME
        self.sort_ascending = True
        # 搜索文本（小写）
        self.search_text = ""

    # ---- 渲染 ----

    def set_items(self, items, update_cache=True):
        """渲染文件列表（批量操作，避免大量文件时逐行重绘卡死）。

        update_cache=False 时不覆盖 current_items/index_by_id，
        用于搜索过滤场景，避免过滤结果覆盖完整列表缓存。
        """
        if update_cache:
            self.current_items = items
            self.index_by_id = {
                str(item.get("FileId")): item for item in items
            }

        table = self.table
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        try:
            count = len(items)
            table.setRowCount(count)

            folder_icon = icon(FIF.FOLDER)
            file_icon = icon(FIF.DOCUMENT)

            for row, file_item in enumerate(items):
                file_name = file_item.get("FileName", "")
                file_type = int(file_item.get("Type", 0))
                file_size = int(file_item.get("Size", 0) or 0)
                file_id = int(file_item.get("FileId", 0) or 0)

                type_text = (
                    tr("file.type_folder", "文件夹")
                    if file_type == 1 else tr("file.type_file", "文件")
                )
                size_text = format_size_text(file_size)

                # 复用已有的 QTableWidgetItem，没有才新建
                name_item = table.item(row, 0)
                if name_item is None:
                    name_item = QTableWidgetItem()
                    table.setItem(row, 0, name_item)
                name_item.setText(file_name)
                # 长文件名被列宽截断时，悬停显示完整名称
                name_item.setToolTip(file_name)
                name_item.setData(Qt.ItemDataRole.UserRole, file_id)
                name_item.setData(Qt.ItemDataRole.UserRole + 1, file_type)
                name_item.setIcon(folder_icon if file_type == 1 else file_icon)

                type_item = table.item(row, 1)
                if type_item is None:
                    type_item = QTableWidgetItem()
                    table.setItem(row, 1, type_item)
                type_item.setText(type_text)

                size_item = table.item(row, 2)
                if size_item is None:
                    size_item = QTableWidgetItem()
                    table.setItem(row, 2, size_item)
                size_item.setText(size_text)

                # 日期列：优先使用 UpdateAt，回退到 CreateAt
                update_at = file_item.get("UpdateAt", file_item.get("updateAt", 0))
                create_at = file_item.get("CreateAt", file_item.get("createAt", 0))
                ts = update_at or create_at or 0
                date_item = table.item(row, 3)
                if date_item is None:
                    date_item = QTableWidgetItem()
                    table.setItem(row, 3, date_item)
                date_item.setText(format_date_text(ts))
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)

    # ---- 排序 ----

    def sort(self, items):
        """客户端排序：文件夹始终在前。"""
        folders = []
        files = []
        for item in items:
            if int(item.get("Type", 0)) == 1:
                folders.append(item)
            else:
                files.append(item)

        reverse = not self.sort_ascending
        if self.sort_mode == self.SORT_NAME:  # 按名称
            key_func = lambda x: x.get("FileName", "").lower()
            folders.sort(key=key_func, reverse=reverse)
            files.sort(key=key_func, reverse=reverse)
        elif self.sort_mode == self.SORT_SIZE:  # 按大小
            folders.sort(key=lambda x: int(x.get("Size", 0) or 0), reverse=reverse)
            files.sort(key=lambda x: int(x.get("Size", 0) or 0), reverse=reverse)
        elif self.sort_mode == self.SORT_DATE:  # 按日期
            def _date_key(item):
                ts = (
                    item.get("UpdateAt", item.get("updateAt", 0))
                    or item.get("CreateAt", item.get("createAt", 0))
                    or 0
                )
                return int(ts)

            folders.sort(key=_date_key, reverse=reverse)
            files.sort(key=_date_key, reverse=reverse)

        return folders + files

    # ---- 搜索 ----

    def apply_search(self, loading):
        """按当前 search_text 过滤并渲染（不覆盖完整列表缓存）。"""
        if not self.search_text:
            sorted_items = self.sort(self.current_items)
            self.set_items(sorted_items)
        else:
            filtered = [
                item for item in self.current_items
                if self.search_text in item.get("FileName", "").lower()
            ]
            sorted_items = self.sort(filtered)
            self.set_items(sorted_items, update_cache=False)
        self.update_state(len(sorted_items), loading)

    # ---- 空状态 ----

    def update_state(self, count, loading):
        """更新表格空状态/加载提示（覆盖层）。"""
        if count > 0:
            self.state_label.hide()
            return
        if self.search_text:
            self.state_label.setText(tr("file.state_no_result", "没有匹配的文件"))
        elif loading:
            self.state_label.setText(tr("file.state_loading", "加载中..."))
        else:
            self.state_label.setText(tr("file.state_empty", "此文件夹为空"))
        self.state_label.show()

    # ---- 查找 ----

    def find_by_id(self, file_id):
        """从当前目录索引中查找文件详情（O(1)）。"""
        return self.index_by_id.get(str(file_id))


def format_size_text(size):
    """文件大小格式化（延迟导入避免循环依赖）。"""
    from ..common.utils import format_file_size

    return format_file_size(size)
