import random
import uuid
from pathlib import Path

import requests

from ..api.session import NetSession
from ..service.auth_service import AuthService
from ..service.download_service import DownloadService
from ..service.file_service import FileService
from ..service.upload_service import UploadService
from .const import all_device_type, all_os_versions, VERSION
from .log import get_logger

logger = get_logger(__name__)


class Pan123:
    """123云盘API客户端类（向后兼容包装层）。

    内部使用服务类处理具体业务逻辑，保持与旧版代码 100% 兼容的公开接口。
    """

    def __init__(
        self,
        readfile=True,
        user_name="",
        password="",
        authorization="",
        input_pwd=False,
    ):
        self._session = NetSession()

        self._auth = AuthService(self._session)
        self._file = FileService(self._session)
        self._download = DownloadService(self._session)
        self._upload = UploadService(self._session)

        self.devicetype = random.choice(all_device_type)
        self.osversion = random.choice(all_os_versions)
        self.loginuuid = uuid.uuid4().hex

        # 目录浏览状态
        self.list = []
        self.total = 0
        self.all_file = False
        self.file_page = 0
        self.parent_file_id = 0

        if readfile:
            self._auth.read_ini(user_name, password, input_pwd, authorization)
            self._sync_from_auth()
        else:
            if user_name == "" or password == "":
                raise Exception("用户名或密码为空")
            self._auth.user_name = user_name
            self._auth.password = password
            self._auth.authorization = authorization
            self._sync_from_auth()

        self._sync_to_session()
        res_code_getdir = self.get_dir()[0]
        if res_code_getdir != 0:
            self.login()
            self.get_dir()

    def _sync_to_session(self):
        self._auth.devicetype = self.devicetype
        self._auth.osversion = self.osversion
        self._auth.loginuuid = self.loginuuid
        self._auth.user_name = self.user_name
        self._auth.password = self.password
        self._auth.authorization = self.authorization
        self._auth.sync_to_session()

    def _sync_from_auth(self):
        self.devicetype = self._auth.devicetype
        self.osversion = self._auth.osversion
        self.loginuuid = self._auth.loginuuid
        self.user_name = self._auth.user_name
        self.password = self._auth.password
        self.authorization = self._auth.authorization

    def login(self):
        logger.info("Pan123.login: user=%s", self.user_name)
        self._auth.user_name = self.user_name
        self._auth.password = self.password
        code = self._auth.login()
        if code == 200:
            self.authorization = self._auth.authorization
            self.save_file()
        return code

    def save_file(self):
        self._auth.devicetype = self.devicetype
        self._auth.osversion = self.osversion
        self._auth.loginuuid = self.loginuuid
        self._auth.user_name = self.user_name
        self._auth.password = self.password
        self._auth.authorization = self.authorization
        self._auth.save_file()

    def get_dir(self, save=True):
        return self.get_dir_by_id(self.parent_file_id, save)

    def get_dir_by_id(self, file_id, save=True, all=False, limit=100):
        code, items, total, all_file, _ = self._file.get_dir_by_id(
            file_id, page=self.file_page, list_len=len(self.list),
            all=all, limit=limit,
        )
        if code == 2:
            logger.warning("token 过期，正在尝试重新登录")
            login_code = self.login()
            if login_code == 200:
                return self.get_dir_by_id(file_id, save, all, limit)
            logger.error("重新登录失败")
            return code, []
        if code != 0:
            logger.error(
                "获取文件列表失败: file_id=%s, code=%s",
                file_id, code,
            )
            return code, []

        self.total = total
        self.all_file = all_file
        self.file_page += 1
        if save:
            self.list = self.list + items

        return 0, items

    def link_by_fileDetail(self, file_detail, showlink=True):
        return self._download.link_by_fileDetail(file_detail, showlink)

    def delete_file(self, file, by_num=True, operation=True):
        self._file.delete_file(self.list, file, by_num, operation)

    def rename_file(self, file_id, new_name):
        return self._file.rename_file(file_id, new_name)

    def share(self, file_id_list, share_pwd=""):
        return self._file.share(file_id_list, share_pwd)

    def up_load(self, file_path):
        return self._upload.up_load(file_path, self.parent_file_id)

    def mkdir(self, dirname, remakedir=False):
        file_id, err = self._file.mkdir(dirname, self.list, self.parent_file_id, remakedir)
        if file_id is not None:
            self.get_dir()
        return file_id

    # ---- Session 配置（门面方法） ----

    def set_download_multi_thread(self, enabled):
        self._download.set_multi_thread(enabled)

    def set_download_speed_limit(self, kbps):
        self._download.set_download_speed_limit(kbps)

    def set_upload_speed_limit(self, kbps):
        self._upload.set_upload_speed_limit(kbps)

    def set_download_proxy(self, proxy_type, host, port, username="", password=""):
        self._download.set_proxy(proxy_type, host, port, username, password)

    def clear_download_proxy(self):
        self._download.clear_proxy()

    def download_file(self, url, file_path, file_size, progress_callback=None):
        return self._download.download_file(url, file_path, file_size, progress_callback)


# ==================== 工具函数和任务管理模块 ====================


def format_file_size(size):
    """格式化文件大小"""
    units = ["B", "KB", "MB", "GB", "TB"]
    for i in range(len(units)):
        if size < 1024.0:
            return f"{round(size, 2)} {units[i]}"
        size /= 1024.0
    return f"{size:.2f} {units[-1]}"


class FileDataManager:
    """文件数据处理器 - 处理与文件相关的业务逻辑，不涉及UI"""

    @staticmethod
    def get_file_type_name(file_type):
        """根据文件类型返回类型名称"""
        return "文件夹" if file_type == 1 else "文件"

    @staticmethod
    def format_file_size_value(size):
        """格式化文件大小（工具函数别名）"""
        return format_file_size(size)

    @staticmethod
    def get_file_extension(filename):
        """获取文件扩展名"""
        return Path(filename).suffix.lower()

    @staticmethod
    def validate_file_exists(file_path):
        """验证文件是否存在"""
        return Path(file_path).is_file()

    @staticmethod
    def is_duplicate_filename(pan_instance, filename):
        """检查是否存在同名文件"""
        return any(item.get("FileName") == filename for item in pan_instance.list)


def check_version():
    """获取版本信息"""
    try:
        response = requests.get(
            "https://api.github.com/repos/123pannextgen/123pan/releases/latest",
            timeout=5,
        )
        response.raise_for_status()
        vesion_info = response.json()
        version = "v" + str(VERSION)
        return vesion_info.get("name") == version
    except Exception as e:
        logger.error("获取版本信息出错: %s", e)
        return False
