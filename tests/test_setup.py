"""Setup-wizard pure-logic tests (no IO)."""
from unist_blackboard_mcp.setup_wizard import SERVER_NAME, build_server_entry, merge_mcp_config


def test_merge_preserves_other_servers_and_keys():
    existing = {"mcpServers": {"other": {"command": "x"}}, "globalShortcut": "Cmd+Y"}
    out = merge_mcp_config(existing, {"command": "uvx", "args": ["unist-blackboard-mcp", "serve"]})
    assert out["mcpServers"]["other"] == {"command": "x"}        # other servers untouched
    assert out["mcpServers"][SERVER_NAME]["command"] == "uvx"     # ours added
    assert out["globalShortcut"] == "Cmd+Y"                       # unrelated keys untouched


def test_merge_empty_or_none():
    assert SERVER_NAME in merge_mcp_config(None, {"command": "uvx", "args": []})["mcpServers"]
    assert SERVER_NAME in merge_mcp_config({}, {"command": "uvx", "args": []})["mcpServers"]


def test_merge_replaces_existing_same_name():
    existing = {"mcpServers": {SERVER_NAME: {"command": "old"}}}
    out = merge_mcp_config(existing, {"command": "uvx", "args": ["x"]})
    assert out["mcpServers"][SERVER_NAME]["command"] == "uvx"


def test_build_server_entry_shape():
    entry = build_server_entry()
    assert "command" in entry
    assert isinstance(entry["args"], list) and entry["args"][-1] == "serve"
