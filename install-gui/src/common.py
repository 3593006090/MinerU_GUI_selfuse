"""MinerU GUI 公共模块：路径、配置、进程与网络工具。

仅供 minerU-install-gui.exe / minerU-gui.exe 共享，纯标准库实现，
保证 PyInstaller 打包后无需任何第三方依赖。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

APP_NAME = "MinerU"
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "MinerU"
CONFIG_FILE = CONFIG_DIR / "gui.json"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_PORTS = {"console": 7861, "webui": 7860, "api": 8000}


# ---------------------------------------------------------------- 基础工具
def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """内置资源目录：冻结后为 _MEIPASS/bundle，源码运行时为 src/bundle。"""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", app_dir()))
    else:
        base = app_dir() / "src"
    cand = base / "bundle"
    return cand if cand.exists() else base


def is_windows_64() -> bool:
    return sys.platform == "win32" and sys.maxsize > 2**32


def windows_version() -> str:
    if sys.platform != "win32":
        return "非 Windows"
    ver = sys.getwindowsversion()
    return f"Windows {ver.major}.{ver.minor} build {ver.build}"


def disk_free_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(str(path)).free / (1024**3)
    except OSError:
        return 0.0


# ---------------------------------------------------------------- 配置
def load_config() -> dict:
    data: dict = {}
    # 1) 用户级配置（可选）
    try:
        data.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    # 2) 安装目录级配置（绿色、可迁移，优先级更高）
    try:
        data.update(json.loads((app_dir() / ".mineru-gui.json").read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return data


def save_config(data: dict) -> None:
    """尽力写配置：用户级失败时落盘到安装目录，二者都不致命。"""
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(payload, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        (app_dir() / ".mineru-gui.json").write_text(payload, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def valid_root(root: Path) -> bool:
    if not root:
        return False
    return (root / ".venv" / "Scripts" / "mineru-kit.exe").exists() or (root / "webapp" / "server.py").exists()


def resolve_root(cli_root: str | None = None) -> Path | None:
    """按优先级定位安装目录：命令行参数 → 用户配置 → exe 所在目录 → E:\\MinerU。"""
    candidates: list[Path] = []
    if cli_root:
        candidates.append(Path(cli_root))
    cfg = load_config().get("root")
    if cfg:
        candidates.append(Path(cfg))
    if is_frozen():
        candidates.append(app_dir())
        candidates.append(app_dir().parent)  # 目录版：exe 在 <root>\minerU-gui 下
    candidates.append(Path(r"E:\MinerU"))
    for c in candidates:
        if c and c.exists():
            c = c.resolve()
            if valid_root(c):
                return c
    return None


# ---------------------------------------------------------------- 运行命令
class Cancelled(Exception):
    pass


def kill_tree(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
    except Exception:  # noqa: BLE001
        pass


def decode_output(data: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    try:
        return data.decode("latin-1").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return data.decode("utf-8", errors="replace")


def child_env(extra: dict | None = None) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    if extra:
        env.update(extra)
    return env


def run(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
    on_line: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: float | None = None,
) -> tuple[int, str]:
    """执行命令并逐行回调；支持取消与超时。返回 (退出码, 合并输出)。"""
    proc = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd else None, env=env or child_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )
    lines: list[str] = []

    def reader() -> None:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.readline()
            if not chunk:
                break
            text = decode_output(chunk).rstrip("\r\n")
            if not text:
                continue
            lines.append(text)
            if on_line:
                try:
                    on_line(text)
                except Exception:  # noqa: BLE001
                    pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    start = time.time()
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            kill_tree(proc.pid)
            break
        if timeout and time.time() - start > timeout:
            kill_tree(proc.pid)
            break
        time.sleep(0.2)
    t.join(timeout=5)
    return proc.wait(), "\n".join(lines)


# ---------------------------------------------------------------- 网络
MIRRORS = [
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://pypi.org/simple",
]


def probe_mirror(mirror: str, timeout: float = 6.0) -> bool:
    try:
        req = urllib.request.Request(mirror.rstrip("/") + "/", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:  # noqa: BLE001
        return False


def pick_mirror(preferred: str | None = None) -> str:
    if preferred:
        return preferred
    for m in MIRRORS:
        if probe_mirror(m):
            return m
    return MIRRORS[0]


def download(url: str, dest: Path, on_progress: Callable[[int, int], None] | None = None,
             timeout: float = 60.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "MinerU-Installer"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with tmp.open("wb") as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    tmp.replace(dest)


# ---------------------------------------------------------------- GPU / 端口
def nvidia_smi_map() -> dict:
    """返回 {gpu_name, cuda_version, memory_mb}；无 NVIDIA 卡时为空 dict。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return {}
        line = decode_output(r.stdout).strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        info = {"gpu_name": parts[0], "memory_mb": 0}
        if len(parts) > 1 and parts[1].split()[0].isdigit():
            info["memory_mb"] = int(parts[1].split()[0])
        try:
            h = subprocess.run(["nvidia-smi"], capture_output=True, timeout=20,
                               creationflags=CREATE_NO_WINDOW)
            m = re.search(r"CUDA (?:UMD )?Version:\s*([\d.]+)", decode_output(h.stdout))
            if m:
                info["cuda_version"] = m.group(1)
        except Exception:  # noqa: BLE001
            pass
        return info
    except Exception:  # noqa: BLE001
        return {}


def torch_index_for(cuda_version: str | None) -> str:
    """按驱动 CUDA 版本选择 PyTorch 官方 wheel 索引。"""
    try:
        major_minor = [int(x) for x in (cuda_version or "12.8").split(".")[:2]]
    except ValueError:
        major_minor = [12, 8]
    if major_minor[0] >= 13:
        return "cu130"
    if major_minor[0] == 12 and major_minor[1] >= 8:
        return "cu128"
    return "cu126"


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port(port: int, seconds: float, cancel: threading.Event | None = None) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if port_open(port):
            return True
        if cancel is not None and cancel.is_set():
            return False
        time.sleep(0.5)
    return port_open(port)


def port_owner(port: int) -> int | None:
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, timeout=15,
                           creationflags=CREATE_NO_WINDOW)
        for line in decode_output(r.stdout).splitlines():
            if f":{port} " in line and "LISTENING" in line.upper():
                pid = line.split()[-1]
                if pid.isdigit():
                    return int(pid)
    except Exception:  # noqa: BLE001
        pass
    return None
