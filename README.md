# write-on-vibe-lab — 개인화 커리어·포트폴리오 AI 에이전트

LangChain + LangGraph + AWS Bedrock + PostgreSQL(`pgvector`) 기반의 **1인용 순환형(Closed-Loop) 커리어·포트폴리오 AI 에이전트**입니다.

## 핵심 기능 (7-Page 순환형 커리어 스튜디오)

1. **나의 신념 & 일상 회고 (`IdentityBeliefsPage`)**
   - 커리어 비전·핵심 신념·희망 직무·선호 문체 관리 (`career_identity` 벡터 자동 동기화)
   - 책·강의 구절·아티클·일상 생각 회고 저널(`belief_notes`) + AI 생각 심화 회고 & 신념·비전 정제
2. **포트폴리오 & STAR-L 마스터리 (`IdentityPortfolioPage`)**
   - **누적식 STAR-L 1,000 XP 마스터리 보드 (`rubric_v2.1`):** 대표 4개 프로젝트 선택 × 프로젝트당 최대 `250 XP` (상위 4개 경험 체감 합산 `100%·80%·50%·20%`, 5번째 이후 `0%`) + 5축 STAR-L 달성도 + 21개 Atomic 체크포인트 히트맵 & 약점 TOP 3 원클릭 채굴 연계
   - **조합형 멀티트랙 포트폴리오 워크스페이스:** 공통 코어 2개 + 5대 역할 트랙 팩 동적 조합, GitHub 딥 분석 SSE, 문서→프로젝트 자동 생성(명확한 섹션 네이밍 규칙 + 섹션 전환 시 편집·AI 제안 상태 유지, 무분별한 경험 자동 생성 차단), 개별 섹션 AI 업데이트 Diff, AI 가지치기, 프로젝트 회고 인터뷰(`KPT`/`4Ls`/`Post-Mortem`), Markdown/Recap 내보내기
   - 프로젝트 요약 또는 **GitHub PR·커밋 Diff**에서 `3. 경험 채굴`로 원클릭 직결
3. **★ 핵심 엔진: 경험 채굴 (`ExperienceMinerPage` · Agent ① Active Interviewer)**
   - **3가지 진입 경로:** ① 연결된 프로젝트 요약 자동 연동 채굴 ② **온디맨드 GitHub PR·Push 커밋 실제 코드 Diff** 기반 역질문 ③ **직접 STAR-L 경험 입력** (`POST /api/experiences`)
   - **21개 Atomic 체크포인트 3단계 엄격 하이브리드 평가 (`rubric_v2.1`):** LLM `0/1/2` 원문 근거 인용 판별 → Python Quote Grounding(`overlap ≥ 0.52`) · 12종 코드 하드 캡 · 엄격 부분배점 정수 합산 (`Spearman ρ = 0.9543`, `Fluff Trap 100%`, `Monotonicity 100%`)
   - **닫힌 피드백 루프 & 역반영:** 보수적 Question Critic-Refiner(`< 70점` 또는 린트 결함), 역질문별 `👍/👎 + 4종 사유 칩`, 완료 만족도(`1~5★`)·점수 체감(`박함/적절/후함`), 실시간 품질·캘리브레이션·21항목 문항 분석 대시보드, 경험 상세 모달 **인라인 수정·즉시 재채점**, **역질문 결과 → 프로젝트 섹션 다시 정리** (`sync-from-experience`)
4. **기업 리서치 (`CompanyInterestPage` · Agent ② Company-Identity Matcher)**
   - 목표 기업 4관점 멀티소스 웹 리서치 (`ddgs` + Google News RSS + 사용자 URL + `trafilatura` 본문 추출)
   - 채용공고(JD) × 기업 비전·동향 × 나의 신념 × 증명 프로젝트 **3각 매칭표** 자동 합성
5. **자소서 공방 & 보관함 (`CoverLetterStudioPage` · Agent ③ Critic-Refiner-Humanizer)**
   - **1단계 (`recommend`):** 기업 제공 문항 심층 해부(숨은 의도·필수 체크포인트·글자수 배분) + 등록된 프로젝트·STAR-L 중 최적 1~2개 추천 및 사용자 직접 선택
   - **2단계 (`generate`):** 선택 프로젝트·STAR-L 사실(PostgreSQL 직접 주입) × 기업 신념 × 나의 신념 3축 융합 초안 → 면접관 관점 비평·퇴고(최대 2회) → De-AI 문체 교정 & 코드 사후 검증 + **생성 자소서 보관함 자동 저장·수정·메모·버전 관리 (`cover_letters`)**
