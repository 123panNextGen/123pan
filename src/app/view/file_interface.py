import importlib
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QRunnable, QThreadPool, pyqtSignal, QObject, QTimer
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
    QTableWidgetItem,
    QInputDialog,
    QFileDialog,
    QMenu,
)
from PyQt6.QtGui import QAction

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    BreadcrumbBar,
    TableWidget,
    TreeWidget,
    PushButton,
    InfoBar,
    Action,
)

from ..common.style_sheet import StyleSheet
from ..common.api import format_file_size
from .newfolder_window import NewFolderDialog

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
        self.transfer_interface = None

        # 排序模式: 0=按名称, 2=按大小
        self.sort_mode = 0
        # 排序方向: True=升序, False=降序
        self.sort_ascending = True

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

        self.backButton = PushButton(
            FIF.LEFT_ARROW.icon(), "返回上一级", self.topBarFrame
        )
        self.breadcrumbBar = BreadcrumbBar(self.topBarFrame)

        # 右侧按钮
        self.newFolderButton = PushButton(
            FIF.FOLDER_ADD.icon(), "新建文件夹", self.topBarFrame
        )
        self.uploadButton = PushButton(FIF.UP.icon(), "上传", self.topBarFrame)
        self.downloadButton = PushButton(FIF.DOWNLOAD.icon(), "下载", self.topBarFrame)
        self.deleteButton = PushButton(FIF.DELETE.icon(), "删除", self.topBarFrame)
        self.refreshButton = PushButton(FIF.UPDATE.icon(), "刷新", self.topBarFrame)

        self.topBarLayout.addWidget(self.backButton, 0)
        self.topBarLayout.addWidget(self.breadcrumbBar, 1)
        self.topBarLayout.addWidget(self.newFolderButton, 0)
        self.topBarLayout.addWidget(self.uploadButton, 0)
        self.topBarLayout.addWidget(self.downloadButton, 0)
        self.topBarLayout.addWidget(self.deleteButton, 0)
        self.topBarLayout.addWidget(self.refreshButton, 0)

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
        self.fileTable.setColumnCount(3)  # 恢复为3列，移除操作列
        self.fileTable.setHorizontalHeaderLabels(["名称", "类型", "大小"])
        self.fileTable.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
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
            # 启用列头点击排序
            header.setSectionsClickable(True)
            header.setSortIndicatorShown(True)
            header.sortIndicatorChanged.connect(self.__onHeaderSortIndicatorChanged)
        self.listLayout.addWidget(self.fileTable)

        self.contentLayout.addWidget(self.treeFrame, 2)
        self.contentLayout.addWidget(self.listFrame, 5)

        self.mainLayout.addLayout(self.contentLayout, 1)

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()
        # 为文件表格添加右键菜单
        self.fileTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fileTable.customContextMenuRequested.connect(self.__onFileTableContextMenu)
        self.__loadPanAndData()

    def __connectSignalToSlot(self):
        self.backButton.clicked.connect(self.__goParentDir)
        self.folderTree.itemClicked.connect(self.__onTreeItemClicked)
        self.folderTree.itemExpanded.connect(self.__onTreeItemExpanded)
        self.fileTable.itemDoubleClicked.connect(self.__onTableItemDoubleClicked)
        self.breadcrumbBar.currentItemChanged.connect(self.__onBreadcrumbItemChanged)
        self.newFolderButton.clicked.connect(self.__createNewFolder)
        self.uploadButton.clicked.connect(self.__uploadFile)
        self.downloadButton.clicked.connect(self.__downloadFile)
        self.deleteButton.clicked.connect(self.__deleteFile)
        self.refreshButton.clicked.connect(self.__refreshFileList)

    def __loadPanAndData(self):
        try:
            self.pan = Pan123(readfile=True)
            self.__initTree()
            self.__loadCurrentList()
            self.__updateBreadcrumb()
            self.__updateBackButtonState()
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
        self.__updateBackButtonState()

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
        self.__updateBackButtonState()

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
        self.__updateBackButtonState()

        tree_item = self.__findTreeItemById(file_id)
        if tree_item:
            self.folderTree.setCurrentItem(tree_item)
            self.folderTree.expandItem(tree_item)

    def __loadCurrentList(self):
        if not self.pan:
            return

        # 使用后台线程加载文件列表，避免阻塞主线程
        self.fileTable.setRowCount(0)

        # 创建任务
        task = self.LoadListTask(self.__fetchDirList, self.current_dir_id)

        # 连接信号
        task.signals.finished.connect(self.__onLoadListFinished)

        # 提交任务到线程池
        QThreadPool.globalInstance().start(task)

    def __fetchDirList(self, dir_id):
        if not self.pan:
            return []

        cached_state = (self.pan.file_page, self.pan.total, self.pan.all_file)
        self.pan.file_page = 0
        try:
            code, items = self.pan.get_dir_by_id(
                dir_id, save=False, all=True, limit=100
            )
            return items if code == 0 else []
        except Exception:
            return []
        finally:
            self.pan.file_page, self.pan.total, self.pan.all_file = cached_state

    # 后台加载文件列表的信号和任务类
    class LoadListTask(QRunnable):
        class LoadListSignals(QObject):
            finished = pyqtSignal(list, str)  # file_items, error

        def __init__(self, fetch_method, dir_id):
            super().__init__()
            self.fetch_method = fetch_method
            self.dir_id = dir_id
            # 将信号对象作为成员变量，防止被垃圾回收
            self.signals = self.LoadListSignals()

        def run(self):
            try:
                file_items = self.fetch_method(self.dir_id)
                self.signals.finished.emit(file_items, "")
            except Exception as e:
                self.signals.finished.emit([], str(e))

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

        self.path_stack = self.path_stack[: target_index + 1]
        self.current_dir_id = target_dir_id
        self.__loadCurrentList()
        self.__updateBackButtonState()

        tree_item = self.__findTreeItemById(target_dir_id)
        if tree_item:
            self.folderTree.setCurrentItem(tree_item)

    def __updateBackButtonState(self):
        """更新返回按钮状态"""
        self.backButton.setEnabled(len(self.path_stack) > 1)

    def __createNewFolder(self):
        """创建新文件夹"""

        # 使用新建文件夹弹窗
        dialog = NewFolderDialog(self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            folder_name = dialog.get_new_name()

            # 检查文件夹名称是否为空
            if not folder_name.strip():
                InfoBar.warning(
                    title="输入错误", content="请输入文件夹名称", parent=self
                )
                return

            # 创建任务执行创建文件夹操作
            class CreateFolderSignals(QObject):
                finished = pyqtSignal(bool, str, str, list, list)  # result, folder_name, error, file_items, folder_items

            class CreateFolderTask(QRunnable):
                def __init__(self, pan, folder_name, current_dir_id, signals):
                    super().__init__()
                    self.pan = pan
                    self.folder_name = folder_name
                    self.current_dir_id = current_dir_id
                    self.signals = signals

                def run(self):
                    try:
                        # 保存当前目录ID
                        current_parent_id = self.pan.parent_file_id
                        # 设置当前目录为目标目录
                        self.pan.parent_file_id = self.current_dir_id
                        # 调用API创建文件夹
                        result = self.pan.mkdir(self.folder_name)
                        # 恢复当前目录
                        self.pan.parent_file_id = current_parent_id

                        if result:
                            # 在后台线程中获取最新的文件列表
                            cached_state = (self.pan.file_page, self.pan.total, self.pan.all_file)
                            self.pan.file_page = 0
                            code, items = self.pan.get_dir_by_id(
                                self.current_dir_id, save=False, all=True, limit=100
                            )
                            self.pan.file_page, self.pan.total, self.pan.all_file = cached_state

                            # 在后台线程中获取文件夹列表（用于更新树）
                            folder_items = []
                            if code == 0:
                                for item in items:
                                    if int(item.get("Type", 0)) == 1:
                                        folder_items.append({
                                            "FileId": item.get("FileId"),
                                            "FileName": item.get("FileName")
                                        })

                            self.signals.finished.emit(True, self.folder_name, "", items, folder_items)
                        else:
                            self.signals.finished.emit(False, self.folder_name, "", [], [])
                    except Exception as e:
                        self.signals.finished.emit(False, self.folder_name, str(e), [], [])

            # 创建信号和任务
            signals = CreateFolderSignals()
            signals.finished.connect(self.__onCreateFolderFinished)
            task = CreateFolderTask(self.pan, folder_name, self.current_dir_id, signals)

            # 提交任务到线程池
            QThreadPool.globalInstance().start(task)

    def __onCreateFolderFinished(self, result, folder_name, error, file_items, folder_items):
        """创建文件夹完成后的回调 - 只负责UI更新"""
        if result:
            InfoBar.success(
                title="创建成功",
                content=f"文件夹 '{folder_name}' 创建成功",
                parent=self,
            )

            # 更新文件列表（轻量级UI操作）
            self.__updateFileListUI(file_items)

            # 更新树结构（轻量级UI操作）
            self.__updateTreeUI(folder_items)

            # 重新选择当前目录
            current_item = self.__findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            if error:
                InfoBar.error(
                    title="创建失败",
                    content=f"创建文件夹时发生错误: {error}",
                    parent=self,
                )
            else:
                InfoBar.error(title="创建失败", content="创建文件夹失败", parent=self)

    def __updateFileListUI(self, file_items):
        """更新文件列表UI - 轻量级操作"""
        self.fileTable.setRowCount(len(file_items))

        for row, file_item in enumerate(file_items):
            file_name = file_item.get("FileName", "")
            file_type = int(file_item.get("Type", 0))
            file_size = int(file_item.get("Size", 0) or 0)
            file_id = int(file_item.get("FileId", 0) or 0)

            type_text = "文件夹" if file_type == 1 else "文件"
            size_text = format_file_size(file_size)

            name_item = QTableWidgetItem(file_name)
            name_item.setData(Qt.ItemDataRole.UserRole, file_id)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, file_type)
            name_item.setIcon(
                FIF.FOLDER.icon() if file_type == 1 else FIF.DOCUMENT.icon()
            )

            type_item = QTableWidgetItem(type_text)
            size_item = QTableWidgetItem(size_text)

            self.fileTable.setItem(row, 0, name_item)
            self.fileTable.setItem(row, 1, type_item)
            self.fileTable.setItem(row, 2, size_item)

    def __onLoadListFinished(self, file_items, error):
        """加载文件列表完成后的回调 - 只负责UI更新"""
        if error:
            InfoBar.error(
                title="加载失败",
                content=f"加载文件列表时发生错误: {error}",
                parent=self,
            )
        else:
            # 对文件列表进行排序
            sorted_items = self.__sortFileList(file_items)
            # 更新文件列表（轻量级UI操作）
            self.__updateFileListUI(sorted_items)

    def __sortFileList(self, file_items):
        """对文件列表进行排序，文件夹始终在前"""
        # 分离文件夹和文件
        folders = []
        files = []

        for item in file_items:
            file_type = int(item.get("Type", 0))
            if file_type == 1:  # 文件夹
                folders.append(item)
            else:  # 文件
                files.append(item)

        # 根据排序模式对文件夹和文件分别排序
        if self.sort_mode == 0:  # 按名称排序（仅翻转，不按字母排序）
            # 不排序，保持原始顺序，但可以翻转
            pass
        elif self.sort_mode == 2:  # 按大小排序
            # sort_ascending=True 表示升序（小到大），reverse=False
            # sort_ascending=False 表示降序（大到小），reverse=True
            reverse = not self.sort_ascending
            folders.sort(key=lambda x: int(x.get("Size", 0) or 0), reverse=reverse)
            files.sort(key=lambda x: int(x.get("Size", 0) or 0), reverse=reverse)

        # 合并结果：文件夹在前，文件在后
        result = folders + files

        # 如果是按名称排序且需要降序，则翻转整个列表
        if self.sort_mode == 0 and not self.sort_ascending:
            result.reverse()

        return result

    def __onHeaderSortIndicatorChanged(self, logicalIndex, order):
        """列头排序指示器改变时的处理"""
        # 只处理名称列（0）和大小列（2）的排序
        if logicalIndex in [0, 2]:
            if logicalIndex == self.sort_mode:
                # 点击同一列，切换排序方向
                self.sort_ascending = not self.sort_ascending
            else:
                # 点击不同列，切换到新列
                self.sort_mode = logicalIndex
                # 如果是大小列，默认使用降序；名称列默认使用升序
                if logicalIndex == 2:
                    self.sort_ascending = False
                else:
                    self.sort_ascending = True
            # 重新加载当前列表以应用新的排序
            self.__loadCurrentList()

    def __updateTreeUI(self, folder_items):
        """更新树结构UI - 轻量级操作"""
        # 简单刷新当前目录下的子节点
        current_item = self.__findTreeItemById(self.current_dir_id)
        if current_item:
            # 移除占位符
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) is None:
                    current_item.removeChild(child)
                    break

            # 更新子节点
            existing_items = {}
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                file_id = child.data(0, Qt.ItemDataRole.UserRole)
                if file_id:
                    existing_items[file_id] = child

            # 添加新的文件夹
            for folder in folder_items:
                file_id = int(folder.get("FileId", 0))
                file_name = folder.get("FileName", "")

                if file_id in existing_items:
                    # 已存在，不需要添加
                    continue

                child = QTreeWidgetItem([file_name])
                child.setIcon(0, FIF.FOLDER.icon())
                child.setData(0, Qt.ItemDataRole.UserRole, file_id)
                child.setData(0, Qt.ItemDataRole.UserRole + 1, False)
                current_item.addChild(child)

                # 添加占位符
                self.__addPlaceholder(child)

    def __getExpandedItems(self):
        """获取树的展开状态"""
        expanded_items = []

        def collect_expanded_items(item):
            if item.isExpanded():
                item_id = item.data(0, Qt.ItemDataRole.UserRole)
                if item_id:
                    expanded_items.append(item_id)

            for i in range(item.childCount()):
                collect_expanded_items(item.child(i))

        root = self.folderTree.invisibleRootItem()
        for i in range(root.childCount()):
            collect_expanded_items(root.child(i))

        return expanded_items

    def __restoreExpandedItems(self, expanded_items):
        """恢复树的展开状态"""

        def expand_items(item):
            item_id = item.data(0, Qt.ItemDataRole.UserRole)
            if item_id and item_id in expanded_items:
                item.setExpanded(True)

            for i in range(item.childCount()):
                expand_items(item.child(i))

        root = self.folderTree.invisibleRootItem()
        for i in range(root.childCount()):
            expand_items(root.child(i))

    def __uploadFile(self):
        """上传文件"""
        # 打开文件选择对话框
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择要上传的文件")

        if file_paths:
            # 添加上传任务到传输界面
            for file_path in file_paths:
                path = Path(file_path)
                file_name = path.name
                file_size = path.stat().st_size
                if self.transfer_interface:
                    self.transfer_interface.add_upload_task(
                        file_name, file_size, file_path, self.current_dir_id
                    )

            InfoBar.success(
                title="上传文件",
                content=f"已添加 {len(file_paths)} 个上传任务",
                parent=self,
            )

    def __downloadFile(self):
        """下载文件"""
        # 获取选中的文件
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(title="下载错误", content="请选择要下载的文件", parent=self)
            return

        # 获取选中行的文件信息
        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()
        file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)

        # 如果是文件夹，将文件名改为xxx.zip
        if file_type == 1:  # 文件夹
            file_name = file_name + ".zip"

        # 导入配置管理器
        from app.common.config import ConfigManager

        # 获取配置
        ask_download_location = ConfigManager.get_setting("askDownloadLocation", True)
        default_download_path = ConfigManager.get_setting(
            "defaultDownloadPath", str(Path.home() / "Downloads")
        )

        save_path = None

        # 根据配置决定是否询问下载位置
        if ask_download_location:
            # 选择保存文件
            save_path, _ = QFileDialog.getSaveFileName(
                self, "保存文件", str(Path(default_download_path) / file_name)
            )
        else:
            # 直接使用默认下载位置
            save_path = str(Path(default_download_path) / file_name)

        if save_path:
            # 获取文件大小
            size_item = self.fileTable.item(row, 2)
            file_size = 0
            if size_item:
                size_text = size_item.text()
                # 简单解析文件大小
                if size_text.endswith(" B"):
                    file_size = int(size_text.split(" ")[0])
                elif size_text.endswith(" KB"):
                    file_size = int(float(size_text.split(" ")[0]) * 1024)
                elif size_text.endswith(" MB"):
                    file_size = int(float(size_text.split(" ")[0]) * 1024 * 1024)
                elif size_text.endswith(" GB"):
                    file_size = int(float(size_text.split(" ")[0]) * 1024 * 1024 * 1024)

            # 添加下载任务到传输界面
            if self.transfer_interface:
                self.transfer_interface.add_download_task(
                    file_name, file_size, file_id, save_path, self.current_dir_id
                )

            InfoBar.success(
                title="下载文件",
                content=f"已添加下载任务: {file_name}",
                parent=self,
            )

    def __refreshFileList(self):
        """刷新文件列表"""
        self.__loadCurrentList()

    def __deleteFile(self, file_id=None, file_name=None):
        """删除文件"""

        # 如果没有提供file_id和file_name，则从选中的文件获取
        if file_id is None or file_name is None:
            selected_items = self.fileTable.selectedItems()
            if not selected_items:
                InfoBar.warning(
                    title="删除错误", content="请选择要删除的文件", parent=self
                )
                return

            # 获取选中行的文件信息
            row = selected_items[0].row()
            name_item = self.fileTable.item(row, 0)
            file_id = name_item.data(Qt.ItemDataRole.UserRole)
            file_name = name_item.text()
            file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)

            # if file_type == 1:  # 文件夹
            #     InfoBar.warning(
            #         title="删除错误", content="暂不支持删除文件夹", parent=self
            #     )
            #     return

        # 创建任务执行删除文件操作
        class DeleteFileSignals(QObject):
            finished = pyqtSignal(bool, str, str, list, list)  # success, file_name, error, file_items, folder_items

        class DeleteFileTask(QRunnable):
            def __init__(self, pan, file_id, file_name, current_dir_id, signals):
                super().__init__()
                self.pan = pan
                self.file_id = file_id
                self.file_name = file_name
                self.current_dir_id = current_dir_id
                self.signals = signals

            def run(self):
                try:
                    # 直接使用文件ID删除，不需要查找索引
                    # 调用API删除文件
                    success = False

                    # 先在self.pan.list中找到对应的文件
                    for i, file in enumerate(self.pan.list):
                        if str(file.get("FileId")) == str(self.file_id):
                            # 调用API删除文件
                            self.pan.delete_file(i, by_num=True, operation=True)
                            success = True
                            break

                    # 如果在self.pan.list中找不到，尝试重新加载当前目录的文件列表
                    if not success:
                        code, files = self.pan.get_dir_by_id(
                            self.current_dir_id, save=True, all=True, limit=1000
                        )
                        if code == 0:
                            for i, file in enumerate(self.pan.list):
                                if str(file.get("FileId")) == str(self.file_id):
                                    # 调用API删除文件
                                    self.pan.delete_file(i, by_num=True, operation=True)
                                    success = True
                                    break

                    if success:
                        # 在后台线程中获取最新的文件列表
                        cached_state = (self.pan.file_page, self.pan.total, self.pan.all_file)
                        self.pan.file_page = 0
                        code, items = self.pan.get_dir_by_id(
                            self.current_dir_id, save=False, all=True, limit=100
                        )
                        self.pan.file_page, self.pan.total, self.pan.all_file = cached_state

                        # 在后台线程中获取文件夹列表（用于更新树）
                        folder_items = []
                        if code == 0:
                            for item in items:
                                if int(item.get("Type", 0)) == 1:
                                    folder_items.append({
                                        "FileId": item.get("FileId"),
                                        "FileName": item.get("FileName")
                                    })

                        self.signals.finished.emit(True, self.file_name, "", items, folder_items)
                    else:
                        self.signals.finished.emit(False, self.file_name, "", [], [])
                except Exception as e:
                    self.signals.finished.emit(False, self.file_name, str(e), [], [])

        # 创建信号和任务
        signals = DeleteFileSignals()
        signals.finished.connect(self.__onDeleteFileFinished)
        task = DeleteFileTask(
            self.pan, file_id, file_name, self.current_dir_id, signals
        )

        # 提交任务到线程池
        QThreadPool.globalInstance().start(task)

    def __onDeleteFileFinished(self, success, file_name, error, file_items, folder_items):
        """删除文件完成后的回调 - 只负责UI更新"""

        if success:
            # 显示成功信息
            InfoBar.success(
                title="删除成功",
                content=f"文件 '{file_name}' 已成功删除",
                parent=self,
            )

            # 更新文件列表（轻量级UI操作）
            self.__updateFileListUI(file_items)

            # 更新树结构（轻量级UI操作）
            self.__updateTreeUI(folder_items)

            # 重新选择当前目录
            current_item = self.__findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            if error:
                # 显示错误信息
                InfoBar.error(
                    title="删除失败",
                    content=f"删除文件时发生错误: {error}",
                    parent=self,
                )
            else:
                # 显示错误信息
                InfoBar.error(title="删除失败", content="文件不存在", parent=self)

    def __onFileTableContextMenu(self, position):
        """文件表格右键菜单"""
        # 获取鼠标点击位置的行
        index = self.fileTable.indexAt(position)
        if not index.isValid():
            return

        # 选择右键点击的行
        self.fileTable.selectRow(index.row())

        # 创建右键菜单
        menu = QMenu(self)

        # 添加删除菜单项
        delete_action = QAction(FIF.DELETE.icon(), "删除", self)
        delete_action.triggered.connect(self.__deleteFile)
        menu.addAction(delete_action)

        # 显示菜单
        menu.exec(self.fileTable.mapToGlobal(position))
