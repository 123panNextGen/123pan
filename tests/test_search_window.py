from unittest.mock import MagicMock

from PySide6.QtCore import Qt

from src.app.view import search_window as search_module
from src.app.view.search_window import SearchDialog


class _FakeLabel:
    def __init__(self):
        self.text = None

    def setText(self, text):
        self.text = text


class _FakeViewport:
    def __init__(self):
        self.updated = False

    def update(self):
        self.updated = True


class _FakeListItem:
    def __init__(self):
        self._data = {}

    def setData(self, role, value):
        self._data[role] = value

    def data(self, role):
        return self._data.get(role)


class _FakeResultList:
    def __init__(self):
        self.items = []
        self._viewport = _FakeViewport()

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def item(self, index):
        return self.items[index]

    def viewport(self):
        return self._viewport


def test_search_finished_ignores_stale_result(monkeypatch):
    dialog = SearchDialog.__new__(SearchDialog)
    dialog._search_request_id = 2
    dialog._closed = False
    dialog._pending_signals = []
    dialog.statusLabel = _FakeLabel()
    dialog.resultList = _FakeResultList()
    dialog._SearchDialog__fetchPaths = MagicMock()
    monkeypatch.setattr(search_module, "QListWidgetItem", _FakeListItem)

    SearchDialog._SearchDialog__onSearchFinished(
        dialog,
        items=[{"FileId": 1, "FileName": "old.txt", "Type": 0, "ParentFileId": 0}],
        error="",
        request_id=1,
    )

    assert dialog.statusLabel.text is None
    assert dialog.resultList.items == []
    dialog._SearchDialog__fetchPaths.assert_not_called()


def test_paths_finished_ignores_stale_result():
    dialog = SearchDialog.__new__(SearchDialog)
    dialog._search_request_id = 2
    dialog._closed = False
    dialog._pending_signals = []
    dialog.resultList = _FakeResultList()
    item = _FakeListItem()
    item.setData(
        Qt.ItemDataRole.UserRole,
        {
            "FileId": 1,
            "FileName": "demo.txt",
            "Type": 0,
            "ParentFileId": 7,
            "paths": None,
        },
    )
    dialog.resultList.addItem(item)

    SearchDialog._SearchDialog__onPathsFetched(
        dialog,
        path_map={7: ["旧目录"]},
        request_id=1,
    )

    assert item.data(Qt.ItemDataRole.UserRole)["paths"] is None
    assert dialog.resultList.viewport().updated is False
