from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


Point = Tuple[float, float]


@dataclass
class GeometryFeatureDefinition:
    feature_id: str
    name: str
    layer: str
    feature_type: str
    source: str = "manual"
    points_px: List[Point] = field(default_factory=list)
    reference_ids: List[str] = field(default_factory=list)
    detection_key: str = ""
    algorithm: str = ""
    enabled: bool = True


@dataclass
class CoordinateSystemDefinition:
    coordinate_id: str
    name: str
    layer: str
    method: str
    reference_ids: List[str] = field(default_factory=list)
    rotation_deg: float = 0.0
    enabled: bool = True


@dataclass
class GeometryMeasurementDefinition:
    measurement_id: str
    name: str
    layer: str
    measurement_type: str
    reference_ids: List[str] = field(default_factory=list)
    coordinate_id: str = ""
    enabled: bool = True


@dataclass
class CoordinateLabelDefinition:
    label_id: str
    name: str
    layer: str
    feature_id: str
    coordinate_id: str
    offset_px: Point = (24.0, -24.0)
    enabled: bool = True


@dataclass
class GeometryProgram:
    features: List[GeometryFeatureDefinition] = field(default_factory=list)
    coordinate_systems: List[CoordinateSystemDefinition] = field(default_factory=list)
    measurements: List[GeometryMeasurementDefinition] = field(default_factory=list)
    coordinate_labels: List[CoordinateLabelDefinition] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "GeometryProgram":
        data = data or {}
        return cls(
            features=[GeometryFeatureDefinition(**item) for item in data.get("features", [])],
            coordinate_systems=[CoordinateSystemDefinition(**item) for item in data.get("coordinate_systems", [])],
            measurements=[GeometryMeasurementDefinition(**item) for item in data.get("measurements", [])],
            coordinate_labels=[CoordinateLabelDefinition(**item) for item in data.get("coordinate_labels", [])],
        )


@dataclass
class GeometryFeatureResult:
    feature_id: str
    name: str
    layer: str
    feature_type: str
    status: str
    center_px: Optional[Point] = None
    points_px: List[Point] = field(default_factory=list)
    radius_px: Optional[float] = None
    residual_px: Optional[float] = None
    quality: str = ""
    algorithm_path: str = ""
    error: str = ""


@dataclass
class CoordinateSystemResult:
    coordinate_id: str
    name: str
    layer: str
    status: str
    origin_px: Optional[Point] = None
    x_axis_image: Optional[Point] = None
    y_axis_image: Optional[Point] = None
    rotation_deg: float = 0.0
    error: str = ""


@dataclass
class GeometryMeasurementResult:
    measurement_id: str
    name: str
    layer: str
    measurement_type: str
    status: str
    value: Optional[float] = None
    unit: str = ""
    quality: str = ""
    algorithm_path: str = ""
    error: str = ""
    reference_ids: List[str] = field(default_factory=list)


@dataclass
class CoordinateLabelResult:
    label_id: str
    name: str
    layer: str
    feature_id: str
    coordinate_id: str
    status: str
    x_um: Optional[float] = None
    y_um: Optional[float] = None
    anchor_px: Optional[Point] = None
    label_px: Optional[Point] = None
    error: str = ""


@dataclass
class GeometryRunResult:
    features: Dict[str, GeometryFeatureResult] = field(default_factory=dict)
    coordinate_systems: Dict[str, CoordinateSystemResult] = field(default_factory=dict)
    measurements: Dict[str, GeometryMeasurementResult] = field(default_factory=dict)
    coordinate_labels: Dict[str, CoordinateLabelResult] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
