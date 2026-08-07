from __future__ import annotations

import sys
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QFontDatabase, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyle,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .auto_mark_detector import detect_auto_marks_with_report
from .access_control import AccessController
from .batch_pairing import validate_batch_pairing
from .candidate_ordering import candidate_display_label
from .geometry_models import GeometryProgram, GeometryRunResult
from .export_naming import build_export_filename
from .image_loader import SUPPORTED_EXTENSIONS, display_to_uint8, load_image
from .measurement_engine import run_measurement_job
from .measurement_service import attach_algorithm_path, describe_algorithm_path, detect_manual_roi
from .measurement_units import axis_scale_um_per_px, rotated_rect_size_um
from .models import DetectionParams, DetectionResult, ImageData, MarkRecipe, MeasurementConfig, OverlayResult, Roi
from .overlay_calculator import calculate_overlay, calculate_relative_overlay
from .production_measurement import refine_candidate
from .quality_profiles import (
    QUALITY_PROFILE_LABELS,
    annotate_detection_quality,
    apply_quality_profile,
    quality_profile_display,
    quality_profile_is_modified,
)
from .recipe_manager import load_recipe, save_recipe
from .recipe_library import RecipeLibrary, RecipeLibraryEntry
from .recipe_integrity import seal_recipe, verify_recipe
from .result_exporter import build_detection_rows, export_results
from .rz_calculator import build_summary_rows
from .runtime_support import RecoveryStore, build_runtime_logger

from .ui_constants import LAYER_LABELS, RESULT_LABELS


class SidebarComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class SidebarDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class SidebarSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class FramelessTitleBar(QFrame):
    """Custom title bar that keeps the frameless window movable and maximizable."""

    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self.window = window
        self.drag_offset: Optional[QPoint] = None
        self.setObjectName("titleBar")
        self.setFixedHeight(46)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.window.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self.drag_offset = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton and not self.window.isMaximized():
            self.window.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class CollapsibleSection(QWidget):
    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText(title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setObjectName("sectionToggle")
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 8, 0, 0)
        self.body_layout.setSpacing(10)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toggle_btn)
        layout.addWidget(self.body)
        self.toggle_btn.toggled.connect(self._apply_state)
        self._apply_state(expanded)

    def _apply_state(self, expanded: bool):
        self.body.setVisible(expanded)
        self.toggle_btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def add_widget(self, widget: QWidget):
        self.body_layout.addWidget(widget)


