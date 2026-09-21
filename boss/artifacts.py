"""按执行实例管理日志、截图和 UI dump。

一次命令执行产生的文件必须能被整体归档，否则不同运行之间的截图和日志
很容易串在一起。 :class:`RunArtifacts` 为每次执行分配一个目录，并用同一
个递增序号给所有视觉工件命名，例如 ``001_dump.xml``、``002_screenshot.png``。
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import IO, Optional, Union


PathLike = Union[str, os.PathLike]


class RunInProgressError(RuntimeError):
    """已有另一条命令正在执行。"""


class RunArtifacts:
    """一个命令执行的文件上下文。

    默认目录是 ``logs/YYYYMMDD_HHMMSS``。同一秒内重复启动时追加两位序号，
    避免覆盖上一轮运行，同时保持目录名仍然以时间戳开头。
    """

    def __init__(
        self,
        directory: Path,
        started_at: Optional[datetime] = None,
        lock_handle: Optional[IO] = None,
        lock_path: Optional[Path] = None,
    ):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.started_at = started_at or datetime.now()
        self._sequence = 0
        self._lock = threading.Lock()
        self._run_lock_handle = lock_handle
        self._run_lock_path = Path(lock_path) if lock_path is not None else None
        self.log_path = self.directory / "run.log"
        # 提前创建日志文件：即使命令在连接设备前失败，也有本次执行的文件。
        self.log_path.touch(exist_ok=True)

    @classmethod
    def create(
        cls,
        base_dir: PathLike = "logs",
        now: Optional[datetime] = None,
    ) -> "RunArtifacts":
        started_at = now or datetime.now()
        stamp = started_at.strftime("%Y%m%d_%H%M%S")
        base = Path(base_dir)
        base.mkdir(parents=True, exist_ok=True)
        lock_path = base / ".run.lock"
        lock_handle = cls._acquire_lock(lock_path)

        suffix = 1
        while True:
            try:
                # mkdir(exist_ok=False) 让并发启动的两个进程不会选中同一目录。
                candidate = base / stamp
                if suffix > 1:
                    candidate = base / f"{stamp}_{suffix:02d}"
                candidate.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                suffix += 1
            except Exception:
                cls._release_lock(lock_handle, lock_path)
                raise
        try:
            return cls(
                candidate,
                started_at=started_at,
                lock_handle=lock_handle,
                lock_path=lock_path,
            )
        except Exception:
            cls._release_lock(lock_handle, lock_path)
            raise

    @staticmethod
    def _release_lock(handle: IO, lock_path: Path) -> None:
        try:
            handle.close()
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass

    @staticmethod
    def _acquire_lock(lock_path: Path) -> IO:
        """原子创建 ``.run.lock``，并在明显过期时清理孤儿锁。"""
        for _attempt in range(2):
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                handle = os.fdopen(fd, "w", encoding="utf-8")
                handle.write(f"pid={os.getpid()}\nstarted={time.time()}\n")
                handle.flush()
                return handle
            except FileExistsError as exc:
                if not RunArtifacts._stale_lock(lock_path):
                    raise RunInProgressError(
                        "已有另一个执行实例正在运行，请等待其结束后再试"
                    ) from exc
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    continue
        raise RunInProgressError("无法取得执行锁，请稍后重试")

    @staticmethod
    def _stale_lock(lock_path: Path) -> bool:
        try:
            content = lock_path.read_text(encoding="utf-8")
            pid_line = next(
                (line for line in content.splitlines() if line.startswith("pid=")),
                "",
            )
            pid = int(pid_line.split("=", 1)[1])
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            return True
        except (FileNotFoundError, ValueError, PermissionError, OSError):
            # 空文件/损坏文件只有在确实长时间未更新时才视为孤儿，避免误删
            # 另一个进程刚创建但还没写完内容的锁。
            try:
                return time.time() - lock_path.stat().st_mtime > 86400
            except OSError:
                return False

    @property
    def run_id(self) -> str:
        return self.directory.name

    def next_path(self, kind: str, extension: str) -> str:
        """分配一个带三位序号的文件路径。"""
        clean_kind = str(kind).strip().replace(" ", "_") or "artifact"
        clean_ext = str(extension).lstrip(".")
        with self._lock:
            self._sequence += 1
            filename = f"{self._sequence:03d}_{clean_kind}"
            if clean_ext:
                filename += f".{clean_ext}"
            return str(self.directory / filename)

    def screenshot_path(self, name: Optional[str] = None) -> str:
        extension = Path(name).suffix.lstrip(".") if name else ""
        extension = extension or "png"
        kind = Path(name).stem if name else "screenshot"
        return self.next_path(kind, extension)

    def dump_path(self, name: Optional[str] = None) -> str:
        extension = Path(name).suffix.lstrip(".") if name else ""
        extension = extension or "xml"
        kind = Path(name).stem if name else "dump"
        return self.next_path(kind, extension)

    def save_screenshot(self, device: object, name: Optional[str] = None) -> str:
        path = self.screenshot_path(name)
        device.screenshot(path)
        return path

    def save_dump(self, device: object, name: Optional[str] = None) -> str:
        path = self.dump_path(name)
        xml = device.dump_hierarchy()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(xml)
        return path

    def close(self) -> None:
        """释放串行执行锁。"""
        handle, self._run_lock_handle = self._run_lock_handle, None
        lock_path, self._run_lock_path = self._run_lock_path, None
        if handle is None:
            return
        try:
            handle.close()
        finally:
            if lock_path is not None:
                try:
                    lock_path.unlink()
                except OSError:
                    pass

    def __enter__(self) -> "RunArtifacts":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def __del__(self):  # pragma: no cover - 仅作为异常退出时的最后兜底。
        try:
            self.close()
        except Exception:
            pass


__all__ = ["RunArtifacts", "RunInProgressError"]
