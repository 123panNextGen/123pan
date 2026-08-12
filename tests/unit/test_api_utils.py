"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from src.app.common.utils import format_file_size


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


class TestConfigureResizableHeader:
    """可交互调整列宽配置。"""

    def _make(self):
        from PySide6.QtWidgets import QApplication, QHeaderView

        from qfluentwidgets import TableWidget

        from src.app.common.utils import configure_resizable_header

        _app = QApplication.instance() or QApplication([])
        table = TableWidget()
        table.setColumnCount(4)
        table.resize(600, 300)
        table.show()
        QApplication.processEvents()
        stretch = configure_resizable_header(
            table, stretch_column=0, default_widths={0: 200, 1: 80}
        )
        QApplication.processEvents()
        return table, stretch

    def test_interactive_resize_mode(self):
        """所有列可交互调整。"""
        from PySide6.QtWidgets import QHeaderView

        table, _ = self._make()
        header = table.horizontalHeader()
        for i in range(header.count()):
            assert (
                header.sectionResizeMode(i) == QHeaderView.ResizeMode.Interactive
            )

    def test_default_widths_applied(self):
        """默认列宽生效。"""
        table, _ = self._make()
        header = table.horizontalHeader()
        assert header.sectionSize(1) == 80, f"col1={header.sectionSize(1)}"
        # 列0 为吸收多余宽度的 stretch 列，可能大于默认值，但不应小于
        assert header.sectionSize(0) >= 200, f"col0={header.sectionSize(0)}"

    def test_stretch_fills_extra_width(self):
        """stretch 列吸收多余宽度。"""
        table, stretch = self._make()
        header = table.horizontalHeader()
        # 人为扩大视口后调用 stretch
        before = header.sectionSize(0)
        table.resize(900, 300)
        table.show()
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        stretch()
        assert header.sectionSize(0) > before
