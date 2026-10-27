# MinerU 4.0 本地部署说明

> 配套文档：[DSH-集成说明.md](DSH-集成说明.md)（给 DeepSeek Harness / 自动化程序调用参考）

## 一、部署环境

| 项目 | 内容 |
| --- | --- |
| 操作系统 | Windows 11（i7-12700KF + RTX 3070 8GB） |
| 显卡驱动 | 616.56（CUDA 13.4 UMD），RTX 3070 已启用 GPU 加速 |
| Python | 3.12.15（由 uv 管理，位于 `.venv`） |
| MinerU | 4.0.12（`mineru[torch]` 安装方式） |
| PyTorch | 2.14.1+cu130（CUDA 13.0 编译，`torch.cuda.is_available()=True`） |
| 小模型后端 | torch / CUDA（版面、OCR、表格、公式） |
| VLM 引擎 | llama.cpp（自带 Vulkan 后端，模型加载进显存推理） |
| 模型 | 约 2.0 GB，来源 ModelScope，已校验就绪，可离线使用 |

实测：单页 A4、standard 档位，空载系统约 7~10 秒；GPU 显存峰值约 4.7 GB，利用率可达 70%+。

## 二、目录结构

```
E:\MinerU
├─ .venv\                     Python 3.12 虚拟环境（约 3.5 GB）
├─ models\                    模型文件（约 2.0 GB）
│  ├─ MinerU-4_models_torch\  小模型：版面/OCR/表格/公式
│  └─ MinerU2.5-Pro-2605-1.2B-GGUF\  VLM 主模型 + mmproj（llama.cpp）
├─ .cache\                    下载缓存（复用可加速后续下载）
├─ webapp\                    本地操作台（FastAPI + 仿官网页面）
│  ├─ server.py               后端，端口 7861
│  ├─ static\                 工作台 / 使用教程页面
│  └─ data\                   上传与解析结果（outputs/<任务ID>/）
├─ bin\mineru-kit.cmd         命令行封装（自动设置缓存目录）
├─ start-console.cmd          一键启动本地操作台（7861）
├─ start-webui.cmd            一键启动原版 Gradio WebUI（7860）
├─ start-api.cmd              一键启动 V1 HTTP API（8000）
├─ test\                      测试样例（含示例 PDF 与解析结果）
└─ torchinductor_wu359\       PyTorch 编译缓存（可删）
```

配置固定在 `C:\Users\wu359\.mineru\config.yaml`：

```yaml
model:
  source: modelscope        # 模型下载源：ModelScope（国内快）
  base_dir: E:\MinerU\models
```

## 三、三种使用入口

### 1）本地操作台（推荐，仿 MinerU 官网布局）

双击 `start-console.cmd`，浏览器打开 **http://127.0.0.1:7861**

![工作台](webapp/shot_index.png)

- 左侧：上传 / 档位选择 / 实时进度与日志 / 最近任务
- 右侧：Markdown 预览、源码、下载 .md 或 ZIP
- 支持 `/?task=<任务ID>` 直接打开历史结果

另有互动教程页：**http://127.0.0.1:7861/guide**（含一键示例解析、命令行与 API 示例、常见问题）：

![使用教程](webapp/shot_guide.png)

### 2）命令行

```bat
rem 单文件
E:\MinerU\bin\mineru-kit.cmd parse D:\docs\paper.pdf -o D:\out\paper.md --tier standard

rem 目录批量（输出必须是目录）
E:\MinerU\bin\mineru-kit.cmd parse D:\docs -o D:\out --format zip

rem 快速预览（不跑 VLM）
E:\MinerU\bin\mineru-kit.cmd parse D:\docs\scan.pdf -o D:\out\scan.md --tier flash
```

### 3）原版 WebUI / HTTP API

- 原版 Gradio WebUI：双击 `start-webui.cmd` → http://127.0.0.1:7860
- V1 HTTP API：双击 `start-api.cmd` → http://127.0.0.1:8000/docs

