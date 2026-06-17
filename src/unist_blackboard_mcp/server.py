"""FastMCP server exposing UNIST Blackboard as MCP tools.

Design:
- Read tools are annotated readOnlyHint=True so well-behaved clients can auto-run them.
- Write tools are annotated destructiveHint=True AND require an explicit `confirm=True`
  argument — annotations are only hints, so the real guard is enforced here in code.
- Auth errors never crash the server; they return a friendly dict telling the user to log in.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import sys

from mcp.server.fastmcp import FastMCP

try:
    from mcp.types import ToolAnnotations
except Exception:  # pragma: no cover - very old SDKs
    ToolAnnotations = None  # type: ignore

from . import config
from .auth import AuthManager
from .client import AuthExpired, BlackboardClient, Forbidden, NotAuthenticated

mcp = FastMCP("unist-blackboard")

_auth = AuthManager()
_client = BlackboardClient(_auth)

_keepalive_task: "asyncio.Task | None" = None


async def _keepalive_loop() -> None:
    while True:
        await asyncio.sleep(config.KEEPALIVE_INTERVAL)
        with contextlib.suppress(Exception):
            await _client.ping_and_persist()


def _ensure_keepalive() -> None:
    """Start the background keep-alive once a loop is running (idempotent)."""
    global _keepalive_task
    if _keepalive_task is None or _keepalive_task.done():
        with contextlib.suppress(RuntimeError):
            _keepalive_task = asyncio.create_task(_keepalive_loop())


def _ann(read_only: bool = False, destructive: bool = False, title: str | None = None):
    if ToolAnnotations is None:
        return None
    return ToolAnnotations(
        title=title,
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=read_only,
        openWorldHint=True,
    )


def _cap_output(result):
    """Soft-cap a tool's JSON size so a huge result can't blow the client token budget.

    Shape-aware: trims trailing list items, and for dicts shrinks the largest list field(s) and
    caps oversized strings, attaching a _truncated marker. No-op (one json.dumps) under budget.
    """
    budget = config.MAX_OUTPUT_CHARS

    def size(o) -> int:
        return len(json.dumps(o, ensure_ascii=False, default=str))

    try:
        if size(result) <= budget:
            return result
    except Exception:  # noqa: BLE001 - unserializable; let it through unchanged
        return result

    if isinstance(result, list):
        out = list(result)
        while out and size(out) > budget - 200:
            out.pop()
        return {"_truncated": True, "returned": len(out), "total": len(result),
                "hint": "Result too large — narrow with term=/course_id=/limit=.", "items": out}
    if isinstance(result, dict):
        out = dict(result)
        for k in sorted(out, key=lambda k: size(out[k]), reverse=True):
            if size(out) <= budget:
                break
            v = out[k]
            if isinstance(v, list):
                while v and size(out) > budget:
                    v.pop()
            elif isinstance(v, str) and len(v) > 500:
                out[k] = v[:500] + "…[truncated]"
        out["_truncated"] = True
        return out
    if isinstance(result, str) and len(result) > budget:
        return result[:budget] + "…[truncated]"
    return result


def _guard(fn):
    """Turn auth exceptions into structured, user-actionable results instead of crashes."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        _ensure_keepalive()
        try:
            return _cap_output(await fn(*args, **kwargs))
        except NotAuthenticated as e:
            return {"error": "not_authenticated", "message": str(e),
                    "fix": "Run the bb_login tool, or `unist-blackboard-mcp login` in a terminal."}
        except AuthExpired as e:
            return {"error": "auth_expired", "message": str(e),
                    "fix": "Session expired. Run bb_login again to refresh cookies."}
        except Forbidden as e:
            return {"error": "forbidden", "message": str(e),
                    "note": "Session is valid; your account just lacks permission for this resource."}
        except Exception as e:  # noqa: BLE001
            print(f"[unist-blackboard-mcp] tool error: {e}", file=sys.stderr, flush=True)
            return {"error": "tool_error", "message": str(e)}
    return wrapper


# ============================ AUTH ============================

@mcp.tool(annotations=_ann(read_only=True, title="Auth status"))
@_guard
async def bb_auth_status() -> dict:
    """Report whether a Blackboard session is stored and how old it is."""
    return _auth.status()


