# 다른 AI에 연결하기 (Gemini · GPT/OpenAI · 그 외 MCP 클라이언트)

이 서버는 **MCP 표준**이라 Claude 외 다른 AI에서도 씁니다. 핵심 원칙:

> **로컬(stdio)이 가장 안전합니다.** 클라이언트가 서버를 *네 컴퓨터에서* 직접 띄우므로(쿠키가 밖으로 안 나감),
> Gemini CLI·OpenAI Agents SDK 등은 **HTTP 없이 stdio로 바로** 연결하세요.
> HTTP는 (a) HTTP를 선호하는 SDK나 (b) ChatGPT 커넥터처럼 *원격 서버가 필요한* 경우에만 씁니다.

전송 방식 요약:

| 클라이언트 | stdio(로컬) | HTTP 필요? |
|---|---|---|
| Claude Desktop / Code | ✅ (기본) | – |
| Gemini CLI | ✅ 권장 | 선택(httpUrl) |
| google-genai (Gemini API) Python SDK | ✅ | – |
| OpenAI Agents SDK (Python) | ✅ 권장 | 선택 |
| ChatGPT 커넥터 / Responses API hosted `mcp` | ❌ | ✅ **공개 HTTPS 필요**(터널) |

---

## 1) Google Gemini

### Gemini CLI (권장, stdio)
`~/.gemini/settings.json` (또는 프로젝트의 `.gemini/settings.json`):

```json
{
  "mcpServers": {
    "unist-blackboard": {
      "command": "uvx",
      "args": ["unist-blackboard-mcp", "serve"],
      "timeout": 30000,
      "trust": false
    }
  }
}
```

- `trust: false` 유지 → 과제 제출/캘린더 쓰기 같은 동작은 매번 확인. (`true`면 확인 생략 — 비권장)
- 특정 도구만 노출하려면 `"includeTools": ["weekly_briefing","upcoming_deadlines","get_grades"]`.
- 참고: 2026-06부터 무료/Google One 계층은 Gemini CLI가 **Antigravity CLI**로 대체됩니다 — `mcpServers` 설정 형식은 동일하게 이어집니다.

### google-genai Python SDK (stdio)
```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google import genai
from google.genai import types  # pip install google-genai mcp ; GEMINI_API_KEY 설정

client = genai.Client()
params = StdioServerParameters(command="uvx", args=["unist-blackboard-mcp", "serve"])

async def main():
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash",                 # 현재 사용 가능한 모델 id로
            contents="이번 주 Blackboard 마감 알려줘",
            config=types.GenerateContentConfig(tools=[session]),  # MCP 세션을 도구로 전달
        )
        print(resp.text)

asyncio.run(main())
```
> MCP 세션은 비동기 전용이라 `client.aio...`(async)를 써야 합니다. (SDK의 MCP 지원은 experimental — 버전 고정 권장)

---

## 2) OpenAI / GPT

### OpenAI Agents SDK (권장, stdio)
```python
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

async def main():
    async with MCPServerStdio(
        name="UNIST Blackboard",
        params={"command": "uvx", "args": ["unist-blackboard-mcp", "serve"]},
        cache_tools_list=True,
    ) as server:
        agent = Agent(
            name="Blackboard Assistant",
            instructions="Blackboard MCP 도구로 학생 질문에 답해.",
            model="gpt-5.5",                  # 현재 사용 가능한 모델 id로
            mcp_servers=[server],
        )
        result = await Runner.run(agent, "다가오는 마감 알려줘")
        print(result.final_output)
```
→ 이 경로는 **네 코드가 서버를 로컬에서 띄우므로** 안전하고 추가 설정이 필요 없습니다.

### ChatGPT 커넥터 / Responses API hosted `mcp` (⚠️ 공개 HTTPS 필요)
ChatGPT(소비자 커넥터·Developer Mode)와 Responses API의 `mcp` 도구는 **OpenAI 서버가 직접** 네 MCP 서버를 호출하므로,
**`localhost`는 거부되고 공개 HTTPS URL이 필요**합니다. 즉 서버를 HTTP로 띄우고 터널로 노출해야 합니다 → 아래 3번 + 보안 경고 참고.

```python
from openai import OpenAI
client = OpenAI()
resp = client.responses.create(
    model="gpt-5.5",
    tools=[{
        "type": "mcp",
        "server_label": "unist_blackboard",
        "server_url": "https://<your-tunnel>/mcp",   # 공개 HTTPS (localhost 불가)
        "authorization": "Bearer <BB_HTTP_TOKEN>",   # 헤더 기반 토큰 필수
        "require_approval": "always",
        "allowed_tools": ["list_courses", "upcoming_deadlines"],
    }],
    input="다가오는 마감 알려줘",
)
print(resp.output_text)
```

---

## 3) HTTP 모드로 직접 띄우기 (HTTP 선호 SDK / 터널용)

```sh
# 로컬호스트 전용(기본) — 같은 컴퓨터의 SDK에서 http://127.0.0.1:8000/mcp 로 접속
uvx unist-blackboard-mcp serve --http                # 127.0.0.1:8000/mcp

# 공개 노출(터널) 대비 — 베어러 토큰 필수
BB_HTTP_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))") \
  uvx unist-blackboard-mcp serve --http
```

- 클라이언트는 `Authorization: Bearer <BB_HTTP_TOKEN>` 헤더로 접속. 토큰 없으면 **401**.
- 로컬호스트 바인딩 시 SDK가 **DNS 리바인딩/Origin 검증**을 자동 적용(브라우저발 CSRF 차단).
- Gemini CLI에서 HTTP로 붙이려면 `command` 대신 `"httpUrl": "http://127.0.0.1:8000/mcp"` + `headers: {"Authorization":"Bearer ..."}`.

### 원격(ChatGPT 등)에 노출해야 한다면 — 터널 + 토큰
```sh
# 서버는 반드시 127.0.0.1에 묶어두고(0.0.0.0 금지), 터널로 TLS+공개 URL을 앞에 둡니다.
BB_HTTP_TOKEN=... uvx unist-blackboard-mcp serve --http        # localhost:8000
cloudflared tunnel --url http://127.0.0.1:8000                  # 또는: ngrok http 8000
# -> https://<random>/mcp 를 ChatGPT/Responses에 등록 (+ Bearer 토큰)
```

---

## 🔒 보안 (꼭 읽기)

이 서버는 **네 Blackboard 로그인 세션**을 들고 있습니다. HTTP로 노출하는 건 곧 *네 성적·자료·과제 제출 권한*을 노출하는 것입니다.

- **기본은 stdio를 쓰세요** — 네 컴퓨터 밖으로 아무것도 안 나갑니다 (Gemini CLI/SDK, OpenAI Agents SDK 모두 stdio 가능).
- HTTP는 **127.0.0.1(로컬호스트)만** 권장. `0.0.0.0`로 묶지 마세요(특히 기숙사/캠퍼스 Wi-Fi).
- 원격 노출이 꼭 필요하면 **터널(TLS) + `BB_HTTP_TOKEN`(베어러)**를 반드시 함께. 평문 HTTP를 외부로 내보내지 마세요.
- 토큰은 소스/설정 파일에 하드코딩하지 말고 환경변수로. 길게(`secrets.token_urlsafe(32)`) 생성하세요.
- ChatGPT/Responses 같은 *서버측 호출* 경로는 OpenAI/Google 인프라가 네 서버에 접속하므로, 가능하면 피하고 로컬 SDK 경로를 쓰세요.
