"""minerU-install-gui.exe 入口：一键部署向导（Tkinter）。

也支持无界面模式，便于自动化测试：
    minerU-install-gui.exe --dry-run --out plan.json
    minerU-install-gui.exe --root E:\\MinerU --with-models false
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import common as C
import deploy as D

ACCENT = "#5b4cf5"
ACCENT_DARK = "#4a3ee0"
BG = "#f4f5fa"
INK = "#1d2033"
MUTED = "#6b7188"


class InstallerApp:
    def __init__(self, win: tk.Tk, initial_root: Path) -> None:
        self.win = win
        self.initial_root = initial_root
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        self.ok = False
        self.err = ""
        self.ctx: D.Context | None = None
        self.step_labels: dict[str, tk.Label] = {}
        self.step_order = [k for k, _, _ in D.STEPS]

        self._build()
        self._poll()

    # ------------------------------------------------------------ UI
    def _build(self) -> None:
        self.win.title("MinerU 一键部署")
        self.win.geometry("900x760")
        self.win.minsize(820, 640)
        self.win.configure(bg=BG)

        header = tk.Frame(self.win, bg=ACCENT, height=92)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="MinerU 一键部署", bg=ACCENT, fg="white",
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", padx=24, pady=(16, 0))
        tk.Label(header, text="无需预装 Python / uv，自动下载依赖、配置 GPU 加速与本地模型",
                 bg=ACCENT, fg="#e7e3ff", font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=24, pady=(2, 0))

        # 底部操作区先占位，保证窗口变矮时按钮不会被挤出
        self.bottom_holder = tk.Frame(self.win, bg=BG)
        self.bottom_holder.pack(side="bottom", fill="x", padx=20, pady=(0, 14))

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=14)
        body.columnconfigure(0, weight=0, minsize=280)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        # 左：配置 + 步骤
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 14))
        left.rowconfigure(2, weight=1)

        card = tk.LabelFrame(left, text=" 安装选项 ", bg="white", fg=INK,
                             font=("Microsoft YaHei UI", 10, "bold"), bd=1, relief="solid")
        card.pack(fill="x", pady=(0, 12))
        tk.Label(card, text="安装目录", bg="white", fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12, pady=(10, 2))
        dirrow = tk.Frame(card, bg="white")
        dirrow.pack(fill="x", padx=12, pady=(0, 8))
        self.root_var = tk.StringVar(value=str(self.initial_root))
        entry = tk.Entry(dirrow, textvariable=self.root_var, font=("Consolas", 9),
                         relief="solid", bd=1)
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        tk.Button(dirrow, text="浏览", command=self._browse, relief="solid", bd=1,
                  bg="#f0f0f6", activebackground="#e4e1ff", cursor="hand2").pack(side="left", padx=(6, 0))

        self.var_models = tk.BooleanVar(value=True)
        self.var_start = tk.BooleanVar(value=True)
        for text, var in (("下载模型（约 2 GB，推荐）", self.var_models),
                          ("完成后启动本地操作台", self.var_start)):
            tk.Checkbutton(card, text=text, variable=var, bg="white", fg=INK,
                           activebackground="white", font=("Microsoft YaHei UI", 9),
                           anchor="w").pack(anchor="w", padx=8, pady=1)

        steps_card = tk.LabelFrame(left, text=" 部署进度 ", bg="white", fg=INK,
                                   font=("Microsoft YaHei UI", 10, "bold"), bd=1, relief="solid")
        steps_card.pack(fill="both", expand=True)
        for key, title, _ in D.STEPS:
            row = tk.Frame(steps_card, bg="white")
            row.pack(fill="x", padx=10, pady=3)
            icon = tk.Label(row, text="○", bg="white", fg="#b8bdd0",
                            font=("Segoe UI", 11))
            icon.pack(side="left")
            lab = tk.Label(row, text=title, bg="white", fg=INK,
                           font=("Microsoft YaHei UI", 9), anchor="w")
            lab.pack(side="left", padx=(6, 0), fill="x", expand=True)
            self.step_labels[key] = icon

        # 右：日志
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, rowspan=2, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        tk.Label(right, text="运行日志", bg=BG, fg=INK,
                 font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.log_text = tk.Text(right, bg="#12141f", fg="#d7daea", insertbackground="white",
                                font=("Consolas", 9), relief="flat", wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        sb = tk.Scrollbar(right, command=self.log_text.yview)
        sb.grid(row=1, column=0, sticky="nse", pady=(6, 0))
        self.log_text.configure(yscrollcommand=sb.set, state="disabled")

        bottom = self.bottom_holder
        self.progress = ttk.Progressbar(bottom, mode="determinate", maximum=len(D.STEPS))
        self.progress.pack(fill="x", pady=(0, 10))
        self.btn_start = tk.Button(bottom, text="开始部署", bg=ACCENT, fg="white",
                                   activebackground=ACCENT_DARK, activeforeground="white",
                                   relief="flat", font=("Microsoft YaHei UI", 11, "bold"),
                                   cursor="hand2", command=self._start)
        self.btn_start.pack(side="left", ipadx=22, ipady=6)
        self.btn_cancel = tk.Button(bottom, text="取消", state="disabled", relief="solid", bd=1,
                                    font=("Microsoft YaHei UI", 10), command=self._cancel)
        self.btn_cancel.pack(side="left", padx=10, ipadx=16, ipady=6)
        self.btn_dir = tk.Button(bottom, text="打开安装目录", state="disabled", relief="solid", bd=1,
                                 font=("Microsoft YaHei UI", 10), command=self._open_dir)
        self.btn_dir.pack(side="right", ipadx=14, ipady=6)

    # ------------------------------------------------------------ 交互
    def _browse(self) -> None:
        path = filedialog.askdirectory(title="选择安装目录")
        if path:
            self.root_var.set(path)

    def _open_dir(self) -> None:
        target = Path(self.root_var.get())
        if target.exists():
            import os
            os.startfile(str(target))

    def _log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _mark(self, key: str, state: str) -> None:
        icon = self.step_labels.get(key)
        if not icon:
            return
        if state == "start":
            icon.configure(text="●", fg=ACCENT)
        elif state == "done":
            icon.configure(text="✓", fg="#12b76a")
        elif state == "fail":
            icon.configure(text="✗", fg="#f04438")

    # ------------------------------------------------------------ 任务
    def _start(self) -> None:
        if self.running:
            return
        root = Path(self.root_var.get().strip())
        if not root:
            messagebox.showwarning("提示", "请填写安装目录")
            return
        self.running = True
        self.ok = False
        self.err = ""
        self.cancel.clear()
        self.progress["value"] = 0
        self.btn_start.configure(state="disabled", text="部署中…")
        self.btn_cancel.configure(state="normal")
        for key, icon in self.step_labels.items():
            icon.configure(text="○", fg="#b8bdd0")

        opt = D.Options(root=root, with_models=self.var_models.get(),
                        start_console=self.var_start.get())
        self.ctx = D.Context(opt=opt, log=self._emit_log, cancel=self.cancel)

        def worker() -> None:
            try:
                done = 0
                self.ctx.log("开始部署：" + str(root))
                for key, title, fn in D.STEPS:
                    if self.cancel.is_set():
                        raise C.Cancelled()
                    self.q.put(("step", key, "start"))
                    self.ctx.log(f"\n=== {title} ===")
                    fn(self.ctx)
                    self.q.put(("step", key, "done"))
                    done += 1
                    self.q.put(("progress", done))
                self.q.put(("done", True, ""))
            except C.Cancelled:
                self.q.put(("done", False, "已取消"))
            except D.StepError as exc:
                self.q.put(("done", False, f"{exc.message}\n{exc.hint}"))
            except Exception as exc:  # noqa: BLE001
                import traceback
                detail = traceback.format_exc()
                try:
                    (root / "logs").mkdir(parents=True, exist_ok=True)
                    (root / "logs" / "error.log").write_text(detail, encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
                self.q.put(("done", False, f"意外错误：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _emit_log(self, text: str) -> None:
        self.q.put(("log", text))

    def _cancel(self) -> None:
        if self.running:
            self.cancel.set()
            self._log("正在取消…")

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "log":
                    self._log(item[1])
                elif item[0] == "step":
                    self._mark(item[1], item[2])
                elif item[0] == "progress":
                    self.progress["value"] = item[1]
                elif item[0] == "done":
                    self._finish(item[1], item[2])
        except queue.Empty:
            pass
        self.win.after(120, self._poll)

    def _finish(self, ok: bool, err: str) -> None:
        self.running = False
        self.ok = ok
        self.err = err
        self.btn_start.configure(state="normal", text="开始部署")
        self.btn_cancel.configure(state="disabled")
        self.btn_dir.configure(state="normal" if ok else "disabled")
        if ok:
            self.progress["value"] = len(D.STEPS)
            messagebox.showinfo("部署完成",
                                "MinerU 已部署完成。\n\n可直接双击 minerU-gui.exe 启动本地操作台。")
            if self.ctx and self.ctx.opt.start_console:
                self._start_console()
        else:
            for key, icon in self.step_labels.items():
                if icon.cget("text") == "●":
                    icon.configure(text="✗", fg="#f04438")
                    break
            messagebox.showerror("部署失败", err or "未知错误")

    def _start_console(self) -> None:
        if not self.ctx:
            return
        root = self.ctx.root
        py = root / ".venv" / "Scripts" / "python.exe"
        server = root / "webapp" / "server.py"
        if not py.exists() or not server.exists():
            return
        import subprocess
        env = C.child_env({
            "MINERU_ROOT": str(root),
            "MODELSCOPE_CACHE": str(root / ".cache" / "modelscope"),
            "HF_HOME": str(root / ".cache" / "hf"),
        })
        log = (root / "webapp" / "server.log").open("a", encoding="utf-8")
        subprocess.Popen([str(py), str(server)], cwd=str(root), env=env,
                         stdout=log, stderr=subprocess.STDOUT,
                         creationflags=C.CREATE_NO_WINDOW)
        self._log("已启动本地操作台：http://127.0.0.1:7861")


def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="minerU-install-gui")
    ap.add_argument("--root", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run", action="store_true", help="无界面执行部署")
    ap.add_argument("--out", default=None, help="把结果写入 JSON 文件")
    ap.add_argument("--with-models", default="true")
    ap.add_argument("--uv-cache", default=None, help="复用已有的 uv 缓存目录")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else (C.resolve_root() or Path(r"E:\MinerU"))
    cache = Path(args.uv_cache) if args.uv_cache else None
    if args.dry_run:
        opt = D.Options(root=root, with_models=str(args.with_models).lower() != "false",
                        uv_cache=cache)
        ctx = D.Context(opt=opt, log=lambda _t: None, cancel=threading.Event())
        data = {"root": str(root), "steps": D.plan(ctx),
                "python_mirrors": D.PYTHON_MIRRORS,
                "torch_index": C.torch_index_for(C.nvidia_smi_map().get("cuda_version"))}
        if args.out:
            Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    if args.run:
        logs: list[str] = []
        result: dict = {"ok": False, "root": str(root), "error": "", "steps": []}
        log_dir = root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / ("install-" + time.strftime("%Y%m%d-%H%M%S") + ".log")

        def log(line: str) -> None:
            logs.append(line)
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

        opt = D.Options(root=root, with_models=str(args.with_models).lower() != "false",
                        uv_cache=cache)
        ctx = D.Context(opt=opt, log=log, cancel=threading.Event())
        try:
            D.run_pipeline(ctx, on_step=lambda key, st: result["steps"].append([key, st]))
            result["ok"] = True
        except D.StepError as exc:
            result["error"] = exc.message + "\n" + exc.hint
        except Exception as exc:  # noqa: BLE001
            import traceback
            result["error"] = f"意外错误：{exc}"
            try:
                (root / "logs").mkdir(parents=True, exist_ok=True)
                (root / "logs" / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        if args.out:
            Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if result["ok"] else 1

    win = tk.Tk()
    InstallerApp(win, root)
    win.mainloop()
    return 0


def main() -> None:
    args = sys.argv[1:]
    if args:
        code = cli(args)
        raise SystemExit(code)
    root = C.resolve_root() or Path(r"E:\MinerU")
    win = tk.Tk()
    InstallerApp(win, root)
    win.mainloop()


if __name__ == "__main__":
    main()
