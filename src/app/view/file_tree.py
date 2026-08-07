"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem, QTreeWidgetItemIterator

from qfluentwidgets import FluentIcon as FIF

from ..common.i18n import tr
from .icons import icon


class FileTreeManager:
    """目录树管理器。

    职责：根节点构建、子文件夹懒加载、节点缓存、增量更新。
    异步加载通过 loader 回调交给 FileInterface 发起（保持无网络依赖）。
    """

    def __init__(self, tree):
        self.tree = tree
        # 目录 ID -> 树节点 缓存（避免每次全树迭代查找）
        self.item_cache = {}
        # 是否正在后台加载子文件夹
        self.is_loading = False

    # ---- 初始化 ----

    def init_tree(self):
        """重建目录树（清空缓存与节点）。"""
        self.tree.clear()
        self.item_cache.clear()

        root_item = QTreeWidgetItem([tr("file.root_dir", "根目录")])
        root_item.setIcon(0, icon(FIF.FOLDER))
        root_item.setData(0, Qt.ItemDataRole.UserRole, 0)
        root_item.setData(0, Qt.ItemDataRole.UserRole + 1, False)
        self.tree.addTopLevelItem(root_item)
        self.item_cache[0] = root_item

        self.add_placeholder(root_item)
        self.tree.expandItem(root_item)
        self.tree.setCurrentItem(root_item)

    @staticmethod
    def add_placeholder(parent_item):
        """添加占位子节点，触发展开以懒加载真实子文件夹。"""
        placeholder = QTreeWidgetItem([""])
        placeholder.setData(0, Qt.ItemDataRole.UserRole, None)
        parent_item.addChild(placeholder)

    # ---- 懒加载 ----

    def ensure_loaded(self, item, loader):
        """确保节点子文件夹已加载。

        Args:
            item: 待展开的树节点。
            loader: 回调 (dir_id, item)，由调用方发起异步加载，
                完成后调用 on_folder_loaded。
        """
        if self.is_loading:
            return

        loaded = item.data(0, Qt.ItemDataRole.UserRole + 1)
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if loaded or dir_id is None:
            return

        # 标记加载中并清空占位，后台加载子文件夹
        self.is_loading = True
        item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
        item.takeChildren()
        loader(int(dir_id), item)

    def on_folder_loaded(self, item, dir_id, folders, error):
        """子文件夹加载完成回调（主线程）。"""
        self.is_loading = False
        try:
            if error or not item.treeWidget():
                return
            if item.data(0, Qt.ItemDataRole.UserRole) != dir_id:
                return  # 用户已切换目录，丢弃过期结果
        except RuntimeError:
            return  # 控件已销毁

        for folder in folders:
            if int(folder.get("Type", 0)) != 1:
                continue

            child = QTreeWidgetItem([folder.get("FileName", "")])
            child.setIcon(0, icon(FIF.FOLDER))
            child_id = int(folder.get("FileId", 0))
            child.setData(0, Qt.ItemDataRole.UserRole, child_id)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, False)
            item.addChild(child)
            self.item_cache[child_id] = child

            self.add_placeholder(child)

    # ---- 查找 / 路径 ----

    def find_item(self, dir_id):
        """按目录 ID 查找树节点（优先缓存，失效时全树扫描兜底）。"""
        cached = self.item_cache.get(dir_id)
        if cached is not None:
            try:
                if cached.treeWidget() is self.tree:
                    return cached
            except RuntimeError:
                # 节点已被销毁，缓存失效
                self.item_cache.pop(dir_id, None)

        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == dir_id:
                self.item_cache[dir_id] = item
                return item
            iterator += 1

        return None

    @staticmethod
    def build_path_stack(item):
        """由树节点回溯构建 (dir_id, name) 路径栈（含根目录）。"""
        stack = []
        current = item
        while current is not None:
            name = current.text(0)
            dir_id = int(current.data(0, Qt.ItemDataRole.UserRole) or 0)
            stack.append((dir_id, name))
            current = current.parent()

        stack.reverse()
        return stack if stack else [(0, tr("file.root_dir", "根目录"))]

    # ---- 增量更新 ----

    def update_folders(self, dir_id, folder_items):
        """创建/重命名/删除操作后，增量刷新指定目录的子文件夹节点。"""
        current_item = self.find_item(dir_id)
        if current_item is None:
            return

        # 移除占位符
        for i in range(current_item.childCount()):
            child = current_item.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) is None:
                current_item.removeChild(child)
                break

        # 记录已有子节点
        existing_items = {}
        for i in range(current_item.childCount()):
            child = current_item.child(i)
            file_id = child.data(0, Qt.ItemDataRole.UserRole)
            if file_id:
                existing_items[file_id] = child
                self.item_cache[file_id] = child

        # 添加新的文件夹
        for folder in folder_items:
            file_id = int(folder.get("FileId", 0))
            file_name = folder.get("FileName", "")
            if file_id in existing_items:
                continue

            child = QTreeWidgetItem([file_name])
            child.setIcon(0, icon(FIF.FOLDER))
            child.setData(0, Qt.ItemDataRole.UserRole, file_id)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, False)
            current_item.addChild(child)
            self.item_cache[file_id] = child
            self.add_placeholder(child)
