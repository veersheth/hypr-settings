from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from common import make_centered


class AboutTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(make_centered(self))
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.setAlignment(Qt.AlignTop)

        body = QLabel(
            "hypr-settings is a graphical settings panel for Hyprland. "
            "It lets you change the most important settings on the fly, "
            "without touching a config file or opening a terminal.\n\n"
            "Covers displays, workspaces, sound, Bluetooth, Wi-Fi, and appearance."
        )
        body.setWordWrap(True)
        body.setObjectName("statusLabel")
        root.addWidget(body)

        links = QLabel(
            '<a href="https://veersheth.in">veersheth.in</a>'
            '&nbsp;&nbsp;|&nbsp;&nbsp;'
            '<a href="https://github.com/veersheth/hypr-settings">GitHub</a>'
        )
        links.setOpenExternalLinks(True)
        links.setObjectName("statusLabel")
        root.addWidget(links)

        root.addStretch()
