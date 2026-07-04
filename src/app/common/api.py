import random
import threading
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

        self.recycle_list = None
        self.list = []
        self.total = 0
        self.parent_file_name_list = []
        self.all_file = False
        self.file_page = 0
        self.file_list = []
        self.dir_list = []
        self.name_dict = {}
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
        self.parent_file_id = 0
        self.parent_file_list = [0]
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

    def show(self):
        self._file.show(len(self.list), self.total, self.all_file)

    def link_by_number(self, file_number, showlink=True):
        file_detail = self.list[file_number]
        return self.link_by_fileDetail(file_detail, showlink)

    def link_by_fileDetail(self, file_detail, showlink=True):
        return self._download.link_by_fileDetail(file_detail, showlink)

    def download(self, file_number, download_path="download"):
        file_detail = self.list[file_number]
        if file_detail["Type"] == 1:
            logger.info("开始下载")
            file_name = file_detail["FileName"] + ".zip"
        else:
            file_name = file_detail["FileName"]

        down_load_url = self.link_by_number(file_number, showlink=False)
        if isinstance(down_load_url, int):
            return
        self._download.download_from_url(down_load_url, file_name, download_path)

    def download_from_url(self, url, file_name, download_path="download"):
        self._download.download_from_url(url, file_name, download_path)

    def get_all_things(self, id):
        self.dir_list.remove(id)
        all_list = self.get_dir_by_id(id, save=False)[1]

        for i in all_list:
            if i["Type"] == 0:
                self.file_list.append(i)
            else:
                self.dir_list.append(i["FileId"])
                self.name_dict[i["FileId"]] = i["FileName"]

        for i in self.dir_list:
            self.get_all_things(i)

    def download_dir(self, file_detail, download_path_root="download"):
        self.name_dict[file_detail["FileId"]] = file_detail["FileName"]
        if file_detail["Type"] != 1:
            logger.warning("不是文件夹")
            return

        all_list = self.get_dir_by_id(
            file_detail["FileId"], save=False, all=True, limit=100
        )[1]
        for i in all_list[::-1]:
            if i["Type"] == 0:
                AbsPath = i["AbsPath"]
                for key, value in self.name_dict.items():
                    AbsPath = AbsPath.replace(str(key), value)
                download_path = download_path_root + AbsPath
                download_path = download_path.replace("/" + str(i["FileId"]), "")
                self.download_from_url(i["DownloadUrl"], i["FileName"], download_path)

            else:
                self.download_dir(i, download_path_root)

    def recycle(self):
        self.recycle_list = self._file.recycle()

    def delete_file(self, file, by_num=True, operation=True):
        self._file.delete_file(self.list, file, by_num, operation)

    def rename_file(self, file_id, new_name):
        return self._file.rename_file(file_id, new_name)

    def share(self, file_id_list, share_pwd=""):
        if not file_id_list:
            raise ValueError("文件ID列表为空")
        data = {
            "driveId": 0,
            "expiration": "2099-12-12T08:00:00+08:00",
            "fileIdList": file_id_list,
            "shareName": "123云盘分享",
            "sharePwd": share_pwd or "",
            "event": "shareCreate",
        }
        share_res = self._session.http.post(
            "https://www.123pan.cn/a/api/share/create",
            json=data,
            timeout=10,
        )
        share_res_json = share_res.json()
        if share_res_json.get("code", -1) != 0:
            raise RuntimeError(f"分享失败: {share_res_json.get('message', '')}")
        share_key = share_res_json["data"]["ShareKey"]
        share_url = "https://www.123pan.cn/s/" + share_key
        return share_url

    def up_load(self, file_path):
        return self._upload.up_load(file_path, self.parent_file_id)

    def cd(self, dir_num):
        if dir_num == "..":
            if len(self.parent_file_list) > 1:
                self.all_file = False
                self.file_page = 0
                self.parent_file_list.pop()
                self.parent_file_id = self.parent_file_list[-1]
                self.list = []
                self.parent_file_name_list.pop()
                self.get_dir()
            else:
                raise RuntimeError("已经是根目录")
            return
        if dir_num == "/":
            self.all_file = False
            self.file_page = 0
            self.parent_file_id = 0
            self.parent_file_list = [0]
            self.list = []
            self.parent_file_name_list = []
            self.get_dir()
            return
        if not str(dir_num).isdigit():
            raise ValueError("文件夹编号必须是数字")
        dir_num = int(dir_num) - 1
        if dir_num > (len(self.list) - 1) or dir_num < 0:
            raise IndexError("文件夹编号超出范围")
        if self.list[dir_num]["Type"] != 1:
            raise TypeError("选中项不是文件夹")
        self.all_file = False
        self.file_page = 0
        self.parent_file_id = self.list[dir_num]["FileId"]
        self.parent_file_list.append(self.parent_file_id)
        self.parent_file_name_list.append(self.list[dir_num]["FileName"])
        self.list = []
        self.get_dir()

    def cdById(self, file_id):
        self.all_file = False
        self.file_page = 0
        self.list = []
        self.parent_file_id = file_id
        self.parent_file_list.append(self.parent_file_id)
        self.get_dir()
        self.show()

    def read_ini(self, user_name="", password="", input_pwd=False, authorization=""):
        self._auth.read_ini(user_name, password, input_pwd, authorization)
        self._sync_from_auth()

    def mkdir(self, dirname, remakedir=False):
        file_id, err = self._file.mkdir(dirname, self.list, self.parent_file_id, remakedir)
        if file_id is not None:
            self.get_dir()
        return file_id

    @staticmethod
    def _compute_file_md5(file_path):
        return UploadService.compute_file_md5(file_path)

    def upload_file_stream(
        self, file_path, dup_choice=1, task_id=None, signals=None, task=None
    ):
        return self._upload.upload_file_stream(
            file_path, self.parent_file_id, dup_choice, signals=signals, task=task
        )


