# 123pan-open 项目 API 文档

>[!IMPORTANT]  
>注意：**此文档由AI生成**

本文档总结了项目中的三个核心模块：`log.py`、`config.py` 和 `api.py`。这些模块提供了日志记录、配置管理和 123 云盘 API 交互的功能。

## 1. log.py - 日志模块

### 概述
`log.py` 模块负责项目的日志记录功能。它使用 Python 的 `logging` 模块来配置日志输出到文件和控制台。

### 主要功能
- 根据操作系统确定配置文件目录（Windows 使用 `APPDATA`，其他使用 `~/.config`）。
- 定义日志文件路径：`{CONFIG_DIR}/123pan-open.log`。
- 提供 `get_logger(name)` 函数来获取配置好的日志记录器。

### 使用示例
```python
from .log import get_logger
logger = get_logger(__name__)
logger.info("这是一条信息日志")
```

## 2. config.py - 配置模块

### 概述
`config.py` 模块处理应用程序的配置管理，包括 UI 主题、文件夹路径、更新设置等。它使用 `qfluentwidgets` 的 `QConfig` 来管理配置项。

### 主要类和功能
- `isWin11()`: 检查是否为 Windows 11。
- `Config` 类：继承自 `QConfig`，定义了多个配置项，如：
  - `musicFolders`: 本地音乐文件夹列表。
  - `downloadFolder`: 下载文件夹。
  - `micaEnabled`: Mica 效果启用状态。
  - `dpiScale`: DPI 缩放。
  - `blurRadius`: 模糊半径。
  - `checkUpdateAtStartUp`: 启动时检查更新。
- `ConfigManager` 类：提供静态方法来加载、保存和获取配置。
  - `load_config()`: 从 JSON 文件加载配置。
  - `save_config(config)`: 保存配置到 JSON 文件。
  - `get_setting(key, default)`: 获取特定设置。
- 常量：`YEAR`、`ABOUT_URL`、`VERSION`。
- 列表：`all_device_type`（设备类型列表）、`all_os_versions`（操作系统版本列表）。

### 使用示例
```python
from .config import ConfigManager
config = ConfigManager.load_config()
username = config.get("userName", "")
```

## 3. api.py - 123 云盘 API 客户端模块

### 概述
`api.py` 模块是与 123 云盘 API 交互的核心模块。它提供了登录、文件列表获取、下载、上传、分享等功能。

### 主要类
#### Pan123 类
123 云盘 API 客户端类，封装了所有 API 操作。

##### 初始化
- `__init__(readfile=True, user_name="", pass_word="", authorization="", input_pwd=False)`: 初始化客户端，自动登录并获取目录。

##### 主要方法
- `login()`: 用户登录，获取授权令牌。
- `save_file()`: 将账户信息保存到配置文件。
- `get_dir(save=True)`: 获取当前目录文件列表。
- `get_dir_by_id(file_id, save=True, all=False, limit=100)`: 按文件夹 ID 获取文件列表，支持分页。
- `show()`: 显示文件列表信息。
- `link_by_number(file_number, showlink=True)`: 按编号获取下载链接。
- `link_by_fileDetail(file_detail, showlink=True)`: 按文件详情获取下载链接。
- `get_all_things(id)`: 获取文件夹内所有内容。
- `recycle()`: 获取回收站列表。
- `delete_file(file, by_num=True, operation=True)`: 删除或恢复文件。
- `share(file_id_list, share_pwd="")`: 分享文件。
- `up_load(file_path)`: 上传文件。
- `cd(dir_num)`: 进入文件夹。
- `cdById(file_id)`: 按 ID 进入文件夹。
- `read_ini(user_name, pass_word, input_pwd, authorization)`: 从配置文件读取账号信息。
- `mkdir(dirname, remakedir=False)`: 创建文件夹。
- `upload_file_stream(file_path, dup_choice=1, task_id=None, signals=None, task=None)`: 流式上传文件，支持进度和取消。

#### TransferTask 类
传输任务的数据模型，包含任务 ID、类型、名称、大小、进度、状态等属性。

#### TransferTaskManager 类
传输任务管理器，处理任务的创建、更新、取消、暂停、恢复等操作。

#### FileDataManager 类
文件数据处理器，提供文件类型判断、大小格式化、扩展名获取等工具方法。

### 工具函数
- `format_file_size(size)`: 格式化文件大小显示。

