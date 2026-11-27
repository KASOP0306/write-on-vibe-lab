# write-on-vibe-lab — 개인화 커리어·포트폴리오 AI 에이전트

LangChain + LangGraph + AWS Bedrock + PostgreSQL(`pgvector`) 기반의 **1인용 순환형(Closed-Loop) 커리어·포트폴리오 AI 에이전트**입니다.

## 핵심 기능 (7-Page 순환형 커리어 스튜디오)

1. **1. 신념 (`IdentityBeliefsPage`)**
   - **인문학적 · 사회적 커리어 신념 카드 (`belief_pillars`, 단일 진실 원천):** AI 시대 인간·사회적 가치 중심 4대 카테고리(`사람·인문적 가치`, `사회적 임팩트`, `커리어 소명`, `기술과 인간의 조화`)로 신념을 구조화하고, 저장·수정·삭제 시 `user_profile.core_beliefs` 및 `career_identity` 벡터를 자동 동기화
   - **AI 신념 발굴 & 다듬기:** 보유 포트폴리오·STAR-L 경험에서 커리어 소명 카드를 역추출(`discover`)하거나 기존 신념 문장을 날카롭게 정제(`sharpen`), 증명 완료(`verified`) / 증명 필요(`needs_proof`) 상태 추적
   - **일상 회고 저널 (`belief_notes`):** 책·강의·아티클·일상 메모 기록 + AI 생각 심화 회고
2. **2. 포트폴리오 (`IdentityPortfolioPage`)**
   - **누적식 STAR-L 1,000 XP 마스터리 보드 (`rubric_v2.1`):** 대표 4개 프로젝트 선택 × 프로젝트당 최대 `250 XP` (상위 4개 경험 체감 합산 `100%·80%·50%·20%`, 5번째 이후 `0%`) + 5축 STAR-L 달성도 + 21개 Atomic 체크포인트 히트맵 & 약점 TOP 3 원클릭 채굴 연계
   - **GitHub 계정 연동 & 내 레포 브라우저 (`GitHubAccountBrowser`):** GitHub PAT 암호화 저장(`SHA256-CTR + HMAC-SHA256`) → Public/Private 전체 레포 탐색, **`미연결 레포 N개` 자동 감지**, 원클릭 분석 불러오기 및 모든 GitHub 분석·PR/커밋 Diff API의 저장 토큰 자동 사용
   - **조합형 멀티트랙 포트폴리오 워크스페이스:** 공통 코어 2개 + 5대 역할 트랙 팩 동적 조합, GitHub 딥 분석 SSE, 문서→프로젝트 자동 생성(명확한 섹션 네이밍 규칙 + 섹션 전환 시 편집·AI 제안 상태 유지, 무분별한 경험 자동 생성 차단), 개별 섹션 AI 업데이트 Diff, AI 가지치기, 프로젝트 회고 인터뷰(`KPT`/`4Ls`/`Post-Mortem`), Markdown/Recap 내보내기
3. **3. 경험 채굴 (`ExperienceMinerPage` · Agent ① Active Interviewer v3.0)**
   - **대화형 멀티턴 채팅 & 의도 라우터:** 사용자 발화를 `answer`(경험 답변·재채점) / `replace_question`(질문 전체 또는 단일 슬롯 즉시 교체) / `ask_coach`(1:1 코치 상담) / `save`(즉시 저장) 4갈래로 분기, 대화 중 선호 조건(`interview_preferences`) 누적 영속화 및 `GET /interview/history/{thread_id}` 복원
   - **온디맨드 GitHub PR·Push 커밋 Diff 1순위 앵커링 (`code_anchor`):** 선택한 PR·커밋의 실제 변경 파일·함수·코드 패치를 영속 `focus_context`로 유지하며 코드 변경점 기반 역질문 수행 (저장된 GitHub 토큰 자동 연동)
   - **21개 Atomic 체크포인트 3단계 엄격 하이브리드 평가 (`rubric_v2.1`):** LLM `0/1/2` 원문 근거 인용 판별 → Python Quote Grounding(`overlap ≥ 0.52`) · 12종 코드 하드 캡 · 엄격 부분배점 정수 합산 (`Spearman ρ = 0.9543`, `Fluff Trap 100%`, `Monotonicity 100%`)
   - **닫힌 피드백 루프 & 역반영:** 보수적 Question Critic-Refiner, 역질문별 `👍/👎 + 4종 사유 칩`, 완료 만족도(`1~5★`)·점수 체감(`박함/적절/후함`), 품질·캘리브레이션·21항목 문항 분석 대시보드, 경험 상세 모달 인라인 수정·즉시 재채점, **역질문 결과 → 프로젝트 섹션 다시 정리** (`sync-from-experience`)
4. **4. 기업 리서치 (`CompanyInterestPage` · Agent ② Company-Identity Matcher)**
   - 목표 기업 4관점 멀티소스 웹 리서치 (`ddgs` + Google News RSS + 사용자 URL + `trafilatura` 본문 추출)
   - 채용공고(JD) × 기업 비전·동향 × **인문·사회적 커리어 신념 카드(`belief_pillars`)** × 증명 프로젝트 **3각 매칭표** 자동 합성
