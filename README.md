# Overlay Measure

对位偏差测量软件，用于识别 Upper / Lower mark 的中心位置，并计算对位偏差 `Dx`、`Dy`、`Dxy` 和 `Rz` 等结果。

## 当前版本

- 当前代码版本：V1.8.2
- 来源文件：`overlay_mark_measure_v1_4_2.zip`
- Windows 启动文件：`start_overlay_measure.bat`
- Python 主入口：`main.py`
- 主界面代码：`overlay_measure/ui_main.py`

## V1.8.2 更新说明

### 卡尺按需显示

- 手动卡尺圆只要生成识别结果，无论质量为有效、宽容或无效，都会自动隐藏内外圈、卡尺窗口和搜索方向。
- 点击拟合圆、矩形轮廓或中心十字，可重新显示当前特征对应的卡尺；点击图像空白处或按 `Esc` 再次隐藏。
- 完全识别失败、没有生成拟合轮廓时继续显示手动卡尺，方便修正 ROI。
- 进入卡尺编辑状态后，原有的移动 ROI、调整内外圈等操作保持可用；ROI 一旦变化会清除旧识别结果，重新分析后再次自动隐藏。
- 自动圆与自动四边卡尺支持按候选特征单独显示；存在多个候选时，只显示当前点击特征的卡尺，不会转换成手动 ROI。
- 轮廓点击采用固定屏幕像素容差，放大或缩小图像后仍保持一致的点击手感。

### 诊断与状态

- 边缘有效点、红色剔除点、拟合轮廓、中心和质量信息与卡尺显示彻底分离。
- 打开诊断模式不会强制恢复卡尺，低质量或无效结果也不会让卡尺持续遮挡特征边。
- 切换 Mark、层、图像、配方、工作方式或执行重置测量时，会清除当前卡尺选中状态。
- 图像区增加“点击拟合轮廓显示卡尺，点击空白处隐藏”的操作提示。

### 应用图标与兼容性

- 使用黑灰光圈与中心靶标专用图标，统一应用于 Qt 窗口、Windows EXE、Setup 安装程序、开始菜单和桌面快捷方式。
- 本次更新不修改测量算法、质量门槛、Recipe 数据结构和导出字段。
- 继续沿用 V1.8.1 的完整安装包覆盖升级、稳定 AppId 和 SHA256 校验机制。

### 验证与下载

- `66` 项 pytest 全部通过。
- Qt 离屏交互测试和打包后启动检查通过。
- Setup 实际静默安装、安装后 EXE 启动和卸载验证通过。
- [下载 V1.8.2 Setup](https://github.com/imbingo/overlay-measure/releases/download/v1.8.2/OverlayMeasure_Setup_V1.8.2.exe)
- [查看 V1.8.2 Release](https://github.com/imbingo/overlay-measure/releases/tag/v1.8.2)
- [查看完整版本记录](CHANGELOG.md)

## 运行

```powershell
python -m pip install -r requirements.txt
python .\main.py
```

Windows 下可以直接双击仓库根目录的 `start_overlay_measure.bat`。启动器会在当前项目根目录创建独立的 `.venv`，首次运行时自动安装并校验 `requirements.txt` 中的依赖，然后启动软件。后续运行会复用该环境；只有依赖文件变化或环境损坏时才会重新安装。

自动安装仍要求电脑已安装 64 位 Python 3.10-3.13。首次安装依赖需要能够访问配置的 Python 软件源。需要强制重新安装依赖时，可在 PowerShell 中执行：

```powershell
.\start_overlay_measure.bat -ForceInstall
```

正式发布包使用：

```powershell
.\scripts\build_release.bat -Python "D:\python\python.exe"
```

输出位于 `release\`。详细说明见 [`installer/README.md`](installer/README.md)。

如需生产环境完全复现当前依赖，可使用：

```powershell
python -m pip install -r requirements.lock.txt
```

## 主要功能

- 支持 Single Image / Dual Image 测量模式。
- 支持手动 ROI 与自动识别测量。
- 支持圆、椭圆、矩形、环形 ROI 等 mark 拟合流程。
- 支持批量测量与重复性分析。
- 支持配方 JSON 保存/加载、本机配方库、共享配方目录、收藏和最近使用快捷切换。
- 支持工程模式修改本机配方库位置，并安全迁移配方签章与使用状态。
- 支持生产/工程权限隔离、配方 SHA256 完整性校验和生产测量前置检查。
- 支持通过、超限、无效、异常四态结果，以及输入文件和参数快照追溯。
- 支持 Excel 结果导出。
- 支持样例图片和样例 recipe 快速验证流程。

## 目录说明

- `overlay_measure/`: 主程序模块。
- `sample_data/`: 示例图片和示例 recipe。
- `main.py`: GUI 启动入口。
- `start_overlay_measure.bat`: Windows 一键环境初始化和启动入口。
- `scripts/bootstrap_and_run.ps1`: 创建项目虚拟环境、安装和校验依赖并启动 GUI。
- `requirements.txt`: Python 依赖。
- `legacy/v1.0.5/`: 更新前仓库版本归档，用于回看旧版本文件。
- `CHANGELOG.md`: 版本更替记录。

## 数据文件规范

- 公开仓库只保留 `sample_data/` 下的演示图片和示例 recipe。
- 程序运行生成的 Excel 结果、根目录配方 JSON、真实料号 recipe 不再提交到仓库。
- 如需共享真实测量数据，请使用私有仓库、Release 附件或单独的数据存储位置。

## 生产模式

- 软件启动后默认处于生产模式。
- 初始工程模式密码为 `admin123`；进入工程模式后可在“产品信息”页修改密码，正式部署后应在受控流程中修改并限制知悉范围。
- 生产模式只接受“已验证”且 `.sha256` 签章匹配的配方。
- 运行日志、未完成任务和测量追溯档案默认保存在 `%LOCALAPPDATA%\OverlayMeasure`。

## 历史版本

仓库根目录始终放当前推荐版本。更新前版本已移动到 `legacy/v1.0.5/`，同时 Git 历史也保留了完整提交记录。
