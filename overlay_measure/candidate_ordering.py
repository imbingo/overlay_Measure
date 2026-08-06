from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

import numpy as np

from .models import DetectionResult


LAYER_PREFIX = {"upper": "上", "lower": "下"}


def _legacy_alpha_index(value: str) -> Optional[int]:
    token = str(value or "").rsplit("-", 1)[-1].strip().lower()
    if not token or not token.isalpha():
        return None
    index = 0
    for char in token:
        if not ("a" <= char <= "z"):
            return None
        index = index * 26 + ord(char) - ord("a") + 1
    return index - 1


def _row_major_numbers(items: list[tuple[int, DetectionResult]]) -> dict[int, int]:
    if not items:
        return {}
    diameters = [max(1.0, float(item.diameter_px)) for _, item in items]
    row_tolerance = max(3.0, 0.45 * float(np.median(diameters)))
    ordered = sorted(
        items,
        key=lambda pair: (float(pair[1].center_y_px), float(pair[1].center_x_px), pair[0]),
    )
    rows: list[list[tuple[int, DetectionResult]]] = []
    row_centers: list[float] = []
    for item in ordered:
        y_value = float(item[1].center_y_px)
        target = next(
            (index for index, center in enumerate(row_centers) if abs(y_value - center) <= row_tolerance),
            None,
        )
        if target is None:
            rows.append([item])
            row_centers.append(y_value)
        else:
            rows[target].append(item)
            row_centers[target] = float(np.median([entry[1].center_y_px for entry in rows[target]]))
    rows = [row for _, row in sorted(zip(row_centers, rows), key=lambda pair: pair[0])]
    numbers: dict[int, int] = {}
    next_number = 1
    for row in rows:
        for original_index, _ in sorted(
            row,
            key=lambda pair: (float(pair[1].center_x_px), float(pair[1].center_y_px), pair[0]),
        ):
            numbers[original_index] = next_number
            next_number += 1
    return numbers


def assign_spatial_candidate_ids(
    detections: Iterable[DetectionResult],
    dual_image: bool,
) -> list[tuple[str, DetectionResult]]:
    """Assign deterministic row-major display IDs without changing rank order.

    Returned entries remain in the input order.  This preserves the existing
    quality/diameter based default selection while exposing spatial numbers to
    operators.
    """
    ranked = list(detections)
    by_layer: dict[str, list[tuple[int, DetectionResult]]] = defaultdict(list)
    for rank, detection in enumerate(ranked):
        detection.shape_params["detection_rank"] = rank
        by_layer[detection.layer].append((rank, detection))
    numbers = {
        layer: _row_major_numbers(items)
        for layer, items in by_layer.items()
    }
    entries: list[tuple[str, DetectionResult]] = []
    for rank, detection in enumerate(ranked):
        number = numbers[detection.layer][rank]
        display = f"{LAYER_PREFIX.get(detection.layer, detection.layer)}-{number}" if dual_image else str(number)
        key = f"{detection.layer}:{number}"
        detection.shape_params["candidate_number"] = number
        detection.shape_params["candidate_display_label"] = display
        detection.shape_params["candidate_key"] = key
        entries.append((key, detection))
    return entries


def candidate_display_label(key: str, detection: Optional[DetectionResult] = None) -> str:
    if detection is not None:
        display = str(detection.shape_params.get("candidate_display_label", "")).strip()
        if display:
            return display
    if ":" in str(key):
        layer, number = str(key).split(":", 1)
        return f"{LAYER_PREFIX.get(layer, layer)}-{number}"
    return str(key)


def resolve_preferred_candidate(value: str, detections: dict[str, dict[str, DetectionResult]]) -> str:
    """Resolve current IDs and legacy a/b/c recipe selections safely."""
    if value in detections:
        return value
    legacy_rank = _legacy_alpha_index(value)
    if legacy_rank is None:
        return ""
    for key, layer_map in detections.items():
        detection = next(iter(layer_map.values()), None)
        if detection is not None and int(detection.shape_params.get("detection_rank", -1)) == legacy_rank:
            return key
    return ""
