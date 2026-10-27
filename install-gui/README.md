# MinerU 一键部署 · 产品与工程说明

本目录包含两个 Windows 桌面程序：

| 程序 | 定位 | 目标用户 | 关键承诺 |
| --- | --- | --- | --- |
| `minerU-install-gui.exe` | **安装向导**：把“手工部署 MinerU”变成一次点击 | 第一次在某台机器上部署的人 | 开箱即用：不需要预装 Python / uv / git，不需要命令行 |
| `minerU-gui.exe` | **日常启动器**：像普通软件一样启动/停止本地 MinerU | 已经装好、每天使用的人 | 双击即用：自动定位安装、启动服务、打开浏览器、退出清理 |

## 一、产品设计（PM 视角）

### 1. 用户旅程

```
第一次使用                          之后每天使用
───────────                        ───────────
双击 minerU-install-gui.exe         双击 minerU-gui.exe
   ↓ 选择安装目录                        ↓ 自动定位安装目录
   ↓ 一键部署（进度/日志可见）            ↓ 自动启动本地操作台（7861）
   ↓ 自动装 Python/uv/依赖/CUDA torch   ↓ 自动打开浏览器
   ↓ 下载并校验模型（可选）              ↓ 需要时启动原版 WebUI（7860）
   ↓ 生成启动/停止脚本、写入配置          ↓ 退出时可选停止自己启动的服务
完成 → 提示可直接使用
```

### 2. 两个产品各自的“体验红线”

**安装向导**

1. **零前置条件**：目标机没有 Python、没有 pip、没有 uv 也能装。
2. **全程可见**：10 个步骤的状态灯 + 实时日志 + 取消按钮，失败时给出“哪一步、为什么、怎么办”。
3. **国内网络可完成**：pip 镜像自动探测（阿里云 → 清华 → 官方），Python 下载走 GitHub 代理镜像，模型走 ModelScope。
4. **幂等可重入**：已装过的步骤自动跳过，可以反复点“开始部署”做修复或补装。
5. **不污染系统**：安装到用户选择的目录，不装服务、不改 PATH、不需要管理员权限。
6. **装完即可用**：自动生成开始/停止脚本、写入用户配置，并可直接拉起操作台。

**日常启动器**

1. 双击就能用：找不到安装时引导选择目录，而不是报错退出。
2. 状态一目了然：操作台 / 原版 WebUI 的端口、运行状态。
3. 不留下“僵尸端口”：退出时可停止自己启动的进程树（`taskkill /T`），下次启动不会端口冲突。
4. 与安装器解耦：只依赖 `MINERU_ROOT` 与安装清单，安装目录可移动（移动后重新选择一次即可）。

### 3. 界面信息架构

安装向导：标题区（产品名 + 一句话价值）→ 安装选项（目录 / 是否下载模型 / 是否启动）→ 部署进度（10 步状态灯）→ 运行日志（等宽字体、自动滚动）→ 底部（开始 / 取消 / 打开目录）。

启动器：标题区（产品名 + 安装路径）→ 两张服务卡片（操作台 / 原版 WebUI：状态灯、地址、启动/停止/打开）→ 快捷入口（教程 / 安装目录 / 日志）→ 选项（退出时停止、启动后开浏览器）→ 运行状态日志。

## 二、兼容性设计（资深程序员视角）

| 维度 | 处理方式 |
| --- | --- |
| 操作系统 | Windows 10 1809+ / Windows 11，仅 64 位；启动时校验 |
| Python | 不依赖系统 Python：安装器自带 uv，uv 下载 Python 3.12 到安装目录 |
| 权限 | 全程普通用户权限，不使用 MSI/注册表；配置写 `%LOCALAPPDATA%\MinerU\gui.json` |
| 路径 | 支持空格、中文、非系统盘；所有子进程用参数列表调用，不经过 `cmd /c` 拼接 |
| 编码 | 子进程统一 `PYTHONUTF8=1 / PYTHONIOENCODING=utf-8`，读取输出按 UTF-8 → GBK 回退 |
| GPU | 自动识别 NVIDIA 显卡与驱动 CUDA 版本：13.x → cu130，12.8+ → cu128，其余 → cu126；无 GPU 时自动降级 CPU 并提示 |
| 网络 | pip 镜像自动探测；Python 下载多镜像回退；模型固定 ModelScope（国内可直连） |
| 已有安装 | 通过 `.venv`、模型目录、`minerU-kit` 探测，已就绪步骤自动跳过（幂等） |
| 卸载/迁移 | 删除安装目录即可；启动器支持重新选择目录并写回配置 |
| 长路径 | 全部使用 `pathlib` 与绝对路径，避免 260 字符问题 |
| 失败恢复 | 每步失败即停止并保留日志（`<安装目录>\logs\install.log`），重跑可续 |

