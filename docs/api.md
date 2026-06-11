# GitHub Video Maker API 文档

## 概述

本文档描述了 GitHub Video Maker Web 控制台的 REST API 接口。

## 基础信息

- **Base URL**: `http://127.0.0.1:8765`
- **Content-Type**: `application/json`
- **认证**: 无（本地运行）

## 健康检查

### GET /api/health

检查服务器是否正常运行。

**响应示例**:
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

## 环境预检

### GET /api/preflight

检查渲染环境是否就绪。

**响应示例**:
```json
{
  "ok": true,
  "checks": [
    {"name": "python_modules", "ok": true, "message": "所有 Python 模块已安装"},
    {"name": "ffmpeg", "ok": true, "message": "ffmpeg 版本 6.0"},
    {"name": "playwright", "ok": true, "message": "Playwright 浏览器已安装"},
    {"name": "github_token", "ok": true, "message": "GitHub Token 有效"},
    {"name": "model_provider", "ok": true, "message": "小米/mimo-v2.5-pro 连接成功"}
  ]
}
```

## 配置管理

### GET /api/config

获取当前配置快照（API Key 已脱敏）。

**响应示例**:
```json
{
  "providers": {
    "openai": {
      "enabled": false,
      "api_key": "sk-****...****",
      "base_url": "https://api.openai.com/v1"
    },
    "anthropic": {
      "enabled": false,
      "api_key": "sk-ant-****...****"
    },
    "deepseek": {
      "enabled": false,
      "api_key": "sk-****...****",
      "base_url": "https://api.deepseek.com/v1"
    },
    "xiaomi": {
      "enabled": true,
      "api_key": "sk-****...****",
      "base_url": "https://api.xiaomi.com/v1"
    }
  },
  "model_routing": {
    "candidate_analysis": "xiaomi/mimo-v2.5-pro",
    "hotlist_ranking": "xiaomi/mimo-v2.5-pro",
    "hook_generation": "xiaomi/mimo-v2.5-pro",
    "narration_generation": "xiaomi/mimo-v2.5-pro",
    "script_polishing": "xiaomi/mimo-v2.5-pro",
    "fact_check": "xiaomi/mimo-v2.5-pro"
  },
  "github": {
    "token": "ghp_****...****"
  },
  "scheduler": {
    "enabled": false,
    "frequency": "daily",
    "time": "09:30",
    "project_count": 5
  },
  "templates": {
    "active": "github_hotlist_vertical_v1",
    "style": "tech_hotspot",
    "render_engine": "hyperframes"
  }
}
```

### POST /api/config

更新配置。

**请求体**:
```json
{
  "providers": {
    "xiaomi": {
      "enabled": true,
      "api_key": "sk-new-key",
      "base_url": "https://api.xiaomi.com/v1"
    }
  },
  "model_routing": {
    "candidate_analysis": "xiaomi/mimo-v2.5-pro"
  }
}
```

**响应示例**:
```json
{
  "ok": true,
  "message": "配置已更新"
}
```

## 供应商管理

### POST /api/providers/:id/test

测试供应商连接。

**路径参数**:
- `id`: 供应商 ID (openai, anthropic, deepseek, xiaomi)

**响应示例**:
```json
{
  "ok": true,
  "message": "连接成功",
  "model": "mimo-v2.5-pro"
}
```

## 任务管理

### GET /api/jobs

列出所有任务。

**响应示例**:
```json
{
  "jobs": [
    {
      "id": "GH-HOTLIST-20260610-001",
      "status": "completed",
      "created_at": "2026-06-10T10:00:00Z",
      "completed_at": "2026-06-10T10:15:00Z",
      "project_count": 5,
      "final_video": "output/jobs/GH-HOTLIST-20260610-001/final.mp4"
    },
    {
      "id": "GH-HOTLIST-20260610-002",
      "status": "in_progress",
      "created_at": "2026-06-10T11:00:00Z",
      "completed_at": null,
      "project_count": null,
      "final_video": null
    }
  ]
}
```