@mcp.tool(annotations=_ann(read_only=True, title="My profile"))
@_guard
async def bb_whoami() -> dict:
    """The signed-in user's identity: name, login id, student id, and email (if Blackboard exposes it)."""
    return await _client.profile()


@mcp.tool(annotations=_ann(read_only=True, title="Server / version info"))
async def bb_server_info() -> dict:
    """Versions for bug reports: this MCP's version + the live Blackboard Learn build. Works logged-out."""
    from . import __version__
    info = {"mcp_version": __version__, "host": config.HOST}
    try:
        client = await _client._ensure()
        r = await client.get(f"{config.PUBLIC_API}/v1/system/version")
        info["blackboard_build"] = r.json().get("learn") if r.status_code == 200 else f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001 - logged-out / offline still returns mcp_version
        info["blackboard_build"] = f"unavailable ({type(e).__name__})"
    return info


@mcp.tool(annotations=_ann(destructive=False, title="Log in (opens browser)"))
@_guard
async def bb_login(timeout_seconds: int = 300) -> dict:
    """Open a browser so you can complete UNIST SSO + MFA, then capture the session.

    Opens a real browser window (subprocess); complete the Microsoft login + MFA there.
    Cookies are stored in the OS keychain. May take a while — if your MCP client times
    out, run `unist-blackboard-mcp login` in a terminal instead.
    """
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "unist_blackboard_mcp", "login",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": "login_timeout",
                "message": "Login did not finish in time. Run `unist-blackboard-mcp login` in a terminal."}
    _client._detach()  # drop stale cookie client WITHOUT yanking it from in-flight reads
    status = _auth.status()
    if not status.get("authenticated"):
        # Don't forward raw subprocess stderr to the model/transcript (it could echo an SSO URL
        # containing a token). The detailed stderr is already on the local stderr log.
        return {"error": "login_failed",
                "message": "Login did not complete. Run `unist-blackboard-mcp login` in a terminal to retry."}
    return {"ok": True, **status}


@mcp.tool(annotations=_ann(destructive=False, title="Refresh session (silent)"))
@_guard
async def bb_refresh() -> dict:
    """Silently refresh the Blackboard session using stored SSO cookies (no MFA if Azure session valid).

    Use this if reads start failing with auth errors. If it returns refreshed=false, the Azure
    SSO session itself expired — run bb_login (which prompts MFA).
    """
    ok = await _auth.refresh_session_async(headless=True)
    await _client._rebuild()
    if ok:
        return {"refreshed": True, **_auth.status()}
    return {"refreshed": False, "fix": "Azure session expired — run bb_login to re-authenticate with MFA."}


# ============================ READ ============================

@mcp.tool(annotations=_ann(read_only=True, title="Weekly briefing"))
@_guard
async def weekly_briefing(days: int = 7) -> dict:
    """One-shot 'what do I need to know': current courses + deadlines in the next `days` +
    recent announcements (which contain exam schedules and class averages). Best starting point."""
    return await _client.weekly_briefing(days)


@mcp.tool(annotations=_ann(read_only=True, title="Course overview"))
@_guard
async def course_overview(course: str) -> dict:
    """Single-course dashboard: top-level contents + recent announcements + that course's deadlines
    + your grade slice. `course` can be a name, code, or courseId."""
    return await _client.course_overview(course)


@mcp.tool(annotations=_ann(read_only=True, title="Exam prep pack"))
@_guard
async def exam_prep_pack(course: str, query: str | None = None) -> dict:
    """Everything for an upcoming exam in one shot: exam-related announcements (date/room/scope),
    the course's deadlines, its materials tree, and where you're losing points. `course`=name/code/id."""
    return await _client.exam_prep_pack(course, query)


@mcp.tool(annotations=_ann(read_only=True, title="Course outline (content tree)"))
@_guard
async def course_outline(course_id: str) -> dict:
    """The full folder/content tree of a course in one call (nested), so you can see all materials
    at a glance and then download_material the ones you want."""
    return await _client.course_outline(course_id)


@mcp.tool(annotations=_ann(read_only=True, title="Content body"))
@_guard
async def get_content_body(course_id: str, content_id: str) -> dict:
    """The readable text body of a content item (lecture page, document). If it's a file-only item,
    the result tells you to use list_attachments + download_material instead."""
    return await _client.get_content_body(course_id, content_id)


