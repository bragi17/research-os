"""In-process local PTY sessions for the embedded production terminal."""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
from pathlib import Path
from uuid import UUID

from apps.worker.production.child_env import scrubbed_child_env


class LocalPtySession:
    """A lightweight local PTY wrapper used by the web terminal WebSocket."""

    def __init__(
        self,
        *,
        session_id: UUID,
        process: subprocess.Popen[bytes],
        master_fd: int,
    ) -> None:
        self.session_id = session_id
        self.process = process
        self.master_fd = master_fd
        self._closed = False
        os.set_blocking(master_fd, False)

    @classmethod
    def open(
        cls,
        *,
        session_id: UUID,
        cwd: Path,
        shell: str,
        rows: int = 24,
        cols: int = 80,
    ) -> LocalPtySession:
        master_fd, slave_fd = pty.openpty()
        try:
            process = subprocess.Popen(
                [shell],
                cwd=str(cwd),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=scrubbed_child_env(),
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(slave_fd)
        session = cls(session_id=session_id, process=process, master_fd=master_fd)
        session.resize(rows=rows, cols=cols)
        return session

    @property
    def closed(self) -> bool:
        return self._closed or self.process.poll() is not None

    async def read(self) -> str | None:
        if self.closed:
            return None
        try:
            data = os.read(self.master_fd, 4096)
        except BlockingIOError:
            await asyncio.sleep(0.03)
            return ""
        except OSError:
            return None
        if not data:
            return None
        return data.decode("utf-8", errors="replace")

    def write(self, data: str) -> None:
        if self.closed:
            return
        os.write(self.master_fd, data.encode("utf-8", errors="replace"))

    def resize(self, *, rows: int, cols: int) -> None:
        if self.closed:
            return
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, packed)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
        except ProcessLookupError:
            pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass


class LocalTerminalManager:
    """Manage local PTY sessions keyed by persisted terminal session id."""

    def __init__(self) -> None:
        self._sessions: dict[UUID, LocalPtySession] = {}

    def open(
        self,
        *,
        session_id: UUID,
        cwd: Path,
        shell: str = "bash",
        rows: int = 24,
        cols: int = 80,
    ) -> LocalPtySession:
        existing = self._sessions.get(session_id)
        if existing and not existing.closed:
            return existing
        session = LocalPtySession.open(
            session_id=session_id,
            cwd=cwd,
            shell=shell,
            rows=rows,
            cols=cols,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: UUID) -> LocalPtySession | None:
        session = self._sessions.get(session_id)
        if session and session.closed:
            self._sessions.pop(session_id, None)
            return None
        return session

    def resize(self, session_id: UUID, *, rows: int, cols: int) -> bool:
        session = self.get(session_id)
        if session is None:
            return False
        session.resize(rows=rows, cols=cols)
        return True

    def close(self, session_id: UUID) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.close()
        return True


terminal_manager = LocalTerminalManager()
