# unist-blackboard-mcp

[![CI](https://github.com/parkseokjune/unist-blackboard-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/parkseokjune/unist-blackboard-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

**UNIST Blackboard를 Claude에 연결하는 MCP 서버.** Claude에게 평소 말하듯 물어보면 Blackboard에서
직접 찾아 답해줍니다 — *"이번 주 뭐 해야 해?"*, *"운영체제 시험 언제고 범위 뭐야?"*,
*"내 성적 시험40·과제30으로 계산해줘"*, *"알고리즘 강의자료 다 받아줘"*, *"확률 교수님 이메일 알려줘"*.

> 2026-06 기준 **세계 최초의 오픈소스 Blackboard MCP** (그동안 Canvas LMS용만 있었습니다).

---

## 🎓 빠른 설치 (학생용)

준비물: **[Claude Desktop](https://claude.ai/download)** + **uv** (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

```sh
uvx unist-blackboard-mcp setup
```

이 한 줄이 ① 로그인용 브라우저 설치 ② UNIST 로그인 창(직접 SSO+MFA) ③ Claude 설정 등록까지 자동으로 합니다.
끝나면 **Claude Desktop을 재실행**하고 *"이번 주 뭐 해야 해?"* 라고 물어보세요.
단계별 안내·문제해결은 **[INSTALL.md](INSTALL.md)**.

> ⚠️ 비공식 도구입니다. **본인 계정으로 본인 데이터만** 봅니다. 로그인은 네 브라우저에서 일어나고
> 쿠키는 네 Mac 키체인에만 저장됩니다(외부 전송 없음). 학교 공식 승인(3LO OAuth)도 병행 추진 중 →
> [docs/unist-official-app-request.md](docs/unist-official-app-request.md).

---

## ✨ 무엇을 할 수 있나요? (기능별)

Claude에게 자연어로 물으면 알아서 아래 도구를 호출합니다. 괄호 안이 실제 도구 이름입니다.

### 📅 이번 주 한눈에
> *"이번 주 뭐 해야 해?"* · *"이번 주 브리핑 해줘"*

- **`weekly_briefing`** — 현재 학기 과목 + 다가오는 마감 + 최근 공지(시험 일정·반 평균 포함)를 **한 번에**. 가장 좋은 시작점.

### ⏰ 마감 & 시험
> *"다가오는 마감 알려줘"* · *"운영체제 시험 대비 자료 정리해줘"*

- **`upcoming_deadlines`** — 전 과목 마감·일정을 임박순으로 (과제/퀴즈/시험).
- **`exam_prep_pack(course)`** — 한 과목 시험 대비 한방: 시험 공지(일정·장소·범위) + 마감 + 자료 트리 + 내 취약 카테고리.

### 📊 성적 (가중치 반영)
> *"내 성적 정리해줘"* · *"운영체제 시험50 과제50으로 지금 몇 점이야?"*

- **`grade_summary(term, weights)`** — 전 과목 성적을 **카테고리별(시험/퀴즈/과제…)로 분해**하고 **가중 총점** 계산.
  - Blackboard에 가중 총점 컬럼이 있으면 그 값을 그대로 사용,
  - 없으면 `weights={"Exam":40,"Quiz":30,"Homework":30}` 처럼 **네 실래버스 비율**을 넘기면 그 비율로 계산.
  - 단순 점수합(`raw_percent`)도 함께 제공.
- **`get_grades(course_id)`** — 한 과목의 항목별 점수.

### 📢 공지 (시험 일정·평균이 여기 있음)
> *"이번주 공지 뭐 있어?"* · *"디지털논리 시험 공지 찾아줘"*

- **`list_announcements`** — 현재 학기 **전 과목 공지 통합**, 본문을 읽기 좋은 텍스트로 정리(시험 일정·반 평균/통계 포함). `since`/`limit`/`course_id` 옵션. 본문에 첨부 이미지/링크가 있으면 URL도 함께.
- **`search(query)`** — 공지·마감을 키워드로 검색하고 매치 부분을 스니펫으로.

### 📚 강의자료
> *"운영체제 강의자료 목록 보여줘"* · *"알고리즘 자료 폴더째로 다 받아줘"*

- **`course_outline(course_id)`** — 과목 전체 폴더/자료 트리를 **한 번에** (중첩 구조).
- **`get_content_body(course_id, content_id)`** — 강의 페이지·문서의 본문 텍스트.
- **`download_material(course_id, content_id, attachment_id)`** — 파일 1개 다운로드.
- **`download_course_materials(course_id, confirm)`** — 과목 **전체 자료를 폴더 구조 그대로 일괄 다운로드**. 기본은 미리보기(목록)만, `confirm=true`로 실제 다운로드.

### 🗂️ 과목 정보
> *"이번 학기 내 과목 뭐 있어?"* · *"운영체제 현황 한눈에 보여줘"*

- **`list_courses(term, include_closed)`** — 수강 과목. `term="current"`로 이번 학기만.
- **`course_overview(course)`** — 한 과목 대시보드: 자료 + 최근 공지 + 그 과목 마감 + 내 성적.
- `get_course_contents` / `get_content_children` — 콘텐츠를 한 단계씩.
- `get_assignment(course_id, content_id)` — 과제 상세.

### 👩‍🏫 교수·TA 연락처
> *"확률 교수님 이메일 알려줘"* · *"운영체제 TA 누구야?"*

- **`course_staff(course_id)`** — 교수·TA 명단(이름·역할·로그인ID) + **실래버스 PDF·공지에서 추출한 이메일**.
  (Blackboard API는 교직원 이메일을 학생에게 안 주므로, 실래버스/공지 텍스트에서 직접 긁어옵니다.)

### ✍️ 쓰기 (반드시 확인 후 실행)
> *"이 과제 마감 캘린더에 추가해줘"*

- **`create_calendar_item`** — 개인 캘린더에 알림 추가. `confirm=true` 필요.
- **`submit_assignment`** — ⚠️ 실험적·비가역. 제출 전 반드시 테스트 과제로 검증. `confirm=true` 필요.

### 🔧 내 정보 & 진단
- **`bb_whoami`** — 내 신원(이름·로그인ID·학번·이메일).
- **`bb_auth_status`** — 세션 상태(로그인 여부·만료 시간).
- **`bb_server_info`** — MCP 버전 + 라이브 Blackboard 빌드(버그 리포트용).
- **`bb_login`** / **`bb_refresh`** — 브라우저 로그인 / 조용한 재인증.

### 💬 프롬프트 (Claude의 `/` 메뉴에 표시)
- `weekly_briefing_prompt` / `weekly_briefing_en_prompt` — "이번 주 브리핑" (한/영)
- `exam_prep_prompt` / `exam_prep_en_prompt` — "시험 대비" (한/영)

---

## 🛡️ 안정성 & 보안 (Stability & Security)

여러 학생이 매일 쓰는 도구라 안정성과 안전성을 최우선으로 설계했습니다.

### 세션이 알아서 유지됩니다
- **자동 재인증(Silent refresh)** — 세션이 만료돼도, 저장된 SSO 쿠키로 SAML을 다시 태워 **MFA 없이** 새 세션을 발급합니다(Azure 세션이 살아있는 동안, 보통 수일~수주). 실측 검증됨.
- **401 자동복구** — 도구 실행 중 만료(401)가 나면 자동으로 1회 재인증 후 재시도합니다. (첫 호출인 `whoami`까지 포함)
- **Keep-alive** — 서버 실행 중 백그라운드로 ~10분마다 가벼운 핑을 보내 세션을 따뜻하게 유지하고 갱신된 쿠키를 저장합니다.
- 완전히 만료(Azure 세션까지)된 경우에만 `login`을 다시 하면 됩니다.

### 끊김 없이 동작합니다 (Graceful degradation)
- 한 과목이 권한 없음(403)이어도 **나머지는 정상** 처리됩니다(`weekly_briefing`/`grade_summary`/`course_staff` 등은 부분 실패를 흡수하고 `partial` 표시).
- 손상된 키체인·빈 결과·없는 과목 등 예외 상황도 친절한 메시지로 degrade하며, 서버가 죽지 않습니다.

### LMS에 정중하게, 출력은 가볍게
- **동시성 제한** — 동시 HTTP 요청을 상한(`BB_MAX_CONCURRENCY`, 기본 6)으로 묶어 학교 서버에 부담/차단(rate-limit)을 피합니다.
- **출력 크기 가드** — 어떤 도구든 결과가 너무 크면(`BB_MAX_OUTPUT_CHARS`, 기본 40k) 자동으로 잘라 `_truncated` 표시 — Claude의 토큰 예산을 보호합니다.
- **캐싱** — 과목 목록은 짧게 캐시(`BB_COURSES_TTL`)해 불필요한 호출을 줄입니다.

### 개인정보·보안
- **로그인은 네 브라우저에서만** — 이 도구는 아이디/비번을 받지 않습니다(UNIST Azure SSO 화면에 직접 입력).
- **쿠키는 OS 키체인에만** 저장(평문 파일 아님), **외부 서버로 전송하지 않음**. 통신은 `blackboard.unist.ac.kr`와 네 Mac 사이뿐.
- **쿠키 호스트 스코핑** — 세션 쿠키는 Blackboard 호스트에만 전송되도록 묶여 있어, 리다이렉트로 외부 도메인에 새지 않습니다. `BB_HOST`는 https만 허용.
- **경로 탐색 차단** — 다운로드 파일/폴더 이름을 모두 정규화(`../`·절대경로 무력화)해 다운로드 폴더 밖에 쓰지 못합니다.
- **읽기 우선 + 쓰기 확인 게이트** — 기본은 조회. 캘린더 추가/과제 제출 같은 쓰기는 `confirm=true`를 강제합니다.
- **로그 안전** — stdout은 JSON-RPC 전용(오염 금지), 민감정보(쿠키/토큰)는 결과로 반환하지 않습니다.

### 품질
- **33개 자동 테스트** + **GitHub Actions CI**(Python 3.10/3.11/3.12) 그린. (`uv run pytest -q`)
- 모든 읽기 기능·자동 재인증·일괄 다운로드를 **실서버(blackboard.unist.ac.kr)로 라이브 검증**.
- 출시 전 **다중 에이전트 보안 리뷰**로 19건(경로 탐색·쿠키 누출 등)을 잡아 수정.

### 자가 진단
문제가 생기면 한 줄로 점검:
```sh
uvx unist-blackboard-mcp doctor
```
→ 파이썬·의존성·브라우저·키체인·호스트·세션·라이브 핑·Claude 등록 여부를 PASS/WARN/FAIL로 보여줍니다.
`uvx unist-blackboard-mcp version` 으로 버전 번들도 확인 가능(버그 리포트에 첨부).

---

## 🧰 전체 도구 목록 (25)

| 그룹 | 도구 | 설명 |
|---|---|---|
| 복합 | `weekly_briefing` | 과목+마감+최근 공지 한 번에 |
| 복합 | `course_overview(course)` | 한 과목 대시보드 |
| 복합 | `exam_prep_pack(course)` | 시험 대비 묶음 |
| 성적 | `grade_summary(term, weights)` | 카테고리 분해 + 가중 총점 |
| 성적 | `get_grades(course_id)` | 항목별 점수 |
| 공지 | `list_announcements` | 전 과목 공지(본문 정리) |
| 검색 | `search(query)` | 공지·마감 키워드 검색 |
| 마감 | `upcoming_deadlines` | 마감/일정(임박순) |
| 과목 | `list_courses(term)` | 수강 과목 |
| 자료 | `course_outline(course_id)` | 전체 콘텐츠 트리 |
| 자료 | `get_content_body` | 콘텐츠 본문 텍스트 |
| 자료 | `get_course_contents`/`get_content_children` | 콘텐츠 단계별 |
| 자료 | `list_attachments` / `download_material` | 첨부 목록 / 단일 다운로드 |
| 자료 | `download_course_materials(course_id, confirm)` | 폴더째 일괄 다운로드 |
| 과제 | `get_assignment` | 과제 상세 |
| 연락처 | `course_staff(course_id)` | 교수·TA + 이메일(PDF 포함) |
| 쓰기 | `create_calendar_item` ⚠️ | 개인 캘린더 추가(confirm) |
| 쓰기 | `submit_assignment` ⚠️ | 과제 제출(실험적, confirm) |
| 인증 | `bb_login` / `bb_refresh` | 로그인 / 재인증 |
| 정보 | `bb_whoami` / `bb_auth_status` / `bb_server_info` | 내 정보 / 세션 / 버전 |

---

## ⌨️ CLI 명령어

```sh
uvx unist-blackboard-mcp setup     # 최초 설치 마법사 (브라우저+로그인+등록)
uvx unist-blackboard-mcp login     # 로그인(브라우저 SSO+MFA)
uvx unist-blackboard-mcp refresh   # 조용한 재인증(무MFA 시도)
uvx unist-blackboard-mcp doctor    # 자가 진단
uvx unist-blackboard-mcp status    # 세션 상태
uvx unist-blackboard-mcp version   # 버전/환경 번들
uvx unist-blackboard-mcp logout    # 저장된 세션 삭제
uvx unist-blackboard-mcp serve     # MCP 서버 실행(클라이언트가 자동 호출)
```

## ⚙️ 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `BB_HOST` | `https://blackboard.unist.ac.kr` | 타 Blackboard 대학으로 전환(https만 허용) |
| `BB_API_BASE` | `public` | `private`로 두면 Ultra 내부 API 사용 |
| `BB_DOWNLOAD_DIR` | `~/Downloads/unist-blackboard` | 다운로드 위치 |
| `BB_PROFILE` | `default` | 키체인 프로필(계정 분리) |
| `BB_KEEPALIVE_SECONDS` | `600` | keep-alive 핑 간격 |
| `BB_COURSES_TTL` | `300` | 과목 목록 캐시 TTL |
| `BB_REFRESH_TIMEOUT_MS` | `45000` | silent refresh 대기 한도 |
| `BB_MAX_CONCURRENCY` | `6` | 동시 HTTP 요청 상한 |
| `BB_MAX_OUTPUT_CHARS` | `40000` | 도구 출력 크기 소프트 캡 |

---

## 🧑‍💻 개발 / 소스 설치

```bash
git clone https://github.com/parkseokjune/unist-blackboard-mcp
cd unist-blackboard-mcp
uv venv --python 3.12
uv pip install -e ".[dev]"
uv run playwright install chromium
uv run pytest -q                    # 테스트
uv run unist-blackboard-mcp login   # 로그인
```

Claude Code에 등록:
```bash
claude mcp add --scope user --transport stdio unist-blackboard \
  -- uvx unist-blackboard-mcp serve
```

진단용: `uv run unist-blackboard-mcp probe` 는 어떤 API 표면이 쿠키 인증을 받는지 확인합니다.
`public/users/me`가 200이 아니고 `private/users/me`만 200이면 `BB_API_BASE=private`로 등록하세요.

---

## ⚠️ 주의 & 라이선스

개인 학습 보조용입니다. 대량 자동 다운로드/계정 공유 금지, 정중한 요청 간격을 지키세요.
세션 쿠키 방식은 UNIST 로그인 흐름이 바뀌면 깨질 수 있습니다. UNIST 관리자(`BLACKBOARD@UNIST.AC.KR`)가
공식 REST 앱을 등록해주면 OAuth 3LO로 전환할 수 있습니다.

MIT License · 변경 이력은 [CHANGELOG.md](CHANGELOG.md).
