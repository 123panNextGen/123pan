from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class TransferInterface(QWidget):
    """传输页面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("TransferInterface")

        self.vBoxLayout = QVBoxLayout(self)
        self.label = QLabel("传输", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vBoxLayout.addWidget(self.label)
