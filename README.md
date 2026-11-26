# write-on-vibe-lab — 개인화 커리어·포트폴리오 AI 에이전트

LangChain + LangGraph + AWS Bedrock + PostgreSQL(`pgvector`) 기반의 **1인용 순환형(Closed-Loop) 커리어·포트폴리오 AI 에이전트**입니다.

## 핵심 기능 (7-Page 순환형 커리어 스튜디오)

1. **나의 신념 & 일상 회고 (`IdentityBeliefsPage`)**
   - 커리어 비전·핵심 신념·희망 직무·선호 문체 관리 (`career_identity` 벡터 자동 동기화)
   - 책·강의 구절·아티클·일상 생각 회고 저널(`belief_notes`) + AI 생각 심화 회고 & 신념·비전 정제
2. **포트폴리오 & 캐릭터 (`IdentityPortfolioPage`)**
   - **6축 포트폴리오 캐릭터 진단** (`KFLA × Google × Spencer Iceberg`: 내적 3축 × 외적 3축, `verified`/`partial`/`missing` 정직성 가드레일, 강점 50 : 약점 50, 접기/펼치기 지원)
   - **조합형 멀티트랙 포트폴리오 워크스페이스** (공통 코어 2개 + 5대 역할 트랙 팩 동적 조합, GitHub 딥 분석 SSE, 문서→프로젝트 자동 생성, **개별 섹션 전용** 파일·메모 AI 업데이트 Diff, AI 가지치기, Markdown/Recap 내보내기)
   - **선택형 STAR-L 온보딩 역질문** & **프로젝트 회고 인터뷰 (`KPT` / `4Ls` / `Post-Mortem`)** — 도출된 `Try` 개선 규칙을 다음 프로젝트 코파일럿으로 자동 인계(학습 루프)
3. **경험 채굴 (`ExperienceMinerPage` · Agent ① Active Interviewer)**
   - 거친 메모에서 **5축 STAR-L (Situation·Task·Action·Result·Learning)** 구조 추출
   - **DDI BARS 5단계 앵커 × Amazon Bar Raiser × Google XYZ** 객관 채점 (`S/A/B/C/D` 캘리브레이션 등급 + 관대화 방지 하드 캡)
   - **DDI Funnel Probing × Bar Raiser Drill-Down** 5종 기법 기반 역질문 루프 (`PostgresSaver` + `thread_id` 영속화, `[이 상태로 저장하기]` 즉시 탈출)
4. **기업 리서치 (`CompanyInterestPage` · Agent ② Company-Identity Matcher)**
   - 목표 기업 4관점 멀티소스 웹 리서치 (`ddgs` + Google News RSS + 사용자 URL + `trafilatura` 본문 추출)
   - 채용공고(JD) × 기업 비전·동향 × 나의 신념 × 증명 프로젝트 **3각 매칭표** 자동 합성
5. **자소서 공방 (`CoverLetterStudioPage` · Agent ③ Critic-Refiner-Humanizer)**
   - **1단계 (`recommend`):** 기업 제공 문항 심층 해부(숨은 의도·필수 체크포인트·글자수 배분) + 등록된 프로젝트·STAR-L 중 최적 1~2개 추천 및 사용자 직접 선택
   - **2단계 (`generate`):** 선택 프로젝트·STAR-L 사실(PostgreSQL 직접 주입) × 기업 신념 × 나의 신념 3축 융합 초안 → 면접관 관점 비평·퇴고(최대 2회) → De-AI 문체 교정 & Diff 리포트
6. **지원 & 취준 회고 (`ApplicationRetroPage` · Agent ④ Mode B)**
   - 지원 전형·결과·피드백 누적 관리 + 6축 포트폴리오 캐릭터 대비 Gap 분석 + 단기/중기 보완 플랜 → 새 프로젝트 코파일럿 주제 원클릭 연계
7. **새 프로젝트 코파일럿 (`ProjectCopilotPage` · Agent ④ Mode A)**
   - **청사진 추천 (`propose-projects`):** 캐릭터 약점·사각지대 + 리서치 기업 동향 + 이전 프로젝트 회고 `Try` 학습 루프 + 실시간 웹 검색을 결합한 보완형 새 프로젝트 2~3종 제안
   - **설계 코파일럿 채팅 (`chat`):** Corrective RAG (내부 컨텍스트 충분성 평가 → 필요 시 웹 검색 최대 1회 Fallback) 기반 아키텍처·실행 로드맵 코칭

