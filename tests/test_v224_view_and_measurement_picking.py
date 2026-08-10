from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from overlay_measure.models import DetectionResult, ImageData, MarkRecipe
from overlay_measure.ui_main import ImageCanvas, MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _image(size: int = 240) -> ImageData:
    gray = np.zeros((size, size), dtype=np.float32)
    return ImageData("roi.png", gray, "roi.png", "uint8", 0.0, 255.0)


def _detection() -> DetectionResult:
    return DetectionResult(
        mark_id="Mark1", layer="upper", center_x_px=25.0, center_y_px=25.0,
        center_x_um=2.5, center_y_um=2.5, diameter_px=20.0, diameter_um=2.0,
        residual_px=0.1, residual_um=0.01, edge_point_count=64, confidence=0.98,
        fitting_mode="Circle", shape_params={"radius_px": 10.0, "quality_status": "Valid"},
    )


def _press(x, y):
    point = QPointF(float(x), float(y))
    return QMouseEvent(
        QEvent.MouseButtonPress, point, point, point,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )


def test_rebinding_same_image_preserves_zoom_and_pan():
    app = _app()
    canvas = ImageCanvas("view", fixed_layer="upper")
    canvas.resize(640, 480)
    image = _image()
    canvas.set_image(image)
    canvas.user_zoom = 4.0
    canvas.pan_x = 73.0
    canvas.pan_y = -41.0
    canvas.set_image(image)
    assert canvas.user_zoom == 4.0
    assert canvas.pan_x == 73.0
    assert canvas.pan_y == -41.0
    canvas.close()
    app.processEvents()


def test_geometry_click_on_circle_contour_snaps_to_detection_center():
    app = _app()
    canvas = ImageCanvas("pick", fixed_layer="upper")
    canvas.resize(640, 480)
    canvas.set_image(_image())
    detection = _detection()
    canvas.set_context(
        "Mark1", "upper", {"Mark1": MarkRecipe("Mark1")}, {},
        roi_detections={"Mark1": {"upper-1": detection}}, active_roi_id="",
    )
    canvas.set_geometry_interaction_active(True)
    picked = []
    canvas.geometryClicked.connect(lambda layer, payload: picked.append((layer, payload)))
    canvas.show()
    app.processEvents()
    x, y = canvas.image_to_widget(35.0, 25.0)
    canvas.mousePressEvent(_press(x, y))
    assert len(picked) == 1
    payload = picked[0][1]
    assert payload["detection_key"] == "Mark1/upper-1:upper"
    assert payload["feature_type"] == "circle"
    assert payload["snapped_to_center"] is True
    assert payload["point_px"] == pytest.approx((25.0, 25.0))
    canvas.close()
    app.processEvents()


def test_manual_geometry_point_remains_a_raw_click_without_snapping():
    app = _app()
    canvas = ImageCanvas("manual point", fixed_layer="upper")
    canvas.resize(640, 480)
    canvas.set_image(_image())
    detection = _detection()
    canvas.set_context(
        "Mark1", "upper", {"Mark1": MarkRecipe("Mark1")}, {},
        roi_detections={"Mark1": {"upper-1": detection}}, active_roi_id="",
    )
    canvas.set_geometry_context(None, None, True, {"action": "feature:point", "clicks": [], "layer": "upper"})
    picked = []
    canvas.geometryClicked.connect(lambda layer, payload: picked.append(payload))
    canvas.show()
    app.processEvents()
    x, y = canvas.image_to_widget(35.0, 25.0)
    canvas.mousePressEvent(_press(x, y))
    assert picked[0]["detection_key"] == ""
    assert picked[0]["snapped_to_center"] is False
    assert picked[0]["point_px"] == pytest.approx((35.0, 25.0))
    canvas.close()
    app.processEvents()


def test_center_distance_rejects_blank_click_instead_of_creating_point():
    app = _app()
    window = MainWindow()
    interaction = {"action": "measurement:center_distance", "clicks": []}
    valid, message = window._validate_geometry_pick(
        interaction,
        {"point_px": (10.0, 10.0), "feature_id": "", "detection_key": "", "feature_type": ""},
    )
    assert valid is False
    assert "圆" in message
    valid, _ = window._validate_geometry_pick(
        interaction,
        {
            "point_px": (25.0, 25.0), "feature_id": "", "detection_key": "Mark1/upper-1:upper",
            "feature_type": "circle", "snapped_to_center": True,
        },
    )
    assert valid is True
    window.close()
    app.processEvents()