> 操作台与原版 WebUI 都会占用显存，建议只开一个；解析前如果 GPU 被其他程序（浏览器、游戏、视频渲染）占满，速度会明显变慢。

### 4）停止服务

| 要停止的 | 操作 |
| --- | --- |
| 原版 WebUI（7860） | 双击 `stop-webui.cmd` |
| 本地操作台（7861） | 双击 `stop-console.cmd` |
| V1 API（8000） | `powershell -File E:\MinerU\bin\stop.ps1 -Target api` |
| 全部 | 双击 `stop-all.cmd` |

脚本会找到占用端口的进程并连同子进程一起结束，最后提示端口是否已释放。直接关闭启动窗口（或按 Ctrl+C）通常也可以，但 MinerU 会派生多个子进程，关窗口有时残留、导致下次启动报端口占用——这时用上面的脚本清理即可。

### 5）图形化安装器与启动器（install-gui 项目）

为避免单文件 exe 解压临时目录失败（Defender 或临时目录受限时会报
`Could not create temporary directory`），两个程序已改为**目录版**：

| 程序 | 路径 |
| --- | --- |
| 安装器 | `E:\MinerU\minerU-install-gui\minerU-install-gui.exe` |
| 启动器 | `E:\MinerU\minerU-gui\minerU-gui.exe` |

直接双击对应目录里的 exe 即可，不要只拷贝 exe 文件（需要同目录的 `_internal` 文件夹）。源码与设计文档在 `install-gui\`。

- 首次运行会被 SmartScreen 拦截一次（未签名新程序）：点"更多信息 → 仍要运行"；也可运行本目录的 `解除阻止.cmd`。
- 若 Defender 反复扫描导致启动慢，可在 Windows 安全中心把 `E:\MinerU` 加入排除项（需管理员）。
- 每次重新构建会改变文件哈希，SmartScreen 可能再提示一次。

## 四、档位选择（RTX 3070 8GB）

| 档位 | 说明 | 速度（空闲机） |
| --- | --- | --- |
| `flash` | 只提取 PDF 原生文本层，不跑模型 | 约 1 秒/页 |
| `basic` | 小模型 OCR / 版面 / 表格 | 约 3 秒/页 |
| `standard` | 小模型 + VLM，质量最好（默认） | 约 8 秒/页 |
| `advanced` | 更多推理计算 | 约 15 秒/页 |

Office（docx/pptx/xlsx）、HTML、EPUB 等格式固定走 flash 快速通道。

## 五、维护与升级

停止服务后执行：

```bat
python -m uv pip install -U "mineru[torch]>=4.0,<5" --python E:\MinerU\.venv\Scripts\python.exe -i https://mirrors.aliyun.com/pypi/simple
```

若升级后 torch 被镜像换回 CPU 版（版本号带 `+cpu`），需重装 CUDA 版：

```bat
python -m uv pip install --python E:\MinerU\.venv\Scripts\python.exe --reinstall --index-strategy unsafe-best-match --index-url https://download.pytorch.org/whl/cu130 --extra-index-url https://mirrors.aliyun.com/pypi/simple "torch==2.14.1+cu130" "torchvision==0.29.1+cu130"
```

检查环境：

```bat
E:\MinerU\.venv\Scripts\mineru-kit.exe models verify --tier standard --small-backend torch --vlm-engine llama-cpp
```

## 六、注意事项

1. **缓存目录**：本机对 `C:\Users\wu359\.cache` 的写入受限，缓存已统一放到 `E:\MinerU\.cache`。请使用 `start-console.cmd`、`bin\mineru-kit.cmd` 等封装启动，它们会自动设置 `MODELSCOPE_CACHE` / `HF_HOME`。
2. **显存**：RTX 3070 为 8 GB，单任务解析约占用 4.7 GB；不要同时开多个解析任务。
3. **首次解析**：模型已下载并校验通过，无需联网即可解析。
4. **性能波动**：后台有游戏/视频渲染/Cherry Studio 等占用 GPU 时，模型加载和推理会明显变慢（实测可从 8 秒涨到 25~40 秒）。