@mcp.tool(annotations=_ann(read_only=True, title="Course staff & emails"))
@_guard
async def course_staff(course_id: str) -> dict:
    """Instructors/TAs for a course (names, roles, login id) plus any emails found in the syllabus,
    announcements, or content. Blackboard hides staff emails from students via API, so the emails
    are scraped from posted text — where professors/TAs usually write them."""
    return await _client.course_staff(course_id)


@mcp.tool(annotations=_ann(read_only=True, title="Search announcements/deadlines"))
@_guard
async def search(query: str, term: str | None = "current", limit: int = 20) -> list[dict]:
    """Keyword search across this term's announcements (title+body) and upcoming deadlines.

    e.g. "디지털논리 시험", "midterm", "project 3". Returns matches with a snippet, newest first.
    """
    return await _client.search(query, term=term, limit=limit)


@mcp.tool(annotations=_ann(read_only=True, title="Grade summary (weighted)"))
@_guard
async def grade_summary(term: str | None = "current", weights: dict | None = None) -> dict:
    """Per-course grades with category breakdown and a WEIGHTED total.

    Grade priority: blackboard_total (Blackboard's own computed grade) > weighted (category
    percents × weights) > raw_percent (unweighted point sum). Many UNIST courses don't store
    weights in Blackboard, so pass your syllabus weights to get the real grade, e.g.
    weights={"Exam": 40, "Quiz": 30, "Homework": 30}, or per course
    weights={"Operating Systems": {"Exam": 50, "Assignment": 50}}.
    """
    return await _client.grade_summary(term=term, weights=weights)


@mcp.tool(annotations=_ann(read_only=True, title="List my courses"))
@_guard
async def list_courses(term: str | None = None, include_closed: bool = False) -> list[dict]:
    """List the courses I'm enrolled in (newest term first).

    - term: filter to one term, e.g. "2026090". Pass "current" for this semester's courses.
    - include_closed: also show closed courses (old votes/compliance). Default hides them.
    Returns courseId, name, courseCode, term, availability, lastAccessed.
    """
    return await _client.list_courses(term=term, include_closed=include_closed)


@mcp.tool(annotations=_ann(read_only=True, title="Course contents"))
@_guard
async def get_course_contents(course_id: str) -> list[dict]:
    """List top-level content items (folders, documents, assignments) for a course."""
    return await _client.get_course_contents(course_id)


@mcp.tool(annotations=_ann(read_only=True, title="Content children"))
@_guard
async def get_content_children(course_id: str, content_id: str) -> list[dict]:
    """List children of a content folder."""
    return await _client.get_content_children(course_id, content_id)


@mcp.tool(annotations=_ann(read_only=True, title="List attachments"))
@_guard
async def list_attachments(course_id: str, content_id: str) -> list[dict]:
    """List downloadable file attachments on a content item."""
    return await _client.list_attachments(course_id, content_id)


@mcp.tool(annotations=_ann(read_only=False, title="Download material"))
@_guard
async def download_material(course_id: str, content_id: str, attachment_id: str) -> dict:
    """Download a course-material attachment to the local download folder; returns the saved path.

    Not read-only: it writes a file to disk (under BB_DOWNLOAD_DIR).
    """
    path = await _client.download_attachment(course_id, content_id, attachment_id)
    return {"saved_to": path}


@mcp.tool(annotations=_ann(read_only=True, title="My grades"))
@_guard
async def get_grades(course_id: str) -> list[dict]:
    """Get my gradebook entries (column name, score, status) for a course."""
    return await _client.get_grades(course_id)


@mcp.tool(annotations=_ann(read_only=True, title="Announcements"))
@_guard
async def list_announcements(
    course_id: str | None = None,
    term: str | None = "current",
    limit: int = 25,
    since: str | None = None,
) -> list[dict]:
    """Course announcements with bodies as readable text — exam schedules, class averages, etc.

    Omit course_id to aggregate across this semester's courses (the useful default; the
    system-wide endpoint is empty here). Pass a course_id for one course. `since` is an
    ISO date filter (e.g. 2026-06-01); `limit` caps the newest-first results (0 = all).
    Returns {course, title, date, body, ...}.
    """
    return await _client.list_announcements(course_id=course_id, term=term, limit=limit, since=since)


