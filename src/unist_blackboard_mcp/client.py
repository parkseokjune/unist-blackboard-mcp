"""Async Blackboard Learn REST client, authenticated with harvested session cookies.

Endpoint paths are taken from the Anthology/Blackboard public REST reference and verified
against community clients (BlackboardSync/bblearn, TimEnglart downloader). The public API
(/learn/api/public) is the primary surface; `whoami` falls back to the private Ultra API
(/learn/api) which is what the web frontend uses with the same session cookies.

VERIFIED 2026-06-16 against the live UNIST instance: the PUBLIC API accepts session-cookie
auth, /users/me resolves self, course list comes from /users/{uid}/courses?expand=course
(GET /courses/{id} is 403 for some courses, hence expand), gradebook is v2, and calendar
items carry the deadlines. Set BB_API_BASE=private only if the public API ever stops
accepting cookies.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import config
from .auth import AuthManager


class NotAuthenticated(Exception):
    """No stored session at all."""


class AuthExpired(Exception):
    """The session was rejected with 401 — needs a fresh login."""


class Forbidden(Exception):
    """403 — the session is valid but the account lacks permission for this specific resource.

    On this UNIST instance a student can list memberships and read contents/calendar, but some
    per-resource calls (e.g. GET /courses/{id} for certain courses) are forbidden. This is NOT
    a session-expiry condition, so it must not trigger a re-login.
    """


def _v1(base: str) -> str:
    return f"{base}/v1"


# UNIST course codes are prefixed with a 7-digit term, e.g. "2026090_CSE31101" -> term "2026090".
# The numeric prefix sorts chronologically, so max(term) == current term.
_TERM_RE = re.compile(r"^(\d{7})_")


def _term_of(course_code: str | None) -> str | None:
    if not course_code:
        return None
    m = _TERM_RE.match(course_code)
    return m.group(1) if m else None


_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(s: str | None) -> str:
    """Flatten announcement HTML to readable plain text (keeps line breaks and list bullets)."""
    if not s:
        return ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)</(div|ul|ol|h[1-6]|tr)\s*>", "\n", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _bb_jar_pairs(client: httpx.AsyncClient) -> dict[str, str]:
    """Extract Blackboard-host cookies (name->value) from the live jar.

    httpx.Cookies.__getitem__ raises CookieConflict when a name (e.g. BbRouter) exists on
    multiple domains, so we iterate the raw jar and keep only the Blackboard-host cookies.
    """
    pairs: dict[str, str] = {}
    for ck in client.cookies.jar:
        dom = (ck.domain or "").lstrip(".")
        if dom.endswith("unist.ac.kr") or dom.endswith("blackboard.com"):
            pairs[ck.name] = ck.value
    return pairs


def _shape_announcement(a: dict, course_id: str, course_name: str | None) -> dict:
    return {
        "course": course_name,
        "courseId": course_id,
        "title": a.get("title"),
        "date": a.get("modified") or a.get("created"),
        "created": a.get("created"),
        "body": _html_to_text(a.get("body")),
        "id": a.get("id"),
    }


class BlackboardClient:
    def __init__(self, auth: AuthManager | None = None) -> None:
        self.auth = auth or AuthManager()
        self._client: httpx.AsyncClient | None = None
        self._uid: str | None = None
        # "public" (default) or "private" — which REST surface to use for data calls.
        self._api = os.environ.get("BB_API_BASE", "public").lower()
        # 401 auto-heal: one silent refresh at a time; skip if refreshed very recently.
        self._refresh_lock = asyncio.Lock()
        self._refreshed_at = float("-inf")  # never "recently refreshed" on first 401
        # membership cache (course list changes rarely).
        self._memb_cache: list[dict] | None = None
        self._memb_cache_at = 0.0

    def _now(self) -> float:
        try:
            return asyncio.get_event_loop().time()
        except RuntimeError:
            return 0.0

    @property
    def base(self) -> str:
        return config.PRIVATE_API if self._api == "private" else config.PUBLIC_API

    async def _ensure(self) -> httpx.AsyncClient:
        if self._client is None:
            cookies = self.auth.cookies()
            if not cookies:
                raise NotAuthenticated(
                    "No stored Blackboard session. Run `unist-blackboard-mcp login` "
                    "(or the bb_login tool) and complete SSO + MFA."
                )
            self._client = httpx.AsyncClient(
                cookies=cookies,
                timeout=config.HTTP_TIMEOUT,
                headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _rebuild(self) -> None:
        """Drop the cookie-bound http client + caches so the next call uses fresh cookies."""
        await self.aclose()
        self._uid = None
        self._memb_cache = None

    async def _try_refresh(self) -> bool:
        """Silently refresh the session once (lock-guarded, deduped). Returns True on success."""
        async with self._refresh_lock:
            # If another coroutine just refreshed, treat as done.
            if self._now() - self._refreshed_at < 30:
                return True
            try:
                ok = await self.auth.refresh_session_async(headless=True)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                self._refreshed_at = self._now()
                await self._rebuild()
            return ok

    async def _get(self, url: str, _retried: bool = False, **kw) -> httpx.Response:
        client = await self._ensure()
        r = await client.get(url, **kw)
        if r.status_code == 401:
            if not _retried and await self._try_refresh():
                return await self._get(url, _retried=True, **kw)
            raise AuthExpired("Blackboard session expired (401) and silent refresh failed. Re-run login.")
        if r.status_code == 403:
            raise Forbidden(f"Access forbidden (403) for {url} — account lacks permission here.")
        r.raise_for_status()
        return r

    async def _json(self, url: str, **kw):
        return (await self._get(url, **kw)).json()

    async def _paged(self, url: str, params: dict | None = None) -> list[dict]:
        """Follow Blackboard's paging (`results` + `paging.nextPage`)."""
        out: list[dict] = []
        next_url: str | None = url
        first = True
        while next_url:
            data = await self._json(next_url, params=params if first else None)
            out.extend(data.get("results", []))
            nxt = (data.get("paging") or {}).get("nextPage")
            next_url = (config.HOST + nxt) if nxt else None
            first = False
        return out

    # ---------- identity ----------
    async def whoami(self, _retried: bool = False) -> dict:
        client = await self._ensure()
        for url in (f"{config.PUBLIC_API}/v1/users/me", f"{config.PRIVATE_API}/v1/users/me"):
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                self._uid = data.get("id") or data.get("userId") or data.get("uuid")
                return data
        # whoami bypasses _get, so it must trigger the same silent-refresh auto-heal itself —
        # it's the first call made, so without this an expired session never gets a chance to refresh.
        if not _retried and await self._try_refresh():
            return await self.whoami(_retried=True)
        raise AuthExpired("Could not resolve the current user and silent refresh failed — run login.")

    async def _self_id(self) -> str:
        if not self._uid:
            await self.whoami()
        assert self._uid
        return self._uid

    # ---------- courses ----------
    async def _memberships(self) -> list[dict]:
        """Course memberships (expand=course), cached for COURSES_TTL seconds."""
        if self._memb_cache is not None and (self._now() - self._memb_cache_at) < config.COURSES_TTL:
            return self._memb_cache
        uid = await self._self_id()
        ms = await self._paged(f"{_v1(self.base)}/users/{uid}/courses", params={"expand": "course"})
        self._memb_cache = ms
        self._memb_cache_at = self._now()
        return ms

    async def list_courses(self, term: str | None = None, include_closed: bool = False) -> list[dict]:
        """List my course enrolments (sorted newest term first).

        - `term`: filter to one term prefix, e.g. "2026090". Pass "current" for the latest term.
        - `include_closed`: also include availability=="No" courses (old votes/compliance).

        Uses expand=course (one paged call) — the per-course GET /courses/{id} is 403 for
        some courses on this instance. Academic courses carry availability=="Term" (term-gated),
        so they are KEPT by default; only "No" (closed) courses are dropped.
        """
        memberships = await self._memberships()
        rows: list[dict] = []
        for m in memberships:
            course = m.get("course") or {}
            avail = (course.get("availability") or {}).get("available")
            if not include_closed and avail == "No":
                continue
            code = course.get("courseId") or course.get("externalId")
            rows.append({
                "courseId": m.get("courseId") or course.get("id"),
                "name": course.get("name"),
                "courseCode": code,
                "term": _term_of(code),
                "available": avail,
                "lastAccessed": m.get("lastAccessed"),
            })

        if term == "current":
            terms = [r["term"] for r in rows if r["term"]]
            term = max(terms) if terms else None
        if term:
            rows = [r for r in rows if r["term"] == term]

        rows.sort(key=lambda c: ((c.get("term") or ""), (c.get("lastAccessed") or "")), reverse=True)
        return rows

    async def get_course_contents(self, course_id: str) -> list[dict]:
        return await self._paged(f"{_v1(self.base)}/courses/{course_id}/contents")

    async def get_content_children(self, course_id: str, content_id: str) -> list[dict]:
        return await self._paged(f"{_v1(self.base)}/courses/{course_id}/contents/{content_id}/children")

    async def list_attachments(self, course_id: str, content_id: str) -> list[dict]:
        return await self._paged(
            f"{_v1(self.base)}/courses/{course_id}/contents/{content_id}/attachments"
        )

    async def download_attachment(
        self, course_id: str, content_id: str, attachment_id: str, filename: str | None = None
    ) -> str:
        url = (f"{_v1(self.base)}/courses/{course_id}/contents/{content_id}"
               f"/attachments/{attachment_id}/download")
        dest_dir = Path(config.DOWNLOAD_DIR) / course_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        client = await self._ensure()
        async with client.stream("GET", url) as r:
            if r.status_code == 401:
                raise AuthExpired("Download rejected (401). Re-run login.")
            r.raise_for_status()
            if not filename:
                cd = r.headers.get("content-disposition", "")
                filename = cd.split("filename=")[-1].strip('"; ') or attachment_id
            path = dest_dir / filename
            with open(path, "wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)
        return str(path)

    # ---------- grades ----------
    async def get_grades(self, course_id: str) -> list[dict]:
        uid = await self._self_id()
        # Gradebook columns moved to v2 (Learn 3400.8.0+). Names live on the column.
        columns = await self._paged(f"{self.base}/v2/courses/{course_id}/gradebook/columns")
        out: list[dict] = []
        # Fetch this user's value per column. Few columns per course, so serial is fine.
        for col in columns:
            col_id = col.get("id")
            try:
                grade = await self._json(
                    f"{self.base}/v2/courses/{course_id}/gradebook/columns/{col_id}/users/{uid}"
                )
            except (httpx.HTTPStatusError, Forbidden):
                grade = {}
            out.append({
                "column": col.get("name"),
                "score": grade.get("displayGrade", {}).get("score") if isinstance(grade.get("displayGrade"), dict) else grade.get("score"),
                "text": (grade.get("displayGrade") or {}).get("text"),
                "status": grade.get("status"),
                "possible": col.get("score", {}).get("possible"),
            })
        return out

    # ---------- announcements ----------
    async def list_announcements(
        self,
        course_id: str | None = None,
        term: str | None = "current",
        limit: int = 25,
        since: str | None = None,
    ) -> list[dict]:
        """Announcements with HTML bodies flattened to text (exam schedules, averages, etc.).

        - course_id given -> just that course.
        - course_id omitted -> aggregate across all courses in `term` (default this semester),
          since the system-wide /announcements endpoint is empty on this instance.
        - `since`: ISO date; keep only announcements at/after it.
        - `limit`: cap the number returned (newest first); 0 = no cap.
        """
        if course_id:
            raw = await self._paged(f"{_v1(self.base)}/courses/{course_id}/announcements")
            rows = [_shape_announcement(a, course_id, None) for a in raw]
        else:
            courses = await self.list_courses(term=term)

            async def _fetch(co: dict) -> list[dict]:
                try:
                    anns = await self._paged(
                        f"{_v1(self.base)}/courses/{co['courseId']}/announcements"
                    )
                except (httpx.HTTPStatusError, Forbidden):
                    return []
                return [_shape_announcement(a, co["courseId"], co.get("name")) for a in anns]

            results = await asyncio.gather(*[_fetch(co) for co in courses])
            rows = [r for sub in results for r in sub]

        if since:
            rows = [r for r in rows if (r.get("date") or "") >= since]
        rows.sort(key=lambda r: (r.get("date") or ""), reverse=True)
        return rows[:limit] if limit else rows

    # ---------- calendar / deadlines ----------
    async def list_calendar(self, since: str | None = None, until: str | None = None) -> list[dict]:
        params = {}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        return await self._paged(f"{_v1(self.base)}/calendars/items", params=params or None)

    async def upcoming_deadlines(self, since: str | None = None, until: str | None = None) -> list[dict]:
        """Calendar items shaped for 'what's due' — {title, course, type, due}, sorted by due date."""
        items = await self.list_calendar(since, until)
        shaped = [
            {
                "title": it.get("title"),
                "course": it.get("calendarName"),
                "type": it.get("type"),
                "due": it.get("end") or it.get("start"),
                "start": it.get("start"),
                "calendarId": it.get("calendarId"),
                "id": it.get("id"),
            }
            for it in items
        ]
        shaped.sort(key=lambda x: (x.get("due") or ""))
        return shaped

    # ---------- composite ----------
    async def weekly_briefing(self, days: int = 7) -> dict:
        """One call: current courses + deadlines in the next `days` + recent announcements.

        Announcements carry exam schedules and class averages, so a briefing combines the
        'what's due' calendar with the 'what was announced' feed.
        """
        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        since_cal = (now - timedelta(days=1)).strftime(fmt)
        until_cal = (now + timedelta(days=days)).strftime(fmt)
        since_ann = (now - timedelta(days=days)).strftime(fmt)

        deadlines, anns, courses = await asyncio.gather(
            self.upcoming_deadlines(since=since_cal, until=until_cal),
            self.list_announcements(since=since_ann, limit=20),
            self.list_courses(term="current"),
        )
        return {
            "generated": now.strftime(fmt),
            "window_days": days,
            "current_courses": [{"courseId": c["courseId"], "name": c["name"]} for c in courses],
            "upcoming_deadlines": deadlines,
            "recent_announcements": anns,
        }

    # ---------- keep-alive ----------
    async def ping_and_persist(self) -> bool:
        """Cheap request to keep the session warm; persist any refreshed cookies. Returns True if alive."""
        try:
            client = await self._ensure()
        except NotAuthenticated:
            return False
        r = await client.get(f"{config.PUBLIC_API}/v1/users/me")
        if r.status_code == 401:
            return await self._try_refresh()
        if r.status_code >= 400:
            return False
        self.auth.persist_pairs(_bb_jar_pairs(client))
        return True

    # ---------- assignments ----------
    async def get_assignment(self, course_id: str, content_id: str) -> dict:
        return await self._json(f"{_v1(self.base)}/courses/{course_id}/contents/{content_id}")

    # ---------- WRITE OPS (guarded by the server with confirm=True) ----------
    async def create_calendar_item(self, title: str, start: str, end: str, description: str = "") -> dict:
        """Create a PERSONAL calendar item (e.g. a self-set study reminder)."""
        client = await self._ensure()
        body = {
            "calendarId": "PERSONAL",
            "title": title,
            "start": start,
            "end": end,
            "description": description,
        }
        r = await client.post(f"{_v1(self.base)}/calendars/items", json=body)
        if r.status_code == 401:
            raise AuthExpired("Write rejected (401). Re-run login.")
        r.raise_for_status()
        return r.json()

    async def submit_assignment_attempt(
        self, course_id: str, column_id: str, text: str
    ) -> dict:
        """EXPERIMENTAL: create + submit a text attempt for an assignment column.

        Blackboard submission via REST is brittle and may be disabled for students on
        this instance. Verify on a throwaway/test assignment first.
        """
        client = await self._ensure()
        base = f"{self.base}/v2/courses/{course_id}/gradebook/columns/{column_id}/attempts"
        created = await client.post(base, json={"text": text, "status": "InProgress"})
        if created.status_code == 401:
            raise AuthExpired("Attempt create rejected (401). Re-run login.")
        created.raise_for_status()
        attempt = created.json()
        attempt_id = attempt.get("id")
        submitted = await client.patch(f"{base}/{attempt_id}", json={"status": "NeedsGrading"})
        submitted.raise_for_status()
        return submitted.json()

    # ---------- diagnostics (Phase 0 probe) ----------
    async def probe(self) -> dict:
        """Hit a few endpoints on BOTH public and private surfaces and report what works."""
        client = await self._ensure()
        report: dict = {"host": config.HOST, "checks": []}
        targets = [
            ("public/system/version", f"{config.PUBLIC_API}/v1/system/version"),
            ("public/users/me", f"{config.PUBLIC_API}/v1/users/me"),
            ("private/users/me", f"{config.PRIVATE_API}/v1/users/me"),
            ("public/courses", f"{config.PUBLIC_API}/v1/courses?limit=1"),
        ]
        for name, url in targets:
            try:
                r = await client.get(url)
                report["checks"].append({
                    "name": name, "status": r.status_code,
                    "ok": r.status_code == 200,
                    "snippet": r.text[:160],
                })
            except Exception as e:  # noqa: BLE001
                report["checks"].append({"name": name, "error": str(e)})
        return report


# small helper used by the server to run sync-from-async download naming safely
async def _gather(*coros):
    return await asyncio.gather(*coros)
