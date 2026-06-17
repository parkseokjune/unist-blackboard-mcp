# Changelog

## 0.1.1 — 2026-06-17 — security & robustness hardening

After a multi-agent adversarial code review (19 confirmed findings), all were fixed:

### Security
- **Path traversal (arbitrary file write) in `download_material`** — the saved filename came
  unsanitized from the server's `Content-Disposition` header (and `course_id` from the caller),
  so `../` or an absolute path could escape the download dir. Now reduced to a safe basename
  with a resolved-path containment check.
- **Session-cookie leakage** — cookies were a bare unscoped dict, so on any 3xx redirect (or a
  malicious `BB_HOST`) httpx would attach the `BbRouter` session cookie to off-host requests.
  Cookies are now domain-scoped to the Blackboard host, and `BB_HOST` is validated as https.
- `bb_login` no longer returns raw subprocess stderr (which could echo an SSO URL/token) to the model.

### Correctness / robustness
- `download_attachment` and the write tools now get the same 401 silent-refresh + 403→Forbidden
  handling as reads; `submit_assignment` guards a missing attempt id.
- Silent refresh no longer `aclose()`s the shared httpx client out from under concurrent in-flight
  requests (detach + background drain); `bb_login` detaches instead of closing.
- `weekly_briefing` uses `return_exceptions=True` (one section's 403 no longer wipes the briefing)
  and bounds announcement-body size; `upcoming_deadlines` gained a `limit`.
- `list_courses(term="current")` returns `[]` (not all courses) when no academic term is resolvable.
- `_now()` uses `time.monotonic()`; `get_grades` handles `score: null`; `load()` tolerates a corrupt
  keychain payload; `bb_auth_status` is now guarded; `ping_and_persist` re-pings to confirm liveness.
- Setup wizard aborts if Chromium install fails and detects Claude Desktop vs Claude Code.

### Tests
- 22 tests (added `_safe_name` traversal, `BB_HOST` validation, and current-term-empty cases).

## 0.1.0 — 2026-06-16

First release. The first open-source MCP server for Blackboard Learn.

### Auth
- Session-cookie harvest via interactive browser login (handles UNIST's Azure AD SSO + MFA);
  no Blackboard developer app key / admin onboarding required.
- Cookies stored in the OS keychain (`keyring`), not plaintext files.
- **Silent SSO refresh**: replays the SAML flow headless using stored Azure cookies — mints a
  fresh Blackboard session without a new MFA prompt while the Azure session is still valid.
- **401 auto-heal** on every API call (including `whoami`) + background keep-alive ping.

### Tools (15)
- Read: `list_courses` (term filter), `get_course_contents`, `get_content_children`,
  `list_attachments`, `download_material`, `get_grades`, `list_announcements`
  (aggregates current-term courses, flattens HTML — surfaces exam schedules & class averages),
  `upcoming_deadlines`, `get_assignment`, `bb_auth_status`.
- Composite: `weekly_briefing` (courses + deadlines + recent announcements in one call).
- Session: `bb_login`, `bb_refresh`.
- Guarded write (`confirm=True` required): `create_calendar_item`, `submit_assignment` (experimental).

### Prompts (2)
- `weekly_briefing_prompt`, `exam_prep_prompt`.

### Quality
- 15 pytest tests (HTML cleaning, term parsing, course filtering, announcement aggregation,
  401→refresh→retry, whoami auto-heal, 403→Forbidden mapping, cookie sanitization).
- Read tools, download, and silent refresh verified live against blackboard.unist.ac.kr.
