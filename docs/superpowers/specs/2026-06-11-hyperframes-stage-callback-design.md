# HyperFrames 阶段显示修正设计

## 目标

修正控制台热榜任务在 HyperFrames 渲染路径上的阶段显示，让阶段时间线与真实执行步骤一致。

## 范围

只处理 `P0-4 修正 HyperFrames 阶段显示`：

- 为 HyperFrames 渲染链路增加阶段回调。
- 控制台使用真实阶段更新任务状态与日志。
- 前端补齐新阶段名称与重试映射。
- 增加对应回归测试。

## 当前问题

当前控制台在进入 HyperFrames 渲染时，会先手工把任务状态跳到：

- `generating_tts`
- `composing_video`
- `post_processing`

但真实步骤实际是：

1. 生成 TTS
2. 生成 HTML composition
3. 调 HyperFrames CLI 渲染视频
4. 混入语音
5. 执行最终后处理

这会导致：

- 用户看到的阶段不准确。
- 失败阶段只能粗略落在 `composing_video`。
- 取消请求也无法按真实步骤边界观察进度。

## 设计

### 新阶段

HyperFrames 路径新增 3 个中间阶段：

- `composing_html`
- `rendering_hyperframes`
- `mixing_audio`

保留已有阶段：

- `generating_tts`
- `post_processing`

### 阶段回调

在 `src/hotlist_v2/render.py` 的 HyperFrames 渲染入口增加可选 `stage_callback(stage, message)`：

- 每进入一个真实步骤前触发一次。
- 控制台消费这个回调并写入 `task.stage` 与日志。

### 控制台行为

- HyperFrames 路径不再预先手工把阶段跳到 `composing_video`。
- `render_video()` 在开始时只标记 `status=running`。
- 具体阶段由回调驱动。

### 前端行为

- 阶段名称映射增加：
  - `composing_html` -> `生成画面`
  - `rendering_hyperframes` -> `渲染动画`
  - `mixing_audio` -> `混合音频`
- 失败重试映射中，这几个阶段都继续走 `render-video`。

## 验收标准

- HyperFrames 路径的阶段历史按真实顺序记录。
- 渲染失败时，`failed_stage` 能落在更准确的真实阶段。
- 前端时间线能显示新增阶段中文标签。
- 相关测试通过。

## 不做范围

- 不新增独立前端进度组件。
- 不调整非 HyperFrames 的阶段流。
- 不改动后台任务化逻辑。
