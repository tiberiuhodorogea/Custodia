import logging
import os
import shutil
import threading
import time
from datetime import datetime
from collections import deque

import database as db

log = logging.getLogger(__name__)


class BackupState:
    """Thread-safe shared state read by the WebSocket broadcaster."""

    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.cancel_requested = False
        self.phase = "idle"  # idle | scanning | copying | cleaning | done
        self.current_file = ""
        self.current_destination = ""
        self.files_total = 0
        self.files_copied = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.bytes_total = 0
        self.bytes_copied = 0
        self.started_at = None
        self.run_id = None
        # ring buffer for live log lines pushed to WS clients
        self._log_queue = deque(maxlen=500)
        self._log_lock = threading.Lock()

    def reset(self):
        with self._lock:
            self.cancel_requested = False
            self.phase = "idle"
            self.current_file = ""
            self.current_destination = ""
            self.files_total = 0
            self.files_copied = 0
            self.files_skipped = 0
            self.files_failed = 0
            self.bytes_total = 0
            self.bytes_copied = 0
            self.started_at = None
            self.run_id = None

    def push_log(self, level: str, message: str):
        with self._log_lock:
            self._log_queue.append(
                {
                    "level": level,
                    "message": message,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                }
            )

    def drain_logs(self):
        with self._log_lock:
            items = list(self._log_queue)
            self._log_queue.clear()
            return items

    def to_dict(self):
        with self._lock:
            elapsed = 0.0
            speed = 0.0
            if self.started_at and self.running:
                elapsed = (datetime.now() - self.started_at).total_seconds()
                if elapsed > 0:
                    speed = self.bytes_copied / elapsed
            return {
                "running": self.running,
                "cancel_requested": self.cancel_requested,
                "phase": self.phase,
                "current_file": self.current_file,
                "current_destination": self.current_destination,
                "files_total": self.files_total,
                "files_copied": self.files_copied,
                "files_skipped": self.files_skipped,
                "files_failed": self.files_failed,
                "bytes_total": self.bytes_total,
                "bytes_copied": self.bytes_copied,
                "elapsed_seconds": round(elapsed, 1),
                "speed_bps": round(speed),
                "run_id": self.run_id,
            }


# ── Shared singleton ────────────────────────────────────
state = BackupState()


def _log(run_id: int, level: str, msg: str):
    """Write to both the database and the live WS queue."""
    try:
        db.add_log(run_id, level, msg)
    except Exception:
        pass
    state.push_log(level, msg)


CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB copy chunks


