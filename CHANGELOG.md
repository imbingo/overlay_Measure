# Changelog

## V2.2.2

- Simplified manual ROI operation around the image canvas: dragging blank image space creates a new ROI, clicking an ROI selects it, and blank click or Esc clears selection.
- Moved ROI copy/delete and layer-level contour/ROI cleanup into the canvas context menu; removed duplicate add/copy/delete/source/apply/clear controls from the right panel.
- ROI and algorithm parameter edits now invalidate stale results immediately; the next analysis always uses the currently displayed parameters without a separate Apply step.
- Improved geometry interaction with selected-point progress, hover highlighting, Backspace undo, Esc cancel, three-point-circle preview, optional continuous measurement and on-canvas dimension labels.
- Moved geometry/measurement deletion to the image context menu and removed duplicate table-delete and global-clear buttons.
- Image source labels now include the parent folder and file name.
- Excel now exports full input-image measurement views for every run/layer, preserving aspect ratio and showing all ROI outlines plus green fitted contours instead of cropped Mark thumbnails.
- Added V2.2.2 ROI-state, source-display, annotated-export and geometry-interaction regression tests.

## V2.2.0

- Corrected minimum-enclosing-circle and robust-circle metrology to fit in calibrated physical coordinates, including non-square X/Y pixels; minimum-circle diameter is no longer confused with maximum Feret diameter.
- Added ROI-level failure records with stable ROI ID, layer, index, status and error; a bad ROI no longer removes successful contours, and Excel retains every failed ROI.
- Marked auto candidates whose precision refinement fails as diagnostic-only and excluded them from reference/target selection.
- Moved Auto Identify and Analyze ROI preview work to cancellable background threads with real progress and explicit failure feedback.
- Changed batch imports to lightweight path references loaded one image pair at a time, with large-count/data-size warnings.
- Added centralized stale-result invalidation for mode changes and locked both canvas and backend ROI edits in Production mode.
- Changed ROI parameter editing to an explicit Apply action, added context-sensitive controls, and added 20-step Engineering-mode ROI undo/redo.
- Added recovery job IDs and running/completed/archived history, table rebuild suppression, state-aware Run guidance, CSV export warnings, and a first-use default-password warning.
- Added V2.2 regression coverage for calibrated circles, ROI-level failures, production locks, stale-state invalidation, lazy batches and recovery lifecycle.

## V2.1.0

- Added unlimited manual ROIs per Mark/layer with stable IDs, numbered layer-local display labels, and add/copy/delete/switch controls.
- Migrated legacy `upper_roi/lower_roi` recipes to ROI lists while keeping compatibility properties and legacy fitting behavior.
- Changed manual analysis, background measurement, batch snapshots, geometry inputs, recognition details, and Excel exports to retain every ROI result.
- Kept reference/target contour selection as the only overlay pairing mechanism; invalidated selections are never silently rebound to another contour.
- Added canvas selection for ROI/fit contours, selected-ROI highlighting, and per-ROI result invalidation after edits.
- Added reference/target contour names and stable IDs to overlay summary exports while preserving ellipse roundness and quality fields per ROI.

## V2.0.0

- 产品名称升级为 **SOMA Vision Metrology**，加入 `See Once, Measure All` 与“视觉轮廓与对位量测平台”副标题；保留原 AppId、内部 EXE 名称和用户数据目录，支持从 V1.x 原位升级。
- 在 V1.9 单工作区中新增“轮廓测量”步骤，不拆分单图/双图和对位/尺寸界面；顶部“计算对位偏差”统一为“运行测量程序”，原“分析 ROI”继续保留。
- 新增点、直线、圆、最小外接圆、稳健外轮廓圆、交点、中点和投影点要素工具；已创建项目仅显示在画布与底部“尺寸结果”表，不占用右侧参数空间。
- 新增两圆心建轴、两点建轴、点原点加直线轴三种坐标系方式，支持 `-180°~180°` 附加旋转；计算在标定后的物理坐标中完成，X 向右、Y 向上、逆时针为正。
- 新增坐标标注、点点距离、圆心距、点线距离、直线角度、两线夹角和直径测量；坐标标注带引线显示在图像上并随配方保存。
- Recipe 新增可选 `geometry_program`，旧配方无该字段时加载为空程序；批量任务按相同程序逐次执行并保留尺寸结果。
- Excel 新增“尺寸结果”Sheet，导出要素、坐标系、坐标标注、尺寸数值、状态、质量、算法路径和错误信息。
- 通过全量 pytest、Qt 离屏启动和 V2 主界面渲染检查；发布包继续采用完整 Setup 与 SHA256 校验。

