"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QTableWidgetItem, QWidget

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import ProgressBar, PushButton

from ..common.i18n import tr
from ..common.utils import format_file_size, format_speed


class TransferTableMixin:
    """传输表格渲染（上传/下载共用，增量刷新）。"""

    def _update_table(self, table, tasks, task_type):
        """更新传输表格（上传/下载共用）。

        只在行数变化时增删行；逐行调用 _update_row，
        未变化的行完全跳过，避免高频进度信号下重复 setText/setValue。
        """
        if table.rowCount() != len(tasks):
            table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            self._update_row(table, task, row, task_type)

    def _update_row(self, table, task, row, task_type):
        """更新表格中单行任务的状态展示。

        渲染状态 = (状态, 进度, 速度, 大小, 名称)，任一变化才更新该行。
        """
        status_item = table.item(row, 6)
        last_state = (
            status_item.data(Qt.ItemDataRole.UserRole) if status_item else None
        )
        state = (
            task.status, task.progress, task.speed,
            task.file_size, task.file_name,
        )

        if state == last_state:
            return

        # ---- 文件名 ----
        name_item = table.item(row, 0)
        if not name_item:
            name_item = QTableWidgetItem(task.file_name)
            table.setItem(row, 0, name_item)
        else:
            name_item.setText(task.file_name)

        # ---- 优先级下拉 ----
        priority_combo = table.cellWidget(row, 1)
        if not priority_combo:
            priority_combo = QComboBox()
            priority_combo.addItems(
                [
                    tr("transfer.priority_low", "低"),
                    tr("transfer.priority_normal", "普通"),
                    tr("transfer.priority_high", "高"),
                ]
            )
            priority_combo.setFixedWidth(72)
            priority_combo.setToolTip(
                tr("transfer.priority_tip", "设置任务优先级（高优先级先执行）")
            )
            priority_combo.currentIndexChanged.connect(
                lambda idx, t=task, tt=task_type: self._change_priority(
                    t, tt, idx
                )
            )
            table.setCellWidget(row, 1, priority_combo)
        priority_combo.blockSignals(True)
        priority_combo.setCurrentIndex(task.priority)
        priority_combo.blockSignals(False)

        # ---- 文件大小 ----
        size_item = table.item(row, 2)
        if not size_item:
            size_item = QTableWidgetItem(format_file_size(task.file_size))
            table.setItem(row, 2, size_item)
        else:
            size_item.setText(format_file_size(task.file_size))

        # ---- 实时速度 ----
        speed_item = table.item(row, 3)
        speed_text = format_speed(task.speed)
        if not speed_item:
            speed_item = QTableWidgetItem(speed_text)
            speed_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 3, speed_item)
        else:
            speed_item.setText(speed_text)

        # ---- 进度条 ----
        progress_bar = table.cellWidget(row, 4)
        if not progress_bar:
            progress_bar = ProgressBar()
            progress_bar.setTextVisible(False)
            table.setCellWidget(row, 4, progress_bar)
        progress_bar.setValue(task.progress)

        # ---- 百分比 ----
        percent_item = table.item(row, 5)
        if not percent_item:
            percent_item = QTableWidgetItem(f"{task.progress}%")
            percent_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 5, percent_item)
        else:
            percent_item.setText(f"{task.progress}%")

        # ---- 状态 ----
        if not status_item:
            status_item = QTableWidgetItem(task.status)
            table.setItem(row, 6, status_item)
        else:
            status_item.setText(task.status)

        # ---- 操作按钮（状态变化时重建，按钮集合随状态变化） ----
        old_action = table.cellWidget(row, 7)
        prev_status = last_state[0] if last_state else None
        status_item.setData(Qt.ItemDataRole.UserRole, state)

        if old_action is None or prev_status != task.status:
            if old_action is not None:
                table.removeCellWidget(row, 7)
                old_action.deleteLater()

            action_layout = QHBoxLayout()
            action_layout.setContentsMargins(0, 0, 0, 0)

            # 暂停/恢复按钮
            if task.status in (
                tr("transfer.status_uploading", "上传中"),
                tr("transfer.status_downloading", "下载中"),
            ):
                pause_btn = PushButton(
                    FIF.PAUSE.icon(), tr("transfer.btn_pause", "暂停"), table
                )
                pause_btn.setFixedSize(64, 24)
                pause_btn.clicked.connect(
                    lambda _, t=task, tt=task_type: self._pause_task(t, tt)
                )
                action_layout.addWidget(pause_btn)
            elif task.status == tr("transfer.status_paused", "已暂停"):
                resume_btn = PushButton(
                    FIF.PLAY.icon(), tr("transfer.btn_resume", "继续"), table
                )
                resume_btn.setFixedSize(64, 24)
                resume_btn.clicked.connect(
                    lambda _, t=task, tt=task_type: self._resume_task(t, tt)
                )
                action_layout.addWidget(resume_btn)
            elif task.status == tr("transfer.status_failed", "失败"):
                # 失败任务支持重试（上传/下载均走断点续传）
                retry_btn = PushButton(
                    FIF.SYNC.icon(), tr("transfer.btn_retry", "重试"), table
                )
                retry_btn.setFixedSize(64, 24)
                retry_btn.clicked.connect(
                    lambda _, t=task, tt=task_type: self._retry_task(t, tt)
                )
                action_layout.addWidget(retry_btn)

            delete_button = PushButton(
                FIF.DELETE.icon(), tr("transfer.btn_delete", "删除"), table
            )
            delete_button.setFixedSize(64, 24)
            delete_button.clicked.connect(
                lambda _, t=task, tt=task_type: self._remove_task(t, tt)
            )
            action_layout.addWidget(delete_button)
            action_widget = QWidget()
            action_widget.setLayout(action_layout)
            table.setCellWidget(row, 7, action_widget)
