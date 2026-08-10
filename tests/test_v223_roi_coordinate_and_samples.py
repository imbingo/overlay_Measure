from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from overlay_measure.geometry_models import (
    CoordinateSystemDefinition,
    CoordinateSystemResult,
    GeometryFeatureDefinition,
    GeometryProgram,
    GeometryRunResult,
)
from overlay_measure.image_loader import load_image
from overlay_measure.measurement_service import detect_manual_roi
from overlay_measure.models import DetectionResult, ImageData, MarkRecipe, Roi
from overlay_measure.recipe_manager import load_recipe
from overlay_measure.ui_geometry import CoordinateSystemSelectorDialog
from overlay_measure.ui_main import ImageCanvas, MainWindow


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "sample_data" / "v2_2_3_hole_array"


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


def _mouse(kind, x, y, button=Qt.LeftButton, buttons=Qt.LeftButton):
    point = QPointF(float(x), float(y))
    return QMouseEvent(kind, point, point, point, button, buttons, Qt.NoModifier)


def _canvas_with_roi(roi: Roi, roi_id: str = "upper-1"):
    app = _app()
    canvas = ImageCanvas("ROI interaction", fixed_layer="upper")
    canvas.resize(640, 480)
    canvas.set_image(_image())
    mark = MarkRecipe("Mark1")
    entry = mark.add_roi("upper", roi, "manual")
    entry.roi_id = roi_id
    canvas.set_context("Mark1", "upper", {"Mark1": mark}, {}, active_roi_id=roi_id)
    canvas.roi_editing_enabled = True
    canvas.show()
    app.processEvents()
    return app, canvas, mark


def test_circle_drag_creation_is_square_and_tiny_drag_reports_message():
    app = _app()
    canvas = ImageCanvas("new ROI", fixed_layer="upper")
    canvas.resize(640, 480)
    canvas.set_image(_image())
    canvas.set_context("Mark1", "upper", {"Mark1": MarkRecipe("Mark1")}, {}, roi_type="Circle", active_roi_id="")
    canvas.roi_editing_enabled = True
    created = []
    messages = []
    canvas.roiChanged.connect(lambda mark, layer, roi: created.append(roi))
    canvas.interactionMessage.connect(messages.append)
    canvas.show()
    app.processEvents()

    x0, y0 = canvas.image_to_widget(30, 40)
    x1, y1 = canvas.image_to_widget(110, 80)
    canvas.mousePressEvent(_mouse(QEvent.MouseButtonPress, x0, y0))
    canvas.mouseMoveEvent(_mouse(QEvent.MouseMove, x1, y1, Qt.NoButton, Qt.LeftButton))
    canvas.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, x1, y1, Qt.LeftButton, Qt.NoButton))
    assert len(created) == 1
    assert created[0].roi_type == "Circle"
    assert abs(created[0].w - created[0].h) < 1e-9

    x2, y2 = canvas.image_to_widget(150, 150)
    x3, y3 = canvas.image_to_widget(152, 152)
    canvas.mousePressEvent(_mouse(QEvent.MouseButtonPress, x2, y2))
    canvas.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, x3, y3, Qt.LeftButton, Qt.NoButton))
    assert messages
    canvas.close()


def test_selected_roi_move_commits_once_and_escape_cancels_preview():
    app, canvas, _ = _canvas_with_roi(Roi(50, 50, 80, 80, "Circle"))
    committed = []
    canvas.roiEditCommitted.connect(lambda *args: committed.append(args))

    center_x, center_y = canvas.image_to_widget(90, 90)
    target_x, target_y = canvas.image_to_widget(110, 100)
    canvas.mousePressEvent(_mouse(QEvent.MouseButtonPress, center_x, center_y))
    canvas.mouseMoveEvent(_mouse(QEvent.MouseMove, target_x, target_y, Qt.NoButton, Qt.LeftButton))
    canvas.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, target_x, target_y, Qt.LeftButton, Qt.NoButton))
    assert len(committed) == 1
    assert committed[0][2] == "upper-1"
    assert committed[0][3].center() == (110.0, 100.0)

    canvas.mousePressEvent(_mouse(QEvent.MouseButtonPress, center_x, center_y))
    canvas.mouseMoveEvent(_mouse(QEvent.MouseMove, target_x, target_y, Qt.NoButton, Qt.LeftButton))
    canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert len(committed) == 1
    assert canvas.roi_edit_preview is None
    canvas.close()
    app.processEvents()


