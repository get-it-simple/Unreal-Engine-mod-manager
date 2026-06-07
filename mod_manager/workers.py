from __future__ import annotations

import multiprocessing as mp
import threading
import queue as _queue
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Picklable task functions (run inside worker processes)
# ---------------------------------------------------------------------------

def _run_import_batch(cfg: dict, tasks: list) -> tuple:
    from .mods import import_mod_file, import_mod_image
    imported, skipped = [], []
    for kind, path, mod_name, replace in tasks:
        if kind == "image":
            ok, msg = import_mod_image(cfg, mod_name, path)
        else:
            ok, msg = import_mod_file(cfg, path, replace)
        (imported if ok else skipped).append(msg)
    return imported, skipped


def _run_deactivate_batch(mods: list) -> int:
    from .mods import deactivate_mod
    for mod in mods:
        deactivate_mod(mod)
    return len(mods)


def _run_save_settings(cfg: dict, values: dict) -> dict:
    from .storage import save_config
    _NUMERIC = frozenset({
        "page_size", "max_mod_name_len", "max_preset_name_len", "max_label_name_len",
        "ui_scale_percent", "gui_font_size", "tile_size", "window_width", "window_height",
    })
    new_cfg = {**cfg}
    for key, value in values.items():
        numeric = str(value).rstrip("%")
        if key in _NUMERIC and numeric.isdigit():
            new_cfg[key] = int(numeric)
        else:
            new_cfg[key] = value
    save_config(new_cfg)
    return new_cfg


# ---------------------------------------------------------------------------
# Worker process entry point
# ---------------------------------------------------------------------------

def _worker_entry(fn: Callable, args: tuple, result_queue, task_id: str, file_key: str) -> None:
    try:
        result = fn(*args)
        result_queue.put((task_id, file_key, result, None))
    except Exception as exc:
        result_queue.put((task_id, file_key, None, exc))


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------

class WorkerPool:
    """
    Runs tasks in child processes.  Tasks sharing a file_key are serialised;
    tasks with different file_keys may run concurrently.
    """

    def __init__(self) -> None:
        self._ctx = mp.get_context("spawn")
        self._result_queue = self._ctx.Queue()
        self._pending: dict[str, list] = {}
        self._running: dict[str, mp.Process] = {}
        self._callbacks: dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def submit(self, file_key: str, fn: Callable, args: tuple = (), callback: Callable | None = None) -> str:
        with self._lock:
            self._counter += 1
            task_id = str(self._counter)
            if callback is not None:
                self._callbacks[task_id] = callback
            self._pending.setdefault(file_key, []).append((task_id, fn, args))
            proc = self._running.get(file_key)
            if proc is None or not proc.is_alive():
                self._dispatch(file_key)
        return task_id

    def _dispatch(self, file_key: str) -> None:
        pending = self._pending.get(file_key)
        if not pending:
            return
        task_id, fn, args = pending.pop(0)
        proc = self._ctx.Process(
            target=_worker_entry,
            args=(fn, args, self._result_queue, task_id, file_key),
            daemon=False,
        )
        proc.start()
        self._running[file_key] = proc

    def poll(self) -> list[tuple[str, Any, Exception | None]]:
        out: list = []
        try:
            while True:
                task_id, file_key, result, error = self._result_queue.get_nowait()
                out.append((task_id, result, error))
                with self._lock:
                    self._dispatch(file_key)
        except _queue.Empty:
            pass
        return out

    def fire_callbacks(self, polled: list) -> None:
        for task_id, result, error in polled:
            cb = self._callbacks.pop(task_id, None)
            if cb is not None:
                cb(result, error)

    def has_work(self) -> bool:
        with self._lock:
            return bool(self._callbacks)

    def shutdown(self) -> None:
        with self._lock:
            for proc in self._running.values():
                if proc.is_alive():
                    proc.terminate()
            self._running.clear()
            self._pending.clear()
            self._callbacks.clear()
