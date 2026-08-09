from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from overlay_measure.image_loader import load_image
from overlay_measure.measurement_engine import run_measurement_job
from overlay_measure.recipe_manager import load_recipe, save_recipe
from overlay_measure.models import Roi
from overlay_measure.ui_main import MainWindow


SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def _job(mark, selection=None):
    config, params, _ = load_recipe(str(SAMPLE_DIR / "demo_recipe.json"))
    config.workflow_mode = "Manual"
    upper = load_image(str(SAMPLE_DIR / "sample_upper.png"))
    lower = load_image(str(SAMPLE_DIR / "sample_lower.png"))
    return {
        "config": config,
        "params": params,
        "marks": {"Mark1": mark, "Mark2": type(mark)("Mark2")},
        "mark_images": {
            "Mark1": {"upper": upper, "lower": lower},
            "Mark2": {"upper": None, "lower": None},
        },
        "batch_images": {
            "Mark1": {"upper": [], "lower": []},
            "Mark2": {"upper": [], "lower": []},
        },
        "selections": {"Mark1": selection or {}, "Mark2": {}},
        "batch": False,
    }


def test_manual_measurement_detects_every_roi_and_defaults_across_layers():
    _, _, marks = load_recipe(str(SAMPLE_DIR / "demo_recipe.json"))
    mark = marks[0]
    second = mark.add_roi("upper", deepcopy(mark.upper_roi), roi_id="upper-extra")

    payload = run_measurement_job(
        _job(mark),
        lambda done, total, message: None,
        lambda: False,
    )

    detections = payload["detections"]["Mark1"]
    assert list(detections) == ["upper-1", second.roi_id, "lower-1"]
    assert detections[second.roi_id].shape_params["roi_index"] == 2
    assert payload["selections"]["Mark1"] == {
        "reference_label": "upper-1",
        "target_label": "lower-1",
    }
    assert payload["overlays"]["Mark1"].reference_contour_id == "upper-1"
    assert payload["overlays"]["Mark1"].target_contour_id == "lower-1"


def test_missing_explicit_roi_selection_is_not_silently_replaced():
    _, _, marks = load_recipe(str(SAMPLE_DIR / "demo_recipe.json"))
    mark = marks[0]
    payload = run_measurement_job(
        _job(mark, {"reference_label": "deleted-roi", "target_label": "lower-1"}),
        lambda done, total, message: None,
        lambda: False,
    )

    assert payload["selections"]["Mark1"]["reference_label"] == ""
    assert payload["selections"]["Mark1"]["target_label"] == "lower-1"
    assert payload["overlays"]["Mark1"].result == "Error"


def test_recipe_round_trip_preserves_roi_ids_and_contour_selection(tmp_path):
    config, params, marks = load_recipe(str(SAMPLE_DIR / "demo_recipe.json"))
    mark = marks[0]
    mark.add_roi("upper", deepcopy(mark.upper_roi), roi_id="upper-stable-id")
    mark.reference_contour_id = "upper-stable-id"
    mark.target_contour_id = "lower-1"
    path = tmp_path / "multi-roi.json"

    save_recipe(str(path), config, params, marks)
    _, _, restored_marks = load_recipe(str(path))
    restored = restored_marks[0]

    assert [entry.roi_id for entry in restored.upper_rois] == ["upper-1", "upper-stable-id"]
    assert [entry.roi_id for entry in restored.lower_rois] == ["lower-1"]
    assert restored.reference_contour_id == "upper-stable-id"
    assert restored.target_contour_id == "lower-1"


def test_ui_switches_copies_and_deletes_rois_without_changing_stable_ids(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._set_operation_mode("Engineering", authenticated=True)
    mark = window.marks["Mark1"]
    first = mark.add_roi("upper", Roi(10, 10, 30, 30, "Circle"), roi_id="stable-a")
    second = mark.add_roi("upper", Roi(50, 10, 30, 30, "Rectangle"), roi_id="stable-b")
    third = mark.add_roi("upper", Roi(90, 10, 30, 30, "Ellipse"), roi_id="stable-c")
    fourth = mark.add_roi("upper", Roi(130, 10, 30, 30, "Robust Center"), roi_id="stable-d")
    window._refresh_roi_index_combo(first.roi_id)

    assert window.roi_index_combo.count() == 4
    window.select_roi_from_canvas("Mark1", "upper", third.roi_id)
    assert window.roi_index_combo.currentData() == third.roi_id

    window.copy_current_roi()
    copied_id = window.roi_index_combo.currentData()
    assert copied_id not in {first.roi_id, second.roi_id, third.roi_id, fourth.roi_id}
    assert window.roi_index_combo.count() == 5

    window._refresh_roi_index_combo(second.roi_id)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    window.delete_current_roi()

    assert [entry.roi_id for entry in mark.upper_rois] == [
        "stable-a", "stable-c", "stable-d", copied_id,
    ]
    assert [window.roi_index_combo.itemText(i) for i in range(4)] == [
        "ROI 1", "ROI 2", "ROI 3", "ROI 4",
    ]
    window.close()
    app.processEvents()