class ImageCanvas(QLabel):
    roiChanged = Signal(str, str, object)  # mark_id, layer, Roi
    geometryClicked = Signal(str, object)  # layer, click payload

    def __init__(self, title: str, fixed_layer: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.title = title
        self.fixed_layer = fixed_layer
        self.setMinimumSize(360, 250)
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.image: Optional[ImageData] = None
        self.pixmap_cache: Optional[QPixmap] = None
        self.scale = 1.0
        self.fit_scale = 1.0
        self.user_zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.active_mark_id = "Mark1"
        self.active_layer = fixed_layer or "upper"
        self.active_roi_type = "Annulus"
        self.active_roi_inner_ratio = 0.60
        self.active_roi_target_edge = "All Edges"
        self.active_roi_angle_deg = 0.0
        self.active_ring_half_width_px = 10.0
        self.active_caliper_count = 64
        self.active_caliper_width_px = 8.0
        self.active_search_direction = "Inner to Outer"
        self.active_diameter_mode = "Average"
        self.circle_pick_mode = False
        self.circle_pick_points = []
        self.circle_preview_point = None
        self.marks: Dict[str, MarkRecipe] = {}
        self.detections: Dict[str, Dict[str, DetectionResult]] = {}
        self.auto_detections: Dict[str, Dict[str, DetectionResult]] = {}
        self.show_auto_detections = False
        self.manual_labels = {}
        self.auto_reference_label = ""
        self.auto_target_label = ""
        self.show_diagnostics = False
        self.geometry_program = GeometryProgram()
        self.geometry_result = GeometryRunResult()
        self.geometry_interaction_active = False
        self.selected_geometry_feature_id = ""
        self.selected_caliper_feature = None
        self.selected_caliper_detection_id = None
        self.caliper_selection_context = None
        self.display_enhancement = False
        self.pixel_size_x_um = 0.1
        self.pixel_size_y_um = 0.1
        self.drag_start_img: Optional[QPoint] = None
        self.drag_current_img: Optional[QPoint] = None
        self.is_dragging = False
        self.is_adjusting_roi = False
        self.is_moving_roi = False
        self.adjust_roi_part = ""
        self.adjust_mark_id = ""
        self.adjust_layer = ""
        self.move_start_img = None
        self.move_start_roi = None
        self.is_panning = False
        self.pan_start_pos: Optional[QPoint] = None
        self.pan_start_x = 0.0
        self.pan_start_y = 0.0
        self.setText("等待导入图像")
        self.setStyleSheet("QLabel { background: #252930; color: #F5F6F8; border: 1px solid #363C45; border-radius: 6px; }")

    def set_image(self, image: Optional[ImageData]):
        self.clear_caliper_selection(update=False)
        self.image = image
        self.pixmap_cache = None
        self.reset_view(update=False)
        if image is not None:
            self.pixmap_cache = self._make_pixmap(image)
            self.setText("")
        else:
            self.setText("等待导入图像")
        self.update()

    def set_display_enhancement(self, enabled: bool):
        enabled = bool(enabled)
        if self.display_enhancement == enabled:
            return
        self.display_enhancement = enabled
        if self.image is not None:
            self.pixmap_cache = self._make_pixmap(self.image)
        self.update()

    def set_context(
        self,
        active_mark_id: str,
        active_layer: str,
        marks: Dict[str, MarkRecipe],
        detections,
        roi_type: str = "Annulus",
        roi_inner_ratio: float = 0.60,
        roi_target_edge: str = "All Edges",
        roi_angle_deg: float = 0.0,
        roi_ring_half_width_px: float = 10.0,
        roi_caliper_count: int = 64,
        roi_caliper_width_px: float = 8.0,
        roi_search_direction: str = "Inner to Outer",
        roi_diameter_mode: str = "Average",
        auto_detections=None,
        show_auto_detections: bool = False,
        manual_labels=None,
        auto_reference_label: str = "",
        auto_target_label: str = "",
        pixel_size_x_um: float = 0.1,
        pixel_size_y_um: float = 0.1,
        show_diagnostics: bool = False,
    ):
        next_layer = self.fixed_layer or active_layer
        next_context = ("auto" if show_auto_detections else "manual", active_mark_id, next_layer)
        if self.caliper_selection_context != next_context:
            self.clear_caliper_selection(update=False)
        self.caliper_selection_context = next_context
        self.active_mark_id = active_mark_id
        self.active_layer = next_layer
        self.active_roi_type = roi_type
        self.active_roi_inner_ratio = float(roi_inner_ratio)
        self.active_roi_target_edge = roi_target_edge
        self.active_roi_angle_deg = float(roi_angle_deg)
        self.active_ring_half_width_px = float(max(1.0, roi_ring_half_width_px))
        self.active_caliper_count = int(roi_caliper_count)
        self.active_caliper_width_px = float(roi_caliper_width_px)
        self.active_search_direction = roi_search_direction
        self.active_diameter_mode = roi_diameter_mode
        self.marks = marks
        self.detections = detections
        self.auto_detections = auto_detections or {}
        self.show_auto_detections = bool(show_auto_detections)
        self.manual_labels = manual_labels or {}
        self.auto_reference_label = auto_reference_label
        self.auto_target_label = auto_target_label
        self.pixel_size_x_um = float(pixel_size_x_um)
        self.pixel_size_y_um = float(pixel_size_y_um)
        self.show_diagnostics = bool(show_diagnostics)
        self._drop_stale_caliper_selection()
        self.update()

    def set_geometry_context(
        self,
        program: Optional[GeometryProgram],
        result: Optional[GeometryRunResult],
        interaction_active: bool = False,
    ):
        self.geometry_program = program or GeometryProgram()
        self.geometry_result = result or GeometryRunResult()
        self.geometry_interaction_active = bool(interaction_active)
        self.update()

    def set_geometry_interaction_active(self, active: bool):
        self.geometry_interaction_active = bool(active)
        self.setCursor(Qt.CrossCursor if active else Qt.ArrowCursor)
        self.update()

    def _geometry_hit(self, pos, tolerance_px: float = 10.0) -> str:
        best_id = ""
        best_distance = float(tolerance_px)
        for feature_id, feature in self.geometry_result.features.items():
            if feature.status != "Valid" or feature.layer != self.active_layer:
                continue
            if feature.center_px is not None:
                wx, wy = self.image_to_widget(*feature.center_px)
                distance = float(np.hypot(wx - pos.x(), wy - pos.y()))
                if feature.radius_px is not None:
                    radial = abs(distance - feature.radius_px * self.scale)
                    distance = min(distance, radial)
                if distance < best_distance:
                    best_id, best_distance = feature_id, distance
            if len(feature.points_px) >= 2 and feature.feature_type == "line":
                a = np.asarray(self.image_to_widget(*feature.points_px[0]), dtype=float)
                b = np.asarray(self.image_to_widget(*feature.points_px[1]), dtype=float)
                p = np.asarray([pos.x(), pos.y()], dtype=float)
                segment = b - a
                denom = float(np.dot(segment, segment))
                if denom > 1e-12:
                    t = float(np.clip(np.dot(p - a, segment) / denom, 0.0, 1.0))
                    distance = float(np.linalg.norm(p - (a + t * segment)))
                    if distance < best_distance:
                        best_id, best_distance = feature_id, distance
        return best_id

    def _detection_key_hit(self, pos, tolerance_px: float = 10.0) -> str:
        maps = self.auto_detections if self.show_auto_detections else self.detections
        best_key = ""
        best_distance = float(tolerance_px)
        for identity, layer_map in maps.items():
            for layer, detection in layer_map.items():
                if layer != self.active_layer:
                    continue
                distance = self._detection_hit_distance(detection, pos)
                if distance < best_distance:
                    prefix = f"{self.active_mark_id}/" if self.show_auto_detections else ""
                    best_key, best_distance = f"{prefix}{identity}:{layer}", distance
        return best_key

    def clear_caliper_selection(self, update: bool = True):
        self.selected_caliper_feature = None
        self.selected_caliper_detection_id = None
        if update:
            self.update()

    @staticmethod
    def _detection_has_calipers(detection: Optional[DetectionResult]) -> bool:
        if detection is None:
            return False
        return bool(detection.shape_params.get("caliper_windows")) or detection.fitting_mode == "CaliperCircle"

    def _selected_detection(self) -> Optional[DetectionResult]:
        if not self.selected_caliper_feature:
            return None
        mode, identity, layer = self.selected_caliper_feature
        if mode == "auto":
            return self.auto_detections.get(identity, {}).get(layer)
        return self.detections.get(identity, {}).get(layer)

    def _drop_stale_caliper_selection(self):
        if not self.selected_caliper_feature:
            return
        detection = self._selected_detection()
        if detection is None or id(detection) != self.selected_caliper_detection_id:
            self.clear_caliper_selection(update=False)

    def _select_caliper_detection(self, mode: str, identity: str, layer: str, detection: DetectionResult):
        self.selected_caliper_feature = (mode, identity, layer)
        self.selected_caliper_detection_id = id(detection)
        self.update()

    def _manual_caliper_selected(self, mark_id: str, layer: str, detection: Optional[DetectionResult]) -> bool:
        return (
            detection is not None
            and self.selected_caliper_feature == ("manual", mark_id, layer)
            and self.selected_caliper_detection_id == id(detection)
        )

    def _auto_caliper_selected(self, label: str, layer: str, detection: Optional[DetectionResult]) -> bool:
        return (
            detection is not None
            and self.selected_caliper_feature == ("auto", label, layer)
            and self.selected_caliper_detection_id == id(detection)
        )

    def _manual_roi_visible(
        self,
        mark_id: str,
        layer: str,
        roi: Optional[Roi],
        detection: Optional[DetectionResult],
    ) -> bool:
        if roi is None:
            return False
        if getattr(roi, "roi_type", "") != "Caliper Circle" or detection is None:
            return True
        return self._manual_caliper_selected(mark_id, layer, detection)

    def _has_caliper_result_for_hint(self) -> bool:
        if self.show_auto_detections:
            return any(
                self._detection_has_calipers(detection)
                for layer_map in self.auto_detections.values()
                for detection in layer_map.values()
            )
        detection = self.detections.get(self.active_mark_id, {}).get(self.active_layer)
        roi = self._active_roi()
        return (
            roi is not None
            and getattr(roi, "roi_type", "") == "Caliper Circle"
            and detection is not None
        )

    def _mean_pixel_size_um(self) -> float:
        return 0.5 * (self.pixel_size_x_um + self.pixel_size_y_um)

    def _contour_label_anchor(self, detection: DetectionResult, direction_index: Optional[int] = None):
        points = detection.shape_params.get("contour_points", detection.edge_points)
        if points:
            array = np.asarray(points, dtype=float)
            if direction_index is None:
                index = int(np.argmax(array[:, 0] - 0.75 * array[:, 1]))
            else:
                angle = -np.pi / 4.0 + direction_index * 2.3999632297
                direction = np.asarray([np.cos(angle), np.sin(angle)])
                offsets = array - np.asarray([detection.center_x_px, detection.center_y_px])
                lengths = np.maximum(np.linalg.norm(offsets, axis=1, keepdims=True), 1e-9)
                index = int(np.argmax((offsets / lengths) @ direction))
            return self.image_to_widget(float(array[index, 0]), float(array[index, 1]))
        radius = float(detection.shape_params.get("radius_px", detection.diameter_px / 2.0))
        return self.image_to_widget(
            detection.center_x_px + radius * 0.70,
            detection.center_y_px - radius * 0.70,
        )

    @staticmethod
    def _point_segment_distance(px: float, py: float, start: QPointF, end: QPointF) -> float:
        ax, ay = float(start.x()), float(start.y())
        bx, by = float(end.x()), float(end.y())
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy
        if denominator <= 1e-12:
            return float(np.hypot(px - ax, py - ay))
        t = float(np.clip(((px - ax) * dx + (py - ay) * dy) / denominator, 0.0, 1.0))
        return float(np.hypot(px - (ax + t * dx), py - (ay + t * dy)))

    def _polyline_hit_distance(self, pos, points, closed: bool = True) -> float:
        if not points or len(points) < 2:
            return float("inf")
        widget_points = [
            QPointF(*self.image_to_widget(float(point[0]), float(point[1])))
            for point in points
        ]
        pairs = list(zip(widget_points, widget_points[1:]))
        if closed and len(widget_points) > 2:
            pairs.append((widget_points[-1], widget_points[0]))
        return min(
            self._point_segment_distance(float(pos.x()), float(pos.y()), start, end)
            for start, end in pairs
        )

    def _detection_hit_distance(self, detection: DetectionResult, pos) -> float:
        """Return distance in widget pixels so hit tolerance is zoom independent."""
        cx, cy = self.image_to_widget(detection.center_x_px, detection.center_y_px)
        center_distance = float(np.hypot(float(pos.x()) - cx, float(pos.y()) - cy))
        if center_distance <= 12.0:
            return center_distance

        if detection.fitting_mode in {"Circle", "EdgeCenter", "CaliperCircle", "ProductionCircle"}:
            radius = float(detection.shape_params.get("radius_px", detection.diameter_px / 2.0))
            radial_distance = float(np.hypot(float(pos.x()) - cx, float(pos.y()) - cy))
            return abs(radial_distance - radius * self.scale)

        if detection.fitting_mode in {"Rectangle", "ProductionRectangle"}:
            width = float(detection.shape_params.get("width_px", detection.diameter_px))
            height = float(detection.shape_params.get("height_px", detection.diameter_px))
            angle = float(detection.shape_params.get("angle_deg", 0.0))
            points = self._rotated_rect_points_widget(
                detection.center_x_px,
                detection.center_y_px,
                width,
                height,
                angle,
            )
            pairs = list(zip(points, points[1:] + points[:1]))
            return min(
                self._point_segment_distance(float(pos.x()), float(pos.y()), start, end)
                for start, end in pairs
            )

        contour = detection.shape_params.get(
            "candidate_contour_points",
            detection.shape_params.get("contour_points", detection.edge_points),
        )
        return self._polyline_hit_distance(pos, contour)

    def _manual_caliper_hit(self, pos, tolerance_px: float = 9.0):
        mark_id = self.active_mark_id
        layer = self.active_layer
        roi = self._active_roi()
        detection = self.detections.get(mark_id, {}).get(layer)
        if (
            roi is None
            or getattr(roi, "roi_type", "") != "Caliper Circle"
            or not self._detection_has_calipers(detection)
        ):
            return None
        if self._detection_hit_distance(detection, pos) <= tolerance_px:
            return mark_id, layer, detection
        return None

    def _nearest_auto_caliper_hit(self, pos, tolerance_px: float = 9.0):
        best = None
        best_distance = tolerance_px
        for label, layer_map in self.auto_detections.items():
            for layer, detection in layer_map.items():
                if self.fixed_layer and layer != self.fixed_layer:
                    continue
                if not self._detection_has_calipers(detection):
                    continue
                distance = self._detection_hit_distance(detection, pos)
                if distance <= best_distance:
                    best = (label, layer, detection)
                    best_distance = distance
        return best

    def set_circle_pick_mode(self, enabled: bool):
        self.circle_pick_mode = enabled
        self.circle_pick_points = []
        self.circle_preview_point = None
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.update()

    def _make_pixmap(self, image: ImageData) -> QPixmap:
        u8 = display_to_uint8(image, self.display_enhancement)
        h, w = u8.shape
        qimg = QImage(u8.data, w, h, w, QImage.Format_Grayscale8).copy()
        return QPixmap.fromImage(qimg)

    def _base_offset_for_scale(self, scale: float):
        if self.pixmap_cache is None:
            return 0.0, 0.0
        img_w = self.pixmap_cache.width()
        img_h = self.pixmap_cache.height()
        return (self.width() - img_w * scale) / 2.0, (self.height() - img_h * scale) / 2.0

    def _update_transform(self):
        if self.pixmap_cache is None:
            return
        img_w = self.pixmap_cache.width()
        img_h = self.pixmap_cache.height()
        if img_w <= 0 or img_h <= 0:
            return
        sx = self.width() / img_w
        sy = self.height() / img_h
        self.fit_scale = min(sx, sy)
        self.scale = self.fit_scale * self.user_zoom
        base_x, base_y = self._base_offset_for_scale(self.scale)
        self.offset_x = base_x + self.pan_x
        self.offset_y = base_y + self.pan_y

    def image_to_widget(self, x: float, y: float):
        # OpenCV coordinates identify pixel centers, while QPainter draws the
        # image from its outer boundary. Account for that half-pixel difference
        # so fitted geometry is not displayed 0.5 px toward the upper-left.
        return self.offset_x + (x + 0.5) * self.scale, self.offset_y + (y + 0.5) * self.scale

    def _rotated_rect_points_widget(self, cx: float, cy: float, w: float, h: float, angle_deg: float):
        theta = np.deg2rad(angle_deg)
        ct, st = np.cos(theta), np.sin(theta)
        hw, hh = w / 2.0, h / 2.0
        local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        pts = []
        for lx, ly in local:
            ix = cx + ct * lx - st * ly
            iy = cy + st * lx + ct * ly
            wx, wy = self.image_to_widget(ix, iy)
            pts.append(QPointF(wx, wy))
        return pts

    def _draw_roi_shape(self, painter: QPainter, roi: Roi, color: QColor, active: bool, label: str = ""):
        r = roi.normalized()
        pen = QPen(color, 2.5 if active else 1.5)
        pen.setStyle(Qt.SolidLine if active else Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        cx, cy = r.center()
        wcx, wcy = self.image_to_widget(cx, cy)
        typ = getattr(r, "roi_type", "Rectangle")

        if typ == "Circle":
            radius = r.outer_radius() * self.scale
            painter.drawEllipse(QRectF(wcx - radius, wcy - radius, 2 * radius, 2 * radius))
        elif typ in {"Annulus", "Caliper Circle"}:
            outer = r.outer_radius() * self.scale
            inner = r.inner_radius() * self.scale
            if typ == "Caliper Circle":
                ring_path = QPainterPath()
                ring_path.addEllipse(QRectF(wcx - outer, wcy - outer, 2 * outer, 2 * outer))
                inner_path = QPainterPath()
                inner_path.addEllipse(QRectF(wcx - inner, wcy - inner, 2 * inner, 2 * inner))
                ring_path = ring_path.subtracted(inner_path)
                painter.fillPath(ring_path, QColor(0, 220, 255, 32))
            painter.drawEllipse(QRectF(wcx - outer, wcy - outer, 2 * outer, 2 * outer))
            inner_pen = QPen(color, 1.8 if active else 1.2)
            inner_pen.setStyle(Qt.DotLine)
            inner_pen.setCosmetic(True)
            painter.setPen(inner_pen)
            painter.drawEllipse(QRectF(wcx - inner, wcy - inner, 2 * inner, 2 * inner))
            painter.setPen(pen)
            if typ == "Caliper Circle":
                mid = 0.5 * (outer + inner)
                middle_pen = QPen(QColor(255, 220, 40), 1.3)
                middle_pen.setStyle(Qt.DashLine)
                middle_pen.setCosmetic(True)
                painter.setPen(middle_pen)
                painter.drawEllipse(QRectF(wcx - mid, wcy - mid, 2 * mid, 2 * mid))
                painter.setPen(pen)
                self._draw_calipers(painter, r, color)
        elif typ == "Rectangular Ring":
            outer_poly = QPolygonF(self._rotated_rect_points_widget(cx, cy, r.w, r.h, r.angle_deg))
            iw, ih = r.inner_size()
            inner_poly = QPolygonF(self._rotated_rect_points_widget(cx, cy, iw, ih, r.angle_deg))
            painter.drawPolygon(outer_poly)
            inner_pen = QPen(color, 1.8 if active else 1.2)
            inner_pen.setStyle(Qt.DotLine)
            inner_pen.setCosmetic(True)
            painter.setPen(inner_pen)
            painter.drawPolygon(inner_poly)
            painter.setPen(pen)
        else:
            x, y = self.image_to_widget(r.x, r.y)
            painter.drawRect(QRectF(x, y, r.w * self.scale, r.h * self.scale))

        # Center cross for advanced ROI modes so users can verify concentricity.
        if typ in {"Circle", "Annulus", "Rectangular Ring", "Caliper Circle"}:
            painter.drawLine(int(wcx - 6), int(wcy), int(wcx + 6), int(wcy))
            painter.drawLine(int(wcx), int(wcy - 6), int(wcx), int(wcy + 6))

        if label:
            # Place label near the top-left of the outer bounding box.
            x, y = self.image_to_widget(r.x, r.y)
            typ_label = {"Annulus": "圆环", "Caliper Circle": "卡尺圆", "Rectangular Ring": "矩形环", "Circle": "圆", "Rectangle": "矩形"}.get(typ, typ)
            painter.drawText(int(x + 4), int(y + 16), f"{label} [{typ_label}]")

    def _draw_calipers(self, painter: QPainter, roi: Roi, color: QColor):
        r = roi.normalized()
        cx, cy = r.center()
        inner = r.inner_radius()
        outer = r.outer_radius()
        mid = 0.5 * (inner + outer)
        length = outer - inner
        width = float(getattr(r, "caliper_width_px", 8.0))
        count = int(np.clip(getattr(r, "caliper_count", 64), 4, 720))
        direction = getattr(r, "search_direction", "Inner to Outer")
        caliper_pen = QPen(QColor(255, 230, 40), 1.0)
        caliper_pen.setCosmetic(True)
        arrow_pen = QPen(QColor(0, 255, 255), 1.2)
        arrow_pen.setCosmetic(True)
        for i in range(count):
            angle = 2.0 * np.pi * i / count
            radial = np.array([np.cos(angle), np.sin(angle)])
            tangent = np.array([-np.sin(angle), np.cos(angle)])
            center = np.array([cx, cy]) + radial * mid
            corners = []
            for rs, ts in [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]:
                p = center + radial * (rs * length) + tangent * (ts * width)
                wx, wy = self.image_to_widget(float(p[0]), float(p[1]))
                corners.append(QPointF(wx, wy))
            painter.setPen(caliper_pen)
            painter.drawPolygon(QPolygonF(corners))
            if direction == "Outer to Inner":
                p0 = np.array([cx, cy]) + radial * (outer - 0.18 * length)
                p1 = np.array([cx, cy]) + radial * (inner + 0.18 * length)
            else:
                p0 = np.array([cx, cy]) + radial * (inner + 0.18 * length)
                p1 = np.array([cx, cy]) + radial * (outer - 0.18 * length)
            x0, y0 = self.image_to_widget(float(p0[0]), float(p0[1]))
            x1, y1 = self.image_to_widget(float(p1[0]), float(p1[1]))
            painter.setPen(arrow_pen)
            painter.drawLine(int(x0), int(y0), int(x1), int(y1))
            # arrow head
            v = np.array([x1 - x0, y1 - y0], dtype=np.float64)
            n = np.linalg.norm(v)
            if n > 1e-6:
                v /= n
                t = np.array([-v[1], v[0]])
                for sgn in (-1, 1):
                    h = np.array([x1, y1]) - v * 6 + t * sgn * 3
                    painter.drawLine(int(x1), int(y1), int(h[0]), int(h[1]))

    def widget_to_image_float(self, pos):
        if self.image is None or self.scale <= 0:
            return None
        h, w = self.image.gray.shape[:2]
        x = (pos.x() - self.offset_x) / self.scale - 0.5
        y = (pos.y() - self.offset_y) / self.scale - 0.5
        if x < -0.5 or y < -0.5 or x >= w - 0.5 or y >= h - 0.5:
            return None
        return float(x), float(y)

    def widget_to_image(self, pos) -> Optional[QPoint]:
        p = self.widget_to_image_float(pos)
        if p is None:
            return None
        x, y = p
        h, w = self.image.gray.shape[:2]
        return QPoint(int(np.clip(round(x), 0, w - 1)), int(np.clip(round(y), 0, h - 1)))

    def _active_roi(self) -> Optional[Roi]:
        mark = self.marks.get(self.active_mark_id)
        if mark is None:
            return None
        return mark.upper_roi if self.active_layer == "upper" else mark.lower_roi

    def _roi_hit_part(self, pos) -> str:
        roi = self._active_roi()
        p = self.widget_to_image_float(pos)
        if roi is None or p is None:
            return ""
        r = roi.normalized()
        x, y = p
        tol = max(4.0 / max(self.scale, 1e-9), 2.0)
        typ = getattr(r, "roi_type", "Annulus")

        if typ in {"Annulus", "Caliper Circle"}:
            cx, cy = r.center()
            dist = float(np.hypot(x - cx, y - cy))
            inner = r.inner_radius()
            outer = r.outer_radius()
            if abs(dist - inner) <= tol:
                return "inner"
            if abs(dist - outer) <= tol:
                return "outer"
            return ""

        if typ == "Rectangular Ring":
            xs = np.array([x], dtype=np.float64)
            ys = np.array([y], dtype=np.float64)
            xr, yr = r._local_rotated(xs, ys)
            ax, ay = abs(float(xr[0])), abs(float(yr[0]))
            ow, oh = max(r.w, 1e-9), max(r.h, 1e-9)
            iw, ih = r.inner_size()
            inner_dist = min(abs(ax - iw / 2.0), abs(ay - ih / 2.0))
            outer_dist = min(abs(ax - ow / 2.0), abs(ay - oh / 2.0))
            if ax <= ow / 2.0 + tol and ay <= oh / 2.0 + tol:
                if inner_dist <= tol and ax <= iw / 2.0 + tol and ay <= ih / 2.0 + tol:
                    return "inner"
                if outer_dist <= tol:
                    return "outer"
        return ""

    def _point_in_active_roi_band(self, pos) -> bool:
        roi = self._active_roi()
        p = self.widget_to_image_float(pos)
        if roi is None or p is None:
            return False
        r = roi.normalized()
        point = np.array([[p[0], p[1]]], dtype=np.float64)
        return bool(r.contains_points(point)[0])

    def _point_in_active_roi_outer(self, pos) -> bool:
        roi = self._active_roi()
        p = self.widget_to_image_float(pos)
        if roi is None or p is None:
            return False
        r = roi.normalized()
        x, y = p
        if r.roi_type in {"Annulus", "Caliper Circle"}:
            cx, cy = r.center()
            return float(np.hypot(x - cx, y - cy)) <= r.outer_radius()
        if r.roi_type == "Rectangular Ring":
            return bool(replace(r, roi_type="Rectangle").contains_points(np.array([[x, y]], dtype=np.float64))[0])
        return bool(r.contains_points(np.array([[x, y]], dtype=np.float64))[0])

    def _circle_from_three_points(self, pts):
        (x1, y1), (x2, y2), (x3, y3) = pts
        d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if abs(d) < 1e-9:
            return None
        ux = (
            (x1 * x1 + y1 * y1) * (y2 - y3)
            + (x2 * x2 + y2 * y2) * (y3 - y1)
            + (x3 * x3 + y3 * y3) * (y1 - y2)
        ) / d
        uy = (
            (x1 * x1 + y1 * y1) * (x3 - x2)
            + (x2 * x2 + y2 * y2) * (x1 - x3)
            + (x3 * x3 + y3 * y3) * (x2 - x1)
        ) / d
        radius = float(np.hypot(x1 - ux, y1 - uy))
        return ux, uy, radius

    def _caliper_roi_from_center_circle(self, circle):
        if circle is None:
            return None
        cx, cy, mid_radius = circle
        half_width = self.active_ring_half_width_px
        inner_radius = max(0.0, mid_radius - half_width)
        outer_radius = max(inner_radius + 1.0, mid_radius + half_width)
        return Roi(
            cx - outer_radius,
            cy - outer_radius,
            outer_radius * 2.0,
            outer_radius * 2.0,
            "Caliper Circle",
            inner_radius / max(outer_radius, 1e-9),
            self.active_roi_target_edge,
            self.active_roi_angle_deg,
            self.active_caliper_count,
            self.active_caliper_width_px,
            self.active_search_direction,
            self.active_diameter_mode,
        ).normalized()

    def _move_active_roi(self, pos):
        if not self.is_moving_roi or self.move_start_img is None or self.move_start_roi is None:
            return
        p = self.widget_to_image_float(pos)
        if p is None:
            return
        dx = p[0] - self.move_start_img[0]
        dy = p[1] - self.move_start_img[1]
        roi = replace(self.move_start_roi, x=self.move_start_roi.x + dx, y=self.move_start_roi.y + dy)
        self.roiChanged.emit(self.active_mark_id, self.active_layer, roi.normalized())

    def _adjust_active_roi(self, pos):
        mark = self.marks.get(self.adjust_mark_id)
        if mark is None:
            return
        roi = mark.upper_roi if self.adjust_layer == "upper" else mark.lower_roi
        p = self.widget_to_image_float(pos)
        if roi is None or p is None:
            return
        r = roi.normalized()
        x, y = p
        typ = getattr(r, "roi_type", "Annulus")
        min_outer = 5.0
        min_width = 2.0

        if typ in {"Annulus", "Caliper Circle"}:
            cx, cy = r.center()
            dist = max(min_outer, float(np.hypot(x - cx, y - cy)))
            outer = r.outer_radius()
            inner = r.inner_radius()
            if self.adjust_roi_part == "inner":
                new_inner = float(np.clip(dist, min_width, max(min_width, outer - min_width)))
                roi.inner_ratio = new_inner / max(outer, 1e-9)
            elif self.adjust_roi_part == "outer":
                new_outer = max(dist, inner + min_width, min_outer)
                roi.x = cx - new_outer
                roi.y = cy - new_outer
                roi.w = new_outer * 2.0
                roi.h = new_outer * 2.0
                roi.inner_ratio = float(np.clip(inner / max(new_outer, 1e-9), 0.0, 0.98))

        elif typ == "Rectangular Ring":
            xs = np.array([x], dtype=np.float64)
            ys = np.array([y], dtype=np.float64)
            xr, yr = r._local_rotated(xs, ys)
            ax, ay = abs(float(xr[0])), abs(float(yr[0]))
            if self.adjust_roi_part == "inner":
                ratio = max(ax / max(r.w / 2.0, 1e-9), ay / max(r.h / 2.0, 1e-9))
                roi.inner_ratio = float(np.clip(ratio, 0.02, 0.98))
            elif self.adjust_roi_part == "outer":
                cx, cy = r.center()
                scale = max(ax / max(r.w / 2.0, 1e-9), ay / max(r.h / 2.0, 1e-9), min_outer / max(min(r.w, r.h), 1e-9))
                new_w = max(min_outer, r.w * scale)
                new_h = max(min_outer, r.h * scale)
                inner_w, inner_h = r.inner_size()
                roi.x = cx - new_w / 2.0
                roi.y = cy - new_h / 2.0
                roi.w = new_w
                roi.h = new_h
                roi.inner_ratio = float(np.clip(max(inner_w / new_w, inner_h / new_h), 0.0, 0.98))

        self.roiChanged.emit(self.adjust_mark_id, self.adjust_layer, roi.normalized())

    def reset_view(self, update: bool = True):
        self.user_zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        if update:
            self.update()

    def zoom_by(self, factor: float, center_pos=None):
        if self.pixmap_cache is None:
            return
        self._update_transform()
        if center_pos is None:
            center_pos = self.rect().center()
        before = self.widget_to_image_float(center_pos)
        if before is None:
            # Zoom around widget center when the cursor is outside the image.
            before = (
                (center_pos.x() - self.offset_x) / max(self.scale, 1e-12) - 0.5,
                (center_pos.y() - self.offset_y) / max(self.scale, 1e-12) - 0.5,
            )
        self.user_zoom = float(np.clip(self.user_zoom * factor, 0.05, 80.0))
        new_scale = self.fit_scale * self.user_zoom
        base_x, base_y = self._base_offset_for_scale(new_scale)
        img_x, img_y = before
        self.pan_x = center_pos.x() - (img_x + 0.5) * new_scale - base_x
        self.pan_y = center_pos.y() - (img_y + 0.5) * new_scale - base_y
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#252930"))

        if self.pixmap_cache is None:
            painter.setPen(QColor("#F5F6F8"))
            painter.drawText(self.rect(), Qt.AlignCenter, "等待导入图像")
            painter.end()
            return

        self._update_transform()
        target = QRectF(self.offset_x, self.offset_y, self.pixmap_cache.width() * self.scale, self.pixmap_cache.height() * self.scale)
        painter.drawPixmap(target, self.pixmap_cache, QRectF(self.pixmap_cache.rect()))

        self._draw_overlays(painter)
        self._draw_geometry_overlays(painter)

        header_rect = QRectF(8, 8, min(270, self.width() - 16), 48)
        painter.fillRect(header_rect, QColor(18, 21, 26, 185))
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.DemiBold))
        painter.drawText(16, 27, self.title)
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.setPen(QColor("#D7DCE3"))
        painter.drawText(16, 46, f"缩放 {self.user_zoom:.2f}x  ·  滚轮缩放 / 右键或中键平移")
        if self.circle_pick_mode:
            hint = f"三点定圆：已选 {len(self.circle_pick_points)}/3 点；可随时右键或中键平移"
            hint_rect = QRectF(12, self.height() - 76, min(360, self.width() - 24), 28)
            painter.fillRect(hint_rect, QColor(18, 21, 26, 205))
            painter.setPen(QColor("#7EE787"))
            painter.drawText(hint_rect.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, hint)
        elif self._has_caliper_result_for_hint():
            hint = (
                "卡尺调整中 · 点击空白处隐藏"
                if self.selected_caliper_feature
                else "点击拟合轮廓显示卡尺，点击空白处隐藏"
            )
            hint_rect = QRectF(12, self.height() - 76, min(330, self.width() - 24), 28)
            painter.fillRect(hint_rect, QColor(18, 21, 26, 205))
            painter.setPen(QColor("#7EE787"))
            painter.drawText(hint_rect.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, hint)
        self._draw_scale_and_axes(painter)
        painter.end()

    def _draw_geometry_overlays(self, painter: QPainter):
        result = self.geometry_result
        if result is None:
            return
        feature_pen = QPen(QColor("#34C759"), 2.0)
        feature_pen.setCosmetic(True)
        selected_pen = QPen(QColor("#FFD60A"), 2.5)
        selected_pen.setCosmetic(True)
        for feature_id, feature in result.features.items():
            if feature.status != "Valid" or feature.layer != self.active_layer:
                continue
            painter.setPen(selected_pen if feature_id == self.selected_geometry_feature_id else feature_pen)
            if feature.center_px is not None:
                cx, cy = self.image_to_widget(*feature.center_px)
                painter.drawLine(int(cx - 6), int(cy), int(cx + 6), int(cy))
                painter.drawLine(int(cx), int(cy - 6), int(cx), int(cy + 6))
                painter.drawText(int(cx + 8), int(cy - 8), feature.name)
                if feature.radius_px is not None:
                    radius = float(feature.radius_px) * self.scale
                    painter.drawEllipse(QRectF(cx - radius, cy - radius, 2.0 * radius, 2.0 * radius))
            if feature.feature_type == "line" and len(feature.points_px) >= 2:
                first = self.image_to_widget(*feature.points_px[0])
                second = self.image_to_widget(*feature.points_px[1])
                painter.drawLine(QPointF(*first), QPointF(*second))

        axis_pen = QPen(QColor("#00C7BE"), 2.0)
        axis_pen.setCosmetic(True)
        for coordinate in result.coordinate_systems.values():
            if coordinate.status != "Valid" or coordinate.layer != self.active_layer or coordinate.origin_px is None:
                continue
            origin = self.image_to_widget(*coordinate.origin_px)
            axis_length = 62.0
            x_axis = coordinate.x_axis_image or (1.0, 0.0)
            y_axis = coordinate.y_axis_image or (0.0, -1.0)
            painter.setPen(axis_pen)
            painter.drawLine(QPointF(*origin), QPointF(origin[0] + x_axis[0] * axis_length, origin[1] + x_axis[1] * axis_length))
            painter.drawLine(QPointF(*origin), QPointF(origin[0] + y_axis[0] * axis_length, origin[1] + y_axis[1] * axis_length))
            painter.drawText(int(origin[0] + x_axis[0] * axis_length + 4), int(origin[1] + x_axis[1] * axis_length), "X")
            painter.drawText(int(origin[0] + y_axis[0] * axis_length + 4), int(origin[1] + y_axis[1] * axis_length), "Y")

        label_pen = QPen(QColor("#FFFFFF"), 1.2)
        label_pen.setCosmetic(True)
        for label in result.coordinate_labels.values():
            if label.status != "Valid" or label.layer != self.active_layer or label.anchor_px is None or label.label_px is None:
                continue
            anchor = self.image_to_widget(*label.anchor_px)
            target = self.image_to_widget(*label.label_px)
            painter.setPen(label_pen)
            painter.drawLine(QPointF(*anchor), QPointF(*target))
            text = f"{label.name}  X={label.x_um:.3f} μm  Y={label.y_um:.3f} μm"
            metrics = painter.fontMetrics()
            rect = metrics.boundingRect(text).adjusted(-7, -5, 7, 5)
            rect.moveTopLeft(QPoint(int(target[0]), int(target[1] - rect.height())))
            painter.fillRect(rect, QColor(18, 21, 26, 210))
            painter.drawText(rect, Qt.AlignCenter, text)

    def _draw_scale_and_axes(self, painter: QPainter):
        if self.pixmap_cache is None or self.scale <= 0:
            return
        mean_um = max(1e-12, self._mean_pixel_size_um())
        target_um = 50.0
        for candidate in (5, 10, 20, 50, 100, 200, 500, 1000):
            if candidate / mean_um * self.scale >= 60:
                target_um = float(candidate)
                break
        bar_px_widget = target_um / mean_um * self.scale
        x0 = 24
        y0 = self.height() - 36
        painter.setPen(QPen(QColor("#FFFFFF"), 3.0))
        painter.drawLine(int(x0), int(y0), int(x0 + bar_px_widget), int(y0))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(int(x0), int(y0 - 8), f"{target_um:g} μm")
        ax0 = self.width() - 92
        ay0 = self.height() - 44
        painter.setPen(QPen(QColor("#FFFFFF"), 2.0))
        painter.drawLine(ax0, ay0, ax0 + 42, ay0)
        painter.drawLine(ax0, ay0, ax0, ay0 - 42)
        painter.drawText(ax0 + 48, ay0 + 5, "X")
        painter.drawText(ax0 - 10, ay0 - 48, "Y")

    def _draw_overlays(self, painter: QPainter):
        if self.image is None:
            return
        colors = {
            "upper": QColor("#007AFF"),
            "lower": QColor("#FF9500"),
        }
        for mark_id, mark in self.marks.items():
            if self.show_auto_detections:
                break
            if mark_id != self.active_mark_id:
                continue
            for layer in ("upper", "lower"):
                if self.fixed_layer and layer != self.fixed_layer:
                    continue
                if not self.fixed_layer and layer != self.active_layer:
                    continue
                roi = mark.upper_roi if layer == "upper" else mark.lower_roi
                det = self.detections.get(mark_id, {}).get(layer)
                detection_valid = det is not None and det.shape_params.get("quality_status", "Valid") != "Invalid"
                if self._manual_roi_visible(mark_id, layer, roi, det):
                    is_active = (mark_id == self.active_mark_id and layer == self.active_layer)
                    self._draw_roi_shape(painter, roi, colors[layer], is_active, f"{mark_id} {LAYER_LABELS[layer]}")

                if det is not None:
                    show_point_diagnostics = self.show_diagnostics or not detection_valid
                    if show_point_diagnostics:
                        painter.setPen(QPen(QColor("#34C759"), 1.0))
                        pts = det.edge_points
                        if pts:
                            step = max(1, len(pts) // 1200)
                            for px, py in pts[::step]:
                                wx, wy = self.image_to_widget(px, py)
                                painter.drawEllipse(QRectF(wx - 2.0, wy - 2.0, 4.0, 4.0))
                        rejected = getattr(det, "rejected_points", [])
                        if rejected:
                            painter.setPen(QPen(QColor("#FF3B30"), 1.4))
                            for px, py in rejected:
                                wx, wy = self.image_to_widget(px, py)
                                painter.drawLine(int(wx - 3), int(wy - 3), int(wx + 3), int(wy + 3))
                                painter.drawLine(int(wx - 3), int(wy + 3), int(wx + 3), int(wy - 3))
                    cx, cy = self.image_to_widget(det.center_x_px, det.center_y_px)
                    fit_color = QColor("#34C759")
                    painter.setPen(QPen(fit_color, 2.0))
                    painter.drawLine(int(cx - 8), int(cy), int(cx + 8), int(cy))
                    painter.drawLine(int(cx), int(cy - 8), int(cx), int(cy + 8))
                    contour_label = self.manual_labels.get((mark_id, layer), "")
                    if contour_label:
                        label_x, label_y = self._contour_label_anchor(det)
                        painter.drawText(int(label_x + 6), int(label_y - 6), f"{contour_label} ({mark_id})")
                    if det.fitting_mode in {"Circle", "EdgeCenter", "CaliperCircle"} and "radius_px" in det.shape_params:
                        rad = det.shape_params["radius_px"] * self.scale
                        painter.setPen(QPen(fit_color, 2.0))
                        painter.drawEllipse(QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad))
                        if det.fitting_mode == "CaliperCircle" and self.show_diagnostics:
                            average_um = float(det.shape_params.get("average_diameter_um", det.diameter_um))
                            maximum_um = float(det.shape_params.get("maximum_diameter_um", average_um))
                            painter.setPen(fit_color)
                            painter.drawText(
                                int(cx + 12),
                                int(cy - 12),
                                f"中心=({det.center_x_um:.3f},{det.center_y_um:.3f}) μm 平均直径={average_um:.3f} μm 最大直径={maximum_um:.3f} μm",
                            )
                    elif det.fitting_mode == "RegionCenter":
                        # V1.4: region-center mode is area segmentation, not circle fitting.
                        # Show only the final selected main contour and min-area box; do not
                        # draw the equivalent-area circle because it is misleading for rounded square holes.
                        contour_points = det.shape_params.get("contour_points", [])
                        if contour_points:
                            widget_points = [QPointF(*self.image_to_widget(float(px), float(py))) for px, py in contour_points]
                            if len(widget_points) >= 3:
                                fill_path = QPainterPath()
                                fill_path.moveTo(widget_points[0])
                                for pt in widget_points[1:]:
                                    fill_path.lineTo(pt)
                                fill_path.closeSubpath()
                                painter.fillPath(fill_path, QColor(52, 199, 89, 36))
                                contour_pen = QPen(QColor("#34C759"), 2.0)
                                contour_pen.setCosmetic(True)
                                painter.setPen(contour_pen)
                                painter.drawPolygon(QPolygonF(widget_points))
                        box_points = det.shape_params.get("region_box_points", [])
                        if box_points:
                            box_widget = [QPointF(*self.image_to_widget(float(px), float(py))) for px, py in box_points]
                            if len(box_widget) >= 4:
                                fit_pen = QPen(fit_color, 2.0)
                                fit_pen.setCosmetic(True)
                                painter.setPen(fit_pen)
                                painter.drawPolygon(QPolygonF(box_widget))
                        width = det.shape_params.get("width_px", 0.0) * self.pixel_size_x_um
                        height = det.shape_params.get("height_px", 0.0) * self.pixel_size_y_um
                        area = det.shape_params.get("region_area_px2", 0.0)
                        polarity = det.shape_params.get("region_polarity", "")
                        painter.setPen(fit_color)
                        painter.drawText(
                            int(cx + 10),
                            int(cy - 10),
                            f"区域中心 W={width:.3f} μm H={height:.3f} μm 面积={area:.0f}px² {polarity}",
                        )
                    elif det.fitting_mode == "Ellipse":
                        major = det.shape_params.get("major_px", det.diameter_px) * self.scale
                        minor = det.shape_params.get("minor_px", det.diameter_px) * self.scale
                        # For V1 display, draw axis-aligned ellipse; angle is reported numerically in table.
                        painter.setPen(QPen(fit_color, 2.0))
                        painter.drawEllipse(QRectF(cx - major / 2, cy - minor / 2, major, minor))
                    elif det.fitting_mode == "Rectangle":
                        # V1.0.4: draw a clearly visible rotated rectangle contour.
                        # Earlier versions calculated the rectangle center, but the outline
                        # could be too thin/ambiguous on high-resolution microscope images.
                        width = det.shape_params.get("width_px", det.diameter_px)
                        height = det.shape_params.get("height_px", det.diameter_px)
                        angle_deg = det.shape_params.get("angle_deg", 0.0)
                        angle = np.deg2rad(angle_deg)
                        hw = width / 2.0
                        hh = height / 2.0
                        local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
                        ct, st = np.cos(angle), np.sin(angle)
                        qpoints = []
                        for lx, ly in local:
                            ix = det.center_x_px + ct * lx - st * ly
                            iy = det.center_y_px + st * lx + ct * ly
                            wx, wy = self.image_to_widget(ix, iy)
                            qpoints.append((wx, wy))

                        fit_pen = QPen(fit_color, 2.8)
                        fit_pen.setCosmetic(True)
                        painter.setPen(fit_pen)
                        for i in range(4):
                            x0, y0 = qpoints[i]
                            x1, y1 = qpoints[(i + 1) % 4]
                            painter.drawLine(int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))

                        # Corner handles make it obvious this is the fitted square/rectangle.
                        painter.setPen(QPen(fit_color, 1.5))
                        for wx, wy in qpoints:
                            painter.drawRect(QRectF(wx - 3.5, wy - 3.5, 7.0, 7.0))

                        # Draw the fit parameter label close to the contour.
                        label_x = int(round(min(x for x, _ in qpoints)))
                        label_y = int(round(min(y for _, y in qpoints))) - 6
                        painter.setPen(fit_color)
                        painter.drawText(
                            label_x,
                            label_y,
                            f"矩形 W={width * self.pixel_size_x_um:.3f} μm H={height * self.pixel_size_y_um:.3f} μm 角度={angle_deg:.1f}° 残差={det.residual_um:.3f} μm",
                        )

        if self.show_auto_detections:
            self._draw_auto_detection_results(painter)

        if self.is_dragging and self.drag_start_img is not None and self.drag_current_img is not None:
            preview_roi = Roi(
                float(self.drag_start_img.x()),
                float(self.drag_start_img.y()),
                float(self.drag_current_img.x() - self.drag_start_img.x()),
                float(self.drag_current_img.y() - self.drag_start_img.y()),
                self.active_roi_type,
                self.active_roi_inner_ratio,
                self.active_roi_target_edge,
                self.active_roi_angle_deg,
            ).normalized()
            self._draw_roi_shape(painter, preview_roi, QColor(120, 255, 120), True, "预览")

        if self.circle_pick_mode and self.circle_pick_points:
            painter.setPen(QPen(QColor(120, 255, 120), 2.0))
            for x, y in self.circle_pick_points:
                wx, wy = self.image_to_widget(x, y)
                painter.drawEllipse(QRectF(wx - 4, wy - 4, 8, 8))
            if len(self.circle_pick_points) == 2:
                x0, y0 = self.image_to_widget(*self.circle_pick_points[0])
                x1, y1 = self.image_to_widget(*self.circle_pick_points[1])
                painter.drawLine(int(x0), int(y0), int(x1), int(y1))
                preview_roi = self._caliper_roi_from_center_circle(
                    self._circle_from_three_points([*self.circle_pick_points, self.circle_preview_point])
                    if self.circle_preview_point is not None
                    else None
                )
                if preview_roi is not None:
                    self._draw_roi_shape(painter, preview_roi, QColor(120, 255, 120), True, "三点预览")
                    mid_radius = 0.5 * (preview_roi.inner_radius() + preview_roi.outer_radius())
                    cx, cy = self.image_to_widget(*preview_roi.center())
                    painter.setPen(QPen(QColor(120, 255, 120), 1.2))
                    painter.drawText(
                        int(cx + 10),
                        int(cy + 22),
                        f"中心半径={mid_radius:.2f} px  半宽={self.active_ring_half_width_px:.2f} px",
                    )

    def _draw_auto_detection_results(self, painter: QPainter):
        label_index = 0
        for label, layer_map in self.auto_detections.items():
            for layer, detection in layer_map.items():
                if self.fixed_layer and layer != self.fixed_layer:
                    continue
                valid = detection.shape_params.get("quality_status", "Valid") == "Valid"
                if not valid:
                    color = QColor(255, 60, 60)
                    role = "无效"
                elif label == self.auto_reference_label:
                    color = QColor(0, 220, 255)
                    role = "基准"
                elif label == self.auto_target_label:
                    color = QColor(255, 210, 0)
                    role = "待测"
                else:
                    color = QColor(0, 255, 90)
                    role = "有效"
                contour_points = detection.shape_params.get("candidate_contour_points", detection.edge_points)
                if self.show_diagnostics and contour_points:
                    widget_points = [
                        QPointF(*self.image_to_widget(float(point[0]), float(point[1])))
                        for point in contour_points
                    ]
                    pen = QPen(QColor(160, 160, 160), 1.0)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.drawPolygon(QPolygonF(widget_points))
                cx, cy = self.image_to_widget(detection.center_x_px, detection.center_y_px)
                pen = QPen(color, 2.3)
                pen.setCosmetic(True)
                painter.setPen(pen)
                if detection.fitting_mode == "ProductionCircle":
                    radius = float(detection.shape_params.get("radius_px", detection.diameter_px / 2.0)) * self.scale
                    painter.drawEllipse(QRectF(cx - radius, cy - radius, 2.0 * radius, 2.0 * radius))
                elif detection.fitting_mode == "ProductionRectangle":
                    width = float(detection.shape_params.get("width_px", detection.diameter_px))
                    height = float(detection.shape_params.get("height_px", detection.diameter_px))
                    angle = np.deg2rad(float(detection.shape_params.get("angle_deg", 0.0)))
                    ct, st = np.cos(angle), np.sin(angle)
                    points = []
                    for lx, ly in ((-width / 2, -height / 2), (width / 2, -height / 2), (width / 2, height / 2), (-width / 2, height / 2)):
                        x = detection.center_x_px + ct * lx - st * ly
                        y = detection.center_y_px + st * lx + ct * ly
                        points.append(QPointF(*self.image_to_widget(x, y)))
                    painter.drawPolygon(QPolygonF(points))
                painter.drawLine(int(cx - 6), int(cy), int(cx + 6), int(cy))
                painter.drawLine(int(cx), int(cy - 6), int(cx), int(cy + 6))
                if self._auto_caliper_selected(label, layer, detection):
                    painter.setPen(QPen(QColor(255, 210, 0, 140), 1.0))
                    for window in detection.shape_params.get("caliper_windows", []):
                        length = float(window.get("length", 0.0)) * self.scale
                        if "angle" in window:
                            direction_x = np.cos(float(window["angle"]))
                            direction_y = np.sin(float(window["angle"]))
                        else:
                            direction_x = float(window.get("direction_x", 0.0))
                            direction_y = float(window.get("direction_y", 0.0))
                        x, y = self.image_to_widget(float(window.get("center_x", 0.0)), float(window.get("center_y", 0.0)))
                        painter.drawLine(
                            int(x - direction_x * length / 2.0),
                            int(y - direction_y * length / 2.0),
                            int(x + direction_x * length / 2.0),
                            int(y + direction_y * length / 2.0),
                        )
                if self.show_diagnostics:
                    painter.setPen(QPen(QColor("#34C759"), 1.0))
                    for px, py in detection.edge_points:
                        x, y = self.image_to_widget(px, py)
                        painter.drawEllipse(QRectF(x - 2, y - 2, 4, 4))
                    painter.setPen(QPen(QColor(255, 60, 60), 1.0))
                    for px, py in detection.rejected_points:
                        x, y = self.image_to_widget(px, py)
                        painter.drawLine(int(x - 3), int(y - 3), int(x + 3), int(y + 3))
                        painter.drawLine(int(x - 3), int(y + 3), int(x + 3), int(y - 3))
                suffix = f" {role}" if role else ""
                label_x, label_y = self._contour_label_anchor(detection, label_index)
                label_index += 1
                painter.drawText(
                    int(label_x + 5),
                    int(label_y - 5),
                    f"{candidate_display_label(label, detection)}{suffix}",
                )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.selected_caliper_feature is not None:
            self.clear_caliper_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if self.image is None:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.25 if delta > 0 else 0.8
        self.zoom_by(factor, event.position().toPoint())
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.image is not None:
            self.reset_view(update=True)
            event.accept()

    def mousePressEvent(self, event):
        if self.image is None:
            return
        if event.button() == Qt.RightButton:
            if not self.circle_pick_mode and not self.show_auto_detections and self._point_in_active_roi_outer(event.position().toPoint()):
                menu = QMenu(self)
                delete_action = menu.addAction("删除当前 ROI")
                action = menu.exec(event.globalPosition().toPoint())
                if action == delete_action:
                    self.roiChanged.emit(self.active_mark_id, self.active_layer, None)
                event.accept()
                return
            self.is_panning = True
            self.pan_start_pos = event.position().toPoint()
            self.pan_start_x = self.pan_x
            self.pan_start_y = self.pan_y
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MiddleButton:
            self.is_panning = True
            self.pan_start_pos = event.position().toPoint()
            self.pan_start_x = self.pan_x
            self.pan_start_y = self.pan_y
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            if self.geometry_interaction_active:
                point = self.widget_to_image_float(event.position().toPoint())
                if point is not None:
                    feature_id = self._geometry_hit(event.position().toPoint())
                    detection_key = self._detection_key_hit(event.position().toPoint())
                    self.selected_geometry_feature_id = feature_id
                    self.geometryClicked.emit(
                        self.active_layer,
                        {
                            "point_px": (float(point[0]), float(point[1])),
                            "feature_id": feature_id,
                            "detection_key": detection_key,
                        },
                    )
                    self.update()
                event.accept()
                return
            if self.show_auto_detections:
                hit = self._nearest_auto_caliper_hit(event.position().toPoint())
                if hit is not None:
                    label, layer, detection = hit
                    self._select_caliper_detection("auto", label, layer, detection)
                elif self.selected_caliper_feature is not None:
                    self.clear_caliper_selection()
                event.accept()
                return
            if self.circle_pick_mode:
                p = self.widget_to_image_float(event.position().toPoint())
                if p is not None:
                    self.circle_pick_points.append(p)
                    if len(self.circle_pick_points) == 3:
                        roi = self._caliper_roi_from_center_circle(self._circle_from_three_points(self.circle_pick_points))
                        if roi is not None:
                            self.roiChanged.emit(self.active_mark_id, self.active_layer, roi)
                        self.set_circle_pick_mode(False)
                    self.update()
                event.accept()
                return
            manual_hit = self._manual_caliper_hit(event.position().toPoint())
            current_detection = self.detections.get(self.active_mark_id, {}).get(self.active_layer)
            manual_selected = self._manual_caliper_selected(
                self.active_mark_id,
                self.active_layer,
                current_detection,
            )
            if manual_hit is not None and not manual_selected:
                mark_id, layer, detection = manual_hit
                self._select_caliper_detection("manual", mark_id, layer, detection)
                event.accept()
                return
            if manual_selected and not self._point_in_active_roi_outer(event.position().toPoint()):
                self.clear_caliper_selection()
                event.accept()
                return
            hit_part = self._roi_hit_part(event.position().toPoint())
            if hit_part:
                self.is_adjusting_roi = True
                self.adjust_roi_part = hit_part
                self.adjust_mark_id = self.active_mark_id
                self.adjust_layer = self.active_layer
                self.setCursor(Qt.SizeAllCursor)
                event.accept()
                return
            if self._point_in_active_roi_outer(event.position().toPoint()):
                roi = self._active_roi()
                p = self.widget_to_image_float(event.position().toPoint())
                if roi is not None and p is not None:
                    self.is_moving_roi = True
                    self.move_start_img = p
                    self.move_start_roi = roi.normalized()
                    self.setCursor(Qt.SizeAllCursor)
                    event.accept()
                    return
            p = self.widget_to_image(event.position().toPoint())
            if p is not None:
                self.drag_start_img = p
                self.drag_current_img = p
                self.is_dragging = True
                self.update()

    def mouseMoveEvent(self, event):
        if self.is_panning and self.pan_start_pos is not None:
            pos = event.position().toPoint()
            self.pan_x = self.pan_start_x + (pos.x() - self.pan_start_pos.x())
            self.pan_y = self.pan_start_y + (pos.y() - self.pan_start_pos.y())
            self.update()
            event.accept()
            return
        if self.circle_pick_mode and len(self.circle_pick_points) == 2:
            p = self.widget_to_image_float(event.position().toPoint())
            if p is not None:
                self.circle_preview_point = p
                self.update()
            event.accept()
            return
        if self.is_dragging and self.image is not None:
            p = self.widget_to_image(event.position().toPoint())
            if p is not None:
                self.drag_current_img = p
                self.update()
            return
        if self.is_adjusting_roi and self.image is not None:
            self._adjust_active_roi(event.position().toPoint())
            self.update()
            event.accept()
            return
        if self.is_moving_roi and self.image is not None:
            self._move_active_roi(event.position().toPoint())
            self.update()
            event.accept()
            return
        self._update_edge_tooltip(event.position().toPoint())

    def _update_edge_tooltip(self, pos):
        if self.image is None:
            return
        best = None
        best_dist = 7.0
        result_maps = [self.auto_detections] if self.show_auto_detections else [self.detections]
        for result_map in result_maps:
            for mark_id, layer_map in result_map.items():
                if not self.show_auto_detections and mark_id != self.active_mark_id:
                    continue
                for layer, det in layer_map.items():
                    if self.fixed_layer and layer != self.fixed_layer:
                        continue
                    if not self.show_auto_detections and not self.fixed_layer and layer != self.active_layer:
                        continue
                    point_groups = (
                        (det.edge_points, getattr(det, "edge_gradients", []), "参与拟合"),
                        (getattr(det, "rejected_points", []), getattr(det, "rejected_gradients", []), "已剔除"),
                    )
                    for points, gradients, state in point_groups:
                        for idx, (px, py) in enumerate(points):
                            wx, wy = self.image_to_widget(px, py)
                            dist = float(np.hypot(wx - pos.x(), wy - pos.y()))
                            if dist < best_dist:
                                grad_txt = f"{gradients[idx]:.3f}" if idx < len(gradients) else "-"
                                best = (
                                    f"{mark_id} {LAYER_LABELS.get(layer, layer)} {state}\n"
                                    f"坐标=({px * self.pixel_size_x_um:.3f}, {py * self.pixel_size_y_um:.3f}) μm\n梯度={grad_txt}"
                                )
                                best_dist = dist
        self.setToolTip(best or "")

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.RightButton, Qt.MiddleButton) and self.is_panning:
            self.is_panning = False
            self.pan_start_pos = None
            self.setCursor(Qt.CrossCursor if self.circle_pick_mode else Qt.ArrowCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.is_moving_roi:
            self._move_active_roi(event.position().toPoint())
            self.is_moving_roi = False
            self.move_start_img = None
            self.move_start_roi = None
            self.setCursor(Qt.ArrowCursor)
            self.update()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.is_adjusting_roi:
            self._adjust_active_roi(event.position().toPoint())
            self.is_adjusting_roi = False
            self.adjust_roi_part = ""
            self.adjust_mark_id = ""
            self.adjust_layer = ""
            self.setCursor(Qt.ArrowCursor)
            self.update()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.is_dragging and self.drag_start_img is not None:
            p = self.widget_to_image(event.position().toPoint())
            if p is None:
                p = self.drag_current_img
            self.is_dragging = False
            if p is not None:
                x0, y0 = self.drag_start_img.x(), self.drag_start_img.y()
                x1, y1 = p.x(), p.y()
                if abs(x1 - x0) >= 5 and abs(y1 - y0) >= 5:
                    roi_type = self.active_roi_type
                    w = float(x1 - x0)
                    h = float(y1 - y0)
                    if roi_type == "Caliper Circle":
                        side = min(abs(w), abs(h))
                        w = side if w >= 0 else -side
                        h = side if h >= 0 else -side
                    roi = Roi(
                        float(x0),
                        float(y0),
                        w,
                        h,
                        roi_type,
                        self.active_roi_inner_ratio,
                        self.active_roi_target_edge,
                        self.active_roi_angle_deg,
                    ).normalized()
                    self.roiChanged.emit(self.active_mark_id, self.active_layer, roi)
            self.drag_start_img = None
            self.drag_current_img = None
            self.update()


class RepeatabilityPlot(QWidget):
    """Lightweight repeatability trend plot without extra plotting dependencies."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series = {}
        self.setMinimumHeight(150)
        self.setStyleSheet("QWidget { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 10px; }")

    def set_series(self, series: dict):
        self.series = series or {}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        margin_l, margin_r, margin_t, margin_b = 46, 16, 18, 30
        rect = self.rect().adjusted(margin_l, margin_t, -margin_r, -margin_b)
        painter.setPen(QPen(QColor("#DADDE3"), 1))
        painter.drawRect(rect)
        if not self.series:
            painter.setPen(QColor("#6E6E73"))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无重复性数据")
            painter.end()
            return
        values = []
        max_len = 0
        for vals in self.series.values():
            values.extend([float(v) for v in vals])
            max_len = max(max_len, len(vals))
        if not values or max_len <= 0:
            painter.end(); return
        vmin, vmax = min(values), max(values)
        if abs(vmax - vmin) < 1e-12:
            vmax = vmin + 1.0
            vmin = vmin - 1.0
        painter.setPen(QColor("#6E6E73"))
        painter.drawText(8, rect.top() + 10, f"{vmax:.3f}")
        painter.drawText(8, rect.bottom(), f"{vmin:.3f}")
        palette = [QColor("#007AFF"), QColor("#FF9500"), QColor("#34C759"), QColor("#AF52DE")]
        legend_x = rect.left() + 4
        for idx, (name, vals) in enumerate(self.series.items()):
            color = palette[idx % len(palette)]
            painter.setPen(QPen(color, 2.0))
            points = []
            for i, val in enumerate(vals):
                x = rect.left() + (rect.width() * i / max(1, max_len - 1))
                y = rect.bottom() - (rect.height() * (float(val) - vmin) / (vmax - vmin))
                points.append(QPointF(x, y))
            for a, b in zip(points, points[1:]):
                painter.drawLine(a, b)
            for pt in points:
                painter.drawEllipse(QRectF(pt.x() - 2.5, pt.y() - 2.5, 5, 5))
            painter.drawText(legend_x, self.rect().bottom() - 8 - 16 * idx, name)
        painter.setPen(QColor("#6E6E73"))
        painter.drawText(rect.center().x() - 40, self.rect().bottom() - 8, "测量次数")
        painter.end()

