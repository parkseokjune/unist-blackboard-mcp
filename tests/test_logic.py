"""Pure-logic unit tests (no network)."""
import pytest

from unist_blackboard_mcp.auth import _is_bb_cookie, _sanitize_for_add
from unist_blackboard_mcp.client import (
    BlackboardClient,
    _html_to_text,
    _shape_announcement,
    _term_of,
)
from unist_blackboard_mcp.config import _validate_host


def test_safe_name_neutralizes_path_traversal():
    sn = BlackboardClient._safe_name
    assert sn("../../../../evil.sh", "fb") == "evil.sh"   # relative traversal stripped
    assert sn("/etc/cron.d/evil", "fb") == "evil"          # absolute path stripped
    assert sn("a/b/c.pdf", "fb") == "c.pdf"                # nested path -> basename
    assert sn("..\\..\\evil", "fb") == "evil"              # windows separators
    assert sn(".hidden", "fb") == "hidden"                  # leading dots stripped
    assert sn("normal_file.pdf", "fb") == "normal_file.pdf"
    for bad in ("", None, "..", ".", "/"):
        assert sn(bad, "fallback") == "fallback"            # empties/dots -> fallback


def test_safe_name_per_segment_blocks_nested_traversal():
    # download_course_materials sanitizes EACH folder segment with _safe_name before joining.
    sn = BlackboardClient._safe_name
    segs = [sn(s, "folder") for s in "../../etc/cron.d".split("/") if s.strip()]
    assert segs == ["folder", "folder", "etc", "cron.d"]      # ".." -> fallback, no traversal
    assert all(".." not in s and "/" not in s for s in segs)


def test_validate_host_requires_https():
    assert _validate_host("https://blackboard.unist.ac.kr") == "https://blackboard.unist.ac.kr"
    for bad in ("http://blackboard.unist.ac.kr", "blackboard.unist.ac.kr", "ftp://x", ""):
        with pytest.raises(ValueError):
            _validate_host(bad)


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
