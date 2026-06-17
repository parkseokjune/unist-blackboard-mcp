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


def _ensure_chromium() -> None:
    _log("[1/3] Playwright용 Chromium 확인/설치 중... (최초 1회, 시간이 좀 걸립니다)")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
    except Exception as e:  # noqa: BLE001
        _log(f"  ! Chromium 설치 실패: {e}\n  수동으로: python -m playwright install chromium")


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


def run_setup() -> None:
    _log("=== UNIST Blackboard MCP 설치 마법사 ===")
    _ensure_chromium()

    _log("\n[2/3] UNIST Blackboard 로그인 — 브라우저에서 SSO + MFA를 완료하세요.")
    from .auth import AuthManager
    AuthManager().interactive_login()

    _log("\n[3/3] Claude Desktop 설정에 서버를 등록합니다...")
    path = _write_desktop_config()
    _log(f"  ✔ 설정 작성: {path}")

    _log(
        "\n=== 완료! ===\n"
        "1) Claude Desktop을 완전히 종료 후 다시 실행하세요.\n"
        "2) Claude에게 이렇게 물어보세요:\n"
        "   - \"이번 주 뭐 해야 해?\"  (weekly_briefing)\n"
        "   - \"이번주 공지 알려줘\" / \"운영체제 성적 정리해줘\"\n"
        "세션이 만료돼도 자동으로 재인증됩니다(보통 MFA 없이). "
        "완전히 만료되면 `uvx unist-blackboard-mcp login` 한 번 더 실행하세요.\n"
        "(Claude Code 사용자는: claude mcp add --scope user --transport stdio "
        "unist-blackboard -- uvx unist-blackboard-mcp serve)"
    )
