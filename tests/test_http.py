"""HTTP-layer behavior with respx-mocked transport: 403 mapping, 401 auto-heal, aggregation."""
import httpx
import pytest
import respx

from unist_blackboard_mcp import config
from unist_blackboard_mcp.client import AuthExpired, BlackboardClient, Forbidden

VERSION_URL = f"{config.PUBLIC_API}/v1/system/version"


class FakeAuth:
    def __init__(self):
        self.refresh_calls = 0

    def cookies(self):
        return {"BbRouter": "x"}

    async def refresh_session_async(self, headless=True):
        self.refresh_calls += 1
        return True

    def persist_pairs(self, pairs):
        pass


@respx.mock
async def test_403_maps_to_forbidden():
    respx.get(VERSION_URL).mock(return_value=httpx.Response(403, text="nope"))
    c = BlackboardClient(auth=FakeAuth())
    with pytest.raises(Forbidden):
        await c._get(VERSION_URL)
    await c.aclose()


@respx.mock
async def test_401_triggers_silent_refresh_then_retry():
    respx.get(VERSION_URL).mock(side_effect=[
        httpx.Response(401),
        httpx.Response(200, json={"ok": True}),
    ])
    auth = FakeAuth()
    c = BlackboardClient(auth=auth)
    data = await c._json(VERSION_URL)
    assert data == {"ok": True}
    assert auth.refresh_calls == 1
    await c.aclose()


@respx.mock
async def test_401_refresh_fails_raises():
    respx.get(VERSION_URL).mock(return_value=httpx.Response(401))

    class DeadAuth(FakeAuth):
        async def refresh_session_async(self, headless=True):
            self.refresh_calls += 1
            return False

    auth = DeadAuth()
    c = BlackboardClient(auth=auth)
    with pytest.raises(AuthExpired):
        await c._json(VERSION_URL)
    assert auth.refresh_calls == 1
    await c.aclose()


@respx.mock
async def test_whoami_auto_heals_on_expiry():
    pub = f"{config.PUBLIC_API}/v1/users/me"
    priv = f"{config.PRIVATE_API}/v1/users/me"
    # both 401 first; after a silent refresh, public returns the user
    respx.get(pub).mock(side_effect=[
        httpx.Response(401),
        httpx.Response(200, json={"id": "_1_1", "userName": "x"}),
    ])
    respx.get(priv).mock(return_value=httpx.Response(401))
    auth = FakeAuth()
    c = BlackboardClient(auth=auth)
    me = await c.whoami()
    assert me["id"] == "_1_1"
    assert auth.refresh_calls == 1  # refreshed exactly once, then retried
    await c.aclose()


@respx.mock
async def test_list_announcements_aggregates_and_cleans():
    c = BlackboardClient(auth=FakeAuth())

    async def fake_courses(term=None, include_closed=False):
        return [{"courseId": "_1_1", "name": "Algorithms"},
                {"courseId": "_2_1", "name": "Probability"}]

    c.list_courses = fake_courses

    base = f"{config.PUBLIC_API}/v1/courses"
    respx.get(f"{base}/_1_1/announcements").mock(return_value=httpx.Response(200, json={
        "results": [{"id": "a1", "title": "Quiz Grades", "body": "<p>Average: 13.8</p>",
                     "created": "2026-06-09T00:00:00Z", "modified": "2026-06-09T00:00:00Z"}]}))
    respx.get(f"{base}/_2_1/announcements").mock(return_value=httpx.Response(200, json={
        "results": [{"id": "b1", "title": "Test 4", "body": "<ul><li>MGF</li><li>CLT</li></ul>",
                     "created": "2026-06-13T00:00:00Z", "modified": "2026-06-13T00:00:00Z"}]}))

    rows = await c.list_announcements(limit=10)
    assert len(rows) == 2
    # newest first
    assert rows[0]["title"] == "Test 4" and rows[0]["course"] == "Probability"
    assert "- MGF" in rows[0]["body"]
    assert rows[1]["body"] == "Average: 13.8"
    await c.aclose()