6. **지원 & 취준 회고 (`ApplicationRetroPage` · Agent ④ Mode B)**
   - 지원 전형·결과·피드백 누적 관리 + 포트폴리오 Gap 분석 + 단기/중기 보완 플랜 → 새 프로젝트 코파일럿 주제 원클릭 연계
7. **새 프로젝트 코파일럿 (`ProjectCopilotPage` · Agent ④ Mode A)**
   - **청사진 추천 (`propose-projects`):** 포트폴리오 약점 + 리서치 기업 동향 + 이전 프로젝트 회고 `Try` 학습 루프 + 실시간 웹 검색을 결합한 보완형 새 프로젝트 2~3종 제안
   - **설계 코파일럿 채팅 (`chat`):** LangGraph Agentic RAG ReAct (`AsyncPostgresSaver` 단기 기억 + `AsyncPostgresStore` 장기 기억 + Hybrid BM25/Vector RRF + MMR + 6종 전용 도구)

## 아키텍처 요약

- **Docker Self-Contained (3 Containers):** `frontend` (React/Vite/Tailwind + Nginx) + `backend` (FastAPI + LangChain + LangGraph SSE) + `db` (`pgvector/pgvector:pg16`, Named Volume `pgdata`)
- **AI 모델 (AWS Bedrock Only):** `ChatBedrockConverse` (`amazon.nova-lite-v1:0` Fast / `amazon.nova-pro-v1:0` Smart) + `BedrockEmbeddings` (`amazon.titan-embed-text-v2:0`, 1024차원), `boto3` 기본 자격 증명 체인(EC2 IAM Role) 사용
- **무료 웹 검색 & GitHub 연동:** `ddgs` + Google News RSS + `trafilatura` / `beautifulsoup4` + GitHub REST API v2022-11-28 (온디맨드 PR·Push 커밋 Diff)

## 문서 안내

- **[EXPERIENCE_MINING_ARCHITECTURE.md](./EXPERIENCE_MINING_ARCHITECTURE.md)** — **★ 핵심 엔진: 경험 채굴(Active Interviewer) · STAR-L 21지표 하이브리드(v2.1) · 1,000 XP · GitHub Diff · 캘리브레이션 실측 심층 설계서**
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
│   ├── eval/                     # 골든 평가셋 4종(RAG 15 / 루브릭 15 / 질문 10 / 요약 6) + 평가 러너 3종
│   ├── tests/                    # 단위 테스트 48건 (STAR-L v2.1 · GitHub Diff · RAG v2 · 루프 A/B · 가드레일)
│   └── app/
│       ├── rubrics/              # 버전 관리형 체크표 번들 (rubric_v2.0.json, rubric_v2.1.json)
│       ├── prompts/              # 외부 프롬프트 템플릿 15종 (<role>/<rules>/<output_format>) + loader.py
│       ├── core/                 # bedrock, database, chunker, vector_store, project_templates, star_rubric, question_critic, summary_verifier
│       ├── schemas/              # Pydantic 입출력 & Structured Output 스키마
│       ├── tools/                # web_search, document_parser, github_analyzer(PR/Commit Diff), portfolio_manager, copilot_tools
│       ├── graphs/               # interview / company / cover_letter / copilot / copilot_agent
│       ├── api/                  # FastAPI REST & SSE 라우터
│       └── seeds/                # 우수 자소서 레퍼런스 시드 로더
├── frontend/                     # React + Vite + Tailwind + Nginx Reverse Proxy
│   ├── Dockerfile
│   ├── nginx.conf                # SPA fallback + /api/ SSE 프록시
│   └── src/
│       ├── api/                  # client.js (REST & ReadableStream SSE 파서)
│       ├── components/           # Sidebar, PortfolioDiagnosisPanel(1,000 XP), ProjectWorkspaceView, StarMeter(21지표),
│       │                         # ExperienceDetailModal(수정·재채점), ExperienceProjectSyncModal, GitHubActivityPickerModal
│       └── pages/                # 7개 독립 커리어 스튜디오 페이지
├── scripts/                      # EC2 무손실 재배포 & E2E 영속성 검증 스크립트
├── docker-compose.yml
├── .env.example
├── .gitignore
├── EXPERIENCE_MINING_ARCHITECTURE.md
├── ARCHITECTURE.md
├── WORKFLOWS.md
├── DEPLOY_EC2.md
└── SECRETS.md
```
