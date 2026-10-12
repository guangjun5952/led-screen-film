# 引擎说明（scripts/）

依赖：`pip install skia-python numpy opencv-python pedalboard`，系统里要有 `ffmpeg`。

| 文件 | 作用 |
|---|---|
| engine.py | 灯珠采样 `led_view`、摄像机 `Cam`、镜头层 `post`、绘图基础函数（`draw_text/rect/line/circle/mono/hatch_rect`）、颜色、字体 |
| film.py | `Shot` 基类、`typed()` 逐字出字、`Film`（运动模糊合成）、三维工具（`Cam3/grid3/box3/line3/poly3/circle3/text3/mono3`）、实拍素材 `clip()/grade()` |
| pixfont.py | 5×7 像素字（`pix_text` 的 y 指字顶）。只包含 ASCII 和少量符号，长破折号 "–" 要写成 "-" |
| common.py | 花字工具 `typed_plate/plate_text/gag/pro/chat_box/bracket`，以及图片 `load_img/draw_img/draw_img_quad` |
| kit.py | `render_clip()`（B-roll MP4 + 音效）、`render_overlay()`（透明通道 MOV）、`Overlay` 基类、`sfx_track()` |
| sfx.py | 35 种合成音效：key blip hit impact whoosh riser swell data scramble cut zip ping zap count hop beep hum lock glitch strobe power_off room tick pick… |
| media.py | 其他介质：`crt / halftone / scope` |
| example_shot.py | 最小示例：`python3 example_shot.py still` 出检查帧，`python3 example_shot.py render` 出成片 |

## Shot 生命周期
- `cam(t) -> Cam(cx, cy, zoom, roll, px, py)`：cx、cy 是画布坐标，zoom=1 时整块屏铺满画面。
- `draw(c, t)`：在 640×360（或 `LED_SW×LED_SH`）的 skia 画布上作画。
- `post(t) -> dict`：可调 dof、dof_r0、band、ca、grain、exposure、bloom、flash、glitch。
- `footage(t)`：可选，返回一张 SH×SW×3 的实拍底图，图形会遮挡在它上面。
- 类属性 `dur`（时长）、`gain`（亮度增益）、`sub`（内容子帧数）、`shutter`（快门，单位帧）、`hud`。

## 音效事件
`events = [(时间秒, '名字', {参数})]`，例如 `(0.3, 'key', {'v': 1.2})`、`(1.0, 'whoosh', {'d': 0.6, 'up': True})`、`(2.0, 'cut', {'i': 0})`。
所有参数都可以加 `'g'` 调整增益。`kit.MASTER` 是全局电平，统一用它，保证各个镜头之间音量一致。

## 常见坑
- `post()` 返回的是 uint8；自己再接其他处理时，要先除以 255。
- 实拍素材的遮挡层要用透明底清屏（`ColorTRANSPARENT`），不能用黑底。
- 逐词对齐时要先精确匹配整个词，否则查"亮"会先命中"月亮"。
- 长任务用 `setsid nohup` 放到后台渲染，再用队列逐个跑。
