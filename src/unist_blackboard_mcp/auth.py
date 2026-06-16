"""Session-cookie auth: interactive login, OS-keychain storage, and silent SSO refresh.

UNIST Blackboard logs in via SAML -> Microsoft Entra ID (Azure AD) with enforced MFA, so we
cannot replay a username/password POST. We open a real browser, let the human complete SSO +
MFA once, then harvest ALL resulting cookies (Blackboard + Azure/ADFS) as full records.

Storing the Azure-side cookies too lets us later re-run the SAML flow HEADLESS: while the
Azure SSO session is still valid, the IdP issues a fresh assertion without a new MFA prompt,
giving us a new Blackboard session silently. Only when the Azure session itself has expired
does the user need to do the interactive (headful) login again.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field

import keyring

from . import config

# Cookies whose domain matches these are the ones sent to the Blackboard API host.
_BB_DOMAIN_SUFFIXES = ("unist.ac.kr", "blackboard.com")


def _log(*args: object) -> None:
    # NEVER print to stdout: in `serve` mode stdout is the JSON-RPC channel.
    print(*args, file=sys.stderr, flush=True)


def _is_bb_cookie(domain: str | None) -> bool:
    d = (domain or "").lstrip(".")
    return any(d == s or d.endswith("." + s) for s in _BB_DOMAIN_SUFFIXES)


def _sanitize_for_add(records: list[dict]) -> list[dict]:
    """Coerce stored cookie records into the shape Playwright's add_cookies accepts."""
    out: list[dict] = []
    for r in records:
        dom = r.get("domain")
        if not dom or not r.get("name"):
            continue
        c: dict = {"name": r["name"], "value": r.get("value", ""), "domain": dom, "path": r.get("path") or "/"}
        exp = r.get("expires")
        if isinstance(exp, (int, float)) and exp > 0:
            c["expires"] = exp
        if r.get("httpOnly") is not None:
            c["httpOnly"] = bool(r["httpOnly"])
        if r.get("secure") is not None:
            c["secure"] = bool(r["secure"])
        if r.get("sameSite") in ("Strict", "Lax", "None"):
            c["sameSite"] = r["sameSite"]
        out.append(c)
    return out


@dataclass
class Session:
    records: list[dict] = field(default_factory=list)  # full cookie records (all domains)
    pairs: dict[str, str] = field(default_factory=dict)  # name->value for the Blackboard host
    saved_at: float = 0.0


