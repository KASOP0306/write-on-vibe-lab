# DEPLOY_EC2.md — AWS EC2 Docker 배포 & E2E 검증 가이드

이 문서는 **EC2 1대 + Docker Compose(3개 컨테이너) + IAM Role + AWS Bedrock** 조합으로 `write-on-vibe-lab`을 안전하게 배포하고 검증하는 실행 매뉴얼입니다.

---

## 1. AWS 콘솔 사전 준비 (체크리스트)

### 1.1 IAM Role 생성 (EC2 연결용 — Access Key 파일 불필요)
1. AWS IAM → **Roles → Create role** → Trusted entity: **AWS service (EC2)**.
2. 아래 최소 권한 인라인 정책(예: `CareerAgentBedrockPolicy`)을 생성해 Role에 연결합니다.
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "AllowBedrockInvoke",
         "Effect": "Allow",
         "Action": [
           "bedrock:InvokeModel",
           "bedrock:InvokeModelWithResponseStream"
         ],
         "Resource": "*"
       }
     ]
   }
   ```
3. AWS Bedrock 콘솔(`AWS_REGION`, 기본 `us-east-1`)에서 사용할 모델 액세스를 활성화합니다.
   - Fast LLM: `amazon.nova-lite-v1:0`
   - Smart LLM: `amazon.nova-pro-v1:0`
   - Embedding: `amazon.titan-embed-text-v2:0` (1024차원)

### 1.2 EC2 인스턴스 생성 & 보안 그룹
- **OS / 스펙:** Amazon Linux 2023 또는 Ubuntu 24.04 LTS, `t3.small` / `t4g.small` 이상 (권장: `t3.medium` 또는 `t4g.medium`), EBS 스토리지 20~30GB 권장
- **IAM Instance Profile:** 위에서 만든 IAM Role 연결
- **보안 그룹 인바운드 규칙:**
  - `TCP 80` (HTTP): 웹 접속용 (본인 IP 또는 `0.0.0.0/0`)
  - `TCP 22` (SSH): **본인 IP만 허용**
  - `5432` (PostgreSQL), `8000` (Backend): **외부 개방 금지**

### 1.3 IMDSv2 Hop Limit = 2 설정 (필수!)
Docker 컨테이너(`backend`) 내부의 `boto3`가 EC2 IAM Role 자격 증명을 읽으려면 인스턴스 메타데이터 홉 제한을 `2`로 올려야 합니다.
```bash
aws ec2 modify-instance-metadata-options \
  --instance-id <EC2_INSTANCE_ID> \
  --http-put-response-hop-limit 2 \
  --http-endpoint enabled
```
*(AWS 콘솔: EC2 인스턴스 선택 → 작업 → 인스턴스 설정 → 인스턴스 메타데이터 옵션 수정 → 홉 제한 `2`)*

---

## 2. EC2 초기 설치 및 첫 배포

EC2 SSH 접속 후 아래 순서대로 실행합니다.

```bash
# 1. Docker & Docker Compose 플러그인 설치 (Ubuntu 기준)
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# 2. 저장소 클론
git clone https://github.com/KASOP0306/write-on-vibe-lab.git
cd write-on-vibe-lab

# 3. 환경변수 설정 (실제 강력한 DB 비밀번호 입력 / AWS Access Key는 입력하지 않음!)
cp .env.example .env
chmod 600 .env
nano .env

# 4. 빌드 및 기동
docker compose up -d --build
```

---

## 3. 배포 후 최종 E2E 검증 체크리스트

### 3.1 컨테이너 헬스, 단위 테스트 & AWS Bedrock 호출 검증
```bash
# 컨테이너 상태 확인 (db healthy, backend/frontend up)
docker compose ps

# Nginx -> Backend -> PostgreSQL 헬스체크
curl http://localhost/api/health

# 백엔드 단위 테스트 실행
docker compose exec -T backend python -m unittest discover -s tests -v

# IAM Role 기반 Bedrock Fast/Smart LLM & Titan Embeddings 단위 검증
docker compose exec -T backend python -m app.scripts.verify_bedrock
```

### 3.2 자소서 레퍼런스 등록 (선택)
- 웹 브라우저에서 `http://<EC2_PUBLIC_IP>` 접속 → **5. 자소서 공방 → 내 합격 자소서 레퍼런스 → 레퍼런스 직접 등록**으로 실제 합격 자소서를 DB에만 안전하게 추가합니다.
- 또는 로컬에서 준비한 `backend/app/seeds/jasoseo_samples.local.json`을 서버에 올려 아래 명령으로 일괄 시딩합니다. *(이 파일은 `.gitignore` 처리되어 Git에 커밋되지 않습니다.)*
  ```bash
  docker compose exec -T backend python -m app.seeds.seed_jasoseo
  ```

### 3.3 컨테이너 재시작 후 `pgdata` 볼륨 영속성 검증
```bash
# 1단계: 스모크 테스트 + 영속성 검증용 임시 프로젝트 생성
python3 scripts/e2e_verify.py --base-url http://localhost

# 2단계: 컨테이너 완전 내려다 올리기 (주의: -v 옵션 절대 사용 금지!)
docker compose down && docker compose up -d

# 3단계: 재시작 후 데이터가 그대로 살아있는지 검증 및 임시 데이터 정리
python3 scripts/e2e_verify.py --base-url http://localhost --verify-persistence
```

### 3.4 웹 UI 전체 7-페이지 순환 시나리오 점검
1. **1. 나의 신념 & 일상 회고:** 커리어 비전·신념·선호 문체 저장 (`career_identity` 동기화) + 일상 회고 노트 작성 & AI 심화 회고
2. **2. 포트폴리오 & 캐릭터:** 프로젝트 등록(직접/문서/GitHub) → 개별 섹션 파일·메모 AI 업데이트 → 선택형 STAR-L 온보딩 역질문 → 프로젝트 회고 인터뷰(`KPT`/`4Ls`/`Post-Mortem`) → 6축 포트폴리오 캐릭터 진단(접기/펼치기) 확인
3. **3. 경험 채굴 (STAR-L):** 프로젝트 연결 후 거친 메모 입력 → 5축 STAR-L 레이더 & S~D 등급 확인 → DDI/Bar-Raiser 역질문 답변 또는 `[이 상태로 저장하기]` 저장
4. **4. 기업 리서치:** 목표 기업 + JD 입력 → 4관점 멀티소스 리서치 & 출처 인용 포함 신념 3각 매칭표 확인
5. **5. 자소서 공방:** 기업·문항 입력 → 1단계 문항 해부 & 최적 프로젝트·STAR-L 추천 선택 → 2단계 3축 융합 작성·비평·퇴고·De-AI 실시간 SSE & 변경 리포트 확인
6. **6. 지원 & 취준 회고:** 지원 결과·피드백 입력 → 6축 캐릭터 대비 Gap 분석 & 보완 플랜 → 코파일럿 주제로 원클릭 연계
7. **7. 새 프로젝트 코파일럿:** 이전 회고 `Try` 학습 루프 + 캐릭터 약점 + 기업 리서치 + 웹 검색 기반 청사진 추천 & 설계 채팅 확인

---

## 4. 코드 업데이트 재배포

이후 코드를 수정해 GitHub에 Push했다면 EC2에서 아래 스크립트 한 줄로 무손실 재배포합니다.

```bash
bash scripts/deploy_ec2.sh
```