## V1.9.0

- 椭圆拟合新增经 X/Y 像素标定和拟合角度换算后的物理长轴、短轴、平均直径与圆度 `(长轴-短轴)/2`；原轴比评分语义保持不变。
- 识别明细和 Excel 增加“椭圆圆度(μm)”及公式说明，圆、卡尺圆和矩形结果不填充该字段。
- 批量任务新增每次识别结果、候选选择、文件名、质量状态和错误信息快照；移除重复保存的卡尺窗口/梯度数组并限制轮廓点数量。
- 识别明细新增批次选择器，支持按次数同步预览图像与轮廓，或在“全部”视图合并所有次数；失败次数同样保留。
- Excel“识别明细”输出全部批次数据；重复性表和最终有效均值的统计定义不变。
- 自动候选改为自适应行聚类后的左上到右下数字编号；双图上下层独立编号，候选质量排序和默认选择优先级保持不变。
- 兼容旧配方 `a/b/c` 候选选择，按旧检测排名映射到新内部标识，映射失败时明确提示并安全回退。
- 通过 76 项 pytest、四种窗口尺寸 Qt 离屏检查、打包后 EXE 冒烟启动、Setup 编译和 SHA256 一致性校验。

## V1.8.3

- 为无边框主窗口增加 Windows 原生 `WM_NCHITTEST` 命中处理，恢复四条边和四个角的自由拖动缩放及系统缩放光标。
- 缩放命中范围按 DPI 换算，并支持负数多显示器坐标；最大化和全屏时不返回缩放命中。
- 保留标题栏拖动、双击最大化、窗口控制按钮和 `1120 × 720` 安全最小尺寸。
- 新增八方向边缘/角落命中与最小尺寸自动回归测试。
- 将“无边框窗口必须完整替代原生窗口交互”加入软件设计 skill，作为后续桌面工具的发布门槛。
- 通过 68 项 pytest、四种窗口尺寸 Qt 渲染检查、实际 Windows 八方向原生命中验证，以及 Setup 安装/启动/卸载验证。

## V1.8.2

- 将手动与自动卡尺从持续显示的测量结果覆盖层改为按需显示的编辑辅助；只要生成识别结果，无论质量等级如何都会自动隐藏。
- 增加固定屏幕像素容差的命中检测；点击拟合圆、矩形、轮廓或中心十字只显示该特征卡尺，点击空白区域再次隐藏。
- 完全识别失败时继续显示手动卡尺；切换上下文或识别结果变化时清除旧选中状态，并保留手动 ROI 的原有编辑行为。
- 将边缘点诊断与卡尺可见性分离，有效点、红色剔除点、拟合轮廓、中心和质量信息可以独立查看。
- 增加专用黑灰光圈/靶标应用图标，覆盖 Qt 窗口、打包 EXE、Setup、开始菜单和桌面快捷方式。
- 不修改测量算法、质量门槛、Recipe 数据结构和导出字段。
- 通过 66 项 pytest、Qt 离屏测试、Setup 实际安装、安装后启动和卸载验证。

## V1.8.1

- Added a reproducible PyInstaller one-folder build that keeps application dependencies isolated while avoiding one-file startup extraction and antivirus friction.
- Added an Inno Setup installer with a stable AppId, Program Files installation, shortcuts, uninstall support, application shutdown during upgrade, and in-place full-installer upgrades.
- Added a release script that runs tests, generates Windows version metadata, builds the application, performs a packaged smoke launch, compiles Setup, and emits SHA256 update metadata.
- Kept recipes, runtime logs, recovery state, and measurement exports outside the installation directory so upgrades do not overwrite operator data.

## V1.8.0

- Split the former 5000-line UI module into focused component, builder, state, workflow, recipe-view, recipe-action, and worker modules.
- Kept `overlay_measure.ui_main.MainWindow`, existing widget imports, `main.py`, recipes, and measurement behavior backward compatible.
- Made worker-to-window signal delivery explicitly queued after the mixin split so all Qt UI updates remain on the GUI thread.
- Kept headless regression runs from invoking unsupported offscreen window capture while preserving production trace screenshots.

## V1.7.2

- Fixed the Analyze ROI button signal so Qt's unchecked-state argument can no longer silently disable user-facing result and error dialogs.
- Restored friendly ROI error translation with actionable guidance for missing edges, caliper failures, excessive residuals, and invalid ROI setup.
- Added immediate analyzing feedback, per-layer stage updates, partial-success warnings, explicit failure dialogs, button-state recovery, and runtime exception logging.

