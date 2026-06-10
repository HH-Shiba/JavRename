"""Tkinter GUI：執行緒安全版本
背景執行緒不直接操作任何 Tkinter 物件；日誌與完成事件一律經由
queue.Queue 傳遞，由主執行緒以 after() 輪詢消化。
"""
import asyncio
import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from . import config
from .logging_setup import LOG_FORMAT, init_logging
from .pipeline import process_files

logger = logging.getLogger("javrename")

POLL_INTERVAL_MS = 100


class QueueLogHandler(logging.Handler):
    """將日誌訊息放入佇列，由 GUI 主執行緒輪詢顯示（執行緒安全）"""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(LOG_FORMAT)

    def emit(self, record):
        self.log_queue.put(("log", self.format(record)))


class SettingsDialog:
    """設定對話框：編輯 config.settings 並持久化到 settings.json"""

    def __init__(self, parent: tk.Tk):
        s = config.settings
        self.win = tk.Toplevel(parent)
        self.win.title("設定")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()  # 模態

        form = tk.Frame(self.win)
        form.pack(padx=14, pady=10)
        row = 0

        def add_row(label_text, widget):
            nonlocal row
            tk.Label(form, text=label_text, anchor="w").grid(
                row=row, column=0, sticky="w", pady=3, padx=(0, 10))
            widget.grid(row=row, column=1, sticky="we", pady=3)
            row += 1

        # 檔名處理
        self.remove_strings_var = tk.StringVar(value=", ".join(s.remove_strings))
        add_row("雜訊字串（逗號分隔）:", tk.Entry(form, textvariable=self.remove_strings_var, width=42))

        self.extensions_var = tk.StringVar(value=", ".join(s.valid_extensions))
        add_row("支援副檔名（逗號分隔）:", tk.Entry(form, textvariable=self.extensions_var, width=42))

        # 網路
        self.concurrent_var = tk.IntVar(value=s.max_concurrent_requests)
        add_row("最大同時請求數:", tk.Spinbox(form, from_=1, to=20, textvariable=self.concurrent_var, width=6))

        self.retry_count_var = tk.IntVar(value=s.retry_count)
        add_row("請求失敗重試次數:", tk.Spinbox(form, from_=0, to=5, textvariable=self.retry_count_var, width=6))

        self.retry_backoff_var = tk.IntVar(value=s.retry_backoff)
        add_row("重試間隔基數（秒）:", tk.Spinbox(form, from_=1, to=30, textvariable=self.retry_backoff_var, width=6))

        self.timeout_var = tk.IntVar(value=s.request_timeout)
        add_row("單次請求逾時（秒）:", tk.Spinbox(form, from_=5, to=120, textvariable=self.timeout_var, width=6))

        # 歸檔
        self.strategy_var = tk.StringVar(value=s.actress_strategy)
        strategy_frame = tk.Frame(form)
        tk.Radiobutton(strategy_frame, text="第一位女優", value="first",
                       variable=self.strategy_var).pack(side=tk.LEFT)
        tk.Radiobutton(strategy_frame, text="多位串接（、）", value="all",
                       variable=self.strategy_var).pack(side=tk.LEFT, padx=(8, 0))
        add_row("資料夾命名策略:", strategy_frame)

        self.max_actresses_var = tk.IntVar(value=s.max_actresses_in_folder)
        add_row("多女優串接上限:", tk.Spinbox(form, from_=1, to=10, textvariable=self.max_actresses_var, width=6))

        self.failed_dir_var = tk.StringVar(value=s.failed_dir_name)
        add_row("失敗佇列目錄名:", tk.Entry(form, textvariable=self.failed_dir_var, width=20))

        # 按鈕列
        buttons = tk.Frame(self.win)
        buttons.pack(pady=(0, 12))
        tk.Button(buttons, text="儲存", width=10, command=self._save).pack(side=tk.LEFT, padx=6)
        tk.Button(buttons, text="取消", width=10, command=self.win.destroy).pack(side=tk.LEFT, padx=6)

    @staticmethod
    def _parse_list(raw: str) -> list[str]:
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _save(self):
        try:
            concurrent = int(self.concurrent_var.get())
            retry_count = int(self.retry_count_var.get())
            retry_backoff = int(self.retry_backoff_var.get())
            timeout = int(self.timeout_var.get())
            max_actresses = int(self.max_actresses_var.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("錯誤", "數值欄位必須為整數。", parent=self.win)
            return

        extensions = []
        for ext in self._parse_list(self.extensions_var.get()):
            ext = ext.lower()
            if not ext.startswith("."):
                ext = "." + ext
            if ext not in extensions:
                extensions.append(ext)
        if not extensions:
            messagebox.showerror("錯誤", "至少需要一個副檔名。", parent=self.win)
            return

        failed_dir = self.failed_dir_var.get().strip()
        if not failed_dir:
            messagebox.showerror("錯誤", "失敗佇列目錄名不可為空。", parent=self.win)
            return

        s = config.settings
        s.remove_strings = self._parse_list(self.remove_strings_var.get())
        s.valid_extensions = extensions
        s.max_concurrent_requests = max(1, concurrent)
        s.retry_count = max(0, retry_count)
        s.retry_backoff = max(1, retry_backoff)
        s.request_timeout = max(5, timeout)
        s.actress_strategy = self.strategy_var.get()
        s.max_actresses_in_folder = max(1, max_actresses)
        s.failed_dir_name = failed_dir

        try:
            s.save()
        except OSError as e:
            messagebox.showerror("錯誤", f"設定檔寫入失敗: {e}", parent=self.win)
            return

        logger.info(f"設定已更新並儲存至 {config.SETTINGS_FILE}")
        self.win.destroy()


class App:
    def __init__(self):
        init_logging()
        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self.root = tk.Tk()
        self.root.title("JavRename - JAV 影片自動歸檔")

        # 上方：目錄選擇
        top = tk.Frame(self.root)
        top.pack(fill=tk.X, padx=10, pady=(10, 4))
        tk.Label(top, text="影片根目錄:").pack(side=tk.LEFT)
        self.folder_var = tk.StringVar()
        tk.Entry(top, textvariable=self.folder_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        tk.Button(top, text="瀏覽...", command=self._browse).pack(side=tk.LEFT)

        # 中間：選項與開始按鈕
        options = tk.Frame(self.root)
        options.pack(fill=tk.X, padx=10)
        self.dry_run_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            options,
            text="預覽模式（只顯示將執行的搬移，不實際搬移檔案）",
            variable=self.dry_run_var,
        ).pack(side=tk.LEFT)
        self.start_btn = tk.Button(options, text="開始處理", width=12, command=self._start)
        self.start_btn.pack(side=tk.RIGHT, pady=4)
        self.settings_btn = tk.Button(options, text="設定...", width=8, command=self._open_settings)
        self.settings_btn.pack(side=tk.RIGHT, padx=(0, 6), pady=4)

        # 下方：日誌顯示
        body = tk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        scrollbar = tk.Scrollbar(body)
        self.log_text = tk.Text(body, height=24, width=100, yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.gui_handler = QueueLogHandler(self.log_queue)
        logger.addHandler(self.gui_handler)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(POLL_INTERVAL_MS, self._poll_log_queue)

    # ---- 事件處理（皆在主執行緒） ----

    def _browse(self):
        folder = filedialog.askdirectory(title="請選擇要處理的影片根目錄 (例如 E:\\H\\Beauty)")
        if folder:
            self.folder_var.set(folder)

    def _open_settings(self):
        SettingsDialog(self.root)

    def _start(self):
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("錯誤", "請先選擇影片根目錄。")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("錯誤", f"目標目錄不存在: {folder}")
            return

        self.start_btn.config(state=tk.DISABLED)
        self.settings_btn.config(state=tk.DISABLED)  # 處理中不可改設定，避免行為不一致
        dry_run = self.dry_run_var.get()
        self.worker = threading.Thread(
            target=self._run_worker, args=(folder, dry_run), daemon=True)
        self.worker.start()

    def _poll_log_queue(self):
        """主執行緒輪詢佇列：顯示日誌、處理完成事件"""
        while True:
            try:
                kind, payload = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log_text.insert(tk.END, payload + "\n")
                self.log_text.see(tk.END)
            elif kind == "done":
                self.start_btn.config(state=tk.NORMAL)
                self.settings_btn.config(state=tk.NORMAL)
                if payload:
                    messagebox.showerror("程式錯誤", f"處理過程中發生嚴重錯誤: {payload}")
                else:
                    messagebox.showinfo("完成", "所有檔案處理已完成！")
        self.root.after(POLL_INTERVAL_MS, self._poll_log_queue)

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel("確認", "處理仍在進行中，確定要關閉嗎？"):
                return
        logger.removeHandler(self.gui_handler)
        self.root.destroy()

    # ---- 背景執行緒：禁止操作 Tkinter，結果經由 queue 回傳 ----

    def _run_worker(self, folder: str, dry_run: bool):
        try:
            asyncio.run(process_files(folder, dry_run=dry_run))
            self.log_queue.put(("done", None))
        except Exception as e:
            logger.error(f"程式執行出錯: {type(e).__name__}: {e}")
            self.log_queue.put(("done", str(e)))

    def run(self):
        self.root.mainloop()


def main():
    App().run()