class AuthManager:
    def __init__(self, profile: str | None = None) -> None:
        self.service = config.KEYRING_SERVICE
        self.key = profile or config.KEYRING_COOKIE_KEY

    # ---- storage ----
    def save_records(self, records: list[dict]) -> None:
        pairs = {r["name"]: r.get("value", "") for r in records if _is_bb_cookie(r.get("domain"))}
        payload = {"version": 2, "records": records, "pairs": pairs, "saved_at": time.time()}
        keyring.set_password(self.service, self.key, json.dumps(payload))

    def load(self) -> Session | None:
        raw = keyring.get_password(self.service, self.key)
        if not raw:
            return None
        data = json.loads(raw)
        if "records" in data:  # v2
            records = data.get("records", [])
            pairs = data.get("pairs") or {
                r["name"]: r.get("value", "") for r in records if _is_bb_cookie(r.get("domain"))
            }
            return Session(records=records, pairs=pairs, saved_at=float(data.get("saved_at", 0)))
        # v1 legacy: {"cookies": {name: value}}
        return Session(records=[], pairs=data.get("cookies", {}), saved_at=float(data.get("saved_at", 0)))

    def clear(self) -> None:
        try:
            keyring.delete_password(self.service, self.key)
        except keyring.errors.PasswordDeleteError:
            pass

    # ---- accessors ----
    def cookies(self) -> dict[str, str] | None:
        """name->value cookies for the Blackboard API host (used by httpx)."""
        s = self.load()
        return s.pairs if s else None

    def playwright_records(self) -> list[dict]:
        s = self.load()
        return s.records if s else []

    def persist_pairs(self, pairs: dict[str, str]) -> None:
        """After a keep-alive ping, write refreshed cookie VALUES back, preserving metadata."""
        s = self.load()
        if s and s.records:
            by_name = {r["name"]: r for r in s.records}
            for name, val in pairs.items():
                if name in by_name:
                    by_name[name]["value"] = val
            self.save_records(list(by_name.values()))
        else:
            merged = dict(s.pairs) if s else {}
            merged.update(pairs)
            keyring.set_password(
                self.service, self.key, json.dumps({"cookies": merged, "saved_at": time.time()})
            )

    def status(self) -> dict:
        s = self.load()
        if not s or not s.pairs:
            return {"authenticated": False, "reason": "no stored session — run `login`"}
        domains = sorted({r.get("domain", "") for r in s.records}) if s.records else []
        return {
            "authenticated": True,
            "profile": self.key,
            "cookie_count": len(s.pairs),
            "has_bbrouter": "BbRouter" in s.pairs,
            "can_silent_refresh": bool(s.records),
            "domains": domains,
            "age_seconds": int(time.time() - s.saved_at),
            "note": "Sessions are short-lived; the server keep-alive + silent refresh extend them. "
                    "If silent refresh fails, run `login` again (Azure session expired).",
        }

    # ---- interactive (headful) login: captures ALL cookies ----
    def interactive_login(self, headless: bool = False) -> dict[str, str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            ) from e

        _log("Opening a browser to UNIST Blackboard. Complete the Microsoft SSO + MFA; "
             "the window closes automatically once you reach the dashboard.")
        records: list[dict] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context(user_agent=config.USER_AGENT)
            page = ctx.new_page()
            page.goto(config.SAML_LOGIN_URL)
            try:
                page.wait_for_url(f"{config.LOGIN_SUCCESS_PREFIX}**", timeout=config.LOGIN_TIMEOUT_MS)
            except Exception:
                _log("Did not detect the /ultra dashboard in time — capturing current cookies anyway.")
            page.wait_for_timeout(1500)
            records = ctx.cookies()  # ALL cookies across all domains visited
            browser.close()

        bb = [r for r in records if _is_bb_cookie(r.get("domain"))]
        if not any(r["name"] == "BbRouter" for r in bb):
            raise RuntimeError("No Blackboard session cookie (BbRouter) captured — login likely incomplete.")
        self.save_records(records)
        _log(f"Saved {len(records)} cookies ({len(bb)} Blackboard-host) to the keychain.")
        return {r["name"]: r["value"] for r in bb}

    # ---- silent (headless) refresh: replays SAML using stored SSO cookies ----
    async def refresh_session_async(self, headless: bool = True, timeout_ms: int | None = None) -> bool:
        """Try to mint a fresh Blackboard session without MFA. Returns True on success."""
        records = self.playwright_records()
        if not records:
            return False  # legacy session without full records — can't reinject; needs `login`
        try:
            from playwright.async_api import async_playwright
        except ImportError:  # pragma: no cover
            return False

        timeout_ms = timeout_ms or config.REFRESH_TIMEOUT_MS
        ok = False
        new_records: list[dict] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            try:
                ctx = await browser.new_context(user_agent=config.USER_AGENT)
                await ctx.add_cookies(_sanitize_for_add(records))
                page = await ctx.new_page()
                await page.goto(config.SAML_LOGIN_URL)
                try:
                    await page.wait_for_url(f"{config.LOGIN_SUCCESS_PREFIX}**", timeout=timeout_ms)
                    ok = True
                except Exception:
                    ok = False
                await page.wait_for_timeout(800)
                new_records = await ctx.cookies()
            finally:
                await browser.close()

        if ok and any(r["name"] == "BbRouter" and _is_bb_cookie(r.get("domain")) for r in new_records):
            self.save_records(new_records)
            _log("Silent SSO refresh succeeded.")
            return True
        _log("Silent SSO refresh did not complete (Azure session likely expired — run `login`).")
        return False
