"""Complete native desktop workflow for ROMULUS (no localhost required)."""

from __future__ import annotations

import contextlib
import json
import os
import queue
import threading
from pathlib import Path
from typing import Optional

import yaml
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from romulus.backtest.engine import BacktestEngine
from romulus.backtest.progress import ProgressEvent
from romulus.backtest.suite import SuiteRunner
from romulus.calendar.trading_days import get_trading_days
from romulus.cli.main import resolve_default_config_path
from romulus.config.schema import SuiteConfig, load_config, load_suite_config
from romulus.data.coverage import build_coverage_index, inspect_cached_coverage
from romulus.data.ingestion import fetch_daily_data, generate_synthetic_daily_data
from romulus.data.universe import Universe
from romulus.runtime import collect_runtime_info, run_xgboost_device_diagnostic
from romulus.ui.presenters import RunPresenter


class QueueWriter:
    def __init__(self, output: queue.Queue[tuple[str, object]]) -> None:
        self.output = output

    def write(self, value: str) -> None:
        if value:
            self.output.put(("log", value))

    def flush(self) -> None:
        return


class RomulusUI:
    """ROMULUS setup, execution, comparison, and audit application."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ROMULUS — Regime-Aware Strategy Laboratory")
        self.root.geometry("1320x820")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self.coverage_ready = False
        self.current_run: Optional[Path] = None
        self.presenter: Optional[RunPresenter] = None

        self.status = tk.StringVar(value="Idle")
        self.current_date = tk.StringVar(value="No run active")
        self.progress_detail = tk.StringVar(value="0 of 0 decisions")
        self.progress_percent = tk.DoubleVar(value=0.0)
        self.config_path = tk.StringVar()
        self.data_source = tk.StringVar(value="synthetic")
        self.coverage_policy = tk.StringVar(value="dynamic")
        self.start_date = tk.StringVar()
        self.end_date = tk.StringVar()
        self.coverage_text = tk.StringVar(value="Inspect data before selecting dates.")

        self._build()
        self._load_default_config()
        self._refresh_runs()
        self.root.after(100, self._poll)

    def run(self) -> None:
        self.root.mainloop()

    def _build(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook = notebook
        self.tabs = {}
        for name in ("Setup", "Run", "Overview", "Champion Timeline", "ML Accuracy", "Decision Audit", "Runs", "Diagnostics"):
            frame = ttk.Frame(notebook)
            self.tabs[name] = frame
            notebook.add(frame, text=name)
        self._build_setup(self.tabs["Setup"])
        self._build_run(self.tabs["Run"])
        self.overview_canvas = tk.Canvas(self.tabs["Overview"], height=230, background="white", highlightthickness=0)
        self.overview_canvas.pack(fill=tk.X, padx=10, pady=(10, 0))
        self.overview_tree = self._table(self.tabs["Overview"], (
            "strategy", "total_return_pct", "cagr_pct", "annualized_volatility", "sharpe", "max_drawdown_pct", "turnover", "cost_drag"
        ))
        self.champion_tree = self._table(self.tabs["Champion Timeline"], (
            "decision_date", "fill_date", "market_regime", "incumbent", "challenger", "selected_strategy", "switched", "score_margin", "switch_reason"
        ))
        self.champion_tree.bind("<<TreeviewSelect>>", self._champion_selected)
        self.ml_tree = self._table(self.tabs["ML Accuracy"], (
            "strategy", "model_family", "target", "split", "series", "observations", "mae", "rmse", "directional_accuracy", "mean_rank_correlation", "top_selection_hit_rate"
        ))
        self.audit_text = tk.Text(self.tabs["Decision Audit"], wrap="word")
        self.audit_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._build_runs(self.tabs["Runs"])
        self._build_diagnostics(self.tabs["Diagnostics"])
        ttk.Label(self.root, textvariable=self.status, anchor="w").pack(fill=tk.X, side=tk.BOTTOM)

    def _build_setup(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Suite configuration").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.config_path).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Browse", command=self._browse_config).grid(row=0, column=2)
        ttk.Label(frame, text="Data source").grid(row=1, column=0, sticky="w", pady=8)
        source = ttk.Combobox(frame, textvariable=self.data_source, values=("synthetic", "cache", "yfinance"), state="readonly")
        source.grid(row=1, column=1, sticky="w", padx=8)
        source.bind("<<ComboboxSelected>>", lambda _event: self._invalidate_coverage())
        ttk.Label(frame, text="Coverage policy").grid(row=2, column=0, sticky="w")
        policy = ttk.Combobox(frame, textvariable=self.coverage_policy, values=("dynamic", "common"), state="readonly")
        policy.grid(row=2, column=1, sticky="w", padx=8)
        policy.bind("<<ComboboxSelected>>", lambda _event: self._invalidate_coverage())
        controls = ttk.Frame(frame)
        controls.grid(row=3, column=0, columnspan=3, sticky="w", pady=10)
        ttk.Button(controls, text="Inspect Coverage", command=self._inspect_coverage).pack(side=tk.LEFT)
        ttk.Button(controls, text="Download Configured Range", command=self._download_coverage).pack(side=tk.LEFT, padx=8)
        ttk.Label(frame, text="Start date").grid(row=4, column=0, sticky="w")
        self.start_picker = ttk.Combobox(frame, textvariable=self.start_date, state="disabled", width=16)
        self.start_picker.grid(row=4, column=1, sticky="w", padx=8)
        ttk.Label(frame, text="End date").grid(row=5, column=0, sticky="w", pady=8)
        self.end_picker = ttk.Combobox(frame, textvariable=self.end_date, state="disabled", width=16)
        self.end_picker.grid(row=5, column=1, sticky="w", padx=8)
        ttk.Label(frame, textvariable=self.coverage_text, justify=tk.LEFT, wraplength=1100).grid(
            row=6, column=0, columnspan=3, sticky="nw", pady=12
        )
        ttk.Label(
            frame,
            text="Dynamic eligibility admits later-inception assets when valid; common overlap waits for every selected asset.",
            foreground="#555555",
        ).grid(row=7, column=0, columnspan=3, sticky="w")
        editor_controls = ttk.Frame(frame)
        editor_controls.grid(row=8, column=0, columnspan=3, sticky="w", pady=(14, 4))
        ttk.Label(editor_controls, text="Advanced configuration (all engine settings)").pack(side=tk.LEFT)
        ttk.Button(editor_controls, text="Validate", command=self._validate_editor).pack(side=tk.LEFT, padx=8)
        ttk.Button(editor_controls, text="Save As…", command=self._save_config).pack(side=tk.LEFT)
        self.config_editor = tk.Text(frame, height=19, wrap="none")
        self.config_editor.grid(row=9, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(9, weight=1)

    def _build_run(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X)
        self.run_button = ttk.Button(buttons, text="Run ROMULUS Suite", command=self._start_run, state="disabled")
        self.run_button.pack(side=tk.LEFT)
        self.cancel_button = ttk.Button(buttons, text="Cancel Safely", command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(side=tk.LEFT, padx=8)
        ttk.Label(frame, textvariable=self.current_date, font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(18, 4))
        ttk.Label(frame, textvariable=self.progress_detail).pack(anchor="w")
        ttk.Progressbar(frame, variable=self.progress_percent, maximum=100).pack(fill=tk.X, pady=10)
        self.run_log = tk.Text(frame, height=28, wrap="word")
        self.run_log.pack(fill=tk.BOTH, expand=True)

    def _build_runs(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(frame)
        left.pack(side=tk.LEFT, fill=tk.Y)
        self.runs_list = tk.Listbox(left, width=44)
        self.runs_list.pack(fill=tk.BOTH, expand=True)
        self.runs_list.bind("<<ListboxSelect>>", self._run_selected)
        ttk.Button(left, text="Refresh", command=self._refresh_runs).pack(fill=tk.X, pady=6)
        ttk.Button(left, text="Open Artifact Folder", command=self._open_artifacts).pack(fill=tk.X)
        self.run_details = tk.Text(frame, wrap="word")
        self.run_details.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(12, 0))

    def _build_diagnostics(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Refresh Environment", command=self._refresh_diagnostics).pack(side=tk.LEFT)
        self.cuda_button = ttk.Button(controls, text="Test XGBoost CUDA", command=self._start_cuda_test)
        self.cuda_button.pack(side=tk.LEFT, padx=8)
        self.diagnostics_text = tk.Text(frame, wrap="word")
        self.diagnostics_text.pack(fill=tk.BOTH, expand=True, pady=10)
        self._refresh_diagnostics()

    @staticmethod
    def _table(parent: ttk.Frame, columns: tuple[str, ...]) -> ttk.Treeview:
        container = ttk.Frame(parent, padding=8)
        container.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(container, columns=columns, show="headings")
        xbar = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=tree.xview)
        ybar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        for column in columns:
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=145, anchor="w")
        return tree

    def _load_default_config(self) -> None:
        path = resolve_default_config_path(candidates=[Path("configs/suite_default.yaml")])
        if path:
            self.config_path.set(str(path))
            try:
                config = load_suite_config(str(path))
                self.config_editor.delete("1.0", tk.END)
                self.config_editor.insert("1.0", Path(path).read_text(encoding="utf-8"))
                self.data_source.set(config.data.source)
                self.coverage_policy.set(config.data.coverage_policy)
            except Exception:
                pass

    def _browse_config(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")])
        if path:
            self.config_path.set(path)
            self.config_editor.delete("1.0", tk.END)
            self.config_editor.insert("1.0", Path(path).read_text(encoding="utf-8"))
            self._invalidate_coverage()

    def _invalidate_coverage(self) -> None:
        self.coverage_ready = False
        self.start_picker.configure(state="disabled")
        self.end_picker.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.coverage_text.set("Coverage changed. Inspect data again before running.")

    def _coverage_inputs(self):
        config = self._config_from_editor()
        universe = Universe.load_from_json(config.universe.source)
        return config, universe.get_all_tickers()

    def _config_from_editor(self) -> SuiteConfig:
        raw = yaml.safe_load(self.config_editor.get("1.0", tk.END))
        return SuiteConfig(**raw)

    def _validate_editor(self) -> None:
        try:
            self._config_from_editor()
            messagebox.showinfo("Configuration", "Configuration is valid.")
            self._invalidate_coverage()
        except Exception as exc:
            messagebox.showerror("Configuration", str(exc))

    def _save_config(self) -> None:
        try:
            config = self._config_from_editor()
            path = filedialog.asksaveasfilename(defaultextension=".yaml", filetypes=[("YAML", "*.yaml")])
            if path:
                Path(path).write_text(yaml.safe_dump(config.model_dump(), sort_keys=False), encoding="utf-8")
                self.config_path.set(path)
        except Exception as exc:
            messagebox.showerror("Configuration", str(exc))

    def _inspect_coverage(self) -> None:
        try:
            config, tickers = self._coverage_inputs()
            source = self.data_source.get()
            policy = self.coverage_policy.get()
            if source == "synthetic":
                data = generate_synthetic_daily_data(tickers, config.backtest.start_date, config.backtest.end_date)
                coverage = build_coverage_index(
                    data, tickers, source="synthetic", policy=policy, minimum_observations=64
                )
            else:
                coverage = inspect_cached_coverage(
                    config.data.cache_dir, tickers, policy=policy, minimum_observations=64
                )
            if coverage.minimum_date is None or coverage.maximum_date is None:
                raise ValueError("No complete cached coverage found. Download the configured range or choose Synthetic.")
            dates = [item.isoformat() for item in get_trading_days(coverage.minimum_date, coverage.maximum_date)]
            self.start_picker.configure(values=dates, state="readonly")
            self.end_picker.configure(values=dates, state="readonly")
            self.start_date.set(max(config.backtest.start_date, coverage.minimum_date))
            self.end_date.set(min(config.backtest.end_date, coverage.maximum_date))
            gaps = sum(item.gap_count for item in coverage.tickers)
            if gaps:
                raise ValueError(
                    f"Coverage contains {gaps} unresolved required-price gaps; repair the cache before running."
                )
            self.coverage_text.set(
                f"Usable range: {coverage.minimum_date} to {coverage.maximum_date}\n"
                f"Policy: {policy}; proxy: {coverage.proxy}; tickers: {len(coverage.tickers)}; business-day gaps flagged: {gaps}"
            )
            self.coverage_ready = True
            self.run_button.configure(state="normal")
        except Exception as exc:
            messagebox.showerror("Coverage inspection", str(exc))

    def _download_coverage(self) -> None:
        if self.data_source.get() != "yfinance":
            messagebox.showinfo("Data", "Downloading is only used for the yfinance source.")
            return
        if self.running:
            return
        try:
            config, tickers = self._coverage_inputs()
        except Exception as exc:
            messagebox.showerror("Configuration", str(exc))
            return
        self.running = True
        self.status.set("Downloading configured market-data range…")
        def worker() -> None:
            try:
                fetch_daily_data(tickers, config.backtest.start_date, config.backtest.end_date, config.data.cache_dir)
                self.events.put(("download_complete", None))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _start_run(self) -> None:
        if self.running or not self.coverage_ready:
            return
        if self.start_date.get() > self.end_date.get():
            messagebox.showerror("Dates", "Start date must not be after end date.")
            return
        try:
            config = self._config_from_editor()
            config.backtest.start_date = self.start_date.get()
            config.backtest.end_date = self.end_date.get()
            config.data.source = self.data_source.get()
            config.data.coverage_policy = self.coverage_policy.get()
            self.pending_config = config
        except Exception as exc:
            messagebox.showerror("Configuration", str(exc))
            return
        self.running = True
        self.cancel_event.clear()
        self.run_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress_percent.set(0)
        self.run_log.delete("1.0", tk.END)
        self.status.set("Running")
        self.notebook.select(self.tabs["Run"])
        threading.Thread(target=self._execute_run, daemon=True).start()

    def _execute_run(self) -> None:
        writer = QueueWriter(self.events)
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            try:
                result = SuiteRunner().run(
                    self.pending_config,
                    progress_callback=lambda event: self.events.put(("progress", event)),
                    cancel_requested=self.cancel_event.is_set,
                )
                self.events.put(("complete", result))
            except Exception as exc:
                self.events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _poll(self) -> None:
        while not self.events.empty():
            kind, payload = self.events.get()
            if kind == "log":
                self.run_log.insert(tk.END, str(payload))
                self.run_log.see(tk.END)
            elif kind == "progress":
                self._show_progress(payload)
            elif kind == "complete":
                result = dict(payload)
                self.running = False
                self.cancel_button.configure(state="disabled")
                self.run_button.configure(state="normal")
                self.status.set(str(result.get("status", "completed")).title())
                self._refresh_runs()
                self._load_run(Path(result["output_path"]))
            elif kind == "download_complete":
                self.running = False
                self.status.set("Download complete")
                self._inspect_coverage()
            elif kind == "diagnostic":
                self.running = False
                self.cuda_button.configure(state="normal")
                self.status.set("Idle")
                self.diagnostics_text.delete("1.0", tk.END)
                self.diagnostics_text.insert("1.0", json.dumps(payload, indent=2, default=str))
            elif kind == "error":
                self.running = False
                self.cancel_button.configure(state="disabled")
                self.run_button.configure(state="normal" if self.coverage_ready else "disabled")
                self.status.set("Failed")
                messagebox.showerror("ROMULUS", str(payload))
        self.root.after(100, self._poll)

    def _show_progress(self, event: ProgressEvent) -> None:
        self.progress_percent.set(event.overall_percent)
        self.status.set(event.stage.replace("_", " ").title())
        self.current_date.set(f"Processing {event.current_date}" if event.current_date else event.message)
        eta = f" • ETA {event.eta_seconds:.0f}s" if event.eta_seconds is not None else ""
        strategy = f" • {event.active_strategy}" if event.active_strategy else ""
        self.progress_detail.set(f"{event.completed} of {event.total} • {event.overall_percent:.1f}%{strategy}{eta}")

    def _refresh_runs(self) -> None:
        self.runs_list.delete(0, tk.END)
        runs = []
        for base in (
            Path("outputs/suite_runs"),
            Path("outputs/runs"),
            Path("outputs/offline_demo/suite_runs"),
        ):
            if base.exists():
                runs.extend(path for path in base.iterdir() if path.is_dir())
        self.run_paths = sorted(runs, key=lambda path: path.stat().st_mtime, reverse=True)
        for path in self.run_paths:
            self.runs_list.insert(tk.END, f"{path.name}  [{path.parent.name}]")

    def _run_selected(self, _event: object) -> None:
        selection = self.runs_list.curselection()
        if selection:
            self._load_run(self.run_paths[selection[0]])

    def _load_run(self, path: Path) -> None:
        self.current_run = path
        self.presenter = RunPresenter(path)
        self.run_details.delete("1.0", tk.END)
        self.run_details.insert("1.0", self.presenter.status_text())
        self._fill_tree(self.overview_tree, self.presenter.overview_rows())
        self._draw_equity(self.presenter.equity_series())
        self._fill_tree(self.champion_tree, self.presenter.champion_rows())
        self._fill_tree(self.ml_tree, self.presenter.ml_rows())

    @staticmethod
    def _fill_tree(tree: ttk.Treeview, rows: list[dict]) -> None:
        tree.delete(*tree.get_children())
        columns = tree["columns"]
        for row in rows:
            values = []
            for column in columns:
                value = row.get(column)
                if isinstance(value, float):
                    value = f"{value:.6g}"
                values.append("" if value is None else value)
            tree.insert("", tk.END, values=values)

    def _draw_equity(self, series: dict[str, list[tuple[str, float]]]) -> None:
        canvas = self.overview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 900)
        height = 230
        margin = 35
        colors = ("#2b6cb0", "#c53030", "#2f855a", "#805ad5", "#d69e2e", "#319795", "#718096")
        canvas.create_text(margin, 12, text="Normalized portfolio value (simulation)", anchor="w")
        for idx, (name, points) in enumerate(sorted(series.items())):
            if len(points) < 2 or points[0][1] == 0:
                continue
            values = [value / points[0][1] for _, value in points]
            all_values = [value / rows[0][1] for rows in series.values() if rows and rows[0][1] for _, value in rows]
            low, high = min(all_values), max(all_values)
            span = max(high - low, 1e-9)
            coords = []
            for point_index, value in enumerate(values):
                x = margin + point_index * (width - 2 * margin) / max(1, len(values) - 1)
                y = height - margin - (value - low) * (height - 2 * margin) / span
                coords.extend((x, y))
            color = colors[idx % len(colors)]
            canvas.create_line(*coords, fill=color, width=2)
            canvas.create_text(width - margin, 20 + idx * 15, text=name, fill=color, anchor="e")

    def _champion_selected(self, _event: object) -> None:
        if self.presenter is None:
            return
        selected = self.champion_tree.selection()
        if not selected:
            return
        decision_date = str(self.champion_tree.item(selected[0], "values")[0])
        audit = self.presenter.decision_audit(decision_date)
        self.audit_text.delete("1.0", tk.END)
        self.audit_text.insert("1.0", json.dumps(audit, indent=2, default=str))
        self.notebook.select(self.tabs["Decision Audit"])

    def _open_artifacts(self) -> None:
        if self.current_run is not None:
            os.startfile(self.current_run)  # type: ignore[attr-defined]

    def _refresh_diagnostics(self) -> None:
        self.diagnostics_text.delete("1.0", tk.END)
        self.diagnostics_text.insert("1.0", json.dumps(collect_runtime_info(), indent=2, default=str))

    def _start_cuda_test(self) -> None:
        if self.running:
            return
        self.running = True
        self.cuda_button.configure(state="disabled")
        self.status.set("Testing XGBoost CUDA")
        def worker() -> None:
            result = run_xgboost_device_diagnostic()
            self.events.put(("diagnostic", {"environment": collect_runtime_info(), "diagnostic": result}))
        threading.Thread(target=worker, daemon=True).start()


def run_headless(
    config_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    suite: bool = False,
) -> dict:
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
    RomulusUI().run()
