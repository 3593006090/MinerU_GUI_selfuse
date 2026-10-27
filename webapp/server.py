"""MinerU 本地操作台后端。

启动方式：
    E:\\MinerU\\.venv\\Scripts\\python.exe E:\\MinerU\\webapp\\server.py
或双击 E:\\MinerU\\start-console.cmd
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# 安装目录：可由 MINERU_ROOT 指定（安装器/启动器会传入），默认取 webapp 的上级目录
ROOT = Path(os.environ.get("MINERU_ROOT") or Path(__file__).resolve().parent.parent)
KIT = ROOT / ".venv" / "Scripts" / "mineru-kit.exe"
DATA = ROOT / "webapp" / "data"
UPLOADS = DATA / "uploads"
OUTPUTS = DATA / "outputs"
STATIC = ROOT / "webapp" / "static"
SAMPLE_PDF = ROOT / "test" / "sample.pdf"

for d in (UPLOADS, OUTPUTS, STATIC):
    d.mkdir(parents=True, exist_ok=True)

ENV = os.environ.copy()
ENV["MODELSCOPE_CACHE"] = str(ROOT / ".cache" / "modelscope")
ENV["HF_HOME"] = str(ROOT / ".cache" / "hf")
ENV["PYTHONIOENCODING"] = "utf-8"

TIERS = {
    "flash": {"name": "Flash", "desc": "仅原生文本提取，不跑模型，秒级完成", "time": "~1 秒/页"},
    "basic": {"name": "Basic", "desc": "小模型 OCR / 版面 / 表格识别", "time": "~3 秒/页"},
    "standard": {"name": "Standard", "desc": "小模型 + VLM，质量最好（推荐）", "time": "~8 秒/页"},
    "advanced": {"name": "Advanced", "desc": "更多推理计算，追求极致质量", "time": "~15 秒/页"},
}

NATIVE_IMAGE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
DONE_HINTS = ("已解析", "解析完成", "Parsed", "parse finished")
TIMEOUT_SECONDS = int(os.environ.get("MINERU_CONSOLE_TIMEOUT", "1800"))

app = FastAPI(title="MinerU 本地操作台")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

TASKS: dict[str, dict[str, Any]] = {}
TASKS_LOCK = threading.Lock()
PARSE_LOCK = threading.Lock()  # 单任务串行，避免 8GB 显存被并发撑爆

_HEALTH: dict[str, Any] = {}


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:  # 修复“UTF-8 字节被按 latin-1 读过一遍”的乱码
        return data.decode("latin-1").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    try:
        return data.decode("gbk")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def collect_health() -> dict[str, Any]:
    if _HEALTH:
        return _HEALTH
    info: dict[str, Any] = {"ok": True, "version": "unknown", "gpu": "未检测到", "models": str(ROOT / "models")}
    try:
        r = subprocess.run([str(KIT), "--version"], capture_output=True, timeout=60)
        text = _decode(r.stdout) + _decode(r.stderr)
        m = re.search(r"(\d+\.\d+\.\d+)", text)
        if m:
            info["version"] = m.group(1)
    except Exception:
        info["ok"] = False
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, timeout=20,
        )
        gpu = _decode(r.stdout).strip().splitlines()
        if gpu:
            info["gpu"] = gpu[0].strip()
    except Exception:
        pass
    _HEALTH.update(info)
    return _HEALTH


def _set(task: dict[str, Any], **kw: Any) -> None:
    with TASKS_LOCK:
        task.update(kw)


def _append_log(task: dict[str, Any], line: str) -> None:
    line = line.strip()
    if not line:
        return
    with TASKS_LOCK:
        task["log"].append(line)
        if len(task["log"]) > 400:
            del task["log"][0]

PROGRESS_RE = re.compile(r"(?P<label>[A-Za-z][A-Za-z0-9 _\-/]{1,40}?):\s*(?P<pct>\d{1,3})%")
PHASE_NAMES = [
    ("Layout Predict", "版面分析"),
    ("MFR Predict", "公式识别"),
    ("OCR-det", "OCR 检测"),
    ("OCR-rec", "OCR 识别"),
    ("Table", "表格识别"),
    ("VLM", "VLM 推理"),
    ("Downloading", "加载模型"),
    ("Loading", "加载模型"),
]


def _phase_of(label: str) -> str:
    for key, name in PHASE_NAMES:
        if key.lower() in label.lower():
            return name
    return label


def _reader(stream, task: dict[str, Any]) -> None:
    """读取子进程输出（含 \\r 进度条），更新阶段、百分比与日志。线程为守护线程，不参与等待。"""
    buf = ""
    try:
        while True:
            chunk = stream.read(1)
            if not chunk:
                break
            buf += _decode(chunk)
            while "\r" in buf or "\n" in buf:
                i = buf.find("\r") if "\r" in buf else len(buf)
                j = buf.find("\n")
                if j != -1 and j < i:
                    i = j
                seg, buf = buf[:i], buf[i + 1:]
                m = PROGRESS_RE.search(seg)
                if m:
                    label = m.group("label").strip()
                    pct = min(100, int(m.group("pct")))
                    with TASKS_LOCK:
                        task["phase"] = _phase_of(label)
                        task["percent"] = pct
                        if pct in (0, 100):
                            task["log"].append(f"{_phase_of(label)} {pct}%")
                            if len(task["log"]) > 400:
                                del task["log"][0]
                else:
                    _append_log(task, seg)
        if buf.strip():
            _append_log(task, buf)
    except Exception:  # noqa: BLE001
        pass


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _pick_tier(name: str, tier: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in NATIVE_IMAGE_SUFFIXES:
        return tier
    return "flash"


def _find_md(out_dir: Path) -> Path | None:
    mds = [p for p in out_dir.rglob("*.md") if p.is_file() and p.stat().st_size > 0]
    mds.sort(key=lambda p: p.stat().st_size, reverse=True)
    return mds[0] if mds else None


def run_task(task_id: str) -> None:
    task = TASKS[task_id]
    src = Path(task["src"])
    out_dir = Path(task["out_dir"])
    effective = _pick_tier(task["name"], task["tier"])

    with PARSE_LOCK:
        if task["status"] == "cancelled":
            return
        _set(task, status="running", phase="启动解析进程", percent=0, started=time.time(),
             effective_tier=effective)
        cmd = [str(KIT), "parse", str(src), "-o", str(out_dir), "--tier", effective]
        _append_log(task, "执行: " + " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=ENV, cwd=str(ROOT),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:  # noqa: BLE001
            _set(task, status="error", error=f"无法启动解析进程: {exc}", finished=time.time())
            return

        _set(task, proc=proc)
        for stream in (proc.stderr, proc.stdout):
            threading.Thread(target=_reader, args=(stream, task), daemon=True).start()

        # 以“输出文件生成”为准判断完成，不依赖管道 EOF（MinerU 子进程可能残留句柄）
        deadline = time.time() + TIMEOUT_SECONDS
        md: Path | None = None
        while True:
            time.sleep(0.5)
            if task["status"] == "cancelled":
                _kill_tree(proc)
                _set(task, finished=time.time(), phase="已取消")
                return
            md = _find_md(out_dir)
            if md is not None:
                log_text = "\n".join(task["log"])
                if any(h in log_text for h in DONE_HINTS) or proc.poll() is not None:
                    break
            elif proc.poll() is not None:
                time.sleep(0.6)
                md = _find_md(out_dir)
                if md is not None:
                    break
                tail = "\n".join(task["log"][-12:])
                _set(task, status="error", error=f"解析进程已退出但未生成结果\n{tail}",
                     finished=time.time())
                return
            if time.time() > deadline:
                _kill_tree(proc)
                _set(task, status="error", error=f"解析超时（超过 {TIMEOUT_SECONDS} 秒）",
                     finished=time.time())
                return

        _kill_tree(proc)
        finished = time.time()
        _set(
            task,
            status="done",
            phase="完成",
            percent=100,
            md_path=str(md),
            finished=finished,
            elapsed=round(finished - task["started"], 1),
        )
        meta = {k: v for k, v in task.items() if k not in ("log", "proc")}
        try:
            (out_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass


def new_task(name: str, src: Path, tier: str) -> dict[str, Any]:
    task_id = uuid.uuid4().hex[:12]
    out_dir = OUTPUTS / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    task = {
        "id": task_id,
        "name": name,
        "src": str(src),
        "tier": tier,
        "out_dir": str(out_dir),
        "status": "queued",
        "phase": "排队中",
        "percent": 0,
        "log": [],
        "created": time.time(),
        "md_path": None,
        "error": None,
        "effective_tier": tier,
    }
    TASKS[task_id] = task
    threading.Thread(target=run_task, args=(task_id,), daemon=True).start()
    return task


def public(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "name": task["name"],
        "tier": task.get("effective_tier") or task["tier"],
        "status": task["status"],
        "phase": task.get("phase"),
        "percent": task.get("percent", 0),
        "error": task.get("error"),
        "elapsed": round(time.time() - task["created"], 1) if task["status"] in ("running", "queued") else task.get("elapsed"),
        "log": (task.get("log") or [])[-60:],
        "created": task.get("created"),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/guide", response_class=HTMLResponse)
def guide() -> HTMLResponse:
    return HTMLResponse((STATIC / "guide.html").read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return collect_health()


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {"tiers": TIERS, "max_mb": 200, "sample": SAMPLE_PDF.exists()}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "doc").suffix.lower() or ".pdf"
    file_id = f"{uuid.uuid4().hex[:10]}_{int(time.time())}{suffix}"
    dest = UPLOADS / file_id
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 200 * 1024 * 1024:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "文件超过 200MB 限制")
            fh.write(chunk)
    # 记录原始文件名，后续任务展示、输出命名都用它
    (UPLOADS / f"{file_id}.meta.json").write_text(
        json.dumps({"name": file.filename or file_id}, ensure_ascii=False), encoding="utf-8")
    return {"file_id": file_id, "name": file.filename, "size": size}


@app.post("/api/tasks")
def create_task(file_id: str = Form(...), tier: str = Form("standard")) -> dict[str, Any]:
    if tier not in TIERS:
        raise HTTPException(400, "未知档位")
    dest = UPLOADS / file_id
    if not dest.exists():
        raise HTTPException(404, "文件不存在，请重新上传")
    original = file_id
    sidecar = UPLOADS / f"{file_id}.meta.json"
    if sidecar.exists():
        try:
            original = json.loads(sidecar.read_text(encoding="utf-8")).get("name") or file_id
        except Exception:  # noqa: BLE001
            pass
    task = new_task(original, dest, tier)
    return {"task_id": task["id"]}


@app.post("/api/demo")
def demo(tier: str = Form("standard")) -> dict[str, Any]:
    if not SAMPLE_PDF.exists():
        raise HTTPException(404, "示例文件不存在")
    dest = UPLOADS / f"demo_{uuid.uuid4().hex[:8]}.pdf"
    shutil.copy(SAMPLE_PDF, dest)
    task = new_task("示例文档.pdf", dest, tier)
    return {"task_id": task["id"]}


def _load_task(task_id: str) -> dict[str, Any] | None:
    """内存中找不到时，从磁盘 meta.json 恢复（服务重启后历史仍可打开）。"""
    task = TASKS.get(task_id)
    if task:
        return task
    meta_path = OUTPUTS / task_id / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    md = _find_md(OUTPUTS / task_id)
    meta.setdefault("out_dir", str(OUTPUTS / task_id))
    meta.setdefault("log", [])
    meta.setdefault("percent", 100)
    meta.setdefault("phase", "完成")
    meta.setdefault("created", time.time())
    if md is not None:
        meta["md_path"] = str(md)
        meta["status"] = "done"
    return meta


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    task = _load_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    data = public(task)
    if task.get("status") == "done" and task.get("md_path"):
        data["markdown"] = Path(task["md_path"]).read_text(encoding="utf-8", errors="replace")
    return data


@app.get("/api/tasks/{task_id}/download")
def download_md(task_id: str) -> FileResponse:
    task = _load_task(task_id)
    if not task or not task.get("md_path"):
        raise HTTPException(404, "结果不存在")
    md = Path(task["md_path"])
    return FileResponse(md, filename=f"{Path(task.get('name') or 'result').stem}.md", media_type="text/markdown")


@app.get("/api/tasks/{task_id}/zip")
def download_zip(task_id: str) -> FileResponse:
    task = _load_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    out_dir = Path(task["out_dir"])
    zpath = out_dir / f"{Path(task.get('name') or 'result').stem}_output.zip"
    if not zpath.exists():
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in out_dir.rglob("*"):
                if p.is_file() and p.name != zpath.name:
                    zf.write(p, p.relative_to(out_dir))
    return FileResponse(zpath, filename=zpath.name, media_type="application/zip")


@app.post("/api/tasks/{task_id}/cancel")
def cancel(task_id: str) -> dict[str, Any]:
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    proc = task.get("proc")
    if proc and proc.poll() is None:
        _set(task, status="cancelled", phase="已取消")
        _kill_tree(proc)
        return {"ok": True}
    return {"ok": False, "reason": "任务不在运行中"}


@app.get("/api/history")
def history() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for meta in OUTPUTS.glob("*/meta.json"):
        try:
            items.append(json.loads(meta.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    for t in TASKS.values():
        if t["status"] == "done":
            items.append({k: v for k, v in t.items() if k not in ("log", "proc")})
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x.get("created", 0), reverse=True):
        if it.get("id") in seen:
            continue
        seen.add(it.get("id"))
        tier_key = it.get("effective_tier") or it.get("tier") or ""
        out.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "status": it.get("status"),
            "tier": TIERS.get(tier_key, {}).get("name", tier_key),
            "created": it.get("created"),
            "elapsed": it.get("elapsed"),
        })
    return out[:12]


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=7861, log_level="info")
