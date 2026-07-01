"""
WASD Macro Hub  —  Launcher GUI for main.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
No more typing `python main.py --calibrate` in a terminal.
This hub gives you buttons for Start / Stop / Calibrate, a live
color-coded log console, a status light, current ROI/config info,
and a global emergency-stop hotkey (F12).

Place this file in the SAME folder as main.py and run:
    python macro_hub.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations
import atexit
import hashlib
import os
import sys
import json
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import keyboard  # for the global emergency-stop hotkey
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

# ══════════════════════════════════════════════════════════════════
#  PATHS & CONSTANTS
# ══════════════════════════════════════════════════════════════════

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
WORKER_SCRIPT = os.path.join(BASE_DIR, "macro_worker.py")
MAIN_SCRIPT = WORKER_SCRIPT
ROI_FILE    = os.path.join(BASE_DIR, "rois.json")
DEBUG_DIR   = os.path.join(BASE_DIR, "debug")
EMERGENCY_HOTKEY = "f12"
APP_INSTANCE_ID = hashlib.sha256(BASE_DIR.lower().encode("utf-8")).hexdigest()[:16]
APP_MUTEX_NAME = f"Local\\WASDMacroHub-{APP_INSTANCE_ID}"
APP_LOCK_FILE = os.path.join(tempfile.gettempdir(), f"wasd_macro_hub_{APP_INSTANCE_ID}.lock")
_INSTANCE_GUARD_HANDLE = None

# Dark theme palette
BG        = "#141416"
BG_PANEL  = "#1c1c1f"
BG_CARD   = "#232326"
FG        = "#e6e6e6"
FG_DIM    = "#8a8a90"
ACCENT    = "#e63946"      # matches the red WASD glyph theme
ACCENT_HOVER = "#ff4b58"
GREEN     = "#5fd97a"
YELLOW    = "#f0c14b"
RED       = "#ff5c5c"
BLUE      = "#5fa8f0"
BORDER    = "#2c2c30"


def read_main_config() -> dict:
    """Best-effort scrape of key constants straight out of main.py so the
    hub always reflects the real values, even if you tweak main.py later."""
    cfg = {
        "hotkey": "e",
        "quit_key": "p",
        "confidence": "?",
        "margin": "?",
    }
    try:
        with open(MAIN_SCRIPT, encoding="utf-8-sig") as f:
            src = f.read()
        m = re.search(r"HOTKEY\s*:\s*str\s*=\s*['\"](\w+)['\"]", src)
        if m: cfg["hotkey"] = m.group(1)
        m = re.search(r"CONFIDENCE_THRESHOLD\s*:\s*float\s*=\s*([\d.]+)", src)
        if m: cfg["confidence"] = m.group(1)
        m = re.search(r"MARGIN_THRESHOLD\s*:\s*float\s*=\s*([\d.]+)", src)
        if m: cfg["margin"] = m.group(1)
        m = re.search(r"QUIT_KEY\s*:\s*str\s*=\s*['\"](\w+)['\"]", src)
        if m: cfg["quit_key"] = m.group(1)
        m = re.search(r"keyboard\.wait\(['\"](\w+)['\"]\)", src)
        if m: cfg["quit_key"] = m.group(1)
    except OSError:
        pass
    return cfg


def get_python_exe() -> str:
    """Return a real Python interpreter path to launch main.py with.

    sys.executable is only safe to use as-is when this hub itself is running
    as a plain .py script. If the hub has been packaged into a standalone
    .exe (PyInstaller, etc.), sys.executable points back at that .exe —
    using it to launch main.py would just relaunch the hub itself, which
    is why the "another hub window pops up" bug happens.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    for candidate in ("python", "python3", "py"):
        found = shutil.which(candidate)
        if found:
            return found

    raise RuntimeError(
        "Running as a packaged .exe, but no Python interpreter was found on "
        "PATH to launch main.py with. Install Python and make sure it's on "
        "PATH, or run macro_hub.py directly with 'python macro_hub.py' "
        "instead of a bundled .exe."
    )


def read_rois() -> list | None:
    if os.path.exists(ROI_FILE):
        try:
            with open(ROI_FILE) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    return None


# ══════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════

