"""MinerU one-click deployment pipeline.

Goals:
- target machine needs no Python / uv / git; this program downloads them;
- every step is idempotent: finished steps are skipped, safe to re-run;
- China-friendly network: pip mirrors, GitHub proxies, ModelScope models;
- detects NVIDIA GPU + driver CUDA version and installs matching CUDA torch;
- writes launcher config so minerU-gui.exe works immediately.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import common as C

MINERU_SPEC = "mineru[torch]>=4.0,<5"

PYTHON_MIRRORS = [
    "",
    "https://ghproxy.net/https://github.com/astral-sh/python-build-standalone/releases/download",
    "https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone/releases/download",
]

TORCH_INDEX = "https://download.pytorch.org/whl/{tag}"


class StepError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class Options:
    root: Path
    with_models: bool = True
    mirror: str | None = None
    force: bool = False
    start_console: bool = False
    uv_cache: Path | None = None


@dataclass
class Context:
    opt: Options
    log: Callable[[str], None]
    cancel: threading.Event
    uv: Path | None = None
    mirror: str = ""
    gpu: dict = field(default_factory=dict)
    cuda_ok: bool = False
    python: Path | None = None
    steps_done: list[str] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.opt.root

    @property
    def cache_dir(self) -> Path:
        return self.opt.uv_cache or (self.root / ".uv" / "cache")

    @property
    def venv_python(self) -> Path:
        return self.root / ".venv" / "Scripts" / "python.exe"

    @property
    def kit(self) -> Path:
        return self.root / ".venv" / "Scripts" / "mineru-kit.exe"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"


def _run(ctx: Context, cmd: list[str], env_extra: dict | None = None,
         timeout: float = 3600, tail: int = 30) -> str:
    if ctx.cancel.is_set():
        raise C.Cancelled()
    ctx.log(">> " + " ".join(cmd))
    env = C.child_env(env_extra)

    def line(text: str) -> None:
        if text.strip():
            ctx.log("   " + text[:2000])

    code, out = C.run(cmd, cwd=ctx.root, env=env, on_line=line, cancel=ctx.cancel, timeout=timeout)
    if ctx.cancel.is_set():
        raise C.Cancelled()
    if code != 0:
        raise StepError(f"命令执行失败（退出码 {code}）", "\n".join(out.splitlines()[-tail:]))
    return out


# ---------------------------------------------------------------- steps
def step_system(ctx: Context) -> None:
    if not C.is_windows_64():
        raise StepError("仅支持 64 位 Windows", "当前系统不被支持。")
    ctx.log("系统：" + C.windows_version())
    free = C.disk_free_gb(ctx.root)
    ctx.log(f"目标盘可用空间：{free:.1f} GB")
    if free < 12:
        raise StepError(f"磁盘空间不足（剩余 {free:.1f} GB）", "建议至少预留 15 GB。")
    ctx.gpu = C.nvidia_smi_map()
    if ctx.gpu:
        ctx.log(f"显卡：{ctx.gpu.get('gpu_name')}，驱动 CUDA {ctx.gpu.get('cuda_version', '未知')}")
    else:
        ctx.log("未检测到 NVIDIA 显卡，将使用 CPU 推理（速度较慢）")


def step_dirs(ctx: Context) -> None:
    for d in (ctx.root, ctx.root / "bin", ctx.root / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    ctx.log("安装目录：" + str(ctx.root))


def _find_uv(ctx: Context) -> Path | None:
    cand = shutil.which("uv")
    if cand:
        return Path(cand)
    local = ctx.root / "bin" / "uv.exe"
    if local.exists():
        return local
    return None


def _download_uv(ctx: Context) -> Path:
    index = ctx.mirror.rstrip("/") + "/uv/"
    ctx.log("从镜像获取 uv：" + index)
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(index, headers={"User-Agent": "MinerU-Installer"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    hrefs = re.findall(r'href="([^"]*uv-[0-9][0-9.]*-py3-none-win_amd64\.whl[^"]*)"', html)
    if not hrefs:
        raise StepError("镜像中未找到 uv 的 Windows wheel", "请检查网络或换一个镜像。")
    pairs: list[tuple[list[int], str, str]] = []
    for href in hrefs:
        m = re.search(r"uv-([0-9][0-9.]*)-py3-none-win_amd64\.whl", href)
        if not m:
            continue
        url = urllib.parse.urljoin(index, href.split("#")[0])
        pairs.append(([int(x) for x in re.findall(r"\d+", m.group(1))], url, m.group(1)))
    if not pairs:
        raise StepError("解析 uv 下载地址失败", "")
    pairs.sort(key=lambda p: p[0])
    _, url, version = pairs[-1]
    whl = ctx.root / "bin" / "uv.whl"
    ctx.log(f"下载 uv {version} …")
    C.download(url, whl)
    target = ctx.root / "bin" / "uv.exe"
    with zipfile.ZipFile(whl) as zf:
        member = next((n for n in zf.namelist() if n.lower().endswith("uv.exe")), None)
        if member is None:
            raise StepError("uv wheel 中未找到 uv.exe", "")
        with zf.open(member) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    whl.unlink(missing_ok=True)
    ctx.log("uv 已就绪：" + str(target))
    return target


def step_uv(ctx: Context) -> None:
    if not ctx.mirror:
        ctx.mirror = ctx.opt.mirror or C.pick_mirror()
        ctx.log("使用镜像：" + ctx.mirror)
    uv = _find_uv(ctx)
    if uv is None:
        uv = _download_uv(ctx)
    code, out = C.run([str(uv), "--version"], cancel=ctx.cancel, timeout=60,
                      env=C.child_env({"UV_CACHE_DIR": str(ctx.cache_dir)}))
    if code != 0:
        raise StepError("uv 无法运行", out[-800:])
    ctx.log(out.strip())
    ctx.uv = uv


def step_python(ctx: Context) -> None:
    assert ctx.uv
    caches = [ctx.cache_dir]
    fallback = ctx.root / ".uv" / "cache"
    if fallback.resolve() != ctx.cache_dir.resolve():
        caches.append(fallback)  # uv 缓存被锁/只读时回退到安装目录内缓存

    last_err = ""
    ok = False
    for cache in caches:
        env = C.child_env({
            "UV_PYTHON_INSTALL_DIR": str(ctx.root / ".uv" / "python"),
            "UV_CACHE_DIR": str(cache),
            "UV_HTTP_TIMEOUT": "120",
        })
        for mirror in PYTHON_MIRRORS:
            if ctx.cancel.is_set():
                raise C.Cancelled()
            if mirror:
                env["UV_PYTHON_INSTALL_MIRROR"] = mirror
                ctx.log("尝试 Python 下载镜像：" + mirror.split("/")[2])
            code, out = C.run([str(ctx.uv), "python", "install", "3.12"],
                              env=env, on_line=lambda t: ctx.log("   " + t[:500]),
                              cancel=ctx.cancel, timeout=1800)
            if code == 0:
                ok = True
                break
            last_err = out
            ctx.log("该来源失败，换下一个镜像…")
        if ok:
            break
        ctx.log("当前缓存目录不可用，改用安装目录内缓存重试…")
    if not ok:
        raise StepError("Python 3.12 下载失败", last_err[-1200:])

    code, out = C.run([str(ctx.uv), "python", "find", "3.12"],
                      env=C.child_env({
                          "UV_PYTHON_INSTALL_DIR": str(ctx.root / ".uv" / "python"),
                          "UV_CACHE_DIR": str(ctx.cache_dir),
                      }),
                      cancel=ctx.cancel, timeout=120)
    path = out.strip().splitlines()[-1] if out.strip() else ""
    if code != 0 or not path:
        raise StepError("未找到已安装的 Python 3.12", out[-500:])
    ctx.python = Path(path)
    ctx.log("Python：" + path)


def step_venv(ctx: Context) -> None:
    assert ctx.uv
    venv = ctx.root / ".venv"
    if ctx.venv_python.exists() and not ctx.opt.force:
        code, out = C.run([str(ctx.venv_python), "-c", "import sys;print(sys.version_info[:2])"],
                          cancel=ctx.cancel, timeout=120)
        if code == 0 and "(3, 12)" in out:
            ctx.log("虚拟环境已存在，跳过创建")
            return
    env = C.child_env({
        "UV_PYTHON_INSTALL_DIR": str(ctx.root / ".uv" / "python"),
        "UV_CACHE_DIR": str(ctx.cache_dir),
    })
    _run(ctx, [str(ctx.uv), "venv", "--python", "3.12", str(venv)], env_extra=env, timeout=900)
    ctx.log("虚拟环境创建完成")


def step_mineru(ctx: Context) -> None:
    assert ctx.uv
    if not ctx.venv_python.exists():
        raise StepError("虚拟环境不可用", "请先完成创建虚拟环境。")
    if not ctx.opt.force:
        code, out = C.run([str(ctx.venv_python), "-c",
                           "import importlib.metadata as m;print(m.version('mineru'))"],
                          cancel=ctx.cancel, timeout=180)
        if code == 0 and out.strip():
            ctx.log("已安装 MinerU：" + out.strip())
            return
    env = {"UV_CACHE_DIR": str(ctx.cache_dir), "UV_HTTP_TIMEOUT": "180"}
    last = ""
    for mirror in C.MIRRORS:
        if ctx.cancel.is_set():
            raise C.Cancelled()
        ctx.log("使用镜像安装依赖：" + mirror)
        code, out = C.run(
            [str(ctx.uv), "pip", "install", "-U", MINERU_SPEC,
             "--python", str(ctx.venv_python), "-i", mirror],
            env=C.child_env(env), on_line=lambda t: ctx.log("   " + t[:800]),
            cancel=ctx.cancel, timeout=7200,
        )
        if code == 0:
            ctx.log("MinerU 安装完成")
            return
        last = out
        ctx.log("安装失败，尝试下一个镜像…")
    raise StepError("MinerU 安装失败", last[-1500:])


def step_cuda(ctx: Context) -> None:
    if not ctx.gpu:
        ctx.log("无 NVIDIA 显卡，使用 CPU 版 PyTorch")
        ctx.cuda_ok = False
        return
    if not ctx.venv_python.exists():
        raise StepError("虚拟环境不可用", "")

    def torch_version() -> str:
        code, out = C.run([str(ctx.venv_python), "-c",
                           "import torch;print(torch.__version__)"], cancel=ctx.cancel, timeout=300)
        return out.strip() if code == 0 else ""

    def cuda_available() -> bool:
        code, out = C.run([str(ctx.venv_python), "-c",
                           "import torch;print(torch.cuda.is_available())"], cancel=ctx.cancel, timeout=600)
        return code == 0 and "True" in out

    ver = torch_version()
    ctx.log("当前 PyTorch：" + (ver or "未安装"))
    if "+cu" in ver and cuda_available():
        ctx.cuda_ok = True
        ctx.log("PyTorch 已是 CUDA 版且可用，跳过")
        return

    primary = C.torch_index_for(ctx.gpu.get("cuda_version"))
    tags: list[str] = []
    for t in (primary, "cu128", "cu126"):
        if t not in tags:
            tags.append(t)
    last = ""
    for tag in tags:
        if ctx.cancel.is_set():
            raise C.Cancelled()
        ctx.log(f"安装 CUDA 版 PyTorch（{tag}）…")
        code, out = C.run(
            [str(ctx.uv), "pip", "install", "--reinstall", "--index-strategy", "unsafe-best-match",
             "--index-url", TORCH_INDEX.format(tag=tag), "--extra-index-url", ctx.mirror,
             "torch", "torchvision", "--python", str(ctx.venv_python)],
            env=C.child_env({"UV_CACHE_DIR": str(ctx.cache_dir)}),
            on_line=lambda t: ctx.log("   " + t[:800]), cancel=ctx.cancel, timeout=7200,
        )
        if code != 0:
            last = out
            continue
        if cuda_available():
            ctx.cuda_ok = True
            ctx.log(f"CUDA 版 PyTorch 就绪（{tag}，{torch_version()}）")
            return
        last = out
    ctx.log("警告：GPU 加速不可用，将回退 CPU 推理")
    if last:
        ctx.log(last[-600:])


def _write_mineru_config(ctx: Context) -> None:
    # 配置放在安装目录内（MINERU_HOME），不写用户目录：绿色、可迁移、无需管理员
    home = ctx.root / ".mineru"
    home.mkdir(parents=True, exist_ok=True)
    cfg = home / "config.yaml"
    text = "model:\n  source: modelscope\n  base_dir: " + str(ctx.models_dir) + "\n"
    cfg.write_text(text, encoding="utf-8")
    ctx.log("文件配置：" + str(cfg))


def step_models(ctx: Context) -> None:
    if not ctx.opt.with_models:
        ctx.log("按选择跳过模型下载（minerU-gui 首次使用时会提示）")
        return
    if not ctx.kit.exists():
        raise StepError("mineru-kit 不存在", "请先完成 MinerU 安装。")
    _write_mineru_config(ctx)
    env = C.child_env({
        "MINERU_HOME": str(ctx.root / ".mineru"),
        "MODELSCOPE_CACHE": str(ctx.root / ".cache" / "modelscope"),
        "HF_HOME": str(ctx.root / ".cache" / "hf"),
        "MINERU_MODEL_SOURCE": "modelscope",
    })
    code, out = C.run(
        [str(ctx.kit), "models", "verify", "--tier", "standard",
         "--small-backend", "torch", "--vlm-engine", "llama-cpp"],
        cancel=ctx.cancel, timeout=600, env=env,
    )
    if code == 0 and "正常" in out:
        ctx.log("模型已就绪，跳过下载")
        return
    ctx.log("开始下载模型（约 2 GB，首次较慢）…")
    code, out = C.run(
        [str(ctx.kit), "models", "download", "--tier", "standard",
         "--small-backend", "torch", "--vlm-engine", "llama-cpp"],
        env=env, on_line=lambda t: ctx.log("   " + t[:800]), cancel=ctx.cancel, timeout=7200,
    )
    if code != 0:
        raise StepError("模型下载失败", out[-1500:])
    ctx.log("模型下载完成")


def step_webapp(ctx: Context) -> None:
    src = C.bundle_dir() / "webapp"
    dst = ctx.root / "webapp"
    if not (src / "server.py").exists():
        ctx.log("未内置操作台资源，跳过（不影响命令行解析）")
        return
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src / "static", dst / "static", dirs_exist_ok=True)
    shutil.copy2(src / "server.py", dst / "server.py")
    for extra in ("README-部署说明.md", "DSH-集成说明.md"):
        cand = C.bundle_dir() / "docs" / extra
        if cand.exists():
            shutil.copy2(cand, ctx.root / extra)
    _write_scripts(ctx)
    ctx.log("本地操作台已部署：" + str(dst))


def _write_scripts(ctx: Context) -> None:
    root = str(ctx.root)
    kit = root + r"\.venv\Scripts\mineru-kit.exe"
    py = root + r"\.venv\Scripts\python.exe"
    env_lines = (
        'set "MINERU_HOME=' + root + r'\.mineru"' + "\r\n"
        'set "MODELSCOPE_CACHE=' + root + r'\.cache\modelscope"' + "\r\n"
        'set "HF_HOME=' + root + r'\.cache\hf"' + "\r\n"
        'set "MINERU_ROOT=' + root + '"' + "\r\n"
        'set "PYTHONIOENCODING=utf-8"' + "\r\n"
    )
    files = {
        "bin\\mineru-kit.cmd": (
            "@echo off\r\nrem MinerU launcher (auto env)\r\n"
            "setlocal\r\n"
            'set "MINERU_ROOT=' + root + '"' + "\r\n"
            'set "MINERU_HOME=' + root + r'\.mineru"' + "\r\n"
            'set "MODELSCOPE_CACHE=' + root + r'\.cache\modelscope"' + "\r\n"
            'set "HF_HOME=' + root + r'\.cache\hf"' + "\r\n"
            '"' + kit + '" %*\r\nendlocal\r\n'
        ),
        "start-console.cmd": (
            "@echo off\r\ncd /d " + root + "\r\n" + env_lines +
            '"' + py + '" "' + root + r'\webapp\server.py"' + "\r\npause\r\n"
        ),
        "start-webui.cmd": (
            "@echo off\r\ncd /d " + root + "\r\n" + env_lines +
            '"' + kit + '" webui --server-name 127.0.0.1 --server-port 7860\r\npause\r\n'
        ),
        "start-api.cmd": (
            "@echo off\r\ncd /d " + root + "\r\n" + env_lines +
            '"' + kit + '" api-server --host 127.0.0.1 --port 8000 --tier standard\r\npause\r\n'
        ),
        "stop-webui.cmd": (
            '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "' + root + r'\bin\stop.ps1" -Target webui' + "\r\npause\r\n"
        ),
        "stop-console.cmd": (
            '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "' + root + r'\bin\stop.ps1" -Target console' + "\r\npause\r\n"
        ),
        "stop-all.cmd": (
            '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "' + root + r'\bin\stop.ps1" -Target all' + "\r\npause\r\n"
        ),
    }
    for name, content in files.items():
        (ctx.root / name).write_text(content, encoding="utf-8", newline="")
    stop_src = C.bundle_dir() / "scripts" / "stop.ps1"
    if stop_src.exists():
        shutil.copy2(stop_src, ctx.root / "bin" / "stop.ps1")
    ctx.log("启动/停止脚本已生成")


def step_finish(ctx: Context) -> None:
    _write_mineru_config(ctx)
    env = C.child_env({"MINERU_HOME": str(ctx.root / ".mineru")})
    if ctx.kit.exists():
        code, out = C.run([str(ctx.kit), "--version"], cancel=ctx.cancel, timeout=300, env=env)
        if code == 0:
            ctx.log("版本：" + out.strip().replace("\n", " | "))
    code, out = C.run([str(ctx.venv_python), "-c",
                       "import importlib.metadata as m;print('mineru', m.version('mineru'))"],
                      cancel=ctx.cancel, timeout=300)
    if code != 0:
        raise StepError("MinerU 导入失败", out[-800:])
    manifest = {
        "app": "minerU-gui",
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(ctx.root),
        "python": str(ctx.venv_python),
        "gpu": ctx.gpu.get("gpu_name", ""),
        "cuda_ok": ctx.cuda_ok,
        "with_models": ctx.opt.with_models,
        "ports": C.DEFAULT_PORTS,
    }
    (ctx.root / ".mineru-install.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = C.load_config()
    cfg.update({"root": str(ctx.root), "ports": C.DEFAULT_PORTS,
                "installed_at": manifest["installed_at"]})
    C.save_config(cfg)
    try:
        (ctx.root / ".mineru-gui.json").write_text(
            json.dumps({"root": str(ctx.root), "ports": C.DEFAULT_PORTS},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    ctx.log("完成：minerU-gui.exe 现在即可直接使用")


STEPS: list[tuple[str, str, Callable[[Context], None]]] = [
    ("system", "检查系统环境", step_system),
    ("dirs", "准备安装目录", step_dirs),
    ("uv", "准备 uv 工具", step_uv),
    ("python", "下载 Python 3.12", step_python),
    ("venv", "创建虚拟环境", step_venv),
    ("mineru", "安装 MinerU 与依赖", step_mineru),
    ("cuda", "配置 CUDA 版 PyTorch", step_cuda),
    ("models", "下载并校验模型", step_models),
    ("webapp", "部署本地操作台", step_webapp),
    ("finish", "写入配置并校验", step_finish),
]


def run_pipeline(ctx: Context, on_step: Callable[[str, str], None] | None = None) -> None:
    for key, title, fn in STEPS:
        if ctx.cancel.is_set():
            raise C.Cancelled()
        if on_step:
            on_step(key, "start")
        ctx.log("\n=== " + title + " ===")
        fn(ctx)
        ctx.steps_done.append(key)
        if on_step:
            on_step(key, "done")


def plan(ctx: Context) -> list[dict]:
    return [{"key": k, "title": t} for k, t, _ in STEPS]
