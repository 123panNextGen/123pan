"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtCore import Qt
from PySide6.QtCore import QThreadPool
from PySide6.QtCore import QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QVBoxLayout,
    QWidget,
    QLabel,
)

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
    SearchLineEdit,
)

from ..common.style_sheet import StyleSheet
from ..common.utils import format_file_size
from ..common.log import get_logger
from ..common.i18n import tr
from ..tasks.file_tasks import (
    LoadFolderListTask,
    LoadListTask,
    LoadStorageInfoTask,
)
from ..tasks.signals import (
    _FolderListSignals,
    _LoadListSignals,
    _StorageInfoSignals,
)
from .file_actions import FileActionsMixin
from .file_table import FileTableManager
from .file_tree import FileTreeManager
from ..tasks.file_tasks import connect_tracked

logger = get_logger(__name__)
# noinspection PyUnresolvedReferences
class FileInterface(QWidget, FileActionsMixin):
    """文件页面（仅浏览）"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("FileInterface")

        self.pan = None
        self.current_dir_id = 0
        self.path_stack = [(0, tr("file.root_dir", "根目录"))]
        self.is_updating_breadcrumb = False
        self.transfer_interface = None
        # 表格/目录树管理器（在 __createContent 中创建，持有渲染与缓存状态）
        self._table_mgr = None
        self._tree_mgr = None
        # 目录列表是否正在加载（用于空状态/加载提示）
        self._loading = False
        # 持有后台任务引用，防止任务/信号被 GC 回收导致 RuntimeError
        self._pending_tasks = []

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
        self.searchBox = SearchLineEdit(self.topBarFrame)
        self.searchBox.setPlaceholderText(tr("file.search_placeholder", "搜索文件名..."))
        self.searchBox.setClearButtonEnabled(True)
        self.searchBox.setMaximumWidth(200)
        self.searchBox.textChanged.connect(self.__onSearchTextChanged)

        # 右侧按钮
        self.newFolderButton = PushButton(
            FIF.FOLDER_ADD.icon(), tr("file.new_folder", "新建文件夹"), self.topBarFrame
        )
        self.uploadButton = PushButton(FIF.UP.icon(), tr("file.upload", "上传"), self.topBarFrame)
        self.offlineDownloadButton = PushButton(
            FIF.CLOUD_DOWNLOAD.icon(), tr("file.offline_download", "离线下载"), self.topBarFrame
        )
        self.downloadButton = PushButton(FIF.DOWNLOAD.icon(), tr("file.download", "下载"), self.topBarFrame)
        self.deleteButton = PushButton(FIF.DELETE.icon(), tr("file.delete", "删除"), self.topBarFrame)
        self.refreshButton = PushButton(FIF.UPDATE.icon(), tr("file.refresh", "刷新"), self.topBarFrame)

        self.topBarLayout.addWidget(self.backButton, 0)
        self.topBarLayout.addWidget(self.breadcrumbBar, 1)
        self.topBarLayout.addWidget(self.searchBox, 0)
        self.topBarLayout.addWidget(self.newFolderButton, 0)
        self.topBarLayout.addWidget(self.uploadButton, 0)
        self.topBarLayout.addWidget(self.offlineDownloadButton, 0)
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
        self._tree_mgr = FileTreeManager(self.folderTree)
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

        # 空目录/加载中/无匹配 状态提示（覆盖在表格上）
        self.listStateLabel = QLabel(
            tr("file.state_loading", "加载中..."), self.listFrame
        )
        self.listStateLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.listStateLabel.setStyleSheet("color: gray; font-size: 14px;")
        self.listStateLabel.hide()

        self.fileTable = TableWidget(self.listFrame)
        self.fileTable.setAlternatingRowColors(True)
        self.fileTable.setColumnCount(4)
        self.fileTable.setHorizontalHeaderLabels([tr("file.col_name", "名称"), tr("file.col_type", "类型"), tr("file.col_size", "大小"), tr("file.col_date", "日期")])
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
            # 名称列允许用户手动调整宽度（默认 320px），其余列按内容自适应；
            # 长文件名被截断时可拖动列宽查看完整名称。
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.resizeSection(0, 320)
            header.setMinimumSectionSize(60)
            # 启用列头点击排序
            header.setSectionsClickable(True)
            header.setSortIndicatorShown(True)
            header.sortIndicatorChanged.connect(self.__onHeaderSortIndicatorChanged)
        self.listLayout.addWidget(self.fileTable)

        # 表格管理器（渲染/排序/过滤/空状态）
        self._table_mgr = FileTableManager(self.fileTable, self.listStateLabel)

        self.contentLayout.addWidget(self.treeFrame, 2)
        self.contentLayout.addWidget(self.listFrame, 5)

        self.mainLayout.addLayout(self.contentLayout, 1)

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()
        # 为文件表格添加右键菜单
        self.fileTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fileTable.customContextMenuRequested.connect(self._onFileTableContextMenu)
        # 启用拖拽上传
        self.setAcceptDrops(True)
        self.fileTable.setAcceptDrops(True)
        # 初始化快捷键
        self.__initShortcuts()
        self.__loadPanAndData()

    def __initShortcuts(self):
        """初始化键盘快捷键"""
        # F5: 刷新
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, self._refreshFileList)
        # Ctrl+N: 新建文件夹
        QShortcut(QKeySequence("Ctrl+N"), self, self._createNewFolder)
        # Ctrl+U: 上传文件
        QShortcut(QKeySequence("Ctrl+U"), self, self._uploadFile)
        # Ctrl+D: 下载选中文件
        QShortcut(QKeySequence("Ctrl+D"), self, self._downloadFile)
        # Delete: 删除选中文件
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, self._deleteFile)
        # F2: 重命名
        QShortcut(QKeySequence(Qt.Key.Key_F2), self, self._renameFile)
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
        self.newFolderButton.clicked.connect(self._createNewFolder)
        self.uploadButton.clicked.connect(self._showUploadMenu)
        self.offlineDownloadButton.clicked.connect(self._openOfflineDownload)
        self.downloadButton.clicked.connect(self._downloadFile)
        self.deleteButton.clicked.connect(self._deleteFile)
        self.refreshButton.clicked.connect(self._refreshFileList)

    def load_pan_and_data(self):
        """公开接口：加载 Pan123 实例并初始化数据（供 MainWindow 调用）。"""
        self.__loadPanAndData()

    def __loadPanAndData(self):
        """加载 Pan123 实例并初始化数据。

        只由外部传入的 pan 驱动（MainWindow 在登录流程中设置 pan 后
        调用 load_pan_and_data）。pan 未就绪时不在此处同步构造
        Pan123（其构造器含网络请求），避免阻塞主线程导致启动白屏。
        """
        if self.pan is None:
            logger.debug("__loadPanAndData: pan 未设置，等待登录流程注入")
            return

        try:
            self.__initTree()
            self._loadCurrentList()
            self.__updateBreadcrumb()
            self.__updateBackButtonState()
            self.load_and_update_storage_info()
        except Exception as e:
            self.__setErrorBreadcrumb(tr("file.init_error", "初始化失败: {}").format(e))
            self.backButton.setEnabled(False)

    def __initTree(self):
        """重建目录树（委托 FileTreeManager）。"""
        self._tree_mgr.init_tree()

    def __onTreeItemExpanded(self, item):
        self.__ensureTreeChildrenLoaded(item)

    def __ensureTreeChildrenLoaded(self, item):
        """确保节点子文件夹已加载（懒加载，后台线程）。"""
        self._tree_mgr.ensure_loaded(item, self.__loadTreeChildren)

    def __loadTreeChildren(self, dir_id, item):
        """发起后台加载指定目录的子文件夹列表。"""
        signals = _FolderListSignals()
        task = LoadFolderListTask(self.pan, dir_id, signals)
        connect_tracked(
            self, signals, "finished",
            lambda did, folders, err, it=item: self.__onTreeFolderLoaded(
                it, did, folders, err
            ),
            task,
        )
        QThreadPool.globalInstance().start(task)

    def __onTreeFolderLoaded(self, item, dir_id, folders, error):
        """目录树子文件夹加载完成回调（主线程）。"""
        self._tree_mgr.on_folder_loaded(item, dir_id, folders, error)

    def __onTreeItemClicked(self, item):
        dir_id = item.data(0, Qt.ItemDataRole.UserRole)
        if dir_id is None:
            return

        self.__ensureTreeChildrenLoaded(item)

        self.current_dir_id = int(dir_id)
        self.path_stack = self._tree_mgr.build_path_stack(item)
        self._loadCurrentList()
        self.__updateBreadcrumb()
        self.__updateBackButtonState()

    def __goParentDir(self):
        if len(self.path_stack) <= 1:
            return

        self.path_stack.pop()
        self.current_dir_id = self.path_stack[-1][0]
        self._loadCurrentList()
        self.__updateBreadcrumb()
        self.__updateBackButtonState()

        current_item = self._findTreeItemById(self.current_dir_id)
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
            self._loadCurrentList()
            self.__updateBreadcrumb()
            self.__updateBackButtonState()

            tree_item = self._findTreeItemById(file_id)
            if tree_item:
                self.folderTree.setCurrentItem(tree_item)
                self.folderTree.expandItem(tree_item)
        else:
            # 文件：尝试预览
            self._previewFile()

    def _loadCurrentList(self, force_refresh=False):
        if not self.pan:
            logger.warning("__loadCurrentList: pan 未设置")
            return

        logger.debug("加载文件列表: dir_id=%s, force=%s", self.current_dir_id, force_refresh)
        self._loading = True
        self.fileTable.setRowCount(0)
        self.__updateListState(0)

        signals = _LoadListSignals()
        task = LoadListTask(
            lambda dir_id: self.__fetchDirList(dir_id, force_refresh),
            self.current_dir_id, signals,
        )
        connect_tracked(self, signals, "finished", self.__onLoadListFinished, task)

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

    def _findTreeItemById(self, dir_id):
        """按目录 ID 查找树节点（委托 FileTreeManager）。"""
        return self._tree_mgr.find_item(dir_id)

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
        self._loadCurrentList()
        self.__updateBackButtonState()

        tree_item = self._findTreeItemById(target_dir_id)
        if tree_item:
            self.folderTree.setCurrentItem(tree_item)

    def __updateBackButtonState(self):
        """更新返回按钮状态"""
        self.backButton.setEnabled(len(self.path_stack) > 1)

    def _updateFileListUI(self, file_items, update_cache=True):
        """更新文件列表UI（委托 FileTableManager）。

        update_cache=False 时不覆盖完整列表缓存，用于搜索过滤场景。
        """
        self._table_mgr.set_items(file_items, update_cache=update_cache)

    def __onLoadListFinished(self, file_items, error):
        """加载文件列表完成后的回调 - 只负责UI更新"""
        self._loading = False
        if error:
            InfoBar.error(
                title=tr("file.msg_load_failed", "加载失败"),
                content=tr("file.msg_load_error", "加载文件列表时发生错误: {}").format(error),
                parent=self,
            )
            self.__updateListState(0)
        else:
            # 对文件列表进行排序
            sorted_items = self.__sortFileList(file_items)
            # 更新文件列表（轻量级UI操作）
            self._updateFileListUI(sorted_items)
            self.__updateListState(len(sorted_items))

    def __updateListState(self, count):
        """更新表格空状态/加载提示（委托 FileTableManager）。"""
        self._table_mgr.update_state(count, self._loading)

    def resizeEvent(self, event):
        """保持表格状态提示覆盖层与列表区域同步。"""
        super().resizeEvent(event)
        state_label = getattr(self, "listStateLabel", None)
        if state_label is not None and self.listFrame is not None:
            state_label.setGeometry(self.listFrame.rect())

    def __onSearchTextChanged(self, text):
        """搜索文本变化时启动防抖，清空时立即恢复"""
        self._table_mgr.search_text = text.strip().lower()
        if not self._table_mgr.search_text:
            self._search_timer.stop()
            self.__applySearchFilter()
        else:
            self._search_timer.start()

    def __applySearchFilter(self):
        """根据搜索文本过滤当前文件列表（委托 FileTableManager）。"""
        if not self._table_mgr.current_items:
            return
        self._table_mgr.apply_search(self._loading)

    def __sortFileList(self, file_items):
        """对文件列表进行排序，文件夹始终在前（委托 FileTableManager）。"""
        return self._table_mgr.sort(file_items)

    def __onHeaderSortIndicatorChanged(self, logicalIndex, order):
        """列头排序指示器改变时的处理（纯客户端排序，不请求服务器）。"""
        if logicalIndex not in [0, 2, 3]:
            return

        mgr = self._table_mgr
        clicked_same_column = logicalIndex == mgr.sort_mode
        mgr.sort_mode = logicalIndex

        if clicked_same_column:
            # 点击同一列：切换方向
            mgr.sort_ascending = not mgr.sort_ascending
        else:
            # 切换到新列：名称默认升序，大小/日期默认降序
            mgr.sort_ascending = logicalIndex == 0

        # 客户端重新排序，不重新请求服务器
        if mgr.search_text:
            mgr.apply_search(self._loading)
        else:
            mgr.set_items(mgr.sort(mgr.current_items))

    def _updateTreeUI(self, folder_items):
        """更新树结构UI（委托 FileTreeManager，轻量级操作）。"""
        self._tree_mgr.update_folders(self.current_dir_id, folder_items)

    def update_storage_info(self, space_used=0, space_total=0):
        """更新云盘存储信息（使用 API 返回的用户空间数据）。

        Args:
            space_used: 已用空间（字节）
            space_total: 永久空间总量（字节）
        """
        used_text = format_file_size(space_used)
        total_text = format_file_size(space_total) if space_total > 0 else format_file_size(2 * 1024 ** 4)

        if space_total > 0:
            usage_percent = space_used / space_total * 100
        else:
            usage_percent = 0

        self.storageProgressBar.setValue(int(usage_percent))
        self.storageValueLabel.setText(f"{used_text} / {total_text}")

    def load_and_update_storage_info(self):
        """从 API 获取用户云盘空间信息并更新显示（后台线程，避免阻塞 GUI）。"""
        if not self.pan:
            return

        signals = _StorageInfoSignals()
        task = LoadStorageInfoTask(self.pan, signals)
        connect_tracked(self, signals, "finished", self.__onStorageInfoFinished, task)
        QThreadPool.globalInstance().start(task)

    def __onStorageInfoFinished(self, user_info, error):
        """云盘空间信息加载完成回调（主线程）。"""
        if error or user_info is None:
            logger.warning("获取用户信息失败: %s", error)
            return

        space_used = getattr(user_info, "space_used", 0)
        space_total = getattr(user_info, "space_total", 0)
        self.update_storage_info(space_used, space_total)
