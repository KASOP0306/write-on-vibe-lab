# write-on-vibe-lab — 개인화 커리어·포트폴리오 AI 에이전트

LangChain + LangGraph + AWS Bedrock + pgvector 기반의 **1인용 순환형(Closed-Loop) 커리어·포트폴리오 AI 에이전트** MVP 저장소입니다.

## 핵심 기능 (4대 LangGraph 에이전트)

1. **경험 채굴 (`Active Interviewer`)** — 메모에서 STAR 빈틈을 탐지하고 연속 역질문으로 포트폴리오 경험을 구조화
2. **목표 기업 리서치 & 신념 3각 매칭 (`Company-Identity Matcher`)** — 기업 이념·비전 × 나의 신념 × 프로젝트 경험 연결
3. **자소서 공방 (`Critic-Refiner-Humanizer`)** — Multi-Source RAG 초안 → 면접관 관점 비평·퇴고(최대 2회) → De-AI 문체 교정
4. **프로젝트 코파일럿 & 취준 회고 (`Router + Corrective RAG`)** — 과거 경험·관심사 기반 조언 및 지원 결과 Gap 분석·보완 플랜 도출

## 아키텍처 요약

- **Docker Self-Contained (3 Containers):** `frontend` (React/Vite/Tailwind + Nginx) + `backend` (FastAPI + LangGraph SSE) + `db` (`pgvector/pgvector:pg16`, Named Volume `pgdata`)
- **AI 모델 (AWS Bedrock Only):** `ChatBedrockConverse` (Fast/Smart Tier 분리) + `BedrockEmbeddings` (1024차원), `boto3` 기본 자격 증명 체인(EC2 IAM Role) 사용
- **무료 웹 검색:** `duckduckgo-search` + `beautifulsoup4`

## 문서 안내

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 시스템 아키텍처 설계서 (인프라·DB ERD·LangGraph·SSE·보안 경계)
- [DEPLOY_EC2.md](./DEPLOY_EC2.md) — AWS EC2 Docker 배포 & Day 4 E2E/영속성 검증 매뉴얼
- [ai.md](./ai.md) — 마스터 기획서 & Docker 아키텍처
- [agents_md.md](./agents_md.md) — 개발 에이전트 작업 지침서
- [SECRETS.md](./SECRETS.md) — 비밀번호·패스워드·AWS 키 보안 관리 가이드 (필독)

## 빠른 시작 (로컬 환경)

> [!IMPORTANT]
> 실행 전 반드시 [SECRETS.md](./SECRETS.md)를 확인하세요. 실제 비밀번호와 AWS 자격 증명은 절대 커밋하지 않습니다.

```powershell
# 1. 환경변수 템플릿 복사 후 값 채우기
Copy-Item .env.example .env

# 2. Docker Compose 빌드 및 기동
docker compose up --build
```

## 프로젝트 구조

```text
write-on-vibe-lab/
├── .github/                 # PR / Issue 템플릿
├── backend/                 # FastAPI + LangChain + LangGraph + pgvector
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── core/            # Bedrock 팩토리, DB 초기화, doc_type 격리 VectorStore
│       ├── schemas/         # Pydantic 입출력 & Structured Output 스키마
│       ├── tools/           # DuckDuckGo + BS4 웹 검색 도구
│       ├── graphs/          # 4대 LangGraph 에이전트 워크플로우
│       ├── api/             # FastAPI REST & SSE 라우터
│       └── seeds/           # 우수 자소서 레퍼런스 시드 데이터
├── frontend/                # React + Vite + Tailwind + Nginx Reverse Proxy
│   ├── Dockerfile
│   ├── nginx.conf           # SPA fallback + /api/ SSE 프록시
│   └── src/
│       ├── api/             # REST & SSE 스트림 파서
│       ├── components/      # 공용 UI 컴포넌트
│       └── pages/           # 5개 메인 화면
├── docker-compose.yml
├── .env.example
├── .gitignore
├── SECRETS.md
├── ai.md
└── agents_md.md
```