def test_circle_outer_handle_resizes_without_moving_center():
    app, canvas, _ = _canvas_with_roi(Roi(50, 50, 80, 80, "Caliper Circle", 0.5))
    committed = []
    canvas.roiEditCommitted.connect(lambda *args: committed.append(args))
    handle_x, handle_y = canvas._roi_handle_points()["outer_e"]
    target_x, target_y = canvas.image_to_widget(145, 90)
    canvas.mousePressEvent(_mouse(QEvent.MouseButtonPress, handle_x, handle_y))
    canvas.mouseMoveEvent(_mouse(QEvent.MouseMove, target_x, target_y, Qt.NoButton, Qt.LeftButton))
    canvas.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, target_x, target_y, Qt.LeftButton, Qt.NoButton))
    assert len(committed) == 1
    resized = committed[0][3]
    assert resized.center() == (90.0, 90.0)
    assert resized.w == resized.h == 110.0
    canvas.close()
    app.processEvents()


def test_overlapping_rois_prefer_current_then_topmost():
    app = _app()
    canvas = ImageCanvas("overlap", fixed_layer="upper")
    canvas.resize(640, 480)
    canvas.set_image(_image())
    mark = MarkRecipe("Mark1")
    first = mark.add_roi("upper", Roi(40, 40, 100, 100, "Rectangle"), "manual")
    second = mark.add_roi("upper", Roi(60, 60, 100, 100, "Rectangle"), "manual")
    canvas.set_context("Mark1", "upper", {"Mark1": mark}, {}, active_roi_id=first.roi_id)
    canvas.show()
    app.processEvents()
    x, y = canvas.image_to_widget(90, 90)
    assert canvas._manual_roi_hit(QPointF(x, y)) == first.roi_id
    canvas.set_context("Mark1", "upper", {"Mark1": mark}, {}, active_roi_id="")
    assert canvas._manual_roi_hit(QPointF(x, y)) == second.roi_id
    canvas.close()
    app.processEvents()


def test_coordinate_selector_previews_and_rejects_invalid_coordinate():
    app = _app()
    selected = []
    coordinates = [
        {
            "coordinate_id": "CS1", "display_name": "上层-两圆心建轴-1 [CS1]",
            "layer_label": "上层", "method_label": "两圆心建轴", "rotation_deg": 0.25,
            "origin_text": "(10.000, 20.000) px", "references_text": "圆1、圆2",
            "valid": True, "error": "",
        },
        {
            "coordinate_id": "CS2", "display_name": "上层-两点建轴-2 [CS2]",
            "layer_label": "上层", "method_label": "两点建轴", "rotation_deg": 0.0,
            "origin_text": "未计算", "references_text": "点1、点2",
            "valid": False, "error": "引用点已删除",
        },
    ]
    dialog = CoordinateSystemSelectorDialog(coordinates, preview_callback=selected.append)
    dialog.show()
    app.processEvents()
    assert dialog.selected_coordinate_id() == "CS1"
    assert selected[-1] == "CS1"
    dialog.list_widget.setCurrentRow(1)
    app.processEvents()
    assert selected[-1] == "CS2"
    assert dialog.selected_coordinate_id() == ""
    assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert "引用点已删除" in dialog.details_label.text()
    dialog.close()


def test_coordinate_items_are_layer_scoped_and_have_readable_legacy_name():
    app = _app()
    window = MainWindow()
    window.geometry_program = GeometryProgram(
        features=[GeometryFeatureDefinition("F1", "圆1", "upper", "circle")],
        coordinate_systems=[
            CoordinateSystemDefinition("CS1", "CS1", "upper", "two_centers", ["F1"], 1.5),
            CoordinateSystemDefinition("CS2", "下层轴", "lower", "two_points", [], 0.0),
        ],
    )
    window.geometry_result = GeometryRunResult(
        coordinate_systems={
            "CS1": CoordinateSystemResult("CS1", "CS1", "upper", "Valid", (10, 20), (1, 0), (0, -1), 1.5),
        }
    )
    items = window._coordinate_selector_items("upper")
    assert [item["coordinate_id"] for item in items] == ["CS1"]
    assert "CS1" in items[0]["display_name"]
    assert items[0]["valid"]
    window.close()
    app.processEvents()


