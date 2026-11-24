# AGENTS.md — 개발 에이전트 작업 지침서

이 문서는 **개인화 커리어·포트폴리오 AI 에이전트** MVP를 일관된 아키텍처로 구현하기 위한 코딩 에이전트 전용 규칙서입니다. 모든 코드 생성·수정 시 아래 스펙과 제약을 엄격히 준수하세요.

---

## 1. 프로젝트 범위 및 절대 가드레일 (Scope Guardrails)

* **목표:** LangChain + LangGraph + AWS Bedrock 기반의 1인용 커리어 에이전트 웹 서비스 MVP.
* **인프라 원칙 (Docker Self-Contained):**
  * EC2 인스턴스 1대에 `docker-compose.yml`로 **`frontend` + `backend` + `db(pgvector)`** 3개 컨테이너만 실행한다.
  * 기존 AWS RDS나 S3 연동 코드를 MVP 필수 경로에 넣지 않는다. DB 영속성은 Docker Named Volume(`pgdata`)으로 보장한다.
* **AI 모델 원칙 (AWS Bedrock Only):**
  * OpenAI, Anthropic Direct API, Tavily 등 유료 외부 API 키를 요구하지 않는다.
  * 모든 LLM은 `langchain_aws.ChatBedrockConverse`, 모든 임베딩은 `langchain_aws.BedrockEmbeddings`를 사용한다.
  * 웹 검색은 무료 `duckduckgo-search` + `beautifulsoup4`로 구현한다.
* **프론트엔드 경량화 원칙:**
  * 로그인/회원가입/JWT 인증을 구현하지 않는다(1인 개인용).
  * Redux, Zustand, React Query 등 무거운 상태 라이브러리를 도입하지 않는다. 기본 React Hook(`useState`, `useEffect`)과 `fetch` 기반 SSE 파서만 사용한다.

---

## 2. 기술 스택 및 표준 디렉토리 구조

### 2.1 핵심 패키지
* **Backend (Python 3.11+):** `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `sqlalchemy[asyncio]`, `psycopg[binary]`, `pgvector`, `langchain`, `langgraph`, `langgraph-checkpoint-postgres`, `langchain-aws`, `boto3`, `duckduckgo-search`, `beautifulsoup4`, `httpx`
* **Frontend (Node 20+):** `react`, `vite`, `tailwindcss`, `lucide-react`, `react-markdown`
* **Database:** Docker Image `pgvector/pgvector:pg16`

### 2.2 모노레포 폴더 구조
```text
career-agent/
├── docker-compose.yml
├── .env.example
├── project_plan.md
├── AGENTS.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                  # FastAPI 앱, CORS, 라우터 등록, lifespan(DB 초기화)
│   │   ├── config.py                # pydantic-settings 환경변수 관리
│   │   ├── core/
│   │   │   ├── bedrock.py           # Fast/Smart LLM & Embeddings 팩토리
│   │   │   ├── database.py          # DB 연결 풀, pgvector 초기화, 스키마 DDL
│   │   │   └── vector_store.py      # doc_type 필터 강제 RAG 저장/검색 래퍼
│   │   ├── schemas/                 # Pydantic 입출력 & Structured Output 스키마
│   │   ├── tools/
│   │   │   └── web_search.py        # DuckDuckGo 검색 + 본문 텍스트 추출 Tool
│   │   ├── graphs/
│   │   │   ├── interview_graph.py   # 워크플로우 ①: 경험 채굴 & 연속 역질문 루프
│   │   │   ├── company_graph.py     # 워크플로우 ②: 기업 리서치 & 신념 3각 매칭
│   │   │   ├── cover_letter_graph.py# 워크플로우 ③: 자소서 비평·퇴고·De-AI 루프
│   │   │   └── copilot_graph.py     # 워크플로우 ④: 프로젝트 코파일럿 & 취준 회고
│   │   ├── api/                     # FastAPI 라우터 (profile, projects, agents, applications)
│   │   └── seeds/
│   │       └── jasoseo_samples.json # 직무/문항 유형별 우수 자소서 샘플 15건
└── frontend/
    ├── Dockerfile                   # Multi-stage: Node build -> Nginx serve
    ├── nginx.conf                   # SPA fallback + /api/ reverse proxy (SSE buffering off)
    ├── package.json
    └── src/
        ├── api/client.js            # REST fetch & SSE 스트림 파서 유틸
        ├── components/              # Sidebar, StepIndicator, StarMeter 등 공용 컴포넌트
        └── pages/
            ├── IdentityPortfolioPage.jsx
            ├── ExperienceMinerPage.jsx
            ├── CompanyInterestPage.jsx
            ├── CoverLetterStudioPage.jsx
            └── CopilotRetroPage.jsx
