"""`unist-blackboard-mcp doctor` — a self-check so students can troubleshoot their own setup.

Each check returns (status, hint); one failing check never aborts the rest. Output goes to stderr
(stdout stays clean), and the process exit code is non-zero if any check FAILs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _check(name: str, fn):
    try:
        status, hint = fn()
    except Exception as e:  # noqa: BLE001
        status, hint = "FAIL", f"{type(e).__name__}: {e}"
    return {"check": name, "status": status, "hint": hint}


def _py():
    ok = sys.version_info >= (3, 10)
    v = f"{sys.version_info.major}.{sys.version_info.minor}"
    return ("PASS" if ok else "FAIL"), (f"Python {v}" + ("" if ok else " — need 3.10+"))


def _deps():
    missing = [m for m in ("mcp", "httpx", "keyring", "playwright", "pypdf")
               if __import__("importlib").util.find_spec(m) is None]
    return ("PASS" if not missing else "FAIL"), ("all installed" if not missing
            else f"missing {missing} — run: uv pip install -e .")


def _chromium():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return "FAIL", "playwright not installed"
    with sync_playwright() as p:
        path = p.chromium.executable_path
    ok = bool(path) and Path(path).exists()
    return ("PASS" if ok else "FAIL"), (path if ok else "run: python -m playwright install chromium")


def _keychain():
    import keyring
    kr = keyring.get_keyring()
    mod = kr.__class__.__module__
    bad = "fail" in mod or "null" in mod
    return ("WARN" if bad else "PASS"), type(kr).__name__ + (
        " — no usable keychain; install keyrings.alt" if bad else "")


def _host():
    from . import config  # import validates BB_HOST is https
    return "PASS", config.HOST


def _session():
    from .auth import AuthManager
    st = AuthManager().status()
    if st.get("authenticated"):
        return "PASS", (f"{st['cookie_count']} cookies, silent_refresh={st.get('can_silent_refresh')}, "
                        f"age {st.get('age_seconds')}s")
    return "FAIL", "no stored session — run `unist-blackboard-mcp login`"


def _live():
    import asyncio

    from .client import AuthExpired, BlackboardClient, Forbidden, NotAuthenticated

    async def go():
        c = BlackboardClient()
        try:
            await c.whoami()
            return "PASS", "session works (whoami OK)"
        except NotAuthenticated:
            return "FAIL", "no session — run login"
        except AuthExpired:
            return "WARN", "session expired and silent refresh failed — run login"
        except Forbidden:
            return "PASS", "cookie valid (some resources restricted, as expected)"
        finally:
            await c.aclose()

    return asyncio.run(go())


def _registered():
    from .setup_wizard import SERVER_NAME, claude_desktop_config_path
    found = []
    p = claude_desktop_config_path()
    if p.exists():
        try:
            if SERVER_NAME in (json.loads(p.read_text(encoding="utf-8")).get("mcpServers") or {}):
                found.append("Claude Desktop")
        except Exception:  # noqa: BLE001
            pass
    cc = Path.home() / ".claude.json"
    if cc.exists():
        try:
            data = json.loads(cc.read_text(encoding="utf-8"))
            if SERVER_NAME in (data.get("mcpServers") or {}):
                found.append("Claude Code (user)")
            elif any(SERVER_NAME in (proj.get("mcpServers") or {}) for proj in (data.get("projects") or {}).values()):
                found.append("Claude Code (project)")
        except Exception:  # noqa: BLE001
            pass
    return ("PASS" if found else "WARN"), (", ".join(found) if found
            else "not registered — run `setup` or `claude mcp add`")


def run_doctor() -> int:
    checks = [
        _check("python", _py),
        _check("dependencies", _deps),
        _check("chromium", _chromium),
        _check("keychain", _keychain),
        _check("host", _host),
        _check("session", _session),
        _check("live", _live),
        _check("registered", _registered),
    ]
    for c in checks:
        print(f"[{c['status']:4}] {c['check']:14} {c['hint']}", file=sys.stderr)
    failed = [c for c in checks if c["status"] == "FAIL"]
    print(json.dumps({"ok": not failed, "checks": checks}, ensure_ascii=False), file=sys.stderr)
    return 1 if failed else 0