## 아키텍처 요약

- **Docker Self-Contained (3 Containers):** `frontend` (React/Vite/Tailwind + Nginx) + `backend` (FastAPI + LangChain + LangGraph SSE) + `db` (`pgvector/pgvector:pg16`, Named Volume `pgdata`)
- **AI 모델 (AWS Bedrock Only):** `ChatBedrockConverse` (`amazon.nova-lite-v1:0` Fast / `amazon.nova-pro-v1:0` Smart) + `BedrockEmbeddings` (`amazon.titan-embed-text-v2:0`, 1024차원), `boto3` 기본 자격 증명 체인(EC2 IAM Role) 사용
- **무료 웹 검색:** `ddgs` + Google News RSS + `trafilatura` / `beautifulsoup4`

## 문서 안내

- **[EXPERIENCE_MINING_ARCHITECTURE.md](./EXPERIENCE_MINING_ARCHITECTURE.md)** — **★ 핵심 엔진: 경험 채굴(Active Interviewer) 작동 과정·LangGraph 아키텍처·STAR-L 채점 심층 설계서**
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 시스템 아키텍처 & 서비스 전체 LLM·LangChain·LangGraph 인벤토리
- [WORKFLOWS.md](./WORKFLOWS.md) — LangGraph AI 에이전트 워크플로우 & 평가 루브릭 상세 명세서
- [LANGCHAIN_LANGGRAPH_UPGRADE.md](./LANGCHAIN_LANGGRAPH_UPGRADE.md) — LangChain · LangGraph · RAG 고도화 설계 및 정량 평가 기록
- [QUALITY_LOOPS_PLAN.md](./QUALITY_LOOPS_PLAN.md) — 질문 · 프로젝트 정리/요약 2대 품질 상승 루프 설계서 및 실측 결과
- [DEPLOY_EC2.md](./DEPLOY_EC2.md) — AWS EC2 Docker 배포 & E2E/영속성 검증 매뉴얼
- [SECRETS.md](./SECRETS.md) — 비밀번호·패스워드·AWS 키 보안 관리 가이드 (필독)
- [ai.md](./ai.md) — 마스터 기획서 & Docker 아키텍처
- [agents_md.md](./agents_md.md) — 개발 에이전트 작업 지침서

## 빠른 시작 (로컬 환경)

> [!IMPORTANT]
> 실행 전 반드시 [SECRETS.md](./SECRETS.md)를 확인하세요. 실제 비밀번호, AWS 자격 증명, `*.local.json` 파일은 절대 커밋하지 않습니다.

```powershell
# 1. 환경변수 템플릿 복사 후 값 채우기
Copy-Item .env.example .env

# 2. Docker Compose 빌드 및 기동
docker compose up --build
```

## 프로젝트 구조

```text
write-on-vibe-lab/
├── .github/                      # PR / Issue 템플릿
├── backend/                      # FastAPI + LangChain + LangGraph + pgvector
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── tests/                    # 단위 테스트 (루브릭·템플릿·JSON 복구·격리 정책 등)
│   └── app/
│       ├── core/                 # bedrock.py, database.py, vector_store.py, project_templates.py, star_rubric.py
│       ├── schemas/              # Pydantic 입출력 & Structured Output 스키마
│       ├── tools/                # web_search.py, document_parser.py, github_analyzer.py, portfolio_manager.py
│       ├── graphs/               # interview / company / cover_letter / copilot
│       ├── api/                  # FastAPI REST & SSE 라우터 (profile, beliefs, projects, experiences, agents 등)
│       └── seeds/                # 우수 자소서 레퍼런스 시드 로더
├── frontend/                     # React + Vite + Tailwind + Nginx Reverse Proxy
│   ├── Dockerfile
│   ├── nginx.conf                # SPA fallback + /api/ SSE 프록시
│   └── src/
│       ├── api/                  # client.js (REST & ReadableStream SSE 파서)
│       ├── components/           # Sidebar, RadarChart, PortfolioDiagnosisPanel, ProjectWorkspaceView, StarMeter 등
│       └── pages/                # 7개 독립 커리어 스튜디오 페이지
├── scripts/                      # EC2 무손실 재배포 & E2E 영속성 검증 스크립트
├── docker-compose.yml
├── .env.example
├── .gitignore
├── ARCHITECTURE.md
├── WORKFLOWS.md
├── DEPLOY_EC2.md
└── SECRETS.md
```
