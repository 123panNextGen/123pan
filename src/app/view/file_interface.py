from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QThreadPool
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QTreeWidgetItemIterator,
    QTableWidgetItem,
    QFileDialog,
    QMenu,
    QApplication,
    QInputDialog,
    QLineEdit,
)
from PyQt6.QtGui import QAction

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    BreadcrumbBar,
    TableWidget,
    TreeWidget,
    PushButton,
    InfoBar,
    CardWidget,
    BodyLabel,
    IconWidget,
    ProgressBar,
)

from ..common.style_sheet import StyleSheet
from ..common.utils import format_file_size
from ..common.const import MAX_STORAGE_CAPACITY
from ..common.api import Pan123
from ..common.log import get_logger
from ..common.i18n import tr
from ..tasks.file_tasks import (
    CreateFolderTask,
    DeleteFileTask,
    BatchDeleteTask,
    LoadListTask,
    RenameFileTask,
    StorageTask,
)
from ..tasks.signals import _LoadListSignals, _OpFinishedSignals, _StorageSignals
from .dialogs import InputDialog

logger = get_logger(__name__)


# noinspection PyUnresolvedReferences
class FileInterface(QWidget):
    """文件页面（仅浏览）"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("FileInterface")

        self.pan = None
        self.current_dir_id = 0
        self.path_stack = [(0, tr("file.root_dir", "根目录"))]
        self.is_loading_tree = False
        self.is_updating_breadcrumb = False
        self.transfer_interface = None
        # 当前目录的文件列表（用于下载/预览/分享等操作的文件查找）
        self._current_file_items = []

        # 排序模式: 0=按名称, 2=按大小
        self.sort_mode = 0
        # 排序方向: True=升序, False=降序
        self.sort_ascending = True

        # 搜索文本
        self._search_text = ""

        # 搜索防抖：300ms 内无新输入才执行过滤，避免每键都重建表格
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.__applySearchFilter)

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
            FIF.LEFT_ARROW.icon(), tr("file.back_button", "返回上一级"), self.topBarFrame
        )

        self.breadcrumbBar = BreadcrumbBar(self.topBarFrame)

        # 搜索框
        self.searchBox = QLineEdit(self.topBarFrame)
        self.searchBox.setPlaceholderText(tr("file.search_placeholder", "搜索文件名..."))
        self.searchBox.setClearButtonEnabled(True)
        self.searchBox.setMaximumWidth(200)
        self.searchBox.textChanged.connect(self.__onSearchTextChanged)

        # 右侧按钮
        self.newFolderButton = PushButton(
            FIF.FOLDER_ADD.icon(), tr("file.new_folder", "新建文件夹"), self.topBarFrame
        )
        self.uploadButton = PushButton(FIF.UP.icon(), tr("file.upload", "上传"), self.topBarFrame)
        self.downloadButton = PushButton(FIF.DOWNLOAD.icon(), tr("file.download", "下载"), self.topBarFrame)
        self.deleteButton = PushButton(FIF.DELETE.icon(), tr("file.delete", "删除"), self.topBarFrame)
        self.refreshButton = PushButton(FIF.UPDATE.icon(), tr("file.refresh", "刷新"), self.topBarFrame)

        self.topBarLayout.addWidget(self.backButton, 0)
        self.topBarLayout.addWidget(self.breadcrumbBar, 1)
        self.topBarLayout.addWidget(self.searchBox, 0)
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
        self.treeLayout.setSpacing(8)

        self.folderTree = TreeWidget(self.treeFrame)
        self.folderTree.setHeaderHidden(True)
        self.folderTree.setUniformRowHeights(True)
        self.treeLayout.addWidget(self.folderTree)

        # 添加云盘占用大小卡片
        self.storageCard = CardWidget(self.treeFrame)
        self.storageLayout = QVBoxLayout(self.storageCard)
        self.storageLayout.setContentsMargins(12, 8, 12, 8)
        self.storageLayout.setSpacing(8)

        # 第一行：图标、标签和容量文本
        self.storageTopLayout = QHBoxLayout()
        self.storageTopLayout.setSpacing(8)

        self.storageIcon = IconWidget(FIF.CLOUD.icon(), self.storageCard)
        self.storageIcon.setFixedSize(20, 20)
        self.storageTopLayout.addWidget(self.storageIcon)

        self.storageLabel = BodyLabel(tr("file.cloud_space", "云盘空间"), self.storageCard)
        self.storageTopLayout.addWidget(self.storageLabel)

        self.storageValueLabel = BodyLabel("-- / --", self.storageCard)
        self.storageValueLabel.setStyleSheet("font-size: 12px; color: gray;")
        self.storageTopLayout.addWidget(
            self.storageValueLabel, 0, Qt.AlignmentFlag.AlignRight
        )

        self.storageTopLayout.addStretch()
        self.storageLayout.addLayout(self.storageTopLayout)

        # 第二行：进度条
        self.storageProgressBar = ProgressBar(self.storageCard)
        self.storageProgressBar.setRange(0, 100)
        self.storageProgressBar.setValue(0)
        self.storageProgressBar.setFixedHeight(6)
        self.storageLayout.addWidget(self.storageProgressBar)

        self.treeLayout.addWidget(self.storageCard)

        self.listFrame = QFrame(self)
        self.listFrame.setObjectName("frame")
        self.listLayout = QVBoxLayout(self.listFrame)
        self.listLayout.setContentsMargins(0, 8, 0, 0)
        self.listLayout.setSpacing(0)

        self.fileTable = TableWidget(self.listFrame)
        self.fileTable.setAlternatingRowColors(True)
        self.fileTable.setColumnCount(3)  # 恢复为3列，移除操作列
        self.fileTable.setHorizontalHeaderLabels([tr("file.col_name", "名称"), tr("file.col_type", "类型"), tr("file.col_size", "大小")])
        self.fileTable.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.fileTable.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        # 启用拖拽上传
        self.setAcceptDrops(True)
        self.fileTable.setAcceptDrops(True)
        # 初始化快捷键
        self.__initShortcuts()
        self.__loadPanAndData()

    def __initShortcuts(self):
        """初始化键盘快捷键"""
        # F5: 刷新
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, self.__refreshFileList)
        # Ctrl+N: 新建文件夹
        QShortcut(QKeySequence("Ctrl+N"), self, self.__createNewFolder)
        # Ctrl+U: 上传文件
        QShortcut(QKeySequence("Ctrl+U"), self, self.__uploadFile)
        # Ctrl+D: 下载选中文件
        QShortcut(QKeySequence("Ctrl+D"), self, self.__downloadFile)
        # Delete: 删除选中文件
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, self.__deleteFile)
        # F2: 重命名
        QShortcut(QKeySequence(Qt.Key.Key_F2), self, self.__renameFile)
        # Backspace: 返回上级
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self, self.__goParentDir)
        # Ctrl+F: 聚焦搜索框
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.searchBox.setFocus())
        # Ctrl+A: 全选
        QShortcut(QKeySequence("Ctrl+A"), self, self.fileTable.selectAll)
        # Enter: 进入文件夹或预览文件
        QShortcut(
            QKeySequence(Qt.Key.Key_Return),
            self,
            lambda: self.__onTableItemDoubleClicked(self.fileTable.currentItem())
            if self.fileTable.currentItem() else None,
        )

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
        """加载 Pan123 实例并初始化数据。

        优先使用外部传入的 pan（由 MainWindow 在登录流程中设置），
        如果未设置则尝试从配置文件加载。
        """
        if self.pan is None:
            try:
                self.pan = Pan123(readfile=True)
            except Exception as e:
                self.__setErrorBreadcrumb(tr("file.init_error", "初始化失败: {}").format(e))
                self.backButton.setEnabled(False)
                return

        try:
            self.__initTree()
            self.__loadCurrentList()
            self.__updateBreadcrumb()
            self.__updateBackButtonState()
            self.load_and_update_storage_info()
        except Exception as e:
            self.__setErrorBreadcrumb(tr("file.init_error", "初始化失败: {}").format(e))
            self.backButton.setEnabled(False)

    def __initTree(self):
        self.folderTree.clear()

        root_item = QTreeWidgetItem([tr("file.root_dir", "根目录")])
        root_item.setIcon(0, FIF.FOLDER.icon())
        root_item.setData(0, Qt.ItemDataRole.UserRole, 0)
        root_item.setData(0, Qt.ItemDataRole.UserRole + 1, False)
        self.folderTree.addTopLevelItem(root_item)

        self.__addPlaceholder(root_item)
        self.folderTree.expandItem(root_item)
        self.folderTree.setCurrentItem(root_item)

    @staticmethod
    def __addPlaceholder(parent_item):
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

    @staticmethod
    def __buildPathStackFromTree(item):
        stack = []
        current = item
        while current is not None:
            name = current.text(0)
            dir_id = int(current.data(0, Qt.ItemDataRole.UserRole) or 0)
            stack.append((dir_id, name))
            current = current.parent()

        stack.reverse()
        return stack if stack else [(0, tr("file.root_dir", "根目录"))]

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
        if item_type == 1:
            # 文件夹：进入目录
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
        else:
            # 文件：尝试预览
            self.__previewFile()

    def __loadCurrentList(self, force_refresh=False):
        if not self.pan:
            logger.warning("__loadCurrentList: pan 未设置")
            return

        logger.debug("加载文件列表: dir_id=%s, force=%s", self.current_dir_id, force_refresh)
        self.fileTable.setRowCount(0)

        signals = _LoadListSignals()
        signals.finished.connect(self.__onLoadListFinished)
        task = LoadListTask(
            lambda: self.__fetchDirList(self.current_dir_id, force_refresh),
            self.current_dir_id, signals,
        )

        QThreadPool.globalInstance().start(task)

    def __fetchDirList(self, dir_id, force_refresh=False):
        if not self.pan:
            logger.warning("__fetchDirList: pan 未设置")
            return []

        logger.debug("异步获取目录列表: dir_id=%s, force=%s", dir_id, force_refresh)
        cached_state = (self.pan.file_page, self.pan.total, self.pan.all_file)
        self.pan.file_page = 0
        try:
            code, items = self.pan.get_dir_by_id(
                dir_id, save=False, all=True, limit=100,
                force_refresh=force_refresh,
            )
            return items if code == 0 else []
        except Exception:
            return []
        finally:
            self.pan.file_page, self.pan.total, self.pan.all_file = cached_state

    def _reload_dir_data(self, dir_id, force_refresh=False):
        """在后台线程中重新加载目录数据和文件夹列表。

        仅供 QRunnable 的 run() 方法调用。
        返回 (items, folder_items) 元组。
        """
        cached_state = (self.pan.file_page, self.pan.total, self.pan.all_file)
        self.pan.file_page = 0
        try:
            code, items = self.pan.get_dir_by_id(
                dir_id, save=False, all=True, limit=100,
                force_refresh=force_refresh,
            )
            folder_items = []
            if code == 0:
                for item in items:
                    if int(item.get("Type", 0)) == 1:
                        folder_items.append(
                            {
                                "FileId": item.get("FileId"),
                                "FileName": item.get("FileName"),
                            }
                        )
            return items, folder_items
        except Exception:
            return [], []
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
        dialog = InputDialog(tr("file.new_folder", "新建文件夹"), tr("file.new_folder_hint", "请输入文件夹名称"), tr("file.new_folder_default", "新建文件夹"), self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            folder_name = dialog.get_input_text()

            # 检查文件夹名称是否为空
            if not folder_name.strip():
                InfoBar.warning(
                    title=tr("file.msg_input_error", "输入错误"), content=tr("file.msg_enter_folder_name", "请输入文件夹名称"), parent=self
                )
                return

            # 在主线程创建信号
            signals = _OpFinishedSignals()
            signals.finished.connect(self.__onCreateFolderFinished)
            task = CreateFolderTask(
                self.pan, folder_name, self.current_dir_id, signals, self
            )

            # 提交任务到线程池
            QThreadPool.globalInstance().start(task)

    def __onCreateFolderFinished(
        self, result, folder_name, new_name, error, file_items, folder_items
    ):
        """创建文件夹完成后的回调 - 只负责UI更新"""
        if result:
            InfoBar.success(
                title=tr("file.msg_create_success", "创建成功"),
                content=tr("file.msg_folder_created", "文件夹 '{}' 创建成功").format(folder_name),
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
                    title=tr("file.msg_create_failed", "创建失败"),
                    content=tr("file.msg_create_folder_error", "创建文件夹时发生错误: {}").format(error),
                    parent=self,
                )
            else:
                InfoBar.error(title=tr("file.msg_create_failed", "创建失败"), content=tr("file.msg_create_folder_failed", "创建文件夹失败"), parent=self)

    def __updateFileListUI(self, file_items, update_cache=True):
        """更新文件列表UI - 批量操作，避免大量文件时逐行重绘卡死

        update_cache=False 时不会覆盖 _current_file_items，
        用于搜索过滤场景，避免过滤结果覆盖完整列表缓存。
        """
        if update_cache:
            self._current_file_items = file_items

        # 暂停重绘和信号，批量更新完成后再一次性刷新
        self.fileTable.setUpdatesEnabled(False)
        self.fileTable.blockSignals(True)
        try:
            count = len(file_items)
            self.fileTable.setRowCount(count)

            for row, file_item in enumerate(file_items):
                file_name = file_item.get("FileName", "")
                file_type = int(file_item.get("Type", 0))
                file_size = int(file_item.get("Size", 0) or 0)
                file_id = int(file_item.get("FileId", 0) or 0)

                type_text = tr("file.type_folder", "文件夹") if file_type == 1 else tr("file.type_file", "文件")
                size_text = format_file_size(file_size)

                # 复用已有的 QTableWidgetItem，没有才新建
                name_item = self.fileTable.item(row, 0)
                if name_item is None:
                    name_item = QTableWidgetItem()
                    self.fileTable.setItem(row, 0, name_item)
                name_item.setText(file_name)
                name_item.setData(Qt.ItemDataRole.UserRole, file_id)
                name_item.setData(Qt.ItemDataRole.UserRole + 1, file_type)
                name_item.setIcon(
                    FIF.FOLDER.icon() if file_type == 1 else FIF.DOCUMENT.icon()
                )

                type_item = self.fileTable.item(row, 1)
                if type_item is None:
                    type_item = QTableWidgetItem()
                    self.fileTable.setItem(row, 1, type_item)
                type_item.setText(type_text)

                size_item = self.fileTable.item(row, 2)
                if size_item is None:
                    size_item = QTableWidgetItem()
                    self.fileTable.setItem(row, 2, size_item)
                size_item.setText(size_text)
        finally:
            self.fileTable.blockSignals(False)
            self.fileTable.setUpdatesEnabled(True)

    def __onLoadListFinished(self, file_items, error):
        """加载文件列表完成后的回调 - 只负责UI更新"""
        if error:
            InfoBar.error(
                title=tr("file.msg_load_failed", "加载失败"),
                content=tr("file.msg_load_error", "加载文件列表时发生错误: {}").format(error),
                parent=self,
            )
        else:
            # 对文件列表进行排序
            sorted_items = self.__sortFileList(file_items)
            # 更新文件列表（轻量级UI操作）
            self.__updateFileListUI(sorted_items)

    def __onSearchTextChanged(self, text):
        """搜索文本变化时启动防抖，清空时立即恢复"""
        self._search_text = text.strip().lower()
        if not self._search_text:
            self._search_timer.stop()
            self.__applySearchFilter()
        else:
            self._search_timer.start()

    def __applySearchFilter(self):
        """根据搜索文本过滤当前文件列表"""
        if not hasattr(self, "_current_file_items") or not self._current_file_items:
            return

        if not self._search_text:
            # 无搜索条件，恢复完整列表
            sorted_items = self.__sortFileList(self._current_file_items)
            self.__updateFileListUI(sorted_items)
            return

        # 按搜索文本过滤（不覆盖 _current_file_items 缓存，确保清空搜索后能恢复完整列表）
        filtered = [
            item for item in self._current_file_items
            if self._search_text in item.get("FileName", "").lower()
        ]
        sorted_items = self.__sortFileList(filtered)
        self.__updateFileListUI(sorted_items, update_cache=False)

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
        """列头排序指示器改变时的处理（纯客户端排序，不请求服务器）。"""
        if logicalIndex not in [0, 2]:
            return

        if logicalIndex == self.sort_mode:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_mode = logicalIndex
            self.sort_ascending = True if logicalIndex == 0 else False

        # 客户端重新排序，不重新请求服务器
        if self._search_text:
            self.__applySearchFilter()
        else:
            sorted_items = self.__sortFileList(self._current_file_items)
            self.__updateFileListUI(sorted_items)

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

    # noinspection PyTypeChecker
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

    # noinspection PyTypeChecker
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
        file_paths, _ = QFileDialog.getOpenFileNames(self, tr("file.upload_title", "选择要上传的文件"))

        if file_paths:
            self.__addUploadTasks(file_paths)

    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入时接受文件拖放"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        """拖拽移动时接受"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """处理拖放文件"""
        urls = event.mimeData().urls()
        if urls:
            file_paths = []
            for url in urls:
                path = url.toLocalFile()
                if path and Path(path).is_file():
                    file_paths.append(path)

            if file_paths:
                self.__addUploadTasks(file_paths)
            else:
                InfoBar.warning(
                    title=tr("file.drop_warn_title", "拖拽上传"),
                    content=tr("file.drop_warn_content", "只支持拖放文件，不支持文件夹"),
                    parent=self,
                )

    def __addUploadTasks(self, file_paths):
        """添加上传任务（共用方法）"""
        logger.info("准备上传 %d 个文件", len(file_paths))
        for file_path in file_paths:
            path = Path(file_path)
            file_name = path.name
            file_size = path.stat().st_size
            logger.debug(
                "上传文件: name=%s, size=%s, dir=%s",
                file_name,
                file_size,
                self.current_dir_id,
            )
            if self.transfer_interface:
                self.transfer_interface.add_upload_task(
                    file_name, file_size, file_path, self.current_dir_id
                )

        InfoBar.success(
            title=tr("file.msg_upload_success", "上传文件"),
            content=tr("file.msg_upload_added", "已添加 {} 个上传任务").format(len(file_paths)),
            parent=self,
        )

    def __downloadFile(self):
        """下载文件（支持批量）"""
        selected_rows = self.__getSelectedRows()
        if not selected_rows:
            InfoBar.warning(title=tr("file.msg_download_error", "下载错误"), content=tr("file.msg_select_file_download", "请选择要下载的文件"), parent=self)
            return

        from app.common.config import ConfigManager

        ask_download_location = ConfigManager.get_setting("askDownloadLocation", True)
        default_download_path = ConfigManager.get_setting(
            "defaultDownloadPath", str(Path.home() / "Downloads")
        )

        # 批量下载时：如果"每次询问"，先选目录；如果不询问，统一使用默认目录
        if ask_download_location and len(selected_rows) > 1:
            save_dir = QFileDialog.getExistingDirectory(
                self, tr("file.download_dir_title", "选择下载保存目录"), default_download_path
            )
            if not save_dir:
                return
            ask_download_location = False  # 批量模式下不再逐个询问
        else:
            save_dir = default_download_path

        count = 0
        for row in selected_rows:
            name_item = self.fileTable.item(row, 0)
            file_id = name_item.data(Qt.ItemDataRole.UserRole)
            file_name = name_item.text()
            file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)

            if file_type == 1:
                file_name = file_name + ".zip"

            if ask_download_location:
                save_path, _ = QFileDialog.getSaveFileName(
                    self, tr("file.save_file_title", "保存文件"), str(Path(default_download_path) / file_name)
                )
                if not save_path:
                    continue
            else:
                save_path = str(Path(save_dir) / file_name)

            file_info = self.__findFileById(file_id)
            file_size = int(file_info.get("Size", 0) or 0) if file_info else 0

            if self.transfer_interface:
                self.transfer_interface.add_download_task(
                    file_name, file_size, file_id, save_path, self.current_dir_id
                )
            count += 1

        if count > 0:
            InfoBar.success(
                title=tr("file.msg_download_success", "下载文件"),
                content=tr("file.msg_download_added", "已添加 {} 个下载任务").format(count),
                parent=self,
            )

    def __refreshFileList(self, force=False):
        """刷新文件列表。

        Args:
            force: 是否强制从服务器获取（跳过缓存）
        """
        self.searchBox.clear()
        self._search_text = ""
        self.__loadCurrentList(force_refresh=force)
        self.load_and_update_storage_info()

    def __getSelectedRows(self):
        """获取所有选中行的行号列表（去重）。"""
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            return []
        rows = sorted(set(item.row() for item in selected_items))
        return rows

    def __deleteFile(self, file_id=None, file_name=None):
        """删除文件（支持批量）"""

        # 如果没有提供file_id和file_name，则从选中的文件批量获取
        if file_id is None or file_name is None:
            selected_rows = self.__getSelectedRows()
            if not selected_rows:
                InfoBar.warning(
                    title=tr("file.msg_delete_error", "删除错误"), content=tr("file.msg_select_file_delete", "请选择要删除的文件"), parent=self
                )
                return

            if len(selected_rows) == 1:
                # 单文件删除走原有路径
                row = selected_rows[0]
                name_item = self.fileTable.item(row, 0)
                file_id = name_item.data(Qt.ItemDataRole.UserRole)
                file_name = name_item.text()
            else:
                # 批量删除
                self.__batchDeleteFiles(selected_rows)
                return

        # 单文件删除
        signals = _OpFinishedSignals()
        signals.finished.connect(self.__onDeleteFileFinished)
        task = DeleteFileTask(
            self.pan, file_id, file_name, self.current_dir_id, signals, self
        )
        QThreadPool.globalInstance().start(task)

    def __batchDeleteFiles(self, selected_rows):
        """批量删除文件。"""
        file_infos = []
        for row in selected_rows:
            name_item = self.fileTable.item(row, 0)
            fid = name_item.data(Qt.ItemDataRole.UserRole)
            fname = name_item.text()
            file_infos.append((fid, fname))

        # 在主线程创建信号
        signals = _OpFinishedSignals()
        signals.finished.connect(
            lambda success, name, new_name, error, items, folders: self.__onBatchDeleteFinished(
                success, name, new_name, error, items, folders
            )
        )
        task = BatchDeleteTask(
            self.pan, file_infos, self.current_dir_id, signals, self
        )
        QThreadPool.globalInstance().start(task)

    def __onBatchDeleteFinished(
        self, success, file_name, new_name, error, file_items, folder_items
    ):
        """批量删除完成后的回调"""
        if success:
            InfoBar.success(
                title=tr("file.msg_batch_delete_success", "批量删除成功"),
                content=file_name,
                parent=self,
            )
            self.__updateFileListUI(file_items)
            self.__updateTreeUI(folder_items)
            current_item = self.__findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        else:
            InfoBar.error(
                title=tr("file.msg_batch_delete_failed", "批量删除失败"),
                content=error or "批量删除失败",
                parent=self,
            )

    def __onDeleteFileFinished(
        self, success, file_name, new_name, error, file_items, folder_items
    ):
        """删除文件完成后的回调 - 只负责UI更新"""

        if success:
            # 显示成功信息
            InfoBar.success(
                title=tr("file.msg_delete_success", "删除成功"),
                content=tr("file.msg_file_deleted", "文件 '{}' 已成功删除").format(file_name),
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
                    title=tr("file.msg_delete_failed", "删除失败"),
                    content=tr("file.msg_delete_file_error", "删除文件时发生错误: {}").format(error),
                    parent=self,
                )
            else:
                # 显示错误信息
                InfoBar.error(title=tr("file.msg_delete_failed", "删除失败"), content=tr("file.msg_file_not_found", "文件不存在"), parent=self)

    def __renameFile(self):
        """重命名文件"""

        # 获取选中的文件
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title=tr("file.msg_rename_error", "重命名错误"), content=tr("file.msg_select_file_rename", "请选择要重命名的文件"), parent=self
            )
            return

        # 获取选中行的文件信息
        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        old_name = name_item.text()
        file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)

        # 使用重命名对话框获取新名称
        dialog = InputDialog(tr("file.menu_rename", "重命名"), "请输入新的名称", old_name, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        new_name = dialog.get_input_text()

        # 检查新名称是否为空
        if not new_name:
            InfoBar.warning(title=tr("file.msg_rename_error", "重命名错误"), content=tr("file.msg_name_empty", "名称不能为空"), parent=self)
            return

        # 检查新名称是否与旧名称相同
        if new_name == old_name:
            InfoBar.warning(
                title=tr("file.msg_rename_error", "重命名错误"),
                content=tr("file.msg_name_same", "新名称与旧名称相同"),
                parent=self,
            )
            return

        # 检查新名称是否包含无效字符
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in new_name for char in invalid_chars):
            InfoBar.warning(
                title=tr("file.msg_rename_error", "重命名错误"),
                content=tr("file.msg_invalid_chars", "名称不能包含以下字符: {}").format(" ".join(invalid_chars)),
                parent=self,
            )
            return

        # 在主线程创建信号
        signals = _OpFinishedSignals()
        signals.finished.connect(self.__onRenameFileFinished)
        task = RenameFileTask(
            self.pan, file_id, old_name, new_name, self.current_dir_id, signals, self
        )

        # 提交任务到线程池
        QThreadPool.globalInstance().start(task)

    def __onRenameFileFinished(
        self, success, old_name, new_name, error, file_items, folder_items
    ):
        """重命名文件完成后的回调 - 只负责UI更新"""

        if success:
            # 显示成功信息
            InfoBar.success(
                title=tr("file.msg_rename_success", "重命名成功"),
                content=tr("file.msg_file_renamed", "文件 '{}' 已成功重命名为 '{}'").format(old_name, new_name),
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
                    title=tr("file.msg_rename_failed", "重命名失败"),
                    content=tr("file.msg_rename_file_error", "重命名文件时发生错误: {}").format(error),
                    parent=self,
                )
            else:
                # 显示错误信息
                InfoBar.error(title=tr("file.msg_rename_failed", "重命名失败"), content=tr("file.msg_rename_failed", "重命名失败"), parent=self)

    # noinspection PyTypeChecker
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

        # 添加获取下载链接菜单项
        copy_link_action = QAction(FIF.LINK.icon(), tr("file.menu_copy_link", "获取下载链接"), self)
        copy_link_action.triggered.connect(self.__copyDownloadLink)
        menu.addAction(copy_link_action)

        # 添加预览菜单项
        preview_action = QAction(FIF.VIEW.icon(), tr("file.menu_preview", "预览"), self)
        preview_action.triggered.connect(self.__previewFile)
        menu.addAction(preview_action)

        # 添加分享菜单项
        share_action = QAction(FIF.LINK.icon(), tr("file.menu_share", "分享"), self)
        share_action.triggered.connect(self.__shareFile)
        menu.addAction(share_action)

        # 添加重命名菜单项
        rename_action = QAction(FIF.EDIT.icon(), tr("file.menu_rename", "重命名"), self)
        rename_action.triggered.connect(self.__renameFile)
        menu.addAction(rename_action)

        # 添加删除菜单项
        delete_action = QAction(FIF.DELETE.icon(), tr("file.delete", "删除"), self)
        delete_action.triggered.connect(self.__deleteFile)
        menu.addAction(delete_action)

        # 显示菜单
        menu.exec(self.fileTable.mapToGlobal(position))

    def __copyDownloadLink(self):
        """复制文件下载链接到剪贴板"""
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(title=tr("file.msg_copy_link_failed", "复制链接失败"), content=tr("file.msg_select_one_file", "请选择一个文件"), parent=self)
            return

        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()
        logger.info("获取下载链接: name=%s, id=%s", file_name, file_id)

        file_detail = self.__findFileById(file_id)

        if not file_detail:
            logger.warning("未找到文件详情: id=%s", file_id)
            InfoBar.error(title=tr("file.msg_copy_link_failed", "复制链接失败"), content=tr("file.msg_file_detail_not_found", "无法找到文件详情"), parent=self)
            return

        try:
            url = self.pan.link_by_fileDetail(file_detail, showlink=False)
            if isinstance(url, str) and url:
                clipboard = QApplication.clipboard()
                clipboard.setText(url)
                logger.info("下载链接已复制: %s", file_name)
                InfoBar.success(
                    title=tr("file.msg_copy_success", "复制成功"),
                    content=tr("file.msg_link_copied", "已复制 {} 的下载链接到剪贴板").format(file_name),
                    parent=self,
                )
            else:
                logger.error("获取下载链接失败: name=%s, url=%s", file_name, url)
                InfoBar.error(
                    title=tr("file.msg_copy_link_failed", "复制链接失败"), content=tr("file.msg_get_link_failed", "获取下载链接失败"), parent=self
                )
        except Exception as e:
            logger.error(f"复制下载链接失败: {e}")
            InfoBar.error(
                title="复制链接失败", content=tr("file.msg_error_occurred", "发生错误: {}").format(str(e)), parent=self
            )

    def __shareFile(self):
        """为选中文件/文件夹生成分享链接并复制到剪贴板（可选设置密码）。"""
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title=tr("file.msg_share_failed", "分享失败"), content=tr("file.msg_select_file_share", "请选择一个文件或文件夹"), parent=self
            )
            return

        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()
        logger.info("生成分享链接: name=%s, id=%s", file_name, file_id)

        pwd, ok = QInputDialog.getText(
            self, tr("file.share_pwd_title", "设置分享密码(可选)"), tr("file.share_pwd_label", "分享密码 (留空则无密码):")
        )
        if not ok:
            logger.debug("用户取消分享密码设置")
            return

        try:
            share_url = self.pan.share([int(file_id)], share_pwd=pwd or "")
            if isinstance(share_url, str) and share_url:
                QApplication.clipboard().setText(share_url)
                logger.info("分享成功: %s -> %s", file_name, share_url)
                InfoBar.success(
                    title=tr("file.msg_share_success", "分享成功"),
                    content=tr("file.msg_share_generated", "已生成分享链接并复制到剪贴板：{}").format(share_url),
                    parent=self,
                )
            else:
                logger.error("分享失败: name=%s, url=%s", file_name, share_url)
                InfoBar.error(title=tr("file.msg_share_failed", "分享失败"), content=tr("file.msg_share_gen_failed", "生成分享链接失败"), parent=self)
        except Exception as e:
            logger.error(f"生成分享链接失败: {e}")
            InfoBar.error(title="分享失败", content=str(e), parent=self)

    def __findFileById(self, file_id):
        """从缓存的文件列表中根据 file_id 查找文件详情。

        优先搜索 _current_file_items（当前目录），
        回退到 pan.list（历史缓存）。
        """
        # 先在当前目录缓存中查找
        for item in self._current_file_items:
            if str(item.get("FileId")) == str(file_id):
                return item
        # 回退到 pan.list
        for item in self.pan.list:
            if str(item.get("FileId")) == str(file_id):
                return item
        return None

    def __previewFile(self):
        """预览选中的文件。

        支持图片、视频、音频、文本等格式。
        不支持预览的格式将弹出提示。
        """
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title=tr("file.msg_preview_failed", "预览失败"), content=tr("file.msg_select_one_file", "请选择一个文件"), parent=self
            )
            return

        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        if name_item is None:
            return

        file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)
        if file_type == 1:
            InfoBar.warning(
                title="预览失败",
                content=tr("file.msg_folder_no_preview", "文件夹不支持预览，请双击打开"),
                parent=self,
            )
            return

        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()
        logger.info("预览文件: name=%s, id=%s", file_name, file_id)

        # 查找文件详情（从缓存的文件列表中查找，而非 pan.list）
        file_detail = self.__findFileById(file_id)

        if not file_detail:
            InfoBar.error(
                title="预览失败",
                content="无法找到文件详情",
                parent=self,
            )
            return

        # 检查是否支持预览
        from ..preview import is_preview_supported

        if not is_preview_supported(file_name):
            InfoBar.warning(
                title=tr("file.msg_preview_unsupported", "不支持预览"),
                content=tr("file.msg_preview_unsupported_type", "不支持预览此文件类型: {}").format(file_name),
                parent=self,
            )
            return

        # 打开预览对话框
        from ..preview.preview_dialog import PreviewDialog

        dialog = PreviewDialog(self.pan, file_detail, self)
        dialog.exec()

    def update_storage_info(self, used_text="0 B"):
        """更新云盘存储信息"""
        if used_text is None:
            used_text = "0 B"
        max_capacity = MAX_STORAGE_CAPACITY
        total_text = format_file_size(max_capacity)

        # 解析 used_text 来获取字节数，用于计算百分比
        # 格式示例: "1.5 GB", "512 MB", "2 KB", "1024 B"
        try:
            parts = used_text.split()
            if len(parts) == 2:
                value = float(parts[0])
                unit = parts[1].upper()

                # 转换为字节
                if unit == "GB":
                    used_bytes = int(value * 1024 * 1024 * 1024)
                elif unit == "MB":
                    used_bytes = int(value * 1024 * 1024)
                elif unit == "KB":
                    used_bytes = int(value * 1024)
                else:  # B
                    used_bytes = int(value)

                # 计算使用百分比
                usage_percent = (
                    (used_bytes / max_capacity * 100) if max_capacity > 0 else 0
                )
            else:
                usage_percent = 0
        except Exception as e:
            logger.error(f"解析存储信息时发生错误: {e}")
            usage_percent = 0

        # 更新进度条
        self.storageProgressBar.setValue(int(usage_percent))

        # 更新文本显示
        self.storageValueLabel.setText(f"{used_text} / {total_text}")

    def calculate_total_storage(self, dir_id=0):
        """
        统计指定目录下的总存储使用量

        Args:
            dir_id: 目录ID，默认为0（根目录）

        Returns:
            格式化后的总存储使用量字符串（如 "1.5 GB"）
        """
        total_size_mb = 0.0

        try:
            # 获取当前目录的文件列表，使用 all=True 确保获取所有文件
            code, items = self.pan.get_dir_by_id(
                dir_id, save=False, all=True, limit=1000
            )

            if code != 0 or not items:
                return "0 B"

            # 遍历文件列表
            for item in items:
                file_size = int(item.get("Size", 0) or 0)
                # 先转换为MB，再累计
                file_size_mb = file_size / (1024 * 1024)
                total_size_mb += file_size_mb

        except Exception as e:
            # 如果某个目录访问失败，返回0
            logger.error(f"统计目录 {dir_id} 时发生错误: {e}")
            return "0 B"

        # 将MB转换回字节，然后格式化
        total_size_bytes = int(total_size_mb * 1024 * 1024)
        return format_file_size(total_size_bytes)

    def load_and_update_storage_info(self):
        """统计并更新云盘存储信息"""
        if not self.pan:
            return

        # 在主线程创建信号
        signals = _StorageSignals()
        signals.finished.connect(self.update_storage_info)
        task = StorageTask(self, signals)
        QThreadPool.globalInstance().start(task)
