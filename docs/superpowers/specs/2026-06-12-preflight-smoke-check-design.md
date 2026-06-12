# 2026-06-12 预检 Smoke Check 设计

## 背景

当前控制台预检主要确认依赖是否存在，但无法证明 `ffmpeg`、`ffprobe`、HyperFrames CLI 等关键工具真的能运行。用户可能看到“依赖可用”，但正式渲染时才发现本机环境不可用。

## 本次范围

围绕 `P1-4` 增加轻量本地 smoke：

1. `ffmpeg/ffprobe` smoke：生成一段 0.2 秒本地样例视频，再用 `ffprobe` 读取时长。
2. HyperFrames smoke：执行 `npx hyperframes --help`，验证 CLI 能启动。
3. 预检摘要区分静态依赖和 smoke 结果。
4. 失败 message 给出可执行修复建议。

## 设计取舍

- 不做 TTS 网络连通 smoke。
  - 原因：打开控制台时触发网络请求会慢，也可能产生费用或限流。
- 不做真实浏览器录制 smoke。
  - 原因：浏览器录制属于慢速端到端验收，更适合 `P2-3` 的显式慢速测试。
- smoke 超时要短。
  - 原因：控制台启动时会调用预检，不能明显拖慢 UI。

## 验收点

1. 预检结果包含 `smoke.ffmpeg_ffprobe` 和 `smoke.hyperframes_cli`。
2. smoke 失败时状态为 blocking，并包含修复建议。
3. 控制台顶部摘要能说明 smoke 已通过或 smoke 未通过。
