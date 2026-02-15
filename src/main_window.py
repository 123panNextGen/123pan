# https://github.com/123panNextGen/123pan
# src/main_window.py

from PyQt6 import QtCore, QtGui, QtWidgets
import os
import json
import hashlib
import requests
import time
import concurrent.futures
import threading
from log import get_logger
from config import ConfigManager
from ui_widgets import SidebarButton, LoginDialog, SettingsDialog, AboutDialog
from api import Pan123
from threading_utils import ThreadedTask
from ui_theme_manager import ThemeManager

logger = get_logger(__name__)


class DropAreaTableWidget(QtWidgets.QTableWidget):
    """支持拖拽上传的表格控件"""
    files_dropped = QtCore.pyqtSignal(list)  # 信号：文件路径列表
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.is_drag_over = False
        # 设置 viewport 也接受拖拽
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)
    
    def eventFilter(self, obj, event):
        """事件过滤器，捕获 viewport 的拖拽事件"""
        if obj == self.viewport():
            if event.type() == QtCore.QEvent.Type.DragEnter:
                return self.dragEnterEvent(event) or True
            elif event.type() == QtCore.QEvent.Type.DragLeave:
                self.dragLeaveEvent(event)
                return True
            elif event.type() == QtCore.QEvent.Type.DragMove:
                if event.mimeData().hasUrls():
                    has_files = any(
                        os.path.isfile(url.toLocalFile()) 
                        for url in event.mimeData().urls()
                    )
                    if has_files:
                        event.acceptProposedAction()
                        return True
            elif event.type() == QtCore.QEvent.Type.Drop:
                return self.dropEvent(event) or True
        return super().eventFilter(obj, event)
    
    def dragEnterEvent(self, event):
        """处理拖进事件"""
        if event.mimeData().hasUrls():
            # 检查是否有文件
            has_files = any(
                os.path.isfile(url.toLocalFile()) 
                for url in event.mimeData().urls()
            )
            if has_files:
                event.acceptProposedAction()
                self.is_drag_over = True
                # 高亮显示表格
                self.setStyleSheet(self.styleSheet() + 
                                 "\nQTableWidget { background-color: rgba(59, 130, 246, 0.15); border: 2px dashed rgba(59, 130, 246, 0.5); }")
                return True
            else:
                event.ignore()
        else:
            event.ignore()
        return False
    
    def dragLeaveEvent(self, event):
        """处理拖出事件"""
        if self.is_drag_over:
            self.is_drag_over = False
            # 恢复原样式
            style = self.styleSheet()
            # 移除高亮样式
            style = style.replace("\nQTableWidget { background-color: rgba(59, 130, 246, 0.15); border: 2px dashed rgba(59, 130, 246, 0.5); }", "")
            self.setStyleSheet(style)
    
    def dropEvent(self, event):
        """处理放下事件"""
        # 恢复原样式
        if self.is_drag_over:
            self.is_drag_over = False
            style = self.styleSheet()
            style = style.replace("\nQTableWidget { background-color: rgba(59, 130, 246, 0.15); border: 2px dashed rgba(59, 130, 246, 0.5); }", "")
            self.setStyleSheet(style)
        
        files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                files.append(file_path)
        
        if files:
            logger.info(f"拖拽上传文件: {files}")
            self.files_dropped.emit(files)
            event.acceptProposedAction()
            return True
        else:
            event.ignore()
        return False

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("123云盘")
        self.resize(980, 620)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)

        self.pan = None
        self.threadpool = QtCore.QThreadPool.globalInstance()
        # 设置线程池的最大线程数，允许同时下载多个文件
        self.threadpool.setMaxThreadCount(64)

        # 应用123云盘主题
        self.theme_manager = ThemeManager(self)
        
        # 注册主题改变回调
        self.theme_manager.on_theme_changed = self.on_theme_changed
        
        # 主题颜色映射
        self.theme_colors = {
            'light': {
                'text_primary': '#2d3749',
                'text_secondary': '#4c4f69',
                'text_disabled': '#9ca0b0',
                'bg_primary': '#eff1f5',
                'bg_secondary': '#fafbfc',
                'accent': '#1e66f5',
                'success': '#40a02b',
                'warning': '#df8e1d',
                'error': '#d20f39',
            },
            'dark': {
                'text_primary': '#cdd6f4',
                'text_secondary': '#bac2de',
                'text_disabled': '#6c7086',
                'bg_primary': '#1e1e2e',
                'bg_secondary': '#313244',
                'accent': '#89b4fa',
                'success': '#a6e3a1',
                'warning': '#f9e2af',
                'error': '#f38ba8',
            }
        }
        
        # 监听系统主题变化
        self.theme_timer = QtCore.QTimer()
        self.theme_timer.timeout.connect(self.theme_manager.check_theme_change)
        self.theme_timer.start(5000)  # 每5秒检查一次

        # 中央布局
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 创建侧边栏
        self.sidebar = QtWidgets.QWidget()
        self.sidebar.setMinimumWidth(200)
        self.sidebar.setMaximumWidth(200)
        
        # 动态设置侧边栏样式
        sidebar_bg = "#fafbfc" if not self.theme_manager.is_dark_mode else "#181825"
        sidebar_border = "#acb0be" if not self.theme_manager.is_dark_mode else "#313244"
        self.sidebar.setStyleSheet(
            f"background-color: {sidebar_bg};"
            f"border-right: 1px solid {sidebar_border};"
            "border-radius: 0;"
        )
        sidebar_layout = QtWidgets.QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 10)
        sidebar_layout.setSpacing(8)
        sidebar_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        
        # 侧边栏标题
        self.sidebar_title = QtWidgets.QLabel("功能菜单")
        self.sidebar_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_color = "#2d3749" if not self.theme_manager.is_dark_mode else "#cdd6f4"
        self.sidebar_title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {title_color}; margin-bottom: 16px; "
            "padding: 8px 0;"
        )
        sidebar_layout.addWidget(self.sidebar_title)
        
        # 侧边栏按钮组
        self.sidebar_buttons = []
        self.sidebar_animations = {}
        self.sidebar_original_geoms = {}
        
        # 文件页按钮 - 改为方形设计，图标居中，标签在下
        self.btn_files = SidebarButton("📁\n文件")
        self.btn_files.setMinimumHeight(100)
        self.btn_files.setMinimumWidth(140)
        self.btn_files.setMaximumHeight(100)
        self.btn_files.setMaximumWidth(140)
        self.btn_files.setStyleSheet(self.get_sidebar_button_style(is_active=True))
        sidebar_layout.addWidget(self.btn_files, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.sidebar_buttons.append(self.btn_files)
        
        # 传输页按钮 - 改为方形设计，图标居中，标签在下
        self.btn_transfer = SidebarButton("🔄\n传输")
        self.btn_transfer.setMinimumHeight(100)
        self.btn_transfer.setMinimumWidth(140)
        self.btn_transfer.setMaximumHeight(100)
        self.btn_transfer.setMaximumWidth(140)
        self.btn_transfer.setStyleSheet(self.get_sidebar_button_style(is_active=False))
        sidebar_layout.addWidget(self.btn_transfer, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.sidebar_buttons.append(self.btn_transfer)
        
        # 为侧边栏按钮添加悬停和点击事件，实现动画效果
        for btn in self.sidebar_buttons:
            btn.entered.connect(lambda b=btn: self.on_sidebar_button_hover(b))
            btn.left.connect(lambda b=btn: self.on_sidebar_button_leave(b))
            btn.pressed.connect(lambda b=btn: self.on_sidebar_button_pressed(b))
            btn.released.connect(lambda b=btn: self.on_sidebar_button_released(b))
            
            # 保存按钮的原始位置
            QtCore.QTimer.singleShot(100, lambda b=btn: self.save_original_position(b))
        
        sidebar_layout.addStretch()
        main_layout.addWidget(self.sidebar)
        
        # 创建右侧内容区域
        right_content = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_content)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)
        
        # 顶部横向按钮栏（左上角为设置按钮）
        toolbar_h = QtWidgets.QHBoxLayout()
        toolbar_h.setSpacing(6)
        
        # 设置按钮（左上角齿轮图标）
        self.btn_settings = QtWidgets.QPushButton("⚙️")
        self.btn_settings.setToolTip("设置")
        self.btn_settings.setMinimumHeight(36)
        self.btn_settings.setMinimumWidth(45)
        self.btn_settings.setMaximumHeight(36)
        self.btn_settings.setMaximumWidth(45)
        self.btn_settings.setStyleSheet(
            "font-size: 20px;"
            "background-color: transparent;"
            "border: none;"
            "border-radius: 8px;"
        )
        self.btn_settings.setObjectName("btn_settings")
        toolbar_h.addWidget(self.btn_settings)
        
        # 退出登陆按钮
        self.btn_logout = QtWidgets.QPushButton("🚪")
        self.btn_logout.setToolTip("退出登陆")
        self.btn_logout.setMinimumHeight(36)
        self.btn_logout.setMinimumWidth(45)
        self.btn_logout.setMaximumHeight(36)
        self.btn_logout.setMaximumWidth(45)
        self.btn_logout.setStyleSheet(
            "font-size: 20px;"
            "background-color: transparent;"
            "border: none;"
            "border-radius: 8px;"
        )
        self.btn_logout.setObjectName("btn_logout")
        toolbar_h.addWidget(self.btn_logout)
        
        # 操作按钮（横向排列）
        self.btn_refresh = QtWidgets.QPushButton("刷新")
        self.btn_more = QtWidgets.QPushButton("更多")
        self.btn_up = QtWidgets.QPushButton("上级")
        self.btn_delete = QtWidgets.QPushButton("删除")
        self.btn_download = QtWidgets.QPushButton("下载")
        self.btn_share = QtWidgets.QPushButton("分享")
        self.btn_link = QtWidgets.QPushButton("显示链接")
        self.btn_upload = QtWidgets.QPushButton("上传文件")
        self.btn_mkdir = QtWidgets.QPushButton("新建文件夹")

        # 关于按钮
        self.btn_about = QtWidgets.QPushButton("ℹ️")
        self.btn_about.setToolTip("关于")
        self.btn_about.setMinimumHeight(36)
        self.btn_about.setMinimumWidth(45)
        self.btn_about.setMaximumHeight(36)
        self.btn_about.setMaximumWidth(45)
        self.btn_about.setStyleSheet(
            "font-size: 20px;"
            "background-color: transparent;"
            "border: none;"
            "border-radius: 8px;"
        )
        self.btn_about.setObjectName("btn_about")
        toolbar_h.addWidget(self.btn_about)
        
        # 设置按钮最小宽度统一外观
        btns = [self.btn_refresh, self.btn_more, self.btn_up, self.btn_download, self.btn_link,
                self.btn_upload, self.btn_mkdir, self.btn_delete, self.btn_share]
        
        # 为每个按钮添加动画效果
        self.button_animations = {}
        # 记录按钮原始尺寸，避免动画使用未完成布局的宽度作为基准
        if not hasattr(self, 'button_original_sizes'):
            self.button_original_sizes = {}

        for b in btns:
            b.setMinimumHeight(30)
            # 根据按钮文本自动计算最小宽度，保证中文/emoji不被截断
            fm = b.fontMetrics()
            text_width = fm.horizontalAdvance(b.text())
            padding = 32  # 左右内边距预留（4px padding + 8px border margin）
            calc_min_w = max(85, text_width + padding)
            b.setMinimumWidth(calc_min_w)
            # 设置较大的最大宽度，避免动画过程中被意外限制
            b.setMaximumWidth(max(calc_min_w + 20, 2000))
            # 初始记录为计算得到的最小宽度
            self.button_original_sizes[b] = calc_min_w
            b.setSizePolicy(QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Minimum)
            b.setStyleSheet(
                "QPushButton {"
                "  padding: 4px 8px;"
                "  background-color: rgba(229, 231, 235, 0.8);"
                "  color: #334155;"
                "  border: 1px solid rgba(0, 0, 0, 0.08);"
                "  border-radius: 6px;"
                "  font-size: 12px;"
                "  font-weight: 500;"
                "}"
                "QPushButton:hover {"
                "  background-color: rgba(209, 213, 219, 0.9);"
                "}"
                "QPushButton:pressed {"
                "  background-color: rgba(189, 195, 204, 1.0);"
                "}"
            )
            toolbar_h.addWidget(b)
            
            # 为按钮添加悬停和点击事件，实现动画效果
            b.enterEvent = lambda event, btn=b: self.on_button_hover(btn)
            b.leaveEvent = lambda event, btn=b: self.on_button_leave(btn)
            b.pressed.connect(lambda btn=b: self.on_button_pressed(btn))
            b.released.connect(lambda btn=b: self.on_button_released(btn))

        toolbar_h.addStretch()
        right_layout.addLayout(toolbar_h)
        
        # 路径栏
        self.path_widget = QtWidgets.QWidget()
        path_h = QtWidgets.QHBoxLayout(self.path_widget)
        path_h.addWidget(QtWidgets.QLabel("路径："))
        self.lbl_path = QtWidgets.QLabel("/")
        font = self.lbl_path.font()
        font.setBold(True)
        self.lbl_path.setFont(font)
        path_h.addWidget(self.lbl_path)
        path_h.addStretch()
        right_layout.addWidget(self.path_widget)
        
        # 创建页面堆栈
        self.page_stack = QtWidgets.QStackedWidget()
        
        # 文件页面
        self.files_page = QtWidgets.QWidget()
        files_layout = QtWidgets.QVBoxLayout(self.files_page)
        files_layout.setContentsMargins(0, 0, 0, 0)
        
        # 文件列表区域（包含表格和加载动画）
        file_list_widget = QtWidgets.QWidget()
        file_list_layout = QtWidgets.QVBoxLayout(file_list_widget)
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        
        # 文件列表表格（支持拖拽上传）
        self.table = DropAreaTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "编号", "名称", "类型", "大小"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.on_table_double)
        self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        # 连接拖拽上传信号
        self.table.files_dropped.connect(self.on_files_dropped)
        file_list_layout.addWidget(self.table, stretch=1)
        
        # 加载动画布局
        self.loading_widget = QtWidgets.QWidget()
        loading_layout = QtWidgets.QVBoxLayout(self.loading_widget)
        loading_layout.setContentsMargins(0, 0, 0, 0)
        loading_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        # 加载标签
        self.loading_label = QtWidgets.QLabel()
        self.loading_label.setText("正在加载...")
        font = self.loading_label.font()
        font.setPointSize(14)
        self.loading_label.setFont(font)
        self.loading_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.loading_label)
        
        # 旋转动画
        self.loading_spinner = QtWidgets.QLabel()
        self.loading_spinner.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        # 创建一个简单的旋转动画
        self.spinner_timer = QtCore.QTimer()
        self.spinner_angle = 0
        self.spinner_timer.timeout.connect(self.update_spinner)
        # 不在这里启动计时器，延迟到loading_widget显示时再启动
        
        loading_layout.addWidget(self.loading_spinner)
        
        # 初始隐藏加载动画
        self.loading_widget.setVisible(False)
        file_list_layout.addWidget(self.loading_widget)
        
        files_layout.addWidget(file_list_widget, stretch=1)
        
        # 传输任务管理
        self.transfer_tasks = []
        self.next_task_id = 0
        self.active_tasks = {}  # 保存活动任务的引用，用于取消
        
        # 传输页面
        self.transfer_page = QtWidgets.QWidget()
        transfer_layout = QtWidgets.QVBoxLayout(self.transfer_page)
        transfer_layout.setContentsMargins(0, 0, 0, 0)
        
        # 传输页面内容
        transfer_title = QtWidgets.QLabel("传输任务")
        transfer_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_color = self.get_theme_color('text_primary')
        transfer_title.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {title_color}; margin: 20px 0;")
        transfer_layout.addWidget(transfer_title)
        
        self.transfer_table = QtWidgets.QTableWidget(0, 6)
        self.transfer_table.setHorizontalHeaderLabels(["类型", "文件名", "大小", "进度", "状态", "操作"])
        self.transfer_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.transfer_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.transfer_table.verticalHeader().setVisible(False)
        self.transfer_table.verticalHeader().setDefaultSectionSize(60)
        self.transfer_table.horizontalHeader().setStretchLastSection(True)
        # 设置列宽
        self.transfer_table.setColumnWidth(0, 80)
        self.transfer_table.setColumnWidth(2, 120)
        self.transfer_table.setColumnWidth(3, 100)
        self.transfer_table.setColumnWidth(4, 100)
        self.transfer_table.setColumnWidth(5, 120)
        transfer_layout.addWidget(self.transfer_table, stretch=1)
        
        # 添加页面到堆栈
        self.page_stack.addWidget(self.files_page)
        self.page_stack.addWidget(self.transfer_page)
        
        right_layout.addWidget(self.page_stack, stretch=1)
        main_layout.addWidget(right_content, stretch=1)

        # 状态栏显示简短提示/进度
        self.status = self.statusBar()
        self.status.showMessage("准备就绪")

        # 信号连接
        self.btn_settings.clicked.connect(self.on_settings)
        self.btn_logout.clicked.connect(self.on_logout)
        self.btn_refresh.clicked.connect(lambda: self.refresh_file_list(reset_page=True))
        self.btn_more.clicked.connect(lambda: self.refresh_file_list(reset_page=False))
        self.btn_up.clicked.connect(self.on_up)
        self.btn_download.clicked.connect(self.on_download)
        self.btn_link.clicked.connect(self.on_showlink)
        self.btn_upload.clicked.connect(self.on_upload)
        self.btn_mkdir.clicked.connect(self.on_mkdir)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_share.clicked.connect(self.on_share)
        
        # 侧边栏按钮信号
        self.btn_files.clicked.connect(lambda: self.switch_page(0))
        self.btn_transfer.clicked.connect(lambda: self.switch_page(1))
        
        # 初始化默认页面
        self.switch_page(0)


        # 关于按钮信号
        self.btn_about.clicked.connect(self.on_about)
        
        # 启动登录流程
        self.startup_login_flow()

    def on_settings(self):
        """打开设置对话框"""
        dlg = SettingsDialog(self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            settings = dlg.get_settings()
            # 保存设置到配置文件
            config = ConfigManager.load_config()
            config["settings"] = settings
            ConfigManager.save_config(config)
            QtWidgets.QMessageBox.information(self, "设置", "设置已保存")
    
    def on_logout(self):
        """退出登陆"""
        reply = QtWidgets.QMessageBox.question(
            self, "退出登陆", "确定要退出登陆吗？",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # 清除配置文件中的登陆信息
            config = ConfigManager.load_config()
            config["userName"] = ""
            config["passWord"] = ""
            config["authorization"] = ""
            ConfigManager.save_config(config)
            
            # 清空当前登陆状态
            self.pan = None
            
            # 显示登陆对话框
            dlg = LoginDialog(self)
            if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                QtWidgets.QMessageBox.information(self, "提示", "未登录，程序将退出。")
                QtCore.QTimer.singleShot(0, self.close)
                return
            self.pan = dlg.get_pan()
            self.refresh_file_list(reset_page=True)
            QtWidgets.QMessageBox.information(self, "提示", "登陆成功")
    
    def on_files_dropped(self, files):
        """处理拖拽上传的文件"""
        logger.info(f"收到拖拽上传请求，文件数: {len(files)}")
        if not self.pan:
            logger.warning("未登录，无法上传")
            QtWidgets.QMessageBox.information(self, "提示", "请先登录。")
            return
        
        # 逐个上传文件
        for file_path in files:
            self._upload_single_file(file_path)
    
    def _upload_single_file(self, file_path):
        """上传单个文件"""
        logger.info(f"准备上传文件: {file_path}")
        if not os.path.isfile(file_path):
            logger.warning(f"文件不存在: {file_path}")
            return
        
        fname = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        logger.info(f"文件信息 - 名称: {fname}, 大小: {file_size} 字节")
        same = [i for i in self.pan.list if i.get("FileName") == fname]
        dup_choice = 1
        
        if same:
            text, ok = QtWidgets.QInputDialog.getText(
                self, "同名文件", 
                f"检测到同名文件: {fname}\n输入行为: 1 覆盖; 2 保留两者; 0 取消（默认1）", 
                text="1"
            )
            if not ok:
                return
            if text.strip() not in ("0", "1", "2"):
                QtWidgets.QMessageBox.information(self, "提示", "无效的选择，已取消")
                return
            if text.strip() == "0":
                return
            dup_choice = int(text.strip())
        
        # 添加传输任务
        task_id = self.add_transfer_task("上传", fname, file_size)
        
        task = ThreadedTask(self._task_upload_file, file_path, dup_choice, task_id)
        
        # 保存任务对象引用
        for i, t in enumerate(self.transfer_tasks):
            if t["id"] == task_id:
                self.transfer_tasks[i]["threaded_task"] = task
                break
        
        self.active_tasks[task_id] = task
        
        def on_task_finished(tid):
            if tid in self.active_tasks:
                del self.active_tasks[tid]
        
        task.signals.progress.connect(lambda p, tid=task_id: (
            self.status.showMessage(f"上传进度: {p}%", 2000),
            self.update_transfer_task(tid, p, "上传中")
        ))
        task.signals.result.connect(lambda r, tid=task_id: (
            self.status.showMessage("上传完成", 3000),
            self.update_transfer_task(tid, 100, "已完成"),
            on_task_finished(tid),
            self.refresh_file_list(reset_page=False)
        ))
        task.signals.error.connect(lambda e, tid=task_id: (
            self.status.showMessage(f"上传出错: {e}", 3000),
            self.update_transfer_task(tid, 0, "失败"),
            on_task_finished(tid)
        ))
        
        self.threadpool.start(task)

    def on_about(self):
        """打开关于对话框"""
        dlg = AboutDialog(self)
        dlg.exec()
    
    def startup_login_flow(self):
        cfg_loaded = False
        config = ConfigManager.load_config()
        if config.get("userName") and config.get("passWord"):
            try:
                self.pan = Pan123(readfile=True, input_pwd=False)
                res_code = self.pan.get_dir(save=False)[0]
                if res_code == 0:
                    cfg_loaded = True
                else:
                    cfg_loaded = False
            except Exception:
                cfg_loaded = False

        if not cfg_loaded:
            dlg = LoginDialog(self)
            if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                QtWidgets.QMessageBox.information(self, "提示", "未登录，程序将退出。")
                QtCore.QTimer.singleShot(0, self.close)
                return
            self.pan = dlg.get_pan()

        self.refresh_file_list(reset_page=True)

    def prompt_selected_row(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "提示", "请先选择一项。")
            return None
        return rows[0].row()

    def get_file_icon(self, file_detail):
        """根据文件类型获取图标"""
        file_type = file_detail.get("Type", 0)
        file_name = file_detail.get("FileName", "")
        
        # 创建一个32x32的图标
        pixmap = QtGui.QPixmap(32, 32)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        if file_type == 1:  # 文件夹
            # 绘制文件夹图标
            painter.setBrush(QtGui.QColor(255, 193, 7))
            painter.setPen(QtGui.QColor(255, 152, 0))
            # 文件夹主体
            painter.drawRect(6, 10, 20, 16)
            # 文件夹盖子
            painter.drawRect(6, 6, 16, 8)
        else:  # 文件
            # 根据文件扩展名选择图标颜色
            ext = os.path.splitext(file_name)[1].lower()
            colors = {
                ".txt": QtGui.QColor(25, 118, 210),
                ".pdf": QtGui.QColor(211, 47, 47),
                ".doc": QtGui.QColor(33, 150, 243),
                ".docx": QtGui.QColor(33, 150, 243),
                ".xls": QtGui.QColor(76, 175, 80),
                ".xlsx": QtGui.QColor(76, 175, 80),
                ".ppt": QtGui.QColor(255, 193, 7),
                ".pptx": QtGui.QColor(255, 193, 7),
                ".jpg": QtGui.QColor(156, 39, 176),
                ".jpeg": QtGui.QColor(156, 39, 176),
                ".png": QtGui.QColor(156, 39, 176),
                ".gif": QtGui.QColor(156, 39, 176),
                ".mp3": QtGui.QColor(94, 53, 177),
                ".mp4": QtGui.QColor(233, 30, 99),
                ".zip": QtGui.QColor(121, 85, 72),
                ".rar": QtGui.QColor(121, 85, 72),
                ".7z": QtGui.QColor(121, 85, 72),
            }
            
            color = colors.get(ext, QtGui.QColor(100, 116, 139))
            painter.setBrush(color)
            painter.setPen(color.darker(120))
            
            # 绘制文件图标
            painter.drawRect(6, 8, 20, 20)
            # 绘制文件顶部的横线
            painter.setBrush(color.darker(120))
            painter.drawRect(6, 8, 20, 4)
        
        painter.end()
        return QtGui.QIcon(pixmap)
    
    def populate_table(self):
        if not self.pan:
            return
        self.table.setRowCount(0)
        
        # 直接添加所有行，避免延迟导致的数据错乱
        for index, item in enumerate(self.pan.list):
            self._add_row(index)

        names = getattr(self.pan, "parent_file_name_list", [])
        path = "/" + "/".join(names) if names else "/"
        self.lbl_path.setText(path)
    
    def _add_row(self, index):
        """添加行，逐行显示"""
        if index >= len(self.pan.list):
            return
            
        item = self.pan.list[index]
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # 添加文件图标
        icon = self.get_file_icon(item)
        icon_item = QtWidgets.QTableWidgetItem()
        icon_item.setIcon(icon)
        self.table.setItem(row, 0, icon_item)
        
        # 设置列宽，图标列不需要太宽
        self.table.setColumnWidth(0, 40)
        
        # 编号
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(index + 1)))
        
        # 文件名
        name_item = QtWidgets.QTableWidgetItem(item.get("FileName", ""))
        # 文件夹使用粗体
        if item.get("Type", 0) == 1:
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
        self.table.setItem(row, 2, name_item)
        
        # 文件类型
        typ = "文件夹" if item.get("Type", 0) == 1 else "文件"
        self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(typ))
        
        # 文件大小
        size = item.get("Size", 0)
        if size > 1073741824:
            s = f"{round(size / 1073741824, 2)} GB"
        elif size > 1048576:
            s = f"{round(size / 1048576, 2)} MB"
        else:
            s = f"{round(size / 1024, 2)} KB"
        self.table.setItem(row, 4, QtWidgets.QTableWidgetItem(s))

    def update_spinner(self):
        """更新旋转动画"""
        self.spinner_angle = (self.spinner_angle + 10) % 360
        pixmap = QtGui.QPixmap(32, 32)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        # 绘制旋转圆环
        pen = QtGui.QPen(QtGui.QColor(59, 130, 246), 3)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rect = QtCore.QRect(4, 4, 24, 24)
        painter.drawArc(rect, (90 - self.spinner_angle) * 16, 180 * 16)
        
        painter.end()
        self.loading_spinner.setPixmap(pixmap)
    
    def refresh_file_list(self, reset_page=True):
        if not self.pan:
            QtWidgets.QMessageBox.information(self, "提示", "尚未初始化，请先登录。")
            return
        if reset_page:
            self.pan.all_file = False
            self.pan.file_page = 0
            self.pan.list = []
        
        # 显示加载动画
        self.table.setVisible(False)
        self.loading_widget.setVisible(True)
        # 启动加载动画计时器
        if not self.spinner_timer.isActive():
            self.spinner_timer.start(50)
        self.status.showMessage("正在获取目录...")
        
        task = ThreadedTask(self._task_get_dir)
        task.signals.result.connect(self._after_get_dir)
        task.signals.error.connect(lambda e: self._show_error("获取目录失败: " + e))
        self.threadpool.start(task)

    def _task_get_dir(self, signals=None, task=None):
        code, _ = self.pan.get_dir(save=True)
        return code

    def _after_get_dir(self, code):
        # 隐藏加载动画，显示表格
        self.loading_widget.setVisible(False)
        self.table.setVisible(True)
        # 停止加载动画计时器
        if self.spinner_timer.isActive():
            self.spinner_timer.stop()
        
        if code != 0:
            self.status.showMessage(f"获取目录返回码: {code}", 5000)
        else:
            self.status.showMessage("目录获取完成", 3000)
        self.populate_table()

    def on_table_double(self, index):
        row = index.row()
        typ_item = self.table.item(row, 3)
        if typ_item and typ_item.text() == "文件夹":
            try:
                # 保存要进入的文件夹编号
                self.target_folder_num = str(row + 1)
                # 添加淡出动画
                self.fade_animation = QtCore.QPropertyAnimation(self.table, b"windowOpacity")
                self.fade_animation.setDuration(200)
                self.fade_animation.setStartValue(1.0)
                self.fade_animation.setEndValue(0.0)
                self.fade_animation.finished.connect(self._after_fade_out_enter_folder)
                self.fade_animation.start()
            except Exception as e:
                self._show_error("进入文件夹失败: " + str(e))
        else:
            ret = QtWidgets.QMessageBox.question(self, "下载", "是否下载所选文件？", QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if ret == QtWidgets.QMessageBox.StandardButton.Yes:
                self.on_download()
    
    def _after_fade_out_enter_folder(self):
        """淡出动画完成后执行的操作 - 进入文件夹"""
        try:
            self.pan.cd(self.target_folder_num)
            self.populate_table()
            # 添加淡入动画
            self.fade_animation = QtCore.QPropertyAnimation(self.table, b"windowOpacity")
            self.fade_animation.setDuration(200)
            self.fade_animation.setStartValue(0.0)
            self.fade_animation.setEndValue(1.0)
            self.fade_animation.start()
        except Exception as e:
            self._show_error("进入文件夹失败: " + str(e))
    
    def on_button_hover(self, button):
        """按钮悬停效果 - 改变背景色和边框"""
        button.setStyleSheet(
            "QPushButton {"
            "  padding: 4px 8px;"
            "  background-color: rgba(189, 195, 204, 0.95);"
            "  color: #334155;"
            "  border: 1px solid rgba(59, 130, 246, 0.3);"
            "  border-radius: 6px;"
            "  font-size: 12px;"
            "  font-weight: 500;"
            "}"
        )
    
    def on_button_leave(self, button):
        """按钮离开效果 - 恢复原始样式"""
        # 停止当前正在运行的动画
        if button in self.button_animations:
            self.button_animations[button].stop()

        button.setStyleSheet(
            "QPushButton {"
            "  padding: 4px 8px;"
            "  background-color: rgba(229, 231, 235, 0.8);"
            "  color: #334155;"
            "  border: 1px solid rgba(0, 0, 0, 0.08);"
            "  border-radius: 6px;"
            "  font-size: 12px;"
            "  font-weight: 500;"
            "}"
            "QPushButton:hover {"
            "  background-color: rgba(209, 213, 219, 0.9);"
            "}"
            "QPushButton:pressed {"
            "  background-color: rgba(189, 195, 204, 1.0);"
            "}"
        )
    
    def on_button_pressed(self, button):
        """按钮按下效果 - 改变样式"""
        # 停止当前正在运行的动画
        if button in self.button_animations:
            self.button_animations[button].stop()

        button.setStyleSheet(
            "QPushButton {"
            "  padding: 4px 8px;"
            "  background-color: rgba(169, 177, 189, 1.0);"
            "  color: #334155;"
            "  border: 1px solid rgba(59, 130, 246, 0.4);"
            "  border-radius: 6px;"
            "  font-size: 12px;"
            "  font-weight: 500;"
            "}"
        )
    
    def on_button_released(self, button):
        """按钮释放效果 - 恢复样式"""
        # 停止当前正在运行的动画
        if button in self.button_animations:
            self.button_animations[button].stop()

        # 检查鼠标是否仍在按钮上
        if button.underMouse():
            button.setStyleSheet(
                "QPushButton {"
                "  padding: 4px 8px;"
                "  background-color: rgba(189, 195, 204, 0.95);"
                "  color: #334155;"
                "  border: 1px solid rgba(59, 130, 246, 0.3);"
                "  border-radius: 6px;"
                "  font-size: 12px;"
                "  font-weight: 500;"
                "}"
            )
        else:
            button.setStyleSheet(
                "QPushButton {"
                "  padding: 4px 8px;"
                "  background-color: rgba(229, 231, 235, 0.8);"
                "  color: #334155;"
                "  border: 1px solid rgba(0, 0, 0, 0.08);"
                "  border-radius: 6px;"
                "  font-size: 12px;"
                "  font-weight: 500;"
                "}"
                "QPushButton:hover {"
                "  background-color: rgba(209, 213, 219, 0.9);"
                "}"
                "QPushButton:pressed {"
                "  background-color: rgba(189, 195, 204, 1.0);"
                "}"
            )

    def on_table_context_menu(self, pos):
        row = self.table.indexAt(pos).row()
        if row < 0:
            return
        menu = QtWidgets.QMenu()
        a_download = menu.addAction("下载")
        a_link = menu.addAction("显示链接")
        a_delete = menu.addAction("删除")
        a_share = menu.addAction("分享")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        self.table.selectRow(row)
        if action == a_download:
            self.on_download()
        elif action == a_link:
            self.on_showlink()
        elif action == a_delete:
            self.on_delete()
        elif action == a_share:
            self.on_share()

    def on_up(self):
        if not self.pan:
            return
        try:
            # 添加淡出动画
            self.fade_animation = QtCore.QPropertyAnimation(self.table, b"windowOpacity")
            self.fade_animation.setDuration(200)
            self.fade_animation.setStartValue(1.0)
            self.fade_animation.setEndValue(0.0)
            self.fade_animation.finished.connect(self._after_fade_out_up)
            self.fade_animation.start()
        except Exception as e:
            self._show_error("返回上级失败: " + str(e))
    
    def _after_fade_out_up(self):
        """淡出动画完成后执行的操作 - 返回上级"""
        try:
            self.pan.cd("..")
            self.populate_table()
            # 添加淡入动画
            self.fade_animation = QtCore.QPropertyAnimation(self.table, b"windowOpacity")
            self.fade_animation.setDuration(200)
            self.fade_animation.setStartValue(0.0)
            self.fade_animation.setEndValue(1.0)
            self.fade_animation.start()
        except Exception as e:
            self._show_error("返回上级失败: " + str(e))
    
    def save_original_position(self, button):
        """保存按钮的原始位置"""
        self.sidebar_original_geoms[button] = button.geometry()
    
    def switch_page(self, page_index):
        """切换页面"""
        # 切换堆栈页面
        self.page_stack.setCurrentIndex(page_index)
        
        # 更新按钮样式
        for i, btn in enumerate(self.sidebar_buttons):
            if i == page_index:
                btn.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(59, 130, 246, 0.9);"
                    "color: white; border-radius: 16px;"
                    "border: none;"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
            else:
                btn.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(229, 231, 235, 0.8); color: #334155;"
                    "border-radius: 16px;"
                    "border: 1px solid rgba(0, 0, 0, 0.08);"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
        
        # 根据页面显示/隐藏路径栏和相关按钮
        if page_index == 0:  # 文件页面
            self.path_widget.setVisible(True)
            self.btn_refresh.setVisible(True)
            self.btn_more.setVisible(True)
            self.btn_up.setVisible(True)
            self.btn_delete.setVisible(True)
            self.btn_download.setVisible(True)
            self.btn_share.setVisible(True)
            self.btn_link.setVisible(True)
            self.btn_upload.setVisible(True)
            self.btn_mkdir.setVisible(True)
        else:  # 传输页面
            self.path_widget.setVisible(False)
            self.btn_refresh.setVisible(False)
            self.btn_more.setVisible(False)
            self.btn_up.setVisible(False)
            self.btn_delete.setVisible(False)
            self.btn_download.setVisible(False)
            self.btn_share.setVisible(False)
            self.btn_link.setVisible(False)
            self.btn_upload.setVisible(False)
            self.btn_mkdir.setVisible(False)
    
    def on_sidebar_button_hover(self, button):
        """侧边栏按钮悬停效果 - 改变背景色"""
        if button == self.btn_files:
            button.setStyleSheet(
                "font-size: 13px; text-align: center; font-weight: 500;"
                "background-color: rgba(37, 99, 235, 1);"
                "color: white; border-radius: 16px;"
                "border: none;"
                "padding: 8px;"
                "line-height: 1.4;"
            )
        elif button == self.btn_transfer:
            button.setStyleSheet(
                "font-size: 13px; text-align: center; font-weight: 500;"
                "background-color: rgba(59, 130, 246, 0.15); color: #1e40af;"
                "border-radius: 16px;"
                "border: 1px solid rgba(37, 99, 235, 0.3);"
                "padding: 8px;"
                "line-height: 1.4;"
            )
    
    def on_sidebar_button_leave(self, button):
        """侧边栏按钮离开效果 - 恢复原始样式"""
        if button == self.btn_files:
            if self.page_stack.currentIndex() == 0:
                button.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(59, 130, 246, 0.9);"
                    "color: white; border-radius: 16px;"
                    "border: none;"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
            else:
                button.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(229, 231, 235, 0.8); color: #334155;"
                    "border-radius: 16px;"
                    "border: 1px solid rgba(0, 0, 0, 0.08);"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
        elif button == self.btn_transfer:
            if self.page_stack.currentIndex() == 1:
                button.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(59, 130, 246, 0.9);"
                    "color: white; border-radius: 16px;"
                    "border: none;"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
            else:
                button.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(229, 231, 235, 0.8); color: #334155;"
                    "border-radius: 16px;"
                    "border: 1px solid rgba(0, 0, 0, 0.08);"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
    
    def on_sidebar_button_pressed(self, button):
        """侧边栏按钮按下效果 - 改变背景色与加深"""
        if button == self.btn_files:
            button.setStyleSheet(
                "font-size: 13px; text-align: center; font-weight: 500;"
                "background-color: rgba(29, 78, 216, 1);"
                "color: white; border-radius: 16px;"
                "border: none;"
                "padding: 8px;"
                "line-height: 1.4;"
            )
        elif button == self.btn_transfer:
            button.setStyleSheet(
                "font-size: 13px; text-align: center; font-weight: 500;"
                "background-color: rgba(37, 99, 235, 0.2); color: #1e40af;"
                "border-radius: 16px;"
                "border: 1px solid rgba(37, 99, 235, 0.4);"
                "padding: 8px;"
                "line-height: 1.4;"
            )
    
    def on_sidebar_button_released(self, button):
        """侧边栏按钮释放效果 - 根据页面状态恢复样式"""
        if button == self.btn_files:
            if self.page_stack.currentIndex() == 0:
                button.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(59, 130, 246, 0.9);"
                    "color: white; border-radius: 16px;"
                    "border: none;"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
            else:
                button.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(229, 231, 235, 0.8); color: #334155;"
                    "border-radius: 16px;"
                    "border: 1px solid rgba(0, 0, 0, 0.08);"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
        elif button == self.btn_transfer:
            if self.page_stack.currentIndex() == 1:
                button.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(59, 130, 246, 0.9);"
                    "color: white; border-radius: 16px;"
                    "border: none;"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )
            else:
                button.setStyleSheet(
                    "font-size: 13px; text-align: center; font-weight: 500;"
                    "background-color: rgba(229, 231, 235, 0.8); color: #334155;"
                    "border-radius: 16px;"
                    "border: 1px solid rgba(0, 0, 0, 0.08);"
                    "padding: 8px;"
                    "line-height: 1.4;"
                )

    def add_transfer_task(self, type_str, name, size):
            # 确保 UI 操作在主线程
            row = self.transfer_table.rowCount()
            self.transfer_table.insertRow(row)

            task_id = self.next_task_id
            self.next_task_id += 1

            # 把 task_id 绑定到 Item 上（用于通过 ID 查找行）
            name_item = QtWidgets.QTableWidgetItem(name)
            name_item.setData(QtCore.Qt.ItemDataRole.UserRole, task_id)

            self.transfer_table.setItem(row, 0, QtWidgets.QTableWidgetItem(type_str))
            self.transfer_table.setItem(row, 1, name_item)

            # 格式化大小
            if size > 1024 * 1024 * 1024:
                s = f"{round(size / (1024**3), 2)} GB"
            elif size > 1024 * 1024:
                s = f"{round(size / (1024**2), 2)} MB"
            else:
                s = f"{round(size / 1024, 2)} KB"
                
            self.transfer_table.setItem(row, 2, QtWidgets.QTableWidgetItem(s))
            self.transfer_table.setItem(row, 3, QtWidgets.QTableWidgetItem("0%"))
            self.transfer_table.setItem(row, 4, QtWidgets.QTableWidgetItem("等待中"))
            
            # 创建操作按钮（解决显示不全的关键）
            action_widget = QtWidgets.QWidget()
            action_layout = QtWidgets.QHBoxLayout(action_widget)
            # 消除布局边距和间距，防止挤压按钮
            action_layout.setContentsMargins(5, 2, 5, 2)
            action_layout.setSpacing(6)
            
            # 暂停/恢复按钮
            pause_btn = QtWidgets.QPushButton("暂停")
            pause_btn.setObjectName("transferActionBtn")
            # 强制设置较小的尺寸控制样式，覆盖全局主题
            btn_style = "padding: 4px 8px; font-size: 11px; min-width: 45px; height: 24px;"
            pause_btn.setStyleSheet(btn_style)
            
            # 取消按钮
            cancel_btn = QtWidgets.QPushButton("取消")
            cancel_btn.setObjectName("transferActionBtn")
            cancel_btn.setStyleSheet(btn_style)

            action_layout.addWidget(pause_btn)
            action_layout.addWidget(cancel_btn)
            # 伸缩量让按钮居中
            action_layout.addStretch() 
            
            self.transfer_table.setCellWidget(row, 5, action_widget)

            # 完善任务字典存储（便于状态更新）
            task_info = {
                "id": task_id,
                "type": type_str,
                "name": name,
                "size": size,
                "progress": 0,
                "status": "等待中",
                "file_path": None,
                "threaded_task": None,
                "pause_button": pause_btn,   # 直接保存引用
                "cancel_button": cancel_btn, # 直接保存引用
                "row": row
            }
            self.transfer_tasks.append(task_info)

            # 绑定按钮事件
            pause_btn.clicked.connect(lambda: self.toggle_task_pause(task_id, pause_btn))
            cancel_btn.clicked.connect(lambda: self.cancel_task(task_id))

            # 自动调整最后一列宽度以适应按钮
            self.transfer_table.setColumnWidth(5, 130) 

            return task_id

    def create_action_buttons(self, task_id):
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        
        # 暂停/恢复按钮
        pause_btn = QtWidgets.QPushButton("暂停")
        # 取消按钮
        cancel_btn = QtWidgets.QPushButton("取消")
        
        # 设置按钮固定大小，防止被 QSS 拉伸变形
        pause_btn.setFixedSize(60, 24)
        cancel_btn.setFixedSize(60, 24)
        
        # 可以在这里为这些按钮添加特定的对象名，以便单独设置样式
        pause_btn.setObjectName("transferActionBtn")
        cancel_btn.setObjectName("transferActionBtn")
        
        # 连接按钮信号到处理函数
        pause_btn.clicked.connect(lambda: self.toggle_task_pause(task_id, pause_btn))
        cancel_btn.clicked.connect(lambda: self.cancel_task(task_id))
        
        # 保存按钮引用到任务中，便于后续更新
        for i, t in enumerate(self.transfer_tasks):
            if t["id"] == task_id:
                self.transfer_tasks[i]['pause_button'] = pause_btn
                self.transfer_tasks[i]['cancel_button'] = cancel_btn
                break

        layout.addWidget(pause_btn)
        layout.addWidget(cancel_btn)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        
        return container
    
    def update_transfer_task(self, task_id, progress, status):
            """根据 task_id 安全地更新传输列表中的某一行"""
            # 遍历表格找到匹配 task_id 的行（假设我们将 task_id 存储在某列的数据角色中）
            found_row = -1
            for row in range(self.transfer_table.rowCount()):
                item = self.transfer_table.item(row, 1) # 获取文件名那一列
                if item and item.data(QtCore.Qt.ItemDataRole.UserRole) == task_id:
                    found_row = row
                    break
            
            if found_row == -1:
                return

            # 更新进度 (第3列)
            if progress is not None:
                self.transfer_table.item(found_row, 3).setText(f"{progress}%")
                
            # 更新状态 (第4列)
            if status:
                self.transfer_table.item(found_row, 4).setText(status)
    
    def cancel_transfer_task(self, task_id):
        """取消传输任务"""
        # 查找任务
        for i, task in enumerate(self.transfer_tasks):
            if task["id"] == task_id:
                # 取消线程任务
                if task.get("threaded_task"):
                    task["threaded_task"].cancel()
                
                # 如果是下载任务，删除临时文件
                if task["type"] == "下载" and task.get("file_path") and os.path.exists(task["file_path"]):
                    try:
                        os.remove(task["file_path"])
                        # 也检查是否有最终文件存在（如果下载已完成但未清理）
                        final_path = task["file_path"].replace(".123pan", "")
                        if os.path.exists(final_path):
                            os.remove(final_path)
                    except Exception as e:
                        print(f"删除文件失败: {e}")
                
                # 更新任务状态
                task["status"] = "已取消"
                task["progress"] = 0
                self.transfer_table.setItem(i, 3, QtWidgets.QTableWidgetItem("0%"))
                self.transfer_table.setItem(i, 4, QtWidgets.QTableWidgetItem("已取消"))
                
                # 隐藏按钮容器
                widget = self.transfer_table.cellWidget(i, 5)
                if widget:
                    widget.setVisible(False)
                # 也隐藏单独的按钮引用（若存在）
                if task.get('pause_button'):
                    try:
                        task['pause_button'].setVisible(False)
                    except Exception:
                        pass
                if task.get('cancel_button'):
                    try:
                        task['cancel_button'].setVisible(False)
                    except Exception:
                        pass
                
                # 从活动任务列表中移除
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]
                
                break

    def pause_transfer_task(self, task_id):
        """切换暂停/继续传输任务"""
        for i, task in enumerate(self.transfer_tasks):
            if task["id"] == task_id:
                threaded = task.get("threaded_task")
                pause_btn = task.get('pause_button')
                if not threaded:
                    return
                # 切换状态
                if getattr(threaded, 'is_paused', False):
                    try:
                        threaded.resume()
                    except Exception:
                        pass
                    task["status"] = "下载中"
                    if pause_btn:
                        pause_btn.setText("暂停")
                else:
                    try:
                        threaded.pause()
                    except Exception:
                        pass
                    task["status"] = "已暂停"
                    if pause_btn:
                        pause_btn.setText("继续")

                # 更新表格显示
                self.transfer_table.setItem(i, 4, QtWidgets.QTableWidgetItem(task["status"]))
                break
    
    def remove_transfer_task(self, task_id):
        """移除传输任务"""
        # 查找任务
        for i, task in enumerate(self.transfer_tasks):
            if task["id"] == task_id:
                # 从列表中移除
                self.transfer_tasks.pop(i)
                # 从表格中移除
                self.transfer_table.removeRow(i)
                # 从活动任务列表中移除
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]
                break
    
    def format_file_size(self, size):
        """格式化文件大小"""
        if size > 1073741824:
            return f"{round(size / 1073741824, 2)} GB"
        elif size > 1048576:
            return f"{round(size / 1048576, 2)} MB"
        elif size > 1024:
            return f"{round(size / 1024, 2)} KB"
        else:
            return f"{size} B"

    def get_selected_detail(self):
        row = self.prompt_selected_row()
        if row is None:
            return None, None
        try:
            # 直接使用行索引作为文件索引，更可靠
            if not self.pan or row < 0 or row >= len(self.pan.list):
                self._show_error("无效的选择行")
                return None, None
            return row, self.pan.list[row]
        except Exception as e:
            self._show_error(f"获取选中文件失败: {str(e)}")
            return None, None

    def on_download(self):
        file_index, file_detail = self.get_selected_detail()
        if file_detail is None:
            return
        
        # 获取设置
        ask_location = ConfigManager.get_setting("askDownloadLocation", True)
        default_path = ConfigManager.get_setting("defaultDownloadPath", 
                                                os.path.join(os.path.expanduser("~"), "Downloads"))
        
        download_dir = default_path
        if ask_location:
            download_dir = QtWidgets.QFileDialog.getExistingDirectory(
                self, "选择下载文件夹", default_path
            )
            if not download_dir:
                return
        
        file_name = file_detail.get("FileName", "未知文件")
        file_size = file_detail.get("Size", 0)
        
        # 添加传输任务
        task_id = self.add_transfer_task("下载", file_name, file_size)
        
        self.status.showMessage("正在解析下载链接...")
        task = ThreadedTask(self._task_get_download_and_stream, file_index, download_dir, task_id)
        
        # 保存任务对象引用
        for i, t in enumerate(self.transfer_tasks):
            if t["id"] == task_id:
                self.transfer_tasks[i]["threaded_task"] = task
                break
        
        self.active_tasks[task_id] = task
        
        task.signals.progress.connect(lambda p, tid=task_id: (
            self.status.showMessage(f"下载进度: {p}%", 2000),
            self.update_transfer_task(tid, p, "下载中")
        ))
        def on_task_finished(tid):
            if tid in self.active_tasks:
                del self.active_tasks[tid]
        
        task.signals.result.connect(lambda r, tid=task_id: (
            self.status.showMessage("下载完成: " + str(r), 5000),
            self.update_transfer_task(tid, 100, "已完成"),
            on_task_finished(tid)
        ))
        task.signals.error.connect(lambda e, tid=task_id: (
            self._show_error("下载失败: " + e),
            self.update_transfer_task(tid, 0, "失败"),
            on_task_finished(tid)
        ))
        task.signals.finished.connect(lambda tid=task_id: on_task_finished(tid))
        self.threadpool.start(task)

    def _task_get_download_and_stream(self, file_index, download_dir, task_id, signals=None, task=None):
        file_detail = self.pan.list[file_index]
        if file_detail["Type"] == 1:
            redirect_url = self.pan.link_by_fileDetail(file_detail, showlink=False)
        else:
            redirect_url = self.pan.link_by_number(file_index, showlink=False)
        if isinstance(redirect_url, int):
            raise RuntimeError("获取下载链接失败，返回码: " + str(redirect_url))
        if file_detail["Type"] == 1:
            fname = file_detail["FileName"] + ".zip"
        else:
            fname = file_detail["FileName"]
        out_path = os.path.join(download_dir, fname)
        temp = out_path + ".123pan"

        # 保存文件路径到任务对象
        for i, t in enumerate(self.transfer_tasks):
            if t["id"] == task_id:
                self.transfer_tasks[i]["file_path"] = temp
                break

        if os.path.exists(out_path):
            reply = QtWidgets.QMessageBox.question(None, "文件已存在", f"{fname} 已存在，是否覆盖？", QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if reply == QtWidgets.QMessageBox.StandardButton.No:
                return "已取消"

        # 尝试获取头信息，判断是否支持 Range
        total = 0
        accept_ranges = False
        try:
            head = requests.head(redirect_url, allow_redirects=True, timeout=30)
            head.raise_for_status()
            total = int(head.headers.get("Content-Length", 0) or 0)
            accept_ranges = head.headers.get("Accept-Ranges", "").lower() == "bytes"
        except Exception:
            # 有些链接不支持 HEAD，使用 GET 获取 headers
            try:
                with requests.get(redirect_url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length", 0) or 0)
                    accept_ranges = r.headers.get("Accept-Ranges", "").lower() == "bytes"
            except Exception:
                total = 0
                accept_ranges = False

        # 如果支持分片并且文件较大，则采用多线程分片下载
        try:
            if accept_ranges and total and total > 1024 * 1024 * 2:
                # 计算分片数（最多 8 片）
                num_threads = min(8, max(1, int(total / (5 * 1024 * 1024))))
                part_size = total // num_threads
                parts = []
                downloaded = [0]
                dl_lock = threading.Lock()

                def download_range(start, end, index):
                    part_path = f"{temp}.part{index}"
                    headers = {"Range": f"bytes={start}-{end}"}
                    try:
                        with requests.get(redirect_url, headers=headers, stream=True, timeout=30) as r:
                            r.raise_for_status()
                            with open(part_path, "wb") as pf:
                                for chunk in r.iter_content(chunk_size=8192):
                                    # 支持暂停/继续
                                    if task:
                                        # wait 如果被暂停，会在这里阻塞
                                        try:
                                            task._pause_event.wait()
                                        except Exception:
                                            pass
                                        if task.is_cancelled:
                                            return False
                                    if chunk:
                                        pf.write(chunk)
                                        with dl_lock:
                                            downloaded[0] += len(chunk)
                                            if total and signals:
                                                signals.progress.emit(int(downloaded[0] * 100 / total))
                        return True
                    except Exception:
                        # 出错时确保部分文件被删除
                        if os.path.exists(part_path):
                            try:
                                os.remove(part_path)
                            except Exception:
                                pass
                        return False

                # 提交分片任务
                futures = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as exe:
                    for i in range(num_threads):
                        start = i * part_size
                        end = (start + part_size - 1) if i < num_threads - 1 else (total - 1)
                        futures.append(exe.submit(download_range, start, end, i))

                    # 等待完成
                    ok = True
                    for f in concurrent.futures.as_completed(futures):
                        if not f.result():
                            ok = False
                            break

                if not ok:
                    # 清理部分文件
                    for i in range(num_threads):
                        p = f"{temp}.part{i}"
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                    raise RuntimeError("分片下载失败")
                if task and task.is_cancelled:
                    for i in range(num_threads):
                        p = f"{temp}.part{i}"
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                    return "已取消"

                # 合并部分文件
                with open(temp, "wb") as out_f:
                    for i in range(num_threads):
                        p = f"{temp}.part{i}"
                        with open(p, "rb") as pf:
                            while True:
                                chunk = pf.read(8192)
                                if not chunk:
                                    break
                                out_f.write(chunk)
                        try:
                            os.remove(p)
                        except Exception:
                            pass

                if task and task.is_cancelled:
                    if os.path.exists(temp):
                        os.remove(temp)
                    return "已取消"
                os.replace(temp, out_path)
                return out_path
            else:
                # 单线程流式下载，支持暂停/取消
                with requests.get(redirect_url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    done = 0
                    with open(temp, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if task:
                                try:
                                    task._pause_event.wait()
                                except Exception:
                                    pass
                                if task.is_cancelled:
                                    f.close()
                                    if os.path.exists(temp):
                                        os.remove(temp)
                                    return "已取消"
                            if chunk:
                                f.write(chunk)
                                done += len(chunk)
                                if total and signals:
                                    signals.progress.emit(int(done * 100 / total))
                if task and task.is_cancelled:
                    if os.path.exists(temp):
                        os.remove(temp)
                    return "已取消"
                os.replace(temp, out_path)
                return out_path
        except Exception as e:
            # 如果发生异常，删除临时文件并抛出
            if os.path.exists(temp):
                try:
                    os.remove(temp)
                except Exception:
                    pass
            raise

    def on_showlink(self):
        file_index, file_detail = self.get_selected_detail()
        if file_detail is None:
            return
        try:
            # 直接调用获取链接，不使用线程，避免参数传递问题
            url = self._task_get_link(file_index)
            self._after_get_link(url)
        except Exception as e:
            self._show_error(f"获取链接失败: {str(e)}")

    def _task_get_link(self, file_index, signals=None, task=None):
        try:
            url = self.pan.link_by_number(file_index, showlink=False)
            return url
        except Exception as e:
            return f"获取链接失败: {str(e)}"

    def _after_get_link(self, url):
        if isinstance(url, int) or (isinstance(url, str) and url.startswith("获取链接失败")):
            error_msg = str(url) if isinstance(url, str) else ("获取链接失败，返回码: " + str(url))
            self._show_error(error_msg)
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("下载链接")
        dlg.resize(700, 140)
        v = QtWidgets.QVBoxLayout(dlg)
        te = QtWidgets.QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(url)
        v.addWidget(te)
        h = QtWidgets.QHBoxLayout()
        btn_copy = QtWidgets.QPushButton("复制到剪贴板")
        btn_copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(url))
        btn_close = QtWidgets.QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        h.addStretch()
        h.addWidget(btn_copy)
        h.addWidget(btn_close)
        v.addLayout(h)
        dlg.exec()

    def on_upload(self):
        if not self.pan:
            QtWidgets.QMessageBox.information(self, "提示", "请先登录。")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择要上传的文件", os.path.expanduser("~"))
        if not path:
            return
        fname = os.path.basename(path)
        file_size = os.path.getsize(path)
        same = [i for i in self.pan.list if i.get("FileName") == fname]
        dup_choice = 1
        if same:
            text, ok = QtWidgets.QInputDialog.getText(self, "同名文件", "检测到同名文件，输入行为：1 覆盖；2 保留两者；0 取消（默认1）", text="1")
            if not ok:
                return
            if text.strip() not in ("0", "1", "2"):
                QtWidgets.QMessageBox.information(self, "提示", "无效的选择，已取消")
                return
            if text.strip() == "0":
                return
            dup_choice = int(text.strip())
        
        # 添加传输任务
        task_id = self.add_transfer_task("上传", fname, file_size)
        
        task = ThreadedTask(self._task_upload_file, path, dup_choice, task_id)
        
        # 保存任务对象引用
        for i, t in enumerate(self.transfer_tasks):
            if t["id"] == task_id:
                self.transfer_tasks[i]["threaded_task"] = task
                break
        
        self.active_tasks[task_id] = task
        
        def on_task_finished(tid):
            if tid in self.active_tasks:
                del self.active_tasks[tid]
        
        task.signals.progress.connect(lambda p, tid=task_id: (
            self.status.showMessage(f"上传进度: {p}%", 2000),
            self.update_transfer_task(tid, p, "上传中")
        ))
        task.signals.result.connect(lambda r, tid=task_id: (
            self.status.showMessage("上传完成", 3000),
            self.update_transfer_task(tid, 100, "已完成"),
            self.refresh_file_list(reset_page=True),
            on_task_finished(tid)
        ))
        task.signals.error.connect(lambda e, tid=task_id: (
            self._show_error("上传失败: " + e),
            self.update_transfer_task(tid, 0, "失败"),
            on_task_finished(tid)
        ))
        task.signals.finished.connect(lambda tid=task_id: on_task_finished(tid))
        self.threadpool.start(task)

    def _task_upload_file(self, file_path, dup_choice, task_id, signals=None, task=None):
        file_path = file_path.replace('"', "").replace("\\", "/")
        file_name = os.path.basename(file_path)
        if not os.path.exists(file_path):
            raise RuntimeError("文件不存在")
        if os.path.isdir(file_path):
            raise RuntimeError("不支持文件夹上传")
        fsize = os.path.getsize(file_path)
        
        # 检查是否被取消
        if task and task.is_cancelled:
            return "已取消"
        
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                data = f.read(64 * 1024)
                if not data:
                    break
                md5.update(data)
                # 检查是否被取消
                if task and task.is_cancelled:
                    return "已取消"
        readable_hash = md5.hexdigest()
        
        # 检查是否被取消
        if task and task.is_cancelled:
            return "已取消"
        list_up_request = {
            "driveId": 0,
            "etag": readable_hash,
            "fileName": file_name,
            "parentFileId": self.pan.parent_file_id,
            "size": fsize,
            "type": 0,
            "duplicate": 0,
        }
        url = "https://www.123pan.com/b/api/file/upload_request"
        headers = self.pan.header_logined.copy()
        res = requests.post(url, headers=headers, data=list_up_request, timeout=30)
        res_json = res.json()
        code = res_json.get("code", -1)
        if code == 5060:
            list_up_request["duplicate"] = dup_choice
            res = requests.post(url, headers=headers, data=json.dumps(list_up_request), timeout=30)
            res_json = res.json()
            code = res_json.get("code", -1)
        if code != 0:
            raise RuntimeError("上传请求失败: " + json.dumps(res_json, ensure_ascii=False))
        data = res_json["data"]
        if data.get("Reuse"):
            return "复用上传成功"
        bucket = data["Bucket"]
        storage_node = data["StorageNode"]
        upload_key = data["Key"]
        upload_id = data["UploadId"]
        up_file_id = data["FileId"]
        block_size = 5242880
        total_sent = 0
        part_number = 1
        with open(file_path, "rb") as f:
            while True:
                block = f.read(block_size)
                if not block:
                    break
                get_link_data = {
                    "bucket": bucket,
                    "key": upload_key,
                    "partNumberEnd": part_number + 1,
                    "partNumberStart": part_number,
                    "uploadId": upload_id,
                    "StorageNode": storage_node,
                }
                get_link_url = "https://www.123pan.com/b/api/file/s3_repare_upload_parts_batch"
                get_link_res = requests.post(get_link_url, headers=headers, data=json.dumps(get_link_data), timeout=30)
                get_link_res_json = get_link_res.json()
                if get_link_res_json.get("code", -1) != 0:
                    raise RuntimeError("获取上传链接失败: " + json.dumps(get_link_res_json, ensure_ascii=False))
                upload_url = get_link_res_json["data"]["presignedUrls"][str(part_number)]
                requests.put(upload_url, data=block, timeout=60)
                total_sent += len(block)
                if signals and fsize:
                    signals.progress.emit(int(total_sent * 100 / fsize))
                part_number += 1
        uploaded_list_url = "https://www.123pan.com/b/api/file/s3_list_upload_parts"
        uploaded_comp_data = {"bucket": bucket, "key": upload_key, "uploadId": upload_id, "storageNode": storage_node}
        requests.post(uploaded_list_url, headers=headers, data=json.dumps(uploaded_comp_data), timeout=30)
        compmultipart_up_url = "https://www.123pan.com/b/api/file/s3_complete_multipart_upload"
        requests.post(compmultipart_up_url, headers=headers, data=json.dumps(uploaded_comp_data), timeout=30)
        if fsize > 64 * 1024 * 1024:
            time.sleep(3)
        close_up_session_url = "https://www.123pan.com/b/api/file/upload_complete"
        close_up_session_data = {"fileId": up_file_id}
        close_res = requests.post(close_up_session_url, headers=headers, data=json.dumps(close_up_session_data), timeout=30)
        cr = close_res.json()
        if cr.get("code", -1) != 0:
            raise RuntimeError("上传完成确认失败: " + json.dumps(cr, ensure_ascii=False))
        return up_file_id

    def on_mkdir(self):
        if not self.pan:
            QtWidgets.QMessageBox.information(self, "提示", "请先登录。")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "新建文件夹", "请输入文件夹名称：")
        if not ok or not name.strip():
            return
        res = self.pan.mkdir(name.strip(), remakedir=False)
        self.status.showMessage("创建完成", 3000)
        self.refresh_file_list(reset_page=True)

    def on_delete(self):
        file_index, file_detail = self.get_selected_detail()
        if file_detail is None:
            return
        r = QtWidgets.QMessageBox.question(self, "删除确认", f"确认将 '{file_detail['FileName']}' 删除？", QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if r == QtWidgets.QMessageBox.StandardButton.No:
            return
        try:
            self.pan.delete_file(file_index, by_num=True, operation=True)
            self.status.showMessage("删除请求已发送", 3000)
            self.refresh_file_list(reset_page=True)
        except Exception as e:
            self._show_error("删除失败: " + str(e))

    def on_share(self):
        file_index, file_detail = self.get_selected_detail()
        if file_detail is None:
            return
        pwd, ok = QtWidgets.QInputDialog.getText(self, "分享", "提取码（留空则没有提取码）：")
        if not ok:
            return
        file_id_list = str(file_detail["FileId"])
        data = {
            "driveId": 0,
            "expiration": "2099-12-12T08:00:00+08:00",
            "fileIdList": file_id_list,
            "shareName": "123云盘分享",
            "sharePwd": pwd or "",
            "event": "shareCreate"
        }
        headers = self.pan.header_logined.copy()
        try:
            r = requests.post("https://www.123pan.com/a/api/share/create", headers=headers, data=json.dumps(data), timeout=30)
            jr = r.json()
            if jr.get("code", -1) != 0:
                self._show_error("分享失败: " + jr.get("message", str(jr)))
                return
            share_key = jr["data"]["ShareKey"]
            share_url = "https://www.123pan.com/s/" + share_key
            QtWidgets.QMessageBox.information(self, "分享链接", f"{share_url}\n提取码：{pwd or '(无)'}")
        except Exception as e:
            self._show_error("分享异常: " + str(e))

    def _show_error(self, msg):
        QtWidgets.QMessageBox.critical(self, "错误", msg)
        self.status.showMessage(msg, 8000)

    def get_theme_color(self, color_key):
        """获取当前主题的颜色"""
        mode = 'dark' if self.theme_manager.is_dark_mode else 'light'
        return self.theme_colors[mode].get(color_key, '#000000')
    
    def get_sidebar_button_style(self, is_active=True):
        """生成侧边栏按钮的样式表"""
        if is_active:
            # 活跃按钮（文件页）
            bg_color = self.get_theme_color('accent')
            text_color = "#ffffff"
            border = "none"
        else:
            # 非活跃按钮（传输页等）
            if self.theme_manager.is_dark_mode:
                bg_color = "#414559"
                text_color = "#cdd6f4"
                border = "1px solid #585b70"
            else:
                bg_color = "#e8edf5"
                text_color = "#4c4f69"
                border = "1px solid #bcc0cc"
        
        return (
            f"font-size: 13px; text-align: center; font-weight: 500; "
            f"background-color: {bg_color}; "
            f"color: {text_color}; "
            f"border-radius: 16px; "
            f"border: {border}; "
            f"padding: 8px; "
            f"line-height: 1.4;"
        )
    
    def on_theme_changed(self):
        """当主题改变时的回调"""
        # 重新应用侧边栏样式
        sidebar_bg = "#fafbfc" if not self.theme_manager.is_dark_mode else "#181825"
        sidebar_border = "#acb0be" if not self.theme_manager.is_dark_mode else "#313244"
        self.sidebar.setStyleSheet(
            f"background-color: {sidebar_bg};"
            f"border-right: 1px solid {sidebar_border};"
            "border-radius: 0;"
        )
        
        # 重新应用侧边栏标题颜色
        if hasattr(self, 'sidebar_title'):
            title_color = "#2d3749" if not self.theme_manager.is_dark_mode else "#cdd6f4"
            self.sidebar_title.setStyleSheet(
                f"font-size: 18px; font-weight: bold; color: {title_color}; margin-bottom: 16px; "
                "padding: 8px 0;"
            )
        
        # 重新应用侧边栏按钮样式
        if hasattr(self, 'btn_files'):
            self.btn_files.setStyleSheet(self.get_sidebar_button_style(is_active=True))
        if hasattr(self, 'btn_transfer'):
            self.btn_transfer.setStyleSheet(self.get_sidebar_button_style(is_active=False))
    
    def closeEvent(self, event):
        # 停止所有计时器，防止线程冲突
        try:
            if hasattr(self, 'spinner_timer') and self.spinner_timer.isActive():
                self.spinner_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, 'theme_timer') and self.theme_timer.isActive():
                self.theme_timer.stop()
        except Exception:
            pass
        try:
            if self.pan and getattr(self.pan, "user_name", "") and getattr(self.pan, "password", ""):
                self.pan.save_file()
        except Exception:
            pass
        event.accept()

    def on_pause_clicked(self, task):
        if task.is_paused:
            task.resume()
        else:
            task.pause()

    def on_cancel_clicked(self, task_id):
        if task_id in self.active_tasks:
            self.active_tasks[task_id].cancel()

    def toggle_task_pause(self, task_id, button):
        """处理暂停和恢复逻辑"""
        task = self.active_tasks.get(task_id)
        if not task: return
        
        if task.is_paused:
            task.resume()
            button.setText("暂停")
            button.setStyleSheet(button.styleSheet().replace("#f9e2af", self.get_theme_color('accent')))
        else:
            task.pause()
            button.setText("恢复")
            # 变成警告色（黄色）
            button.setStyleSheet(button.styleSheet().replace(self.get_theme_color('accent'), "#f9e2af"))
            self.update_transfer_task(task_id, None, "已暂停")

    def cancel_task(self, task_id):
        """取消任务"""
        task = self.active_tasks.get(task_id)
        if task:
            task.cancel()
            self.update_transfer_task(task_id, 0, "已取消")
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]