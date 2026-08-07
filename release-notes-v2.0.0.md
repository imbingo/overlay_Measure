# SOMA Vision Metrology V2.0.0

`See Once, Measure All` · 视觉轮廓与对位量测平台

## 主要更新

- 在 V1.9.0 单工作区中新增轮廓测量，不拆分单图、双图或对位流程。
- 新增点、直线、圆、最小外接圆、稳健外轮廓圆、交点、中点和投影点。
- 新增三种自定义坐标系建立方式和附加旋转角度。
- 新增图上坐标标注、点点距离、圆心距、点线距离、直线角度、两线夹角和直径。
- 顶部主命令改为“运行测量程序”，统一执行已配置的识别、对位和尺寸程序。
- Recipe 增加可选 `geometry_program`，兼容 V1.x 配方。
- 批量测量保留每次尺寸结果；Excel 增加“尺寸结果”Sheet。
- 保留原 AppId、内部 EXE 名称和 `%LOCALAPPDATA%\OverlayMeasure` 用户数据目录，可覆盖升级 V1.x。

## 安装

下载并运行：

`SOMA_Vision_Metrology_V2.0.0_Setup.exe`

安装前建议关闭旧版本。Setup 会执行完整覆盖升级，不会删除本机配方、运行日志和历史测量档案。

## 校验

Release 同时提供 `.sha256` 文件和 `update_manifest.json`。可用以下 PowerShell 命令核对：

```powershell
Get-FileHash .\SOMA_Vision_Metrology_V2.0.0_Setup.exe -Algorithm SHA256
```
