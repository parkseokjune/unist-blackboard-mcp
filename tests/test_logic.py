"""Pure-logic unit tests (no network)."""
from unist_blackboard_mcp.auth import _is_bb_cookie, _sanitize_for_add
from unist_blackboard_mcp.client import _html_to_text, _shape_announcement, _term_of


def test_html_to_text_bullets_and_breaks():
    html = "<p>Test 4 on Jun 15.</p><br><ul><li>un 3-1</li><li>un 3-2</li></ul><p>Prof.</p>"
    text = _html_to_text(html)
    assert "Test 4 on Jun 15." in text
    assert "- un 3-1" in text
    assert "- un 3-2" in text
    # no leftover tags, and bullets are not double-spaced
    assert "<" not in text and ">" not in text
    assert "\n\n\n" not in text


def test_html_to_text_entities_and_nbsp():
    assert _html_to_text("a&nbsp;b &amp; c") == "a b & c"
    assert _html_to_text("") == ""
    assert _html_to_text(None) == ""


def test_term_of():
    assert _term_of("2026090_CSE31101") == "2026090"
    assert _term_of("health_on_suicide_prevention") is None
    assert _term_of(None) is None


def test_shape_announcement():
    a = {"id": "_1_1", "title": "Quiz", "body": "<p>Average: 13.8</p>",
         "created": "2026-06-01T00:00:00Z", "modified": "2026-06-02T00:00:00Z"}
    s = _shape_announcement(a, "_99_1", "Algorithms")
    assert s["course"] == "Algorithms"
    assert s["courseId"] == "_99_1"
    assert s["date"] == "2026-06-02T00:00:00Z"  # prefers modified
    assert s["body"] == "Average: 13.8"


def test_is_bb_cookie():
    assert _is_bb_cookie("blackboard.unist.ac.kr")
    assert _is_bb_cookie(".unist.ac.kr")
    assert _is_bb_cookie("unist.blackboard.com")
    assert not _is_bb_cookie("login.microsoftonline.com")
    assert not _is_bb_cookie("")


def test_sanitize_for_add():
    recs = [
        {"name": "a", "value": "1", "domain": "blackboard.unist.ac.kr", "path": "/",
         "sameSite": "Lax", "httpOnly": True, "expires": 123.0},
        {"name": "b", "value": "2"},  # no domain -> dropped
        {"name": "c", "value": "3", "domain": "x.com", "sameSite": "bogus"},  # bad sameSite dropped
    ]
    out = _sanitize_for_add(recs)
    names = {c["name"] for c in out}
    assert names == {"a", "c"}
    a = next(c for c in out if c["name"] == "a")
    assert a["sameSite"] == "Lax" and a["httpOnly"] is True and a["path"] == "/"
    c = next(c for c in out if c["name"] == "c")
    assert "sameSite" not in c and c["path"] == "/"