### GET /api/jobs/:id

获取任务详情。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "id": "GH-HOTLIST-20260610-001",
  "status": "completed",
  "created_at": "2026-06-10T10:00:00Z",
  "completed_at": "2026-06-10T10:15:00Z",
  "config": {
    "frequency": "daily",
    "project_count": 5,
    "style": "tech_hotspot"
  },
  "candidates": [
    {
      "rank": 1,
      "name": "project-name",
      "owner": "owner",
      "stars": 1234,
      "description": "项目描述",
      "recommendation": "推荐理由"
    }
  ],
  "selection": [
    {
      "rank": 1,
      "name": "project-name",
      "owner": "owner",
      "hook_title": "钩子标题",
      "bullet_points": ["要点1", "要点2", "要点3"]
    }
  ],
  "script": {
    "title": "视频标题",
    "segments": [
      {
        "timestamp": 0,
        "duration": 4,
        "narration": "口播内容",
        "visual_asset": "opening"
      }
    ]
  },
  "artifacts": {
    "shot_plan": "output/jobs/GH-HOTLIST-20260610-001/shot_plan.json",
    "asset_manifest": "output/jobs/GH-HOTLIST-20260610-001/asset_manifest.json",
    "final_video": "output/jobs/GH-HOTLIST-20260610-001/final.mp4"
  }
}
```

### GET /api/jobs/:id/logs

获取任务日志。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "logs": [
    {"timestamp": "2026-06-10T10:00:00Z", "level": "info", "message": "任务创建"},
    {"timestamp": "2026-06-10T10:00:05Z", "level": "info", "message": "开始生成候选项目"},
    {"timestamp": "2026-06-10T10:01:00Z", "level": "info", "message": "候选项目生成完成，共 10 个"},
    {"timestamp": "2026-06-10T10:05:00Z", "level": "info", "message": "用户确认 5 个项目"},
    {"timestamp": "2026-06-10T10:05:30Z", "level": "info", "message": "生成口播脚本"},
    {"timestamp": "2026-06-10T10:10:00Z", "level": "info", "message": "生成计划文件"},
    {"timestamp": "2026-06-10T10:10:05Z", "level": "info", "message": "校验通过"},
    {"timestamp": "2026-06-10T10:10:10Z", "level": "info", "message": "开始渲染视频"},
    {"timestamp": "2026-06-10T10:15:00Z", "level": "info", "message": "视频渲染完成"}
  ]
}
```

### GET /api/jobs/:id/artifacts

获取任务产物列表。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "artifacts": [
    {
      "name": "shot_plan.json",
      "path": "output/jobs/GH-HOTLIST-20260610-001/shot_plan.json",
      "size": 2048,
      "created_at": "2026-06-10T10:10:00Z"
    },
    {
      "name": "asset_manifest.json",
      "path": "output/jobs/GH-HOTLIST-20260610-001/asset_manifest.json",
      "size": 1024,
      "created_at": "2026-06-10T10:10:00Z"
    },
    {
      "name": "final.mp4",
      "path": "output/jobs/GH-HOTLIST-20260610-001/final.mp4",
      "size": 15728640,
      "created_at": "2026-06-10T10:15:00Z"
    },
    {
      "name": "preview_001.png",
      "path": "output/jobs/GH-HOTLIST-20260610-001/preview_frames/preview_001.png",
      "size": 51200,
      "created_at": "2026-06-10T10:10:05Z"
    }
  ]
}
```

### GET /api/jobs/:id/artifacts/*

下载产物文件。

**路径参数**:
- `id`: 任务 ID
- `*`: 文件路径

**响应**: 文件流

### POST /api/jobs

创建热榜任务。

**请求体**:
```json
{
  "frequency": "daily",
  "project_count": 5,
  "style": "tech_hotspot"
}
```

**响应示例**:
```json
{
  "ok": true,
  "job_id": "GH-HOTLIST-20260610-003"
}
```

### POST /api/jobs/:id/candidates

生成候选项目。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "ok": true,
  "candidates": [
    {
      "rank": 1,
      "name": "project-name",
      "owner": "owner",
      "full_name": "owner/project-name",
      "stars": 1234,
      "language": "Python",
      "description": "项目描述",
      "topics": ["ai", "machine-learning"],
      "recommendation": "推荐理由",
      "target_audience": "目标受众",
      "score": 85
    }
  ]
}
```

