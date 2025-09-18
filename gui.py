from __future__ import annotations

import sys
from typing import Sequence

from PyQt6.QtWidgets import QApplication

from gui_main_window import launch_gui

def launch(argv: Sequence[str] | None = None) -> None:
    args = list(argv) if argv is not None else sys.argv
    app = QApplication(args)
    window = launch_gui(app)
    app.exec()

