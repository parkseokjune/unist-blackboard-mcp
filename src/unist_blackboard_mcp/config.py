"""Live-verified UNIST Blackboard constants (probed against the live server 2026-06-16).

All values are overridable via environment variables so the package can be pointed at
another Blackboard Learn institution (the only UNIST-specific bits are the host, the
SAML provider id `apId=_3282_1`, and the Azure AD tenant behind it).
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit


def _validate_host(url: str) -> str:
    """BB_HOST must be an https:// URL with a hostname.

    Session cookies are sent to this host, so allowing http:// (no TLS) or a bare/garbage value
    would risk leaking the BbRouter session cookie in cleartext or to the wrong host.
    """
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname:
        raise ValueError(f"BB_HOST must be an https:// URL with a hostname, got {url!r}")
    return url


# Canonical host. Avoid bb.unist.ac.kr (TLS cert SAN mismatch). unist.blackboard.com is a SaaS alias.
HOST = _validate_host(os.environ.get("BB_HOST", "https://blackboard.unist.ac.kr").rstrip("/"))

# Public REST API — documented + stable. Cookie-session auth confirmed enabled on this host.
PUBLIC_API = f"{HOST}/learn/api/public"
# Private / Ultra-UI API — what the web frontend calls; reliable fallback for cookie-session auth
# (used by `whoami` and by `probe` to detect which surface accepts our cookies).
PRIVATE_API = f"{HOST}/learn/api"

# SAML SSO entry point. Redirects to Microsoft Entra ID (tenant e8715ec0-6179-432a-a864-54ea4008adc2).
# MFA is enforced — login MUST be completed interactively by the human in a real browser.
SAML_LOGIN_URL = os.environ.get(
    "BB_SAML_LOGIN_URL",
    f"{HOST}/auth-saml/saml/login?apId=_3282_1&redirectUrl={HOST}/ultra",
)
# We consider login successful once the browser lands back on the Ultra base URL.
LOGIN_SUCCESS_PREFIX = os.environ.get("BB_LOGIN_SUCCESS_PREFIX", f"{HOST}/ultra")

# Cookie domains we keep after login (canonical vanity domain + SaaS slug + parent).
COOKIE_DOMAINS = ("blackboard.unist.ac.kr", "unist.blackboard.com", ".unist.ac.kr")

# OS keychain (via `keyring`) is where the harvested cookies live — never a plaintext file.
KEYRING_SERVICE = "unist-blackboard-mcp"
KEYRING_COOKIE_KEY = os.environ.get("BB_PROFILE", "default")

# Where downloaded course materials are written.
DOWNLOAD_DIR = os.path.expanduser(os.environ.get("BB_DOWNLOAD_DIR", "~/Downloads/unist-blackboard"))

HTTP_TIMEOUT = float(os.environ.get("BB_HTTP_TIMEOUT", "30"))
# Generous window for the human to complete SSO + MFA in the popped browser.
LOGIN_TIMEOUT_MS = int(os.environ.get("BB_LOGIN_TIMEOUT_MS", str(5 * 60 * 1000)))
# Headless silent-refresh: short — if the IdP shows an MFA wall we want to fail fast.
REFRESH_TIMEOUT_MS = int(os.environ.get("BB_REFRESH_TIMEOUT_MS", str(45 * 1000)))
# Background keep-alive ping interval (seconds) while the server is running.
KEEPALIVE_INTERVAL = int(os.environ.get("BB_KEEPALIVE_SECONDS", "600"))
# In-memory cache TTL (seconds) for the course-membership list (changes rarely).
COURSES_TTL = int(os.environ.get("BB_COURSES_TTL", "300"))
# Max concurrent in-flight HTTP requests (politeness to the LMS / avoid WAF rate-limits).
MAX_CONCURRENCY = int(os.environ.get("BB_MAX_CONCURRENCY", "6"))
# Soft cap on a tool's JSON output size (chars) so a huge result can't blow the client token budget.
MAX_OUTPUT_CHARS = int(os.environ.get("BB_MAX_OUTPUT_CHARS", "40000"))
USER_AGENT = os.environ.get("BB_USER_AGENT", "unist-blackboard-mcp/0.1 (+personal)")
