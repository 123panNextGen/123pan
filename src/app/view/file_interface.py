import importlib

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QTreeWidgetItemIterator,
    QTableWidgetItem
)

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import BreadcrumbBar, TableWidget, TreeWidget, PushButton

from ..common.style_sheet import StyleSheet

Pan123 = importlib.import_module("app.common.api").Pan123


class FileInterface(QWidget):
    """文件页面（仅浏览）"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("FileInterface")

        self.pan = None
        self.current_dir_id = 0
        self.path_stack = [(0, "根目录")]
        self.is_loading_tree = False
        self.is_updating_breadcrumb = False

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(24, 20, 24, 24)
        self.mainLayout.setSpacing(12)

        self.__createTopBar()
        self.__createContent()
        self.__initWidget()

    def __createTopBar(self):
        self.topBarFrame = QFrame(self)
        self.topBarFrame.setObjectName("frame")
        self.topBarLayout = QHBoxLayout(self.topBarFrame)
        self.topBarLayout.setContentsMargins(12, 10, 12, 10)
        self.topBarLayout.setSpacing(8)

        self.backButton = PushButton(FIF.LEFT_ARROW.icon(), "返回上一级", self.topBarFrame)
        self.breadcrumbBar = BreadcrumbBar(self.topBarFrame)

        self.topBarLayout.addWidget(self.backButton, 0)
        self.topBarLayout.addWidget(self.breadcrumbBar, 1)

        self.mainLayout.addWidget(self.topBarFrame, 0)

    def __createContent(self):
        self.contentLayout = QHBoxLayout()
        self.contentLayout.setContentsMargins(0, 0, 0, 0)
        self.contentLayout.setSpacing(12)

        self.treeFrame = QFrame(self)
        self.treeFrame.setObjectName("frame")
        self.treeLayout = QVBoxLayout(self.treeFrame)
        self.treeLayout.setContentsMargins(0, 8, 0, 0)
        self.treeLayout.setSpacing(0)

        self.folderTree = TreeWidget(self.treeFrame)
        self.folderTree.setHeaderHidden(True)
        self.folderTree.setUniformRowHeights(True)
        self.treeLayout.addWidget(self.folderTree)

        self.listFrame = QFrame(self)
        self.listFrame.setObjectName("frame")
        self.listLayout = QVBoxLayout(self.listFrame)
        self.listLayout.setContentsMargins(0, 8, 0, 0)
        self.listLayout.setSpacing(0)

        self.fileTable = TableWidget(self.listFrame)
        self.fileTable.setAlternatingRowColors(True)
        self.fileTable.setColumnCount(3)
        self.fileTable.setHorizontalHeaderLabels(["名称", "类型", "大小"])
        self.fileTable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fileTable.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.fileTable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        vertical_header = self.fileTable.verticalHeader()
        if vertical_header is not None:
            vertical_header.hide()
        self.fileTable.setBorderRadius(8)
        self.fileTable.setBorderVisible(True)
        header = self.fileTable.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.listLayout.addWidget(self.fileTable)

        self.contentLayout.addWidget(self.treeFrame, 2)
        self.contentLayout.addWidget(self.listFrame, 5)

        self.mainLayout.addLayout(self.contentLayout, 1)

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()
        self.__loadPanAndData()

    def __connectSignalToSlot(self):
        self.backButton.clicked.connect(self.__goParentDir)
        self.folderTree.itemClicked.connect(self.__onTreeItemClicked)
        self.folderTree.itemExpanded.connect(self.__onTreeItemExpanded)
        self.fileTable.itemDoubleClicked.connect(self.__onTableItemDoubleClicked)
        self.breadcrumbBar.currentItemChanged.connect(self.__onBreadcrumbItemChanged)

    def __loadPanAndData(self):
        try:
            self.pan = Pan123(readfile=True)
            self.__initTree()
            self.__loadCurrentList()
            self.__updateBreadcrumb()
        except Exception as e:
            self.__setErrorBreadcrumb(f"初始化失败: {e}")
            self.backButton.setEnabled(False)

    def __initTree(self):
        self.folderTree.clear()

        root_item = QTreeWidgetItem(["根目录"])
        root_item.setIcon(0, FIF.FOLDER.icon())
        root_item.setData(0, Qt.ItemDataRole.UserRole, 0)
        root_item.setData(0, Qt.ItemDataRole.UserRole + 1, False)
        self.folderTree.addTopLevelItem(root_item)

        self.__addPlaceholder(root_item)
        self.folderTree.expandItem(root_item)
        self.folderTree.setCurrentItem(root_item)

    def __addPlaceholder(self, parent_item):
        placeholder = QTreeWidgetItem([""])
        placeholder.setData(0, Qt.ItemDataRole.UserRole, None)
        parent_item.addChild(placeholder)

    def __onTreeItemExpanded(self, item):
        self.__ensureTreeChildrenLoaded(item)

    def __ensureTreeChildrenLoaded(self, item):
        if self.is_loading_tree:
            return

        loaded = item.data(0, Qt.ItemDataRole.UserRole + 1)
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if loaded or dir_id is None:
            return

        self.is_loading_tree = True
        try:
            item.takeChildren()
            folder_list = self.__fetchDirList(dir_id)
            for folder in folder_list:
                if int(folder.get("Type", 0)) != 1:
                    continue

                child = QTreeWidgetItem([folder.get("FileName", "")])
                child.setIcon(0, FIF.FOLDER.icon())
                child_id = int(folder.get("FileId", 0))
                child.setData(0, Qt.ItemDataRole.UserRole, child_id)
                child.setData(0, Qt.ItemDataRole.UserRole + 1, False)
                item.addChild(child)

                self.__addPlaceholder(child)

            item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
        finally:
            self.is_loading_tree = False

    def __onTreeItemClicked(self, item):
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if dir_id is None:
            return

        self.__ensureTreeChildrenLoaded(item)

        self.current_dir_id = int(dir_id)
        self.path_stack = self.__buildPathStackFromTree(item)
        self.__loadCurrentList()
        self.__updateBreadcrumb()

    def __buildPathStackFromTree(self, item):
        stack = []
        current = item
        while current is not None:
            name = current.text(0)
            dir_id = int(current.data(0, Qt.ItemDataRole.UserRole) or 0)
            stack.append((dir_id, name))
            current = current.parent()

        stack.reverse()
        return stack if stack else [(0, "根目录")]

    def __goParentDir(self):
        if len(self.path_stack) <= 1:
            return

        self.path_stack.pop()
        self.current_dir_id = self.path_stack[-1][0]
        self.__loadCurrentList()
        self.__updateBreadcrumb()

        current_item = self.__findTreeItemById(self.current_dir_id)
        if current_item:
            self.folderTree.setCurrentItem(current_item)

    def __onTableItemDoubleClicked(self, item):
        row = item.row()
        name_item = self.fileTable.item(row, 0)
        if name_item is None:
            return

        item_type = name_item.data(Qt.ItemDataRole.UserRole + 1)
        if item_type != 1:
            return

        file_id = int(name_item.data(Qt.ItemDataRole.UserRole))
        name = name_item.text()

        self.current_dir_id = file_id
        self.path_stack.append((file_id, name))
        self.__loadCurrentList()
        self.__updateBreadcrumb()

        tree_item = self.__findTreeItemById(file_id)
        if tree_item:
            self.folderTree.setCurrentItem(tree_item)
            self.folderTree.expandItem(tree_item)

    def __loadCurrentList(self):
        if not self.pan:
            return

        self.fileTable.setRowCount(0)
        file_items = self.__fetchDirList(self.current_dir_id)
        self.fileTable.setRowCount(len(file_items))

        for row, file_item in enumerate(file_items):
            file_name = file_item.get("FileName", "")
            file_type = int(file_item.get("Type", 0))
            file_size = int(file_item.get("Size", 0) or 0)
            file_id = int(file_item.get("FileId", 0) or 0)

            type_text = "文件夹" if file_type == 1 else "文件"
            size_text = "-" if file_type == 1 else self.__formatSize(file_size)

            name_item = QTableWidgetItem(file_name)
            name_item.setData(Qt.ItemDataRole.UserRole, file_id)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, file_type)
            name_item.setIcon(FIF.FOLDER.icon() if file_type == 1 else FIF.DOCUMENT.icon())

            type_item = QTableWidgetItem(type_text)
            size_item = QTableWidgetItem(size_text)

            self.fileTable.setItem(row, 0, name_item)
            self.fileTable.setItem(row, 1, type_item)
            self.fileTable.setItem(row, 2, size_item)

    def __fetchDirList(self, dir_id):
        if not self.pan:
            return []

        cached_state = (self.pan.file_page, self.pan.total, self.pan.all_file)
        self.pan.file_page = 0
        try:
            code, items = self.pan.get_dir_by_id(dir_id, save=False, all=True, limit=100)
            return items if code == 0 else []
        except Exception:
            return []
        finally:
            self.pan.file_page, self.pan.total, self.pan.all_file = cached_state

    def __findTreeItemById(self, dir_id):
        iterator = QTreeWidgetItemIterator(self.folderTree)
        while iterator.value():
            item = iterator.value()
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == dir_id:
                return item
            iterator += 1

        return None

    def __setErrorBreadcrumb(self, message):
        self.is_updating_breadcrumb = True
        self.breadcrumbBar.clear()
        self.breadcrumbBar.addItem("error", message)
        self.is_updating_breadcrumb = False

    def __updateBreadcrumb(self):
        self.is_updating_breadcrumb = True
        self.breadcrumbBar.clear()
        for dir_id, name in self.path_stack:
            self.breadcrumbBar.addItem(str(dir_id), name)
        self.is_updating_breadcrumb = False

    def __onBreadcrumbItemChanged(self, route_key):
        if self.is_updating_breadcrumb:
            return

        try:
            target_dir_id = int(route_key)
        except (TypeError, ValueError):
            return

        target_index = -1
        for i, (dir_id, _) in enumerate(self.path_stack):
            if dir_id == target_dir_id:
                target_index = i
                break

        if target_index < 0:
            return

        self.path_stack = self.path_stack[:target_index + 1]
        self.current_dir_id = target_dir_id
        self.__loadCurrentList()

        tree_item = self.__findTreeItemById(target_dir_id)
        if tree_item:
            self.folderTree.setCurrentItem(tree_item)

    def __formatSize(self, size):
        if size < 1024:
            return f"{size} B"
        if size < 1024 ** 2:
            return f"{size / 1024:.2f} KB"
        if size < 1024 ** 3:
            return f"{size / 1024 ** 2:.2f} MB"
        return f"{size / 1024 ** 3:.2f} GB"