def test_coordinate_creation_keeps_stable_id_and_readable_default_name(monkeypatch):
    app = _app()
    window = MainWindow()
    window.geometry_program.features = [
        GeometryFeatureDefinition("F1", "圆1", "upper", "circle"),
        GeometryFeatureDefinition("F2", "圆2", "upper", "circle"),
    ]
    monkeypatch.setattr("overlay_measure.ui_geometry.QInputDialog.getDouble", lambda *args, **kwargs: (1.25, True))
    monkeypatch.setattr("overlay_measure.ui_geometry.QInputDialog.getText", lambda *args, **kwargs: ("", False))
    window._finish_geometry_interaction({
        "action": "coordinate", "clicks": [{"feature_id": "F1"}, {"feature_id": "F2"}],
        "layer": "upper", "method": "two_centers",
    })
    coordinate = window.geometry_program.coordinate_systems[0]
    assert coordinate.coordinate_id == "CS1"
    assert coordinate.name == "上层-两圆心建轴-1"
    assert coordinate.rotation_deg == 1.25
    window.close()
    app.processEvents()


def test_canvas_edit_commit_invalidates_only_one_roi_and_adds_one_undo():
    app = _app()
    window = MainWindow()
    window.operation_mode = "Engineering"
    first = window.marks["Mark1"].add_roi("upper", Roi(10, 10, 30, 30, "Circle"), "manual")
    second = window.marks["Mark1"].add_roi("upper", Roi(80, 80, 30, 30, "Circle"), "manual")
    window.roi_detections["Mark1"][first.roi_id] = _detection()
    window.roi_detections["Mark1"][second.roi_id] = _detection()
    before = len(window._roi_undo_stack)
    window.commit_canvas_roi_edit("Mark1", "upper", first.roi_id, Roi(20, 25, 30, 30, "Circle"))
    assert len(window._roi_undo_stack) == before + 1
    assert first.roi_id not in window.roi_detections["Mark1"]
    assert second.roi_id in window.roi_detections["Mark1"]
    assert window.marks["Mark1"].roi_entry("upper", first.roi_id).roi.x == 20
    window.close()
    app.processEvents()


def test_hole_array_assets_match_ground_truth_and_recipe():
    required = {
        "hole_array_upper.png", "hole_array_lower.png", "hole_array_ground_truth.json",
        "hole_array_v2_2_3_recipe.json", "README_孔阵列测试说明.md",
    }
    assert required.issubset({path.name for path in SAMPLES.iterdir()})
    truth = json.loads((SAMPLES / "hole_array_ground_truth.json").read_text(encoding="utf-8"))
    recipe = json.loads((SAMPLES / "hole_array_v2_2_3_recipe.json").read_text(encoding="utf-8"))
    assert truth["hole_diameter_um"] == 120.0
    assert truth["array"] == {"columns": 5, "rows": 4, "pitch_um": 200.0}
    assert len(truth["holes"]) == 20
    assert truth["lower_relative_to_upper_image_px"] == {"x": 3.4, "y": -2.6}
    assert len(recipe["marks"][0]["upper_rois"]) == 20
    assert len(recipe["marks"][0]["lower_rois"]) == 20
    assert recipe["measurement_config"]["pixel_size_x_um"] == 1.0


def test_hole_array_first_and_last_holes_match_known_centers_and_diameter():
    config, params, marks = load_recipe(str(SAMPLES / "hole_array_v2_2_3_recipe.json"))
    truth = json.loads((SAMPLES / "hole_array_ground_truth.json").read_text(encoding="utf-8"))
    mark = marks[0]
    for layer, filename, center_key in (
        ("upper", "hole_array_upper.png", "upper_center_px"),
        ("lower", "hole_array_lower.png", "lower_center_px"),
    ):
        image = load_image(str(SAMPLES / filename))
        entries = mark.roi_entries(layer)
        for entry, hole in ((entries[0], truth["holes"][0]), (entries[-1], truth["holes"][-1])):
            detection = detect_manual_roi(mark.mark_id, layer, image, entry.roi, params, config)
            expected = hole[center_key]
            assert detection.center_x_px == pytest.approx(expected["x"], abs=0.5)
            assert detection.center_y_px == pytest.approx(expected["y"], abs=0.5)
            assert detection.diameter_um == pytest.approx(120.0, abs=0.5)