def acquire_single_instance_guard() -> bool:
    """Return False when another Hub for this folder is already running."""
    global _INSTANCE_GUARD_HANDLE

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
        if not handle:
            return True

        ERROR_ALREADY_EXISTS = 183
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False

        _INSTANCE_GUARD_HANDLE = handle
        atexit.register(lambda: kernel32.CloseHandle(_INSTANCE_GUARD_HANDLE))
        return True

    try:
        fd = os.open(APP_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return True

    with os.fdopen(fd, "w") as lock_file:
        lock_file.write(str(os.getpid()))

    atexit.register(lambda: os.path.exists(APP_LOCK_FILE) and os.unlink(APP_LOCK_FILE))
    return True


def show_already_running_message():
    text = "WASD Macro Hub is already running for this folder."
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, "WASD Macro Hub", 0x40)
            return
        except Exception:
            pass
    print(text)


class MacroHub(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WASD Macro Hub")
        self.geometry("760x560")
        self.minsize(640, 460)
        self.configure(bg=BG)

        self.proc: subprocess.Popen | None = None
        self.proc_mode: str | None = None      # "macro" | "calibrate"
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.debug_var = tk.BooleanVar(value=False)

        self._build_style()
        self._build_layout()
        self._refresh_info()
        self._poll_queue()

        if HAS_KEYBOARD:
            try:
                keyboard.add_hotkey(EMERGENCY_HOTKEY, self._emergency_stop)
            except Exception:
                pass

        if not os.path.exists(MAIN_SCRIPT):
            messagebox.showwarning(
                "macro_worker.py not found",
                f"Couldn't find macro_worker.py next to this hub:\n{MAIN_SCRIPT}"
            )

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── styling ──────────────────────────────────────────────────
    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCheckbutton", background=BG_PANEL, foreground=FG,
                         font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", BG_PANEL)])

    def _btn(self, parent, text, cmd, color=ACCENT, hover=ACCENT_HOVER, width=16):
        b = tk.Button(
            parent, text=text, command=cmd, width=width,
            bg=color, fg="white", activebackground=hover, activeforeground="white",
            font=("Segoe UI", 10, "bold"), relief="flat", bd=0, cursor="hand2",
            padx=8, pady=8,
        )
        b.bind("<Enter>", lambda e: b.config(bg=hover))
        b.bind("<Leave>", lambda e: b.config(bg=b._base_color))
        b._base_color = color
        return b

    # ── layout ───────────────────────────────────────────────────
    def _build_layout(self):
        # Header
        header = tk.Frame(self, bg=BG, pady=14, padx=18)
        header.pack(fill="x")
        tk.Label(header, text="⌨  WASD Macro Hub", bg=BG, fg=FG,
                  font=("Segoe UI", 16, "bold")).pack(side="left")

        self.status_dot = tk.Canvas(header, width=12, height=12, bg=BG, highlightthickness=0)
        self.status_dot.pack(side="right", padx=(0, 6))
        self.status_dot_id = self.status_dot.create_oval(1, 1, 11, 11, fill=FG_DIM, outline="")
        self.status_label = tk.Label(header, text="Idle", bg=BG, fg=FG_DIM,
                                      font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side="right")

        # Info card
        info = tk.Frame(self, bg=BG_CARD, padx=16, pady=12)
        info.pack(fill="x", padx=18, pady=(0, 12))
        self.info_labels: dict[str, tk.Label] = {}
        grid = tk.Frame(info, bg=BG_CARD)
        grid.pack(fill="x")
        fields = [
            ("hotkey", "Trigger key"),
            ("quit_key", "Quit key"),
            ("confidence", "Confidence thresh."),
            ("margin", "Margin thresh."),
            ("rois", "ROIs calibrated"),
        ]
        for i, (key, label) in enumerate(fields):
            col = i % 3
            row = i // 3
            cell = tk.Frame(grid, bg=BG_CARD)
            cell.grid(row=row, column=col, sticky="w", padx=(0, 28), pady=(0, 6))
            tk.Label(cell, text=label.upper(), bg=BG_CARD, fg=FG_DIM,
                      font=("Segoe UI", 8, "bold")).pack(anchor="w")
            val = tk.Label(cell, text="—", bg=BG_CARD, fg=FG, font=("Segoe UI", 11, "bold"))
            val.pack(anchor="w")
            self.info_labels[key] = val

        # Controls card
        controls = tk.Frame(self, bg=BG_PANEL, padx=16, pady=14)
        controls.pack(fill="x", padx=18)

        row1 = tk.Frame(controls, bg=BG_PANEL)
        row1.pack(fill="x", pady=(0, 10))
        self.start_btn = self._btn(row1, "▶  Start Macro", self.start_macro, color=GREEN, hover="#7cf497")
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = self._btn(row1, "⏹  Stop", self.stop_process, color=RED, hover="#ff7d7d")
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.calib_btn = self._btn(row1, "🎯  Calibrate ROIs", self.start_calibrate, color=BLUE, hover="#82c0ff")
        self.calib_btn.pack(side="left", padx=(0, 8))

        ttk.Checkbutton(row1, text="Debug mode (save debug images every cycle)",
                         variable=self.debug_var).pack(side="left", padx=(12, 0))

        row2 = tk.Frame(controls, bg=BG_PANEL)
        row2.pack(fill="x")
        self._btn(row2, "📂 Open ROI file", self.open_roi_file, color=BG_CARD,
                  hover=BORDER, width=16).pack(side="left", padx=(0, 8))
        self._btn(row2, "📂 Open debug folder", self.open_debug_folder, color=BG_CARD,
                  hover=BORDER, width=18).pack(side="left", padx=(0, 8))
        self._btn(row2, "🔄 Refresh info", self._refresh_info, color=BG_CARD,
                  hover=BORDER, width=14).pack(side="left", padx=(0, 8))
        self._btn(row2, "🧹 Clear log", self.clear_log, color=BG_CARD,
                  hover=BORDER, width=12).pack(side="left")

        if HAS_KEYBOARD:
            tk.Label(controls, text=f"Emergency stop: [{EMERGENCY_HOTKEY.upper()}] (works globally, even in-game)",
                      bg=BG_PANEL, fg=FG_DIM, font=("Segoe UI", 8, "italic")).pack(anchor="w", pady=(10, 0))
        else:
            tk.Label(controls, text="Install 'keyboard' package for the global emergency-stop hotkey.",
                      bg=BG_PANEL, fg=YELLOW, font=("Segoe UI", 8, "italic")).pack(anchor="w", pady=(10, 0))

        # Log console
        log_frame = tk.Frame(self, bg=BG, padx=18, pady=12)
        log_frame.pack(fill="both", expand=True)
        tk.Label(log_frame, text="LIVE CONSOLE", bg=BG, fg=FG_DIM,
                  font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 4))

        console_wrap = tk.Frame(log_frame, bg=BORDER, bd=1)
        console_wrap.pack(fill="both", expand=True)
        self.console = tk.Text(
            console_wrap, bg="#0e0e10", fg=FG, insertbackground=FG,
            font=("Consolas", 9), relief="flat", padx=10, pady=8, wrap="word",
            state="disabled",
        )
        scroll = tk.Scrollbar(console_wrap, command=self.console.yview)
        self.console.configure(yscrollcommand=scroll.set)
        self.console.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.console.tag_config("info", foreground=FG)
        self.console.tag_config("warning", foreground=YELLOW)
        self.console.tag_config("error", foreground=RED)
        self.console.tag_config("success", foreground=GREEN)
        self.console.tag_config("dim", foreground=FG_DIM)

        self._update_button_states()

    # ── info panel ───────────────────────────────────────────────
    def _refresh_info(self):
        cfg = read_main_config()
        self.info_labels["hotkey"].config(text=f"[{cfg['hotkey'].upper()}]")
        self.info_labels["quit_key"].config(text=f"[{cfg['quit_key'].upper()}]")
        self.info_labels["confidence"].config(text=cfg["confidence"])
        self.info_labels["margin"].config(text=cfg["margin"])

        rois = read_rois()
        if rois:
            self.info_labels["rois"].config(text=f"✓ {len(rois)} slots", fg=GREEN)
        else:
            self.info_labels["rois"].config(text="✗ not calibrated", fg=RED)

    # ── process management ──────────────────────────────────────
    def _launch(self, args: list[str], mode: str):
        if self.proc is not None:
            messagebox.showinfo("Already running", "Stop the current process first.")
            return
        if not os.path.exists(MAIN_SCRIPT):
            messagebox.showerror("macro_worker.py not found", f"Expected at:\n{MAIN_SCRIPT}")
            return

        try:
            python_exe = get_python_exe()
        except RuntimeError as e:
            messagebox.showerror("No Python interpreter found", str(e))
            return

        cmd = [python_exe, "-u", MAIN_SCRIPT] + args
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            self.proc = subprocess.Popen(
                cmd, cwd=BASE_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=creationflags,
            )
        except Exception as e:
            messagebox.showerror("Failed to launch", str(e))
            self.proc = None
            return

        self.proc_mode = mode
        threading.Thread(target=self._read_output, daemon=True).start()
        self._set_status(mode)
        self._update_button_states()

    def start_macro(self):
        args = ["--debug"] if self.debug_var.get() else []
        self._log(f"Launching macro{'  (debug mode)' if args else ''}...", "dim")
        self._launch(args, "macro")

    def start_calibrate(self):
        self._log("Launching calibration — hover each key center and press 1-5 in-game.", "dim")
        self._launch(["--calibrate"], "calibrate")

    def stop_process(self):
        if self.proc is None:
            return
        try:
            self.proc.terminate()
        except Exception:
            pass
        self._log("Stopped by user.", "warning")
        self.proc = None
        self.proc_mode = None
        self._set_status("idle")
        self._update_button_states()
        self._refresh_info()

    def _emergency_stop(self):
        # Called from the keyboard-hook thread — only touch thread-safe bits directly,
        # marshal the rest onto the Tk main loop.
        self.after(0, self.stop_process)

    def _read_output(self):
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self.log_queue.put(line.rstrip("\n"))
        proc.wait()
        self.log_queue.put("__PROC_DONE__")

    def _poll_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__PROC_DONE__":
                    if self.proc is not None:
                        self._log("Process ended.", "dim")
                    self.proc = None
                    self.proc_mode = None
                    self._set_status("idle")
                    self._update_button_states()
                    self._refresh_info()
                else:
                    self._route_log_line(line)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _route_log_line(self, line: str):
        low = line.upper()
        if " ERROR" in low or "TRACEBACK" in low or "ERROR:" in low:
            tag = "error"
        elif " WARNING" in low or "SKIPPED" in low:
            tag = "warning"
        elif "ACCEPTED]" in line and "5/5" in line:
            tag = "success"
        else:
            tag = "info"
        self._log(line, tag)

    # ── helpers ──────────────────────────────────────────────────
    def _log(self, text: str, tag: str = "info"):
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _set_status(self, mode: str):
        colors = {"idle": FG_DIM, "macro": GREEN, "calibrate": BLUE}
        labels = {"idle": "Idle", "macro": "● Macro running", "calibrate": "● Calibrating"}
        self.status_dot.itemconfig(self.status_dot_id, fill=colors.get(mode, FG_DIM))
        self.status_label.config(text=labels.get(mode, "Idle"), fg=colors.get(mode, FG_DIM))

    def _update_button_states(self):
        running = self.proc is not None
        self.start_btn.config(state="disabled" if running else "normal")
        self.calib_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")

    def open_roi_file(self):
        if not os.path.exists(ROI_FILE):
            messagebox.showinfo("No ROI file yet", "Run Calibrate ROIs first.")
            return
        self._open_path(ROI_FILE)

    def open_debug_folder(self):
        os.makedirs(DEBUG_DIR, exist_ok=True)
        self._open_path(DEBUG_DIR)

    @staticmethod
    def _open_path(path: str):
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Couldn't open", str(e))

    def _on_close(self):
        if self.proc is not None:
            if not messagebox.askyesno("Process running", "A process is still running. Stop it and quit?"):
                return
            self.stop_process()
        self.destroy()


if __name__ == "__main__":
    if not acquire_single_instance_guard():
        show_already_running_message()
        sys.exit(0)

    app = MacroHub()
    app.mainloop()
