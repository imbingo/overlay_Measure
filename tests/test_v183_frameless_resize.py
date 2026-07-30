from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from overlay_measure.ui_main import MainWindow


def test_frameless_window_exposes_all_resize_edges_and_corners():
    hit = MainWindow._frameless_hit_test
    bounds = (100, 200, 1100, 900)
    margin = 8

    assert hit(100, 200, *bounds, margin) == MainWindow._HTTOPLEFT
    assert hit(1099, 200, *bounds, margin) == MainWindow._HTTOPRIGHT
    assert hit(100, 899, *bounds, margin) == MainWindow._HTBOTTOMLEFT
    assert hit(1099, 899, *bounds, margin) == MainWindow._HTBOTTOMRIGHT
    assert hit(100, 500, *bounds, margin) == MainWindow._HTLEFT
    assert hit(1099, 500, *bounds, margin) == MainWindow._HTRIGHT
    assert hit(500, 200, *bounds, margin) == MainWindow._HTTOP
    assert hit(500, 899, *bounds, margin) == MainWindow._HTBOTTOM
    assert hit(500, 500, *bounds, margin) == MainWindow._HTCLIENT


def test_frameless_window_keeps_declared_safe_minimum_size():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.minimumWidth() == 1120
    assert window.minimumHeight() == 720

    window.close()
    app.processEvents()