### 使用示例
```python
from .api import Pan123
pan = Pan123(user_name="your_username", pass_word="your_password")
pan.get_dir()
file_detail = pan.list[0]
url = pan.link_by_fileDetail(file_detail)
```

---

## 详细 API 调用文档

### Pan123 类 API 调用指南

`Pan123` 类是 123 云盘 API 的主要接口类。以下是其主要方法的详细调用说明，包括参数、返回值、示例和可能的异常。

#### 初始化
```python
pan = Pan123(readfile=True, user_name="", pass_word="", authorization="", input_pwd=False)
```
- **参数**:
  - `readfile`: bool, 是否从配置文件读取账号信息。默认 True。
  - `user_name`: str, 用户名。如果 `readfile=True`，可为空。
  - `pass_word`: str, 密码。如果 `readfile=True`，可为空。
  - `authorization`: str, 授权令牌。如果 `readfile=True`，可为空。
  - `input_pwd`: bool, 是否输入密码。默认 False。
- **返回值**: 无。
- **说明**: 初始化时会自动登录并获取根目录文件列表。如果登录失败，会抛出异常。
- **异常**: 如果用户名或密码为空且无法从配置读取，会抛出 Exception。
- **示例**:
  ```python
  pan = Pan123(user_name="example@123.com", pass_word="password123")
  ```

#### login()
```python
code = pan.login()
```
- **参数**: 无。
- **返回值**: int, 登录状态码（0 表示成功）。
- **说明**: 登录 123 云盘账户并获取授权令牌。成功后更新 `authorization` 属性。
- **异常**: 如果登录失败，返回非 0 码。
- **示例**:
  ```python
  if pan.login() == 0:
      print("登录成功")
  ```

#### save_file()
```python
pan.save_file()
```
- **参数**: 无。
- **返回值**: 无。
- **说明**: 将当前账户信息（用户名、密码、授权令牌、设备信息）保存到配置文件。
- **异常**: 如果保存失败，记录错误日志。
- **示例**:
  ```python
  pan.save_file()
  ```

#### get_dir(save=True)
```python
code, file_list = pan.get_dir(save=True)
```
- **参数**:
  - `save`: bool, 是否保存结果到实例的 `list` 属性。默认 True。
- **返回值**: tuple, (状态码 int, 文件列表 list)。
- **说明**: 获取当前目录的文件列表。内部调用 `get_dir_by_id`。
- **异常**: 如果请求失败，返回非 0 码。
- **示例**:
  ```python
  code, files = pan.get_dir()
  if code == 0:
      print(f"获取到 {len(files)} 个文件")
  ```

#### get_dir_by_id(file_id, save=True, all=False, limit=100)
```python
code, file_list = pan.get_dir_by_id(12345, save=True, all=False, limit=100)
```
- **参数**:
  - `file_id`: int, 文件夹 ID。
  - `save`: bool, 是否保存结果到实例列表。默认 True。
  - `all`: bool, 是否强制获取所有文件（忽略分页）。默认 False。
  - `limit`: int, 每页限制数量。默认 100。
- **返回值**: tuple, (状态码 int, 文件列表 list)。
- **说明**: 按文件夹 ID 获取文件列表，支持分页。如果 `all=True`，会获取所有文件。
- **异常**: 如果请求失败，返回非 0 码。
- **示例**:
  ```python
  code, files = pan.get_dir_by_id(0, all=True)  # 获取根目录所有文件
  ```

#### show()
```python
pan.show()
```
- **参数**: 无。
- **返回值**: 无。
- **说明**: 显示当前文件列表的信息到日志，包括获取的文件数量和总数。
- **异常**: 无。
- **示例**:
  ```python
  pan.show()
  ```

#### link_by_number(file_number, showlink=True)
```python
url = pan.link_by_number(0, showlink=True)
```
- **参数**:
  - `file_number`: int, 文件在列表中的索引（从 0 开始）。
  - `showlink`: bool, 是否在日志中显示链接。默认 True。
- **返回值**: str 或 int, 下载 URL 或错误码。
- **说明**: 获取指定文件的下载链接。
- **异常**: 如果索引超出范围或请求失败，返回错误码。
- **示例**:
  ```python
  url = pan.link_by_number(0)
  if isinstance(url, str):
      print(f"下载链接: {url}")
  ```

