# EXPERIENCE_MINING_ARCHITECTURE.md — 핵심 엔진: 경험 채굴 (Active Interviewer) 심층 아키텍처

> **우리 프로젝트의 심장(Core Engine):**  
> 모든 AI 자소서·포트폴리오 도구의 진짜 병목은 "글을 못 써서"가 아니라, **지원자가 자신의 모호한 경험 메모에서 면접관이 검증하려는 핵심 의사결정·기여도·정량 근거를 스스로 끌어내지 못하는 것(Garbage In, Garbage Out)**입니다.  
> `write-on-vibe-lab`의 핵심 엔진인 **경험 채굴 (`Active Interviewer`)**은 거친 메모 한 줄을 **Stateful LangGraph Human-in-the-Loop(HITL) 인터뷰 루프**로 파고들어, 객관적으로 검증된 **5축 STAR-L 1급 데이터**로 정련한 뒤 서비스 전체(캐릭터 진단·기업 매칭·자소서·코파일럿)에 공급합니다.

---

## 1. 전체 시스템에서 '경험 채굴'의 위치 (Hub-and-Spoke)

```mermaid
flowchart LR
    RAW["거친 경험 메모\n('Redis 붙여서 빨라졌어요')"] --> CORE["★ 핵심 엔진: 경험 채굴\n(Active Interviewer · LangGraph HITL)\n5축 STAR-L 추출 · BARS 채점 · 역질문 루프"]
    CORE -->|"정형 DB 저장"| EXP[("experiences 테이블\n5축 STAR-L + star_scores")]
    CORE -->|"효용 로그"| QLOG[("question_feedback_logs\n기법·축별 ΔSTAR-L 추적")]
    CORE -->|"Parent/Child 청킹"| VDB[("pgvector HNSW DB\ndoc_type='experience' 격리")]

    EXP --> CHAR["2. 6축 포트폴리오 캐릭터 진단\n(내적3×외적3 · 강점50:약점50)"]
    VDB --> COMP["4. 기업 리서치 3각 매칭\n(기업 비전 × 신념 × 증명 경험)"]
    VDB --> CL["5. 자소서 공방 v2\n(유일한 1급 사실 근거 · 환각 차단)"]
    VDB --> COP["7. 새 프로젝트 코파일럿\n(Agentic RAG Hybrid+MMR 검색)"]
```

- **왜 핵심인가?** 경험 채굴에서 확보된 **사실 밀도 높은 STAR-L 1건**이 아래 4개 다운스트림 AI 워크플로우의 품질 상한선을 결정합니다.

---

## 2. End-to-End 작동 과정 (실시간 SSE & 멀티턴 체크포인터 시퀀스)

사용자가 메모를 입력하고 역질문에 답해 저장하기까지의 전체 실행 흐름입니다.