def _copy_file(src: str, dst: str):
    """Copy a single file in chunks, updating byte progress on state."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            if state.cancel_requested:
                raise InterruptedError("cancelled")
            chunk = fsrc.read(CHUNK_SIZE)
            if not chunk:
                break
            fdst.write(chunk)
            state.bytes_copied += len(chunk)
    # preserve timestamps
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass


def _scan_sources(sources):
    """Walk all enabled sources and return list of file descriptors."""
    files = []
    for src in sources:
        src_path = src["path"]
        label = src["label"]
        if not os.path.isdir(src_path):
            state.push_log("warning", f"Source path not found: {src_path}")
            continue
        for root, _dirs, filenames in os.walk(src_path):
            for fname in filenames:
                full = os.path.join(root, fname)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                rel = os.path.relpath(full, src_path)
                files.append(
                    {
                        "label": label,
                        "src_root": src_path,
                        "rel": rel,
                        "full": full,
                        "size": size,
                    }
                )
    return files


def _cleanup_old_backups(dest_path: str, keep: int):
    """Remove oldest backup_* folders exceeding retention count."""
    try:
        dirs = sorted(
            d
            for d in os.listdir(dest_path)
            if d.startswith("backup_") and os.path.isdir(os.path.join(dest_path, d))
        )
    except OSError:
        return
    while len(dirs) > keep:
        oldest = dirs.pop(0)
        target = os.path.join(dest_path, oldest)
        try:
            shutil.rmtree(target)
        except Exception as exc:
            state.push_log("warning", f"Failed to remove old backup {target}: {exc}")


def run_backup():
    """Execute a full backup.  Intended to run in a background thread."""
    if state.running:
        return
    state.reset()
    state.running = True
    state.started_at = datetime.now()
    state.phase = "scanning"

    run_id = db.create_run()
    state.run_id = run_id
    log.info("Backup run #%d started", run_id)
    _log(run_id, "info", "Backup started")

    try:
        sources = [s for s in db.get_sources() if s["enabled"]]
        destinations = [d for d in db.get_destinations() if d["enabled"]]

        if not sources:
            _log(run_id, "error", "No enabled sources configured")
            db.complete_run(run_id, "failed", error_message="No sources")
            return
        if not destinations:
            _log(run_id, "error", "No enabled destinations configured")
            db.complete_run(run_id, "failed", error_message="No destinations")
            return

        # ── Scan ────────────────────────────────────────
        _log(run_id, "info", f"Scanning {len(sources)} source(s)...")
        all_files = _scan_sources(sources)

        total_files = len(all_files) * len(destinations)
        total_bytes = sum(f["size"] for f in all_files) * len(destinations)
        state.files_total = total_files
        state.bytes_total = total_bytes
        _log(
            run_id,
            "info",
            f"Found {len(all_files)} files "
            f"({_fmt_bytes(total_bytes // max(len(destinations),1))}) "
            f"→ {len(destinations)} destination(s)",
        )

        # ── Copy ────────────────────────────────────────
        state.phase = "copying"
        settings = db.get_settings()
        retention = int(settings.get("retention_count", "3"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for dest in destinations:
            dest_path = dest["path"]
            state.current_destination = dest["label"]

            backup_dir = os.path.join(dest_path, f"backup_{timestamp}")
            try:
                os.makedirs(backup_dir, exist_ok=True)
            except OSError as exc:
                _log(run_id, "error", f"Cannot create {backup_dir}: {exc}")
                state.files_failed += len(all_files)
                continue

            _log(run_id, "info", f"Copying to {dest['label']} ({dest_path})")

            cancelled = False
            for finfo in all_files:
                if state.cancel_requested:
                    cancelled = True
                    break

                dst = os.path.join(backup_dir, finfo["label"], finfo["rel"])
                state.current_file = finfo["rel"]
                try:
                    _copy_file(finfo["full"], dst)
                    state.files_copied += 1
                except InterruptedError:
                    cancelled = True
                    break
                except PermissionError:
                    state.files_skipped += 1
                    _log(
                        run_id,
                        "warning",
                        f"Skipped (locked/permission): {finfo['full']}",
                    )
                except Exception as exc:
                    state.files_failed += 1
                    _log(run_id, "error", f"Failed to copy {finfo['full']}: {exc}")

            if cancelled:
                # Remove the incomplete backup folder so it doesn't pollute
                # the destination or count against the retention limit.
                _log(run_id, "warning", f"Removing incomplete backup: {backup_dir}")
                try:
                    shutil.rmtree(backup_dir)
                except Exception as exc:
                    _log(run_id, "warning", f"Could not remove {backup_dir}: {exc}")
                _log(run_id, "warning", "Backup cancelled by user")
                db.complete_run(
                    run_id,
                    "cancelled",
                    files_total=state.files_total,
                    files_copied=state.files_copied,
                    files_skipped=state.files_skipped,
                    files_failed=state.files_failed,
                    bytes_total=state.bytes_total,
                    bytes_copied=state.bytes_copied,
                )
                return

        # ── Cleanup ─────────────────────────────────────
        state.phase = "cleaning"
        _log(run_id, "info", f"Cleaning old backups (keeping {retention})")
        for dest in destinations:
            _cleanup_old_backups(dest["path"], retention)

        # ── Done ────────────────────────────────────────
        state.phase = "done"
        status = "completed"
        err = None
        if state.files_failed > 0 or state.files_skipped > 0:
            status = "completed_with_warnings"
            err = (
                f"{state.files_skipped} skipped, {state.files_failed} failed"
            )
        _log(
            run_id,
            "info",
            f"Backup finished — {state.files_copied} copied, "
            f"{state.files_skipped} skipped, {state.files_failed} failed",
        )
        db.complete_run(
            run_id,
            status,
            files_total=state.files_total,
            files_copied=state.files_copied,
            files_skipped=state.files_skipped,
            files_failed=state.files_failed,
            bytes_total=state.bytes_total,
            bytes_copied=state.bytes_copied,
            error_message=err,
        )
        if status == "completed":
            log.info("Backup run #%d completed: %d files, %s",
                     run_id, state.files_copied, _fmt_bytes(state.bytes_copied))
        else:
            log.warning("Backup run #%d completed with warnings: %s",
                        run_id, err)

    except Exception as exc:
        log.exception("Backup run #%d failed with unhandled exception", run_id)
        _log(run_id, "error", f"Backup failed: {exc}")
        db.complete_run(run_id, "failed", error_message=str(exc))
    finally:
        state.running = False
        state.phase = "idle"
        state.current_file = ""
        state.current_destination = ""


def cancel_backup():
    state.cancel_requested = True


def start_backup_thread():
    """Spawn a daemon thread to run the backup."""
    if state.running:
        return False
    t = threading.Thread(target=run_backup, daemon=True)
    t.start()
    return True


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