5. **5. 자소서 공방 (`CoverLetterStudioPage` · Agent ③ Critic-Refiner-Humanizer)**
   - **1단계 (`recommend`):** 기업 제공 문항 심층 해부(숨은 의도·필수 체크포인트·글자수 배분) + 등록 프로젝트·STAR-L 및 **핵심 신념 카드(`belief_pillars`)** 최적 조합 추천 및 사용자 직접 선택
   - **2단계 (`generate`):** 선택 프로젝트·STAR-L 사실(PostgreSQL 직접 주입) × **선택 신념 카드(`belief_pillars` 1급 주입)** × 기업 비전 3축 융합 초안 → 면접관 관점 비평(`[신념 연결]` 항목 포함)·퇴고(최대 2회) → De-AI 문체 교정 & 코드 사후 검증 + **자소서 보관함 자동 저장(`used_beliefs` 포함)·수정·메모·버전 관리 (`cover_letters`)**
6. **6. 지원 회고 (`ApplicationRetroPage` · Agent ④ Mode B)**
   - 지원 전형·결과·피드백 누적 관리 + STAR-L 마스터리 기반 Gap 분석 + 단기/중기 보완 플랜 → 코파일럿 주제 원클릭 연계
7. **7. 프로젝트 코파일럿 (`ProjectCopilotPage` · Agent ④ Mode A)**
   - **실시간 STAR-L 1,000 XP · 21지표 취약 히트맵 · 미증명 신념 카드(`needs_proof`) 연동:** 구 6축 캐릭터를 완전 대체해 실제 STAR-L 취약 체크포인트와 미증명 신념 칩을 클릭 포커스로 지정
   - **청사진 추천 & GitHub 새 레포 자동 생성 (`propose-projects` + `POST /api/github/repos`):** 포트폴리오 약점 + 미증명 신념 + 리서치 기업 동향 + 회고 `Try` 학습 루프 + 실시간 웹 검색 기반 청사진 제안. 초안 생성 시 **`GitHub 새 레포 자동 생성 · 연결` (`Private/Public`)** 옵션을 켜면 GitHub에 새 레포를 생성하고 초기 `README.md`를 커밋한 뒤 `repo_url`에 자동 연결
   - **설계 코파일럿 채팅 (`chat`):** LangGraph Agentic RAG ReAct (`AsyncPostgresSaver` 단기 기억 + `AsyncPostgresStore` 장기 기억 + Hybrid BM25/Vector RRF + MMR + 6종 전용 도구)

## 아키텍처 요약

- **Docker Self-Contained (3 Containers):** `frontend` (React/Vite/Tailwind + Nginx) + `backend` (FastAPI + LangChain + LangGraph SSE) + `db` (`pgvector/pgvector:pg16`, Named Volume `pgdata`)
- **AI 모델 (AWS Bedrock Only):** `ChatBedrockConverse` (`amazon.nova-lite-v1:0` Fast / `amazon.nova-pro-v1:0` Smart) + `BedrockEmbeddings` (`amazon.titan-embed-text-v2:0`, 1024차원), `boto3` 기본 자격 증명 체인(EC2 IAM Role) 사용
- **무료 웹 검색 & GitHub 통합 연동:** `ddgs` + Google News RSS + `trafilatura` / `beautifulsoup4` + GitHub REST API v2022-11-28 (암호화 PAT 연동 · 내 레포 브라우저 · 온디맨드 PR·Push 커밋 Diff · 새 레포 자동 생성)

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
│   ├── tests/                    # 단위 테스트 60건 (STAR-L v2.1 · 대화형 인터뷰 v3.0 · 신념·코파일럿 · GitHub 통합 · RAG v2 · 루프 A/B)
│   └── app/
│       ├── rubrics/              # 버전 관리형 체크표 번들 (rubric_v2.0.json, rubric_v2.1.json)
│       ├── prompts/              # 외부 프롬프트 템플릿 17종 (<role>/<rules>/<output_format>) + loader.py
│       ├── core/                 # bedrock, database, token_crypto, chunker, vector_store, project_templates, star_rubric, question_critic, summary_verifier
│       ├── schemas/              # Pydantic 입출력 & Structured Output 스키마
│       ├── tools/                # web_search, document_parser, github_analyzer(계정·레포·PR/Commit Diff·생성), portfolio_manager, copilot_tools
│       ├── graphs/               # interview / company / cover_letter / copilot / copilot_agent
│       ├── api/                  # FastAPI REST & SSE 라우터 (beliefs, github, projects, experiences, agents 등)
│       └── seeds/                # 우수 자소서 레퍼런스 시드 로더
├── frontend/                     # React + Vite + Tailwind + Nginx Reverse Proxy
│   ├── Dockerfile
│   ├── nginx.conf                # SPA fallback + /api/ SSE 프록시
│   └── src/
│       ├── api/                  # client.js (REST & ReadableStream SSE 파서)
│       ├── components/           # Sidebar, PortfolioDiagnosisPanel(1,000 XP), GitHubAccountBrowser, ProjectWorkspaceView, StarMeter(21지표),
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
