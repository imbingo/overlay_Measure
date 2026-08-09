from __future__ import annotations

from copy import deepcopy
from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .geometry_engine import execute_geometry_program, flatten_detection_map
from .geometry_models import (
    CoordinateLabelDefinition,
    CoordinateSystemDefinition,
    GeometryFeatureDefinition,
    GeometryMeasurementDefinition,
    GeometryProgram,
    GeometryRunResult,
)
from .ui_components import CollapsibleSection


FEATURE_LABELS = {
    "point": "点",
    "line": "直线",
    "circle": "圆",
    "outer_circle_min": "最小外接圆",
    "outer_circle_robust": "稳健外轮廓圆",
    "intersection": "交点",
    "midpoint": "中点",
    "projection": "投影点",
}

MEASUREMENT_LABELS = {
    "point_distance": "点点距离",
    "center_distance": "圆心距",
    "point_line_distance": "点线距离",
    "line_angle": "直线角度",
    "two_line_angle": "两线夹角",
    "diameter": "直径",
}


class MainWindowGeometryMixin:
    def _initialize_geometry_state(self):
        self.geometry_program = GeometryProgram()
        self.geometry_result = GeometryRunResult()
        self.batch_geometry_results = []
        self._geometry_interaction: Optional[dict] = None
        self._geometry_sequence = 0

    def _build_geometry_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        feature_section = CollapsibleSection("几何工具", True)
        feature_group = QGroupBox("手工几何工具（不进行亚像素识别）")
        feature_grid = QGridLayout(feature_group)
        feature_specs = [
            ("点", "point"), ("直线", "line"), ("圆", "circle"),
            ("交点", "intersection"), ("中点", "midpoint"), ("投影点", "projection"),
        ]
        self.geometry_feature_buttons = {}
        for index, (text, action) in enumerate(feature_specs):
            button = QPushButton(text)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=action: self.start_geometry_feature(value))
            feature_grid.addWidget(button, index // 2, index % 2)
            self.geometry_feature_buttons[action] = button
        feature_section.add_widget(feature_group)
        layout.addWidget(feature_section)

        measurement_section = CollapsibleSection("测量工具", True)
        measurement_group = QGroupBox("测量工具")
        measurement_layout = QVBoxLayout(measurement_group)
        coordinate_row = QHBoxLayout()
        self.create_coordinate_btn = QPushButton("建立坐标系")
        self.coordinate_label_btn = QPushButton("坐标标注")
        coordinate_row.addWidget(self.create_coordinate_btn)
        coordinate_row.addWidget(self.coordinate_label_btn)
        measurement_layout.addLayout(coordinate_row)

        grid = QGridLayout()
        measurement_specs = [
            ("点点距离", "point_distance"), ("圆心距", "center_distance"),
            ("点线距离", "point_line_distance"), ("直线角度", "line_angle"),
            ("两线夹角", "two_line_angle"), ("直径", "diameter"),
        ]
        self.geometry_measurement_buttons = {}
        for index, (text, action) in enumerate(measurement_specs):
            button = QPushButton(text)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=action: self.start_geometry_measurement(value))
            grid.addWidget(button, index // 2, index % 2)
            self.geometry_measurement_buttons[action] = button
        measurement_layout.addLayout(grid)

        edit_row = QHBoxLayout()
        self.geometry_cancel_btn = QPushButton("取消当前操作")
        self.geometry_continuous_check = QCheckBox("连续测量")
        edit_row.addWidget(self.geometry_cancel_btn)
        edit_row.addWidget(self.geometry_continuous_check)
        measurement_layout.addLayout(edit_row)
        measurement_section.add_widget(measurement_group)
        layout.addWidget(measurement_section)

        self.geometry_active_tool_label = QLabel("当前工具：未选择")
        self.geometry_active_tool_label.setStyleSheet("font-weight: 700; color: #6E6E73;")
        layout.addWidget(self.geometry_active_tool_label)
        self.geometry_hint_label = QLabel("ROI 识别结果可直接用于测量；几何工具用于手工点、线、圆及派生点。")
        self.geometry_hint_label.setWordWrap(True)
        self.geometry_hint_label.setObjectName("statusCaption")
        layout.addWidget(self.geometry_hint_label)
        layout.addStretch(1)

        self.create_coordinate_btn.clicked.connect(self.start_coordinate_system)
        self.coordinate_label_btn.clicked.connect(self.start_coordinate_label)
        self.geometry_cancel_btn.clicked.connect(self.cancel_geometry_interaction)
        return page

    def _next_geometry_id(self, prefix: str) -> str:
        self._geometry_sequence += 1
        return f"{prefix}{self._geometry_sequence}"

    def _geometry_layer(self) -> str:
        return self._current_layer()

    def _set_geometry_interaction(self, action: str, count: int, prompt: str, **extra):
        self._geometry_interaction = {
            "action": action,
            "required": int(count),
            "clicks": [],
            "layer": self._geometry_layer(),
            "prompt": prompt,
            **extra,
        }
        self.geometry_hint_label.setText(prompt)
        label = action.split(":", 1)[-1]
        display = FEATURE_LABELS.get(label, MEASUREMENT_LABELS.get(label, "坐标工具"))
        self.geometry_active_tool_label.setText(f"当前工具：{display}（已选择 0/{int(count)}）")
        self.geometry_active_tool_label.setStyleSheet("font-weight: 700; color: #007AFF;")
        for key, button in {**self.geometry_feature_buttons, **self.geometry_measurement_buttons}.items():
            button.blockSignals(True)
            button.setChecked(key == label)
            button.blockSignals(False)
        self.progress_stage_label.setText(f"当前阶段：{prompt}")
        for canvas in (self.upper_canvas, self.lower_canvas):
            canvas.set_geometry_interaction_active(True)
        self._refresh_geometry_canvas_context()

    def cancel_geometry_interaction(self):
        self._geometry_interaction = None
        if hasattr(self, "geometry_hint_label"):
            self.geometry_hint_label.setText("当前操作已取消。选择工具后可重新建立要素或测量项目。")
        if hasattr(self, "geometry_active_tool_label"):
            self.geometry_active_tool_label.setText("当前工具：未选择")
            self.geometry_active_tool_label.setStyleSheet("font-weight: 700; color: #6E6E73;")
        for button in [*getattr(self, "geometry_feature_buttons", {}).values(),
                       *getattr(self, "geometry_measurement_buttons", {}).values()]:
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)
        for canvas in (self.upper_canvas, self.lower_canvas):
            canvas.set_geometry_interaction_active(False)
        self._refresh_geometry_canvas_context()

    def start_geometry_feature(self, feature_type: str):
        requirements = {
            "point": (1, "在图像上点击点位置"),
            "line": (2, "依次点击直线上的两个点"),
            "circle": (3, "依次点击圆边界上的三个点"),
            "outer_circle_min": (1, "点击一个已识别轮廓，建立最小外接圆"),
            "outer_circle_robust": (1, "点击一个已识别轮廓，建立稳健外轮廓圆"),
            "intersection": (2, "依次点击两条已创建直线"),
            "midpoint": (2, "依次点击两个点或圆心要素"),
            "projection": (2, "先点击点要素，再点击直线要素"),
        }
        count, prompt = requirements[feature_type]
        self._set_geometry_interaction(f"feature:{feature_type}", count, prompt)

    def start_coordinate_system(self):
        labels = ["两圆心建轴", "两点建轴", "点原点 + 直线轴"]
        label, accepted = QInputDialog.getItem(self, "建立坐标系", "建立方式", labels, 0, False)
        if not accepted:
            return
        method = {labels[0]: "two_centers", labels[1]: "two_points", labels[2]: "point_line"}[label]
        prompt = {
            "two_centers": "依次点击原点圆和 +X 方向圆",
            "two_points": "依次点击原点和 +X 方向点",
            "point_line": "先点击原点，再点击定义 +X 方向的直线",
        }[method]
        self._set_geometry_interaction("coordinate", 2, prompt, method=method)

    def start_coordinate_label(self):
        valid_coordinates = [item for item in self.geometry_program.coordinate_systems if item.enabled]
        if not valid_coordinates:
            QMessageBox.warning(self, "坐标标注", "请先建立坐标系。")
            return
        names = [item.name for item in valid_coordinates]
        selected, accepted = QInputDialog.getItem(self, "坐标标注", "选择坐标系", names, 0, False)
        if not accepted:
            return
        coordinate_id = valid_coordinates[names.index(selected)].coordinate_id
        self._set_geometry_interaction("coordinate_label", 2, "先点击圆/点要素，再点击标注放置位置", coordinate_id=coordinate_id)

    def start_geometry_measurement(self, measurement_type: str):
        requirements = {
            "point_distance": (2, "依次点击两个点或中心要素"),
            "center_distance": (2, "依次点击两个圆要素"),
            "point_line_distance": (2, "先点击点/圆心，再点击直线"),
            "line_angle": (1, "点击一条直线"),
            "two_line_angle": (2, "依次点击两条直线"),
            "diameter": (1, "点击一个圆要素"),
        }
        count, prompt = requirements[measurement_type]
        self._set_geometry_interaction(f"measurement:{measurement_type}", count, prompt)

    def _ensure_detection_feature(self, detection_key: str, layer: str) -> str:
        for item in self.geometry_program.features:
            if item.source == "detection" and item.detection_key == detection_key:
                return item.feature_id
        detection = self._current_geometry_detections().get(detection_key)
        mode = getattr(detection, "fitting_mode", "")
        if mode == "Line":
            feature_type = "line"
        elif mode in {"Rectangle", "ProductionRectangle"}:
            feature_type = "rectangle"
        elif mode == "Ellipse":
            feature_type = "ellipse"
        elif mode in {"RegionCenter", "EdgeCenter"}:
            feature_type = "region"
        else:
            feature_type = "circle"
        feature_id = self._next_geometry_id("F")
        self.geometry_program.features.append(
            GeometryFeatureDefinition(feature_id, feature_id, layer, feature_type, "detection", detection_key=detection_key)
        )
        return feature_id

    def _click_feature_id(self, click: dict, layer: str) -> str:
        feature_id = str(click.get("feature_id", ""))
        if feature_id:
            return feature_id
        detection_key = str(click.get("detection_key", ""))
        if detection_key:
            return self._ensure_detection_feature(detection_key, layer)
        feature_id = self._next_geometry_id("P")
        self.geometry_program.features.append(
            GeometryFeatureDefinition(feature_id, feature_id, layer, "point", points_px=[click["point_px"]])
        )
        return feature_id

    def _on_geometry_canvas_clicked(self, layer: str, click: dict):
        interaction = self._geometry_interaction
        if not interaction:
            return
        if layer != interaction["layer"]:
            self.geometry_hint_label.setText("请在开始操作时选择的同一图层完成全部点击。")
            return
        interaction["clicks"].append(dict(click))
        self._refresh_geometry_canvas_context()
        current = len(interaction["clicks"])
        required = interaction["required"]
        if current < required:
            self.geometry_hint_label.setText(f"已选择 {current}/{required}，请继续点击。")
            self.geometry_active_tool_label.setText(
                self.geometry_active_tool_label.text().split("（", 1)[0] + f"（已选择 {current}/{required}）"
            )
            return
        action = interaction["action"]
        required = interaction["required"]
        prompt = interaction.get("prompt", self.geometry_hint_label.text())
        extra = {key: value for key, value in interaction.items() if key not in {"action", "required", "clicks", "layer", "prompt"}}
        try:
            self._finish_geometry_interaction(interaction)
            self._refresh_geometry_results()
        except Exception as exc:
            QMessageBox.warning(self, "轮廓测量", str(exc))
        finally:
            if getattr(self, "geometry_continuous_check", None) is not None and self.geometry_continuous_check.isChecked():
                self._set_geometry_interaction(action, required, prompt, **extra)
            else:
                self.cancel_geometry_interaction()

    def handle_geometry_command(self, command: str):
        if command == "clear_all":
            self.clear_all_contours()
            return
        if command.startswith("delete:"):
            self.delete_geometry_item(command.split(":", 1)[1])
            return
        if command == "cancel":
            self.cancel_geometry_interaction()
            return
        if command == "undo" and self._geometry_interaction:
            clicks = self._geometry_interaction.get("clicks", [])
            if clicks:
                clicks.pop()
            current = len(clicks)
            required = self._geometry_interaction["required"]
            self.geometry_active_tool_label.setText(
                self.geometry_active_tool_label.text().split("（", 1)[0] + f"（已选择 {current}/{required}）"
            )
            self.geometry_hint_label.setText("已撤销上一个选点，请继续。")
            self._refresh_geometry_canvas_context()

    def delete_geometry_item(self, identifier: str):
        identifier = str(identifier or "")
        if not identifier:
            return
        self.geometry_program.features = [item for item in self.geometry_program.features if item.feature_id != identifier]
        self.geometry_program.measurements = [item for item in self.geometry_program.measurements if item.measurement_id != identifier]
        self.geometry_program.coordinate_labels = [item for item in self.geometry_program.coordinate_labels if item.label_id != identifier]
        self.geometry_program.coordinate_systems = [item for item in self.geometry_program.coordinate_systems if item.coordinate_id != identifier]
        self._refresh_geometry_results()

    def _finish_geometry_interaction(self, interaction: dict):
        action = interaction["action"]
        clicks = interaction["clicks"]
        layer = interaction["layer"]
        if action.startswith("feature:"):
            feature_type = action.split(":", 1)[1]
            feature_id = self._next_geometry_id("F")
            definition = GeometryFeatureDefinition(feature_id, feature_id, layer, feature_type)
            if feature_type in {"point", "line", "circle"}:
                definition.points_px = [item["point_px"] for item in clicks]
            elif feature_type in {"outer_circle_min", "outer_circle_robust"}:
                detection_key = clicks[0].get("detection_key", "")
                if not detection_key:
                    raise ValueError("请点击已识别的圆或轮廓。")
                definition.source = "detection"
                definition.detection_key = detection_key
            else:
                definition.reference_ids = [self._click_feature_id(item, layer) for item in clicks]
            self.geometry_program.features.append(definition)
            return

        if action == "coordinate":
            references = [self._click_feature_id(item, layer) for item in clicks]
            rotation, accepted = QInputDialog.getDouble(
                self, "坐标轴旋转", "附加旋转角度（°，逆时针为正）", 0.0, -180.0, 180.0, 3
            )
            if not accepted:
                rotation = 0.0
            coordinate_id = self._next_geometry_id("CS")
            self.geometry_program.coordinate_systems.append(
                CoordinateSystemDefinition(
                    coordinate_id, coordinate_id, layer, interaction["method"], references, rotation
                )
            )
            return

        if action == "coordinate_label":
            feature_id = self._click_feature_id(clicks[0], layer)
            anchor = self._feature_anchor_from_program(feature_id)
            placement = clicks[1]["point_px"]
            label_id = self._next_geometry_id("L")
            self.geometry_program.coordinate_labels.append(
                CoordinateLabelDefinition(
                    label_id, label_id, layer, feature_id, interaction["coordinate_id"],
                    (placement[0] - anchor[0], placement[1] - anchor[1]),
                )
            )
            return

        if action.startswith("measurement:"):
            measurement_type = action.split(":", 1)[1]
            references = [self._click_feature_id(item, layer) for item in clicks]
            measurement_id = self._next_geometry_id("M")
            self.geometry_program.measurements.append(
                GeometryMeasurementDefinition(
                    measurement_id, f"{MEASUREMENT_LABELS[measurement_type]} {measurement_id}",
                    layer, measurement_type, references,
                )
            )

    def _feature_anchor_from_program(self, feature_id: str):
        self._refresh_geometry_results()
        feature = self.geometry_result.features.get(feature_id)
        if feature is None or feature.center_px is None:
            raise ValueError("所选要素没有可用中心。")
        return feature.center_px

    def _current_geometry_detections(self):
        if not self._is_auto_workflow():
            flattened = {}
            for mark_id, roi_map in self._current_manual_detection_map().items():
                for roi_id, detection in roi_map.items():
                    flattened[f"{mark_id}/{roi_id}:{detection.layer}"] = detection
            return flattened
        flattened = {}
        for mark_id, detected_by_label in self.auto_detections_by_mark.items():
            for label, layer_map in detected_by_label.items():
                for layer, detection in layer_map.items():
                    flattened[f"{mark_id}/{label}:{layer}"] = detection
        return flattened

    def _refresh_geometry_results(self):
        if self._is_batch_mode() and self.batch_geometry_results:
            selected = self._batch_detail_last_single_index
            if isinstance(self._batch_detail_run_index, int):
                selected = self._batch_detail_run_index
            index = max(0, min(len(self.batch_geometry_results) - 1, int(selected) - 1))
            self.geometry_result = self.batch_geometry_results[index]
            self._refresh_geometry_canvas_context()
            if hasattr(self, "geometry_table"):
                self._refresh_geometry_table()
            return
        try:
            self.geometry_result = execute_geometry_program(
                self.geometry_program,
                self._current_geometry_detections(),
                self.config,
            )
        except Exception as exc:
            self.geometry_result = GeometryRunResult()
            self.runtime_logger.exception("Geometry program failed")
            if hasattr(self, "geometry_hint_label"):
                self.geometry_hint_label.setText(f"轮廓测量程序异常：{exc}")
        self._refresh_geometry_canvas_context()
        if hasattr(self, "geometry_table"):
            self._refresh_geometry_table()

    def _refresh_geometry_canvas_context(self):
        active = bool(self._geometry_interaction)
        for canvas in (self.upper_canvas, self.lower_canvas):
            canvas.set_geometry_context(self.geometry_program, self.geometry_result, active, self._geometry_interaction)

    def _refresh_geometry_table(self):
        headers = ["类型", "编号", "层", "数值", "单位", "状态", "质量", "算法路径", "提示"]
        rows = []
        for feature in self.geometry_result.features.values():
            value = ""
            unit = ""
            if feature.radius_px is not None:
                value = f"{2.0 * feature.radius_px * 0.5 * (self.config.pixel_size_x_um + self.config.pixel_size_y_um):.3f}"
                unit = "μm"
            rows.append([
                f"要素-{FEATURE_LABELS.get(feature.feature_type, feature.feature_type)}",
                feature.name, "上层" if feature.layer == "upper" else "下层", value, unit,
                "有效" if feature.status == "Valid" else "无效", feature.quality,
                feature.algorithm_path, feature.error,
            ])
        for measurement in self.geometry_result.measurements.values():
            rows.append([
                "测量", measurement.name, "上层" if measurement.layer == "upper" else "下层",
                "" if measurement.value is None else f"{measurement.value:.3f}", measurement.unit,
                "有效" if measurement.status == "Valid" else "无效", measurement.quality,
                measurement.algorithm_path, measurement.error,
            ])
        for label in self.geometry_result.coordinate_labels.values():
            value = "" if label.x_um is None else f"X={label.x_um:.3f}, Y={label.y_um:.3f}"
            rows.append([
                "坐标标注", label.name, "上层" if label.layer == "upper" else "下层",
                value, "μm", "有效" if label.status == "Valid" else "无效", "", "自定义坐标系", label.error,
            ])
        self._fill_table(self.geometry_table, headers, rows)

    def delete_selected_geometry_item(self):
        if not hasattr(self, "geometry_table") or self.geometry_table.currentRow() < 0:
            QMessageBox.information(self, "删除", "请先在“尺寸结果”表格中选择一行。")
            return
        identifier = self.geometry_table.item(self.geometry_table.currentRow(), 1)
        if identifier is None:
            return
        name = identifier.text()
        self.geometry_program.features = [item for item in self.geometry_program.features if item.name != name]
        self.geometry_program.measurements = [item for item in self.geometry_program.measurements if item.name != name]
        self.geometry_program.coordinate_labels = [item for item in self.geometry_program.coordinate_labels if item.name != name]
        self.geometry_program.coordinate_systems = [item for item in self.geometry_program.coordinate_systems if item.name != name]
        self._refresh_geometry_results()

    def clear_all_contours(self):
        answer = QMessageBox.question(
            self,
            "清除所有轮廓",
            "将清除全部识别轮廓、几何要素、测量项目和当前结果，但保留已导入图像与 ROI。是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        self.cancel_geometry_interaction()
        self.detections = {}
        self.roi_detections = {"Mark1": {}, "Mark2": {}}
        self.auto_detections_by_mark = {"Mark1": {}, "Mark2": {}}
        self.auto_candidates_by_mark = {"Mark1": {}, "Mark2": {}}
        self.overlays = {}
        self.auto_overlays = {}
        self.batch_overlays = {"Mark1": [], "Mark2": []}
        self.batch_run_records = {"Mark1": [], "Mark2": []}
        self.geometry_program = GeometryProgram()
        self.geometry_result = GeometryRunResult()
        self.batch_geometry_results = []
        self.auto_selections = {
            "Mark1": {"reference_label": "", "target_label": ""},
            "Mark2": {"reference_label": "", "target_label": ""},
        }
        for mark in self.marks.values():
            mark.reference_contour_id = ""
            mark.target_contour_id = ""
        for canvas in (self.upper_canvas, self.lower_canvas):
            canvas.clear_caliper_selection()
        self._refresh_auto_selection_combos()
        self._refresh_geometry_results()
        self._refresh_all_widgets()
        self._append_log("已清除所有识别轮廓、几何要素和测量结果；图像与 ROI 已保留。")

    def geometry_program_snapshot(self) -> GeometryProgram:
        return deepcopy(self.geometry_program)
