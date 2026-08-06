from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import DetectionResult


def _decimate_points(points: Any, limit: int = 256) -> list[tuple[float, float]]:
    values = list(points or [])
    if len(values) <= limit:
        return [(float(point[0]), float(point[1])) for point in values]
    step = len(values) / float(limit)
    return [
        (float(values[int(index * step)][0]), float(values[int(index * step)][1]))
        for index in range(limit)
    ]


def compact_detection(detection: DetectionResult) -> DetectionResult:
    shape_params = dict(detection.shape_params)
    shape_params.pop("caliper_windows", None)
    for key in ("contour_points", "candidate_contour_points"):
        if key in shape_params:
            shape_params[key] = _decimate_points(shape_params[key])
    return replace(
        detection,
        edge_points=_decimate_points(detection.edge_points),
        rejected_points=_decimate_points(detection.rejected_points),
        edge_gradients=[],
        rejected_gradients=[],
        shape_params=shape_params,
    )


def compact_detection_map(value: Any) -> Any:
    if isinstance(value, DetectionResult):
        return compact_detection(value)
    if isinstance(value, dict):
        return {key: compact_detection_map(item) for key, item in value.items()}
    return value
