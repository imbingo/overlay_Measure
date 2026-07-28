from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from overlay_measure.models import DetectionResult, ImageData, MarkRecipe, Roi
from overlay_measure.ui_main import ImageCanvas


def _image() -> ImageData:
    gray = np.zeros((128, 128), dtype=np.float32)
    return ImageData("circle.png", gray, "circle.png", "uint8", 0.0, 255.0)


def _detection(
    *,
    mode: str = "CaliperCircle",
    quality: str = "Valid",
    center: tuple[float, float] = (64.0, 64.0),
) -> DetectionResult:
    cx, cy = center
    shape_params = {
        "radius_px": 20.0,
        "width_px": 40.0,
        "height_px": 32.0,
        "angle_deg": 0.0,
        "quality_status": quality,
        "caliper_windows": [
            {
                "angle": 0.0,
                "center_x": cx + 20.0,
                "center_y": cy,
                "length": 12.0,
            }
        ],
    }
    return DetectionResult(
        mark_id="Mark1",
        layer="upper",
        center_x_px=cx,
        center_y_px=cy,
        center_x_um=cx,
        center_y_um=cy,
        diameter_px=40.0,
        diameter_um=40.0,
        residual_px=0.2,
        residual_um=0.2,
        edge_point_count=32,
        confidence=0.5,
        fitting_mode=mode,
        edge_points=[(cx + 20.0, cy)],
        rejected_points=[(cx - 20.0, cy)],
        shape_params=shape_params,
    )


def _mouse_press(x: float, y: float) -> QMouseEvent:
    point = QPointF(float(x), float(y))
    return QMouseEvent(
        QEvent.MouseButtonPress,
        point,
        point,
        point,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )


def _show_canvas() -> tuple[QApplication, ImageCanvas]:
    app = QApplication.instance() or QApplication([])
    canvas = ImageCanvas("卡尺显示测试", fixed_layer="upper")
    canvas.resize(640, 480)
    canvas.set_image(_image())
    canvas.show()
    app.processEvents()
    return app, canvas


@pytest.mark.parametrize("quality", ["Valid", "Tolerant", "Invalid"])
def test_manual_caliper_is_hidden_after_any_detection_quality(quality):
    app, canvas = _show_canvas()
    roi = Roi(34.0, 34.0, 60.0, 60.0, "Caliper Circle", 0.5)
    mark = MarkRecipe("Mark1", upper_roi=roi)
    detection = _detection(quality=quality)
    canvas.set_context(
        "Mark1",
        "upper",
        {"Mark1": mark},
        {"Mark1": {"upper": detection}},
        show_diagnostics=True,
    )

    assert not canvas._manual_roi_visible("Mark1", "upper", roi, detection)

    canvas.close()
    app.processEvents()


def test_manual_caliper_stays_visible_when_detection_did_not_exist():
    app, canvas = _show_canvas()
    roi = Roi(34.0, 34.0, 60.0, 60.0, "Caliper Circle", 0.5)
    mark = MarkRecipe("Mark1", upper_roi=roi)
    canvas.set_context("Mark1", "upper", {"Mark1": mark}, {})

    assert canvas._manual_roi_visible("Mark1", "upper", roi, None)

    canvas.close()
    app.processEvents()


def test_clicking_manual_fit_reveals_caliper_and_blank_click_hides_it():
    app, canvas = _show_canvas()
    roi = Roi(34.0, 34.0, 60.0, 60.0, "Caliper Circle", 0.5)
    mark = MarkRecipe("Mark1", upper_roi=roi)
    detection = _detection(quality="Invalid")
    canvas.set_context(
        "Mark1",
        "upper",
        {"Mark1": mark},
        {"Mark1": {"upper": detection}},
    )
    app.processEvents()

    hit_x, hit_y = canvas.image_to_widget(84.0, 64.0)
    canvas.mousePressEvent(_mouse_press(hit_x, hit_y))
    assert canvas._manual_caliper_selected("Mark1", "upper", detection)
    assert canvas._manual_roi_visible("Mark1", "upper", roi, detection)

    canvas.mousePressEvent(_mouse_press(8.0, canvas.height() - 8.0))
    assert canvas.selected_caliper_feature is None

    canvas.close()
    app.processEvents()


@pytest.mark.parametrize("mode", ["ProductionCircle", "ProductionRectangle"])
def test_clicking_one_auto_feature_only_selects_its_calipers(mode):
    app, canvas = _show_canvas()
    first = _detection(mode=mode, center=(44.0, 64.0))
    second = _detection(mode=mode, center=(90.0, 64.0))
    canvas.set_context(
        "Mark1",
        "upper",
        {},
        {},
        auto_detections={
            "a": {"upper": first},
            "b": {"upper": second},
        },
        show_auto_detections=True,
        show_diagnostics=True,
    )
    app.processEvents()

    hit_x, hit_y = canvas.image_to_widget(64.0, 64.0)
    canvas.mousePressEvent(_mouse_press(hit_x, hit_y))

    assert canvas._auto_caliper_selected("a", "upper", first)
    assert not canvas._auto_caliper_selected("b", "upper", second)

    canvas.mousePressEvent(_mouse_press(8.0, canvas.height() - 8.0))
    assert canvas.selected_caliper_feature is None

    canvas.close()
    app.processEvents()


def test_new_detection_object_automatically_closes_caliper_editor():
    app, canvas = _show_canvas()
    roi = Roi(34.0, 34.0, 60.0, 60.0, "Caliper Circle", 0.5)
    mark = MarkRecipe("Mark1", upper_roi=roi)
    first = _detection()
    canvas.set_context("Mark1", "upper", {"Mark1": mark}, {"Mark1": {"upper": first}})
    canvas._select_caliper_detection("manual", "Mark1", "upper", first)

    replacement = _detection()
    canvas.set_context(
        "Mark1",
        "upper",
        {"Mark1": mark},
        {"Mark1": {"upper": replacement}},
    )

    assert canvas.selected_caliper_feature is None
    assert not canvas._manual_roi_visible("Mark1", "upper", roi, replacement)

    canvas.close()
    app.processEvents()