```mermaid
sequenceDiagram
    actor User as 지원자 (Browser)
    participant UI as ExperienceMinerPage.jsx
    participant Nginx as Nginx (/api/ SSE\nproxy_buffering off)
    participant API as FastAPI (agents.py)
    participant Graph as LangGraph\n(interview_graph.py)
    participant PG as PostgreSQL\n(checkpoints / experiences /\nquestion_feedback_logs / pgvector)
    participant BR as AWS Bedrock\n(Nova Lite + Titan Embed v2)

    Note over User,BR: [1턴] 거친 메모 입력 → 분석 → 역질문 대기 (Interrupt)
    User->>UI: 거친 메모 입력 & [채굴 시작]
    UI->>Nginx: POST /api/agents/interview/start (SSE)
    Nginx->>API: Stream Proxy
    API->>Graph: astream(input_state, thread_id="exp-xxxx", recursion_limit=12)
    Graph->>BR: extract_star (interview_extract.txt, Structured Output)
    BR-->>Graph: 5축 STAR-L + 정량 지표 (날조 엄금)
    Graph-->>UI: SSE node_end("extract_star") → 실시간 STAR-L 카드 갱신
    Graph->>BR: grade_gaps (DDI BARS 5축 채점)
    Graph->>Graph: 코드 레벨 관대화 방지 하드 캡 적용 (S~D 등급)
    Graph-->>UI: SSE node_end("grade_gaps") → 5축 레이더 & 점수 게이지 갱신
    alt 완성도 < 80점 AND force_save=false
        Graph->>BR: generate_questions (DDI Funnel × Bar Raiser 역질문 2개)
        Graph->>BR: 루프 A: 코드 린터 + Question Critic-Refiner (최대 2회)
        Graph->>PG: AsyncPostgresSaver 체크포인트 저장 (thread_id)
        Graph-->>UI: SSE interrupt(thread_id, questions, structured_questions)
        UI-->>User: 프로빙 기법 배지 + 면접관 의도 + 역질문 2개 표시
    end

    Note over User,BR: [2턴+] 사용자 답변 → 체크포인트 복원 → ΔSTAR-L 기록 → 재채점 또는 저장
    User->>UI: 역질문 답변 입력 (또는 [이 상태로 저장하기])
    UI->>API: POST /api/agents/interview/reply (thread_id, user_reply, force_save)
    API->>Graph: AsyncPostgresSaver에서 thread_id 상태 자동 복원
    Graph->>Graph: prepare_turn (직전 점수 스냅샷 · 답변 병합 · 단축 경로 판별)
    Graph->>BR: extract_star (누적 Q&A 통합 재추출)
    Graph->>BR: grade_gaps (5축 재채점)
    Graph->>PG: question_feedback_logs에 ΔSTAR-L(답변후 - 답변전) 기록
    alt score >= 80 & is_sufficient OR force_save=true
        Graph->>PG: experiences 테이블 영속 저장
        Graph->>BR: Titan Embed v2 (1024차원) 임베딩
        Graph->>PG: vector_documents 업서트 (doc_type='experience', HNSW)
        Graph-->>UI: SSE done(experience_id, star, star_scores, vector_synced)
    end
```

---

## 3. LangGraph 내부 상태 머신 아키텍처 (`backend/app/graphs/interview_graph.py`)

### 3.1 노드 · 조건부 엣지 그래프

```mermaid
flowchart TD
    S((START)) --> P["1. prepare_turn\n· latest_reply를 qa_history에 병합\n· 직전 점수/질문 스냅샷(ΔSTAR-L 계산용)\n· force_save 단축 경로 여부 판단"]

    P -->|"skip_extraction=true\n(force_save=true & 기존 STAR 존재 &\n추가 답변 없음)"| SAVE
    P -->|"일반 실행"| EXT["2. extract_star\n· Fast LLM (Nova Lite, temp=0.1)\n· prompts/interview_extract.txt\n· 최근 6턴 원문 + 오래된 턴 압축\n· 미언급 수치/성과 날조 엄금"]

    EXT --> GRADE["3. grade_gaps\n· 5축 STAR-L BARS 객관 채점\n· 코드 레벨 관대화 방지 하드 캡\n· 직전 턴 존재 시 ΔSTAR-L DB 기록"]

    GRADE -->|"force_save=true OR\n(score >= 80 AND is_sufficient)"| SAVE["5. save_experience\n· experiences 테이블 저장\n· Titan Embed v2 선행 임베딩\n· experience 청킹 벡터 업서트"]
    GRADE -->|"빈틈 존재 (< 80점)"| Q["4. generate_questions\n· 가장 약한 축 2개 자동 선별\n· DDI Funnel × Bar Raiser 5기법 매칭\n· 루프 A: 코드 린터 + Critic-Refiner(max 2)"]

    Q --> INT(("END (SSE interrupt)\nAsyncPostgresSaver에\nthread_id 상태 영속화"))
    SAVE --> DONE(("END (SSE done)"))
```

### 3.2 `InterviewState` 핵심 필드 설계

| 필드 | 역할 | 설계 포인트 |
| :--- | :--- | :--- |
| `raw_notes`, `qa_history`, `latest_reply` | 초기 메모 및 멀티턴 질의응답 누적 | 6턴 초과 시 오래된 턴은 핵심 180자 요약으로 자동 압축해 토큰 폭증 방지(`_build_context_text`) |
| `star`, `completeness_score`, `star_scores` | 5축 STAR-L 본문 및 축별 BARS 점수·등급 | 매 턴 전체 누적 맥락을 재통합해 S·T·A·R·L이 점진적으로 고밀도화됨 |
| `prev_completeness_score`, `prev_structured_questions` | 직전 턴 스냅샷 | 답변 직후 `ΔSTAR-L = new_score - prev_score`를 정확히 산출해 `question_feedback_logs`에 저장 |
| `force_save`, `skip_extraction` | 사용자 즉시 탈출 제어 | 사용자가 `[이 상태로 저장하기]` 클릭 시 추가 답변이 없으면 LLM 호출 없이 즉시 `save_experience`로 단축 라우팅 |
| `question_critic_score`, `question_critic_revisions` | 루프 A 품질 메타 | 질문 비평 점수 및 리라이트 횟수(최대 2회) 추적 |