#### link_by_fileDetail(file_detail, showlink=True)
```python
url = pan.link_by_fileDetail(file_detail, showlink=True)
```
- **参数**:
  - `file_detail`: dict, 文件详情字典。
  - `showlink`: bool, 是否在日志中显示链接。默认 True。
- **返回值**: str 或 int, 下载 URL 或错误码。
- **说明**: 根据文件详情获取下载链接。支持文件和文件夹（文件夹返回 ZIP 下载链接）。
- **异常**: 如果请求失败，返回错误码。
- **示例**:
  ```python
  file_detail = pan.list[0]
  url = pan.link_by_fileDetail(file_detail)
  ```

#### get_all_things(id)
```python
pan.get_all_things(12345)
```
- **参数**:
  - `id`: int, 文件夹 ID。
- **返回值**: 无。
- **说明**: 递归获取文件夹内所有内容（文件和子文件夹），更新 `file_list` 和 `dir_list`。
- **异常**: 无。
- **示例**:
  ```python
  pan.get_all_things(0)  # 获取根目录所有内容
  ```

#### recycle()
```python
pan.recycle()
```
- **参数**: 无。
- **返回值**: 无。
- **说明**: 获取回收站中的文件列表，存储在 `recycle_list`。
- **异常**: 如果请求失败，记录错误。
- **示例**:
  ```python
  pan.recycle()
  print(pan.recycle_list)
  ```

#### delete_file(file, by_num=True, operation=True)
```python
pan.delete_file(0, by_num=True, operation=True)
```
- **参数**:
  - `file`: int 或 dict, 文件索引或详情。
  - `by_num`: bool, 是否按索引。默认 True。
  - `operation`: bool, True 为删除，False 为恢复。默认 True。
- **返回值**: 无。
- **说明**: 删除或恢复文件。
- **异常**: 如果索引无效或文件不存在，抛出异常。
- **示例**:
  ```python
  pan.delete_file(0)  # 删除第一个文件
  pan.delete_file(0, operation=False)  # 恢复第一个文件
  ```

#### share(file_id_list, share_pwd="")
```python
share_url = pan.share([12345], share_pwd="1234")
```
- **参数**:
  - `file_id_list`: list, 文件 ID 列表。
  - `share_pwd`: str, 分享密码（可选）。
- **返回值**: str, 分享 URL。
- **说明**: 创建文件分享链接。
- **异常**: 如果列表为空或请求失败，抛出异常。
- **示例**:
  ```python
  url = pan.share([pan.list[0]["FileId"]], "password")
  print(url)
  ```

#### up_load(file_path)
```python
file_id = pan.up_load("/path/to/file.txt")
```
- **参数**:
  - `file_path`: str, 文件路径。
- **返回值**: int, 上传文件的 ID。
- **说明**: 上传文件到当前目录。支持分块上传。
- **异常**: 如果文件不存在或上传失败，抛出异常。
- **示例**:
  ```python
  id = pan.up_load("example.txt")
  ```

#### cd(dir_num)
```python
pan.cd(1)  # 进入第一个文件夹
pan.cd("..")  # 返回上级目录
pan.cd("/")  # 返回根目录
```
- **参数**:
  - `dir_num`: int 或 str, 文件夹索引、".." 或 "/"。
- **返回值**: 无。
- **说明**: 导航到指定文件夹。
- **异常**: 如果索引无效或不是文件夹，抛出异常。
- **示例**:
  ```python
  pan.cd(1)
  ```

#### cdById(file_id)
```python
pan.cdById(12345)
```
- **参数**:
  - `file_id`: int, 文件夹 ID。
- **返回值**: 无。
- **说明**: 按 ID 进入文件夹。
- **异常**: 无。
- **示例**:
  ```python
  pan.cdById(12345)
  ```

#### read_ini(user_name, pass_word, input_pwd, authorization)
```python
pan.read_ini("", "", False, "")
```
- **参数**:
  - `user_name`: str, 用户名。
  - `pass_word`: str, 密码。
  - `input_pwd`: bool, 是否输入密码。
  - `authorization`: str, 授权令牌。
- **返回值**: 无。
- **说明**: 从配置文件读取账号信息并设置属性。
- **异常**: 如果无法读取，抛出异常。
- **示例**:
  ```python
  pan.read_ini("user", "pass", False, "token")
  ```

