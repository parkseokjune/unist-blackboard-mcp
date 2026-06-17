"""list_courses filtering / term logic, with memberships stubbed (no network)."""
from unist_blackboard_mcp.client import BlackboardClient


def _membership(code, name, avail, last=None):
    return {
        "courseId": f"_{abs(hash(code)) % 9999}_1",
        "courseRoleId": "Student",
        "lastAccessed": last,
        "course": {"courseId": code, "name": name, "availability": {"available": avail}},
    }


FIXTURE = [
    _membership("2026090_CSE31101", "Operating Systems", "Term", "2026-06-14T00:00:00Z"),
    _membership("2026090_CSE33101", "Algorithms", "Term", "2026-06-16T00:00:00Z"),
    _membership("2025092_CSE22101", "Data Structures", "Term", "2025-12-01T00:00:00Z"),
    _membership("2026_Online_Violence", "Compliance", "Yes", None),
    _membership("2024_vote_dorm", "Old Vote", "No", None),
]


def _client():
    c = BlackboardClient(auth=object())  # auth unused because _memberships is stubbed

    async def fake_memberships():
        return FIXTURE

    c._memberships = fake_memberships
    return c


async def test_default_excludes_closed():
    rows = await _client().list_courses()
    codes = {r["courseCode"] for r in rows}
    assert "2024_vote_dorm" not in codes          # availability "No" dropped
    assert "2026_Online_Violence" in codes        # "Yes" kept
    assert "2026090_CSE31101" in codes            # "Term" kept


async def test_include_closed():
    rows = await _client().list_courses(include_closed=True)
    assert any(r["courseCode"] == "2024_vote_dorm" for r in rows)


async def test_term_current_picks_latest():
    rows = await _client().list_courses(term="current")
    assert {r["courseCode"] for r in rows} == {"2026090_CSE31101", "2026090_CSE33101"}
    # within a term, newest lastAccessed first
    assert rows[0]["courseCode"] == "2026090_CSE33101"


async def test_explicit_term_filter():
    rows = await _client().list_courses(term="2025092")
    assert [r["courseCode"] for r in rows] == ["2025092_CSE22101"]
    assert rows[0]["term"] == "2025092"


async def test_term_current_with_no_academic_terms_returns_empty():
    # If no enrolment has a parseable 7-digit term, "current" must return [] (not all courses).
    c = BlackboardClient(auth=object())

    async def only_non_academic():
        return [_membership("2026_Online_Violence", "Compliance", "Yes"),
                _membership("vote_for_x", "Vote", "Yes")]

    c._memberships = only_non_academic
    assert await c.list_courses(term="current") == []
