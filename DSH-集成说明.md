# MinerU 本地部署 · DeepSeek Harness 集成说明

> 面向对象：以后在本机运行的 DeepSeek Harness 会话（或任何自动化代理）。
> 目的：不用重新部署、不用查文档，照本文即可调用本地 MinerU 解析文档。

## 0. 一句话结论

| 你要做的事 | 用哪种方式 |
| --- | --- |
| 解析 1 个文件，拿到 Markdown | **CLI**：`E:\MinerU\bin\mineru-kit.cmd parse ...` |
| 程序化/批量/需要进度与结果 JSON | **HTTP API**：`http://127.0.0.1:7861`（本地操作台） |
| 在 Python 脚本里内嵌 | **SDK**：`from mineru import parse`（用 `E:\MinerU\.venv` 的解释器） |

机器可读摘要：

```json
{
  "tool": "MinerU 4.0.12",
  "os": "Windows 11",
  "python": "E:\\MinerU\\.venv\\Scripts\\python.exe (3.12.15)",
  "cli": "E:\\MinerU\\bin\\mineru-kit.cmd",
  "cli_exe": "E:\\MinerU\\.venv\\Scripts\\mineru-kit.exe",
  "api_base": "http://127.0.0.1:7861",
  "webui_gradio": "http://127.0.0.1:7860 (需 start-webui.cmd)",
  "models_dir": "E:\\MinerU\\models",
  "gpu": "NVIDIA RTX 3070 8GB (CUDA torch + llama.cpp Vulkan)",
  "required_env": {
    "MODELSCOPE_CACHE": "E:\\MinerU\\.cache\\modelscope",
    "HF_HOME": "E:\\MinerU\\.cache\\hf"
  }
}
```

## 1. 调用前必须做的事

### 1.1 设置两个环境变量（重要）

```powershell
$env:MODELSCOPE_CACHE = 'E:\MinerU\.cache\modelscope'
$env:HF_HOME = 'E:\MinerU\.cache\hf'
```

原因：本机针对 `C:\Users\<user>\.cache` 的写入会被系统拒绝（`WinError 5 拒绝访问`），只有把缓存指到 `E:\MinerU\.cache` 才能稳定运行。使用 `E:\MinerU\bin\mineru-kit.cmd` 时会自动设置，直接调 `.exe` 时必须自己设。

### 1.2 确认服务状态（仅 HTTP API 需要）

```powershell
curl.exe -s http://127.0.0.1:7861/api/health
# 期望: {"ok": true, "version": "4.0.12", "gpu": "NVIDIA GeForce RTX 3070, 8192 MiB", ...}
```

未启动则先运行 `E:\MinerU\start-console.cmd`（或后台执行 `E:\MinerU\.venv\Scripts\python.exe E:\MinerU\webapp\server.py`）。

## 2. 方式 A：命令行（最省事）

```powershell
# 单文件 → 指定 Markdown 输出
& 'E:\MinerU\bin\mineru-kit.cmd' parse 'D:\docs\paper.pdf' -o 'D:\out\paper.md' --tier standard

# 单文件 → 输出到目录（生成 <stem>.md）
& 'E:\MinerU\bin\mineru-kit.cmd' parse 'D:\docs\paper.pdf' -o 'E:\MinerU\out\paper' --tier standard

# 整个目录 → 打包
& 'E:\MinerU\bin\mineru-kit.cmd' parse 'D:\docs' -o 'D:\out' --format zip
```

规则与要点：

- `--tier`：PDF/图片可用 `flash` / `basic` / `standard` / `advanced`；Office（docx/pptx/xlsx）、HTML、EPUB 等固定走 `flash`，传其他档位会报错。
- 完成判据：进程退出码 0 且输出目录出现 `.md` 文件。中间日志里的 `已解析 1 个输入。` 也可作为完成信号。
- 输出 Markdown 中的图片是 **base64 data URI**（内嵌），单文件即可完整预览；需要独立图片文件时用 ZIP 输出。
- 每次调用都会重新加载模型，冷启动约 5~20 秒（受系统后台负载影响），单页 `standard` 推理约 7~10 秒。
- 中文路径可用，已实测通过。

## 3. 方式 B：HTTP API（推荐给程序调用）

Base URL：`http://127.0.0.1:7861`，所有接口均为 JSON（上传除外）。

### 3.1 端点一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/upload` | `multipart/form-data`，字段 `file`；返回 `{file_id, name, size}`；单文件 ≤200MB |
| POST | `/api/tasks` | 表单字段 `file_id`、`tier`；返回 `{task_id}`，立即返回、后台解析 |
| GET | `/api/tasks/{task_id}` | 任务状态；`status=done` 时附带 `markdown` 全文 |
| GET | `/api/tasks/{task_id}/download` | 下载 .md 附件 |
| GET | `/api/tasks/{task_id}/zip` | 下载整个输出目录 ZIP |
| POST | `/api/tasks/{task_id}/cancel` | 取消运行中的任务 |
| GET | `/api/history` | 最近 12 个任务摘要 |
| GET | `/api/health` | 服务与 GPU 信息 |
| GET | `/api/config` | 可用档位、大小限制 |
| POST | `/api/demo` | 表单字段 `tier`；解析内置示例文档，返回 `{task_id}` |

