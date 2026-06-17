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
import json as _json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

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
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


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


def _snippet(text: str | None, q: str, width: int = 160) -> str:
    """A short excerpt of `text` centered on the first match of `q` (case-insensitive)."""
    if not text:
        return ""
    flat = text.replace("\n", " ")
    i = flat.lower().find(q)
    if i < 0:
        return flat[:width].strip()
    start = max(0, i - width // 3)
    end = min(len(flat), i + len(q) + (width * 2) // 3)
    return ("…" if start > 0 else "") + flat[start:end].strip() + ("…" if end < len(flat) else "")


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


def _parse_formula_weights(formula: str | None, cat_name: dict) -> dict | None:
    """Best-effort: pull per-category weights out of a Blackboard 'Calculated' column formula.

    The formula embeds `wgt:{"weights":[{"element":{"type":"cat","id":...},"value":40.0}, ...]}`.
    Returns {category_title: weight}. None if absent/unparseable (common — many courses don't weight).
    """
    if not formula or "wgt" not in formula:
        return None
    m = re.search(r"wgt:(\{.*?\}\s*\]\s*\})", formula)
    if not m:
        return None
    try:
        data = _json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return None
    out: dict[str, float] = {}
    for w in data.get("weights", []):
        el = w.get("element") or {}
        val = w.get("value", w.get("weight"))
        if el.get("type") == "cat" and val is not None:
            name = cat_name.get(el.get("id"))
            if name:
                out[name] = float(val)
    return out or None


def _apply_weights(categories: list[dict], weights: dict | None) -> dict | None:
    """Weighted standing from per-category percents and a {category: weight} map (case-insensitive).

    Normalizes over the categories that actually have graded data, so it reflects current standing.
    """
    if not weights:
        return None
    wmap = {str(k).lower(): float(v) for k, v in weights.items()}
    num = den = 0.0
    used = []
    for c in categories:
        w = wmap.get((c.get("category") or "").lower())
        if w and c.get("percent") is not None:
            num += c["percent"] * w
            den += w
            used.append({"category": c["category"], "weight": w, "percent": c["percent"]})
    if den == 0:
        return None
    return {"weighted_percent": round(num / den, 1), "based_on": used, "weight_total_used": round(den, 2)}


def _weights_for(course: dict, weights: dict | None) -> dict | None:
    """Resolve the weight map for one course. `weights` may be a flat {category: weight} applied to
    all courses, or {courseId-or-name-substring: {category: weight}} per course."""
    if not weights:
        return None
    if any(isinstance(v, dict) for v in weights.values()):  # per-course mapping
        for k, v in weights.items():
            if isinstance(v, dict) and (k == course.get("courseId")
                                        or str(k).lower() in (course.get("name") or "").lower()):
                return v
        return None
    return weights  # flat category->weight, same for every course


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
        # background drain tasks for clients orphaned by a refresh (kept referenced so not GC'd).
        self._drains: set = set()

    def _now(self) -> float:
        # loop-independent monotonic clock (no deprecated get_event_loop, no bogus 0.0 off-loop).
        return time.monotonic()

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
            # Scope every cookie to the Blackboard host so httpx/cookiejar never attaches the
            # session cookie to an off-host request — even when following a 3xx redirect (which
            # would otherwise leak BbRouter to e.g. an S3/CDN or attacker host). config validates
            # BB_HOST is https, closing the plain-http / wrong-host config vector.
            host = urlsplit(config.HOST).hostname
            jar = httpx.Cookies()
            for name, value in cookies.items():
                jar.set(name, value, domain=host, path="/")
            self._client = httpx.AsyncClient(
                cookies=jar,
                timeout=config.HTTP_TIMEOUT,
                headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _detach(self) -> None:
        """Drop the shared client + caches WITHOUT closing it out from under in-flight requests.

        Each request captures its own local client reference, so it finishes on the orphaned
        client; the next call rebuilds with fresh cookies. Use this (not aclose) whenever a
        re-login/refresh happens while other tool calls may be mid-request.
        """
        self._client = None
        self._uid = None
        self._memb_cache = None

    async def _rebuild(self) -> None:
        """Swap in a fresh cookie-bound client. The old one is detached (not closed inline) so
        concurrent in-flight requests can finish, then drained-closed in the background."""
        old = self._client
        self._detach()
        if old is not None:
            async def _drain(c: httpx.AsyncClient) -> None:
                try:
                    await asyncio.sleep(config.HTTP_TIMEOUT + 5)  # let in-flight requests finish
                finally:
                    await c.aclose()
            t = asyncio.create_task(_drain(old))
            self._drains.add(t)
            t.add_done_callback(self._drains.discard)

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

    async def _write(self, method: str, url: str, _retried: bool = False, **kw) -> httpx.Response:
        """POST/PATCH/etc. with the same 401 silent-refresh + 403->Forbidden handling as _get."""
        client = await self._ensure()
        r = await client.request(method, url, **kw)
        if r.status_code == 401:
            if not _retried and await self._try_refresh():
                return await self._write(method, url, _retried=True, **kw)
            raise AuthExpired("Write rejected (401) and silent refresh failed. Re-run login.")
        if r.status_code == 403:
            raise Forbidden(f"Write forbidden (403) for {url} — account lacks permission here.")
        r.raise_for_status()
        return r

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
            if not terms:
                return []  # asked for the current term but none is resolvable -> nothing, not all
            term = max(terms)
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

    @staticmethod
    def _safe_name(name: str | None, fallback: str) -> str:
        """Reduce a server- or caller-supplied name to a bare, traversal-free basename.

        Neutralizes path traversal: basename('/etc/x')=='x', basename('../../x')=='x'; strips
        leading dots and caps length. Used so a malicious content-disposition / course_id can
        never make download_attachment write outside the download dir (CWE-22 arbitrary write).
        """
        base = os.path.basename((name or "").replace("\\", "/")).strip().lstrip(".")
        return base[:200] if base and base not in (".", "..") else fallback

    async def download_attachment(
        self, course_id: str, content_id: str, attachment_id: str, filename: str | None = None
    ) -> str:
        root = Path(config.DOWNLOAD_DIR).resolve()
        dest_dir = (root / self._safe_name(course_id, "course")).resolve()
        if not dest_dir.is_relative_to(root):
            raise ValueError(f"Refusing path outside download dir for course_id={course_id!r}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        url = (f"{_v1(self.base)}/courses/{course_id}/contents/{content_id}"
               f"/attachments/{attachment_id}/download")

        async def _open_and_save(_retried: bool = False) -> str:
            client = await self._ensure()
            async with client.stream("GET", url) as r:
                if r.status_code == 401:
                    if not _retried and await self._try_refresh():
                        return await _open_and_save(_retried=True)
                    raise AuthExpired("Download rejected (401) and silent refresh failed. Re-run login.")
                if r.status_code == 403:
                    raise Forbidden(f"Download forbidden (403) for {url} — account lacks permission.")
                r.raise_for_status()
                name = filename
                if not name:
                    cd = r.headers.get("content-disposition", "")
                    name = cd.split("filename=")[-1].strip('"; ')
                name = self._safe_name(name, attachment_id)
                path = (dest_dir / name).resolve()
                if not path.is_relative_to(dest_dir):  # defense in depth
                    raise ValueError(f"Unsafe attachment filename: {name!r}")
                with open(path, "wb") as f:
                    async for chunk in r.aiter_bytes():
                        f.write(chunk)
                return str(path)

        return await _open_and_save()

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
                "possible": (col.get("score") or {}).get("possible"),
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

    async def upcoming_deadlines(
        self, since: str | None = None, until: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Calendar items shaped for 'what's due' — {title, course, type, due}, sorted by due date.

        `limit` caps the result (0 = no cap) so an unbounded calendar can't blow the output budget.
        """
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
        return shaped[:limit] if limit else shaped

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

        # return_exceptions=True so one section's 403/timeout doesn't wipe out the whole briefing.
        results = await asyncio.gather(
            self.upcoming_deadlines(since=since_cal, until=until_cal),
            self.list_announcements(since=since_ann, limit=20),
            self.list_courses(term="current"),
            return_exceptions=True,
        )
        deadlines, anns, courses = (r if not isinstance(r, Exception) else [] for r in results)
        deadlines, anns, courses = list(deadlines), list(anns), list(courses)
        # keep the bundled payload bounded (announcement bodies can be long)
        for a in anns:
            body = a.get("body")
            if body and len(body) > 1500:
                a["body"] = body[:1500] + "… [truncated]"
        return {
            "generated": now.strftime(fmt),
            "window_days": days,
            "partial": any(isinstance(r, Exception) for r in results),
            "current_courses": [{"courseId": c["courseId"], "name": c["name"]} for c in courses],
            "upcoming_deadlines": deadlines,
            "recent_announcements": anns,
        }

    async def course_staff(self, course_id: str) -> dict:
        """Instructors/TAs for a course (names, roles, login id) + any emails scraped from the
        syllabus/announcements/content — because Blackboard does NOT expose staff emails via the API.
        """
        members = await self._paged(f"{_v1(self.base)}/courses/{course_id}/users", params={"expand": "user"})
        staff = []
        for m in members:
            role = m.get("courseRoleId")
            if role and role != "Student":
                u = m.get("user") or {}
                nm = u.get("name") or {}
                full = f"{nm.get('given', '')} {nm.get('family', '')}".strip()
                staff.append({
                    "role": role,
                    "name": full or u.get("userName"),
                    "userName": u.get("userName"),
                    "email": (u.get("contact") or {}).get("email"),  # almost always None for students
                })
        role_order = {"Instructor": 0, "TeachingAssistant": 1, "Grader": 2}
        staff.sort(key=lambda s: role_order.get(s["role"], 9))

        # Harvest emails from text the staff actually wrote (syllabus usually lists them here).
        emails: dict[str, str] = {}

        def _scan(text: str, source: str) -> None:
            for em in _EMAIL_RE.findall(text or ""):
                emails.setdefault(em.lower(), source)

        try:
            for a in await self.list_announcements(course_id=course_id, limit=0):
                _scan(f"{a.get('title', '')} {a.get('body', '')}", f"announcement: {a.get('title')}")
        except (httpx.HTTPStatusError, Forbidden):
            pass
        try:
            contents = await self.get_course_contents(course_id)
        except (httpx.HTTPStatusError, Forbidden):
            contents = []
        syllabus_hits = 0
        for ct in contents:
            title = ct.get("title") or ""
            _scan(f"{title} {ct.get('description', '')}", f"content: {title}")
            # The syllabus is often a document whose BODY (not list desc) holds the emails — fetch a few.
            if syllabus_hits < 5 and any(
                k in title.lower() for k in ("syllabus", "강의계획", "course info", "개요", "orientation", "info")
            ):
                syllabus_hits += 1
                try:
                    detail = await self.get_assignment(course_id, ct["id"])
                    _scan(_html_to_text(detail.get("body")), f"syllabus: {title}")
                except (httpx.HTTPStatusError, Forbidden):
                    pass

        return {
            "courseId": course_id,
            "staff": staff,
            "emails_found": [{"email": k, "source": v} for k, v in emails.items()],
            "note": "Blackboard does not expose staff emails to students via API, so `staff` has "
                    "names/roles/login-id only. `emails_found` are addresses scraped from the "
                    "syllabus/announcements/content text. For a syllabus PDF, use download_material.",
        }

    async def search(self, query: str, term: str | None = "current", limit: int = 20) -> list[dict]:
        """Keyword search across this term's announcements (title+body) and upcoming deadlines.

        Returns matches with a snippet, newest first. Good for "find the exam announcement for X".
        """
        q = (query or "").lower().strip()
        if not q:
            return []
        anns, deadlines = await asyncio.gather(
            self.list_announcements(term=term, limit=0),
            self.upcoming_deadlines(limit=0),
            return_exceptions=True,
        )
        anns = anns if not isinstance(anns, Exception) else []
        deadlines = deadlines if not isinstance(deadlines, Exception) else []

        hits: list[dict] = []
        for a in anns:
            body = a.get("body") or ""
            if q in f"{a.get('title','')}\n{body}\n{a.get('course','')}".lower():
                hits.append({
                    "type": "announcement", "course": a.get("course"), "title": a.get("title"),
                    "date": a.get("date"), "courseId": a.get("courseId"),
                    "snippet": _snippet(body, q),
                })
        for d in deadlines:
            if q in f"{d.get('title','')}\n{d.get('course','')}".lower():
                hits.append({
                    "type": "deadline", "course": d.get("course"), "title": d.get("title"),
                    "due": d.get("due"),
                })
        hits.sort(key=lambda h: (h.get("date") or h.get("due") or ""), reverse=True)
        return hits[:limit] if limit else hits

    async def _course_grades_detailed(self, course_id: str) -> tuple[list[dict], dict | None]:
        """Per-column grades enriched with category names; plus Blackboard's own category weights
        (parsed from a Calculated column's formula) if the course defines them."""
        uid = await self._self_id()
        cols = await self._paged(f"{self.base}/v2/courses/{course_id}/gradebook/columns")
        try:  # categories live on v1 (v2 404s on this instance)
            cats_raw = await self._paged(f"{_v1(self.base)}/courses/{course_id}/gradebook/categories")
        except (httpx.HTTPStatusError, Forbidden):
            cats_raw = []
        cat_name = {c["id"]: c.get("title") for c in cats_raw}

        rows: list[dict] = []
        weights_bb: dict | None = None
        for col in cols:
            gtype = (col.get("grading") or {}).get("type")
            name = col.get("name") or ""
            if gtype == "Calculated":
                w = _parse_formula_weights((col.get("formula") or {}).get("formula"), cat_name)
                if w:
                    weights_bb = w
            try:
                grade = await self._json(
                    f"{self.base}/v2/courses/{course_id}/gradebook/columns/{col['id']}/users/{uid}"
                )
            except (httpx.HTTPStatusError, Forbidden):
                grade = {}
            dg = grade.get("displayGrade")
            rows.append({
                "column": name,
                "category": cat_name.get(col.get("gradebookCategoryId")),
                "type": gtype,
                "is_total": gtype == "Calculated"
                            or name.lower() in ("total", "overall grade", "weighted total", "running total"),
                "score": dg.get("score") if isinstance(dg, dict) else grade.get("score"),
                "possible": (col.get("score") or {}).get("possible"),
                "text": (dg or {}).get("text") if isinstance(dg, dict) else None,
            })
        return rows, weights_bb

    async def grade_summary(self, term: str | None = "current", weights: dict | None = None) -> dict:
        """Per-course grades with category breakdown and WEIGHTED standing.

        Grade priority: blackboard_total (Blackboard's own computed grade) > weighted (category
        percents × weights) > raw_percent (unweighted point sum). Weights come from Blackboard's
        formula if the course defines them, else from the `weights` arg you pass.
        """
        courses = await self.list_courses(term=term)

        async def _one(co: dict) -> dict:
            try:
                rows, weights_bb = await self._course_grades_detailed(co["courseId"])
            except (httpx.HTTPStatusError, Forbidden):
                return {"course": co["name"], "courseId": co["courseId"], "error": "could not load grades"}

            graded = [r for r in rows if not r["is_total"] and isinstance(r.get("score"), (int, float))]
            agg: dict = defaultdict(lambda: {"earned": 0.0, "possible": 0.0, "items": 0})
            for r in graded:
                a = agg[r["category"] or "Uncategorized"]
                a["earned"] += r["score"]
                a["items"] += 1
                if isinstance(r["possible"], (int, float)):
                    a["possible"] += r["possible"]
            categories = [
                {"category": k, "earned": round(v["earned"], 2), "possible": round(v["possible"], 2),
                 "percent": round(v["earned"] / v["possible"] * 100, 1) if v["possible"] else None,
                 "items": v["items"]}
                for k, v in sorted(agg.items())
            ]
            earned = sum(r["score"] for r in graded)
            possible = sum(r["possible"] for r in graded if isinstance(r["possible"], (int, float)))
            bb_total = next((r for r in rows if r["is_total"] and isinstance(r.get("score"), (int, float))), None)
            user_w = _weights_for(co, weights)
            weighted = _apply_weights(categories, weights_bb or user_w)
            return {
                "course": co["name"], "courseId": co["courseId"],
                "graded_count": len(graded),
                "pending_count": sum(1 for r in rows if not r["is_total"] and r.get("score") is None),
                "categories": categories,
                "blackboard_total": (
                    {"name": bb_total["column"], "score": bb_total["score"], "possible": bb_total["possible"],
                     "text": bb_total["text"],
                     "percent": round(bb_total["score"] / bb_total["possible"] * 100, 1)
                                if bb_total.get("possible") else None}
                    if bb_total else None
                ),
                "weights_source": "blackboard" if weights_bb else ("user" if (user_w and weighted) else None),
                "weighted": weighted,
                "raw_percent": round(earned / possible * 100, 1) if possible else None,
                "raw_earned": round(earned, 2), "raw_possible": round(possible, 2),
            }

        summaries = await asyncio.gather(*[_one(c) for c in courses])
        return {
            "term": term,
            "courses": list(summaries),
            "note": "Grade priority: blackboard_total > weighted (categories × weights) > raw_percent "
                    "(unweighted). Many UNIST courses don't store weights in Blackboard — pass "
                    "weights={'Exam':40,'Quiz':30,'Homework':30} (or {course: {category: weight}}) "
                    "to apply your syllabus weights.",
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
            # Don't trust _try_refresh's deduped return as proof of liveness — re-ping the
            # rebuilt client and judge from the actual response.
            await self._try_refresh()
            try:
                client = await self._ensure()
            except NotAuthenticated:
                return False
            r = await client.get(f"{config.PUBLIC_API}/v1/users/me")
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
        body = {
            "calendarId": "PERSONAL",
            "title": title,
            "start": start,
            "end": end,
            "description": description,
        }
        r = await self._write("POST", f"{_v1(self.base)}/calendars/items", json=body)
        return r.json()

    async def submit_assignment_attempt(
        self, course_id: str, column_id: str, text: str
    ) -> dict:
        """EXPERIMENTAL: create + submit a text attempt for an assignment column.

        Blackboard submission via REST is brittle and may be disabled for students on
        this instance. Verify on a throwaway/test assignment first.
        """
        base = f"{self.base}/v2/courses/{course_id}/gradebook/columns/{column_id}/attempts"
        created = await self._write("POST", base, json={"text": text, "status": "InProgress"})
        attempt = created.json()
        attempt_id = attempt.get("id")
        if not attempt_id:
            raise RuntimeError(f"Attempt create returned no id (keys: {list(attempt)[:8]}); cannot submit.")
        submitted = await self._write("PATCH", f"{base}/{attempt_id}", json={"status": "NeedsGrading"})
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
