"""BNOS AI 伴侣 — 新 GUI 入口

数据流：GUI -> gui_input.json -> gui_adapter -> user_input -> aaa_cognition
                                     <- aaa_cognition/output.json <-
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
