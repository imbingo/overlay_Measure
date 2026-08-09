from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from .geometry_models import GeometryProgram
from .models import DetectionParams, MarkRecipe, MeasurementConfig, Roi, RoiEntry


def _roi_to_dict(roi):
    return None if roi is None else asdict(roi)


def _roi_from_dict(data):
    if not data:
        return None
    return Roi(**data)


def _roi_entries_to_dict(entries: List[RoiEntry]) -> list[dict]:
    return [
        {"roi_id": item.roi_id, "source": item.source, "roi": _roi_to_dict(item.roi)}
        for item in entries
    ]


def _roi_entries_from_dict(items, layer: str) -> List[RoiEntry]:
    result = []
    for index, item in enumerate(items or [], start=1):
        roi = _roi_from_dict(item.get("roi"))
        if roi is None:
            continue
        result.append(
            RoiEntry(
                str(item.get("roi_id") or f"{layer}-{index}"),
                roi,
                str(item.get("source") or "recipe"),
            )
        )
    return result


def _legacy_roi_type(roi: Roi | None, fitting_mode: str) -> Roi | None:
    """Migrate V2.0's generic rectangle search box to a semantic ROI type."""
    if roi is None or roi.roi_type != "Rectangle":
        return roi
    roi.roi_type = {
        "Circle": "Circle",
        "Ellipse": "Ellipse",
        "RegionCenter": "Region Center",
        "EdgeCenter": "Robust Center",
        "Auto": "Legacy Auto",
    }.get(fitting_mode, "Rectangle")
    return roi


def save_recipe(
    path: str,
    config: MeasurementConfig,
    params: DetectionParams,
    marks: List[MarkRecipe],
    geometry_program: GeometryProgram | None = None,
) -> None:
    data = {
        "software_name": "SOMA Vision Metrology",
        "version": "2.2.2",
        "roi_fit_policy": "roi_type",
        "measurement_config": asdict(config),
        "detection_params": asdict(params),
        "geometry_program": (geometry_program or GeometryProgram()).to_dict(),
        "marks": [
            {
                "mark_id": m.mark_id,
                "upper_roi": _roi_to_dict(m.upper_roi),
                "lower_roi": _roi_to_dict(m.lower_roi),
                "upper_rois": _roi_entries_to_dict(m.upper_rois),
                "lower_rois": _roi_entries_to_dict(m.lower_rois),
                "reference_contour_id": m.reference_contour_id,
                "target_contour_id": m.target_contour_id,
                "reference_shape": m.reference_shape,
                "target_shape": m.target_shape,
                "reference_size_min_um": m.reference_size_min_um,
                "reference_size_max_um": m.reference_size_max_um,
                "target_size_min_um": m.target_size_min_um,
                "target_size_max_um": m.target_size_max_um,
            }
            for m in marks
        ],
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_recipe(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    config = MeasurementConfig(**data.get("measurement_config", {}))
    params_data = data.get("detection_params", {})
    if "upper_fitting_mode" not in params_data and "fitting_mode" in params_data:
        params_data["upper_fitting_mode"] = params_data["fitting_mode"]
    if "lower_fitting_mode" not in params_data and "fitting_mode" in params_data:
        params_data["lower_fitting_mode"] = params_data["fitting_mode"]
    params = DetectionParams(**params_data)
    marks = []
    roi_fit_policy = data.get("roi_fit_policy", "legacy")
    for item in data.get("marks", []):
        upper_entries = _roi_entries_from_dict(item.get("upper_rois"), "upper")
        lower_entries = _roi_entries_from_dict(item.get("lower_rois"), "lower")
        upper_roi = _roi_from_dict(item.get("upper_roi")) if not upper_entries else None
        lower_roi = _roi_from_dict(item.get("lower_roi")) if not lower_entries else None
        if roi_fit_policy != "roi_type":
            upper_roi = _legacy_roi_type(upper_roi, params.upper_fitting_mode)
            lower_roi = _legacy_roi_type(lower_roi, params.lower_fitting_mode)
        marks.append(
            MarkRecipe(
                mark_id=item.get("mark_id", f"Mark{len(marks)+1}"),
                upper_roi=upper_roi,
                lower_roi=lower_roi,
                reference_shape=item.get("reference_shape", "Any"),
                target_shape=item.get("target_shape", "Any"),
                reference_size_min_um=float(item.get("reference_size_min_um", 0.0)),
                reference_size_max_um=float(item.get("reference_size_max_um", 999999.0)),
                target_size_min_um=float(item.get("target_size_min_um", 0.0)),
                target_size_max_um=float(item.get("target_size_max_um", 999999.0)),
                upper_rois=upper_entries,
                lower_rois=lower_entries,
                reference_contour_id=str(item.get("reference_contour_id", "")),
                target_contour_id=str(item.get("target_contour_id", "")),
            )
        )
    return config, params, marks


def load_recipe_with_geometry(path: str):
    """Load a recipe while preserving the legacy three-value API.

    ``load_recipe`` remains unchanged for integrations built against V1.x.
    New UI code uses this helper to read the optional V2 geometry program.
    """
    config, params, marks = load_recipe(path)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return config, params, marks, GeometryProgram.from_dict(data.get("geometry_program"))
