from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from overlay_measure.export_visualization import render_measurement_image
from overlay_measure.models import DetectionResult, ImageData, MarkRecipe, Roi
from overlay_measure.ui_main import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _image(path: Path) -> ImageData:
    gray = np.full((120, 180), 128, dtype=np.float32)
    return ImageData(gray=gray, path=str(path), display_name=path.name, source_dtype="uint8", source_min=0, source_max=255)


def _detection() -> DetectionResult:
    return DetectionResult(
        mark_id="Mark1", layer="upper", center_x_px=70.0, center_y_px=50.0,
        center_x_um=7.0, center_y_um=5.0, diameter_px=40.0, diameter_um=4.0,
        fitting_mode="Circle", residual_px=0.05, residual_um=0.005, edge_point_count=64, confidence=0.98,
        shape_params={"radius_px": 20.0, "quality_status": "Valid"},
    )


def test_right_panel_uses_canvas_driven_roi_management():
    app = _app()
    window = MainWindow()
    window.operation_mode = "Engineering"
    app.processEvents()
    for removed in (
        "add_roi_btn", "copy_roi_btn", "delete_roi_btn", "roi_source_label",
        "apply_roi_params_btn", "clear_current_roi_btn", "clear_recipe_rois_btn",
        "geometry_delete_btn", "geometry_clear_btn",
    ):
        assert not hasattr(window, removed)
    assert window.roi_index_combo.currentIndex() == -1
    window.close()


def test_blank_canvas_state_creates_new_roi_instead_of_overwriting():
    app = _app()
    window = MainWindow()
    window.operation_mode = "Engineering"
    first = window.marks["Mark1"].add_roi("upper", Roi(10, 10, 30, 30), "manual")
    window._refresh_roi_index_combo(first.roi_id)
    window.clear_roi_selection("Mark1", "upper")
    window.set_roi("Mark1", "upper", Roi(60, 40, 25, 25), "manual")
    app.processEvents()
    entries = window.marks["Mark1"].roi_entries("upper")
    assert len(entries) == 2
    assert entries[0].roi_id == first.roi_id
    assert entries[1].roi.x == 60
    window.close()


def test_roi_parameter_edit_invalidates_only_stale_result():
    app = _app()
    window = MainWindow()
    window.operation_mode = "Engineering"
    entry = window.marks["Mark1"].add_roi("upper", Roi(10, 10, 30, 30, "Circle"), "manual")
    window.roi_detections["Mark1"][entry.roi_id] = _detection()
    window._refresh_roi_index_combo(entry.roi_id)
    window.on_active_roi_selection_changed()
    window.center_x_spin.setValue(window.center_x_spin.value() + 2.0)
    app.processEvents()
    assert entry.roi_id not in window.roi_detections["Mark1"]
    window.close()


def test_image_source_shows_parent_folder_and_filename(tmp_path):
    app = _app()
    folder = tmp_path / "sample_folder"
    folder.mkdir()
    source = folder / "upper.png"
    Image.new("L", (8, 8), 120).save(source)
    window = MainWindow()
    window.mark_images["Mark1"]["upper"] = _image(source)
    window._sync_current_mark_images()
    window._refresh_all_widgets()
    assert "sample_folder / upper.png" in window.upper_file_label.text()
    window.close()


def test_full_image_export_preserves_canvas_and_draws_green_fit(tmp_path):
    source = tmp_path / "input.png"
    output = tmp_path / "annotated.png"
    image = _image(source)
    assert render_measurement_image(
        image,
        output,
        [("ROI 1", Roi(35, 15, 70, 70, "Circle"))],
        {"ROI 1": _detection()},
    )
    rendered = np.asarray(Image.open(output).convert("RGB"))
    assert rendered.shape[:2] == image.gray.shape
    green = (rendered[:, :, 1] > 170) & (rendered[:, :, 0] < 100)
    assert int(green.sum()) > 20


def test_geometry_backspace_undoes_last_pick():
    app = _app()
    window = MainWindow()
    window.start_geometry_feature("line")
    window._geometry_interaction["clicks"].append({"point_px": (10.0, 10.0)})
    window.handle_geometry_command("undo")
    assert window._geometry_interaction["clicks"] == []
    window.close()