### POST /api/jobs/:id/selection

确认项目选择。

**路径参数**:
- `id`: 任务 ID

**请求体**:
```json
{
  "selected": [
    {
      "rank": 1,
      "name": "project-name",
      "owner": "owner"
    },
    {
      "rank": 2,
      "name": "another-project",
      "owner": "another-owner"
    }
  ]
}
```

**响应示例**:
```json
{
  "ok": true,
  "selection": [
    {
      "rank": 1,
      "name": "project-name",
      "owner": "owner",
      "hook_title": "这个 AI 工具太强了",
      "bullet_points": ["自动生成代码", "支持 100+ 语言", "完全免费"]
    },
    {
      "rank": 2,
      "name": "another-project",
      "owner": "another-owner",
      "hook_title": "GitHub 热榜第一",
      "bullet_points": ["高性能", "易扩展", "社区活跃"]
    }
  ],
  "script": {
    "title": "今日 GitHub 热榜",
    "segments": [
      {
        "timestamp": 0,
        "duration": 4,
        "narration": "今天给大家分享 GitHub 热榜上的 5 个开源项目",
        "visual_asset": "opening"
      }
    ]
  }
}
```

### POST /api/jobs/:id/script

确认口播脚本。

**路径参数**:
- `id`: 任务 ID

**请求体**:
```json
{
  "script": {
    "title": "今日 GitHub 热榜",
    "segments": [
      {
        "timestamp": 0,
        "duration": 4,
        "narration": "今天给大家分享 GitHub 热榜上的 5 个开源项目",
        "visual_asset": "opening"
      },
      {
        "timestamp": 4,
        "duration": 6,
        "narration": "第一个项目是一个 AI 代码生成工具",
        "visual_asset": "project_1"
      }
    ]
  }
}
```

**响应示例**:
```json
{
  "ok": true,
  "quality_check": {
    "passed": true,
    "issues": [],
    "suggestions": []
  },
  "publishing_package": {
    "title": "今日 GitHub 热榜",
    "tags": ["github", "开源", "AI", "编程"],
    "description": "今天给大家分享 GitHub 热榜上的 5 个开源项目..."
  }
}
```

### POST /api/jobs/:id/prepare-plan

生成计划文件。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "ok": true,
  "shot_plan": {
    "title": "今日 GitHub 热榜",
    "shots": [
      {
        "start": 0,
        "duration": 4,
        "visual_asset": "opening",
        "visual_treatment": "hotlist_opening",
        "narration_intent": "开场介绍",
        "subtitle": "今日 GitHub 热榜"
      }
    ]
  },
  "asset_manifest": {
    "assets": [
      {
        "id": "project_1_screenshot",
        "type": "screenshot",
        "source": "playwright",
        "path": "output/jobs/GH-HOTLIST-20260610-001/assets/project_1.png",
        "caption": "项目截图",
        "use_case": "rank_card",
        "quality": "high"
      }
    ]
  },
  "preview_frames": [
    "output/jobs/GH-HOTLIST-20260610-001/preview_frames/preview_001.png",
    "output/jobs/GH-HOTLIST-20260610-001/preview_frames/preview_002.png"
  ]
}
```

### POST /api/jobs/:id/validate-plan

校验计划。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "ok": true,
  "validation": {
    "passed": true,
    "checks": [
      {"name": "shot_plan_exists", "ok": true, "message": "分镜文件存在"},
      {"name": "asset_manifest_exists", "ok": true, "message": "素材清单存在"},
      {"name": "assets_captured", "ok": true, "message": "所有素材已采集"},
      {"name": "script_complete", "ok": true, "message": "口播脚本完整"},
      {"name": "duration_valid", "ok": true, "message": "时长 45 秒，符合要求"}
    ]
  }
}
```

