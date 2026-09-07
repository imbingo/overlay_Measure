import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from overlay_measure.ui_main import MainWindow


@pytest.mark.parametrize('mode,canvas,layer', [
    ('Single Image', 'upper_canvas', 'upper'),
    ('Dual Image', 'upper_canvas', 'upper'),
    ('Dual Image', 'lower_canvas', 'lower'),
])
def test_drop_routes_to_canvas(tmp_path, mode, canvas, layer):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.config.mode = mode
    path = tmp_path / 'image.npy'
    np.save(path, np.zeros((80, 80), np.float32))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    getattr(window, canvas).dropEvent(event)
    assert event.isAccepted()
    assert window.mark_images['Mark1'][layer].path == str(path)
    assert window.mark_images['Mark1']['lower' if layer == 'upper' else 'upper'] is None
    window.close()


def test_busy_and_corrupt_drop_preserve_image(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    path = tmp_path / 'image.npy'
    np.save(path, np.zeros((80, 80), np.float32))
    window.import_dropped_image(str(path), 'upper')
    previous = window.mark_images['Mark1']['upper']
    window._calculation_running = True
    window.import_dropped_image(str(path), 'upper')
    assert window.mark_images['Mark1']['upper'] is previous
    window._calculation_running = False
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: QMessageBox.Ok)
    path.write_bytes(b'broken')
    window.import_dropped_image(str(path), 'upper')
    assert window.mark_images['Mark1']['upper'] is previous
    window.close()