# ==================== 工具函数和任务管理模块 ====================


def format_file_size(size):
    """格式化文件大小"""
    units = ["B", "KB", "MB", "GB", "TB"]
    for i in range(len(units)):
        if size < 1024.0:
            return f"{round(size, 2)} {units[i]}"
        size /= 1024.0
    return f"{size:.2f} {units[-1]}"


class TransferTask:
    """传输任务的数据模型"""

    def __init__(self, task_id, task_type, name, size):
        self.id = task_id
        self.type = task_type
        self.name = name
        self.size = size
        self.progress = 0
        self.status = "等待中"
        self.file_path = None
        self.threaded_task = None
        self.is_paused = False

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "size": self.size,
            "progress": self.progress,
            "status": self.status,
            "file_path": self.file_path,
        }


class TransferTaskManager:
    """传输任务管理器 - 仅处理业务逻辑，不涉及UI"""

    def __init__(self):
        self.tasks = {}
        self.next_task_id = 0
        self.lock = threading.Lock()

    def create_task(self, task_type, name, size):
        """创建新任务并返回task_id"""
        with self.lock:
            task_id = self.next_task_id
            self.next_task_id += 1
            self.tasks[task_id] = TransferTask(task_id, task_type, name, size)
        return task_id

    def get_task(self, task_id):
        """获取指定任务"""
        return self.tasks.get(task_id)

    def update_task_progress(self, task_id, progress):
        """更新任务进度"""
        task = self.get_task(task_id)
        if task:
            task.progress = max(0, min(100, progress))

    def update_task_status(self, task_id, status):
        """更新任务状态"""
        task = self.get_task(task_id)
        if task:
            task.status = status

    def update_task(self, task_id, progress=None, status=None):
        """更新任务（进度和/或状态）"""
        task = self.get_task(task_id)
        if task:
            if progress is not None:
                task.progress = max(0, min(100, progress))
            if status is not None:
                task.status = status

    def cancel_task(self, task_id):
        """取消任务"""
        task = self.get_task(task_id)
        if task:
            task.status = "已取消"
            if task.threaded_task:
                try:
                    task.threaded_task.cancel()
                except:
                    pass
            return True
        return False

    def pause_task(self, task_id):
        """暂停任务"""
        task = self.get_task(task_id)
        if task and task.threaded_task:
            try:
                task.threaded_task.pause()
                task.status = "已暂停"
                task.is_paused = True
                return True
            except:
                pass
        return False

    def resume_task(self, task_id):
        """恢复任务"""
        task = self.get_task(task_id)
        if task and task.threaded_task:
            try:
                task.threaded_task.resume()
                task.status = "下载中" if task.type == "下载" else "上传中"
                task.is_paused = False
                return True
            except:
                pass
        return False

    def remove_task(self, task_id):
        """移除任务"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False

    def get_all_tasks(self):
        """获取所有任务"""
        return list(self.tasks.values())

    def clear_completed_tasks(self):
        """清除已完成的任务"""
        to_remove = [
            task_id
            for task_id, task in self.tasks.items()
            if task.status in ("已完成", "已取消", "失败")
        ]
        for task_id in to_remove:
            del self.tasks[task_id]


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
