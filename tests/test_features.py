"""search / grade_summary logic, with underlying calls stubbed (no network)."""
from unist_blackboard_mcp.client import BlackboardClient, _snippet


def test_snippet_centers_on_match():
    text = "intro padding then the QUIZ keyword and trailing words after it here"
    s = _snippet(text, "quiz", width=30)
    assert "QUIZ" in s
    assert s.startswith("…") and len(s) < len(text)


def test_snippet_no_match_returns_head():
    assert _snippet("hello world", "zzz", width=5).startswith("hello")
    assert _snippet("", "x") == ""


async def test_search_matches_body_and_deadline():
    c = BlackboardClient(auth=object())

    async def anns(term=None, limit=0):
        return [
            {"course": "Probability", "title": "Test 4", "body": "covers MGF and CLT",
             "date": "2026-06-13", "courseId": "_1_1"},
            {"course": "OS", "title": "FAQ", "body": "34 test cases", "date": "2026-06-12", "courseId": "_2_1"},
        ]

    async def deadlines(limit=0):
        return [{"course": "Algorithms", "title": "Quiz #6", "due": "2026-06-19"}]

    c.list_announcements = anns
    c.upcoming_deadlines = deadlines

    hits = await c.search("clt")
    assert len(hits) == 1
    assert hits[0]["course"] == "Probability" and "CLT" in hits[0]["snippet"]

    hits2 = await c.search("quiz")
    assert any(h["type"] == "deadline" and h["title"] == "Quiz #6" for h in hits2)

    assert await c.search("") == []  # empty query


async def test_grade_summary_computes_raw_percent_and_overall():
    c = BlackboardClient(auth=object())

    async def courses(term=None, include_closed=False):
        return [{"courseId": "_1_1", "name": "Operating Systems"}]

    async def grades(cid):
        return [
            {"column": "Project #1", "score": 98.6, "text": None, "status": "Graded", "possible": 100.0},
            {"column": "Midterm", "score": 16.0, "text": None, "status": "Graded", "possible": 100.0},
            {"column": "Project #3", "score": None, "text": None, "status": None, "possible": 100.0},
            {"column": "Overall Grade", "score": None, "text": "57%", "status": None, "possible": 200.0},
        ]

    c.list_courses = courses
    c.get_grades = grades

    out = await c.grade_summary()
    co = out["courses"][0]
    assert co["graded_count"] == 2 and co["pending_count"] == 2
    assert co["raw_earned"] == 114.6 and co["raw_possible"] == 200.0
    assert co["raw_percent"] == 57.3
    assert co["overall_column"]["name"] == "Overall Grade" and co["overall_column"]["text"] == "57%"
