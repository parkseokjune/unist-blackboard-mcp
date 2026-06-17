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


async def test_course_staff_lists_staff_and_scrapes_emails():
    c = BlackboardClient(auth=object())

    async def paged(url, params=None):
        return [
            {"courseRoleId": "Instructor",
             "user": {"name": {"given": "웅기", "family": "백"}, "userName": "10204", "contact": {"email": None}}},
            {"courseRoleId": "TeachingAssistant",
             "user": {"name": {"given": "정석", "family": "남"}, "userName": "ta1", "contact": {}}},
            {"courseRoleId": "Student", "user": {"userName": "s1"}},
        ]

    async def anns(course_id=None, limit=0):
        return [{"title": "Welcome", "body": "email the TA at ta1@unist.ac.kr"}]

    async def contents(course_id):
        return [{"id": "_1_1", "title": "Course Syllabus", "description": "prof: baek@unist.ac.kr"}]

    async def assignment(course_id, content_id):
        return {"body": "<p>extra TA: ta2@unist.ac.kr</p>"}

    c._paged = paged
    c.list_announcements = anns
    c.get_course_contents = contents
    c.get_assignment = assignment

    out = await c.course_staff("_c_")
    assert {s["role"] for s in out["staff"]} == {"Instructor", "TeachingAssistant"}  # students excluded
    assert out["staff"][0]["role"] == "Instructor"                                   # sorted first
    found = {e["email"] for e in out["emails_found"]}
    assert {"ta1@unist.ac.kr", "baek@unist.ac.kr", "ta2@unist.ac.kr"} <= found


async def test_grade_summary_category_breakdown_and_user_weights():
    c = BlackboardClient(auth=object())

    async def courses(term=None, include_closed=False):
        return [{"courseId": "_1_1", "name": "Operating Systems"}]

    async def detailed(course_id):
        rows = [
            {"column": "Quiz 1", "category": "Quiz", "type": "Manual", "is_total": False,
             "score": 18.0, "possible": 20.0, "text": None},
            {"column": "Quiz 2", "category": "Quiz", "type": "Manual", "is_total": False,
             "score": 16.0, "possible": 20.0, "text": None},
            {"column": "Midterm", "category": "Exam", "type": "Manual", "is_total": False,
             "score": 80.0, "possible": 100.0, "text": None},
            {"column": "Project 1", "category": "Assignment", "type": "Manual", "is_total": False,
             "score": None, "possible": 100.0, "text": None},
        ]
        return rows, None  # no Blackboard-defined weights

    c.list_courses = courses
    c._course_grades_detailed = detailed

    out = await c.grade_summary(weights={"Exam": 50, "Quiz": 50})
    co = out["courses"][0]
    cats = {x["category"]: x for x in co["categories"]}
    assert cats["Quiz"]["earned"] == 34.0 and cats["Quiz"]["possible"] == 40.0 and cats["Quiz"]["percent"] == 85.0
    assert cats["Exam"]["percent"] == 80.0
    assert co["pending_count"] == 1                      # Project 1 ungraded
    assert co["weights_source"] == "user"
    assert co["weighted"]["weighted_percent"] == 82.5    # (85*50 + 80*50) / 100
    assert co["raw_percent"] == 81.4                     # 114 / 140, unweighted


async def test_grade_summary_prefers_blackboard_total_and_formula_weights():
    c = BlackboardClient(auth=object())

    async def courses(term=None, include_closed=False):
        return [{"courseId": "_1_1", "name": "X"}]

    async def detailed(course_id):
        rows = [
            {"column": "HW", "category": "Homework", "type": "Manual", "is_total": False,
             "score": 9.0, "possible": 10.0, "text": None},
            {"column": "Total", "category": None, "type": "Calculated", "is_total": True,
             "score": 29.0, "possible": 30.0, "text": "96.7%"},
        ]
        return rows, {"Homework": 100}  # weights parsed from Blackboard formula

    c.list_courses = courses
    c._course_grades_detailed = detailed

    co = (await c.grade_summary())["courses"][0]
    assert co["blackboard_total"]["score"] == 29.0 and co["blackboard_total"]["percent"] == 96.7
    assert co["weights_source"] == "blackboard"
