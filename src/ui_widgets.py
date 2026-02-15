# https://github.com/123panNextGen/123pan
# src/ui_widgets.py

from PyQt6 import QtCore, QtWidgets
import os
from config import ConfigManager


class SidebarButton(QtWidgets.QPushButton):
    """侧栏按钮，支持hover事件"""
    entered = QtCore.pyqtSignal()
    left = QtCore.pyqtSignal()
    
    def enterEvent(self, event):
        """鼠标进入事件"""
        super().enterEvent(event)
        self.entered.emit()
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        super().leaveEvent(event)
        self.left.emit()


class SettingsDialog(QtWidgets.QDialog):
    """设置对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(500, 200)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # 下载设置组
        download_group = QtWidgets.QGroupBox("下载设置")
        download_layout = QtWidgets.QVBoxLayout()
        
        # 默认下载路径
        path_layout = QtWidgets.QHBoxLayout()
        path_layout.addWidget(QtWidgets.QLabel("默认下载路径:"))
        self.le_download_path = QtWidgets.QLineEdit()
        self.le_download_path.setReadOnly(True)
        path_layout.addWidget(self.le_download_path, 1)
        self.btn_browse = QtWidgets.QPushButton("浏览...")
        self.btn_browse.clicked.connect(self.browse_download_path)
        path_layout.addWidget(self.btn_browse)
        download_layout.addLayout(path_layout)
        
        # 下载前询问
        self.cb_ask_location = QtWidgets.QCheckBox("每次下载前询问保存位置")
        download_layout.addWidget(self.cb_ask_location)
        
        download_group.setLayout(download_layout)
        layout.addWidget(download_group)
        
        # 按钮
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        self.btn_save = QtWidgets.QPushButton("保存")
        self.btn_cancel = QtWidgets.QPushButton("取消")
        button_layout.addWidget(self.btn_save)
        button_layout.addWidget(self.btn_cancel)
        layout.addLayout(button_layout)
        
        # 连接信号
        self.btn_save.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
        # 加载当前设置
        self.load_settings()
    
    def load_settings(self):
        """加载当前设置"""
        default_path = ConfigManager.get_setting("defaultDownloadPath", 
                                                os.path.join(os.path.expanduser("~"), "Downloads"))
        ask_location = ConfigManager.get_setting("askDownloadLocation", True)
        
        self.le_download_path.setText(default_path)
        self.cb_ask_location.setChecked(ask_location)
    
    def browse_download_path(self):
        """浏览下载路径"""
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择默认下载路径", self.le_download_path.text()
        )
        if path:
            self.le_download_path.setText(path)
    
    def get_settings(self):
        """获取设置的参数"""
        return {
            "defaultDownloadPath": self.le_download_path.text(),
            "askDownloadLocation": self.cb_ask_location.isChecked()
        }


class LoginDialog(QtWidgets.QDialog):
    """登录对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录123云盘")
        self.setModal(True)
        self.resize(420, 150)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.le_user = QtWidgets.QLineEdit()
        self.le_pass = QtWidgets.QLineEdit()
        self.le_pass.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        form.addRow("用户名：", self.le_user)
        form.addRow("密码：", self.le_pass)
        layout.addLayout(form)

        h = QtWidgets.QHBoxLayout()
        h.addStretch()
        self.btn_ok = QtWidgets.QPushButton("登录")
        self.btn_cancel = QtWidgets.QPushButton("取消")
        h.addWidget(self.btn_ok)
        h.addWidget(self.btn_cancel)
        layout.addLayout(h)

        self.btn_ok.clicked.connect(self.on_ok)
        self.btn_cancel.clicked.connect(self.reject)

        self.pan = None
        self.login_error = None

        # 从配置文件中加载用户名
        config = ConfigManager.load_config()
        self.le_user.setText(config.get("userName", ""))

    def on_ok(self):
        """登录处理"""
        from api import Pan123
        
        user = self.le_user.text().strip()
        pwd = self.le_pass.text()
        if not user or not pwd:
            QtWidgets.QMessageBox.information(self, "提示", "请输入用户名和密码。")
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            # 构造123pan并登录
            try:
                self.pan = Pan123(readfile=False, user_name=user, pass_word=pwd, input_pwd=False)
            except Exception:
                self.pan = Pan123(readfile=False, user_name=user, pass_word=pwd, input_pwd=False)
            if not getattr(self.pan, "authorization", None):
                code = self.pan.login()
                if code != 200 and code != 0:
                    self.login_error = f"登录失败，返回码: {code}"
                    QtWidgets.QApplication.restoreOverrideCursor()
                    QtWidgets.QMessageBox.critical(self, "登录失败", self.login_error)
                    return
        except Exception as e:
            self.login_error = str(e)
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(self, "登录异常", "登录时发生异常:\n" + str(e))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        try:
            if hasattr(self.pan, "save_file"):
                self.pan.save_file()
        except Exception:
            pass
        self.accept()

    def get_pan(self):
        """获取登录成功的Pan对象"""
        return self.pan


class AboutDialog(QtWidgets.QDialog):
    """关于对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于123pan")
        self.setModal(True)
        self.resize(450, 350)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # 应用标题
        title = QtWidgets.QLabel("123pan")
        title_font = title.font()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 分隔线
        separator1 = QtWidgets.QFrame()
        separator1.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        layout.addWidget(separator1)
        
        # 版本信息
        version_label = QtWidgets.QLabel("版本: 2.3.1")
        version_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)
        
        # 描述
        description = QtWidgets.QLabel("123pan是一款基于Python开发的高效下载辅助工具，通过模拟安卓客户端协议，帮助用户绕过123云盘的自用下载流量限制，实现无阻碍下载体验。")
        description.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        layout.addWidget(description)
        
        
        # 分隔线
        separator3 = QtWidgets.QFrame()
        separator3.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        layout.addWidget(separator3)
        
        # 项目信息
        project_info = QtWidgets.QLabel(
            "GitHub: https://github.com/123panNextGen/123pan\n"
            "By Qxyz17 xhdndmm \n"
            "Apache License v2.0"
        )
        project_info.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        project_info.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(project_info)
        
        # 关闭按钮
        btn_close = QtWidgets.QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
