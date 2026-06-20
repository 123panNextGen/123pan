from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional


class ApiCode(Enum):
    success = auto()
    fail = auto()


@dataclass
class ApiReturnModel:
    code: int
    api_code: int
    api_code_enum: ApiCode
    msg: str
    data: Any = None


@dataclass
class DeviceModel:
    os: str
    type: str


@dataclass
class UserInfoModel:
    user_name: str
    password: str
    uuid: str
    authorization: str
    device: DeviceModel


@dataclass
class FileItemModel:
    file_id: int
    file_name: str
    _type: int
    size: int
    create_at: datetime
    update_at: datetime
    hidden: bool
    etag: str
    s3key_flag: str
    content_type: str
    parent_file_id: int
    pin_yin: str
    starred_status: bool

    def from_json(self, json: dict[str, Any]):
        self.file_id = int(json['FileId'])
        self.file_name = str(json['FileName'])
        self._type = int(json['Type'])
        self.size = int(json['Size'])
        self.create_at = self._parse_timestamp(json['CreateAt'])
        self.update_at = self._parse_timestamp(json['UpdateAt'])
        self.hidden = bool(json['Hidden'])
        self.etag = str(json['Etag'])
        self.s3key_flag = str(json['S3KeyFlag'])
        self.content_type = str(json['ContentType'])
        self.parent_file_id = int(json['ParentFileId'])
        self.pin_yin = str(json['PinYin'])
        self.starred_status = bool(json['StarredStatus'])

    def to_json(self) -> dict[str, Any]:
        return {
            'FileId': self.file_id,
            'FileName': self.file_name,
            'Type': self._type,
            'Size': self.size,
            'CreateAt': int(self.create_at.timestamp()),
            'UpdateAt': int(self.update_at.timestamp()),
            'Hidden': self.hidden,
            'Etag': self.etag,
            'S3KeyFlag': self.s3key_flag,
            'ContentType': self.content_type,
            'ParentFileId': self.parent_file_id,
            'PinYin': self.pin_yin,
            'StarredStatus': self.starred_status,
        }

    def is_dir(self):
        return self._type == 1

    @staticmethod
    def _parse_timestamp(value) -> datetime:
        """安全解析时间戳，兼容 Unix 时间戳(int/float/str)和 ISO 8601 字符串。"""
        if value is None or value == 0 or value == "":
            return datetime.fromtimestamp(0)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        s = str(value).strip()
        if not s:
            return datetime.fromtimestamp(0)
        if 'T' in s or '-' in s:
            return datetime.fromisoformat(s)
        return datetime.fromtimestamp(float(s))

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> 'FileItemModel':
        return cls(
            file_id=int(json.get('FileId', json.get('fileId', 0))),
            file_name=str(json.get('FileName', json.get('fileName', ''))),
            _type=int(json.get('Type', json.get('type', 0))),
            size=int(json.get('Size', json.get('size', 0))),
            create_at=cls._parse_timestamp(json.get('CreateAt', json.get('createAt', 0))),
            update_at=cls._parse_timestamp(json.get('UpdateAt', json.get('updateAt', 0))),
            hidden=bool(json.get('Hidden', json.get('hidden', False))),
            etag=str(json.get('Etag', json.get('etag', ''))),
            s3key_flag=str(json.get('S3KeyFlag', json.get('s3keyFlag', ''))),
            content_type=str(json.get('ContentType', json.get('contentType', ''))),
            parent_file_id=int(json.get('ParentFileId', json.get('parentFileId', 0))),
            pin_yin=str(json.get('PinYin', json.get('pinYin', ''))),
            starred_status=bool(json.get('StarredStatus', json.get('starredStatus', False))),
        )


@dataclass
class FileListData:
    next: str
    len: int
    total: int
    is_first: bool
    info_list: list[FileItemModel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> 'FileListData':
        info = json.get('InfoList', json.get('infoList', []))
        return cls(
            next=str(json.get('Next', json.get('next', '-1'))),
            len=int(json.get('Len', json.get('len', 0))),
            total=int(json.get('Total', json.get('total', 0))),
            is_first=bool(json.get('IsFirst', json.get('isFirst', False))),
            info_list=[FileItemModel.from_dict(item) for item in info],
        )


@dataclass
class FileListResponse:
    code: int
    message: str
    data: FileListData

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> 'FileListResponse':
        return cls(
            code=int(json.get('code', json.get('Code', -1))),
            message=str(json.get('message', json.get('Message', ''))),
            data=FileListData.from_dict(json.get('data', json.get('Data', {}))),
        )
