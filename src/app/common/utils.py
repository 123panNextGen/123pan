"""
通用工具函数。

此模块包含项目中多处使用的辅助函数，从 common/api.py 中提取以降低耦合。
"""

from pathlib import Path


def format_file_size(size):
    """将字节数格式化为人类可读的文件大小字符串。

    Args:
        size: 文件大小（字节）

    Returns:
        格式化后的字符串，如 "1.5 GB"、"256 KB"
    """
    units = ["B", "KB", "MB", "GB", "TB"]
    for i in range(len(units)):
        if size < 1024.0:
            return f"{round(size, 2)} {units[i]}"
        size /= 1024.0
    return f"{size:.2f} {units[-1]}"


class FileDataManager:
    """文件数据处理器 - 处理与文件相关的业务逻辑，不涉及 UI。"""

    @staticmethod
    def get_file_type_name(file_type):
        """根据文件类型返回类型名称。"""
        return "文件夹" if file_type == 1 else "文件"

    @staticmethod
    def get_file_extension(filename):
        """获取文件扩展名（小写）。"""
        return Path(filename).suffix.lower()

    @staticmethod
    def validate_file_exists(file_path):
        """验证文件是否存在。"""
        return Path(file_path).is_file()

    @staticmethod
    def is_duplicate_filename(pan_instance, filename):
        """检查是否存在同名文件。"""
        return any(item.get("FileName") == filename for item in pan_instance.list)

    @staticmethod
    def format_file_size_value(size):
        """格式化文件大小（format_file_size 的别名）。"""
        return format_file_size(size)
