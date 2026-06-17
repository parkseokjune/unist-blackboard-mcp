# unist-blackboard-mcp

[![CI](https://github.com/parkseokjune/unist-blackboard-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/parkseokjune/unist-blackboard-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

UNIST Blackboard(Learn Ultra)를 Claude에 연결하는 MCP 서버.
"이번 주 마감 뭐 있어?", "운영체제 강의자료 받아줘", "과목별 성적 요약해줘" 같은 요청을 Claude가 직접 처리합니다.

## 어떻게 동작하나 (인증)

UNIST Blackboard는 **Azure AD(Microsoft Entra ID) SAML SSO + MFA**로 로그인합니다. 아이디/비번
자동 전송이 불가능하므로, **실제 브라우저로 직접 로그인 → 세션 쿠키 수확 → 재사용** 방식을 씁니다.
Blackboard 개발자 앱 키(관리자 승인 필요)가 **필요 없습니다**.

```
사용자 → 브라우저로 SSO+MFA 직접 완료 → 세션 쿠키 캡처(BbRouter 등)
      → OS 키체인(keyring)에 저장 → REST API(/learn/api/public)를 그 학생 권한으로 호출
```

> 쿠키는 평문 파일이 아니라 **macOS 키체인**에 저장됩니다. 만료돼도 보통 **자동 재인증**(무MFA)되며,
> 완전 만료 시에만 다시 `login` 하면 됩니다.

## 🎓 학생용 빠른 설치

**[Claude Desktop](https://claude.ai/download)** 과 **uv**(`curl -LsSf https://astral.sh/uv/install.sh | sh`)만 있으면 한 줄:

```sh
uvx unist-blackboard-mcp setup
```

→ 브라우저 설치 + UNIST 로그인 + Claude 설정 등록까지 자동. 끝나면 Claude Desktop 재실행 후
"이번 주 뭐 해야 해?"라고 물어보세요. 자세한 단계·문제해결·개인정보는 **[INSTALL.md](INSTALL.md)** 참고.

> ⚠️ 비공식 도구. 본인 계정으로 본인 데이터만, 로그인은 네 브라우저에서, 쿠키는 네 Mac에만 저장됩니다.
> 학교 공식 승인(3LO OAuth)도 병행 추진 중입니다 → [docs/unist-official-app-request.md](docs/unist-official-app-request.md).

## 개발자 설치 (소스에서)

```bash
cd unist-blackboard-mcp
uv venv --python 3.12
uv pip install -e .
uv run playwright install chromium   # 로그인용 브라우저
```

## 사용 순서

```bash
# 1) 로그인 (브라우저가 열림 → Microsoft 로그인 + MFA 완료)
uv run unist-blackboard-mcp login

# 2) Phase 0 진단: 어떤 API 표면이 쿠키 인증을 받아주는지 확인
uv run unist-blackboard-mcp probe

# 3) 상태 확인
uv run unist-blackboard-mcp status
```

`probe` 결과에서 `public/users/me`가 200이면 그대로 사용. 만약 public이 401인데
`private/users/me`만 200이면, MCP 등록 시 `BB_API_BASE=private` 환경변수를 추가하세요.

## Claude Code에 등록

```bash
claude mcp add --scope local --transport stdio unist-blackboard \
  -- uv run --directory /Users/parkseokjune/Desktop/claude/unist-blackboard-mcp \
     unist-blackboard-mcp serve
```

## Claude Desktop에 등록

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "unist-blackboard": {
      "command": "uv",
      "args": ["run", "--directory",
               "/Users/parkseokjune/Desktop/claude/unist-blackboard-mcp",
               "unist-blackboard-mcp", "serve"]
    }
  }
}
```

## 도구 (Tools)

**복합 (추천 시작점)**
- `weekly_briefing(days=7)` — 현재 과목 + 다가오는 마감 + 최근 공지(시험일정·평균 포함)를 한 번에
- `grade_summary(term, weights)` — 전 과목 성적 (카테고리별 분해 + **가중 총점**). Blackboard에 가중 총점이 있으면 그걸 쓰고, 없으면 `weights={"Exam":40,"Quiz":30,...}`로 시험·과제 비율 적용
- `search(query)` — 공지·마감 키워드 검색 (예: "디지털논리 시험", "midterm")

**읽기 (readOnlyHint=true)**
- `bb_auth_status` — 세션 상태
- `bb_login` — 브라우저 로그인(서브프로세스). 타임아웃 시 터미널에서 `login` 권장
- `bb_refresh` — 저장된 SSO 쿠키로 **조용한 재인증**(Azure 세션 살아있으면 MFA 없이)
- `list_courses(term=, include_closed=)` — 수강 과목. `term="current"`로 이번 학기만
- `get_course_contents` / `get_content_children` — 콘텐츠 트리
- `list_attachments`, `download_material` — 자료 목록/다운로드
- `get_grades` — 성적
- `list_announcements` — 공지 (현재 학기 전 과목 통합, 본문 HTML→텍스트; 시험일정·평균·통계 포함). `since`/`limit`/`course_id` 옵션
- `upcoming_deadlines` — 마감/일정(전 과목)
- `get_assignment` — 과제 상세

**쓰기 (destructiveHint=true, `confirm=True` 필수)**
- `create_calendar_item` — 개인 캘린더 알림 생성
- `submit_assignment` — ⚠️ 실험적·비가역. 제출 전 반드시 테스트 과제로 검증

## 프롬프트 (Prompts)
- `weekly_briefing_prompt` — "이번 주 브리핑" (마감+시험+공지 평균까지 한국어 정리)
- `exam_prep_prompt(course="")` — 시험 대비 (공지 일정/범위 + 현재 점수로 우선순위)

## 세션 유지

- **Keep-alive**: 서버 실행 중 백그라운드로 ~10분마다 핑 → 세션 워밍 + 쿠키 갱신 저장
- **401 자동복구**: 도구 호출 중 세션 만료(401) 시 자동으로 1회 silent refresh 후 재시도
- **수동**: `bb_refresh` 도구 또는 `uv run unist-blackboard-mcp refresh`
- Azure SSO 세션까지 만료되면 `login`(MFA) 재실행 필요

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `BB_HOST` | `https://blackboard.unist.ac.kr` | 타 Blackboard 대학으로 전환 시 |
| `BB_API_BASE` | `public` | `private`로 두면 Ultra 내부 API 사용 |
| `BB_DOWNLOAD_DIR` | `~/Downloads/unist-blackboard` | 다운로드 위치 |
| `BB_PROFILE` | `default` | 키체인 프로필(계정 분리) |
| `BB_KEEPALIVE_SECONDS` | `600` | keep-alive 핑 간격 |
| `BB_COURSES_TTL` | `300` | 과목 목록 캐시 TTL |
| `BB_REFRESH_TIMEOUT_MS` | `45000` | silent refresh 대기 한도 |

## 주의

개인 학습 보조용입니다. 대량 자동 다운로드/계정 공유 금지, 정중한 요청 간격 유지.
세션 쿠키 방식은 UNIST 로그인 흐름이 바뀌면 깨질 수 있습니다(취약성). 향후 UNIST 관리자
(`BLACKBOARD@UNIST.AC.KR`)가 공식 REST 앱을 등록해주면 OAuth 3LO로 교체 가능합니다.

## 상태

**Phase 1 완료 (2026-06-16, blackboard.unist.ac.kr).** 15 tools + 2 prompts, 14개 테스트 통과.

라이브 검증됨: `weekly_briefing`·`list_courses`(학기 필터)·`get_grades`(실제 점수)·
`get_course_contents`·`upcoming_deadlines`·`list_announcements`(시험·평균 본문)·`whoami`·
keep-alive 핑, **그리고 silent refresh — `refresh`가 MFA 없이 새 세션 발급 성공**(저장된 Azure
SSO 쿠키로 SAML 재실행). public API가 쿠키 인증을 받아줌(`/users/me` OK, 과목 목록 `expand=course`
1회, `GET /courses/{id}` 일부 403 회피).

미검증(저위험): `download_material`, 쓰기 도구 `create_calendar_item`·`submit_assignment`
(계정 변경이라 의도적으로 라이브 테스트 안 함).

테스트: `uv run pytest -q`. 세계 최초 오픈소스 Blackboard MCP(2026-06 기준 Canvas MCP만 존재).