## 三、工程结构

```
install-gui\
├─ src\
│  ├─ common.py           公共：路径/配置/进程/端口/下载/GPU 探测
│  ├─ deploy.py           部署流水线（10 步，幂等）
│  ├─ installer_main.py   安装向导 GUI（含 --dry-run 无界面模式）
│  └─ launcher_main.py    启动器 GUI（含 --check 无界面模式）
├─ assets\make_icon.py    构建期生成 icon.ico（需 Pillow）
├─ build\build.ps1        一键构建（PyInstaller onedir，免临时目录解压）
├─ dist\                  构建产物：dist\minerU-gui\、dist\minerU-install-gui\
└─ src\bundle\            构建时注入：操作台 webapp、文档、stop.ps1
```

构建：

```powershell
powershell -ExecutionPolicy Bypass -File E:\MinerU\install-gui\build\build.ps1
```

产物会复制到 `E:\MinerU\minerU-gui\` 与 `E:\MinerU\minerU-install-gui\`。**必须整个目录一起分发**（exe 依赖同目录 `_internal`），不要只拷 exe。

## 四、部署流水线（10 步）

1. 检查系统环境（版本、64 位、磁盘、GPU）
2. 准备安装目录
3. 准备 uv（PATH 中找不到就从镜像下载 wheel 并解出 uv.exe）
4. 下载 Python 3.12（uv 管理，多镜像回退）
5. 创建虚拟环境
6. 安装 `mineru[torch]`（镜像自动重试）
7. 配置 CUDA 版 PyTorch（按驱动 CUDA 版本选 whl 索引，验证 `torch.cuda.is_available()`）
8. 下载并校验模型（ModelScope；已就绪则跳过）
9. 部署本地操作台（webapp + 启动/停止脚本 + 文档）
10. 写入配置并校验（版本、导入、用户配置、安装清单）

## 五、首次运行与 SmartScreen

两个程序采用**目录版（onedir）**：启动时不释放临时文件，因此不会再出现
`Could not create temporary directory`（单文件版在 TEMP 受限或被 Defender 拦截时会报这个错）。

它们未做代码签名，Windows SmartScreen 会按“未知发布者”拦截一次：

1. 弹窗里点 **“更多信息”** → **“仍要运行”**；
2. 之后同一文件不再提示（按文件哈希记忆）；
3. 也可以用根目录的 `解除阻止.cmd` 解除文件锁定；
4. 若 Defender 反复扫描导致启动慢或误报，可在“Windows 安全中心 → 病毒和威胁防护 → 管理设置 → 排除项”里把 `E:\MinerU` 加入排除（需管理员）。

注意：**每次重新构建 exe 都会改变哈希，SmartScreen 可能再次提示一次**。交付时建议保持最终构建不再改动。

## 六、验收标准

- [ ] 干净机器（无 Python）双击安装器可完成部署
- [ ] 有 NVIDIA 卡时 `torch.cuda.is_available()` 为 True
- [ ] 模型校验输出“正常”
- [ ] 安装完成后 `minerU-gui.exe` 能启动操作台并打开浏览器
- [ ] 退出启动器后端口释放，再次启动无冲突
- [ ] 安装中断后重跑可继续（不重复下载已完成的组件）
- [ ] 安装到含空格/中文的路径下仍然可用

## 六、无界面模式（便于自动化）

```powershell
# 查看部署计划（不执行）
minerU-install-gui.exe --dry-run --out plan.json --root E:\MinerU

# 用已有 uv 缓存快速部署、跳过模型
minerU-install-gui.exe --root D:\MinerU-new --with-models false --uv-cache C:\Users\me\AppData\Local\uv\cache

# 启动器：输出当前状态
minerU-gui.exe --check --out status.json
```
