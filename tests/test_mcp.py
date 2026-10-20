"""The MCP server: its handshake, its refusals, and a part built through a tool call."""

from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from gridfinity.mcp import INSTRUCTIONS, NAME, tools
from solidcraft_script.mcp_server import serve
from solidcraft_script.runner import available


def exchange(*messages: dict) -> list[dict]:
    reader = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    writer = io.StringIO()
    serve(NAME, "test", tools(7878), INSTRUCTIONS, reader, writer)
    return [json.loads(line) for line in writer.getvalue().splitlines()]


def call(ident: int, name: str, arguments: dict) -> dict:
    params = {"name": name, "arguments": arguments}
    return {"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": params}


def test_handshake_lists_the_four_tools() -> None:
    hello = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26"},
    }
    ready = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    first, second = exchange(hello, ready, listing)
    assert first["result"]["protocolVersion"] == "2025-03-26"
    assert first["result"]["serverInfo"]["name"] == "gridfinity"
    assert "Gridfinity" in first["result"]["instructions"]
    # The notification gets no reply, so the listing answers second
    listed = {tool["name"]: tool for tool in second["result"]["tools"]}
    assert set(listed) == {"box", "baseplate", "clip", "collection"}
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in listed.values())


def test_unknown_methods_and_tools_are_refused() -> None:
    method, tool = exchange(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, call(2, "drawer", {})
    )
    assert method["error"]["code"] == -32601
    assert tool["error"]["code"] == -32602


def test_bad_arguments_come_back_as_tool_errors() -> None:
    unknown, out_of_range = exchange(
        call(1, "box", {"units_z": 3, "live": False}), call(2, "box", {"height": 1, "live": False})
    )
    assert unknown["result"]["isError"] and "units_z" in unknown["result"]["content"][0]["text"]
    assert out_of_range["result"]["isError"]
    assert "units_z = 1" in out_of_range["result"]["content"][0]["text"]


@pytest.mark.solidcraft
@pytest.mark.skipif(not available(), reason="solidcraft-cli is not on PATH")
def test_box_tool_builds_files_and_reports_its_settings(tmp_path) -> None:
    stl = tmp_path / "bin.stl"
    arguments = {
        "units": [2, 1],
        "split_top": True,
        "elements": [{"kind": "wall", "x": 12, "y": 0, "length": 12, "orientation": "y"}],
        "live": False,
        "outputs": [str(stl)],
    }
    (reply,) = exchange(call(1, "box", arguments))
    text = reply["result"]["content"][0]["text"]
    assert not reply["result"]["isError"], text
    assert "Bin " in text and "BinTop " in text
    assert stl.stat().st_size > 10_000
    settings = json.loads(text.split("settings:\n", 1)[1])
    assert settings["split_top"] is True and len(settings["elements"]) == 1


def test_server_answers_over_stdio() -> None:
    hello = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    done = subprocess.run(
        [sys.executable, "-c", "from gridfinity.mcp import main; main()"],
        input="".join(json.dumps(m) + "\n" for m in (hello, listing)),
        capture_output=True,
        text=True,
        timeout=60,
    )
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert len(replies[1]["result"]["tools"]) == 4
