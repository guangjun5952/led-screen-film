# 发布验证

2026-10-12，本地 macOS / Apple Silicon / Python 3.12.12：

- 所有 Python 文件通过语法检查；代码与文档通过常见凭据、私人绝对路径扫描。
- 使用 `requirements.txt` 安装依赖：NumPy 2.5.4、OpenCV 4.14.0.94、skia-python 144.0.post2、Pedalboard 0.9.26。
- `example_shot.py still` 在 640×360 与默认 1920×1080 下均成功生成 3 张 B-roll 检查帧和 1 张透明花字合成预览。
- 640×360 / 30 fps 完整示例渲染通过：6 秒 H.264/AAC MP4；3.5 秒 PNG/RGBA + PCM MOV。
- 两个输出均通过 FFprobe 流信息检查和 FFmpeg 全片解码。
- 中文示例使用测试机器的系统字体；系统字体文件未随仓库分发。
- 附带 Instrument Serif Italic 字体与 Google Fonts 官方副本 SHA-256 一致，并附完整 OFL 许可证。

这次验证覆盖示例渲染流程；未进行全部音效、所有镜头参数、其他介质函数、编辑器导入或 Linux/Windows 实机测试。
