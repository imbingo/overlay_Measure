from __future__ import annotations

import json

import numpy as np
from PySide6.QtWidgets import QApplication

from overlay_measure.geometry_engine import execute_geometry_program
from overlay_measure.geometry_models import (
    CoordinateLabelDefinition,
    CoordinateSystemDefinition,
    GeometryFeatureDefinition,
    GeometryMeasurementDefinition,
    GeometryProgram,
)
from overlay_measure.models import DetectionParams, DetectionResult, MarkRecipe, MeasurementConfig
from overlay_measure.recipe_manager import load_recipe, load_recipe_with_geometry, save_recipe
from overlay_measure.ui_main import MainWindow


def _circle_detection(points):
    return DetectionResult(
        "Mark1", "upper", 10.0, 20.0, 1.0, 2.0, 20.0, 2.0,
        0.1, 0.01, len(points), 0.99, "Circle",
        edge_points=list(points), shape_params={"radius_px": 10.0, "contour_points": list(points)},
    )


def test_geometry_coordinate_measurements_use_calibrated_y_up_space():
    config = MeasurementConfig(pixel_size_x_um=2.0, pixel_size_y_um=1.0)
    program = GeometryProgram(
        features=[
            GeometryFeatureDefinition("P1", "P1", "upper", "point", points_px=[(10.0, 10.0)]),
            GeometryFeatureDefinition("P2", "P2", "upper", "point", points_px=[(20.0, 10.0)]),
            GeometryFeatureDefinition("P3", "P3", "upper", "point", points_px=[(10.0, 5.0)]),
            GeometryFeatureDefinition("LN1", "LN1", "upper", "line", points_px=[(10.0, 10.0), (20.0, 10.0)]),
        ],
        coordinate_systems=[
            CoordinateSystemDefinition("CS1", "CS1", "upper", "two_points", ["P1", "P2"], 0.0),
        ],
        measurements=[
            GeometryMeasurementDefinition("M1", "距离", "upper", "point_distance", ["P1", "P2"]),
            GeometryMeasurementDefinition("M2", "角度", "upper", "line_angle", ["LN1"]),
        ],
        coordinate_labels=[
            CoordinateLabelDefinition("L1", "L1", "upper", "P3", "CS1"),
        ],
    )
    result = execute_geometry_program(program, {}, config)
    assert result.measurements["M1"].value == 20.0
    assert result.measurements["M2"].value == 0.0
    assert result.coordinate_labels["L1"].x_um == 0.0
    assert result.coordinate_labels["L1"].y_um == 5.0


def test_outer_circle_algorithms_reuse_detected_contour():
    angles = np.linspace(0.0, 2.0 * np.pi, 80, endpoint=False)
    points = [(10.0 + 8.0 * np.cos(value), 20.0 + 8.0 * np.sin(value)) for value in angles]
    detection = _circle_detection(points)
    program = GeometryProgram(features=[
        GeometryFeatureDefinition("C1", "最小外接圆", "upper", "outer_circle_min", "detection", detection_key="Mark1:upper"),
        GeometryFeatureDefinition("C2", "稳健外轮廓圆", "upper", "outer_circle_robust", "detection", detection_key="Mark1:upper"),
    ])
    result = execute_geometry_program(program, {"Mark1:upper": detection}, MeasurementConfig())
    for feature in result.features.values():
        assert feature.status == "Valid"
        assert abs(feature.center_px[0] - 10.0) < 1e-3
        assert abs(feature.center_px[1] - 20.0) < 1e-3
        assert abs(feature.radius_px - 8.0) < 1e-3


def test_v2_recipe_roundtrip_and_legacy_loader(tmp_path):
    path = tmp_path / "v2_recipe.json"
    program = GeometryProgram(features=[
        GeometryFeatureDefinition("P1", "原点", "upper", "point", points_px=[(1.0, 2.0)])
    ])
    save_recipe(str(path), MeasurementConfig(), DetectionParams(), [MarkRecipe("Mark1")], program)
    config, params, marks = load_recipe(str(path))
    assert marks[0].mark_id == "Mark1"
    _, _, _, loaded_program = load_recipe_with_geometry(str(path))
    assert loaded_program.features[0].name == "原点"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["software_name"] == "SOMA Vision Metrology"
    assert data["version"] == "2.2.2"


def test_v2_ui_brand_tabs_and_measurement_command():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    app.processEvents()
    assert window.title_label.text() == "SOMA Vision Metrology"
    assert "See Once, Measure All" in window.brand_subtitle_label.text()
    assert window.side_tabs.count() == 5
    assert hasattr(window, "geometry_continuous_check")
    assert not hasattr(window, "geometry_clear_btn")
    assert window.result_tabs.tabText(2) == "尺寸结果"
    assert window.analyze_all_btn.text() == "运行测量程序"
    window.close()
