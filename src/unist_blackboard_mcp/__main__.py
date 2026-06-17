"""CLI entrypoint.

  unist-blackboard-mcp            # run the MCP stdio server (default)
  unist-blackboard-mcp serve      # same
  unist-blackboard-mcp setup      # FIRST-TIME wizard: install browser, login, register in Claude
  unist-blackboard-mcp login      # open a browser, complete SSO+MFA, store cookies
  unist-blackboard-mcp refresh    # silent headless re-auth using stored SSO cookies (no MFA if valid)
  unist-blackboard-mcp doctor     # self-check: deps, browser, session, registration, live ping
  unist-blackboard-mcp status     # show stored-session status
  unist-blackboard-mcp logout     # clear stored cookies
  unist-blackboard-mcp version    # print version/environment bundle
  unist-blackboard-mcp probe      # Phase-0 diagnostic: which API surface accepts our cookies
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys

from . import __version__


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _version_bundle() -> dict:
    from importlib.metadata import version as _v
    deps = {}
    for name in ("mcp", "httpx", "keyring", "playwright", "pypdf"):
        try:
            deps[name] = _v(name)
        except Exception:  # noqa: BLE001
            deps[name] = "not installed"
    return {"unist-blackboard-mcp": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "dependencies": deps}


async def _probe() -> None:
    from .client import BlackboardClient
    client = BlackboardClient()
    try:
        _print(await client.probe())
    finally:
        await client.aclose()


async def _refresh() -> None:
    from .auth import AuthManager
    auth = AuthManager()
    ok = await auth.refresh_session_async(headless=True)
    print(json.dumps({"refreshed": ok, **auth.status()}, indent=2, ensure_ascii=False), file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(prog="unist-blackboard-mcp")
    parser.add_argument("--version", action="version", version=f"unist-blackboard-mcp {__version__}")
    parser.add_argument(
        "command", nargs="?", default="serve",
        choices=["serve", "setup", "login", "refresh", "doctor", "logout", "status", "version", "probe"],
    )
    args = parser.parse_args()

    if args.command == "serve":
        from .server import run
        run()
    elif args.command == "version":
        _print(_version_bundle())
    elif args.command == "doctor":
        from .doctor import run_doctor
        sys.exit(run_doctor())
    elif args.command == "setup":
        from .setup_wizard import run_setup
        run_setup()
    elif args.command == "login":
        from .auth import AuthManager
        AuthManager().interactive_login()
    elif args.command == "refresh":
        asyncio.run(_refresh())
    elif args.command == "logout":
        from .auth import AuthManager
        AuthManager().clear()
        print("Cleared stored Blackboard session.", file=sys.stderr)
    elif args.command == "status":
        from .auth import AuthManager
        _print(AuthManager().status())
    elif args.command == "probe":
        asyncio.run(_probe())


if __name__ == "__main__":
    main()
