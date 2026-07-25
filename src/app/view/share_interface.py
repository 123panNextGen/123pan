"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QTableWidgetItem,
)

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    TableWidget,
    PushButton,
    InfoBar,
    MessageBox,
)

from ..common.style_sheet import StyleSheet
from ..common.log import get_logger
from ..common.i18n import tr

logger = get_logger(__name__)


class ShareInterface(QWidget):
    """分享链接管理页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("ShareInterface")

        self.pan = None
        self._free_shares = []
        self._pay_shares = []

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(24, 20, 24, 24)
        self.mainLayout.setSpacing(12)

        self.__createTopBar()
        self.__createTabWidget()
        self.__initWidget()

    def set_pan(self, pan):
        """设置 Pan123 实例"""
        self.pan = pan

    def __createTopBar(self):
        self.topBarFrame = QFrame(self)
        self.topBarFrame.setObjectName("frame")
        self.topBarLayout = QHBoxLayout(self.topBarFrame)
        self.topBarLayout.setContentsMargins(12, 10, 12, 10)
        self.topBarLayout.setSpacing(8)

        self.refreshButton = PushButton(
            FIF.UPDATE.icon(), tr("share.refresh", "刷新"), self.topBarFrame
        )
        self.copyLinkButton = PushButton(
            FIF.LINK.icon(), tr("share.copy_link", "复制链接"), self.topBarFrame
        )
        self.copyPwdButton = PushButton(
            FIF.FONT.icon(), tr("share.copy_pwd", "复制密码"), self.topBarFrame
        )
        self.deleteShareButton = PushButton(
            FIF.DELETE.icon(), tr("share.delete", "删除分享"), self.topBarFrame
        )

        self.topBarLayout.addWidget(self.refreshButton, 0)
        self.topBarLayout.addWidget(self.copyLinkButton, 0)
        self.topBarLayout.addWidget(self.copyPwdButton, 0)
        self.topBarLayout.addWidget(self.deleteShareButton, 0)
        self.topBarLayout.addStretch(1)

        self.mainLayout.addWidget(self.topBarFrame, 0)

    def __createTabWidget(self):
        self.tabWidget = QTabWidget(self)

        # 免费分享标签页
        self.freeTab = self.__createShareTab()
        self.tabWidget.addTab(self.freeTab, tr("share.tab_free", "免费分享"))

        # 付费分享标签页
        self.payTab = self.__createShareTab()
        self.tabWidget.addTab(self.payTab, tr("share.tab_pay", "付费分享"))

        self.mainLayout.addWidget(self.tabWidget, 1)

    def __createShareTab(self):
        """创建分享列表标签页框架"""
        frame = QFrame(self)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)

        table = TableWidget(frame)
        table.setAlternatingRowColors(True)
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            tr("share.col_name", "分享名称"),
            tr("share.col_pwd", "密码"),
            tr("share.col_downloads", "下载"),
            tr("share.col_previews", "预览"),
            tr("share.col_saves", "保存"),
            tr("share.col_expiration", "有效期"),
            tr("share.col_status", "状态"),
            tr("share.col_create_time", "创建时间"),
        ])
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        vertical_header = table.verticalHeader()
        if vertical_header is not None:
            vertical_header.hide()
        table.setBorderRadius(8)
        table.setBorderVisible(True)
        header = table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(table)
        return frame

    def __initWidget(self):
        StyleSheet.VIEW_INTERFACE.apply(self)
        self.__connectSignalToSlot()

    def showEvent(self, event):
        """页面显示时自动刷新分享列表"""
        super().showEvent(event)
        if self.pan:
            self.__refreshAll()

    def __connectSignalToSlot(self):
        self.refreshButton.clicked.connect(self.__refreshAll)
        self.copyLinkButton.clicked.connect(self.__copySelectedLink)
        self.copyPwdButton.clicked.connect(self.__copySelectedPwd)
        self.deleteShareButton.clicked.connect(self.__deleteSelectedShare)

    def __getCurrentTabIndex(self):
        return self.tabWidget.currentIndex()

    def __getCurrentTable(self):
        """获取当前标签页的表格"""
        if self.__getCurrentTabIndex() == 0:
            return self.freeTab.findChild(TableWidget)
        return self.payTab.findChild(TableWidget)

    def __getCurrentShares(self):
        """获取当前标签页的分享数据"""
        if self.__getCurrentTabIndex() == 0:
            return self._free_shares
        return self._pay_shares

    def __refreshAll(self):
        """刷新所有分享列表"""
        self.__refreshFreeShares()
        self.__refreshPayShares()

    def __refreshFreeShares(self):
        """刷新免费分享列表"""
        if not self.pan:
            logger.warning("免费分享刷新: pan 未设置")
            return
        try:
            result = self.pan.get_free_share_list()
            if result.code != 0:
                InfoBar.error(
                    title=tr("share.msg_refresh_failed", "刷新失败"),
                    content=tr("share.msg_get_list_error", "获取分享列表失败: {}").format(result.msg),
                    parent=self,
                )
                return
            share_data = result.data
            self._free_shares = share_data.data.info_list
            self.__updateTableUI(self.freeTab.findChild(TableWidget), self._free_shares)
            logger.info("免费分享列表已刷新: %d 条", len(self._free_shares))
        except Exception as e:
            logger.error("免费分享刷新失败: %s", e)
            InfoBar.error(
                title=tr("share.msg_refresh_failed", "刷新失败"),
                content=tr("share.msg_get_list_error", "获取分享列表失败: {}").format(e),
                parent=self,
            )

    def __refreshPayShares(self):
        """刷新付费分享列表"""
        if not self.pan:
            logger.warning("付费分享刷新: pan 未设置")
            return
        try:
            result = self.pan.get_pay_share_list()
            if result.code != 0:
                InfoBar.error(
                    title=tr("share.msg_refresh_failed", "刷新失败"),
                    content=tr("share.msg_get_list_error", "获取分享列表失败: {}").format(result.msg),
                    parent=self,
                )
                return
            share_data = result.data
            self._pay_shares = share_data.data.info_list
            self.__updateTableUI(self.payTab.findChild(TableWidget), self._pay_shares)
            logger.info("付费分享列表已刷新: %d 条", len(self._pay_shares))
        except Exception as e:
            logger.error("付费分享刷新失败: %s", e)
            InfoBar.error(
                title=tr("share.msg_refresh_failed", "刷新失败"),
                content=tr("share.msg_get_list_error", "获取分享列表失败: {}").format(e),
                parent=self,
            )

    def __updateTableUI(self, table, share_list):
        """更新分享表格"""
        table.setRowCount(len(share_list))
        for row, item in enumerate(share_list):
            share_name = item.share_name
            share_pwd = item.share_pwd or tr("share.no_pwd", "无")
            download_count = str(item.download_count)
            preview_count = str(item.preview_count)
            save_count = str(item.save_count)
            expiration = self.__formatExpiration(item)
            status_text = self.__formatStatus(item)
            create_time = self.__formatTime(item.create_at)

            name_cell = QTableWidgetItem(share_name)
            pwd_cell = QTableWidgetItem(share_pwd)
            dl_cell = QTableWidgetItem(download_count)
            dl_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            pv_cell = QTableWidgetItem(preview_count)
            pv_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            sv_cell = QTableWidgetItem(save_count)
            sv_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            exp_cell = QTableWidgetItem(expiration)
            status_cell = QTableWidgetItem(status_text)
            time_cell = QTableWidgetItem(create_time)

            table.setItem(row, 0, name_cell)
            table.setItem(row, 1, pwd_cell)
            table.setItem(row, 2, dl_cell)
            table.setItem(row, 3, pv_cell)
            table.setItem(row, 4, sv_cell)
            table.setItem(row, 5, exp_cell)
            table.setItem(row, 6, status_cell)
            table.setItem(row, 7, time_cell)

    def __formatExpiration(self, item):
        """格式化有效期"""
        if item.expired:
            return tr("share.expired", "已过期")
        if not item.expiration:
            return tr("share.forever", "永久")
        # 尝试提取日期部分
        exp_str = str(item.expiration)
        if "T" in exp_str:
            return exp_str.split("T")[0]
        return exp_str

    def __formatStatus(self, item):
        """格式化分享状态"""
        # auditStatus: 0=正常, 其他=审核中/违规
        if item.audit_status != 0:
            return tr("share.status_auditing", "审核中")
        if item.status != 0:
            return tr("share.status_disabled", "已禁用")
        if item.expired:
            return tr("share.expired", "已过期")
        if item.is_pay_share:
            return tr("share.status_pay", "付费")
        return tr("share.status_normal", "正常")

    def __formatTime(self, time_str):
        """格式化时间字符串，提取日期部分"""
        if not time_str:
            return ""
        if "T" in time_str:
            return time_str.split("T")[0]
        return time_str

    def __getSelectedShares(self):
        """获取当前标签页选中的分享条目"""
        table = self.__getCurrentTable()
        shares = self.__getCurrentShares()

        selected_rows = set()
        for table_item in table.selectedItems():
            selected_rows.add(table_item.row())

        result = []
        for row in sorted(selected_rows):
            if 0 <= row < len(shares):
                result.append(shares[row])
        return result

    def __copySelectedLink(self):
        """复制选中分享的链接"""
        selected = self.__getSelectedShares()
        if not selected:
            InfoBar.warning(
                title=tr("share.msg_copy_link", "复制链接"),
                content=tr("share.msg_select_share", "请选择要复制链接的分享"),
                parent=self,
            )
            return

        links = []
        for item in selected:
            if item.share_link:
                links.append(item.share_link)
            elif item.share_url:
                links.append(item.share_url)

        if not links:
            InfoBar.warning(
                title=tr("share.msg_copy_link", "复制链接"),
                content=tr("share.msg_no_link", "所选分享没有可用链接"),
                parent=self,
            )
            return

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(links))

        InfoBar.success(
            title=tr("share.msg_copy_success", "复制成功"),
            content=tr("share.msg_link_copied", "已复制 {} 个分享链接到剪贴板").format(len(links)),
            parent=self,
        )

    def __copySelectedPwd(self):
        """复制选中分享的密码"""
        selected = self.__getSelectedShares()
        if not selected:
            InfoBar.warning(
                title=tr("share.msg_copy_pwd", "复制密码"),
                content=tr("share.msg_select_share", "请选择要复制密码的分享"),
                parent=self,
            )
            return

        pwds = []
        for item in selected:
            if item.share_pwd:
                pwds.append(item.share_pwd)

        if not pwds:
            InfoBar.warning(
                title=tr("share.msg_copy_pwd", "复制密码"),
                content=tr("share.msg_no_pwd_selected", "所选分享没有设置密码"),
                parent=self,
            )
            return

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(pwds))

        InfoBar.success(
            title=tr("share.msg_copy_success", "复制成功"),
            content=tr("share.msg_pwd_copied", "已复制 {} 个分享密码到剪贴板").format(len(pwds)),
            parent=self,
        )

    def __deleteSelectedShare(self):
        """删除选中的分享链接"""
        if not self.pan:
            logger.warning("删除分享: pan 未设置")
            return

        selected = self.__getSelectedShares()
        if not selected:
            InfoBar.warning(
                title=tr("share.msg_delete_share", "删除分享"),
                content=tr("share.msg_select_delete", "请选择要删除的分享"),
                parent=self,
            )
            return

        # 确认对话框
        count = len(selected)
        title = tr("share.msg_delete_share", "删除分享")
        content = tr("share.msg_confirm_delete", "确定删除选中的 {} 个分享链接吗？此操作不可撤销。").format(count)
        box = MessageBox(title, content, self)
        if not box.exec():
            return

        success_count = 0
        fail_count = 0
        last_error = ""

        for item in selected:
            share_id = item.share_id
            share_name = item.share_name
            logger.info("正在删除分享: name=%s, shareId=%s", share_name, share_id)
            try:
                result = self.pan.delete_share(share_id)
                if result.code == 0:
                    success_count += 1
                    logger.info("分享删除成功: %s (shareId=%s)", share_name, share_id)
                else:
                    fail_count += 1
                    last_error = result.msg
                    logger.warning("分享删除失败: %s (shareId=%s), msg=%s", share_name, share_id, result.msg)
            except Exception as e:
                fail_count += 1
                last_error = str(e)
                logger.error("分享删除异常: %s (shareId=%s): %s", share_name, share_id, e)

        # 显示结果
        if fail_count == 0:
            InfoBar.success(
                title=tr("share.msg_delete_success", "删除成功"),
                content=tr("share.msg_delete_count", "成功删除 {} 个分享链接").format(success_count),
                parent=self,
            )
        else:
            InfoBar.warning(
                title=tr("share.msg_delete_partial", "部分删除失败"),
                content=tr("share.msg_delete_result", "成功 {} 个，失败 {} 个: {}").format(
                    success_count, fail_count, last_error
                ),
                parent=self,
            )

        # 刷新列表
        self.__refreshAll()
