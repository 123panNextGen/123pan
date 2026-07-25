"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


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

    def to_json(self) -> dict[str, Any]:
        return {
            "FileId": self.file_id,
            "FileName": self.file_name,
            "Type": self._type,
            "Size": self.size,
            "CreateAt": int(self.create_at.timestamp()),
            "UpdateAt": int(self.update_at.timestamp()),
            "Hidden": self.hidden,
            "Etag": self.etag,
            "S3KeyFlag": self.s3key_flag,
            "ContentType": self.content_type,
            "ParentFileId": self.parent_file_id,
            "PinYin": self.pin_yin,
            "StarredStatus": self.starred_status,
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
        if "T" in s or "-" in s:
            return datetime.fromisoformat(s)
        return datetime.fromtimestamp(float(s))

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "FileItemModel":
        return cls(
            file_id=int(json.get("FileId", json.get("fileId", 0))),
            file_name=str(json.get("FileName", json.get("fileName", ""))),
            _type=int(json.get("Type", json.get("type", 0))),
            size=int(json.get("Size", json.get("size", 0))),
            create_at=cls._parse_timestamp(
                json.get("CreateAt", json.get("createAt", 0))
            ),
            update_at=cls._parse_timestamp(
                json.get("UpdateAt", json.get("updateAt", 0))
            ),
            hidden=bool(json.get("Hidden", json.get("hidden", False))),
            etag=str(json.get("Etag", json.get("etag", ""))),
            s3key_flag=str(json.get("S3KeyFlag", json.get("s3keyFlag", ""))),
            content_type=str(json.get("ContentType", json.get("contentType", ""))),
            parent_file_id=int(json.get("ParentFileId", json.get("parentFileId", 0))),
            pin_yin=str(json.get("PinYin", json.get("pinYin", ""))),
            starred_status=bool(
                json.get("StarredStatus", json.get("starredStatus", False))
            ),
        )


@dataclass
class FileListData:
    next: str
    len: int
    total: int
    is_first: bool
    info_list: list[FileItemModel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "FileListData":
        info = json.get("InfoList", json.get("infoList", []))
        return cls(
            next=str(json.get("Next", json.get("next", "-1"))),
            len=int(json.get("Len", json.get("len", 0))),
            total=int(json.get("Total", json.get("total", 0))),
            is_first=bool(json.get("IsFirst", json.get("isFirst", False))),
            info_list=[FileItemModel.from_dict(item) for item in info],
        )


@dataclass
class FileListResponse:
    code: int
    message: str
    data: FileListData

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "FileListResponse":
        return cls(
            code=int(json.get("code", json.get("Code", -1))),
            message=str(json.get("message", json.get("Message", ""))),
            data=FileListData.from_dict(json.get("data", json.get("Data", {}))),
        )


@dataclass
class CloudUserInfoModel:
    """云盘用户信息（来自 /b/api/user/info）。"""
    uid: int
    nickname: str
    space_used: int       # 已用空间（字节）
    space_total: int      # 永久空间总量（字节）
    space_temp: int       # 临时空间（字节）
    file_count: int
    vip: bool
    vip_expire: str       # VIP 到期日期
    vip_level: int
    head_image: str
    direct_traffic: int   # 直链流量
    share_traffic: int    # 分享流量
    passport: int

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "CloudUserInfoModel":
        data = json.get("data", json) if "data" in json else json
        return cls(
            uid=int(data.get("UID", data.get("uid", 0))),
            nickname=str(data.get("Nickname", data.get("nickname", ""))),
            space_used=int(data.get("SpaceUsed", data.get("spaceUsed", 0))),
            space_total=int(data.get("SpacePermanent", data.get("spacePermanent", 0))),
            space_temp=int(data.get("SpaceTemp", data.get("spaceTemp", 0))),
            file_count=int(data.get("FileCount", data.get("fileCount", 0))),
            vip=bool(data.get("Vip", data.get("vip", False))),
            vip_expire=str(data.get("VipExpire", data.get("vipExpire", ""))),
            vip_level=int(data.get("VipLevel", data.get("vipLevel", 0))),
            head_image=str(data.get("HeadImage", data.get("headImage", ""))),
            direct_traffic=int(data.get("DirectTraffic", data.get("directTraffic", 0))),
            share_traffic=int(data.get("ShareTraffic", data.get("shareTraffic", 0))),
            passport=int(data.get("Passport", data.get("passport", 0))),
        )

    def space_used_str(self):
        """格式化已用空间（如 '525.1 GB'）。"""
        return _format_bytes(self.space_used)

    def space_total_str(self):
        """格式化总空间（如 '28.5 TB'）。"""
        return _format_bytes(self.space_total)

    def traffic_str(self):
        """格式化直链流量（如 '10.0 GB'）。"""
        return _format_bytes(self.direct_traffic)


@dataclass
class ShareItemModel:
    """分享链接条目模型。"""
    share_id: int
    share_key: str
    drive_id: int
    file_id_list: str
    download_count: int
    preview_count: int
    save_count: int
    share_name: str
    expiration: str
    expired: bool
    share_pwd: str
    status: int
    create_at: str
    update_at: str
    is_pay_share: int
    is_reward: int
    audit_status: int
    amount: int
    share_url: str
    share_link: str
    traffic_switch: int
    traffic_limit_switch: int
    traffic_limit: int

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "ShareItemModel":
        link_list = json.get("shareLinkList", {}) or {}
        links = link_list.get("list", [])
        share_link = links[0] if links else ""
        return cls(
            share_id=int(json.get("ShareId", json.get("shareId", 0))),
            share_key=str(json.get("ShareKey", json.get("shareKey", ""))),
            drive_id=int(json.get("DriveId", json.get("driveId", 0))),
            file_id_list=str(json.get("FileIdList", json.get("fileIdList", ""))),
            download_count=int(json.get("DownloadCount", json.get("downloadCount", 0))),
            preview_count=int(json.get("PreviewCount", json.get("previewCount", 0))),
            save_count=int(json.get("SaveCount", json.get("saveCount", 0))),
            share_name=str(json.get("ShareName", json.get("shareName", ""))),
            expiration=str(json.get("Expiration", json.get("expiration", ""))),
            expired=bool(json.get("Expired", json.get("expired", False))),
            share_pwd=str(json.get("SharePwd", json.get("sharePwd", ""))),
            status=int(json.get("Status", json.get("status", 0))),
            create_at=str(json.get("CreateAt", json.get("createAt", ""))),
            update_at=str(json.get("UpdateAt", json.get("updateAt", ""))),
            is_pay_share=int(json.get("isPayShare", 0)),
            is_reward=int(json.get("isReward", 0)),
            audit_status=int(json.get("auditStatus", 0)),
            amount=int(json.get("amount", 0)),
            share_url=str(json.get("ShareUrl", json.get("shareUrl", ""))),
            share_link=str(share_link),
            traffic_switch=int(json.get("trafficSwitch", 0)),
            traffic_limit_switch=int(json.get("trafficLimitSwitch", 0)),
            traffic_limit=int(json.get("trafficLimit", 0)),
        )


@dataclass
class ShareListData:
    """分享列表分页数据。"""
    next: str
    len: int
    total: int
    is_first: bool
    info_list: list[ShareItemModel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "ShareListData":
        info = json.get("InfoList", json.get("infoList", [])) or []
        return cls(
            next=str(json.get("Next", json.get("next", "-1"))),
            len=int(json.get("Len", json.get("len", 0))),
            total=int(json.get("Total", json.get("total", 0))),
            is_first=bool(json.get("IsFirst", json.get("isFirst", False))),
            info_list=[ShareItemModel.from_dict(item) for item in info],
        )


@dataclass
class ShareListResponse:
    """分享列表 API 响应。"""
    code: int
    message: str
    data: ShareListData

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "ShareListResponse":
        return cls(
            code=int(json.get("code", json.get("Code", -1))),
            message=str(json.get("message", json.get("Message", ""))),
            data=ShareListData.from_dict(json.get("data", json.get("Data", {}))),
        )


def _format_bytes(size):
    """字节数格式化为可读字符串。"""
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


@dataclass
class DeviceItemModel:
    """登录设备条目模型。"""
    device_name: str
    plat_form: str
    ip: str
    last_login_time: str
    device_type: str
    key: str
    cur_device: bool
    login_type: str
    img: str
    login_uuid: str

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "DeviceItemModel":
        return cls(
            device_name=str(json.get("device_name", "")),
            plat_form=str(json.get("plat_form", "")),
            ip=str(json.get("ip", "")),
            last_login_time=str(json.get("last_login_time", "")),
            device_type=str(json.get("device_type", "")),
            key=str(json.get("key", "")),
            cur_device=bool(json.get("cur_device", False)),
            login_type=str(json.get("login_type", "")),
            img=str(json.get("img", "")),
            login_uuid=str(json.get("LoginUuid", json.get("loginUuid", ""))),
        )


@dataclass
class DeviceListResponse:
    """设备列表 API 响应。"""
    device_list: list[DeviceItemModel] = field(default_factory=list)
    del_device_power: bool = False
    master_device: DeviceItemModel | None = None

    @classmethod
    def from_dict(cls, json: dict[str, Any]) -> "DeviceListResponse":
        data = json.get("data", json) if "data" in json else json
        devices = data.get("DeviceS", []) or []
        master = data.get("masterDevice")
        return cls(
            device_list=[DeviceItemModel.from_dict(d) for d in devices],
            del_device_power=bool(data.get("del_device_power", False)),
            master_device=DeviceItemModel.from_dict(master) if master else None,
        )
