"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from src.app.common.utils import FileDataManager, format_file_size


class TestFormatFileSize:
    def test_bytes(self):
        assert format_file_size(0) == "0 B"
        assert format_file_size(512) == "512 B"
        assert format_file_size(1023) == "1023 B"

    def test_kb(self):
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(2048) == "2.0 KB"
        assert format_file_size(1536) == "1.5 KB"

    def test_mb(self):
        assert format_file_size(1048576) == "1.0 MB"
        assert format_file_size(1572864) == "1.5 MB"

    def test_gb(self):
        result = format_file_size(1073741824)
        assert "GB" in result
        assert result.startswith("1.0")

    def test_tb(self):
        result = format_file_size(1099511627776)
        assert "TB" in result


class TestFileDataManager:
    def test_get_file_type_name(self):
        assert FileDataManager.get_file_type_name(1) == "文件夹"
        assert FileDataManager.get_file_type_name(0) == "文件"
        assert FileDataManager.get_file_type_name(2) == "文件"

    def test_format_file_size_value(self):
        assert FileDataManager.format_file_size_value(1024) == "1.0 KB"

    def test_get_file_extension(self):
        assert FileDataManager.get_file_extension("test.txt") == ".txt"
        assert FileDataManager.get_file_extension("no_ext") == ""
        assert FileDataManager.get_file_extension("") == ""
