from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QEvent

from src.app.view import file_interface as fi_module
from src.app.view.file_interface import FileInterface


class _FakeUrl:
    def __init__(self, local_file="", is_local=True):
        self._local_file = local_file
        self._is_local = is_local

    def isLocalFile(self):
        return self._is_local

    def toLocalFile(self):
        return self._local_file


class _FakeMimeData:
    def __init__(self, urls):
        self._urls = urls

    def hasUrls(self):
        return bool(self._urls)

    def urls(self):
        return self._urls


def test_extract_local_paths_filters_non_local_and_duplicates(tmp_path):
    file_path = tmp_path / "a.txt"
    file_path.write_text("a", encoding="utf-8")
    folder_path = tmp_path / "folder"
    folder_path.mkdir()

    mime_data = _FakeMimeData(
        [
            _FakeUrl(str(file_path)),
            _FakeUrl(str(file_path)),
            _FakeUrl(str(folder_path)),
            _FakeUrl("https://example.com/demo", is_local=False),
            _FakeUrl(""),
        ]
    )

    paths = FileInterface._FileInterface__extractLocalPaths(mime_data)

    assert paths == [file_path, folder_path]


def test_build_upload_summary_handles_empty_folder_upload():
    summary = FileInterface._FileInterface__buildUploadSummary(0, 3)

    assert summary == "已创建 3 个文件夹"


@patch("src.app.view.file_interface.QFileDialog.getExistingDirectory")
def test_upload_folder_calls_prepare_with_selected_path(mock_dialog):
    mock_dialog.return_value = "/some/folder"
    mock_prepare = MagicMock()

    fi = MagicMock()
    fi._FileInterface__prepareLocalUploads = mock_prepare
    FileInterface._FileInterface__uploadFolder(fi)

    mock_prepare.assert_called_once_with([Path("/some/folder")])


@patch("src.app.view.file_interface.QFileDialog.getExistingDirectory")
def test_upload_folder_cancel_does_not_call_prepare(mock_dialog):
    mock_dialog.return_value = ""
    mock_prepare = MagicMock()

    fi = MagicMock()
    fi._FileInterface__prepareLocalUploads = mock_prepare
    FileInterface._FileInterface__uploadFolder(fi)

    mock_prepare.assert_not_called()


def test_drag_highlight_sets_stylesheet_on_enter():
    fi = MagicMock()
    fi.fileTable = MagicMock()
    viewport_mock = MagicMock()
    fi.fileTable.viewport.return_value = viewport_mock
    fi._FileInterface__acceptLocalDrop = MagicMock(return_value=True)

    event = MagicMock()
    event.type.return_value = QEvent.Type.DragEnter

    result = FileInterface._FileInterface__handleDropEvent(fi, event)

    assert result is True
    viewport_mock.setStyleSheet.assert_called_once_with(
        "border: 2px dashed #0078d4; border-radius: 8px;"
    )


def test_drag_highlight_clears_on_leave():
    fi = MagicMock()
    fi.fileTable = MagicMock()
    viewport_mock = MagicMock()
    fi.fileTable.viewport.return_value = viewport_mock

    event = MagicMock()
    event.type.return_value = QEvent.Type.DragLeave

    result = FileInterface._FileInterface__handleDropEvent(fi, event)

    assert result is False
    viewport_mock.setStyleSheet.assert_called_once_with("")


def test_drag_highlight_clears_on_drop():
    fi = MagicMock()
    fi.fileTable = MagicMock()
    viewport_mock = MagicMock()
    fi.fileTable.viewport.return_value = viewport_mock
    fi._FileInterface__dropLocalPaths = MagicMock(return_value=True)

    event = MagicMock()
    event.type.return_value = QEvent.Type.Drop

    result = FileInterface._FileInterface__handleDropEvent(fi, event)

    assert result is True
    viewport_mock.setStyleSheet.assert_called_once_with("")


def test_prepare_upload_task_skips_failed_file_but_keeps_other_uploads(tmp_path):
    ok_file = tmp_path / "ok.txt"
    ok_file.write_text("ok", encoding="utf-8")
    missing_file = tmp_path / "missing.txt"
    task = FileInterface.PrepareUploadTask(
        pan=MagicMock(),
        target_dir_id=9,
        local_paths=[str(ok_file), str(missing_file)],
    )
    results = []
    task.signals.finished.connect(lambda uploads, created, folders, error: results.append(
        (uploads, created, folders, error)
    ))

    task.run()

    uploads, created_dir_count, folder_items, error = results[0]
    assert uploads == [
        {
            "file_name": "ok.txt",
            "file_size": 2,
            "local_path": str(ok_file),
            "target_dir_id": 9,
        }
    ]
    assert created_dir_count == 0
    assert folder_items == []
    assert "missing.txt" in error


