"""A Model Context Protocol server over stdio, for servers that only offer tools.

Messages are JSON-RPC 2.0, one per line on stdin and stdout; anything else a server wants to
say goes to stderr. The server answers initialize, ping, tools/list and tools/call, ignores
notifications, and refuses any other request.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TextIO

PROTOCOL_VERSION = "2025-06-18"
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

type Json = dict[str, Any]


class ToolError(Exception):
    """A failure the client sees as the tool's result, with this message, rather than as an
    error of the protocol."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: Json
    run: Callable[[Json], str]

    def listing(self) -> Json:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def serve(
    name: str,
    version: str,
    tools: Sequence[Tool],
    instructions: str = "",
    reader: TextIO | Iterable[str] = sys.stdin,
    writer: TextIO = sys.stdout,
) -> None:
    """Answer requests from `reader` on `writer` until `reader` ends."""
    by_name = {tool.name: tool for tool in tools}
    for line in reader:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _send(writer, _error(None, PARSE_ERROR, "the line is not JSON"))
            continue
        reply = handle(message, name, version, by_name, instructions)
        if reply is not None:
            _send(writer, reply)


def handle(
    message: Any, name: str, version: str, tools: dict[str, Tool], instructions: str = ""
) -> Json | None:
    """The reply to one message; None for a notification."""
    if not isinstance(message, dict) or "method" not in message:
        return _error(
            message.get("id") if isinstance(message, dict) else None,
            INVALID_REQUEST,
            "not a request",
        )
    if "id" not in message:
        return None
    ident, method, params = message["id"], message["method"], message.get("params") or {}
    if method == "initialize":
        result: Json = {
            # The client's version is answered with its own: tools work the same in each
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": name, "version": version},
        }
        if instructions:
            result["instructions"] = instructions
        return _result(ident, result)
    if method == "ping":
        return _result(ident, {})
    if method == "tools/list":
        return _result(ident, {"tools": [tool.listing() for tool in tools.values()]})
    if method == "tools/call":
        tool = tools.get(params.get("name", ""))
        if tool is None:
            return _error(ident, INVALID_PARAMS, f"no tool named {params.get('name')!r}")
        return _result(ident, _call(tool, params.get("arguments") or {}))
    return _error(ident, METHOD_NOT_FOUND, f"no method {method!r}")


def _call(tool: Tool, arguments: Json) -> Json:
    try:
        text, failed = tool.run(arguments), False
    except ToolError as error:
        text, failed = str(error), True
    except Exception as error:  # noqa: BLE001 - a failing tool must not stop the server
        traceback.print_exc(file=sys.stderr)
        text, failed = f"{type(error).__name__}: {error}", True
    return {"content": [{"type": "text", "text": text}], "isError": failed}


def _result(ident: Any, result: Json) -> Json:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _error(ident: Any, code: int, message: str) -> Json:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def _send(writer: TextIO, message: Json) -> None:
    writer.write(json.dumps(message) + "\n")
    writer.flush()
