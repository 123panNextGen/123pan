"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import json
from unittest.mock import MagicMock

from src.app.service.offline_service import OfflineService
from src.app.tasks.file_tasks import GenerateRapidTask
from src.app.tasks.signals import _GenerateRapidSignals


def _svc():
    session = MagicMock()
    return OfflineService(session)


def _file(path, etag="d41d8cd98f00b204e9800998ecf8427e", size=100):
    return {"path": path, "etag": etag, "size": size}


class TestBuildRapidPayload:
    """秒传数据生成（JSON + 文本链接）。"""

    def test_single_file(self):
        svc = _svc()
        json_text, link_text = svc.build_rapid_payload([_file("a.txt")])
        data = json.loads(json_text)
        assert data["commonPath"] == ""
        assert len(data["files"]) == 1
        assert data["files"][0]["path"] == "a.txt"
        assert data["totalFilesCount"] == 1
        # 文本链接：123FLCPV2$%etag#size#path
        assert link_text.startswith("123FLCPV2$%")
        assert "d41d8cd98f00b204e9800998ecf8427e#100#a.txt" in link_text

    def test_common_path(self):
        svc = _svc()
        files = [
            _file("folder/sub/a.txt"),
            _file("folder/sub/b.txt"),
            _file("folder/c.txt"),
        ]
        json_text, link_text = svc.build_rapid_payload(files)
        data = json.loads(json_text)
        assert data["commonPath"] == "folder/"
        paths = {f["path"] for f in data["files"]}
        assert paths == {"sub/a.txt", "sub/b.txt", "c.txt"}
        # 链接中路径为相对路径
        assert "sub/a.txt" in link_text
        assert link_text.startswith("123FLCPV2$folder/%")

    def test_no_common_path_with_files_in_root(self):
        svc = _svc()
        files = [_file("a.txt"), _file("dir/b.txt")]
        json_text, _ = svc.build_rapid_payload(files)
        data = json.loads(json_text)
        assert data["commonPath"] == ""
        paths = {f["path"] for f in data["files"]}
        assert paths == {"a.txt", "dir/b.txt"}

    def test_skips_invalid_etag(self):
        svc = _svc()
        import pytest

        # 唯一文件 etag 无效 → 全部被过滤 → 报错
        with pytest.raises(ValueError):
            svc.build_rapid_payload([_file("a.txt", etag="invalid")])

    def test_roundtrip_generate_parse(self):
        """生成后可被 parse_rapid_data 解析回同一文件集。"""
        svc = _svc()
        files = [_file("folder/a.txt"), _file("folder/sub/b.txt", size=200)]
        json_text, link_text = svc.build_rapid_payload(files)

        # JSON 解析
        parsed_json = svc.parse_rapid_data(json_text)
        assert {f["path"] for f in parsed_json} == {"folder/a.txt", "folder/sub/b.txt"}

        # 文本链接解析
        parsed_link = svc.parse_rapid_data(link_text)
        assert {f["path"] for f in parsed_link} == {"folder/a.txt", "folder/sub/b.txt"}
        assert {f["etag"] for f in parsed_link} == {
            "d41d8cd98f00b204e9800998ecf8427e"
        }


class TestGenerateRapidTask:
    """秒传生成后台任务。"""

    def _run(self, pan, file_infos):
        signals = _GenerateRapidSignals()
        result = {}

        def on_finished(j, l, c, s, e):
            result.update({"json": j, "link": l, "count": c, "size": s, "error": e})

        signals.finished.connect(on_finished)
        task = GenerateRapidTask(pan, file_infos, signals)
        task.run()
        return result

    def test_collect_files_recursively(self):
        pan = MagicMock()
        pan.file_page = 0
        pan.total = 0
        pan.all_file = False
        # 文件夹 10 下有 a.txt 和子文件夹 11，子文件夹 11 下有 b.txt
        def _get_dir(file_id, save=False, all=False, limit=100):
            if int(file_id) == 10:
                return 0, [
                    {"FileId": 11, "FileName": "sub", "Type": 1},
                    {"FileId": 12, "FileName": "a.txt", "Type": 0,
                     "Size": 100, "Etag": "d41d8cd98f00b204e9800998ecf8427e"},
                ]
            if int(file_id) == 11:
                return 0, [
                    {"FileId": 13, "FileName": "b.txt", "Type": 0,
                     "Size": 200, "Etag": "e2fc714c4727ee9395f324cd2e7f331f"},
                ]
            return 0, []

        pan.get_dir_by_id.side_effect = _get_dir
        pan.offline_build_rapid.side_effect = lambda files: (
            json.dumps({"files": files}), "LINK"
        )

        # 选中文件夹 "folder"(id=10) 与文件 "a2.txt"
        file_infos = [
            ({"FileId": 10, "FileName": "folder", "Type": 1}, "folder"),
            ({"FileId": 20, "FileName": "a2.txt", "Type": 0,
              "Size": 50, "Etag": "d41d8cd98f00b204e9800998ecf8427e"}, "a2.txt"),
        ]
        result = self._run(pan, file_infos)

        assert result["error"] == ""
        assert result["count"] == 3  # a.txt + b.txt + a2.txt
        collected = json.loads(result["json"])["files"]
        paths = {f["path"] for f in collected}
        assert paths == {"folder/a.txt", "folder/sub/b.txt", "a2.txt"}

    def test_no_valid_files(self):
        pan = MagicMock()
        pan.file_page = 0
        pan.total = 0
        pan.all_file = False
        pan.get_dir_by_id.return_value = (0, [])
        file_infos = [
            ({"FileId": 10, "FileName": "empty", "Type": 1}, "empty"),
        ]
        result = self._run(pan, file_infos)
        assert result["json"] == ""
        assert "没有可生成" in result["error"]
