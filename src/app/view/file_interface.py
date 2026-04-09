from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QEvent, QRunnable, QThreadPool, Signal, QObject
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
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
)
from PySide6.QtGui import QAction, QShortcut, QKeySequence

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    BreadcrumbBar,
    TableWidget,
    TreeWidget,
    PushButton,
    SplitPushButton,
    InfoBar,
    Action,
    CardWidget,
    BodyLabel,
    IconWidget,
    ProgressBar,
    RoundMenu,
    MessageBox,
    SearchLineEdit,
    ToolButton,
)

from ..common.database import Database
from ..common.style_sheet import StyleSheet
from ..common.api import format_file_size

from ..common.log import get_logger
from .newfolder_window import NewFolderDialog
from .rename_window import RenameDialog
from .move_window import MoveDialog
from .search_window import SearchDialog

logger = get_logger(__name__)

# Windows 保留名
_WINDOWS_RESERVED = frozenset(
    "CON PRN AUX NUL COM1 COM2 COM3 COM4 COM5 COM6 COM7 COM8 COM9 "
    "LPT1 LPT2 LPT3 LPT4 LPT5 LPT6 LPT7 LPT8 LPT9".split()
)


def _sanitize_filename(name: str) -> str:
    """H10: 过滤非法字符和保留名，防止路径注入。"""
    import re as _re
    name = _re.sub(r'[<>:"|?*\\]', '_', name)
    name = name.rstrip('. ')
    if not name:
        name = "_unnamed"
    stem = Path(name).stem.upper()
    if stem in _WINDOWS_RESERVED:
        name = "_" + name
    if len(name) > 200:
        ext = Path(name).suffix
        name = name[:200 - len(ext)] + ext
    return name


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

        # H9: 异步加载请求 ID，防止旧回调覆盖新数据
        self._load_request_id = 0

        # 防止 QRunnable 异步任务的 signals 在回调处理前被 GC
        self._pending_signals = []

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
        self.topBarOuterLayout = QVBoxLayout(self.topBarFrame)
        self.topBarOuterLayout.setContentsMargins(12, 10, 12, 10)
        self.topBarOuterLayout.setSpacing(6)

        # 第一行：操作按钮 + 搜索
        self.actionBarLayout = QHBoxLayout()
        self.actionBarLayout.setSpacing(8)

        self.newFolderButton = PushButton(
            FIF.FOLDER_ADD.icon(), "新建文件夹", self.topBarFrame
        )
        self.__createUploadButtonGroup()
        self.downloadButton = PushButton(FIF.DOWNLOAD.icon(), "下载", self.topBarFrame)
        self.deleteButton = PushButton(FIF.DELETE.icon(), "删除", self.topBarFrame)

        self.searchBar = SearchLineEdit(self.topBarFrame)
        self.searchBar.setPlaceholderText("搜索文件")
        self.searchBar.setFixedWidth(200)

        self.actionBarLayout.addWidget(self.newFolderButton)
        self.actionBarLayout.addWidget(self.uploadButtonGroup)
        self.actionBarLayout.addWidget(self.downloadButton)
        self.actionBarLayout.addWidget(self.deleteButton)
        self.actionBarLayout.addStretch(1)
        self.actionBarLayout.addWidget(self.searchBar)

        # 第二行：返回 + 面包屑 + 刷新
        self.navBarLayout = QHBoxLayout()
        self.navBarLayout.setSpacing(4)

        self.backButton = ToolButton(FIF.LEFT_ARROW, self.topBarFrame)
        self.backButton.setToolTip("返回上一级")
        self.breadcrumbBar = BreadcrumbBar(self.topBarFrame)
        self.refreshButton = PushButton(FIF.UPDATE.icon(), "刷新", self.topBarFrame)

        self.navBarLayout.addWidget(self.backButton, 0)
        self.navBarLayout.addWidget(self.breadcrumbBar, 1)
        self.navBarLayout.addWidget(self.refreshButton, 0)

        self.topBarOuterLayout.addLayout(self.actionBarLayout)
        self.topBarOuterLayout.addLayout(self.navBarLayout)

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

        self.storageLabel = BodyLabel("云盘空间", self.storageCard)
        self.storageTopLayout.addWidget(self.storageLabel)

        self.storageValueLabel = BodyLabel("-- / --", self.storageCard)
        self.storageValueLabel.setStyleSheet("font-size: 12px; color: gray;")
        self.storageTopLayout.addWidget(self.storageValueLabel, 0, Qt.AlignmentFlag.AlignRight)

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
        self.fileTable.setHorizontalHeaderLabels(["名称", "类型", "大小"])
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

        self.statusLabel = BodyLabel("", self.listFrame)
        self.statusLabel.setStyleSheet("font-size: 12px; color: gray; padding: 4px 8px;")
        self.listLayout.addWidget(self.statusLabel)

        self.contentLayout.addWidget(self.treeFrame, 1)
        self.contentLayout.addWidget(self.listFrame, 6)

        self.mainLayout.addLayout(self.contentLayout, 1)

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()
        self.__setupShortcuts()
        self.setAcceptDrops(True)
        self.fileTable.viewport().setAcceptDrops(True)
        self.fileTable.viewport().installEventFilter(self)
        # 为文件表格添加右键菜单
        self.fileTable.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fileTable.customContextMenuRequested.connect(self.__onFileTableContextMenu)
        self.__loadPanAndData()

    def eventFilter(self, watched, event):
        if watched is self.fileTable.viewport() and self.__handleDropEvent(event):
            return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if self.__handleDropEvent(event):
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self.__handleDropEvent(event):
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if self.__handleDropEvent(event):
            return
        super().dropEvent(event)

    def __connectSignalToSlot(self):
        self.folderTree.itemClicked.connect(self.__onTreeItemClicked)
        self.folderTree.itemExpanded.connect(self.__onTreeItemExpanded)
        self.fileTable.itemDoubleClicked.connect(self.__onTableItemDoubleClicked)
        self.fileTable.itemSelectionChanged.connect(self.__updateStatusLabel)
        self.breadcrumbBar.currentItemChanged.connect(self.__onBreadcrumbItemChanged)
        self.newFolderButton.clicked.connect(self.__createNewFolder)
        self.uploadButton.clicked.connect(self.__uploadFile)
        self.downloadButton.clicked.connect(self.__downloadFile)
        self.deleteButton.clicked.connect(self.__deleteFile)
        self.refreshButton.clicked.connect(self.__refreshFileList)
        self.backButton.clicked.connect(self.__goUpToParent)
        self.searchBar.searchSignal.connect(self.__onSearch)
        self.searchBar.returnPressed.connect(self.searchBar.search)

    def __setupShortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self).activated.connect(
            self.__onDeleteShortcut
        )
        QShortcut(QKeySequence(Qt.Key.Key_F2), self).activated.connect(
            self.__onRenameShortcut
        )
        QShortcut(QKeySequence(Qt.Key.Key_F5), self).activated.connect(
            self.__refreshFileList
        )
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self.searchBar.setFocus
        )
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self).activated.connect(
            self.__onBackspaceShortcut
        )

    def __onDeleteShortcut(self):
        if self.searchBar.hasFocus():
            return
        self.__deleteFile()

    def __onRenameShortcut(self):
        if self.searchBar.hasFocus():
            return
        self.__renameFile()

    def __onBackspaceShortcut(self):
        if self.searchBar.hasFocus():
            return
        self.__goUpToParent()

    def __goUpToParent(self):
        if len(self.path_stack) <= 1:
            return
        self.path_stack.pop()
        self.current_dir_id = self.path_stack[-1][0]
        self.__loadCurrentList()
        self.__updateBreadcrumb()
        tree_item = self.__findTreeItemById(self.current_dir_id)
        if tree_item:
            self.folderTree.setCurrentItem(tree_item)

    def __createUploadButtonGroup(self):
        self.uploadMenu = RoundMenu(parent=self)
        self.uploadMenu.addAction(
            Action(FIF.DOCUMENT.icon(), "上传文件", triggered=self.__uploadFile)
        )
        self.uploadMenu.addAction(
            Action(FIF.FOLDER.icon(), "上传文件夹", triggered=self.__uploadFolder)
        )
        self.uploadButton = SplitPushButton(
            "上传文件",
            self.topBarFrame,
            FIF.DOCUMENT,
        )
        self.uploadButton.setFlyout(self.uploadMenu)
        self.uploadButton.setDropIcon(FIF.DOWN)
        self.uploadButton.dropButton.setToolTip("更多上传方式")
        self.uploadButtonGroup = self.uploadButton

    def __handleDropEvent(self, event):
        event_type = event.type()
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            result = self.__acceptLocalDrop(event)
            if result:
                self.fileTable.viewport().setStyleSheet(
                    "border: 2px dashed #0078d4; border-radius: 8px;"
                )
            return result
        if event_type == QEvent.Type.DragLeave:
            self.fileTable.viewport().setStyleSheet("")
            return False
        if event_type == QEvent.Type.Drop:
            self.fileTable.viewport().setStyleSheet("")
            return self.__dropLocalPaths(event)
        return False

    def __acceptLocalDrop(self, event):
        if not self.__extractLocalPaths(event.mimeData()):
            return False
        event.acceptProposedAction()
        return True

    def __dropLocalPaths(self, event):
        local_paths = self.__extractLocalPaths(event.mimeData())
        if not local_paths:
            return False
        event.acceptProposedAction()
        self.__prepareLocalUploads(local_paths)
        return True

    @staticmethod
    def __extractLocalPaths(mime_data):
        if mime_data is None or not mime_data.hasUrls():
            return []

        local_paths = []
        seen = set()
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            local_file = url.toLocalFile().strip()
            if not local_file or local_file in seen:
                continue
            seen.add(local_file)
            local_paths.append(Path(local_file))

        return local_paths

    def reload(self):
        """公开方法：重新加载 pan 数据和文件列表"""
        self.__loadPanAndData()

    def refresh(self):
        """公开方法：刷新当前文件列表"""
        self.__refreshFileList()

    def __loadPanAndData(self):
        try:
            self.__initTree()
            self.__loadCurrentList()
            self.__updateBreadcrumb()

            # 统计并更新云盘存储信息
            self.load_and_update_storage_info()
        except Exception as e:
            self.__setErrorBreadcrumb(f"初始化失败: {e}")

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

        # 使用后台线程加载文件列表，避免阻塞主线程
        self.fileTable.setRowCount(0)

        # H9: 递增请求 ID，回调时比对
        self._load_request_id += 1
        current_request_id = self._load_request_id

        # 创建任务
        task = self.LoadListTask(self.__fetchDirList, self.current_dir_id)

        # 持有 signals 引用防止 QRunnable autoDelete 后 signals 被 GC
        signals = task.signals
        self._pending_signals.append(signals)

        def _on_finished(items, err, rid=current_request_id, sig=signals):
            self.__onLoadListFinished(items, err, rid)
            if sig in self._pending_signals:
                self._pending_signals.remove(sig)

        signals.finished.connect(_on_finished)

        # 提交任务到线程池
        QThreadPool.globalInstance().start(task)

    def __fetchDirList(self, dir_id, search_data=""):
        if not self.pan:
            return []
        try:
            code, items = self.pan.get_dir_by_id(
                dir_id, save=False, all=True, limit=100, search_data=search_data
            )
            if code != 0:
                raise RuntimeError(f"获取文件列表失败，返回码: {code}")
            return items
        except Exception:
            raise

    # 后台加载文件列表的信号和任务类
    class LoadListTask(QRunnable):
        class LoadListSignals(QObject):
            finished = Signal(list, str)  # file_items, error

        def __init__(self, fetch_method, dir_id, search_data=""):
            super().__init__()
            self.fetch_method = fetch_method
            self.dir_id = dir_id
            self.search_data = search_data
            # 将信号对象作为成员变量，防止被垃圾回收
            self.signals = self.LoadListSignals()

        def run(self):
            try:
                file_items = self.fetch_method(self.dir_id, self.search_data)
                self.signals.finished.emit(file_items, "")
            except Exception as e:
                self.signals.finished.emit([], str(e))

    class PrepareUploadTask(QRunnable):
        class PrepareUploadSignals(QObject):
            finished = Signal(list, int, list, str)

        def __init__(self, pan, target_dir_id, local_paths):
            super().__init__()
            self.pan = pan
            self.target_dir_id = target_dir_id
            self.local_paths = local_paths
            self.signals = self.PrepareUploadSignals()

        def run(self):
            try:
                uploads = []
                created_dir_count = 0
                folder_items = []
                skipped_files = []
                for local_path in self.local_paths:
                    path = Path(local_path)
                    if path.is_dir():
                        plan = self.pan.prepare_folder_upload(
                            path, self.target_dir_id
                        )
                        uploads.extend(plan["file_targets"])
                        created_dir_count += int(plan["created_dir_count"])
                        folder_items.append(
                            {
                                "FileId": plan["root_dir_id"],
                                "FileName": plan["root_dir_name"],
                            }
                        )
                        continue

                    try:
                        if not path.exists():
                            raise FileNotFoundError(f"路径不存在: {path}")
                        uploads.append(
                            {
                                "file_name": path.name,
                                "file_size": path.stat().st_size,
                                "local_path": str(path),
                                "target_dir_id": self.target_dir_id,
                            }
                        )
                    except Exception as exc:
                        skipped_files.append(f"{path.name}: {exc}")

                self.signals.finished.emit(
                    uploads,
                    created_dir_count,
                    folder_items,
                    "；".join(skipped_files),
                )
            except Exception as e:
                self.signals.finished.emit([], 0, [], str(e))

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
        self.__updateBreadcrumb()

        tree_item = self.__findTreeItemById(target_dir_id)
        if tree_item:
            self.folderTree.setCurrentItem(tree_item)

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
                finished = Signal(
                    bool, str, str, list, list
                )  # result, folder_name, error, file_items, folder_items

            class CreateFolderTask(QRunnable):
                def __init__(self, pan, folder_name, current_dir_id, signals):
                    super().__init__()
                    self.pan = pan
                    self.folder_name = folder_name
                    self.current_dir_id = current_dir_id
                    self.signals = signals

                def run(self):
                    try:
                        result = self.pan._create_directory(
                            self.current_dir_id,
                            self.folder_name,
                        )

                        if result:
                            code, items = self.pan.get_dir_by_id(
                                self.current_dir_id, save=False, all=True, limit=100
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

                            self.signals.finished.emit(
                                True, self.folder_name, "", items, folder_items
                            )
                        else:
                            self.signals.finished.emit(
                                False, self.folder_name, "", [], []
                            )
                    except Exception as e:
                        self.signals.finished.emit(
                            False, self.folder_name, str(e), [], []
                        )

            # 创建信号和任务
            signals = CreateFolderSignals()
            signals.finished.connect(self.__onCreateFolderFinished)
            task = CreateFolderTask(self.pan, folder_name, self.current_dir_id, signals)

            # 持有 signals 引用防止 GC
            self._pending_signals.append(signals)
            signals.finished.connect(lambda *_, sig=signals: (
                self._pending_signals.remove(sig) if sig in self._pending_signals else None
            ))

            # 提交任务到线程池
            QThreadPool.globalInstance().start(task)

    def __onCreateFolderFinished(
        self, result, folder_name, error, file_items, folder_items
    ):
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
            name_item.setData(Qt.ItemDataRole.UserRole + 2, dict(file_item))
            name_item.setIcon(
                FIF.FOLDER.icon() if file_type == 1 else FIF.DOCUMENT.icon()
            )

            type_item = QTableWidgetItem(type_text)
            size_item = QTableWidgetItem(size_text)

            self.fileTable.setItem(row, 0, name_item)
            self.fileTable.setItem(row, 1, type_item)
            self.fileTable.setItem(row, 2, size_item)

    def __onLoadListFinished(self, file_items, error, request_id=None):
        """加载文件列表完成后的回调 - 只负责UI更新"""
        # H9: 丢弃过期的回调结果
        if request_id is not None and request_id != self._load_request_id:
            return
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
        self.__updateStatusLabel()

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

        reverse = not self.sort_ascending
        if self.sort_mode == 0:  # 按名称排序
            folders.sort(key=lambda x: x.get("FileName", ""), reverse=reverse)
            files.sort(key=lambda x: x.get("FileName", ""), reverse=reverse)
        elif self.sort_mode == 2:  # 按大小排序
            folders.sort(key=lambda x: int(x.get("Size", 0) or 0), reverse=reverse)
            files.sort(key=lambda x: int(x.get("Size", 0) or 0), reverse=reverse)

        result = folders + files

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

            # M10: 删除不在新 folder_items 中的节点
            new_ids = {int(f.get("FileId", 0)) for f in folder_items}
            for file_id, child in list(existing_items.items()):
                if file_id not in new_ids:
                    current_item.removeChild(child)
                    del existing_items[file_id]

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

    def __uploadFile(self):
        """上传文件"""
        # 打开文件选择对话框
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择要上传的文件")

        if file_paths:
            self.__prepareLocalUploads([Path(file_path) for file_path in file_paths])

    def __uploadFolder(self):
        """上传文件夹"""
        folder_path = QFileDialog.getExistingDirectory(self, "选择要上传的文件夹")
        if folder_path:
            self.__prepareLocalUploads([Path(folder_path)])

    def __prepareLocalUploads(self, local_paths):
        if not self.pan:
            InfoBar.error(title="上传失败", content="当前未登录", parent=self)
            return
        if not self.transfer_interface:
            InfoBar.error(title="上传失败", content="传输页面未初始化", parent=self)
            return
        if not local_paths:
            return

        task = self.PrepareUploadTask(
            self.pan,
            self.current_dir_id,
            [str(path) for path in local_paths],
        )
        context = {
            "pan": self.pan,
            "account_name": getattr(self.transfer_interface, "current_account_name", ""),
            "target_dir_id": self.current_dir_id,
        }
        signals = task.signals
        self._pending_signals.append(signals)
        signals.finished.connect(
            lambda uploads, created_dir_count, folder_items, error, ctx=context:
            self.__onPrepareUploadFinished(
                uploads, created_dir_count, folder_items, error, ctx
            )
        )
        signals.finished.connect(lambda *_, sig=signals: (
            self._pending_signals.remove(sig) if sig in self._pending_signals else None
        ))
        QThreadPool.globalInstance().start(task)

    def __onPrepareUploadFinished(
        self, uploads, created_dir_count, folder_items, error, context=None
    ):
        if context is not None:
            current_account_name = getattr(
                self.transfer_interface, "current_account_name", ""
            )
            if self.pan is not context["pan"] or current_account_name != context["account_name"]:
                logger.info("上传准备结果已过期，丢弃回调")
                return
            should_refresh_current_dir = self.current_dir_id == context["target_dir_id"]
        else:
            should_refresh_current_dir = True

        if error and not uploads and not folder_items:
            InfoBar.error(
                title="上传准备失败",
                content=f"准备上传任务时发生错误: {error}",
                parent=self,
            )
            return

        added_count = 0
        for upload in uploads:
            self.transfer_interface.add_upload_task(
                upload["file_name"],
                upload["file_size"],
                upload["local_path"],
                upload["target_dir_id"],
            )
            added_count += 1

        if folder_items and should_refresh_current_dir:
            self.__updateTreeUI(folder_items)
        if (uploads or folder_items) and should_refresh_current_dir:
            self.__refreshFileList()

        InfoBar.success(
            title="上传文件",
            content=self.__buildUploadSummary(added_count, created_dir_count),
            parent=self,
        )
        if error:
            InfoBar.warning(
                title="部分文件已跳过",
                content=error,
                parent=self,
            )

    @staticmethod
    def __buildUploadSummary(upload_count, created_dir_count):
        if upload_count and created_dir_count:
            return (
                f"已添加 {upload_count} 个上传任务，"
                f"创建 {created_dir_count} 个文件夹"
            )
        if created_dir_count:
            return f"已创建 {created_dir_count} 个文件夹"
        return f"已添加 {upload_count} 个上传任务"

    def __getSelectedRows(self):
        """从 selectedItems 提取去重行号列表"""
        rows = sorted({item.row() for item in self.fileTable.selectedItems()})
        return rows

    def __downloadFile(self):
        """下载文件（支持多选）"""
        rows = self.__getSelectedRows()
        if not rows:
            InfoBar.warning(title="下载错误", content="请选择要下载的文件", parent=self)
            return

        ask_download_location = Database.instance().get_config("askDownloadLocation", True)
        default_download_path = Database.instance().get_config(
            "defaultDownloadPath", str(Path.home() / "Downloads")
        )
        single_save_path = ""

        # 多选且需要询问位置时，弹一次目录选择
        download_dir = default_download_path
        if ask_download_location:
            if len(rows) > 1:
                chosen = QFileDialog.getExistingDirectory(
                    self, "选择下载目录", default_download_path,
                )
                if not chosen:
                    return
                download_dir = chosen
            else:
                name_item = self.fileTable.item(rows[0], 0)
                fname = name_item.text()
                ftype = name_item.data(Qt.ItemDataRole.UserRole + 1)
                if ftype == 1:
                    fname += ".zip"
                chosen, _ = QFileDialog.getSaveFileName(
                    self, "保存文件", str(Path(download_dir) / fname),
                )
                if not chosen:
                    return
                # 单文件直接走后面逻辑
                download_dir = None
                single_save_path = chosen

        added = 0
        for row in rows:
            name_item = self.fileTable.item(row, 0)
            file_id = name_item.data(Qt.ItemDataRole.UserRole)
            file_name = name_item.text()
            file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)
            file_meta = name_item.data(Qt.ItemDataRole.UserRole + 2) or {}

            if file_type == 1:
                file_name += ".zip"

            file_name = _sanitize_filename(file_name)

            if download_dir is not None:
                save_path = str(Path(download_dir) / file_name)
            else:
                save_path = single_save_path

            file_size = int(file_meta.get("Size", 0) or 0)
            if self.transfer_interface:
                self.transfer_interface.add_download_task(
                    file_name, file_size, file_id, save_path,
                    self.current_dir_id,
                    file_type=file_type,
                    etag=file_meta.get("Etag", ""),
                    s3key_flag=file_meta.get("S3KeyFlag", False),
                )
                added += 1

        if added:
            InfoBar.success(
                title="下载文件",
                content=f"已添加 {added} 个下载任务",
                parent=self,
            )

    def __refreshFileList(self):
        """刷新文件列表"""
        self.__loadCurrentList()
        # 同时更新云盘存储信息
        self.load_and_update_storage_info()

    def __onSearch(self, text):
        if not self.pan:
            return
        dlg = SearchDialog(self.pan, self)
        dlg.searchBar.setText(text)
        dlg.searchBar.search()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            if result:
                self.__jumpToFile(result)

    def __jumpToFile(self, result):
        """搜索结果跳转：进入文件所在目录并选中"""
        file_id = int(result.get("FileId", 0))
        file_type = int(result.get("Type", 0))
        parent_id = int(result.get("ParentFileId", 0))

        if file_type == 1:
            target_dir_id = file_id
            select_file_id = None
        else:
            target_dir_id = parent_id
            select_file_id = file_id

        class JumpSignals(QObject):
            finished = Signal(object, int, object, str)

        class JumpTask(QRunnable):
            def __init__(self, pan, file_id, target_dir_id, select_file_id, signals):
                super().__init__()
                self.pan = pan
                self.file_id = file_id
                self.target_dir_id = target_dir_id
                self.select_file_id = select_file_id
                self.signals = signals

            def run(self):
                try:
                    details = self.pan.file_details([self.file_id])
                    detail_paths = details.get("paths", []) if details else []
                    self.signals.finished.emit(
                        detail_paths, self.target_dir_id, self.select_file_id, ""
                    )
                except Exception as e:
                    self.signals.finished.emit([], self.target_dir_id, None, str(e))

        self._jump_signals = JumpSignals()
        self._jump_signals.finished.connect(self.__onJumpFinished)
        task = JumpTask(self.pan, file_id, target_dir_id, select_file_id, self._jump_signals)
        QThreadPool.globalInstance().start(task)

    def __onJumpFinished(self, detail_paths, target_dir_id, select_file_id, error):
        if error:
            InfoBar.error(title="跳转失败", content=error, parent=self)
            return

        # 从 detail_paths 构建 path_stack（包含 fileId）
        self.path_stack = [(0, "根目录")]
        for p in detail_paths:
            fid = int(p.get("fileId", 0))
            fname = p.get("fileName", "")
            if fid != 0:
                self.path_stack.append((fid, fname))
        if self.path_stack[-1][0] != target_dir_id:
            for p in detail_paths:
                if int(p.get("fileId", 0)) == target_dir_id:
                    self.path_stack.append((target_dir_id, p.get("fileName", "")))
                    break

        self.current_dir_id = target_dir_id
        self.__updateBreadcrumb()

        # 加载目标目录内容，完成后选中文件
        self.fileTable.setRowCount(0)
        self._load_request_id += 1
        current_request_id = self._load_request_id
        task = self.LoadListTask(self.__fetchDirList, target_dir_id)

        # 持有 signals 引用防止 GC
        signals = task.signals
        self._pending_signals.append(signals)

        def _cleanup(*_, sig=signals):
            if sig in self._pending_signals:
                self._pending_signals.remove(sig)

        if select_file_id is not None:
            def on_loaded(file_items, err, rid=current_request_id):
                self.__onLoadListFinished(file_items, err, rid)
                if not err:
                    for row in range(self.fileTable.rowCount()):
                        name_item = self.fileTable.item(row, 0)
                        if name_item and int(name_item.data(Qt.ItemDataRole.UserRole)) == select_file_id:
                            self.fileTable.selectRow(row)
                            self.fileTable.scrollToItem(name_item)
                            break
            signals.finished.connect(on_loaded)
        else:
            signals.finished.connect(
                lambda items, err, rid=current_request_id: self.__onLoadListFinished(items, err, rid)
            )

        signals.finished.connect(_cleanup)
        QThreadPool.globalInstance().start(task)

        tree_item = self.__findTreeItemById(target_dir_id)
        if tree_item:
            self.folderTree.setCurrentItem(tree_item)

    def __updateStatusLabel(self):
        count = len(self.__getSelectedRows())
        total = self.fileTable.rowCount()
        if count:
            self.statusLabel.setText(f"已选中 {count} 个，共 {total} 个")
        else:
            self.statusLabel.setText(f"共 {total} 个")

    def __deleteFile(self, file_id=None, file_name=None):
        """删除文件（支持多选 + 确认弹窗）"""
        # 收集待删除文件列表: [(file_id, file_name), ...]
        delete_list = []
        if file_id is not None and file_name is not None:
            delete_list.append((file_id, file_name))
        else:
            rows = self.__getSelectedRows()
            if not rows:
                InfoBar.warning(
                    title="删除错误", content="请选择要删除的文件", parent=self
                )
                return
            for row in rows:
                name_item = self.fileTable.item(row, 0)
                delete_list.append((
                    name_item.data(Qt.ItemDataRole.UserRole),
                    name_item.text(),
                ))

        # 确认弹窗
        if len(delete_list) == 1:
            content = f'确定要删除 "{delete_list[0][1]}" 吗？'
        else:
            names = [n for _, n in delete_list[:5]]
            lines = "\n".join(names)
            if len(delete_list) > 5:
                lines += f"\n...等共 {len(delete_list)} 个文件"
            else:
                lines += f"\n\n共 {len(delete_list)} 个文件"
            content = lines

        msg = MessageBox("确认删除", content, self)
        if not msg.exec():
            return

        # 创建批量删除任务
        class DeleteFilesSignals(QObject):
            finished = Signal(int, int, str, list, list)

        class DeleteFilesTask(QRunnable):
            def __init__(self, pan, delete_list, current_dir_id, signals):
                super().__init__()
                self.pan = pan
                self.delete_list = delete_list
                self.current_dir_id = current_dir_id
                self.signals = signals

            def run(self):
                try:
                    code, items = self.pan.get_dir_by_id(
                        self.current_dir_id, save=False, all=True, limit=1000,
                    )
                    if code != 0:
                        self.signals.finished.emit(0, len(self.delete_list), "获取目录失败", [], [])
                        return

                    item_map = {str(i.get("FileId")): i for i in items}
                    ok_count = 0
                    for fid, _ in self.delete_list:
                        detail = item_map.get(str(fid))
                        if detail:
                            self.pan.delete_file(detail, by_num=False, operation=True)
                            ok_count += 1

                    code, items = self.pan.get_dir_by_id(
                        self.current_dir_id, save=False, all=True, limit=100,
                    )
                    if code == 0:
                        folder_items = [
                            {"FileId": i.get("FileId"), "FileName": i.get("FileName")}
                            for i in items if int(i.get("Type", 0)) == 1
                        ]
                        self.signals.finished.emit(
                            ok_count, len(self.delete_list), "", items, folder_items,
                        )
                    else:
                        self.signals.finished.emit(ok_count, len(self.delete_list), "", [], [])
                except Exception as e:
                    self.signals.finished.emit(0, len(self.delete_list), str(e), [], [])

        signals = DeleteFilesSignals()
        signals.finished.connect(self.__onDeleteFilesFinished)
        task = DeleteFilesTask(
            self.pan, delete_list, self.current_dir_id, signals
        )
        self._pending_signals.append(signals)
        signals.finished.connect(lambda *_, sig=signals: (
            self._pending_signals.remove(sig) if sig in self._pending_signals else None
        ))
        QThreadPool.globalInstance().start(task)

    def __onDeleteFilesFinished(
        self, ok_count, total, error, file_items, folder_items
    ):
        """批量删除完成回调"""
        if error:
            InfoBar.error(
                title="删除失败", content=f"删除时发生错误: {error}", parent=self,
            )
            return

        if ok_count > 0:
            InfoBar.success(
                title="删除成功",
                content=f"已成功删除 {ok_count} 个文件",
                parent=self,
            )

        if file_items:
            self.__updateFileListUI(file_items)
            self.__updateTreeUI(folder_items)
            current_item = self.__findTreeItemById(self.current_dir_id)
            if current_item:
                self.folderTree.setCurrentItem(current_item)
        elif ok_count > 0:
            self.__refreshFileList()

    def __renameFile(self):
        """重命名文件"""

        # 获取选中的文件
        selected_items = self.fileTable.selectedItems()
        if not selected_items:
            InfoBar.warning(
                title="重命名错误", content="请选择要重命名的文件", parent=self
            )
            return

        # 获取选中行的文件信息
        row = selected_items[0].row()
        name_item = self.fileTable.item(row, 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        old_name = name_item.text()
        file_type = name_item.data(Qt.ItemDataRole.UserRole + 1)

        # 使用重命名对话框获取新名称
        dialog = RenameDialog(old_name, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        new_name = dialog.get_new_name()

        # 检查新名称是否为空
        if not new_name:
            InfoBar.warning(title="重命名错误", content="名称不能为空", parent=self)
            return

        # 检查新名称是否与旧名称相同
        if new_name == old_name:
            InfoBar.warning(
                title="重命名错误", content="新名称与旧名称相同", parent=self
            )
            return

        # 检查新名称是否包含无效字符
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in new_name for char in invalid_chars):
            InfoBar.warning(
                title="重命名错误",
                content=f"名称不能包含以下字符: {' '.join(invalid_chars)}",
                parent=self,
            )
            return

        # 创建任务执行重命名操作
        class RenameFileSignals(QObject):
            finished = Signal(
                bool, str, str, str, list, list
            )  # success, old_name, new_name, error, file_items, folder_items

        class RenameFileTask(QRunnable):
            def __init__(
                self, pan, file_id, old_name, new_name, current_dir_id, signals
            ):
                super().__init__()
                self.pan = pan
                self.file_id = file_id
                self.old_name = old_name
                self.new_name = new_name
                self.current_dir_id = current_dir_id
                self.signals = signals

            def run(self):
                try:
                    success = self.pan.rename_file(self.file_id, self.new_name)
                    if success:
                        code, items = self.pan.get_dir_by_id(
                            self.current_dir_id,
                            save=False,
                            all=True,
                            limit=100,
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
                        self.signals.finished.emit(
                            True,
                            self.old_name,
                            self.new_name,
                            "",
                            items,
                            folder_items,
                        )
                        return
                    self.signals.finished.emit(
                        False,
                        self.old_name,
                        self.new_name,
                        "重命名失败",
                        [],
                        [],
                    )
                except Exception as e:
                    self.signals.finished.emit(
                        False, self.old_name, self.new_name, str(e), [], []
                    )

        # 创建信号和任务
        signals = RenameFileSignals()
        signals.finished.connect(self.__onRenameFileFinished)
        task = RenameFileTask(
            self.pan, file_id, old_name, new_name, self.current_dir_id, signals
        )

        # 持有 signals 引用防止 GC
        self._pending_signals.append(signals)
        signals.finished.connect(lambda *_, sig=signals: (
            self._pending_signals.remove(sig) if sig in self._pending_signals else None
        ))

        # 提交任务到线程池
        QThreadPool.globalInstance().start(task)

    def __onRenameFileFinished(
        self, success, old_name, new_name, error, file_items, folder_items
    ):
        """重命名文件完成后的回调 - 只负责UI更新"""

        if success:
            # 显示成功信息
            InfoBar.success(
                title="重命名成功",
                content=f"文件 '{old_name}' 已成功重命名为 '{new_name}'",
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
                    title="重命名失败",
                    content=f"重命名文件时发生错误: {error}",
                    parent=self,
                )
            else:
                # 显示错误信息
                InfoBar.error(title="重命名失败", content="重命名失败", parent=self)

    def __moveFile(self):
        """移动文件到目标文件夹"""
        rows = self.__getSelectedRows()
        if not rows:
            InfoBar.warning(title="移动错误", content="请选择要移动的文件", parent=self)
            return

        # 收集待移动文件信息
        move_list = []
        for row in rows:
            name_item = self.fileTable.item(row, 0)
            move_list.append((
                name_item.data(Qt.ItemDataRole.UserRole),
                name_item.text(),
            ))

        # 弹出目标文件夹选择弹窗
        dialog = MoveDialog(self.pan, self.current_dir_id, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        target_id, target_name = dialog.get_target()
        if target_id is None:
            return

        # 不允许移动到当前目录
        if target_id == self.current_dir_id:
            InfoBar.warning(title="移动错误", content="目标文件夹与当前文件夹相同", parent=self)
            return

        # 后台执行移动
        file_id_list = [fid for fid, _ in move_list]

        class MoveFilesSignals(QObject):
            finished = Signal(bool, int, str, str)

        class MoveFilesTask(QRunnable):
            def __init__(self, pan, file_id_list, target_id, target_name, signals):
                super().__init__()
                self.pan = pan
                self.file_id_list = file_id_list
                self.target_id = target_id
                self.target_name = target_name
                self.signals = signals

            def run(self):
                try:
                    success = self.pan.move_file(self.file_id_list, self.target_id)
                    self.signals.finished.emit(
                        success, len(self.file_id_list), self.target_name, ""
                    )
                except Exception as e:
                    self.signals.finished.emit(False, 0, self.target_name, str(e))

        signals = MoveFilesSignals()
        signals.finished.connect(self.__onMoveFilesFinished)
        task = MoveFilesTask(self.pan, file_id_list, target_id, target_name, signals)
        self._pending_signals.append(signals)
        signals.finished.connect(lambda *_, sig=signals: (
            self._pending_signals.remove(sig) if sig in self._pending_signals else None
        ))
        QThreadPool.globalInstance().start(task)

    def __onMoveFilesFinished(self, success, count, target_name, error):
        """移动文件完成回调"""
        if error:
            InfoBar.error(
                title="移动失败", content=f"移动文件时发生错误: {error}", parent=self
            )
            return
        if success:
            InfoBar.success(
                title="移动成功",
                content=f"已将 {count} 个文件移动到「{target_name}」",
                parent=self,
            )
            self.__refreshFileList()
        else:
            InfoBar.error(title="移动失败", content="移动文件失败", parent=self)

    def __showFileDetails(self):
        """显示文件/文件夹详情"""
        rows = self.__getSelectedRows()
        if not rows:
            return

        name_item = self.fileTable.item(rows[0], 0)
        file_id = name_item.data(Qt.ItemDataRole.UserRole)
        file_name = name_item.text()

        class FileDetailsSignals(QObject):
            finished = Signal(str, object, str)

        class FileDetailsTask(QRunnable):
            def __init__(self, pan, file_id, file_name, signals):
                super().__init__()
                self.pan = pan
                self.file_id = file_id
                self.file_name = file_name
                self.signals = signals

            def run(self):
                try:
                    data = self.pan.file_details([self.file_id])
                    self.signals.finished.emit(self.file_name, data, "")
                except Exception as e:
                    self.signals.finished.emit(self.file_name, None, str(e))

        signals = FileDetailsSignals()
        signals.finished.connect(self.__onFileDetailsFinished)
        task = FileDetailsTask(self.pan, file_id, file_name, signals)
        self._pending_signals.append(signals)
        signals.finished.connect(lambda *_, sig=signals: (
            self._pending_signals.remove(sig) if sig in self._pending_signals else None
        ))
        QThreadPool.globalInstance().start(task)

    def __onFileDetailsFinished(self, file_name, data, error):
        """文件详情回调"""
        if error or data is None:
            InfoBar.error(
                title="获取详情失败",
                content=error or "未知错误",
                parent=self,
            )
            return

        file_num = data.get("fileNum", 0)
        dir_num = data.get("dirNum", 0)
        total_size = int(data.get("totalSize", 0))
        paths = data.get("paths", [])

        path_str = " / ".join(p.get("fileName", "") for p in paths)
        lines = [f"路径：{path_str}"]
        if dir_num > 0:
            lines.append(f"文件夹数：{dir_num}")
        if file_num > 0:
            lines.append(f"文件数：{file_num}")
        lines.append(f"总大小：{format_file_size(total_size)}")

        msg = MessageBox(f"「{file_name}」详情", "\n".join(lines), self)
        msg.cancelButton.hide()
        msg.exec()

    def __onFileTableContextMenu(self, position):
        """文件表格右键菜单"""
        # 获取鼠标点击位置的行
        index = self.fileTable.indexAt(position)
        if not index.isValid():
            return

        # 如果右键行不在已选范围内，切换为只选该行；否则保持多选
        clicked_row = index.row()
        selected_rows = self.__getSelectedRows()
        if clicked_row not in selected_rows:
            self.fileTable.selectRow(clicked_row)
            selected_rows = [clicked_row]

        menu = QMenu(self)

        # 下载
        download_action = QAction(FIF.DOWNLOAD.icon(), "下载", self)
        download_action.triggered.connect(self.__downloadFile)
        menu.addAction(download_action)

        # 重命名（仅单选时显示）
        if len(selected_rows) == 1:
            rename_action = QAction(FIF.EDIT.icon(), "重命名", self)
            rename_action.triggered.connect(self.__renameFile)
            menu.addAction(rename_action)

        # 移动到
        move_action = QAction(FIF.MOVE.icon(), "移动到", self)
        move_action.triggered.connect(self.__moveFile)
        menu.addAction(move_action)

        # 删除
        delete_action = QAction(FIF.DELETE.icon(), "删除", self)
        delete_action.triggered.connect(self.__deleteFile)
        menu.addAction(delete_action)

        menu.addSeparator()

        # 详情（仅单选时显示）
        if len(selected_rows) == 1:
            detail_action = QAction(FIF.INFO.icon(), "详情", self)
            detail_action.triggered.connect(self.__showFileDetails)
            menu.addAction(detail_action)

        menu.exec(self.fileTable.mapToGlobal(position))

    def update_storage_info(self, info):
        """更新云盘存储信息

        Args:
            info: (used_bytes, total_bytes) 元组
        """
        used_bytes, total_bytes = info
        used_text = format_file_size(used_bytes)
        total_text = format_file_size(total_bytes)

        usage_percent = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0

        self.storageProgressBar.setValue(int(usage_percent))
        self.storageValueLabel.setText(f"{used_text} / {total_text}")

    class StorageTask(QRunnable):
        class StorageSignals(QObject):
            finished = Signal(object)

        def __init__(self, pan):
            super().__init__()
            self.pan = pan
            self.signals = self.StorageSignals()

        def run(self):
            try:
                data = self.pan.user_info()
                if data:
                    used = int(data.get("SpaceUsed", 0))
                    total = int(data.get("SpacePermanent", 0))
                    self.signals.finished.emit((used, total))
                else:
                    self.signals.finished.emit((0, 0))
            except Exception as e:
                logger.error(f"获取存储信息失败: {e}")
                self.signals.finished.emit((0, 0))

    def load_and_update_storage_info(self):
        """通过 user_info API 获取并更新云盘存储信息"""
        if not self.pan:
            return

        task = self.StorageTask(self.pan)
        signals = task.signals
        self._pending_signals.append(signals)

        def _on_finished(info, sig=signals):
            self.update_storage_info(info)
            if sig in self._pending_signals:
                self._pending_signals.remove(sig)

        signals.finished.connect(_on_finished)
        QThreadPool.globalInstance().start(task)