def test_prepare_upload_task_stops_when_folder_creation_fails(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    pan = MagicMock()
    pan.prepare_folder_upload.side_effect = RuntimeError("429")
    task = FileInterface.PrepareUploadTask(
        pan=pan,
        target_dir_id=9,
        local_paths=[str(folder)],
    )
    results = []
    task.signals.finished.connect(lambda uploads, created, folders, error: results.append(
        (uploads, created, folders, error)
    ))

    task.run()

    assert results[0] == ([], 0, [], "429")


def test_prepare_upload_finished_drops_stale_cross_account_result():
    fi = MagicMock()
    fi.pan = object()
    fi.transfer_interface = MagicMock()
    fi.transfer_interface.current_account_name = "current"
    fi.current_dir_id = 7
    fi._FileInterface__updateTreeUI = MagicMock()
    fi._FileInterface__refreshFileList = MagicMock()

    FileInterface._FileInterface__onPrepareUploadFinished(
        fi,
        uploads=[{
            "file_name": "a.txt",
            "file_size": 1,
            "local_path": "/tmp/a.txt",
            "target_dir_id": 7,
        }],
        created_dir_count=0,
        folder_items=[],
        error="",
        context={
            "pan": object(),
            "account_name": "old",
            "target_dir_id": 7,
        },
    )

    fi.transfer_interface.add_upload_task.assert_not_called()
    fi._FileInterface__updateTreeUI.assert_not_called()
    fi._FileInterface__refreshFileList.assert_not_called()


def test_jump_finished_drops_stale_result():
    fi = FileInterface.__new__(FileInterface)
    fi._jump_request_id = 2
    fi.path_stack = [(0, "根目录")]
    fi.current_dir_id = 0
    fi._FileInterface__updateBreadcrumb = MagicMock()

    FileInterface._FileInterface__onJumpFinished(
        fi,
        detail_paths=[{"fileId": 7, "fileName": "docs"}],
        target_dir_id=7,
        select_file_id=None,
        error="",
        request_id=1,
    )

    assert fi.path_stack == [(0, "根目录")]
    assert fi.current_dir_id == 0
    fi._FileInterface__updateBreadcrumb.assert_not_called()


def test_create_folder_finished_drops_stale_dir_result():
    fi = FileInterface.__new__(FileInterface)
    fi.pan = object()
    fi.current_dir_id = 9
    fi.transfer_interface = MagicMock(current_account_name="alice")
    fi._FileInterface__updateFileListUI = MagicMock()
    fi._FileInterface__updateTreeUI = MagicMock()

    FileInterface._FileInterface__onCreateFolderFinished(
        fi,
        result=True,
        folder_name="docs",
        error="",
        file_items=[{"FileId": 1, "FileName": "docs"}],
        folder_items=[{"FileId": 1, "FileName": "docs"}],
        context={
            "pan": fi.pan,
            "account_name": "alice",
            "dir_id": 7,
            "request_id": None,
        },
    )

    fi._FileInterface__updateFileListUI.assert_not_called()
    fi._FileInterface__updateTreeUI.assert_not_called()


def test_move_finished_drops_stale_account_result():
    fi = FileInterface.__new__(FileInterface)
    fi.pan = object()
    fi.current_dir_id = 7
    fi.transfer_interface = MagicMock(current_account_name="current")
    fi._FileInterface__refreshFileList = MagicMock()

    FileInterface._FileInterface__onMoveFilesFinished(
        fi,
        success=True,
        count=2,
        target_name="目标目录",
        error="",
        context={
            "pan": fi.pan,
            "account_name": "old",
            "dir_id": 7,
            "request_id": None,
        },
    )

    fi._FileInterface__refreshFileList.assert_not_called()


@patch("src.app.view.file_interface.MessageBox", side_effect=AssertionError("should not open"))
def test_file_details_finished_drops_stale_request(_mock_message_box):
    fi = FileInterface.__new__(FileInterface)
    fi.pan = object()
    fi.transfer_interface = MagicMock(current_account_name="alice")
    fi._file_details_request_id = 2

    FileInterface._FileInterface__onFileDetailsFinished(
        fi,
        file_name="demo.txt",
        data={"paths": [], "fileNum": 1, "dirNum": 0, "totalSize": 1},
        error="",
        context={
            "pan": fi.pan,
            "account_name": "alice",
            "dir_id": None,
            "request_id": 1,
        },
    )


def test_async_context_helper_marks_stale_storage_result():
    fi = FileInterface.__new__(FileInterface)
    fi.pan = object()
    fi.transfer_interface = MagicMock(current_account_name="alice")
    fi.current_dir_id = 7

    stale = FileInterface._FileInterface__isAsyncContextStale(
        fi,
        {
            "pan": object(),
            "account_name": "alice",
            "dir_id": None,
            "request_id": None,
        },
    )

    assert stale is True


def test_create_upload_button_group_uses_split_push_button(monkeypatch):
    created_actions = []

    class _FakeMenu:
        def addAction(self, action):
            created_actions.append(action)

    class _FakeDropButton:
        def setToolTip(self, text):
            self.tooltip = text

    class _FakeSplitButton:
        def __init__(self, text, parent, icon):
            self.text = text
            self.parent = parent
            self.icon = icon
            self.flyout = None
            self.drop_icon = None
            self.height = None
            self.dropButton = _FakeDropButton()

        def setFlyout(self, flyout):
            self.flyout = flyout

        def setDropIcon(self, icon):
            self.drop_icon = icon

    monkeypatch.setattr("src.app.view.file_interface.RoundMenu", lambda parent=None: _FakeMenu())
    monkeypatch.setattr("src.app.view.file_interface.SplitPushButton", _FakeSplitButton)
    monkeypatch.setattr(
        "src.app.view.file_interface.Action",
        lambda icon, text, triggered=None: {
            "icon": icon,
            "text": text,
            "triggered": triggered,
        },
    )

    fi = MagicMock()
    fi.topBarFrame = object()
    fi._FileInterface__uploadFile = MagicMock()
    fi._FileInterface__uploadFolder = MagicMock()

    FileInterface._FileInterface__createUploadButtonGroup(fi)

    assert fi.uploadButton.text == "上传文件"
    assert fi.uploadButton.drop_icon == fi_module.FIF.DOWN
    assert fi.uploadButton.dropButton.tooltip == "更多上传方式"
    assert [action["text"] for action in created_actions] == ["上传文件", "上传文件夹"]
    assert fi.uploadButtonGroup is fi.uploadButton
