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

from .ui_constants import LAYER_LABELS, RESULT_LABELS, STEP_TITLES
from .ui_components import (
    CollapsibleSection,
    FramelessTitleBar,
    ImageCanvas,
    RepeatabilityPlot,
    SidebarComboBox,
    SidebarDoubleSpinBox,
    SidebarSpinBox,
)
from .ui_recipe_views import RecipeLibraryDialog, RecipeQuickMenu
from .ui_workers import MeasurementWorker


class MainWindowStateMixin:
        def on_operation_mode_changed(self):
            requested = self.operation_mode_combo.currentData() or "Production"
            if requested == self.operation_mode:
                return
            if requested == "Engineering":
                password, accepted = QInputDialog.getText(
                    self,
                    "进入工程模式",
                    "请输入工程模式密码：",
                    QLineEdit.Password,
                )
                if not accepted or not self.access_controller.verify(password):
                    self.operation_mode_combo.blockSignals(True)
                    self._set_combo_value(self.operation_mode_combo, "Production")
                    self.operation_mode_combo.blockSignals(False)
                    self.runtime_logger.warning("Engineering mode authentication failed")
                    if accepted:
                        QMessageBox.warning(self, "密码错误", "工程模式密码不正确。")
                    return
            self.operation_mode = requested
            self.runtime_logger.info("Operation mode changed to %s", requested)
            self._apply_operation_mode()

        def change_engineering_password(self):
            if self.operation_mode != "Engineering":
                QMessageBox.warning(self, "权限不足", "请先验证密码并切换到工程模式。")
                return
            current, accepted = QInputDialog.getText(
                self, "修改工程模式密码", "请输入当前密码：", QLineEdit.Password
            )
            if not accepted:
                return
            if not self.access_controller.verify(current):
                QMessageBox.warning(self, "密码错误", "当前工程模式密码不正确。")
                return
            new_password, accepted = QInputDialog.getText(
                self, "修改工程模式密码", "请输入新密码（至少 6 个字符）：", QLineEdit.Password
            )
            if not accepted:
                return
            confirmation, accepted = QInputDialog.getText(
                self, "修改工程模式密码", "请再次输入新密码：", QLineEdit.Password
            )
            if not accepted:
                return
            if new_password != confirmation:
                QMessageBox.warning(self, "两次输入不一致", "两次输入的新密码不一致。")
                return
            try:
                self.access_controller.set_password(new_password)
            except ValueError as exc:
                QMessageBox.warning(self, "密码无效", str(exc))
                return
            self.runtime_logger.info("Engineering mode password changed")
            QMessageBox.information(self, "修改完成", "工程模式密码已更新。")

        def _set_operation_mode(self, mode: str, *, authenticated: bool = False):
            if mode == "Engineering" and not authenticated:
                raise PermissionError("切换工程模式需要身份验证")
            self.operation_mode = mode
            self.operation_mode_combo.blockSignals(True)
            self._set_combo_value(self.operation_mode_combo, mode)
            self.operation_mode_combo.blockSignals(False)
            self._apply_operation_mode()

        def _apply_operation_mode(self):
            if not hasattr(self, "side_tabs"):
                return
            engineering = self.operation_mode == "Engineering"
            self.side_tabs.setTabEnabled(2, engineering)
            self.side_tabs.setTabEnabled(3, engineering)
            self.save_recipe_btn.setEnabled(engineering and not self._calculation_running)
            self.diagnostic_check.setEnabled(engineering)
            self.change_engineering_password_btn.setEnabled(engineering and not self._calculation_running)
            for widget in (
                self.material_code_edit,
                self.recipe_name_edit,
                self.recipe_version_edit,
                self.recipe_status_combo,
                self.process_name_edit,
                self.equipment_model_edit,
                self.calibration_date_edit,
            ):
                widget.setEnabled(engineering)
            if not engineering and self.side_tabs.currentIndex() in {2, 3}:
                self.side_tabs.setCurrentIndex(1)
            color = "#2468B2" if engineering else "#248A3D"
            background = "#EAF3FD" if engineering else "#F1F7F3"
            self.operation_mode_combo.setStyleSheet(
                f"color: {color}; background: {background}; font-weight: 600;"
            )
            self.operation_mode_combo.setToolTip(
                "工程模式：允许修改 ROI、算法参数和配方。" if engineering
                else "生产模式：配方与算法参数已锁定。切换工程模式需要密码。"
            )

        def on_display_enhancement_changed(self, checked: bool):
            self.upper_canvas.set_display_enhancement(checked)
            self.lower_canvas.set_display_enhancement(checked)
            self._append_log("已开启显示增强。" if checked else "已关闭显示增强。")

        def _append_log(self, message: str):
            # V1.2.5：取消独立日志窗口，所有操作反馈统一显示在左下角状态栏，避免界面拥挤。
            self.statusBar().showMessage(message, 3500)

        def _friendly_error(self, exc: Exception) -> str:
            message = str(exc).strip()
            if not message:
                return "分析发生未知异常。请检查图像、ROI 和算法参数后重试。"
            if "有效边缘点不足" in message or "最少边缘点数" in message:
                return (
                    "有效边缘点不足。请确认 ROI 覆盖目标边缘，适当扩大搜索环带、"
                    "降低最小梯度，或切换到宽容质量门槛。\n"
                    f"详细信息：{message}"
                )
            if "卡尺找圆" in message and "不足" in message:
                return (
                    "卡尺圆找到的有效边缘点不足。请收窄到正确边缘、检查搜索方向和边缘极性，"
                    "或适当降低最小梯度。\n"
                    f"详细信息：{message}"
                )
            if "残差" in message:
                return (
                    "拟合残差超过当前要求。请确认 ROI 是否混入其他边缘；来料加工质量较差时，"
                    "可由工程人员评估后使用宽容质量门槛。\n"
                    f"详细信息：{message}"
                )
            if "ROI" in message:
                return f"ROI 分析失败。请确认已导入对应图像，并且 ROI 框住目标特征。\n详细信息：{message}"
            return message

        def show_algorithm_path_dialog(self):
            text = getattr(self, "algorithm_path_text", "暂无测量结果；分析 ROI 或自动识别后可查看实际算法路径。")
            QMessageBox.information(self, "算法路径", text.replace("；", "\n\n"))

        def _install_button_feedback(self):
            for button in self.findChildren(QPushButton):
                if button.property("feedback_installed"):
                    continue
                button.setProperty("feedback_installed", True)
                button.clicked.connect(lambda checked=False, b=button: self._append_log(f"点击按钮：{b.text().replace('&', '')}"))
                button.setToolTip(button.toolTip() or f"点击执行：{button.text().replace('&', '')}")

        def _pull_config_from_ui(self):
            self.config.mode = self._current_mode()
            self.config.workflow_mode = self._combo_value(self.workflow_combo)
            self.config.auto_reference_label = self.auto_reference_combo.currentData() or ""
            self.config.auto_target_label = self.auto_target_combo.currentData() or ""
            self.config.material_code = self.material_code_edit.text().strip()
            self.config.recipe_name = self.recipe_name_edit.text().strip()
            self.config.recipe_version = self.recipe_version_edit.text().strip()
            self.config.recipe_validation_status = self._combo_value(self.recipe_status_combo)
            self.config.process_name = self.process_name_edit.text().strip()
            self.config.equipment_model = self.equipment_model_edit.text().strip()
            self.config.calibration_date = self.calibration_date_edit.text().strip()
            self.config.operator_name = self.operator_name_edit.text().strip()
            self.config.pixel_size_x_um = self.pixel_x_spin.value()
            self.config.pixel_size_y_um = self.pixel_y_spin.value()
            self.config.registration_offset_x_um = self.offset_x_spin.value()
            self.config.registration_offset_y_um = self.offset_y_spin.value()
            self.config.rx_angle_urad = self.rx_angle_spin.value()
            self.config.ry_angle_urad = self.ry_angle_spin.value()
            self.config.material_thickness_mm = self.material_thickness_spin.value()
            self.config.delta_x_limit_um = self.dx_limit_spin.value()
            self.config.delta_y_limit_um = self.dy_limit_spin.value()
            self.config.overlay_r_limit_um = self.r_limit_spin.value()
            self.config.quality_profile = self._combo_value(self.quality_profile_combo)
            self.config.confidence_min = self.conf_min_spin.value()
            self.config.rz_layout = self.rz_layout_combo.currentText()
            self.config.rz_distance_l_um = self.rz_l_spin.value()
            self.config.rz_limit = self.rz_limit_spin.value()
            self.config.production_caliper_count = self.caliper_count_spin.value()
            self.config.production_caliper_width_px = self.caliper_width_spin.value()
            self.config.production_search_half_width_px = self.production_search_spin.value()
            self.config.production_min_coverage = self.production_coverage_spin.value()
            self.config.production_max_rejected_ratio = self.production_reject_spin.value()
            self.config.production_max_residual_um = self.production_residual_spin.value()
            self.config.production_max_radial_deviation_um = self.production_deviation_spin.value()

            self.params.gaussian_sigma_px = self.sigma_spin.value()
            self.params.canny_low = self.canny_low_spin.value()
            self.params.canny_high = self.canny_high_spin.value()
            self.params.min_gradient = self.min_gradient_spin.value()
            self.params.profile_half_width_px = self.profile_half_spin.value()
            self.params.profile_step_px = self.profile_step_spin.value()
            self.params.fitting_mode = self._combo_value(self.fit_mode_combo)
            self.params.upper_fitting_mode = self._combo_value(self.upper_fit_mode_combo)
            self.params.lower_fitting_mode = self._combo_value(self.lower_fit_mode_combo)
            self.params.use_ransac = self.ransac_check.isChecked()
            self.params.residual_limit_px = self.residual_limit_spin.value()
            self.params.min_edge_points = self.min_edge_points_spin.value()
            self.params.polarity = self._combo_value(self.polarity_combo)
            self.params.measurement_timeout_s = self.measurement_timeout_spin.value()

        def _push_config_to_ui(self):
            self._set_mode_ui(self.config.mode)
            self._set_combo_value(self.workflow_combo, getattr(self.config, "workflow_mode", "Manual"))
            self.material_code_edit.setText(getattr(self.config, "material_code", ""))
            self.recipe_name_edit.setText(getattr(self.config, "recipe_name", ""))
            self.recipe_version_edit.setText(getattr(self.config, "recipe_version", "1.0"))
            self._set_combo_value(self.recipe_status_combo, getattr(self.config, "recipe_validation_status", "Draft"))
            self.process_name_edit.setText(getattr(self.config, "process_name", ""))
            self.equipment_model_edit.setText(getattr(self.config, "equipment_model", ""))
            self.calibration_date_edit.setText(getattr(self.config, "calibration_date", ""))
            self.operator_name_edit.setText(getattr(self.config, "operator_name", ""))
            self.pixel_x_spin.setValue(self.config.pixel_size_x_um)
            self.pixel_y_spin.setValue(self.config.pixel_size_y_um)
            self.offset_x_spin.setValue(self.config.registration_offset_x_um)
            self.offset_y_spin.setValue(self.config.registration_offset_y_um)
            self.rx_angle_spin.setValue(getattr(self.config, "rx_angle_urad", 0.0))
            self.ry_angle_spin.setValue(getattr(self.config, "ry_angle_urad", 0.0))
            self.material_thickness_spin.setValue(getattr(self.config, "material_thickness_mm", 0.0))
            self.dx_limit_spin.setValue(self.config.delta_x_limit_um)
            self.dy_limit_spin.setValue(self.config.delta_y_limit_um)
            self.r_limit_spin.setValue(self.config.overlay_r_limit_um)
            self.quality_profile_combo.blockSignals(True)
            self._set_combo_value(
                self.quality_profile_combo,
                getattr(self.config, "quality_profile", "Standard"),
            )
            self.quality_profile_combo.blockSignals(False)
            self._updating_quality_controls = True
            self.conf_min_spin.setValue(self.config.confidence_min)
            self.rz_layout_combo.setCurrentText(getattr(self.config, "rz_layout", "Y向前后分布"))
            self.rz_l_spin.setValue(getattr(self.config, "rz_distance_l_um", 1.0))
            self.rz_limit_spin.setValue(getattr(self.config, "rz_limit", 999999.0))
            self.caliper_count_spin.setValue(getattr(self.config, "production_caliper_count", 64))
            self.caliper_width_spin.setValue(getattr(self.config, "production_caliper_width_px", 8.0))
            self.production_search_spin.setValue(getattr(self.config, "production_search_half_width_px", 8.0))
            self.production_coverage_spin.setValue(getattr(self.config, "production_min_coverage", 0.65))
            self.production_reject_spin.setValue(getattr(self.config, "production_max_rejected_ratio", 0.40))
            self.production_residual_spin.setValue(getattr(self.config, "production_max_residual_um", 0.30))
            self.production_deviation_spin.setValue(getattr(self.config, "production_max_radial_deviation_um", 0.60))
            self._updating_quality_controls = False
            self._refresh_quality_profile_hint()

            self.sigma_spin.setValue(self.params.gaussian_sigma_px)
            self.canny_low_spin.setValue(self.params.canny_low)
            self.canny_high_spin.setValue(self.params.canny_high)
            self.min_gradient_spin.setValue(self.params.min_gradient)
            self.profile_half_spin.setValue(self.params.profile_half_width_px)
            self.profile_step_spin.setValue(self.params.profile_step_px)
            self._set_combo_value(self.fit_mode_combo, self.params.fitting_mode)
            self._set_combo_value(self.upper_fit_mode_combo, getattr(self.params, "upper_fitting_mode", self.params.fitting_mode))
            self._set_combo_value(self.lower_fit_mode_combo, getattr(self.params, "lower_fitting_mode", self.params.fitting_mode))
            self.ransac_check.setChecked(self.params.use_ransac)
            self.residual_limit_spin.setValue(self.params.residual_limit_px)
            self.min_edge_points_spin.setValue(self.params.min_edge_points)
            self._set_combo_value(self.polarity_combo, self.params.polarity)
            self.measurement_timeout_spin.setValue(getattr(self.params, "measurement_timeout_s", 180))
            self._set_combo_value(self.auto_reference_combo, getattr(self.config, "auto_reference_label", ""))
            self._set_combo_value(self.auto_target_combo, getattr(self.config, "auto_target_label", ""))

        def _current_roi(self):
            mark_id = self.mark_combo.currentText() or "Mark1"
            layer = self._current_layer()
            mark = self.marks.get(mark_id)
            if not mark:
                return None
            return mark.upper_roi if layer == "upper" else mark.lower_roi

        def _current_layer(self) -> str:
            return self.layer_combo.currentData() or "upper"

        def _current_mode(self) -> str:
            text = self.mode_combo.currentText()
            return "Dual Image" if text == "双图模式" else "Single Image"

        def _is_auto_workflow(self) -> bool:
            return self._combo_value(self.workflow_combo) == "Auto"

        def _set_mode_ui(self, mode: str):
            self.mode_combo.setCurrentText("双图模式" if mode == "Dual Image" else "单图模式")

        def _current_mark_id(self) -> str:
            return self.mark_combo.currentText() or "Mark1"

        def _ensure_mark_runtime(self, mark_id: str):
            self.mark_images.setdefault(mark_id, {"upper": None, "lower": None})
            self.mark_image_sources.setdefault(mark_id, {"upper": "none", "lower": "none"})
            self.auto_detections_by_mark.setdefault(mark_id, {})
            self.auto_candidates_by_mark.setdefault(mark_id, {})
            self.auto_selections.setdefault(mark_id, {"reference_label": "", "target_label": ""})

        def _set_image_for_layer(self, mark_id: str, layer: str, image: Optional[ImageData], source: str):
            self._ensure_mark_runtime(mark_id)
            self.mark_images[mark_id][layer] = image
            self.mark_image_sources[mark_id][layer] = source if image is not None else "none"

        def _image_source(self, mark_id: str, layer: str) -> str:
            self._ensure_mark_runtime(mark_id)
            return self.mark_image_sources.get(mark_id, {}).get(layer, "none")

        def _active_image_for_layer(self, mark_id: str, layer: str) -> Optional[ImageData]:
            self._ensure_mark_runtime(mark_id)
            image = self.mark_images[mark_id][layer]
            if image is None:
                return None
            if not self._is_batch_mode() and self._image_source(mark_id, layer) == "batch_preview":
                return None
            return image

        def _mark_images_snapshot_for_current_run(self) -> dict:
            snapshot = {}
            for mark_id in ("Mark1", "Mark2"):
                snapshot[mark_id] = {
                    layer: self._active_image_for_layer(mark_id, layer)
                    for layer in ("upper", "lower")
                }
            return snapshot

        def _switch_to_single_measurement_after_top_import(self):
            if hasattr(self, "measurement_run_mode_combo"):
                self._set_combo_value(self.measurement_run_mode_combo, "Single")
            self.batch_overlays = {"Mark1": [], "Mark2": []}
            self.batch_run_records = {"Mark1": [], "Mark2": []}

        def _current_auto_detections(self):
            mark_id = self._current_mark_id()
            self._ensure_mark_runtime(mark_id)
            return self.auto_detections_by_mark[mark_id]

        def _sync_current_mark_images(self):
            mark_id = self._current_mark_id()
            self._ensure_mark_runtime(mark_id)
            self.upper_image = self._active_image_for_layer(mark_id, "upper")
            self.lower_image = self._active_image_for_layer(mark_id, "lower")
            self.upper_canvas.set_image(self.upper_image)
            self.lower_canvas.set_image(self.lower_image)

        def _invalidate_image_dependent_results(self, mark_id: str, layer: str):
            if self._current_mode() == "Single Image":
                self.detections.pop(mark_id, None)
            elif mark_id in self.detections:
                self.detections[mark_id].pop(layer, None)
                if not self.detections[mark_id]:
                    self.detections.pop(mark_id, None)
            self.overlays.pop(mark_id, None)
            self.auto_detections_by_mark[mark_id] = {}
            self.auto_candidates_by_mark[mark_id] = {}
            self.auto_overlays.pop(mark_id, None)
            self.auto_selections[mark_id] = {"reference_label": "", "target_label": ""}

        def _combo_value(self, combo: QComboBox) -> str:
            return combo.currentData() or combo.currentText()

        def _set_combo_value(self, combo: QComboBox, value: str):
            for i in range(combo.count()):
                if combo.itemData(i) == value or combo.itemText(i) == value:
                    combo.setCurrentIndex(i)
                    return
            combo.setCurrentText(value)

        def _set_quality_threshold_controls(self):
            controls = (
                (self.conf_min_spin, self.config.confidence_min),
                (self.production_coverage_spin, self.config.production_min_coverage),
                (self.production_reject_spin, self.config.production_max_rejected_ratio),
                (self.production_residual_spin, self.config.production_max_residual_um),
                (self.production_deviation_spin, self.config.production_max_radial_deviation_um),
            )
            self._updating_quality_controls = True
            try:
                for control, value in controls:
                    control.blockSignals(True)
                    control.setValue(value)
                    control.blockSignals(False)
            finally:
                self._updating_quality_controls = False

        def _sync_quality_config_from_controls(self):
            self.config.quality_profile = self._combo_value(self.quality_profile_combo)
            self.config.confidence_min = self.conf_min_spin.value()
            self.config.production_min_coverage = self.production_coverage_spin.value()
            self.config.production_max_rejected_ratio = self.production_reject_spin.value()
            self.config.production_max_residual_um = self.production_residual_spin.value()
            self.config.production_max_radial_deviation_um = self.production_deviation_spin.value()

        def _refresh_quality_profile_hint(self):
            if not hasattr(self, "quality_profile_hint"):
                return
            profile = quality_profile_display(self.config)
            modified = quality_profile_is_modified(self.config)
            self.quality_profile_hint.setText(
                f"当前：{profile}。置信度≥{self.config.confidence_min:.2f}，"
                f"覆盖率≥{self.config.production_min_coverage:.0%}，"
                f"异常点≤{self.config.production_max_rejected_ratio:.0%}，"
                f"残差≤{self.config.production_max_residual_um:.3f} μm，"
                f"最大轮廓偏差≤{self.config.production_max_radial_deviation_um:.3f} μm。"
                + (" 详细参数已偏离该预设。" if modified else "")
            )
            self.quality_profile_hint.setToolTip(
                "宽容模式只放宽结果是否可用；识别明细仍会显示实际质量为优秀、合格、较差或无效。"
            )

        def _quality_settings_changed(self, message: str):
            for mark_map in self.detections.values():
                for detection in mark_map.values():
                    annotate_detection_quality(detection, self.config)
            for detected_by_label in self.auto_detections_by_mark.values():
                for layer_map in detected_by_label.values():
                    for detection in layer_map.values():
                        annotate_detection_quality(detection, self.config)
            self.overlays = {}
            self.auto_overlays = {}
            self.batch_overlays = {"Mark1": [], "Mark2": []}
            self.batch_run_records = {"Mark1": [], "Mark2": []}
            self._refresh_quality_profile_hint()
            self._refresh_auto_selection_combos()
            self._refresh_all_widgets()
            self._append_log(message + "，请重新计算对位偏差。")

        def on_quality_profile_changed(self):
            if self._updating_quality_controls:
                return
            profile = self._combo_value(self.quality_profile_combo)
            apply_quality_profile(self.config, profile)
            self._set_quality_threshold_controls()
            self._quality_settings_changed(f"识别质量门槛已切换为{QUALITY_PROFILE_LABELS[profile]}")

        def on_quality_threshold_edited(self):
            if self._updating_quality_controls:
                return
            self._sync_quality_config_from_controls()
            self._quality_settings_changed("识别质量详细参数已调整")

        def _fit_mode_for_layer(self, layer: str) -> str:
            if layer == "upper":
                mode = self._combo_value(self.upper_fit_mode_combo) if hasattr(self, "upper_fit_mode_combo") else getattr(self.params, "upper_fitting_mode", self.params.fitting_mode)
            else:
                mode = self._combo_value(self.lower_fit_mode_combo) if hasattr(self, "lower_fit_mode_combo") else getattr(self.params, "lower_fitting_mode", self.params.fitting_mode)
            if mode == "Auto":
                mode = self._combo_value(self.fit_mode_combo) if hasattr(self, "fit_mode_combo") else self.params.fitting_mode
            return mode

        def _auto_ring_roi_type(self, layer: str) -> str:
            if hasattr(self, "roi_type_combo"):
                return self._combo_value(self.roi_type_combo)
            return "Annulus"

        def _coerce_roi_to_auto_ring(self, roi: Roi, layer: str) -> Roi:
            """Return the ROI saved for this layer without overwriting its type.

            Earlier versions forced every saved ROI to the currently selected ROI Type in
            the side panel. That made mixed-shape measurements fail: for example, when
            the lower layer used 卡尺圆, the upper square ROI was also coerced to
            Caliper Circle during one-click calculation, so the square mark was measured
            as a circle.

            ROI type is now treated as a per-ROI/per-layer property. The side-panel
            settings only update the active ROI when the user draws/applies ROI
            parameters; calculation must respect each ROI's own stored type.
            """
            if roi is None:
                return roi
            # Keep the ROI's own type and geometry. Only normalize missing caliper
            # parameters for legacy recipes that do not contain these fields.
            roi_type = getattr(roi, "roi_type", "Rectangle")
            if roi_type == "Caliper Circle":
                return replace(
                    roi,
                    caliper_count=int(getattr(roi, "caliper_count", 64) or 64),
                    caliper_width_px=float(getattr(roi, "caliper_width_px", 8.0) or 8.0),
                    search_direction=getattr(roi, "search_direction", "Inner to Outer") or "Inner to Outer",
                )
            return roi

        def on_active_roi_selection_changed(self, *args):
            if hasattr(self, "three_point_circle_btn") and self.three_point_circle_btn.isChecked():
                self.three_point_circle_btn.blockSignals(True)
                self.three_point_circle_btn.setChecked(False)
                self.three_point_circle_btn.blockSignals(False)
                self.upper_canvas.set_circle_pick_mode(False)
                self.lower_canvas.set_circle_pick_mode(False)
            self._sync_current_mark_images()
            if hasattr(self, "auto_reference_combo"):
                self._push_current_auto_match_rules()
                self._refresh_auto_selection_combos()
            layer = self._current_layer()
            roi = self._current_roi()
            if roi is not None and hasattr(self, "roi_type_combo"):
                # Show current ROI parameters without triggering recursive updates.
                self.roi_type_combo.blockSignals(True)
                self.center_x_spin.blockSignals(True)
                self.center_y_spin.blockSignals(True)
                self.inner_radius_spin.blockSignals(True)
                self.outer_radius_spin.blockSignals(True)
                self.caliper_count_spin.blockSignals(True)
                self.caliper_width_spin.blockSignals(True)
                self.search_direction_combo.blockSignals(True)
                self.target_edge_combo.blockSignals(True)
                self.diameter_mode_combo.blockSignals(True)
                self.inner_ratio_spin.blockSignals(True)
                self.roi_angle_spin.blockSignals(True)
                self._set_combo_value(self.roi_type_combo, getattr(roi, "roi_type", "Annulus"))
                cx, cy = roi.center()
                self.center_x_spin.setValue(cx)
                self.center_y_spin.setValue(cy)
                self.inner_radius_spin.setValue(roi.inner_radius())
                self.outer_radius_spin.setValue(roi.outer_radius())
                self.caliper_count_spin.setValue(int(getattr(roi, "caliper_count", 64)))
                self.caliper_width_spin.setValue(float(getattr(roi, "caliper_width_px", 8.0)))
                self._set_combo_value(self.search_direction_combo, getattr(roi, "search_direction", "Inner to Outer"))
                self._set_combo_value(self.target_edge_combo, getattr(roi, "target_edge", "All Edges"))
                self._set_combo_value(self.diameter_mode_combo, getattr(roi, "diameter_mode", "Average"))
                self.inner_ratio_spin.setValue(float(getattr(roi, "inner_ratio", 0.60)))
                self.roi_angle_spin.setValue(float(getattr(roi, "angle_deg", 0.0)))
                self.roi_type_combo.blockSignals(False)
                self.center_x_spin.blockSignals(False)
                self.center_y_spin.blockSignals(False)
                self.inner_radius_spin.blockSignals(False)
                self.outer_radius_spin.blockSignals(False)
                self.caliper_count_spin.blockSignals(False)
                self.caliper_width_spin.blockSignals(False)
                self.search_direction_combo.blockSignals(False)
                self.target_edge_combo.blockSignals(False)
                self.diameter_mode_combo.blockSignals(False)
                self.inner_ratio_spin.blockSignals(False)
                self.roi_angle_spin.blockSignals(False)
            self._refresh_all_widgets()

        def apply_roi_params_to_current(self):
            mark_id = self.mark_combo.currentText() or "Mark1"
            layer = self._current_layer()
            mark = self.marks.get(mark_id)
            if not mark:
                return
            roi = mark.upper_roi if layer == "upper" else mark.lower_roi
            if roi is None:
                return
            cx = self.center_x_spin.value()
            cy = self.center_y_spin.value()
            inner = max(0.0, self.inner_radius_spin.value())
            outer = max(inner + 0.1, self.outer_radius_spin.value())
            roi.x = cx - outer
            roi.y = cy - outer
            roi.w = outer * 2.0
            roi.h = outer * 2.0
            roi.roi_type = self._auto_ring_roi_type(layer)
            roi.inner_ratio = float(np.clip(inner / max(outer, 1e-9), 0.0, 0.98))
            roi.target_edge = self._combo_value(self.target_edge_combo)
            roi.angle_deg = self.roi_angle_spin.value()
            roi.caliper_count = self.caliper_count_spin.value()
            roi.caliper_width_px = self.caliper_width_spin.value()
            roi.search_direction = self._combo_value(self.search_direction_combo)
            roi.diameter_mode = self._combo_value(self.diameter_mode_combo)
            self.roi_sources.setdefault(mark_id, {})[layer] = "manual"
            self._recipe_roi_confirmation_signature = None
            if mark_id in self.detections and layer in self.detections[mark_id]:
                del self.detections[mark_id][layer]
            if mark_id in self.overlays:
                del self.overlays[mark_id]
            # Reflect the just-drawn ROI parameters in the side panel.
            if mark_id == (self.mark_combo.currentText() or "Mark1") and layer == self._current_layer():
                self._set_combo_value(self.roi_type_combo, getattr(roi, "roi_type", "Annulus"))
                cx, cy = roi.center()
                self.center_x_spin.setValue(cx)
                self.center_y_spin.setValue(cy)
                self.inner_radius_spin.setValue(roi.inner_radius())
                self.outer_radius_spin.setValue(roi.outer_radius())
                self.caliper_count_spin.setValue(int(getattr(roi, "caliper_count", 64)))
                self.caliper_width_spin.setValue(float(getattr(roi, "caliper_width_px", 8.0)))
                self._set_combo_value(self.search_direction_combo, getattr(roi, "search_direction", "Inner to Outer"))
                self._set_combo_value(self.target_edge_combo, getattr(roi, "target_edge", "All Edges"))
                self._set_combo_value(self.diameter_mode_combo, getattr(roi, "diameter_mode", "Average"))
                self.inner_ratio_spin.setValue(float(getattr(roi, "inner_ratio", 0.60)))
                self.roi_angle_spin.setValue(float(getattr(roi, "angle_deg", 0.0)))
            self._refresh_all_widgets()

        def _refresh_all_widgets(self, *args):
            current_mark = self.mark_combo.currentText() or "Mark1"
            current_layer = self._current_layer()
            is_dual = self._current_mode() == "Dual Image"
            self.import_upper_btn.setText("导入上层/单图")
            self.import_lower_btn.setText("导入下层图像")
            self.upper_canvas.title = "上层图像" if is_dual else "单图图像"
            self.lower_canvas.title = "下层图像"
            if hasattr(self, "upper_image_card"):
                self.upper_image_card.title_label.setText(self.upper_canvas.title)
            if hasattr(self, "lower_image_card"):
                self.lower_image_card.title_label.setText(self.lower_canvas.title)
            if self.upper_canvas.image is None:
                self.upper_canvas.setText("等待导入图像")
            if self.lower_canvas.image is None:
                self.lower_canvas.setText("等待导入图像")
            self.upper_canvas.fixed_layer = None if not is_dual else "upper"
            upper_layer = "upper" if is_dual else current_layer
            lower_layer = "lower"
            upper_roi_type = self._auto_ring_roi_type(upper_layer) if hasattr(self, "roi_type_combo") else "Annulus"
            lower_roi_type = self._auto_ring_roi_type(lower_layer) if hasattr(self, "roi_type_combo") else "Annulus"
            roi_inner_ratio = self.inner_ratio_spin.value() if hasattr(self, "inner_ratio_spin") else 0.60
            roi_target_edge = self._combo_value(self.target_edge_combo) if hasattr(self, "target_edge_combo") else "All Edges"
            roi_angle_deg = self.roi_angle_spin.value() if hasattr(self, "roi_angle_spin") else 0.0
            roi = self._current_roi()
            if roi is not None:
                roi_ring_half_width_px = max(1.0, 0.5 * (roi.outer_radius() - roi.inner_radius()))
            else:
                roi_ring_half_width_px = max(1.0, 0.5 * (self.outer_radius_spin.value() - self.inner_radius_spin.value()))
            roi_caliper_count = self.caliper_count_spin.value() if hasattr(self, "caliper_count_spin") else 64
            roi_caliper_width_px = self.caliper_width_spin.value() if hasattr(self, "caliper_width_spin") else 8.0
            roi_search_direction = self._combo_value(self.search_direction_combo) if hasattr(self, "search_direction_combo") else "Inner to Outer"
            roi_diameter_mode = self._combo_value(self.diameter_mode_combo) if hasattr(self, "diameter_mode_combo") else "Average"
            show_auto = self._is_auto_workflow()
            if hasattr(self, "roi_source_label"):
                self.roi_source_label.setText(self._roi_source_text(self._roi_source(current_mark, current_layer)))
            if hasattr(self, "workflow_explanation_label"):
                self.workflow_explanation_label.setText(
                    "全图自动识别：本次计算不会读取任何 ROI。"
                    if show_auto
                    else "手动 ROI 测量：使用各 Mark、各层当前显示的 ROI；配方 ROI 会在计算前确认。"
                )
            current_auto_detections = self._current_auto_detections()
            is_validated_recipe = self._combo_value(self.recipe_status_combo) == "Validated" if hasattr(self, "recipe_status_combo") else False
            if hasattr(self, "production_status_label"):
                self.production_status_label.setText(
                    "正式测量 / 已验证配方" if is_validated_recipe else "试测 / 未验证配方（不作正式判定）"
                )
            manual_labels = self._manual_detection_labels()
            reference_label = self.auto_reference_combo.currentData() or "" if hasattr(self, "auto_reference_combo") else ""
            target_label = self.auto_target_combo.currentData() or "" if hasattr(self, "auto_target_combo") else ""
            self.upper_canvas.set_context(
                current_mark,
                current_layer,
                self.marks,
                self.detections,
                upper_roi_type,
                roi_inner_ratio,
                roi_target_edge,
                roi_angle_deg,
                roi_ring_half_width_px,
                roi_caliper_count,
                roi_caliper_width_px,
                roi_search_direction,
                roi_diameter_mode,
                current_auto_detections,
                show_auto,
                manual_labels,
                reference_label,
                target_label,
                self.config.pixel_size_x_um,
                self.config.pixel_size_y_um,
                self.diagnostic_check.isChecked() if hasattr(self, "diagnostic_check") else False,
            )
            self.lower_canvas.set_context(
                current_mark,
                current_layer,
                self.marks,
                self.detections,
                lower_roi_type,
                roi_inner_ratio,
                roi_target_edge,
                roi_angle_deg,
                roi_ring_half_width_px,
                roi_caliper_count,
                roi_caliper_width_px,
                roi_search_direction,
                roi_diameter_mode,
                current_auto_detections,
                show_auto,
                manual_labels,
                reference_label,
                target_label,
                self.config.pixel_size_x_um,
                self.config.pixel_size_y_um,
                self.diagnostic_check.isChecked() if hasattr(self, "diagnostic_check") else False,
            )
            self.lower_canvas.setVisible(is_dual)
            if hasattr(self, "lower_image_card"):
                self.lower_image_card.setVisible(is_dual)
            self.import_lower_btn.setEnabled(is_dual)
            self.auto_detect_btn.setEnabled(show_auto)
            # 基准/待测轮廓选择在自动识别和手动 ROI 两种工作方式下都需要可用。
            self.auto_reference_combo.setEnabled(True)
            self.auto_target_combo.setEnabled(True)
            auto_reference = self.auto_reference_combo.currentData()
            auto_target = self.auto_target_combo.currentData()
            self.auto_calculate_btn.setEnabled(
                bool(auto_reference) and bool(auto_target) and auto_reference != auto_target
            )
            self.analyze_roi_btn.setEnabled(not show_auto)
            self.analyze_current_btn.setEnabled(not show_auto)
            self.analyze_all_btn.setEnabled(True)
            self.three_point_circle_btn.setEnabled(not show_auto)
            self.apply_roi_params_btn.setEnabled(not show_auto)
            self.clear_current_roi_btn.setEnabled(not show_auto)
            self._refresh_mark_combo()
            if hasattr(self, "current_recipe_label"):
                recipe_display = self.loaded_recipe_display_name or self.recipe_name_edit.text().strip() or "未加载"
                self.current_recipe_label.setText(f"当前配方：{recipe_display}")
                self.current_recipe_label.setToolTip(f"当前配方：{recipe_display}")
            if hasattr(self, "load_recipe_btn"):
                recipe_display = self.loaded_recipe_display_name or self.recipe_name_edit.text().strip() or "未加载"
                full_text = f"当前配方：{recipe_display}  ▾"
                self.load_recipe_btn.setText(
                    self.load_recipe_btn.fontMetrics().elidedText(full_text, Qt.ElideMiddle, 290)
                )
                self.load_recipe_btn.setToolTip(
                    f"当前配方：{recipe_display}\n点击搜索、切换或从文件导入配方。"
                )
            if hasattr(self, "workflow_recipe_label"):
                recipe_display = self.loaded_recipe_display_name or self.recipe_name_edit.text().strip() or "未加载"
                self.workflow_recipe_label.setText(f"当前配方：{recipe_display}")
            if hasattr(self, "image_status_label"):
                if self.upper_image is None:
                    self.image_status_label.setText("等待导入图像")
                elif is_dual and self.lower_image is None:
                    self.image_status_label.setText("等待导入下层图像")
                elif (self.auto_overlays if show_auto else self.overlays):
                    self.image_status_label.setText("离线分析完成")
                else:
                    self.image_status_label.setText("图像已加载，可分析 ROI 区域或计算对位偏差")
            if hasattr(self, "upper_file_label"):
                upper_img = self._image_for_layer("upper", current_mark)
                lower_img = self._image_for_layer("lower", current_mark)
                self.upper_file_label.setText(Path(upper_img.path).name if upper_img and upper_img.path else "未导入")
                self.lower_file_label.setText(Path(lower_img.path).name if lower_img and lower_img.path else "未导入")
                if hasattr(self, "image_mode_tip_label"):
                    self.image_mode_tip_label.setText(self.mode_combo.currentText())
            self._refresh_tables()
            self._refresh_batch_image_table()
            self._refresh_repeatability_table()
            if hasattr(self, "_refresh_summary_cards"):
                self._refresh_summary_cards()
            if hasattr(self, "_refresh_step_status"):
                self._refresh_step_status(current_mark, show_auto)
            if hasattr(self, "_refresh_algorithm_path_panel"):
                self._refresh_algorithm_path_panel(current_mark, show_auto)
            self._update_toolbar_density()
            self._apply_operation_mode()

        def _refresh_mark_combo(self):
            self.marks = {
                mark_id: self.marks.get(mark_id, MarkRecipe(mark_id))
                for mark_id in ("Mark1", "Mark2")
            }
            current = self.mark_combo.currentText()
            self.mark_combo.blockSignals(True)
            self.mark_combo.clear()
            self.mark_combo.addItems(["Mark1", "Mark2"])
            if current in self.marks:
                self.mark_combo.setCurrentText(current)
            elif self.marks:
                self.mark_combo.setCurrentText(next(iter(self.marks)))
            self.mark_combo.blockSignals(False)

        def _mark_number(self, mark_id: str) -> str:
            digits = "".join(ch for ch in mark_id if ch.isdigit())
            return digits or mark_id

        @staticmethod
        def _alpha_label(index: int) -> str:
            label = ""
            value = index
            while True:
                value, remainder = divmod(value, 26)
                label = chr(ord("a") + remainder) + label
                if value == 0:
                    return label
                value -= 1

        def _manual_detection_labels(self):
            numbered = []
            for mark_id, layer_map in self.detections.items():
                for layer, detection in layer_map.items():
                    numbered.append((detection.diameter_px, mark_id, layer))
            numbered.sort(key=lambda item: (-item[0], item[1], item[2]))
            return {(mark_id, layer): self._alpha_label(index) for index, (_, mark_id, layer) in enumerate(numbered)}

        def _display_detections(self):
            if not self._is_auto_workflow():
                return self.detections
            combined = {}
            for mark_id, detected in self.auto_detections_by_mark.items():
                for label, layer_map in detected.items():
                    combined[f"{mark_id}-{label}"] = layer_map
            return combined

        def _display_overlays(self):
            return self.auto_overlays if self._is_auto_workflow() else self.overlays

        def _find_auto_detection(self, mark_id: str, label: str) -> Optional[DetectionResult]:
            layer_map = self.auto_detections_by_mark.get(mark_id, {}).get(label, {})
            return next(iter(layer_map.values()), None)

        def _build_summary_rows(self):
            overlay_map = self.auto_overlays if self._is_auto_workflow() else self.overlays
            is_trial = self._is_auto_workflow() and self.config.recipe_validation_status != "Validated"
            return build_summary_rows(overlay_map, self.config, is_trial=is_trial)

        def _set_result_card(self, value_label: QLabel, unit_label: QLabel, value: str, unit: str, color: str = "#1D1D1F"):
            value_label.setText(value)
            value_label.setProperty("resultColor", color)
            value_label.setStyleSheet(f"color: {color};")
            unit_label.setText(unit)
            unit_label.setToolTip(unit)

        def _refresh_summary_cards(self):
            rows = self._build_summary_rows()
            first = next((row for row in rows if row.get("项目") in {"Mark1", "Mark2"}), None)
            if first:
                dx_key = next((key for key in first if key.startswith("Dx")), "")
                dy_key = next((key for key in first if key.startswith("Dy")), "")
                dxy_key = next((key for key in first if key.startswith("Dxy")), "")
                dx = float(first.get(dx_key, 0.0))
                dy = float(first.get(dy_key, 0.0))
                dxy = float(first.get(dxy_key, 0.0))
                verdict = first.get("判定", "--")
                if verdict == "通过":
                    color = "#34C759"
                elif verdict in {"超限", "不通过", "异常"}:
                    color = "#FF3B30"
                else:
                    color = "#FFCC00"
                self._set_result_card(self.dx_value_label, self.dx_unit_label, f"{dx:+.3f}", "μm", "#007AFF")
                self._set_result_card(self.dy_value_label, self.dy_unit_label, f"{dy:+.3f}", "μm", "#FF9500")
                self._set_result_card(self.r_value_label, self.r_unit_label, f"{dxy:.3f}", "μm")
                result_note = {
                    "通过": "符合规格",
                    "超限": "对位结果超出规格",
                    "不通过": "对位结果超出规格",
                    "无效": "识别质量不满足要求",
                    "异常": "计算流程异常",
                    "试测": "未验证配方",
                }.get(verdict, "离线分析状态")
                self._set_result_card(self.result_value_label, self.result_unit_label, verdict, result_note, color)
                self.result_unit_label.setToolTip(first.get("提示", "") or result_note)
                self._update_summary_typography()
                return
            self._set_result_card(self.dx_value_label, self.dx_unit_label, "--", "μm", "#007AFF")
            self._set_result_card(self.dy_value_label, self.dy_unit_label, "--", "μm", "#FF9500")
            self._set_result_card(self.r_value_label, self.r_unit_label, "--", "μm")
            self._set_result_card(self.result_value_label, self.result_unit_label, "待分析", "离线分析状态", "#6E6E73")
            self._update_summary_typography()

        def _refresh_step_status(self, current_mark: str, show_auto: bool):
            imported = self._image_for_layer("upper", current_mark) is not None
            if self._current_mode() == "Dual Image":
                imported = imported and self._image_for_layer("lower", current_mark) is not None
            mark = self.marks.get(current_mark)
            roi_ready = bool(mark and (mark.upper_roi is not None or mark.lower_roi is not None))
            result_ready = current_mark in (self.auto_overlays if show_auto else self.overlays)
            states = [
                ("完成", "信息可编辑"),
                ("完成" if imported else "当前", "图像已加载" if imported else "等待导入图像"),
                ("完成" if roi_ready or show_auto else ("当前" if imported else "待处理"), "ROI 已设置" if roi_ready else ("自动识别模式" if show_auto else "等待设置 ROI")),
                ("完成" if imported else "待处理", "参数已就绪" if imported else "导入图像后设置"),
                ("完成" if result_ready else "待处理", "可导出结果" if result_ready else "等待计算"),
            ]
            colors = {"待处理": "#A1A1A6", "当前": "#007AFF", "完成": "#34C759", "异常": "#FF3B30"}
            for idx, (row, dot, label, note, state_dot) in enumerate(getattr(self, "step_rows", [])):
                state, detail = states[idx]
                color = colors[state]
                dot.setStyleSheet(f"color: {color}; border: 1px solid {color}; border-radius: 13px; font-weight: 700; background: #FFFFFF;")
                label.setStyleSheet(f"font-weight: 600; color: {'#007AFF' if state == '当前' else '#1D1D1F'};")
                note.setText(detail)
                state_dot.setStyleSheet(f"color: {color};")
            if not imported:
                status_text, status_color = "等待导入图像", "#A1A1A6"
            elif result_ready:
                status_text, status_color = "离线分析完成", "#34C759"
            else:
                status_text, status_color = "图像已加载", "#34C759"
            if hasattr(self, "status_task_dot"):
                self.status_task_dot.setStyleSheet(f"color: {status_color};")
                self.status_task_label.setText(f"任务状态：{status_text}")
            if hasattr(self, "progress_stage_label") and not self._calculation_running:
                if result_ready:
                    self.progress_bar.setValue(100)
                    self.progress_stage_label.setText("当前阶段：离线分析完成")
                elif imported:
                    self.progress_bar.setValue(0)
                    self.progress_stage_label.setText("当前阶段：图像已加载，等待计算")
                else:
                    self.progress_bar.setValue(0)
                    self.progress_stage_label.setText("当前阶段：等待导入图像")
            if hasattr(self, "workflow_status_dot"):
                self.workflow_status_dot.setStyleSheet(f"color: {status_color};")
                self.workflow_status_label.setText(status_text)

        def _refresh_algorithm_path_panel(self, current_mark: str, show_auto: bool):
            if not hasattr(self, "algorithm_path_button"):
                return
            workflow = "Auto" if show_auto else "Manual"
            reference_label = self.auto_reference_combo.currentData() or "" if hasattr(self, "auto_reference_combo") else ""
            target_label = self.auto_target_combo.currentData() or "" if hasattr(self, "auto_target_combo") else ""
            if show_auto:
                reference = self._find_auto_detection(current_mark, reference_label) if reference_label else None
                target = self._find_auto_detection(current_mark, target_label) if target_label else None
            else:
                reference = self._find_manual_detection(current_mark, reference_label) if reference_label else None
                target = self._find_manual_detection(current_mark, target_label) if target_label else None

            if reference is None and target is None:
                self.algorithm_path_text = "暂无测量结果；分析 ROI 或自动识别后可查看实际算法路径。"
                self.algorithm_path_button.setToolTip(self.algorithm_path_text)
                if hasattr(self, "algorithm_path_summary_label"):
                    self.algorithm_path_summary_label.setText("算法路径：暂无测量结果")
                    self.algorithm_path_summary_label.setToolTip(self.algorithm_path_text)
                return
            parts = [f"当前 {current_mark}"]
            if reference is not None:
                parts.append(f"基准({reference_label})：{describe_algorithm_path(reference, workflow)}")
            if target is not None:
                parts.append(f"待测({target_label})：{describe_algorithm_path(target, workflow)}")
            self.algorithm_path_text = "；".join(parts)
            self.algorithm_path_button.setToolTip(self.algorithm_path_text)
            if hasattr(self, "algorithm_path_summary_label"):
                compact = self.algorithm_path_text.replace("当前 ", "").replace("：", " · ")
                if len(compact) > 38:
                    compact = compact[:37] + "…"
                self.algorithm_path_summary_label.setText(f"算法路径：{compact}")
                self.algorithm_path_summary_label.setToolTip(self.algorithm_path_text)

        def _refresh_tables(self):
            det_headers = [
                "标记", "层", "中心 X (μm)", "中心 Y (μm)",
                "尺寸/直径 (μm)", "参考残差 (μm)", "边缘点数", "置信度", "算法",
                "质量状态", "质量门槛", "实际质量", "质量详情", "覆盖率",
                "形状参数", "算法路径", "提示",
            ]
            det_rows = []
            display_detections = self._display_detections()
            manual_labels = self._manual_detection_labels()
            for mark_id, layer_map in display_detections.items():
                for layer, d in layer_map.items():
                    if d.fitting_mode == "Rectangle":
                        width_um, height_um = rotated_rect_size_um(
                            d.shape_params.get("width_px", 0),
                            d.shape_params.get("height_px", 0),
                            d.shape_params.get("angle_deg", 0),
                            self.config,
                        )
                        shape_txt = (
                            f"宽={width_um:.3f}μm, "
                            f"高={height_um:.3f}μm, "
                            f"角度={d.shape_params.get('angle_deg', 0):.3f}°"
                        )
                    elif d.fitting_mode == "Ellipse":
                        angle_deg = d.shape_params.get("angle_deg", 0)
                        major_um = d.shape_params.get("major_px", 0) * axis_scale_um_per_px(self.config, angle_deg)
                        minor_um = d.shape_params.get("minor_px", 0) * axis_scale_um_per_px(self.config, angle_deg + 90.0)
                        shape_txt = (
                            f"长轴={major_um:.3f}μm, "
                            f"短轴={minor_um:.3f}μm, "
                            f"角度={d.shape_params.get('angle_deg', 0):.3f}°"
                        )
                    elif d.fitting_mode == "Circle":
                        average = float(d.shape_params.get("average_diameter_um", d.diameter_um))
                        maximum = float(d.shape_params.get("maximum_diameter_um", average))
                        shape_txt = f"平均直径={average:.3f}μm, 最大直径={maximum:.3f}μm"
                    elif d.fitting_mode == "EdgeCenter":
                        shape_txt = (
                            f"边缘中心, 参考半径={d.diameter_um / 2.0:.3f}μm, "
                            f"宽={d.shape_params.get('width_px', 0) * self.config.pixel_size_x_um:.3f}μm, "
                            f"高={d.shape_params.get('height_px', 0) * self.config.pixel_size_y_um:.3f}μm"
                        )
                    elif d.fitting_mode == "CaliperCircle":
                        average = float(d.shape_params.get("average_diameter_um", d.diameter_um))
                        maximum = float(d.shape_params.get("maximum_diameter_um", average))
                        definition = "最大直径" if d.shape_params.get("diameter_mode") == "Maximum" else "平均直径"
                        shape_txt = (
                            f"卡尺圆, 平均直径={average:.3f}μm, 最大直径={maximum:.3f}μm, "
                            f"采用={definition}, "
                            f"内点={d.shape_params.get('inlier_count', 0)}, "
                            f"剔除={d.shape_params.get('rejected_count', 0)}, "
                            f"卡尺={d.shape_params.get('caliper_count', 0)}"
                        )
                    elif d.fitting_mode == "ProductionRectangle":
                        width_um, height_um = rotated_rect_size_um(
                            d.shape_params.get("width_px", 0),
                            d.shape_params.get("height_px", 0),
                            d.shape_params.get("angle_deg", 0),
                            self.config,
                        )
                        shape_txt = (
                            f"方形精测, 宽={width_um:.3f}μm, "
                            f"高={height_um:.3f}μm, "
                            f"角度={d.shape_params.get('angle_deg', 0):.3f}°"
                        )
                    elif d.fitting_mode in {"AutoCircle", "AutoRectangle", "ProductionCircle"}:
                        shape_type = "方形精测" if d.fitting_mode == "ProductionRectangle" else ("圆形精测" if d.fitting_mode == "ProductionCircle" else ("方形轮廓" if d.fitting_mode == "AutoRectangle" else "圆形轮廓"))
                        if d.fitting_mode == "ProductionCircle":
                            average = float(d.shape_params.get("average_diameter_um", d.diameter_um))
                            maximum = float(d.shape_params.get("maximum_diameter_um", average))
                            shape_txt = f"{shape_type}, 平均直径={average:.3f}μm, 最大直径={maximum:.3f}μm"
                        else:
                            shape_txt = (
                                f"{shape_type}, 参考半径={d.diameter_um / 2.0:.3f}μm, "
                                f"宽={d.shape_params.get('width_px', 0) * self.config.pixel_size_x_um:.3f}μm, "
                                f"高={d.shape_params.get('height_px', 0) * self.config.pixel_size_y_um:.3f}μm"
                            )
                    else:
                        shape_txt = ""
                    mode_txt = {
                        "Rectangle": "矩形",
                        "Ellipse": "椭圆",
                        "Circle": "圆",
                        "EdgeCenter": "边缘中心",
                        "RegionCenter": "区域中心",
                        "CaliperCircle": "卡尺找圆",
                        "AutoCircle": "自动圆轮廓",
                        "AutoRectangle": "自动方形轮廓",
                        "ProductionCircle": "正式卡尺圆拟合",
                        "ProductionRectangle": "正式四边卡尺拟合",
                    }.get(d.fitting_mode, d.fitting_mode)
                    roi_type_txt = {
                        "Annulus": "圆环",
                        "Caliper Circle": "卡尺圆",
                        "Rectangular Ring": "矩形环",
                        "Circle": "圆",
                        "Rectangle": "矩形",
                        "Auto Full Image": "全图自动识别",
                        "Auto Caliper Circle": "自动卡尺圆",
                        "Auto Four-Side Caliper": "自动四边卡尺",
                    }.get(d.shape_params.get("roi_type", ""), d.shape_params.get("roi_type", ""))
                    edge_txt = {
                        "All Edges": "全部边缘",
                        "Near Inner Boundary": "靠近内环",
                        "Near Outer Boundary": "靠近外环",
                        "Strongest Edge": "最强边缘",
                    }.get(d.shape_params.get("roi_target_edge", ""), d.shape_params.get("roi_target_edge", ""))
                    roi_txt = f"ROI={roi_type_txt}, 边缘={edge_txt}"
                    display_mark_id = mark_id
                    if not self._is_auto_workflow() and (mark_id, layer) in manual_labels:
                        display_mark_id = f"{mark_id} [{manual_labels[(mark_id, layer)]}]"
                    det_rows.append([
                        display_mark_id, LAYER_LABELS.get(layer, layer),
                        f"{d.center_x_um:.3f}", f"{d.center_y_um:.3f}",
                        f"{d.diameter_um:.3f}", f"{d.residual_um:.3f}",
                        str(d.edge_point_count), f"{d.confidence:.3f}", mode_txt,
                        {"Valid": "有效", "Invalid": "无效"}.get(d.shape_params.get("quality_status", ""), ""),
                        d.shape_params.get("quality_profile_label", quality_profile_display(self.config)),
                        d.shape_params.get("quality_grade", "未评估"),
                        d.shape_params.get("quality_details", ""),
                        f"{d.shape_params.get('coverage', 0):.1%}" if "coverage" in d.shape_params else "",
                        shape_txt + "; " + roi_txt,
                        d.shape_params.get("algorithm_path", describe_algorithm_path(d, "Auto" if self._is_auto_workflow() else "Manual")),
                        d.warning,
                    ])
            self._fill_table(self.det_table, det_headers, det_rows)

            ov_headers = ["项目", "Dx/Dy/Dxy/Rz", "数值", "判定", "质量门槛", "实际质量", "质量详情", "提示"]
            ov_rows = []
            display_overlays = self._display_overlays()
            for row in self._build_summary_rows():
                project = row.get("项目", "")
                verdict = row.get("判定", "")
                note = row.get("提示", "")
                overlay = display_overlays.get(project)
                profile = overlay.quality_profile if overlay else (quality_profile_display(self.config) if project != "Rz" else "—")
                grade = overlay.quality_grade if overlay else ("未评估" if project != "Rz" else "—")
                quality_summary = overlay.quality_summary if overlay else ""
                for key, value in row.items():
                    if key in {"项目", "判定", "质量门槛", "实际质量", "质量详情", "提示", "公式", "L(μm)"}:
                        continue
                    ov_rows.append([
                        project,
                        key,
                        f"{value:.3f}" if isinstance(value, float) else value,
                        verdict,
                        profile,
                        grade,
                        quality_summary,
                        note,
                    ])
                if project == "Rz":
                    ov_rows[-1][7] = f"{row.get('公式', '')}；L={row.get('L(μm)', '')}；{note}".strip("；")
            self._fill_table(self.overlay_table, ov_headers, ov_rows)

        def _fill_table(self, table: QTableWidget, headers, rows):
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    item = QTableWidgetItem(str(val))
                    row_text = " ".join(str(x) for x in row)
                    row_values = {str(value).strip() for value in row}
                    hard_failure = bool(
                        row_values.intersection({"失败", "超限", "无效", "异常", "Fail", "Invalid", "Error"})
                    ) or any(
                        token in row_text
                        for token in ("识别失败", "计算异常", "低于宽容门槛", "超出配方范围")
                    )
                    if hard_failure:
                        item.setBackground(QColor(255, 199, 206))
                        item.setForeground(QColor(156, 0, 6))
                    elif "较差（仅宽容可用）" in row_text:
                        item.setBackground(QColor(255, 243, 205))
                        item.setForeground(QColor(133, 77, 14))
                    elif "优秀（满足超精确）" in row_text:
                        item.setBackground(QColor(226, 244, 232))
                        item.setForeground(QColor(25, 107, 58))
                    table.setItem(r, c, item)
            table.resizeColumnsToContents()

        def zoom_canvases(self, factor: float):
            self.upper_canvas.zoom_by(factor)
            if self.lower_canvas.isVisible():
                self.lower_canvas.zoom_by(factor)
            self._sync_zoom_level_display()

        def set_canvas_zoom_percent(self, text: str):
            if not text or not text.endswith("%"):
                return
            try:
                zoom = float(text[:-1]) / 100.0
            except ValueError:
                return
            for canvas in (self.upper_canvas, self.lower_canvas):
                canvas.user_zoom = float(np.clip(zoom, 0.05, 80.0))
                canvas.pan_x = 0.0
                canvas.pan_y = 0.0
                canvas.update()

        def reset_canvas_views(self):
            self.upper_canvas.reset_view(update=True)
            self.lower_canvas.reset_view(update=True)
            self._sync_zoom_level_display()

        def _sync_zoom_level_display(self):
            if not hasattr(self, "zoom_level_combo"):
                return
            zoom_text = f"{int(round(self.upper_canvas.user_zoom * 100.0))}%"
            self.zoom_level_combo.blockSignals(True)
            if self.zoom_level_combo.findText(zoom_text) < 0:
                self.zoom_level_combo.addItem(zoom_text)
            self.zoom_level_combo.setCurrentText(zoom_text)
            self.zoom_level_combo.blockSignals(False)
