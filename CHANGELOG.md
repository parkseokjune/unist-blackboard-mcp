# Changelog

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