## V1.7.1

- Added Standard, Tolerant, and Ultra-Precise recognition-quality presets; Standard preserves the existing V1.7.0 thresholds.
- Kept the five underlying quality limits editable in engineering mode and marks a preset as adjusted when custom values differ.
- Separated gate validity from actual recognition quality, reporting excellent, standard, tolerant-only, or invalid quality independently of the selected gate.
- Added quality preset, actual quality grade, and detailed metrics to recognition details, overlay results, traceability data, and Excel exports.

## V1.7.0

- Changed three-point circle input to an initialization aid; the reported center and average diameter now come from coherent full-circumference caliper edges, RANSAC rejection, and robust geometric circle refinement.
- Added explicit inner-edge, outer-edge, and globally consistent strongest-edge selection so individual calipers no longer mix concentric boundaries.
- Added a per-caliper-ROI average/maximum diameter selector plus average, maximum Feret, minimum, PV, angular-coverage, and largest-gap statistics in measurement details and Excel exports; diameter choice does not alter the fitted center.
- Corrected the half-pixel mismatch between OpenCV pixel-center coordinates and Qt image rendering that made fitted outlines appear shifted toward the upper-left.
- Hid completed caliper search rings, windows, edge points, and rejected points by default; diagnostics remain available on demand and stay visible for invalid results.
- Changed solid circle and rectangle ROIs from all-edge collection to main-target segmentation followed by subpixel refinement of one connected contour.
- Tightened circle outlier rejection, added robust orthogonal-distance refinement, and made automatic model selection prefer a circle over a nearly circular ellipse.
- Added regression tests for concentric edge selection, noisy solid-ROI isolation, pixel-center rendering, and updated golden measurements.

## V1.6.1

- Added a configurable local recipe-library location in Recipe Manager, separate from the optional shared recipe directory.
- Added “copy, migrate, and switch”, “switch only”, and “restore default” workflows while retaining the original directory as a safety backup.
- Migrated recipe JSON files, SHA256 sidecars, favorites, recent-use history, and shared-directory configuration; conflicting recipes are retained under timestamped names.
- Added rollback behavior so a failed migration does not switch the active library and removes files created by the failed attempt.
- Persisted the selected local-library path in application settings outside the recipe directory, while retaining the existing environment-variable override.
- Locked local/shared directory changes and recipe import in production mode to prevent unapproved recipe publication.
- Added migration, conflict, rollback, persistence, and production-permission regression tests.

## V1.6.0

- Added production and engineering operation modes. The application starts in production mode; entering engineering mode requires a password, initially `admin123`, and authenticated engineers can change it from the product-information page.
- Locked ROI editing, algorithm parameters, diagnostic controls, product configuration, and recipe saving in production mode.
- Added SHA256 recipe sidecars and blocked production calculations when a recipe is unsealed, modified, unvalidated, or missing required production metadata.
- Added explicit `Pass`, `Fail`, `Invalid`, and `Error` result states so specification failures are no longer conflated with recognition failures or runtime exceptions.
- Added batch image pairing checks for missing layers, count mismatches, and accidental use of the same file as both upper and lower images.
- Added automatic measurement archives containing software version, operation mode, recipe hash, parameter snapshots, input-file hashes, per-run results, and a UI screenshot.
- Added rotating runtime logs, unfinished-task recovery, configurable calculation timeout, and cooperative cancellation.
- Added measurement ID, operation mode, recipe hash, and archive path to exported Excel traceability information.
- Added focused regression coverage for access control, recipe integrity, quality verdicts, batch pairing, traceability archives, and production preflight checks.

## V1.5.7

- Added a searchable quick recipe switcher in the frameless title bar, grouped by favorites, recent use, and all recipes.
- Added a managed local recipe library under the user's local application-data directory with validated, draft, and archived categories.
- Preserved direct JSON file loading with an explicit choice between one-time loading and importing a managed library copy.
- Added a recipe manager for filtering recipes, toggling favorites, opening the local library, and configuring an optional company shared recipe directory.
- Made recipe switching preserve imported single/batch images while replacing old ROIs and clearing stale measurement, auto-detection, and repeatability results after confirmation.
- Kept existing recipe JSON fields compatible and stored favorites, history, and shared-library settings in a separate library-state file.

## V1.5.6

