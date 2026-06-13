# 真实端到端验收清单

用于验证 GitHub Video Maker 在当前机器上能完成真实 API、浏览器采集、TTS、ffmpeg 合成和媒体探测。默认测试不会运行这条慢链路，需要人工显式执行。

## 前置条件

- Python 依赖已安装：`.venv/bin/python -m pip install -e .`
- Node 依赖已安装：`npm install`
- Playwright Chromium 已安装：`.venv/bin/python -m playwright install chromium`
- `ffmpeg` 和 `ffprobe` 可执行：`ffmpeg -version`、`ffprobe -version`
- 网络可访问 `api.github.com`、`github.com`、`raw.githubusercontent.com` 和 Edge TTS 服务
- 可选：配置 `GITHUB_TOKEN`，降低 GitHub API 限流概率

## 固定样例

使用两个长期稳定的公共仓库，避免热榜排序波动影响验收：

- `https://github.com/psf/requests`
- `https://github.com/pallets/flask`

## 手动命令

```bash
mkdir -p output/e2e-real-smoke
.venv/bin/python -m src.cli \
  "https://github.com/psf/requests,https://github.com/pallets/flask" \
  --vertical \
  --style hotlist \
  --no-bgm \
  -o output/e2e-real-smoke/final.mp4
```

```bash
ffprobe -v error \
  -show_entries format=duration,size \
  -show_streams \
  -of json \
  output/e2e-real-smoke/final.mp4
```

## 慢速自动验收

```bash
GITHUB_VIDEO_RUN_SLOW_E2E=1 .venv/bin/python -m pytest tests/test_real_e2e_smoke.py -q
```

不设置 `GITHUB_VIDEO_RUN_SLOW_E2E=1` 时，该测试应显示 skipped。

## 通过标准

- `output/e2e-real-smoke/final.mp4` 存在且文件大小大于 0
- `ffprobe` 输出至少包含一个 video stream 和一个 audio stream
- `duration` 大于 0
- 命令输出经过这些阶段：GitHub 仓库信息拉取、素材采集、TTS、视频合成、后处理

## 失败定位

- GitHub：仓库元数据拉取失败、API 限流或网络无法访问 `api.github.com`
- 浏览器采集：Playwright Chromium 缺失、网页超时或截图失败
- TTS：Edge TTS 网络不可达、语音服务超时或返回异常
- ffmpeg/ffprobe：本机缺少二进制、编码失败、没有音视频流或媒体文件损坏