### POST /api/jobs/:id/render-video

渲染最终视频。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "ok": true,
  "message": "视频渲染已启动",
  "estimated_time": "2-5 分钟"
}
```

**注意**: 此接口会启动后台任务，可通过 `GET /api/jobs/:id` 查看进度。

### POST /api/jobs/:id/open-folder

打开任务目录（仅 macOS）。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "ok": true,
  "path": "output/jobs/GH-HOTLIST-20260610-001"
}
```

### POST /api/jobs/:id/finalize

生成带编号的正式文件。

**路径参数**:
- `id`: 任务 ID

**响应示例**:
```json
{
  "ok": true,
  "numbered_files": [
    "output/jobs/GH-HOTLIST-20260610-001/01-ai-code-generator.mp4",
    "output/jobs/GH-HOTLIST-20260610-001/02-performance-tool.mp4",
    "output/jobs/GH-HOTLIST-20260610-001/03-ml-framework.mp4",
    "output/jobs/GH-HOTLIST-20260610-001/04-cli-tool.mp4",
    "output/jobs/GH-HOTLIST-20260610-001/05-web-framework.mp4"
  ]
}
```

## 定时任务

### POST /api/scheduler/run-due

手动触发到期的定时任务。

**响应示例**:
```json
{
  "ok": true,
  "triggered": [
    {
      "job_id": "GH-HOTLIST-20260610-004",
      "frequency": "daily",
      "scheduled_time": "09:30"
    }
  ]
}
```

## 错误响应

所有接口在出错时返回统一格式：

```json
{
  "ok": false,
  "error": "错误类型",
  "message": "详细错误信息"
}
```

### 常见错误码

| HTTP 状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 400 | bad_request | 请求参数错误 |
| 404 | not_found | 资源不存在 |
| 500 | internal_error | 服务器内部错误 |

### 错误示例

```json
{
  "ok": false,
  "error": "validation_error",
  "message": "project_count 必须在 1-10 之间"
}
```

## 使用示例

### 使用 curl 调用 API

#### 1. 创建任务
```bash
curl -X POST http://127.0.0.1:8765/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"frequency": "daily", "project_count": 5}'
```

#### 2. 生成候选项目
```bash
curl -X POST http://127.0.0.1:8765/api/jobs/GH-HOTLIST-20260610-001/candidates
```

#### 3. 确认项目选择
```bash
curl -X POST http://127.0.0.1:8765/api/jobs/GH-HOTLIST-20260610-001/selection \
  -H "Content-Type: application/json" \
  -d '{
    "selected": [
      {"rank": 1, "name": "project-1", "owner": "owner-1"},
      {"rank": 2, "name": "project-2", "owner": "owner-2"}
    ]
  }'
```

#### 4. 查看任务状态
```bash
curl http://127.0.0.1:8765/api/jobs/GH-HOTLIST-20260610-001
```

#### 5. 下载最终视频
```bash
curl -O http://127.0.0.1:8765/api/jobs/GH-HOTLIST-20260610-001/artifacts/final.mp4
```

### 使用 Python 调用 API

```python
import httpx

base_url = "http://127.0.0.1:8765"

# 创建任务
response = httpx.post(f"{base_url}/api/jobs", json={
    "frequency": "daily",
    "project_count": 5
})
job_id = response.json()["job_id"]

# 生成候选项目
response = httpx.post(f"{base_url}/api/jobs/{job_id}/candidates")
candidates = response.json()["candidates"]

# 确认项目选择
response = httpx.post(f"{base_url}/api/jobs/{job_id}/selection", json={
    "selected": [
        {"rank": 1, "name": candidates[0]["name"], "owner": candidates[0]["owner"]}
    ]
})

# 查看任务状态
response = httpx.get(f"{base_url}/api/jobs/{job_id}")
job = response.json()
print(f"任务状态: {job['status']}")
```

## WebSocket (未实现)

未来可能支持 WebSocket 实现实时任务进度推送。
