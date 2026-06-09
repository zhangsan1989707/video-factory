# GitHub Video Maker

本地 GitHub 视频工厂。当前主流程是用浏览器控制台生成 GitHub 热榜竖屏视频草稿，人工确认项目和口播后默认用 HyperFrames 的“科技热点风”模板渲染最终视频。

## 启动控制台

```bash
.venv/bin/python -m src.console --port 8765
```

打开:

```text
http://127.0.0.1:8765
```

控制台会保存本地配置到 `.config/video-console/`，任务和产物保存到 `output/jobs/`。

## 控制台流程

1. 在配置里填写 GitHub Token 和模型供应商。
2. 选择日榜、周榜或月榜，生成候选草稿。
3. 人工选择并排序项目。
4. 生成并编辑口播脚本。
5. 生成计划文件、校验 dry run，然后渲染最终视频。
6. 在产物栏查看预览帧、日志、`final.mp4` 和带编号的正式 mp4。

## 命令行渲染

```bash
.venv/bin/python -m src.cli https://github.com/owner/repo --style desktop-review --vertical --dry-run -o output/dir/final.mp4
.venv/bin/python -m src.cli --from-plan output/dir -o output/dir/final.mp4 --vertical
.venv/bin/python scripts/render_hotlist_v2.py --style tech_hotspot --token "$GITHUB_TOKEN" -o output/hotlist-v2/final.mp4
```

## 验证

```bash
.venv/bin/python tests/test_bgm.py && \
.venv/bin/python tests/test_console_jobs.py && \
.venv/bin/python tests/test_console_preflight.py && \
.venv/bin/python tests/test_console_providers.py && \
.venv/bin/python tests/test_console_scheduler.py && \
.venv/bin/python tests/test_console_server_smoke.py && \
.venv/bin/python tests/test_github_hotlist.py && \
.venv/bin/python tests/test_pipeline_from_plan.py && \
.venv/bin/python -m compileall src tests generate_hotlist10.py && \
node --check src/console/static/app.js && \
node --check tests/test_console_static_app.js && \
node tests/test_console_static_app.js && \
git diff --check
```
