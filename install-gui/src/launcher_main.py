"""minerU-gui.exe: daily launcher (Tkinter).

- locates the install root (installer config, exe folder, or user pick);
- starts/stops the local console (7861) and the original web UI (7860);
- optional cleanup of started processes on exit (no zombie ports).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import common as C

ACCENT = "#5b4cf5"
ACCENT_DARK = "#4a3ee0"
BG = "#f4f5fa"
INK = "#1d2033"
MUTED = "#6b7188"
OK = "#12b76a"


# ------------------------------------------------------------ process helpers
def _env(root: Path) -> dict:
    return C.child_env({
        "MINERU_ROOT": str(root),
        "MINERU_HOME": str(root / ".mineru"),
        "MODELSCOPE_CACHE": str(root / ".cache" / "modelscope"),
        "HF_HOME": str(root / ".cache" / "hf"),
    })


def start_console(root: Path) -> subprocess.Popen | None:
    py = root / ".venv" / "Scripts" / "python.exe"
    server = root / "webapp" / "server.py"
    if not py.exists() or not server.exists():
        return None
    log = (root / "webapp" / "server.log").open("a", encoding="utf-8")
    return subprocess.Popen([str(py), str(server)], cwd=str(root), env=_env(root),
                            stdout=log, stderr=subprocess.STDOUT,
                            creationflags=C.CREATE_NO_WINDOW)


def start_webui(root: Path, port: int) -> subprocess.Popen | None:
    kit = root / ".venv" / "Scripts" / "mineru-kit.exe"
    if not kit.exists():
        return None
    log = (root / "webui.log").open("a", encoding="utf-8")
    return subprocess.Popen([str(kit), "webui", "--server-name", "127.0.0.1",
                             "--server-port", str(port)],
                            cwd=str(root), env=_env(root),
                            stdout=log, stderr=subprocess.STDOUT,
                            creationflags=C.CREATE_NO_WINDOW)


def stop_port(port: int) -> bool:
    pid = C.port_owner(port)
    if pid:
        C.kill_tree(pid)
        time.sleep(0.8)
    return not C.port_open(port)


class LauncherApp:
    def __init__(self, win: tk.Tk, root: Path | None) -> None:
        self.win = win
        self.root = root
        self.procs: dict[str, subprocess.Popen] = {}
        self.ports = dict(C.DEFAULT_PORTS)
        self._build()
        self._refresh()
        self.win.after(800, self._auto_start)

    # ------------------------------------------------------------ UI
    def _build(self) -> None:
        self.win.title("MinerU 本地版")
        self.win.geometry("620x520")
        self.win.minsize(560, 460)
        self.win.configure(bg=BG)
        self.win.protocol("WM_DELETE_WINDOW", self._quit)

        header = tk.Frame(self.win, bg=ACCENT, height=86)
        header.pack(fill="x")
        header.pack_propagate(False)
        title = tk.Frame(header, bg=ACCENT)
        title.pack(anchor="w", padx=22, pady=(14, 0))
        tk.Label(title, text="M", bg="white", fg=ACCENT, width=2,
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(title, text=" MinerU 本地版", bg=ACCENT, fg="white",
                 font=("Microsoft YaHei UI", 17, "bold")).pack(side="left", padx=(8, 0))
        self.path_lbl = tk.Label(header, text="", bg=ACCENT, fg="#e7e3ff",
                                 font=("Consolas", 8))
        self.path_lbl.pack(anchor="w", padx=24, pady=(2, 0))

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        self.cards: dict[str, dict] = {}
        for key, name, port in (("console", "本地操作台", self.ports["console"]),
                                ("webui", "原版 WebUI", self.ports["webui"])):
            card = tk.LabelFrame(body, text="  " + name + "  ", bg="white", fg=INK,
                                 font=("Microsoft YaHei UI", 10, "bold"), bd=1, relief="solid")
            card.pack(fill="x", pady=6)
            row = tk.Frame(card, bg="white")
            row.pack(fill="x", padx=12, pady=10)
            dot = tk.Label(row, text="●", bg="white", fg="#c0c4d4", font=("Segoe UI", 10))
            dot.pack(side="left")
            state = tk.Label(row, text="未运行", bg="white", fg=MUTED,
                             font=("Microsoft YaHei UI", 10))
            state.pack(side="left", padx=(6, 0))
            url = tk.Label(row, text=f"http://127.0.0.1:{port}", bg="white", fg="#9aa0b4",
                           font=("Consolas", 9))
            url.pack(side="left", padx=(10, 0))
            btn_box = tk.Frame(row, bg="white")
            btn_box.pack(side="right")
            start_btn = tk.Button(btn_box, text="启动", relief="solid", bd=1,
                                  font=("Microsoft YaHei UI", 9), cursor="hand2",
                                  command=lambda k=key: self._start(k))
            start_btn.pack(side="left", padx=3)
            stop_btn = tk.Button(btn_box, text="停止", relief="solid", bd=1,
                                 font=("Microsoft YaHei UI", 9), cursor="hand2",
                                 command=lambda k=key: self._stop(k))
            stop_btn.pack(side="left", padx=3)
            open_btn = tk.Button(btn_box, text="打开", relief="solid", bd=1,
                                 font=("Microsoft YaHei UI", 9), cursor="hand2",
                                 command=lambda k=key: self._open(k))
            open_btn.pack(side="left", padx=3)
            self.cards[key] = {"dot": dot, "state": state, "start": start_btn,
                               "stop": stop_btn, "open": open_btn}

        tools = tk.Frame(body, bg=BG)
        tools.pack(fill="x", pady=(4, 8))
        for text, cmd in (("使用教程", lambda: self._open_url(
                              f"http://127.0.0.1:{self.ports['console']}/guide")),
                          ("安装目录", self._open_root),
                          ("查看日志", self._open_log)):
            tk.Button(tools, text=text, relief="solid", bd=1, font=("Microsoft YaHei UI", 9),
                      cursor="hand2", command=cmd).pack(side="left", padx=3)

        self.var_stop = tk.BooleanVar(value=True)
        self.var_browser = tk.BooleanVar(value=True)
        opts = tk.Frame(body, bg=BG)
        opts.pack(fill="x", pady=(2, 6))
        tk.Checkbutton(opts, text="退出时停止我启动的服务", variable=self.var_stop,
                       bg=BG, fg=INK, activebackground=BG,
                       font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Checkbutton(opts, text="启动后自动打开浏览器", variable=self.var_browser,
                       bg=BG, fg=INK, activebackground=BG,
                       font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(12, 0))

        tk.Label(body, text="运行状态", bg=BG, fg=INK,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(8, 4))
        self.log = tk.Text(body, bg="#12141f", fg="#c8ccdf", font=("Consolas", 8),
                           relief="flat", height=7, wrap="none")
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        self._update_root_label()

    # ------------------------------------------------------------ state
    def _update_root_label(self) -> None:
        self.path_lbl.configure(text=str(self.root) if self.root else "未找到安装目录")

    def _refresh(self) -> None:
        for key, card in self.cards.items():
            port = self.ports[key]
            up = C.port_open(port)
            proc = self.procs.get(key)
            alive = proc is not None and proc.poll() is None
            if up:
                card["dot"].configure(fg=OK)
                card["state"].configure(text="运行中" + ("（本程序启动）" if alive else ""), fg=INK)
                card["start"].configure(state="disabled")
                card["stop"].configure(state="normal")
            else:
                card["dot"].configure(fg="#c0c4d4")
                card["state"].configure(text="未运行", fg=MUTED)
                card["start"].configure(state="normal" if self.root else "disabled")
                card["stop"].configure(state="normal" if alive else "disabled")
        self.win.after(1000, self._refresh)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 400:
            self.log.delete("1.0", f"{lines - 400}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ actions
    def _ensure_root(self) -> bool:
        if self.root:
            return True
        picked = filedialog.askdirectory(title="选择 MinerU 安装目录")
        if not picked:
            return False
        root = Path(picked)
        if not C.valid_root(root):
            messagebox.showerror("目录无效", "该目录不是有效的 MinerU 安装目录。\n"
                                            "请先运行 minerU-install-gui.exe 完成部署。")
            return False
        self.root = root
        cfg = C.load_config()
        cfg["root"] = str(root)
        C.save_config(cfg)
        self._update_root_label()
        return True

    def _start(self, key: str) -> None:
        if not self._ensure_root():
            return
        assert self.root
        if C.port_open(self.ports[key]):
            self._open(key)
            return
        proc = start_console(self.root) if key == "console" else start_webui(self.root, self.ports[key])
        if proc is None:
            messagebox.showerror("无法启动", "缺少程序组件，请重新运行 minerU-install-gui.exe。")
            return
        self.procs[key] = proc
        self._append_log(f"[{key}] 启动中 PID={proc.pid}")
        threading.Thread(target=self._wait_ready, args=(key, proc), daemon=True).start()

    def _wait_ready(self, key: str, proc: subprocess.Popen) -> None:
        for _ in range(90):
            if proc.poll() is not None:
                self._append_log(f"[{key}] 进程退出（代码 {proc.returncode}），请查看日志")
                return
            if C.port_open(self.ports[key]):
                self._append_log(f"[{key}] 已就绪：http://127.0.0.1:{self.ports[key]}")
                if self.var_browser.get() and key == "console":
                    self._open(key)
                return
            time.sleep(0.5)
        self._append_log(f"[{key}] 启动超时，请查看日志")

    def _stop(self, key: str) -> None:
        proc = self.procs.pop(key, None)
        if proc and proc.poll() is None:
            C.kill_tree(proc.pid)
        else:
            stop_port(self.ports[key])
        self._append_log(f"[{key}] 已停止")

    def _open(self, key: str) -> None:
        self._open_url(f"http://127.0.0.1:{self.ports[key]}")

    @staticmethod
    def _open_url(url: str) -> None:
        webbrowser.open(url)

    def _open_root(self) -> None:
        if self.root and self.root.exists():
            os.startfile(str(self.root))

    def _open_log(self) -> None:
        if not self.root:
            return
        log = self.root / "webapp" / "server.log"
        if log.exists():
            os.startfile(str(log))
        else:
            messagebox.showinfo("日志", "还没有运行日志。")

    def _quit(self) -> None:
        if self.var_stop.get():
            for key in list(self.procs):
                proc = self.procs.pop(key)
                if proc.poll() is None:
                    C.kill_tree(proc.pid)
        self.win.destroy()

    def _auto_start(self) -> None:
        if self.root and not C.port_open(self.ports["console"]):
            self._start("console")


# ------------------------------------------------------------ headless CLI
def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="minerU-gui")
    ap.add_argument("--root", default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--start-console", action="store_true")
    ap.add_argument("--stop-console", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    root = C.resolve_root(args.root)
    if args.check:
        data = {
            "root": str(root) if root else None,
            "found": bool(root),
            "console": C.port_open(C.DEFAULT_PORTS["console"]),
            "webui": C.port_open(C.DEFAULT_PORTS["webui"]),
            "gpu": C.nvidia_smi_map(),
        }
        if args.out:
            Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if root else 2

    if not root:
        if args.out:
            Path(args.out).write_text(json.dumps({"ok": False, "error": "未找到安装目录"},
                                                 ensure_ascii=False), encoding="utf-8")
        return 2

    result = {"root": str(root), "ok": False}
    if args.start_console:
        port = C.DEFAULT_PORTS["console"]
        if C.port_open(port):
            result.update(ok=True, note="already running")
        else:
            proc = start_console(root)
            if proc is None:
                result["error"] = "缺少组件"
            else:
                ready = False
                deadline = time.time() + 120
                while time.time() < deadline:
                    if proc.poll() is not None:
                        result["error"] = f"服务进程提前退出（代码 {proc.returncode}）"
                        break
                    if C.port_open(port):
                        ready = True
                        break
                    time.sleep(0.5)
                if ready:
                    result.update(ok=True, started=True, pid=proc.pid)
                elif "error" not in result:
                    result["error"] = "启动超时"
    elif args.stop_console:
        result.update(ok=stop_port(C.DEFAULT_PORTS["console"]))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result.get("ok") else 1


def main() -> None:
    args = sys.argv[1:]
    if args:
        raise SystemExit(cli(args))
    root = C.resolve_root()
    win = tk.Tk()
    LauncherApp(win, root)
    win.mainloop()


if __name__ == "__main__":
    main()
