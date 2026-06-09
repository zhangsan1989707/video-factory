# GitHub Video Maker

自动生成 GitHub 项目介绍视频的工具。

## 项目配置

### TTS 配音
- **声音**: `zh-CN-YunxiNeural`（微软 Edge TTS 中文男声）
- **说明**: 用户确认此声音效果好，后续视频统一使用此声音

### 视频风格
- **desktop-review**: 桌面浏览器风格，横屏 1592x1080，带开场卡、桌面背景、浏览器窗口、鼠标指针
- **vertical**: 竖屏 1080x1920，适合短视频平台

### 常用命令

```bash
# 生成 desktop-review 风格视频（完整流程）
.venv/bin/python -m src.cli https://github.com/owner/repo --style desktop-review --vertical --dry-run -o output/dir/final.mp4
.venv/bin/python -m src.cli --from-plan output/dir -o output/dir/final.mp4

# 生成竖屏视频
.venv/bin/python -m src.cli https://github.com/owner/repo --vertical --dry-run -o output/dir/final.mp4
.venv/bin/python -m src.cli --from-plan output/dir -o output/dir/final.mp4
```

### 输出目录结构
```
output/
  └── project-name/
      ├── desktop_review_plan.json  # desktop-review 分镜
      ├── shot_plan.json            # 竖屏分镜
      ├── script.json               # 口播脚本
      ├── info.json                 # 项目信息
      ├── audio/                    # TTS 音频
      ├── desktop_frames/           # 浏览器录制帧
      ├── preview_frames/           # 预览帧
      └── final.mp4                 # 最终视频
```
