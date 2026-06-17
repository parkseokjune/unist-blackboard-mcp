"""`unist-blackboard-mcp setup` — one command to get a student fully running.

Steps: (1) ensure the Playwright Chromium browser is installed, (2) do the interactive
SSO+MFA login, (3) write/merge the Claude Desktop config so the server is registered.
Designed for students installing via `uvx unist-blackboard-mcp` — no repo clone, no editing
JSON by hand.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SERVER_NAME = "unist-blackboard"


def _log(*a: object) -> None:
    print(*a, file=sys.stderr, flush=True)


def build_server_entry() -> dict:
    """The command Claude should run to launch this server."""
    if shutil.which("uvx"):
        return {"command": "uvx", "args": ["unist-blackboard-mcp", "serve"]}
    return {"command": sys.executable, "args": ["-m", "unist_blackboard_mcp", "serve"]}


def merge_mcp_config(existing: dict | None, entry: dict, name: str = SERVER_NAME) -> dict:
    """Pure merge: add/replace our server under mcpServers, preserving everything else."""
    cfg = dict(existing or {})
    servers = dict(cfg.get("mcpServers") or {})
    servers[name] = entry
    cfg["mcpServers"] = servers
    return cfg


def claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform.startswith("win"):
        import os
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "Claude/claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"


def claude_desktop_installed() -> bool:
    """Best-effort check for Claude Desktop, so we don't write a config nothing reads."""
    if sys.platform == "darwin":
        return Path("/Applications/Claude.app").exists() or claude_desktop_config_path().parent.exists()
    return claude_desktop_config_path().parent.exists()


def _ensure_chromium() -> bool:
    _log("[1/3] Playwright용 Chromium 확인/설치 중... (최초 1회, 시간이 좀 걸립니다)")
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return True
    except Exception as e:  # noqa: BLE001
        _log(f"  ! Chromium 설치 실패: {e}\n  수동으로: python -m playwright install chromium")
        return False


def _write_desktop_config() -> Path | None:
    path = claude_desktop_config_path()
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _log(f"  ! 기존 설정을 못 읽음({path}) — 백업 후 새로 작성합니다.")
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)

    merged = merge_mcp_config(existing, build_server_entry())
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


_CLAUDE_CODE_CMD = (
    "claude mcp add --scope user --transport stdio unist-blackboard "
    "-- uvx unist-blackboard-mcp serve"
)


def run_setup() -> None:
    _log("=== UNIST Blackboard MCP 설치 마법사 ===")
    if not _ensure_chromium():
        _log("\n설치를 중단합니다. `python -m playwright install chromium` 실행 후 다시 시도하세요.")
        return

    _log("\n[2/3] UNIST Blackboard 로그인 — 브라우저에서 SSO + MFA를 완료하세요.")
    from .auth import AuthManager
    AuthManager().interactive_login()

    _log("\n[3/3] Claude에 서버를 등록합니다...")
    if claude_desktop_installed():
        path = _write_desktop_config()
        _log(
            f"  ✔ Claude Desktop 설정: {path}\n"
            "\n=== 완료! ===\n"
            "1) Claude Desktop을 완전히 종료 후 다시 실행하세요.\n"
            "2) Claude에게: \"이번 주 뭐 해야 해?\" / \"이번주 공지\" / \"운영체제 성적 정리해줘\"\n"
            "세션이 만료돼도 보통 MFA 없이 자동 재인증됩니다. 완전 만료 시 `uvx unist-blackboard-mcp login`.\n"
            f"(Claude Code 사용자는 대신: {_CLAUDE_CODE_CMD})"
        )
    else:
        _log(
            "  ! Claude Desktop이 보이지 않습니다.\n"
            "  • Claude Code를 쓰신다면 아래를 실행하세요:\n"
            f"      {_CLAUDE_CODE_CMD}\n"
            "  • Claude Desktop을 쓰실 거면 https://claude.ai/download 설치 후 "
            "`uvx unist-blackboard-mcp setup` 재실행.\n"
            "로그인 세션은 이미 저장됐습니다."
        )