### 3.2 任务对象（`GET /api/tasks/{id}` 返回）

```json
{
  "id": "61418ff64960",
  "name": "论文.pdf",
  "tier": "standard",
  "status": "running",          // queued | running | done | error | cancelled
  "phase": "OCR 检测",           // 中文阶段名：加载模型/版面分析/公式识别/OCR 检测/VLM 推理/完成
  "percent": 100,
  "elapsed": 12.3,              // 秒
  "error": null,                // status=error 时是错误信息 + 日志尾部
  "log": ["...", "..."],        // 最近 60 行日志
  "created": 1793036900.03,
  "markdown": "..."             // 仅 status=done 时出现
}
```

### 3.3 轮询建议

- 间隔 1~1.5 秒；`status in (done, error, cancelled)` 时停止。
- 服务端默认单任务串行（内置锁），并发提交会排队，不会爆显存。
- 服务端超时默认 1800 秒，可用环境变量 `MINERU_CONSOLE_TIMEOUT` 调整。
- 上传支持中文文件名，返回的 `name` 即原始文件名；任务输出与历史记录都用该名字。

### 3.4 完整调用示例（PowerShell，可直接复制）

```powershell
$up = curl.exe -s -F "file=@D:\docs\paper.pdf" http://127.0.0.1:7861/api/upload | ConvertFrom-Json
$task = curl.exe -s -F "file_id=$($up.file_id)" -F "tier=standard" http://127.0.0.1:7861/api/tasks | ConvertFrom-Json
$id = $task.task_id
do {
  Start-Sleep -Seconds 1
  $d = curl.exe -s "http://127.0.0.1:7861/api/tasks/$id" | ConvertFrom-Json
} while ($d.status -notin @('done','error','cancelled'))
$d.markdown > D:\out\paper.md
```

## 4. 方式 C：Python SDK

```python
# 解释器必须是 E:\MinerU\.venv\Scripts\python.exe
from mineru import parse
result = parse(r"D:\docs\paper.pdf", tier="standard")
print(result.markdown)
```

## 5. 硬性注意事项（违反会出错）

1. **不要并发解析**。RTX 3070 只有 8GB 显存，两个 VLM 实例同时加载会 OOM；API 已串行化，CLI 请自己排队。
2. **缓存必须指向工作区**（见 1.1），否则模型下载/加载会因 `C:\Users\<user>\.cache` 写入被拒而失败。
3. **Office/HTML/EPUB 文件强制 flash 档位**，不要对它们传 `standard`，会报 `quality_tier_unavailable` 一类错误。API 端会自动降级为 flash，CLI 端不会。
4. **每个 CLI 进程都会加载一次模型**：批量处理大目录时用一次目录解析命令，而不是循环调用单文件命令。
5. 输出 `.md` 可能很大（扫描页图片为 base64 内嵌），读取时避免一次性塞进上下文；需要时先取 `markdown` 长度或只取前若干字符。
6. 服务端口：操作台 `7861`；原版 Gradio WebUI `7860`（仅在需要时启动）。两者可同时运行，但会争抢显存，解析前建议只保留一个。
7. 纯文本文件（.txt/.md）不需要走 MinerU，直接读取即可。

## 6. 健康检查与排障

```powershell
curl.exe -s http://127.0.0.1:7861/api/health          # 服务 + GPU
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
& 'E:\MinerU\.venv\Scripts\mineru-kit.exe' models verify --tier standard --small-backend torch --vlm-engine llama-cpp
Get-Content E:\MinerU\webapp\server.log -Tail 30        # 操作台日志
```

| 现象 | 原因 / 处理 |
| --- | --- |
| `WinError 5 拒绝访问: C:\Users\...\.cache` | 未设置 `MODELSCOPE_CACHE`/`HF_HOME`（见 1.1） |
| 解析卡住、`status=running` 很久 | 后台程序占满 GPU（浏览器/游戏/视频渲染）；关掉后重试 |
| `quality_tier_unavailable` | 对 Office/HTML 传了非 flash 档位 |
| API 连接被拒 | 操作台未启动；运行 `start-console.cmd` |
| 想释放显存 | 停止操作台/CLI 进程即可，模型不常驻 |

## 7. 相关文件

| 文件 | 作用 |
| --- | --- |
| `E:\MinerU\README-部署说明.md` | 部署概览、目录结构、升级方式 |
| `E:\MinerU\webapp\server.py` | 操作台后端（FastAPI，端口 7861） |
| `E:\MinerU\webapp\static\` | 操作台与教程页面 |
| `E:\MinerU\webapp\data\outputs\<task_id>\` | 每个任务的输出与 `meta.json` |
| `E:\MinerU\start-console.cmd` | 启动操作台 |
| `E:\MinerU\start-webui.cmd` / `start-api.cmd` | 启动原版 WebUI / V1 API |
| `E:\MinerU\stop-webui.cmd` / `stop-console.cmd` / `stop-all.cmd` | 停止对应服务（结束端口进程树） |