```

---

## 3. AWS Bedrock & 환경변수 규칙

1. **자격 증명:** 코드에 AWS Access Key를 절대 하드코딩하지 않는다. `boto3` 기본 자격 증명 체인(EC2에서는 IAM Role 자동 사용, 로컬에서는 `~/.aws` 또는 환경변수)에 위임한다.
2. **모델 티어 분리 (`backend/app/config.py`):**
   * `AWS_REGION` (기본값 `us-east-1` 또는 Bedrock 활성화 리전)
   * `BEDROCK_FAST_MODEL_ID` (예: `amazon.nova-lite-v1:0` — 라우팅, STAR 추출, 완성도 평가, 관련성 평가)
   * `BEDROCK_SMART_MODEL_ID` (예: `us.anthropic.claude-3-7-sonnet-20250219-v1:0` 또는 `amazon.nova-pro-v1:0` — 기업 매칭, 자소서 초안/비평/퇴고, De-AI, 회고 분석)
   * `BEDROCK_EMBED_MODEL_ID` (예: `cohere.embed-multilingual-v3` 또는 `amazon.titan-embed-text-v2:0`)
   * `EMBEDDING_DIM` (기본값 `1024`)
3. **Structured Output 안정성:** `llm.with_structured_output(PydanticModel)`을 사용하되, 모델별 JSON 파싱 실패 대비 예외 처리 및 재시도(최대 1회)를 포함한다.

---

## 4. 데이터베이스 & RAG 격리 규칙 (CRITICAL)

* `vector_documents` 테이블 조회 함수(`vector_store.py`)는 **`doc_types: list[str]` 파라미터를 필수 인자**로 강제한다. 필터 없는 전체 벡터 검색을 금지한다.
* 허용 `doc_type` 값(Enum 고정):
  1. `experience` (내 실제 경험 팩트)
  2. `career_identity` (내 신념·꿈·비전)
  3. `company_research` (목표 기업 이념·비전·동향)
  4. `interest_clip` (관심 분야 외부 스크랩 지식)
  5. `jasoseo_sample` (우수 자소서 레퍼런스)
* **자소서 환각 방지 규칙:** `cover_letter_graph.py`의 프롬프트에 다음 제약을 반드시 명시한다:
  > "`jasoseo_sample`은 문단 전개 구조와 설득 논리만 참고한다. 샘플 속 경험·수치·기업명을 지원자의 사실처럼 차용하는 것을 엄격히 금지하며, 모든 사실 근거는 `experience`에서만 가져온다."
* `user_profile`이나 `experiences`가 수정/저장될 때마다 `vector_documents`의 해당 `ref_id` 임베딩을 자동 업서트(Upsert)해 정형 DB와 벡터 DB 간 정합성을 유지한다.

---

## 5. LangGraph 구현 & SSE 스트리밍 규약

### 5.1 루프 안전장치 (Guardrails)
* **워크플로우 ① (역질문 루프):** `PostgresSaver` Checkpointer + `thread_id`로 상태를 유지한다. 유저가 `force_save=true`를 보내면 완성도 점수와 무관하게 즉시 저장 노드로 라우팅해 탈출할 수 있어야 한다.
* **워크플로우 ③ (비평·퇴고 루프):** `revision_count`가 `2`에 도달하거나 `critic_score >= 85`이면 무조건 `de_ai_humanizer` 노드로 넘어간다. (무한 루프 금지)
* **워크플로우 ④ (Corrective RAG):** 웹 검색 Fallback은 요청당 최대 1회로 제한한다.

### 5.2 De-AI Humanizer 필수 체크리스트
`de_ai_humanizer` 노드는 최종본을 다듬을 때 아래를 검사·교정하고, 무엇을 바꿨는지 `humanizer_changes: list[str]`로 반환한다.
* 상투적 AI 표현 제거 (`"~을 통해 한 단계 성장"`, `"귀사의 무궁한 발전"`, `"혁신적인 시너지"`, `"단순한 ~을 넘어"`, `"결론적으로"`)
* 과도한 추상 명사/수식어 축소 → 실제 기술명, 수치, 행동 동사 중심 서술
* 문장 길이 리듬 다양화 및 `user_profile.preferred_tone` 반영

### 5.3 공통 SSE(Server-Sent Events) 포맷
모든 에이전트 실행 API는 `text/event-stream`으로 아래 JSON 스키마를 전송한다.
```json
data: {"event": "node_start", "node": "critic", "message": "면접관 관점에서 초안을 평가하는 중..."}