- Refined the frameless window against the approved fused measurement-workstation mockup.
- Reduced the custom title bar to 46 px and limited it to product identity, version, recipe actions, and system window controls.
- Moved image import, display mode, reset, zoom, ROI analysis, overlay calculation, and export into a dedicated command bar.
- Added a direct zoom percentage selector while preserving wheel zoom, panning, and fit-to-window behavior.
- Rebalanced the image workspace and right configuration rail, reduced result-table minimum height, and retained a stable four-column result summary.
- Kept task state, current recipe, persistent progress, current stage, algorithm path, and cancellation visible in one non-jumping bottom status row.
- Removed remaining emoji button labels and aligned controls to a restrained neutral-blue industrial visual system.

## V1.5.5

- Reworked the desktop layout into a frameless, light industrial workspace based on the selected fused UI direction.
- Removed the redundant left workflow rail while keeping the numbered 1–5 configuration tabs on the right.
- Added a stable four-column result strip with responsive typography for compact window sizes.
- Consolidated task state, current recipe, live progress, current calculation stage, algorithm path, and cancellation in the bottom status bar.
- Fixed three-point circle creation so right/middle-button panning takes priority after two points without clearing the selected points.
- Ensured top-level single-image imports replace stale batch previews and switch the run back to single-measurement mode.
- Added a full measurement reset that clears imported images, batch lists, results, detections, automatic candidates, and every ROI while preserving reusable parameters.
- Added append-style batch import from multiple folders, direct folder import, optional recursive subfolder scanning, natural ordering, and duplicate-file skipping.
- Removed the redundant expected-repeat-count input; repeat counts now come directly from imported image lists.

## V1.5.4

- Moved single and batch overlay calculations to a `QThread` worker with real stage progress and cooperative cancellation.
- Added per-Mark/per-layer ROI source tracking (`recipe`, `manual`, or unset), source display, and explicit recipe-ROI confirmation before manual calculations.
- Made full-image auto recognition explicitly ignore every stored ROI and clear stale automatic candidates when switching workflows.
- Renamed the ROI fitting option to clarify that automatic model selection is not the full-image auto-recognition workflow.
- Added controls to clear the current ROI or all remaining recipe ROIs.
- Combined the web V1.5.3 display/export improvements with the main branch measurement service, non-square-pixel conversion, golden tests, and automatic-search truncation diagnostics.
- Preserved native image intensity ranges when display enhancement is off and retained failed batch runs in repeatability exports.

## V1.5.3

- Added Rx/Ry angle and material thickness compensation for overlay calculations.
- Added repeatability export rows with per-run results, mean, 3 sigma, and PV statistics.
- Added default export filenames based on the input image name plus `Misalignment_Result` and timestamp.
- Preserved Mark image aspect ratio in Excel exports.
- Added a UI display-enhancement switch, defaulting to raw grayscale display.
- Consolidated detection details, overlay results, and repeatability analysis into one result tab area.
- Added progress feedback and cancel support for Mark/batch overlay calculations.
- Restored algorithm-path traceability in the detection detail table and kept the status-bar popup.
- Removed duplicated top recipe/workflow hints and fixed recipe-name fallback after loading JSON.
- Changed final fit outlines and labels to high-contrast green instead of white.

## V1.5

- Added a service layer for manual ROI detection and Rz summary calculation, reducing UI coupling.
- Added golden-sample pytest coverage for manual ROI measurements, non-square pixel conversion, auto-detection reports, and Rz summaries.
- Added pytest project configuration and dependency constraints, plus a locked requirements file for reproducible production installs.
- Added a status-bar algorithm-path button that opens the actual measurement pipeline in a popup without occupying the main workspace.
- Added auto-detection truncation warnings for time, contour, and candidate limits.
- Improved physical unit conversion for non-square pixels, including radial statistics and rotated rectangle sizing.
- Removed redundant table section title labels to give more vertical space to measurement details and results.
- Added `start_overlay_measure.bat` as a clear Windows startup file while keeping `main.py` as the Python entry point.

## V1.4.2

- Replaced the repository root application with the package from `overlay_mark_measure_v1_4_2.zip`.
- Kept the previous repository version under `legacy/v1.0.5/`.
- Removed tracked `__pycache__` and PyCharm `.idea` files from the active project tree.
- Updated `README.md` to point to the current runnable entry point.
- Updated package metadata in `overlay_measure/__init__.py` to `1.4.2`.

## V1.0.5 / V1.1 lineage

- Previous repository root version before the V1.4.2 replacement.
- Retained as `legacy/v1.0.5/` for reference.
