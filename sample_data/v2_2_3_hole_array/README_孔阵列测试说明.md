# V2.2.3 孔阵列测试数据

- 上层图像：`hole_array_upper.png`
- 下层图像：`hole_array_lower.png`
- 测试配方：`hole_array_v2_2_3_recipe.json`
- 真实值：`hole_array_ground_truth.json`

图像为固定随机种子的数学模拟背光图。阵列为 5 列 x 4 行，孔径 120 μm，孔距 200 μm，像素尺寸 1.0 μm/px。

下层相对上层的图像坐标偏移为 X = +3.4 px、Y = -2.6 px。图像 Y 轴向下、设备 Y 轴向上，因此下层相对上层的设备坐标偏移为 X = +3.4 μm、Y = +2.6 μm。默认对位定义为 Upper - Lower，预期 ΔX = -3.4 μm、ΔY = -2.6 μm。

建议操作：加载测试配方，导入上下层图像，运行“分析 ROI 区域”，确认 20 个 ROI 按左上到右下识别，再选择对应上下层轮廓执行对位测量。