data: {"event": "node_end", "node": "critic", "data": {"score": 78, "feedback": "..."}}

data: {"event": "interrupt", "thread_id": "exp-123", "data": {"questions": ["..."], "completeness_score": 65}}

data: {"event": "done", "data": {"final_text": "...", "diff_summary": ["..."]}}

data: {"event": "error", "message": "오류 설명"}
```

---

## 6. API 엔드포인트 & Nginx 프록시 규약

### 6.1 주요 API 목록
* **Profile / Interests / Projects:**
  * `GET/PUT /api/profile` — 신념·비전·선호 문체 조회/저장 (벡터 업서트 포함)
  * `GET/POST/DELETE /api/interests` — 관심 분야 키워드 CRUD
  * `GET/POST/PUT/DELETE /api/projects` — 프로젝트 CRUD
  * `POST /api/projects/{id}/recap` — 프로젝트 소속 경험 기반 포트폴리오 Markdown 리캡 생성
* **Agents (SSE):**
  * `POST /api/agents/interview/start` & `POST /api/agents/interview/reply` — 경험 채굴 역질문 시작/답변/강제저장
  * `POST /api/agents/company/research` — 목표 기업 리서치 & 신념 3각 매칭 (저장 포함)
  * `POST /api/agents/interests/search` & `POST /api/agents/interests/clip` — 관심사 검색 및 선택 클립 저장
  * `POST /api/agents/cover-letter/generate` — 자소서 생성·비평·퇴고·De-AI 실행
  * `POST /api/agents/copilot/chat` — 과거 경험 + 관심사 + Corrective RAG 채팅
  * `POST /api/agents/applications/retrospect` — 취준 결과 저장 + Gap 분석 + 보완 액션 플랜 도출

### 6.2 Docker & Nginx 필수 설정
* `frontend/nginx.conf`의 `/api/` location 블록에는 SSE 실시간 전송을 위해 아래 3줄을 반드시 포함한다:
  ```nginx
  proxy_http_version 1.1;
  proxy_set_header Connection "";
  proxy_buffering off;
  proxy_read_timeout 300s;
  ```
* `docker-compose.yml`의 `db` 서비스는 `healthcheck`(`pg_isready`)를 정의하고, `backend`는 `depends_on: db: condition: service_healthy`로 기동 순서를 보장한다.
* 4대 에이전트 상세 노드 구조 및 조건부 분기 흐름은 [WORKFLOWS.md](./WORKFLOWS.md)를 참조한다.
