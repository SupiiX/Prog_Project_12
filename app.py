#!/usr/bin/env python3
"""
Project 12: Mobile Tower Coverage Mapper - Tkinter launcher.
Buttons to run the pipeline and open the generated outputs.
"""
import os
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    OUTPUT_MAP_HTML, OUTPUT_GAP_HTML, OUTPUT_SIM_HTML,
    OUTPUT_HEATMAP_PNG, OUTPUT_GAP_PNG, OUTPUT_SIM_PNG,
)
import main as pipeline


class LauncherApp:
    """Small launcher window: run pipeline + open output files."""

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Mobile Tower Coverage Mapper")
        root.geometry("420x440")
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # --- Header ---
        ttk.Label(frame, text="Mobile Tower Coverage Mapper",
                  font=('Segoe UI', 13, 'bold')).pack(pady=(0, 4))
        ttk.Label(frame, text="Budapest - OpenCelliD",
                  font=('Segoe UI', 9), foreground='#666').pack(pady=(0, 14))

        # --- Status + progress ---
        self.status_var = tk.StringVar(value="Ready - press the button to run the pipeline.")
        ttk.Label(frame, textvariable=self.status_var,
                  foreground='#444', wraplength=380).pack(pady=(0, 8))

        self.progress = ttk.Progressbar(frame, mode='indeterminate', length=380)
        self.progress.pack(pady=(0, 12))

        # --- Run button ---
        self.run_btn = ttk.Button(frame, text="Run pipeline", command=self._on_run)
        self.run_btn.pack(fill=tk.X, pady=2)

        ttk.Separator(frame).pack(fill=tk.X, pady=8)

        # --- Open-result buttons ---
        ttk.Label(frame, text="Open results:",
                  font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 4))

        ttk.Button(frame, text="Coverage map (HTML)",
                   command=lambda: self._open(OUTPUT_MAP_HTML, in_browser=True)
                   ).pack(fill=tk.X, pady=2)
        ttk.Button(frame, text="Gap analysis (HTML)",
                   command=lambda: self._open(OUTPUT_GAP_HTML, in_browser=True)
                   ).pack(fill=tk.X, pady=2)
        ttk.Button(frame, text="Network expansion (HTML)",
                   command=lambda: self._open(OUTPUT_SIM_HTML, in_browser=True)
                   ).pack(fill=tk.X, pady=2)
        ttk.Separator(frame).pack(fill=tk.X, pady=4)
        ttk.Button(frame, text="Coverage overview (PNG)",
                   command=lambda: self._open(OUTPUT_HEATMAP_PNG)
                   ).pack(fill=tk.X, pady=2)
        ttk.Button(frame, text="Gap analysis (PNG)",
                   command=lambda: self._open(OUTPUT_GAP_PNG)
                   ).pack(fill=tk.X, pady=2)
        ttk.Button(frame, text="Network expansion (PNG)",
                   command=lambda: self._open(OUTPUT_SIM_PNG)
                   ).pack(fill=tk.X, pady=2)

    # --- Pipeline futtatas (worker thread) ---

    def _on_run(self):
        self.run_btn.configure(state='disabled')
        self.progress.start(10)
        self.status_var.set("Pipeline running... (this may take a minute)")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            pipeline.main()
            self.root.after(0, self._on_done)
        except Exception as e:
            err = str(e)
            self.root.after(0, lambda: self._on_error(err))

    def _on_done(self):
        self.progress.stop()
        self.run_btn.configure(state='normal')
        self.status_var.set("Done - outputs saved to the output/ folder.")

    def _on_error(self, msg: str):
        self.progress.stop()
        self.run_btn.configure(state='normal')
        self.status_var.set(f"Error: {msg}")
        messagebox.showerror("Pipeline failed", msg)

    # --- Fajlmegnyitas ---

    def _open(self, path: str, in_browser: bool = False):
        if not os.path.exists(path):
            messagebox.showwarning(
                "File not found",
                f"{path}\n\nRun the pipeline first."
            )
            return
        abs_path = os.path.abspath(path)
        if in_browser:
            webbrowser.open(abs_path)
        else:
            try:
                os.startfile(abs_path)  # Windows-only
            except AttributeError:
                # Fallback macOS / Linux
                import subprocess
                opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
                subprocess.run([opener, abs_path])


def main():
    root = tk.Tk()
    try:
        root.tk.call('tk', 'scaling', 1.25)
    except tk.TclError:
        pass
    LauncherApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
