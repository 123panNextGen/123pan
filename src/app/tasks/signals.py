from PyQt6.QtCore import QObject, pyqtSignal


class _LoadListSignals(QObject):
    finished = pyqtSignal(list, str)


class _OpFinishedSignals(QObject):
    finished = pyqtSignal(bool, str, str, str, list, list)


class _StorageSignals(QObject):
    finished = pyqtSignal(str)
