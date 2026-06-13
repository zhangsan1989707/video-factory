# 真实端到端验收样例设计

## 背景

P2-3 要补齐真实 API、真实 TTS、真实浏览器采集、真实视频渲染的验收方式。现有单元测试保护核心逻辑，`tests/smoke_*.py` 能手动跑本机渲染，但缺少固定样例、统一清单和可显式开启的慢速 e2e。

## 范围

本轮新增：

- 手动验收清单：`docs/e2e-manual-checklist.md`
- 慢速 pytest：`tests/test_real_e2e_smoke.py`
- 开发指南中加入手动和慢速 e2e 入口

默认测试不运行真实 e2e；必须显式设置：

```bash
GITHUB_VIDEO_RUN_SLOW_E2E=1 .venv/bin/python -m pytest tests/test_real_e2e_smoke.py -q
```

## 固定样例

慢速 e2e 使用固定公共仓库：

- `https://github.com/psf/requests`
- `https://github.com/pallets/flask`

这两个项目长期稳定、README 和仓库元数据充足，适合作为公共 smoke 样例。测试不依赖热榜抓取排序，避免选题波动影响判断。

## 验收链路

慢速 e2e 调用 `run_pipeline()` 的 hotlist 竖屏路径：

1. 拉取固定仓库元数据。
2. 生成 hotlist 分镜与脚本。
3. 采集真实素材。
4. 生成真实 TTS。
5. 合成竖屏 MP4。
6. 使用 `ffprobe` 检查视频流、音频流、时长和文件大小。

## 失败定位

清单和测试输出按阶段定位：

- GitHub：仓库元数据拉取失败或 API 限流。
- TTS：语音生成失败。
- 浏览器采集：素材采集失败或浏览器缺失。
- ffmpeg/ffprobe：合成、编码或媒体探测失败。

## 验收

- 默认 pytest 中该测试显示 skipped。
- 设置环境变量后才执行真实慢速 e2e。
- 文档说明从空环境到跑出视频的步骤和证据记录。
