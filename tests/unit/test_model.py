"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from datetime import datetime

from src.app.api.model import ApiCode, ApiReturnModel, FileItemModel, FileListData


class TestApiReturnModel:
    def test_creation(self):
        m = ApiReturnModel(code=200, api_code=0, api_code_enum=ApiCode.success, msg="ok")
        assert m.code == 200
        assert m.api_code == 0
        assert m.api_code_enum == ApiCode.success
        assert m.msg == "ok"
        assert m.data is None

    def test_with_data(self):
        m = ApiReturnModel(code=200, api_code=0, api_code_enum=ApiCode.success, msg="ok", data={"key": "val"})
        assert m.data == {"key": "val"}


class TestFileItemModel:
    def test_from_dict_pascal_case(self):
        data = {
            "FileId": 1, "FileName": "test.txt", "Type": 0,
            "Size": 1024, "CreateAt": 1700000000, "UpdateAt": 1700000001,
            "Hidden": False, "Etag": "abc", "S3KeyFlag": "", "ContentType": "text/plain",
            "ParentFileId": 0, "PinYin": "test", "StarredStatus": False,
        }
        item = FileItemModel.from_dict(data)
        assert item.file_id == 1
        assert item.file_name == "test.txt"
        assert item._type == 0
        assert item.size == 1024
        assert not item.is_dir()

    def test_from_dict_camel_case(self):
        data = {
            "fileId": 2, "fileName": "folder", "type": 1,
            "size": 0, "createAt": 1700000000, "updateAt": 1700000001,
            "hidden": False, "etag": "def", "s3keyFlag": "",
            "contentType": "", "parentFileId": 0, "pinYin": "",
            "starredStatus": False,
        }
        item = FileItemModel.from_dict(data)
        assert item.file_id == 2
        assert item.file_name == "folder"
        assert item._type == 1
        assert item.is_dir()

    def test_from_dict_missing_fields_use_defaults(self):
        data = {}
        item = FileItemModel.from_dict(data)
        assert item.file_id == 0
        assert item.file_name == ""
        assert item._type == 0
        assert item.size == 0

    def test_to_json_roundtrip(self):
        data = {
            "FileId": 1, "FileName": "test.txt", "Type": 0,
            "Size": 1024, "CreateAt": 1700000000, "UpdateAt": 1700000001,
            "Hidden": False, "Etag": "abc", "S3KeyFlag": "", "ContentType": "text/plain",
            "ParentFileId": 0, "PinYin": "test", "StarredStatus": False,
        }
        item = FileItemModel.from_dict(data)
        out = item.to_json()
        assert out["FileId"] == 1
        assert out["FileName"] == "test.txt"
        assert out["Type"] == 0
        assert out["Size"] == 1024

    def test_is_dir(self):
        file_item = FileItemModel(1, "f", 0, 0, datetime.now(), datetime.now(), False, "", "", "", 0, "", False)
        dir_item = FileItemModel(2, "d", 1, 0, datetime.now(), datetime.now(), False, "", "", "", 0, "", False)
        assert file_item.is_dir() is False
        assert dir_item.is_dir() is True

    def test_parse_timestamp_none(self):
        assert FileItemModel._parse_timestamp(None) == datetime.fromtimestamp(0)
        assert FileItemModel._parse_timestamp(0) == datetime.fromtimestamp(0)
        assert FileItemModel._parse_timestamp("") == datetime.fromtimestamp(0)

    def test_parse_timestamp_int(self):
        dt = FileItemModel._parse_timestamp(1700000000)
        assert isinstance(dt, datetime)
        assert int(dt.timestamp()) == 1700000000

    def test_parse_timestamp_iso(self):
        dt = FileItemModel._parse_timestamp("2024-01-01T00:00:00")
        assert dt == datetime.fromisoformat("2024-01-01T00:00:00")


class TestFileListData:
    def test_from_dict(self):
        data = {
            "Next": "-1", "Len": 10, "Total": 100, "IsFirst": True,
            "InfoList": [
                {"FileId": 1, "FileName": "a.txt", "Type": 0, "Size": 100,
                 "CreateAt": 1700000000, "UpdateAt": 1700000000,
                 "Hidden": False, "Etag": "", "S3KeyFlag": "",
                 "ContentType": "", "ParentFileId": 0, "PinYin": "", "StarredStatus": False},
            ],
        }
        fld = FileListData.from_dict(data)
        assert fld.next == "-1"
        assert fld.len == 10
        assert fld.total == 100
        assert fld.is_first is True
        assert len(fld.info_list) == 1
        assert fld.info_list[0].file_name == "a.txt"

    def test_from_dict_camel(self):
        data = {
            "next": "-1", "len": 0, "total": 0, "isFirst": False,
            "infoList": [],
        }
        fld = FileListData.from_dict(data)
        assert fld.next == "-1"
        assert fld.is_first is False
        assert fld.info_list == []
