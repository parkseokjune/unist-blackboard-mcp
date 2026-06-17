# 설치 가이드 (UNIST 학생용)

Claude로 UNIST Blackboard를 다루는 도구입니다. "이번 주 뭐 해야 해?", "이번주 공지", "운영체제 성적
정리해줘" 같은 걸 Claude가 바로 처리합니다.

> ⚠️ 비공식 도구입니다. 본인 계정으로 본인 데이터만 봅니다. 로그인은 **네 브라우저**에서 이뤄지고,
> 세션 쿠키는 **네 Mac 키체인**에만 저장됩니다(서버 업로드 없음). [개인정보·보안](#개인정보보안) 참고.

## 0. 미리 필요한 것
- **Claude Desktop** (또는 Claude Code) — MCP 도구를 쓰려면 필수. https://claude.ai/download
- **uv** (파이썬 런처) — 없으면 한 줄로 설치:
  ```sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

## 1. 한 번에 설치 (권장)
터미널에 그대로 붙여넣으세요. (주석 `#` 줄은 빼고 한 줄씩)

```sh
uvx unist-blackboard-mcp setup
```

이 한 줄이 자동으로:
1. 로그인용 브라우저(Chromium) 설치
2. UNIST 로그인 창을 띄움 → **Microsoft 로그인 + MFA**를 직접 완료
3. Claude Desktop 설정에 서버를 자동 등록

끝나면 **Claude Desktop을 완전히 종료 후 재실행**하세요.

## 2. 써보기
Claude에게:
- "이번 주 뭐 해야 해?" → 마감 + 시험일정 + 공지 요약
- "이번주 공지 알려줘"
- "운영체제 내 성적 평균 대비 어때?"
- "알고리즘 강의자료 받아줘"

## 세션이 만료되면?
보통 **자동으로 재인증**됩니다(MFA 없이). 완전히 만료된 경우에만:
```sh
uvx unist-blackboard-mcp login
```

## Claude Code 사용자
```sh
claude mcp add --scope user --transport stdio unist-blackboard \
  -- uvx unist-blackboard-mcp serve
```

## 개인정보·보안
- **로그인은 네 브라우저에서만** 일어납니다. 아이디/비번을 이 도구가 받지 않습니다(UNIST Azure SSO 화면에 직접 입력).
- 로그인 후 **세션 쿠키만** macOS 키체인에 저장됩니다. **외부 서버로 전송하지 않습니다** — 통신은 UNIST(`blackboard.unist.ac.kr`)와 네 Mac 사이뿐.
- 소스 전체 공개(MIT): https://github.com/parkseokjune/unist-blackboard-mcp — 직접 확인 가능.
- 기본은 **읽기 위주**. 쓰기(과제 제출 등)는 `confirm` 확인을 강제하며 기본 사용 안 함.
- 삭제: `uvx unist-blackboard-mcp logout` (쿠키 삭제) + Claude 설정에서 서버 항목 제거.

## 문제가 생기면
- "command not found: uvx" → uv 설치(위 0번) 후 새 터미널.
- 브라우저가 안 뜨거나 로그인 후 멈춤 → `uvx unist-blackboard-mcp login` 재시도.
- Claude에서 도구가 안 보임 → Claude Desktop **완전 종료 후 재실행**.
- 그 외 → GitHub Issues에 남겨주세요.
