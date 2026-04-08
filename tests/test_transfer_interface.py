from pathlib import Path

from src.app.common import database as database_module
from src.app.common.database import Database
from src.app.view.transfer_interface import DownloadTask, TransferInterface


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
    interface.download_status_filter = "全部"
    interface.current_account_name = "alice"
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
