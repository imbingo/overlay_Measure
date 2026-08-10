from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from overlay_measure.geometry_models import GeometryProgram  # noqa: E402
from overlay_measure.models import DetectionParams, MarkRecipe, MeasurementConfig, Roi, RoiEntry  # noqa: E402
from overlay_measure.recipe_manager import save_recipe  # noqa: E402


OUTPUT = ROOT / "sample_data" / "v2_2_3_hole_array"
WIDTH, HEIGHT = 1100, 900
PIXEL_SIZE_UM = 1.0
DIAMETER_UM = 120.0
PITCH_UM = 200.0
SHIFT_X_PX = 3.4
SHIFT_Y_PX = -2.6
SEED = 223120
SUPERSAMPLE = 4


def centers(shift_x: float = 0.0, shift_y: float = 0.0) -> list[tuple[float, float]]:
    return [
        (150.0 + column * PITCH_UM + shift_x, 150.0 + row * PITCH_UM + shift_y)
        for row in range(4)
        for column in range(5)
    ]


def render(path: Path, hole_centers: list[tuple[float, float]], seed: int) -> None:
    scale = SUPERSAMPLE
    yy, xx = np.mgrid[0 : HEIGHT * scale, 0 : WIDTH * scale]
    base = 17.0 + 4.0 * xx / (WIDTH * scale) - 3.0 * yy / (HEIGHT * scale)
    image = base.astype(np.float32)
    radius = DIAMETER_UM / PIXEL_SIZE_UM * scale / 2.0
    for center_x, center_y in hole_centers:
        distance = np.hypot(xx - center_x * scale, yy - center_y * scale)
        image[distance <= radius] = 226.0
    image = Image.fromarray(np.clip(image, 0, 255).astype(np.uint8), mode="L")
    image = image.filter(ImageFilter.GaussianBlur(radius=1.15 * scale))
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    values = np.asarray(image, dtype=np.float32)
    rng = np.random.default_rng(seed)
    values += rng.normal(0.0, 1.35, values.shape)
    Image.fromarray(np.clip(values, 0, 255).astype(np.uint8), mode="L").save(path)


def make_rois(layer: str, hole_centers: list[tuple[float, float]]) -> list[RoiEntry]:
    result = []
    size = 156.0
    for index, (center_x, center_y) in enumerate(hole_centers, start=1):
        result.append(
            RoiEntry(
                f"{layer}-hole-{index:02d}",
                Roi(center_x - size / 2.0, center_y - size / 2.0, size, size, "Circle"),
                "sample",
            )
        )
    return result


def write_ground_truth(upper: list[tuple[float, float]], lower: list[tuple[float, float]]) -> None:
    holes = []
    for index, (upper_center, lower_center) in enumerate(zip(upper, lower), start=1):
        holes.append(
            {
                "index": index,
                "row": (index - 1) // 5 + 1,
                "column": (index - 1) % 5 + 1,
                "upper_center_px": {"x": upper_center[0], "y": upper_center[1]},
                "lower_center_px": {"x": lower_center[0], "y": lower_center[1]},
                "diameter_um": DIAMETER_UM,
            }
        )
    data = {
        "dataset": "V2.2.3 backlit 120 um hole array",
        "generator_seed": SEED,
        "image_size_px": {"width": WIDTH, "height": HEIGHT},
        "pixel_size_um_per_px": {"x": PIXEL_SIZE_UM, "y": PIXEL_SIZE_UM},
        "array": {"columns": 5, "rows": 4, "pitch_um": PITCH_UM},
        "hole_diameter_um": DIAMETER_UM,
        "lower_relative_to_upper_image_px": {"x": SHIFT_X_PX, "y": SHIFT_Y_PX},
        "lower_relative_to_upper_device_um": {"x": SHIFT_X_PX, "y": -SHIFT_Y_PX},
        "expected_upper_minus_lower_device_um": {"delta_x": -SHIFT_X_PX, "delta_y": SHIFT_Y_PX},
        "coordinate_convention": "image +Y is down; device +Y is up",
        "holes": holes,
    }
    (OUTPUT / "hole_array_ground_truth.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_recipe(upper: list[tuple[float, float]], lower: list[tuple[float, float]]) -> None:
    config = MeasurementConfig(
        mode="Dual Image",
        workflow_mode="Manual",
        recipe_name="V2.2.3_120um_孔阵列测试",
        recipe_version="2.2.3",
        recipe_validation_status="Test",
        pixel_size_x_um=PIXEL_SIZE_UM,
        pixel_size_y_um=PIXEL_SIZE_UM,
        delta_x_limit_um=10.0,
        delta_y_limit_um=10.0,
        overlay_r_limit_um=15.0,
    )
    params = DetectionParams(
        gaussian_sigma_px=1.0,
        canny_low=25.0,
        canny_high=80.0,
        min_gradient=3.0,
        fitting_mode="Circle",
        upper_fitting_mode="Circle",
        lower_fitting_mode="Circle",
        residual_limit_px=1.5,
        min_edge_points=60,
        diameter_min_um=105.0,
        diameter_max_um=135.0,
        polarity="Bright to Dark",
    )
    mark = MarkRecipe(
        "Mark1",
        upper_rois=make_rois("upper", upper),
        lower_rois=make_rois("lower", lower),
        reference_contour_id="upper-hole-01",
        target_contour_id="lower-hole-01",
        reference_shape="Circle",
        target_shape="Circle",
        reference_size_min_um=105.0,
        reference_size_max_um=135.0,
        target_size_min_um=105.0,
        target_size_max_um=135.0,
    )
    save_recipe(str(OUTPUT / "hole_array_v2_2_3_recipe.json"), config, params, [mark], GeometryProgram())


def write_readme() -> None:
    content = """# V2.2.3 孔阵列测试数据

- 上层图像：`hole_array_upper.png`
- 下层图像：`hole_array_lower.png`
- 测试配方：`hole_array_v2_2_3_recipe.json`
- 真实值：`hole_array_ground_truth.json`

图像为固定随机种子的数学模拟背光图。阵列为 5 列 x 4 行，孔径 120 μm，孔距 200 μm，像素尺寸 1.0 μm/px。

下层相对上层的图像坐标偏移为 X = +3.4 px、Y = -2.6 px。图像 Y 轴向下、设备 Y 轴向上，因此下层相对上层的设备坐标偏移为 X = +3.4 μm、Y = +2.6 μm。默认对位定义为 Upper - Lower，预期 ΔX = -3.4 μm、ΔY = -2.6 μm。

建议操作：加载测试配方，导入上下层图像，运行“分析 ROI 区域”，确认 20 个 ROI 按左上到右下识别，再选择对应上下层轮廓执行对位测量。
"""
    (OUTPUT / "README_孔阵列测试说明.md").write_text(content, encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    upper = centers()
    lower = centers(SHIFT_X_PX, SHIFT_Y_PX)
    render(OUTPUT / "hole_array_upper.png", upper, SEED)
    render(OUTPUT / "hole_array_lower.png", lower, SEED + 1)
    write_ground_truth(upper, lower)
    write_recipe(upper, lower)
    write_readme()
    print(OUTPUT)


if __name__ == "__main__":
    main()
