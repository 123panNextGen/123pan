"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    InfoBar,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SegmentedWidget,
    TableWidget,
)

from ..common.i18n import tr
from ..common.log import get_logger
from ..common.utils import configure_resizable_header, format_file_size
from ..tasks.file_tasks import (
    OfflineResolveTask,
    OfflineSubmitTask,
    RapidTransferTask,
    connect_tracked,
)
from ..tasks.signals import (
    _OfflineResolveSignals,
    _OfflineSubmitSignals,
    _RapidTransferSignals,
)

logger = get_logger(__name__)

# 类型显示映射
_TYPE_TEXT = {
    "http": "HTTP",
    "https": "HTTPS",
    "ftp": "FTP",
    "magnet": "磁力链接",
    "thunder": "迅雷链接",
    "ed2k": "电驴链接",
    "bt": "BT",
}


class _FileSelectDialog(QDialog):
    """多文件资源（如种子）的文件选择对话框。"""

    def __init__(self, resource, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle(tr("offline.select_files", "选择文件"))
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel(
            tr("offline.select_files_hint", "选择要下载的文件："), self
        )
        layout.addWidget(title)

        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels([
            tr("offline.col_sel", "选择"),
            tr("file.col_name", "名称"),
        ])
        self.table.setBorderRadius(8)
        self.table.setBorderVisible(True)
        configure_resizable_header(
            self.table, stretch_column=1, default_widths={0: 60, 1: 400}
        )

        files = resource.get("files") or []
        self.table.setRowCount(len(files))
        for i, f in enumerate(files):
            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check_item.setCheckState(Qt.CheckState.Checked)
            check_item.setData(
                Qt.ItemDataRole.UserRole, int(f.get("id", 0) or 0)
            )
            self.table.setItem(i, 0, check_item)
            name_item = QTableWidgetItem(str(f.get("name", "")))
            name_item.setToolTip(str(f.get("name", "")))
            self.table.setItem(i, 1, name_item)

        layout.addWidget(self.table)

        self._file_count = len(files)
        self._all_checked = self._file_count > 0
        self.table.itemChanged.connect(self.__onItemChanged)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.selectAllButton = PushButton(
            FIF.CHECKBOX, tr("offline.select_all", "全选"), self
        )
        self.selectAllButton.clicked.connect(self.__toggle_all)
        btn_row.addWidget(self.selectAllButton)
        self.okButton = PrimaryPushButton(
            tr("offline.confirm", "确定"), self
        )
        self.okButton.clicked.connect(self.accept)
        btn_row.addWidget(self.okButton)
        layout.addLayout(btn_row)

    def __update_select_all_text(self):
        """根据当前勾选状态更新全选按钮文本。"""
        self._all_checked = self.__all_checked()
        self.selectAllButton.setText(
            tr("offline.deselect_all", "取消全选")
            if self._all_checked and self._file_count > 0
            else tr("offline.select_all", "全选")
        )

    def __all_checked(self):
        return all(
            self.table.item(i, 0) is not None
            and self.table.item(i, 0).checkState() == Qt.CheckState.Checked
            for i in range(self.table.rowCount())
        )

    def __onItemChanged(self, item):
        if item.column() != 0:
            return
        self.__update_select_all_text()

    def __toggle_all(self):
        state = (
            Qt.CheckState.Unchecked
            if self._all_checked and self._file_count > 0
            else Qt.CheckState.Checked
        )
        self.table.blockSignals(True)
        try:
            for i in range(self.table.rowCount()):
                it = self.table.item(i, 0)
                if it is not None:
                    it.setCheckState(state)
        finally:
            self.table.blockSignals(False)
        self._all_checked = state == Qt.CheckState.Checked
        self.selectAllButton.setText(
            tr("offline.deselect_all", "取消全选")
            if self._all_checked and self._file_count > 0
            else tr("offline.select_all", "全选")
        )

    def selected_file_ids(self):
        """返回勾选的文件 ID 列表。"""
        ids = []
        for i in range(self.table.rowCount()):
            it = self.table.item(i, 0)
            if it is not None and it.checkState() == Qt.CheckState.Checked:
                fid = it.data(Qt.ItemDataRole.UserRole)
                if fid is not None:
                    ids.append(fid)
        return ids


class OfflineDownloadDialog(QDialog):
    """离线下载 / 秒传导入对话框。

    离线下载：粘贴 URL（http/https/magnet/thunder 等）→ 解析 → 选择文件 → 提交，
    由 123 云盘服务器后台下载。
    秒传导入：粘贴 123FastLink / 秒传 JSON 生成器（夸克/天翼等）导出的秒传数据，
    通过 etag 秒传到 123 云盘。
    """

    def __init__(self, pan, current_dir_id, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle(tr("offline.title", "离线下载"))
        self.resize(760, 620)
        self.pan = pan
        self.current_dir_id = int(current_dir_id)
        # 持有后台任务引用，防止任务/信号被 GC 回收
        self._pending_tasks = []

        self._resources = []  # 解析后的离线下载资源列表
        self._rapid_files = []  # 秒传解析后的文件列表

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(20, 16, 20, 16)
        self.mainLayout.setSpacing(12)

        self.segmentedWidget = SegmentedWidget(self)
        self.segmentedWidget.addItem(
            routeKey="offline", icon=FIF.CLOUD_DOWNLOAD.icon(),
            text=tr("offline.tab_url", "离线下载"),
        )
        self.segmentedWidget.addItem(
            routeKey="rapid", icon=FIF.HISTORY.icon(),
            text=tr("offline.tab_rapid", "秒传导入"),
        )
        self.segmentedWidget.setCurrentItem("offline")
        self.mainLayout.addWidget(self.segmentedWidget)

        self.offlinePage = self.__createOfflinePage()
        self.rapidPage = self.__createRapidPage()
        self.mainLayout.addWidget(self.offlinePage, 1)
        self.mainLayout.addWidget(self.rapidPage, 1)
        self.rapidPage.hide()

        self.segmentedWidget.currentItemChanged.connect(self.__onSegmentChanged)
        self.__connectOfflineSignals()
        self.__connectRapidSignals()

    # ---- 离线下载页 ----

    def __createOfflinePage(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            tr("offline.url_hint",
               "每行一个链接，支持 HTTP/HTTPS、磁力链接、迅雷链接等"),
            page,
        )
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        self.urlEdit = QTextEdit(page)
        self.urlEdit.setPlaceholderText(
            tr("offline.url_placeholder", "粘贴下载链接（每行一个）...")
        )
        self.urlEdit.setFixedHeight(110)
        layout.addWidget(self.urlEdit)

        row = QHBoxLayout()
        row.addStretch()
        self.resolveButton = PushButton(
            FIF.SEARCH.icon(), tr("offline.resolve", "解析链接"), page
        )
        self.resolveButton.clicked.connect(self.__resolveUrls)
        row.addWidget(self.resolveButton)
        layout.addLayout(row)

        self.resourceTable = TableWidget(page)
        self.resourceTable.setColumnCount(6)
        self.resourceTable.setHorizontalHeaderLabels([
            tr("offline.col_sel", "选择"),
            tr("file.col_name", "名称"),
            tr("transfer.col_size", "大小"),
            tr("offline.col_type", "类型"),
            tr("offline.col_files", "文件数"),
            tr("transfer.col_status", "状态"),
        ])
        self.resourceTable.setBorderRadius(8)
        self.resourceTable.setBorderVisible(True)
        self.resourceTable.setAlternatingRowColors(True)
        self.resourceTable.setSelectionBehavior(
            self.resourceTable.SelectionBehavior.SelectRows
        )
        # 所有列可交互调整列宽，名称列吸收多余宽度
        configure_resizable_header(
            self.resourceTable,
            stretch_column=1,
            default_widths={0: 60, 1: 280, 2: 100, 3: 90, 4: 70, 5: 140},
        )
        self.resourceTable.itemChanged.connect(self.__onResourceItemChanged)
        layout.addWidget(self.resourceTable, 1)

        self.offlineStatusLabel = QLabel("", page)
        self.offlineStatusLabel.setStyleSheet("color: gray;")
        layout.addWidget(self.offlineStatusLabel)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.submitButton = PrimaryPushButton(
            FIF.DOWNLOAD.icon(), tr("offline.submit", "提交下载"), page
        )
        self.submitButton.clicked.connect(self.__submitOffline)
        self.submitButton.setEnabled(False)
        bottom.addWidget(self.submitButton)
        layout.addLayout(bottom)

        return page

    # ---- 秒传导入页 ----

    def __createRapidPage(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            tr("offline.rapid_hint",
               "粘贴 123FastLink 或秒传 JSON 生成器导出的秒传数据（JSON 或链接），"
               "将文件秒传到当前目录"),
            page,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        self.rapidEdit = QTextEdit(page)
        self.rapidEdit.setPlaceholderText(
            tr("offline.rapid_placeholder", "粘贴秒传 JSON 或秒传链接...")
        )
        self.rapidEdit.setFixedHeight(140)
        layout.addWidget(self.rapidEdit)

        row = QHBoxLayout()
        row.addStretch()
        self.rapidResolveButton = PushButton(
            FIF.SEARCH.icon(), tr("offline.rapid_resolve", "解析"), page
        )
        self.rapidResolveButton.clicked.connect(self.__parseRapidData)
        row.addWidget(self.rapidResolveButton)
        layout.addLayout(row)

        self.rapidInfoLabel = QLabel("", page)
        self.rapidInfoLabel.setStyleSheet("color: gray;")
        self.rapidInfoLabel.setWordWrap(True)
        layout.addWidget(self.rapidInfoLabel)

        self.rapidProgressBar = ProgressBar(page)
        self.rapidProgressBar.setRange(0, 100)
        self.rapidProgressBar.setValue(0)
        layout.addWidget(self.rapidProgressBar)

        self.rapidStatusLabel = QLabel("", page)
        self.rapidStatusLabel.setStyleSheet("color: gray;")
        layout.addWidget(self.rapidStatusLabel)

        layout.addStretch()

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.rapidTransferButton = PrimaryPushButton(
            FIF.HISTORY.icon(), tr("offline.rapid_transfer", "开始导入"), page
        )
        self.rapidTransferButton.clicked.connect(self.__startRapidTransfer)
        self.rapidTransferButton.setEnabled(False)
        bottom.addWidget(self.rapidTransferButton)
        layout.addLayout(bottom)

        return page

    # ---- 信号连接 ----

    def __connectOfflineSignals(self):
        self.resolveButton.clicked.connect(self.__resolveUrls)
        self.submitButton.clicked.connect(self.__submitOffline)

    def __connectRapidSignals(self):
        self.rapidResolveButton.clicked.connect(self.__parseRapidData)
        self.rapidTransferButton.clicked.connect(self.__startRapidTransfer)

    def __onSegmentChanged(self, route_key):
        if route_key == "offline":
            self.offlinePage.show()
            self.rapidPage.hide()
        else:
            self.offlinePage.hide()
            self.rapidPage.show()

    # ---- 离线下载 ----

    def __resolveUrls(self):
        urls = self.urlEdit.toPlainText().strip()
        if not urls:
            InfoBar.warning(
                title=tr("offline.msg_input_error", "输入错误"),
                content=tr("offline.msg_url_empty", "请输入下载链接"),
                parent=self,
            )
            return

        self.resolveButton.setEnabled(False)
        self.offlineStatusLabel.setText(
            tr("offline.msg_resolving", "正在解析链接...")
        )
        self.resourceTable.setRowCount(0)

        signals = _OfflineResolveSignals()
        task = OfflineResolveTask(self.pan, urls, signals)
        connect_tracked(self, signals, "finished", self.__onResolveFinished, task)
        QThreadPool.globalInstance().start(task)

    def __onResolveFinished(self, resources, error):
        self.resolveButton.setEnabled(True)
        if error:
            self.offlineStatusLabel.setText("")
            InfoBar.error(
                title=tr("offline.msg_resolve_failed", "解析失败"),
                content=error,
                parent=self,
            )
            return
        self._resources = resources or []
        self.__renderResources()
        ok_count = sum(1 for r in self._resources if r.get("result", 1) == 0)
        self.offlineStatusLabel.setText(
            tr("offline.msg_resolved", "解析完成：成功 {} 个，失败 {} 个").format(
                ok_count, len(self._resources) - ok_count
            )
        )
        self.submitButton.setEnabled(ok_count > 0)

    def __renderResources(self):
        """渲染解析结果表格。"""
        table = self.resourceTable
        table.blockSignals(True)
        try:
            table.setRowCount(len(self._resources))
            for row, res in enumerate(self._resources):
                ok = res.get("result", 1) == 0

                check_item = QTableWidgetItem()
                if ok:
                    check_item.setFlags(
                        Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )
                    check_item.setCheckState(Qt.CheckState.Checked)
                else:
                    check_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    check_item.setCheckState(Qt.CheckState.Unchecked)
                check_item.setData(Qt.ItemDataRole.UserRole, row)
                table.setItem(row, 0, check_item)

                name_item = QTableWidgetItem(str(res.get("name", "") or ""))
                name_item.setToolTip(str(res.get("name", "") or ""))
                table.setItem(row, 1, name_item)

                size_item = QTableWidgetItem(
                    format_file_size(int(res.get("size", 0) or 0))
                )
                table.setItem(row, 2, size_item)

                type_item = QTableWidgetItem(
                    _TYPE_TEXT.get(str(res.get("type", "")), str(res.get("type", "")))
                )
                table.setItem(row, 3, type_item)

                files = res.get("files") or []
                files_item = QTableWidgetItem(
                    str(len(files)) if files else "1"
                )
                table.setItem(row, 4, files_item)

                if not ok:
                    err_msg = res.get("err_msg") or ""
                    status_item = QTableWidgetItem(
                        tr("offline.msg_resolve_err", "解析失败") + (
                            f": {err_msg}" if err_msg else ""
                        )
                    )
                else:
                    status_item = QTableWidgetItem(
                        tr("offline.msg_ok", "可下载")
                    )
                table.setItem(row, 5, status_item)
        finally:
            table.blockSignals(False)

    def __onResourceItemChanged(self, item):
        """资源行勾选状态变化时更新提交按钮状态。"""
        if item.column() != 0:
            return
        self.submitButton.setEnabled(self.__has_selected_resources())

    def __has_selected_resources(self):
        for i in range(self.resourceTable.rowCount()):
            it = self.resourceTable.item(i, 0)
            if it is not None and it.checkState() == Qt.CheckState.Checked:
                return True
        return False

    def __build_resources(self):
        """根据勾选与文件选择构造提交资源列表。"""
        resources = []
        for row, res in enumerate(self._resources):
            check_item = self.resourceTable.item(row, 0)
            if check_item is None or check_item.checkState() != Qt.CheckState.Checked:
                continue
            if res.get("result", 1) != 0:
                continue
            resource_id = int(res.get("id", 0) or 0)
            if not resource_id:
                continue
            files = res.get("files") or []
            if len(files) > 1:
                dlg = _FileSelectDialog(res, self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    continue
                select_ids = dlg.selected_file_ids()
                if not select_ids:
                    continue
                resources.append(
                    {"resource_id": resource_id, "select_file_id": select_ids}
                )
            else:
                # 单文件资源：select_file_id 留空表示全部
                resources.append(
                    {"resource_id": resource_id, "select_file_id": []}
                )
        return resources

    def __submitOffline(self):
        resources = self.__build_resources()
        if not resources:
            InfoBar.warning(
                title=tr("offline.msg_no_selection", "未选择资源"),
                content=tr("offline.msg_select_resources", "请勾选要下载的资源"),
                parent=self,
            )
            return

        self.submitButton.setEnabled(False)
        self.offlineStatusLabel.setText(
            tr("offline.msg_submitting", "正在提交下载任务...")
        )
        signals = _OfflineSubmitSignals()
        task = OfflineSubmitTask(self.pan, resources, signals)
        connect_tracked(self, signals, "finished", self.__onSubmitFinished, task)
        QThreadPool.globalInstance().start(task)

    def __onSubmitFinished(self, task_list, error):
        self.submitButton.setEnabled(True)
        if error:
            self.offlineStatusLabel.setText("")
            InfoBar.error(
                title=tr("offline.msg_submit_failed", "提交失败"),
                content=error,
                parent=self,
            )
            return
        ok_count = sum(1 for t in task_list if t.get("result", 1) == 0)
        self.offlineStatusLabel.setText("")
        if ok_count > 0:
            InfoBar.success(
                title=tr("offline.msg_submitted", "已提交"),
                content=tr("offline.msg_submitted_desc", "已提交 {} 个离线下载任务").format(ok_count),
                parent=self,
            )
        else:
            InfoBar.error(
                title=tr("offline.msg_submit_failed", "提交失败"),
                content=tr("offline.msg_submit_failed_desc", "离线下载任务提交失败"),
                parent=self,
            )

    # ---- 秒传导入 ----

    def __parseRapidData(self):
        text = self.rapidEdit.toPlainText().strip()
        if not text:
            InfoBar.warning(
                title=tr("offline.msg_input_error", "输入错误"),
                content=tr("offline.msg_rapid_empty", "请输入秒传数据"),
                parent=self,
            )
            return
        try:
            files = self.pan.offline_parse_rapid(text)
        except ValueError as e:
            InfoBar.error(
                title=tr("offline.msg_rapid_parse_failed", "解析失败"),
                content=str(e),
                parent=self,
            )
            return
        except Exception as e:
            logger.error("秒传数据解析异常: %s", e)
            InfoBar.error(
                title=tr("offline.msg_rapid_parse_failed", "解析失败"),
                content=str(e),
                parent=self,
            )
            return

        self._rapid_files = files
        total_size = sum(f.get("size", 0) for f in files)
        self.rapidInfoLabel.setText(
            tr("offline.msg_rapid_parsed", "解析到 {} 个文件，共 {}").format(
                len(files), format_file_size(total_size)
            )
        )
        self.rapidTransferButton.setEnabled(True)

    def __startRapidTransfer(self):
        if not self._rapid_files:
            return
        self.rapidTransferButton.setEnabled(False)
        self.rapidProgressBar.setValue(0)
        self.rapidStatusLabel.setText(
            tr("offline.msg_rapid_transferring", "正在秒传导入...")
        )
        signals = _RapidTransferSignals()
        task = RapidTransferTask(
            self.pan, self._rapid_files, self.current_dir_id, signals
        )
        signals.progress.connect(self.__onRapidProgress)
        connect_tracked(self, signals, "finished", self.__onRapidFinished, task)
        QThreadPool.globalInstance().start(task)

    def __onRapidProgress(self, current, total):
        if total > 0:
            self.rapidProgressBar.setValue(int(current * 100 / total))
            self.rapidStatusLabel.setText(
                tr("offline.msg_rapid_transferring", "正在秒传导入...") +
                f" {current}/{total}"
            )

    def __onRapidFinished(self, stats, error):
        self.rapidTransferButton.setEnabled(True)
        if error:
            self.rapidStatusLabel.setText("")
            InfoBar.error(
                title=tr("offline.msg_rapid_failed", "导入失败"),
                content=error,
                parent=self,
            )
            return
        success = stats.get("success") or []
        failed = stats.get("failed") or []
        self.rapidStatusLabel.setText("")
        if success:
            InfoBar.success(
                title=tr("offline.msg_rapid_done", "导入完成"),
                content=tr("offline.msg_rapid_done_desc", "成功 {} 个，失败 {} 个").format(
                    len(success), len(failed)
                ),
                parent=self,
            )
        elif failed:
            InfoBar.error(
                title=tr("offline.msg_rapid_failed", "导入失败"),
                content=tr("offline.msg_rapid_done_desc", "成功 {} 个，失败 {} 个").format(
                    len(success), len(failed)
                ),
                parent=self,
            )
        else:
            InfoBar.info(
                title=tr("offline.msg_rapid_done", "导入完成"),
                content=tr("offline.msg_rapid_done_desc", "成功 {} 个，失败 {} 个").format(
                    len(success), len(failed)
                ),
                parent=self,
            )
