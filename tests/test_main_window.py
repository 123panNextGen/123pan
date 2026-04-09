import sys
from unittest.mock import MagicMock

sys.modules.setdefault("qrcode", MagicMock())

from src.app.view.main_window import MainWindow


def test_stop_all_transfers_uses_thread_lists():
    window = MainWindow.__new__(MainWindow)
    upload_thread = MagicMock()
    download_thread = MagicMock()
    window.transfer_interface = type(
        "_Transfer",
        (),
        {
            "upload_threads": [upload_thread],
            "download_threads": [download_thread],
            "upload_tasks": [],
            "download_tasks": [],
        },
    )()

    MainWindow._stop_all_transfers(window)

    upload_thread.cancel.assert_called_once()
    upload_thread.wait.assert_called_once_with(5000)
    download_thread.cancel.assert_called_once()
    download_thread.wait.assert_called_once_with(5000)
