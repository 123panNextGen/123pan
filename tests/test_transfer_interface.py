from pathlib import Path
from unittest.mock import MagicMock

from src.app.common import database as database_module
from src.app.common.database import Database
from src.app.view.transfer_interface import DownloadTask, TransferInterface


class _FakeSignal:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    def connect(self, handler):
        self.connected.append(handler)

    def disconnect(self, handler):
        self.disconnected.append(handler)
        if handler in self.connected:
            self.connected.remove(handler)


class _FakeButton:
    def __init__(self):
        self.clicked = _FakeSignal()
        self.text = None
        self.enabled = None
        self.icon = None

    def setText(self, text):
        self.text = text

    def setEnabled(self, enabled):
        self.enabled = enabled

    def setIcon(self, icon):
        self.icon = icon


def _use_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "123pan-open.db"
    monkeypatch.setattr(database_module, "_get_db_path", lambda: db_path)
    Database.reset()
    return Database.instance()


def _make_interface(tmp_path, monkeypatch):
    db = _use_temp_db(tmp_path, monkeypatch)
    interface = TransferInterface.__new__(TransferInterface)
    interface.download_tasks = []
    interface.upload_tasks = []
    interface.upload_threads = []
    interface.download_threads = []
    interface.download_status_filter = "全部"
    interface.current_account_name = "alice"
    interface.pan = None
    interface._TransferInterface__update_download_table = lambda: None
    interface._TransferInterface__update_upload_table = lambda: None
    interface._TransferInterface__try_start_pending_downloads = lambda: None
    interface._TransferInterface__try_start_pending_uploads = lambda: None
    interface.downloadTable = type(
        "_Table",
        (),
        {"currentRow": lambda self: 0},
    )()
    monkeypatch.setattr("src.app.view.transfer_interface.Database.instance", lambda: db)
    return interface, db


