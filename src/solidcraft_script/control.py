"""Drive the running SolidCraft app over its control port (JSON lines on 127.0.0.1)."""

from __future__ import annotations

import itertools
import json
import os
import socket
import sys
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

from solidcraft_script.script import Json

DEFAULT_PORT = 7878
HOST = "127.0.0.1"
# The app answers a batch within an hour at most; a single request within a minute
TIMEOUT_S = 3700.0


class ControlError(RuntimeError):
    pass


class ControlClient:
    """One authenticated connection; requests run on the app's UI thread in order."""

    def __init__(
        self, port: int = DEFAULT_PORT, token: str | None = None, host: str = HOST
    ) -> None:
        self.port = port
        self.host = host
        self._token = (
            token
            or os.environ.get("SOLIDCRAFT_CONTROL_TOKEN")
            or token_path(port).read_text().strip()
        )
        self._ids = itertools.count(1)
        self._socket: socket.socket | None = None
        self._buffer = b""
        self._authenticated = False

    def __enter__(self) -> ControlClient:
        self._socket = socket.create_connection((self.host, self.port), timeout=TIMEOUT_S)
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None

    def request(self, method: str, params: Json | None = None) -> Any:
        if self._socket is None:
            raise ControlError("not connected; use the client as a context manager")
        message: Json = {
            "id": next(self._ids),
            "method": method,
            "params": params or {},
        }
        if not self._authenticated:
            message["token"] = self._token
        self._socket.sendall((json.dumps(message) + "\n").encode())
        reply = json.loads(self._read_line())
        if not reply.get("ok"):
            raise ControlError(f"{method}: {reply.get('error')}")
        self._authenticated = True
        return reply.get("result")

    def _read_line(self) -> bytes:
        assert self._socket is not None
        while b"\n" not in self._buffer:
            chunk = self._socket.recv(1 << 16)
            if not chunk:
                raise ControlError("the app closed the connection")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line

    def execute(self, command: str, params: Json | None = None) -> Any:
        return self.request("engine.execute", {"command": command, "params": params or {}})

    def batch(self, commands: Sequence[Json], rollback: bool = True) -> Json:
        """Run the steps in one undoable request; raises with the failing step."""
        result = self.request("engine.batch", {"commands": list(commands), "rollback": rollback})
        if failed := result.get("failed"):
            raise ControlError(f"step {failed['index']} ({failed['command']}): {failed['error']}")
        return result

    def inspect(self, measure: bool = True) -> Json:
        return self.request("document.inspect", {"measure": measure})


def token_path(port: int) -> Path:
    """Where the app writes this launch's token for `port`."""
    if folder := os.environ.get("SOLIDCRAFT_CONTROL_DIR"):
        return Path(folder) / f"{port}.token"
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "SolidCraft"
    elif sys.platform == "win32":
        base = Path(os.environ["LOCALAPPDATA"]) / "SolidCraft"
    else:
        base = (
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "solidcraft"
        )
    return base / "control" / f"{port}.token"
