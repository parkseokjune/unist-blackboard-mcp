# UNIST 공식 REST API 앱 등록 요청 (이메일 초안)

> 보내는 곳: `BLACKBOARD@UNIST.AC.KR` (Pioneers 교육혁신팀, T. 052-217-4103)
> 목적: 현재 "학생 본인 브라우저 세션 재사용" 방식을, **공식 REST API 앱(3LO OAuth)** 으로 전환해
> 학교 승인 하에 안정적으로 운영. 보내기 전 `[ ]` 부분(이름/학번/연락처/GitHub)을 채우세요.

---

## 국문

제목: [학생 프로젝트] Blackboard 공식 REST API 애플리케이션 등록 문의

안녕하세요, 교육혁신팀 담당자님.

저는 UNIST 재학생 [이름, 학번]입니다. 학생들이 **Claude(AI 어시스턴트)**에게
"이번 주 마감 알려줘", "공지 요약해줘", "내 성적 정리해줘"처럼 물으면 Blackboard 정보를
자연어로 받아볼 수 있는 오픈소스 도구를 만들었습니다.
(소스 공개, MIT 라이선스: [GitHub URL])

**현재 동작 방식과 한계**
- 현재는 학생이 평소처럼 브라우저로 Blackboard에 로그인(Azure SSO + MFA)한 뒤,
  그 **본인 세션**으로 공개 REST API(`/learn/api/public`)를 호출해 **본인 데이터만 읽기**로 가져옵니다.
- 자격증명은 도구가 받지 않으며(SSO 화면에 직접 입력), 세션 쿠키는 학생 PC에만 저장됩니다.
- 다만 이 방식은 (1) 세션이 짧아 자주 재로그인이 필요하고, (2) 비공식 경로라 향후 학교 정책/로그인
  변경에 취약하며, (3) 다수 학생이 쓰기엔 적절한 방법이 아니라고 판단했습니다.

**요청 드리는 것**
Blackboard Learn의 **공식 REST API 통합(3LO, Three-Legged OAuth)** 으로 전환하고자 합니다.
이를 위해 관리자님의 인스턴스에 저희 애플리케이션을 등록(승인)해 주실 수 있는지 문의드립니다.
- 제가 Anthology 개발자 포털에서 발급받은 **Application ID(UUID)**를 전달드리면,
  System Admin > Integrations > REST API Integrations 에서 등록 + **End User Access=Yes**로
  설정해 주시면 됩니다.
- 권한 범위는 **읽기(read) 최소 권한**이면 충분합니다(과목/콘텐츠/성적/공지/일정 조회).
- 각 학생은 자신의 UNIST 계정으로 직접 동의·로그인하므로, 도구가 타인 데이터에 접근하지 않습니다.

**기대 효과**
- 학교가 승인·통제하는 공식 경로 → 보안·정책 준수, 안정성 향상.
- 학생 편의(마감/공지/성적 확인) 개선. 필요하시면 사용 범위·인원·로그를 제한하는 방향도 함께 논의 가능합니다.

가능하시다면 등록 절차나 필요한 추가 정보, 혹은 짧은 미팅을 안내해 주시면 감사하겠습니다.
요구되는 보안 검토나 조건이 있으면 적극 따르겠습니다.

감사합니다.
[이름] 드림 / [학번] / [이메일·연락처] / [GitHub URL]

---

## English

Subject: [Student project] Request to register an official Blackboard REST API application

Dear Education Innovation Team,

I am [Name], a UNIST student ([student ID]). I built an open-source tool that lets students
ask an AI assistant (Claude) natural-language questions about Blackboard — upcoming deadlines,
announcement summaries, their own grades. (Open source, MIT: [GitHub URL])

**How it works today / its limits**
- A student logs into Blackboard as usual (Azure SSO + MFA) in their own browser; the tool then
  uses that **personal session** to read **only the student's own data** via the public REST API
  (`/learn/api/public`). The tool never receives the password (entered on the SSO page), and the
  session cookie stays on the student's own computer.
- However this approach is (1) short-lived (frequent re-login), (2) unofficial and fragile to
  policy/login changes, and (3) not the right mechanism for many students.

**My request**
I would like to move to Blackboard Learn's **official REST API integration (3LO / three-legged
OAuth)**. Could you register/approve my application on your Learn instance?
- I will provide the **Application ID (UUID)** issued by the Anthology Developer Portal; an admin
  registers it under System Admin > Integrations > REST API Integrations with **End User Access = Yes**.
- **Read-only, least-privilege** scope is sufficient (courses, contents, grades, announcements, calendar).
- Each student authorizes with their own UNIST account, so the app never accesses anyone else's data.

**Why**
- A school-approved, controllable official path → better security, policy compliance, reliability.
- Improved student experience. I'm happy to discuss limiting scope, users, or logging as needed.

If possible, please advise on the registration process, any additional information you need, or a
short meeting. I will gladly follow any security review or conditions you require.

Thank you,
[Name] / [Student ID] / [email·phone] / [GitHub URL]