#### mkdir(dirname, remakedir=False)
```python
file_id = pan.mkdir("new_folder", remakedir=False)
```
- **参数**:
  - `dirname`: str, 文件夹名称。
  - `remakedir`: bool, 是否允许重名。默认 False。
- **返回值**: int, 新文件夹的 ID。
- **说明**: 创建新文件夹。
- **异常**: 如果创建失败，记录错误。
- **示例**:
  ```python
  id = pan.mkdir("test")
  ```

#### upload_file_stream(file_path, dup_choice=1, task_id=None, signals=None, task=None)
```python
result = pan.upload_file_stream("/path/to/file.txt", dup_choice=1, task_id=1, signals=signals, task=task)
```
- **参数**:
  - `file_path`: str, 文件路径。
  - `dup_choice`: int, 同名文件处理方式（1=覆盖）。默认 1。
  - `task_id`: int, 任务 ID（可选）。
  - `signals`: object, 信号对象（可选）。
  - `task`: object, 任务对象（可选）。
- **返回值**: int 或 str, 文件 ID 或 "已取消"。
- **说明**: 流式上传文件，支持进度、暂停和取消。
- **异常**: 如果文件不存在或上传失败，抛出异常。
- **示例**:
  ```python
  id = pan.upload_file_stream("file.txt")
  ```

### TransferTaskManager 类 API 调用指南

#### create_task(task_type, name, size)
```python
task_id = manager.create_task("下载", "file.txt", 1024)
```
- **参数**:
  - `task_type`: str, 任务类型（"上传" 或 "下载"）。
  - `name`: str, 文件名。
  - `size`: int, 文件大小。
- **返回值**: int, 任务 ID。

#### update_task_progress(task_id, progress)
```python
manager.update_task_progress(1, 50)
```
- **参数**:
  - `task_id`: int, 任务 ID。
  - `progress`: int, 进度百分比。

#### cancel_task(task_id)
```python
success = manager.cancel_task(1)
```
- **参数**:
  - `task_id`: int, 任务 ID。
- **返回值**: bool, 是否成功。

#### pause_task(task_id)
```python
success = manager.pause_task(1)
```
- **参数**:
  - `task_id`: int, 任务 ID。
- **返回值**: bool, 是否成功。

#### resume_task(task_id)
```python
success = manager.resume_task(1)
```
- **参数**:
  - `task_id`: int, 任务 ID。
- **返回值**: bool, 是否成功。

#### remove_task(task_id)
```python
success = manager.remove_task(1)
```
- **参数**:
  - `task_id`: int, 任务 ID。
- **返回值**: bool, 是否成功。

#### get_all_tasks()
```python
tasks = manager.get_all_tasks()
```
- **返回值**: list, 所有任务对象列表。

#### clear_completed_tasks()
```python
manager.clear_completed_tasks()
```
- **返回值**: 无。

### FileDataManager 类 API 调用指南

#### get_file_type_name(file_type)
```python
type_name = FileDataManager.get_file_type_name(1)  # "文件夹"
```
- **参数**:
  - `file_type`: int, 文件类型（1=文件夹，0=文件）。
- **返回值**: str, 类型名称。

#### format_file_size_value(size)
```python
size_str = FileDataManager.format_file_size_value(1024)  # "1.0 KB"
```
- **参数**:
  - `size`: int, 文件大小（字节）。
- **返回值**: str, 格式化字符串。

#### get_file_extension(filename)
```python
ext = FileDataManager.get_file_extension("file.txt")  # ".txt"
```
- **参数**:
  - `filename`: str, 文件名。
- **返回值**: str, 扩展名。

#### validate_file_exists(file_path)
```python
exists = FileDataManager.validate_file_exists("/path/to/file.txt")
```
- **参数**:
  - `file_path`: str, 文件路径。
- **返回值**: bool, 是否存在。

#### is_duplicate_filename(pan_instance, filename)
```python
dup = FileDataManager.is_duplicate_filename(pan, "file.txt")
```
- **参数**:
  - `pan_instance`: Pan123, 实例。
  - `filename`: str, 文件名。
- **返回值**: bool, 是否重复。

### 工具函数

#### format_file_size(size)
```python
size_str = format_file_size(1073741824)  # "1.0 GB"
```
- **参数**: int, 文件大小（字节）。
- **返回值**: str, 格式化字符串。