def test_task_finished_deletes_download_record(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    task = DownloadTask(
        file_name="demo.bin",
        file_size=10,
        file_id=1,
        save_path=str(tmp_path / "demo.bin"),
        account_name="alice",
    )
    db.save_download_task({
        "resume_id": task.resume_id,
        "account_name": "alice",
        "file_name": task.file_name,
        "file_id": task.file_id,
        "save_path": task.save_path,
    })

    interface._TransferInterface__task_finished(task, "download")

    assert task.status == "已完成"
    assert db.get_download_task(task.resume_id) is None


def test_get_filtered_download_tasks_by_status(tmp_path, monkeypatch):
    interface, _db = _make_interface(tmp_path, monkeypatch)
    interface.download_tasks = [
        DownloadTask("a.bin", 1, 1, str(tmp_path / "a.bin"), account_name="alice"),
        DownloadTask("b.bin", 1, 2, str(tmp_path / "b.bin"), account_name="alice"),
    ]
    interface.download_tasks[0].status = "下载中"
    interface.download_tasks[1].status = "失败"
    interface.download_status_filter = "失败"

    filtered = interface._TransferInterface__get_filtered_download_tasks()

    assert [task.file_name for task in filtered] == ["b.bin"]


def test_resolve_download_folder_prefers_selected_visible_task(tmp_path, monkeypatch):
    interface, _db = _make_interface(tmp_path, monkeypatch)
    selected = DownloadTask(
        "a.bin",
        1,
        1,
        str(tmp_path / "custom" / "a.bin"),
        account_name="alice",
    )
    interface.download_tasks = [selected]

    folder = interface._TransferInterface__resolve_download_folder()

    assert folder == str(tmp_path / "custom")


def test_resolve_download_folder_falls_back_to_default_setting(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    interface.downloadTable = type(
        "_Table",
        (),
        {"currentRow": lambda self: -1},
    )()
    db.set_config("defaultDownloadPath", str(tmp_path / "downloads"))

    folder = interface._TransferInterface__resolve_download_folder()

    assert folder == str(tmp_path / "downloads")


def test_add_download_task_persists_record(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)

    task = interface.add_download_task(
        "demo.bin",
        12,
        99,
        str(tmp_path / "demo.bin"),
        current_dir_id=7,
        file_type=0,
        etag="etag-1",
        s3key_flag=True,
    )

    stored = db.get_download_task(task.resume_id)
    assert stored is not None
    assert stored["file_name"] == "demo.bin"
    assert stored["file_id"] == 99
    assert stored["current_dir_id"] == 7
    assert stored["etag"] == "etag-1"


def test_reload_upload_tasks_pauses_active_verifying_tasks(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    db.save_upload_task({
        "task_id": "upload-1",
        "account_name": "alice",
        "file_name": "demo.bin",
        "file_size": 12,
        "local_path": str(tmp_path / "demo.bin"),
        "target_dir_id": 7,
        "status": "校验中",
        "progress": 34,
    })

    interface._TransferInterface__reload_upload_tasks()

    assert len(interface.upload_tasks) == 1
    assert interface.upload_tasks[0].status == "已暂停"
    stored = db.get_upload_task("upload-1")
    assert stored is not None
    assert stored["status"] == "已暂停"


def test_reload_download_tasks_marks_verifying_tasks_failed(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    db.save_download_task({
        "resume_id": "download-1",
        "account_name": "alice",
        "file_name": "demo.bin",
        "file_size": 12,
        "file_id": 7,
        "save_path": str(tmp_path / "demo.bin"),
        "status": "校验中",
        "progress": 34,
    })

    interface._TransferInterface__reload_download_tasks()

    assert len(interface.download_tasks) == 1
    assert interface.download_tasks[0].status == "失败"
    assert interface.download_tasks[0].last_error == "下载中断，等待重试"
    assert interface._TransferInterface__active_download_count() == 0


def test_active_upload_count_includes_verifying_tasks(tmp_path, monkeypatch):
    interface, _db = _make_interface(tmp_path, monkeypatch)
    interface.upload_tasks = [
        type("_Task", (), {"status": "校验中"})(),
        type("_Task", (), {"status": "上传中"})(),
        type("_Task", (), {"status": "等待中"})(),
    ]

    assert interface._TransferInterface__active_upload_count() == 2


def test_active_upload_count_includes_starting_thread(tmp_path, monkeypatch):
    interface, _db = _make_interface(tmp_path, monkeypatch)
    interface.upload_tasks = [
        type("_Task", (), {"status": "等待中", "thread": object()})(),
        type("_Task", (), {"status": "等待中", "thread": None})(),
    ]

    assert interface._TransferInterface__active_upload_count() == 1


def test_try_start_pending_uploads_respects_thread_occupied_slots(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    db.set_config("maxConcurrentUploads", 1)
    started = []

    class _Task:
        def __init__(self, name):
            self.file_name = name
            self.status = "等待中"
            self.thread = None
            self.delete_requested = False

    task_a = _Task("a")
    task_b = _Task("b")
    interface.upload_tasks = [task_a, task_b]

    def fake_start(task):
        started.append(task.file_name)
        task.thread = object()

    interface._TransferInterface__start_upload_task = fake_start

    TransferInterface._TransferInterface__try_start_pending_uploads(interface)

    assert started == ["a"]
    assert task_b.thread is None


def test_remove_active_upload_defers_delete_until_terminal_status(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    task = interface.add_upload_task(
        "demo.bin",
        12,
        str(tmp_path / "demo.bin"),
        7,
    )
    task.thread = MagicMock()
    task_id = task.db_task_id

    interface._TransferInterface__remove_task(task, "upload")

    assert task in interface.upload_tasks
    assert task.delete_requested is True
    stored = db.get_upload_task(task_id)
    assert stored is not None
    assert stored["delete_requested"] == 1
    assert stored["status"] == "已取消"

    task.thread = None
    interface._TransferInterface__update_task_status(task, "已取消")

    assert task not in interface.upload_tasks
    assert task.db_task_id is None
    assert db.get_upload_task(task_id) is None


def test_start_download_task_clears_pause_and_cancel_flags(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    interface.pan = object()
    task = DownloadTask(
        file_name="demo.bin",
        file_size=12,
        file_id=1,
        save_path=str(tmp_path / "demo.bin"),
        account_name="alice",
    )
    task.pause_requested = True
    task.is_cancelled = True

    created_threads = []

    class _FakeThread:
        def __init__(self, task_arg, pan_arg):
            created_threads.append((task_arg.pause_requested, task_arg.is_cancelled, pan_arg))
            self.progress_updated = MagicMock()
            self.status_updated = MagicMock()
            self.conn_info_updated = MagicMock()
            self.finished = MagicMock()
            self.error = MagicMock()

        def start(self):
            return None

    monkeypatch.setattr("src.app.view.transfer_interface.DownloadThread", _FakeThread)
    interface._ensure_speed_timer = lambda: None

    interface._TransferInterface__start_download_task(task)

    assert task.pause_requested is False
    assert task.is_cancelled is False
    assert created_threads == [(False, False, interface.pan)]
    assert task.thread is not None


def test_upload_task_error_persists_error_message(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    task = interface.add_upload_task(
        "demo.bin",
        12,
        str(tmp_path / "demo.bin"),
        7,
    )

    interface._TransferInterface__task_error(task, "boom")

    stored = db.get_upload_task(task.db_task_id)
    assert stored is not None
    assert stored["status"] == "失败"
    assert stored["error"] == "boom"
    assert task.last_error == "boom"


def test_download_task_error_keeps_thread_until_terminal_cleanup(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    task = DownloadTask(
        file_name="demo.bin",
        file_size=12,
        file_id=1,
        save_path=str(tmp_path / "demo.bin"),
        account_name="alice",
    )
    db.save_download_task({
        "resume_id": task.resume_id,
        "account_name": "alice",
        "file_name": task.file_name,
        "file_id": task.file_id,
        "save_path": task.save_path,
    })

    class _FakeThread:
        def __init__(self):
            self.disconnected = False

        def disconnect(self):
            self.disconnected = True

    thread = _FakeThread()
    task.thread = thread
    interface.download_threads.append(thread)
    monkeypatch.setattr("src.app.view.transfer_interface.InfoBar.error", lambda **_kwargs: None)

    interface._TransferInterface__task_error(task, "boom")

    assert task.thread is thread
    assert task.last_error == "boom"

    interface._TransferInterface__update_task_status(task, "失败")

    assert thread.disconnected is True
    assert interface.download_threads == []
    stored = db.get_download_task(task.resume_id)
    assert stored is not None
    assert stored["status"] == "失败"
    assert stored["error"] == "boom"


def test_retry_upload_clears_stale_session_and_parts(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    task = interface.add_upload_task(
        "demo.bin",
        12,
        str(tmp_path / "demo.bin"),
        7,
    )
    task.status = "失败"
    task.bucket = "bucket"
    task.storage_node = "node"
    task.upload_key = "key"
    task.upload_id_s3 = "upload-id"
    task.up_file_id = 123
    task.total_parts = 4
    task.block_size = 5
    task.etag = "etag"
    task.progress = 66
    db.update_upload_task(
        task.db_task_id,
        bucket=task.bucket,
        storage_node=task.storage_node,
        upload_key=task.upload_key,
        upload_id_s3=task.upload_id_s3,
        up_file_id=task.up_file_id,
        total_parts=task.total_parts,
        block_size=task.block_size,
        etag=task.etag,
        progress=task.progress,
        status="失败",
        error="boom",
    )
    db.record_upload_part(task.db_task_id, 1, "etag-1")

    interface._TransferInterface__retry_upload(task)

    stored = db.get_upload_task(task.db_task_id)
    assert stored is not None
    assert stored["status"] == "等待中"
    assert stored["progress"] == 0
    assert stored["bucket"] == ""
    assert stored["upload_key"] == ""
    assert stored["upload_id_s3"] == ""
    assert stored["etag"] == ""
    assert stored["error"] == ""
    assert db.get_upload_parts(task.db_task_id) == []


def test_reload_upload_tasks_drops_persisted_delete_requested_items(tmp_path, monkeypatch):
    interface, db = _make_interface(tmp_path, monkeypatch)
    db.save_upload_task({
        "task_id": "upload-1",
        "account_name": "alice",
        "file_name": "demo.bin",
        "file_size": 12,
        "local_path": str(tmp_path / "demo.bin"),
        "target_dir_id": 7,
        "status": "已取消",
        "delete_requested": 1,
    })

    interface._TransferInterface__reload_upload_tasks()

    assert interface.upload_tasks == []
    assert db.get_upload_task("upload-1") is None


def test_bind_button_disconnects_previous_handler_only():
    interface = TransferInterface.__new__(TransferInterface)
    button = _FakeButton()

    first = lambda: None
    second = lambda: None

    interface._TransferInterface__bind_button(button, first)
    interface._TransferInterface__bind_button(button, second)

    assert button.clicked.disconnected == [first]
    assert button.clicked.connected == [second]


def test_configure_upload_actions_disables_primary_button_without_receivers_call():
    interface = TransferInterface.__new__(TransferInterface)
    primary = _FakeButton()
    secondary = _FakeButton()
    primary._transfer_click_handler = lambda: None
    primary.receivers = MagicMock(side_effect=AssertionError("receivers should not be used"))
    widget = type(
        "_Widget",
        (),
        {"primary_button": primary, "secondary_button": secondary},
    )()
    task = type("_Task", (), {"status": "已完成"})()

    interface._TransferInterface__get_or_create_actions = lambda *_args: widget
    interface._TransferInterface__remove_task = lambda *_args: None
    interface.uploadTable = object()

    interface._TransferInterface__configure_upload_actions(0, task)

    assert primary.text == ""
    assert primary.enabled is False
    assert primary.clicked.disconnected