### 3.3 운영 안전장치 (Guardrails)
1. **체크포인터 영속화 (`AsyncPostgresSaver`):** 서버가 재시작되거나 네트워크가 잠시 끊겨도 `thread_id`로 직전 노드 상태에서 대화를 이어갈 수 있습니다.
2. **실행 상한 (`recursion_limit=12`):** 그래프 레벨 무한 순환을 원천 차단합니다.
3. **트랜잭션 격리 업서트 (`try_upsert_document`):** `save_experience`에서 Bedrock 임베딩 호출을 DB 벡터 쓰기보다 먼저 수행해, 임베딩 장애가 발생해도 이미 저장된 `experiences` 정형 레코드와 ORM 세션이 롤백/만료되지 않습니다.

---

## 4. 객관화 채점 엔진 해부 (`backend/app/core/star_rubric.py`)

일반 LLM에게 "이 경험 몇 점이야?"라고 물으면 대부분 **80~90점의 관대화 편향(Leniency Bias)**을 보입니다. 이를 해결하기 위해 **글로벌 채용 평가 프레임워크 3종 + 코드 레벨 하드 캡**을 결합했습니다.

### 4.1 5축 STAR-L 가중치 공식 & 레퍼런스

$$\text{종합 점수} = 0.15 \times S + 0.15 \times T + 0.35 \times A + 0.25 \times R + 0.10 \times L$$

| 축 | 가중치 | 레퍼런스 기준 | 핵심 검증 포인트 |
| :---: | :---: | :--- | :--- |
| **S (Situation)** | 15% | DDI Targeted Selection BARS | 배경·제약조건·문제 심각성(규모·긴급도)이 명확한가 |
| **T (Task)** | 15% | Amazon Bar Raiser ('I' Rule) | 팀 목표가 아니라 **본인 고유 책임 범위**와 달성 목표가 분리되었는가 |
| **A (Action)** | **35%** | Amazon Bar Raiser × Google GCA | "우리가" 아닌 **"내가" 직접 내린 의사결정, 대안 비교, 트레이드오프, 실행 행동**인가 |
| **R (Result)** | **25%** | Google XYZ Formula | 전/후 비교 정량 지표(`Accomplished X as measured by Y`) 또는 객관 검증 근거가 있는가 |
| **L (Learning)** | 10% | Post-Mortem / Learning Agility | 단순 소감이 아니라 **재발 방지 설계·다음 프로젝트 적용 원칙**으로 일반화되었는가 |

### 4.2 5단계 행동 앵커(BARS Lv.1~5) & S~D 캘리브레이션 + 코드 하드 캡
- **S (90+)** Bar Raiser Top 10% / **A (80~89)** 면접 즉시 활용 가능 / **B (65~79)** 핵심 구조 양호·정량 보강 필요 / **C (50~64)** 서술 추상적·본인 기여 불명확 / **D (< 50)** 메모 초안 수준
- **코드 레벨 관대화 방지 하드 캡 (Post-Validation):**
  - `quantified_metrics`가 비어 있고 `Result`에 정량 수치가 전혀 없으면, LLM이 높은 점수를 주더라도 코드가 `Result` 상한을 강제 제한
  - `Learning`이 비어 있거나 너무 짧으면 `Learning` 상한 강제 제한
  - `Action`·`Result`에 치명적 공백이 있으면 `is_sufficient=False`를 유지해 역질문 루프로 유도

---

## 5. 2단계 에스컬레이션 프로빙 & 루프 A(질문 퀄리티 상승 루프)