@mcp.tool(annotations=_ann(read_only=True, title="Upcoming deadlines"))
@_guard
async def upcoming_deadlines(since: str | None = None, until: str | None = None) -> list[dict]:
    """List calendar items (assignment due dates, events) across all courses in a date range.

    Dates are ISO-8601 (e.g. 2026-06-16T00:00:00Z). Omit for the default server window.
    Returns {title, course, type, due} sorted by due date.
    """
    return await _client.upcoming_deadlines(since, until)


@mcp.tool(annotations=_ann(read_only=True, title="Assignment detail"))
@_guard
async def get_assignment(course_id: str, content_id: str) -> dict:
    """Get the full detail of one assignment/content item."""
    return await _client.get_assignment(course_id, content_id)


# ============================ WRITE (guarded) ============================

@mcp.tool(annotations=_ann(destructive=True, title="Create calendar reminder"))
@_guard
async def create_calendar_item(
    title: str, start: str, end: str, description: str = "", confirm: bool = False
) -> dict:
    """Create a PERSONAL calendar reminder. Requires confirm=True to actually write.

    start/end are ISO-8601. With confirm=False this returns a preview only.
    """
    if not confirm:
        return {"preview": True, "action": "create_calendar_item",
                "will_create": {"title": title, "start": start, "end": end, "description": description},
                "note": "Re-call with confirm=True to actually create this calendar item."}
    return await _client.create_calendar_item(title, start, end, description)


@mcp.tool(annotations=_ann(destructive=True, title="Submit assignment (EXPERIMENTAL)"))
@_guard
async def submit_assignment(
    course_id: str, column_id: str, text: str, confirm: bool = False
) -> dict:
    """EXPERIMENTAL & IRREVERSIBLE: submit a text attempt for an assignment column.

    Submitting is irreversible. Requires confirm=True. REST submission is brittle and may
    be disabled for students on this instance — test on a throwaway assignment first.
    """
    if not confirm:
        return {"preview": True, "action": "submit_assignment", "irreversible": True,
                "will_submit": {"course_id": course_id, "column_id": column_id,
                                "text_preview": text[:200]},
                "warning": "This SUBMITS coursework and cannot be undone. Re-call with confirm=True."}
    return await _client.submit_assignment_attempt(course_id, column_id, text)


# ============================ PROMPTS ============================

@mcp.prompt(title="이번 주 브리핑")
def weekly_briefing_prompt() -> str:
    return (
        "weekly_briefing 도구를 호출한 뒤, 결과를 한국어로 정리해줘:\n"
        "1) 다가오는 마감 (과목/제목/날짜, 임박순)\n"
        "2) 다가오는 시험 — recent_announcements 본문에서 시험 일정·장소·출제범위를 추출\n"
        "3) 새 공지 요약 — 채점 완료 공지의 평균/통계(Average/Median 등)가 있으면 함께\n"
        "마지막에 '이번 주 가장 급한 것 3가지'를 굵게 요약."
    )


@mcp.prompt(title="시험 대비")
def exam_prep_prompt(course: str = "") -> str:
    target = f" '{course}'" if course else " 현재 학기 전 과목"
    return (
        f"{target}의 시험을 대비하려고 해. list_announcements로 공지를 확인해 시험 일정과 출제범위를 찾고,"
        " get_grades로 현재 점수를 확인한 뒤, 남은 기간 대비 우선순위를 정해줘. 한국어로."
    )


@mcp.prompt(title="Weekly briefing (EN)")
def weekly_briefing_en_prompt() -> str:
    return (
        "Call weekly_briefing, then summarize in English:\n"
        "1) Upcoming deadlines (course / title / date, soonest first)\n"
        "2) Upcoming exams — extract date, room and scope from recent_announcements bodies\n"
        "3) New announcements — include class average/stats (Average/Median) from grading posts\n"
        "End with the 3 most urgent things this week in bold."
    )


@mcp.prompt(title="Exam prep (EN)")
def exam_prep_en_prompt(course: str = "") -> str:
    target = f" for '{course}'" if course else " for my current courses"
    return (
        f"Help me prepare{target}. Call exam_prep_pack (or list_announcements + grade_summary): find the "
        "exam date/scope from announcements, check my current grades, and prioritize what to study given "
        "the time left. Answer in English."
    )


def run() -> None:
    mcp.run(transport="stdio")
