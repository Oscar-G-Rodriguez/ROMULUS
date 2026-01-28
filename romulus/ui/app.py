"""Tkinter desktop UI for ROMULUS (no localhost required)."""

from __future__ import annotations

import contextlib
import json
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from romulus.backtest.engine import BacktestEngine
from romulus.backtest.suite import SuiteRunner
from romulus.cli.main import resolve_default_config_path
from romulus.config.schema import load_config, load_suite_config


@dataclass
class RunRequest:
    config_path: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    suite: bool


class QueueWriter:
    """Redirects stdout/stderr to a queue for UI display."""

    def __init__(self, output: queue.Queue[str]) -> None:
        self._queue = output

    def write(self, text: str) -> None:
        if not text:
            return
        self._queue.put(text)

    def flush(self) -> None:
        return


class RomulusUI:
    """Main UI window."""

    def __init__(self) -> None:
        self._root = tk.Tk()
        self._root.title("ROMULUS")
        self._root.geometry("1100x700")

        self._output_queue: queue.Queue[str] = queue.Queue()
        self._progress_text = tk.StringVar(value="Idle")

        self._build_layout()
        self._poll_output()

    def run(self) -> None:
        self._root.mainloop()

    def _build_layout(self) -> None:
        notebook = ttk.Notebook(self._root)
        notebook.pack(fill=tk.BOTH, expand=True)

        self._run_tab = ttk.Frame(notebook)
        self._suite_tab = ttk.Frame(notebook)
        self._runs_tab = ttk.Frame(notebook)

        notebook.add(self._run_tab, text="Run")
        notebook.add(self._suite_tab, text="Suite")
        notebook.add(self._runs_tab, text="Runs")

        self._build_run_tab(self._run_tab, suite=False)
        self._build_run_tab(self._suite_tab, suite=True)
        self._build_runs_tab(self._runs_tab)

        status = ttk.Label(self._root, textvariable=self._progress_text, anchor="w")
        status.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_run_tab(self, parent: ttk.Frame, suite: bool) -> None:
        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(frame, text="Config path:").grid(row=row, column=0, sticky="w")
        config_entry = ttk.Entry(frame, width=80)
        config_entry.grid(row=row, column=1, sticky="ew")
        browse_button = ttk.Button(
            frame,
            text="Browse",
            command=lambda: self._browse_config(config_entry),
        )
        browse_button.grid(row=row, column=2, padx=6)

        default_candidates = (
            [Path("configs/suite_default.yaml"), Path("configs/default.yaml")]
            if suite
            else [Path("configs/etf_equal_weight.yaml"), Path("configs/default.yaml")]
        )
        default_path = resolve_default_config_path(candidates=default_candidates)
        if default_path:
            config_entry.insert(0, str(default_path))

        row += 1
        ttk.Label(frame, text="Start date (YYYY-MM-DD):").grid(row=row, column=0, sticky="w")
        start_entry = ttk.Entry(frame)
        start_entry.grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Label(frame, text="End date (YYYY-MM-DD):").grid(row=row, column=0, sticky="w")
        end_entry = ttk.Entry(frame)
        end_entry.grid(row=row, column=1, sticky="w")

        row += 1
        run_button = ttk.Button(
            frame,
            text="Run Suite" if suite else "Run Backtest",
            command=lambda: self._submit_run(
                RunRequest(
                    config_path=config_entry.get().strip() or None,
                    start_date=start_entry.get().strip() or None,
                    end_date=end_entry.get().strip() or None,
                    suite=suite,
                ),
                run_button,
            ),
        )
        run_button.grid(row=row, column=0, pady=8)

        row += 1
        ttk.Label(frame, text="Log:").grid(row=row, column=0, sticky="w", pady=(10, 0))
        row += 1
        log_box = tk.Text(frame, height=18, wrap="word")
        log_box.grid(row=row, column=0, columnspan=3, sticky="nsew")

        scrollbar = ttk.Scrollbar(frame, command=log_box.yview)
        scrollbar.grid(row=row, column=3, sticky="ns")
        log_box.configure(yscrollcommand=scrollbar.set)

        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(row, weight=1)

        if suite:
            self._suite_log = log_box
        else:
            self._run_log = log_box

    def _build_runs_tab(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(frame)
        right = ttk.Frame(frame)
        left.pack(side=tk.LEFT, fill=tk.Y)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Runs:").pack(anchor="w")
        self._runs_list = tk.Listbox(left, width=45)
        self._runs_list.pack(fill=tk.Y, expand=True, side=tk.LEFT)
        scrollbar = ttk.Scrollbar(left, command=self._runs_list.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._runs_list.configure(yscrollcommand=scrollbar.set)

        refresh = ttk.Button(left, text="Refresh", command=self._refresh_runs)
        refresh.pack(pady=6)

        ttk.Label(right, text="Run details:").pack(anchor="w")
        self._run_details = tk.Text(right, wrap="word")
        self._run_details.pack(fill=tk.BOTH, expand=True)

        self._runs_list.bind("<<ListboxSelect>>", self._show_run_details)
        self._refresh_runs()

    def _browse_config(self, entry: ttk.Entry) -> None:
        path = filedialog.askopenfilename(
            title="Select config file",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
        )
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    def _submit_run(self, request: RunRequest, button: ttk.Button) -> None:
        if self._is_running():
            messagebox.showwarning("ROMULUS", "A run is already in progress.")
            return

        button.state(["disabled"])
        self._progress_text.set("Running...")
        target = self._run_suite if request.suite else self._run_backtest

        thread = threading.Thread(target=target, args=(request, button), daemon=True)
        thread.start()

    def _run_backtest(self, request: RunRequest, button: ttk.Button) -> None:
        self._execute_run(request, button, suite=False)

    def _run_suite(self, request: RunRequest, button: ttk.Button) -> None:
        self._execute_run(request, button, suite=True)

    def _execute_run(self, request: RunRequest, button: ttk.Button, suite: bool) -> None:
        writer = QueueWriter(self._output_queue)
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            try:
                config_path = self._resolve_config(request, suite)
                if config_path is None:
                    self._output_queue.put("No config path provided.\n")
                    return

                if suite:
                    config = load_suite_config(str(config_path))
                else:
                    config = load_config(str(config_path))

                if request.start_date:
                    config.backtest.start_date = request.start_date
                if request.end_date:
                    config.backtest.end_date = request.end_date

                self._output_queue.put(f"Using config: {config_path}\n")
                self._output_queue.put("Starting run...\n")

                if suite:
                    result = SuiteRunner().run(config)
                else:
                    result = BacktestEngine().run(config)

                self._output_queue.put(json.dumps(result, indent=2, default=str) + "\n")
                self._output_queue.put("Run complete.\n")
            except Exception as exc:
                self._output_queue.put(f"Error: {exc}\n")
            finally:
                button.state(["!disabled"])
                self._progress_text.set("Idle")
                self._refresh_runs()

    def _resolve_config(self, request: RunRequest, suite: bool) -> Optional[Path]:
        if request.config_path:
            return Path(request.config_path)
        candidates = (
            [Path("configs/suite_default.yaml"), Path("configs/default.yaml")]
            if suite
            else [Path("configs/etf_equal_weight.yaml"), Path("configs/default.yaml")]
        )
        return resolve_default_config_path(candidates=candidates)

    def _poll_output(self) -> None:
        while not self._output_queue.empty():
            text = self._output_queue.get()
            target = self._suite_log if "suite" in text.lower() else self._run_log
            target.insert(tk.END, text)
            target.see(tk.END)
            if "progress:" in text:
                self._progress_text.set(text.strip().replace("\r", ""))
        self._root.after(100, self._poll_output)

    def _refresh_runs(self) -> None:
        self._runs_list.delete(0, tk.END)
        run_dirs = []
        for base in (Path("outputs/runs"), Path("outputs/suite_runs")):
            if base.exists():
                run_dirs.extend([path for path in base.iterdir() if path.is_dir()])

        run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        self._runs_index = run_dirs
        for path in run_dirs:
            self._runs_list.insert(tk.END, path.name)

    def _show_run_details(self, _event: object) -> None:
        selection = self._runs_list.curselection()
        if not selection:
            return
        index = selection[0]
        run_path = self._runs_index[index]
        details = self._collect_run_details(run_path)
        self._run_details.delete("1.0", tk.END)
        self._run_details.insert(tk.END, details)

    def _collect_run_details(self, run_path: Path) -> str:
        parts = [f"Run: {run_path.name}", f"Path: {run_path}"]
        manifest_path = run_path / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            parts.append(f"Created: {manifest.get('created_at')}")
            parts.append(f"Config: {manifest.get('config_name')}")
            parts.append(f"Config hash: {manifest.get('config_hash')}")

        metrics_path = run_path / "metrics.json"
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            parts.append("Metrics:")
            for key, value in metrics.items():
                parts.append(f"  {key}: {value}")

        suite_summary = run_path / "suite_summary.json"
        if suite_summary.exists():
            summary = json.loads(suite_summary.read_text(encoding="utf-8"))
            best = summary.get("best_overall")
            if best:
                parts.append(f"Best strategy: {best.get('strategy')}")

        return "\n".join(parts)

    def _is_running(self) -> bool:
        return self._progress_text.get().startswith("Running")


def run_headless(
    config_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    suite: bool = False,
) -> dict:
    request = RunRequest(config_path=config_path, start_date=start_date, end_date=end_date, suite=suite)
    if suite:
        config = load_suite_config(config_path)
        if start_date:
            config.backtest.start_date = start_date
        if end_date:
            config.backtest.end_date = end_date
        return SuiteRunner().run(config)
    config = load_config(config_path)
    if start_date:
        config.backtest.start_date = start_date
    if end_date:
        config.backtest.end_date = end_date
    return BacktestEngine().run(config)


def launch_ui() -> None:
    app = RomulusUI()
    app.run()