### 5.1 턴 깊이에 따른 질문 전략 전환 (`interview_graph.py`)
1. **1턴 (Directed Probe):** 5축 점수 중 **가장 낮은 축 2개**를 자동 정렬해, 먼저 `'우리가 했다' → '내가 했다'` 경계 분리(`ownership_drilldown`)와 핵심 빈틈 사실부터 끌어냅니다.
2. **2턴 이상 (Micro-Behavioral & Counter-Factual Drill-Down):** 직전 답변에서 아직 모호한 지점을 파고들어 포기한 대안·트레이드오프(`counter_factual`), 구체 행동 장면(`micro_behavioral`), 전후 비교 수치(`xyz_quantification`), 재발 방지 원칙(`learning_transfer`)을 서로 다른 기법으로 공략합니다.
3. **반복 차단:** `prev_qs`(이미 물어본 질문 목록)를 프롬프트와 코드 린터 양쪽에 전달해 동일 질문 재출제를 방지합니다.

### 5.2 루프 A: 질문 사전 비평 & 실전 효용 추적 (`question_critic.py`)

```mermaid
flowchart LR
    GEN["역질문 후보 2개 생성\n(DDI/Bar-Raiser 5기법)"] --> LINT["1차: 코드 린터 (비용 0원)\n· 예/아니오 폐쇄형 차단\n· 물음표 2개+ 복합 질문 차단\n· 135자 초과 차단\n· 2-gram 중복(>=0.55) 차단\n· 최약 축 미적중 차단"]
    LINT --> CRIT["2차: Fast LLM 4축 비평\n(비반복·용이성·날카로움·적중도)\n총 100점"]
    CRIT -->|"< 80점 또는 린트 결함\n(최대 2회)"| REF["Question Refiner\n핀포인트 리라이트"]
    REF --> LINT
    CRIT -->|">= 80점 & 린트 0건"| USER["사용자에게 제시"]
    USER -->|"답변 입력"| DELTA["ΔSTAR-L 계산\nquestion_feedback_logs 누적\nGET /api/agents/question-quality/stats"]
```

---

## 6. 포트폴리오·발표·면접용 핵심 Q&A 포인트

| 예상 질문 | 핵심 답변 (우리 아키텍처 근거) |
| :--- | :--- |
| **Q1. 그냥 ChatGPT 멀티턴 대화로 STAR 정리하면 되지 않나요?** | 일반 챗봇은 ① 매 턴 점수가 객관화되지 않아 관대하게 넘어가고 ② 대화가 길어지면 앞 문맥을 놓치거나 같은 질문을 반복하며 ③ 결과가 텍스트로 흩어집니다. 우리는 **LangGraph `StateGraph` + `AsyncPostgresSaver` + 5축 BARS 코드 하드 캡 + 5종 구조화 프로빙**으로 "빈틈이 채워질 때까지 정조준"하고, 결과를 **정형 DB + HNSW 격리 벡터 DB**로 즉시 자산화합니다. |
| **Q2. LLM 채점의 관대화 편향과 환각은 어떻게 통제했나요?** | ① `extract_star`에서 미언급 수치·기술 날조 금지 프롬프트 외부화(`interview_extract.txt`) ② `grade_gaps`에서 BARS Lv.1~5 풀 앵커 제공 + **코드 레벨 정량/회고 미기재 하드 캡**으로 LLM 점수를 결정론적으로 보정했습니다. |
| **Q3. 질문 퀄리티 루프(루프 A)를 도입하고 숫자로 검증해 보셨나요?** | 네. 10종 빈약 메모 골든셋(`question_golden_dataset.json`)으로 Nova Pro Judge 실측을 돌린 결과, **코드 린터가 결함을 `1 → 0건`으로 제거**한 반면, `Nova Lite` Critic이 이미 좋은 1차 질문까지 과도하게 리라이트해 `specificity`가 `0.74 → 0.56`으로 하락하는 트레이드오프를 숫자로 발견했습니다. 덕분에 "무조건 루프를 돌리는 것보다 코드 린트 결함·저점수(`< 70`) 핀포인트 개입이 최적"이라는 데이터 기반 설계 결론을 도출했습니다. |
| **Q4. 채굴한 경험이 이후 서비스에서 어떻게 재활용되나요?** | 저장 즉시 Parent/Child 청킹(500자/겹침 100자)으로 `doc_type='experience'` 벡터에 색인되어, **자소서 공방의 유일한 팩트 근거**, **기업 3각 매칭의 증명 소재**, **6축 캐릭터 진단의 근거**, **코파일럿 Agentic RAG의 한국어 2-gram BM25+Vector RRF 검색 대상(`MRR 1.000`, 토큰 `-35%`)**으로 연결됩니다. |
