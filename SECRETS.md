# SECRETS.md — 비밀번호·패스워드·API 키 및 보안 관리 지침

> [!CAUTION]
> 이 저장소(`KASOP0306/write-on-vibe-lab`)는 **Public 저장소**입니다.  
> 실제 비밀번호, AWS Access Key, SSH `.pem` 키, GitHub Token, `.env` 파일은 **단 한 번이라도 커밋·푸시되어서는 안 됩니다.**

---

## 1. 절대 커밋 금지 항목 (Never Commit)

`.gitignore`에 아래 항목이 차단되어 있으며, 어떠한 경우에도 `git add -f`로 강제 추가하지 않습니다.

- `.env`, `.env.local`, `.env.production` 등 실제 환경변수 파일 (`.env.example`만 예외적으로 커밋 허용)
- AWS 자격 증명 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `~/.aws/credentials`, `*accessKeys*.csv`)
- SSH / EC2 개인 키 및 인증서 (`*.pem`, `*.key`, `*.ppk`, `id_rsa*`, `id_ed25519*`)
- PostgreSQL 실제 비밀번호가 포함된 `DATABASE_URL` 문자열, DB 백업 덤프(`*.dump`, `*.sql.bak`)
- GitHub Personal Access Token (`ghp_*`, `gho_*`, `github_pat_*`)

---

## 2. 프로젝트 자격 증명 & 환경변수 인벤토리

이 프로젝트는 **AWS Bedrock Only + Docker Self-Contained** 원칙을 따릅니다. OpenAI, Anthropic Direct, Tavily 등의 유료 외부 API 키는 요구하지 않습니다.

| 구분 | 변수명 / 자산 | 민감도 | 로컬 개발 관리 | EC2 운영 관리 | Git 커밋 |
| :--- | :--- | :---: | :--- | :--- | :---: |
| **DB 계정** | `POSTGRES_USER` | 낮음 | `.env` | EC2 `.env` (`chmod 600`) | ❌ (`.env.example`만) |
| **DB 비밀번호** | `POSTGRES_PASSWORD` | **높음** | `.env` (무작위 생성) | EC2 `.env` (강력한 난수) | ❌ 절대 금지 |
| **DB 연결 URL** | `DATABASE_URL` | **높음** | `.env` (비밀번호 포함) | EC2 `.env` | ❌ 절대 금지 |
| **AWS 인증** | `~/.aws/credentials` 또는 `AWS_PROFILE` | **최상** | 로컬 `~/.aws` 프로파일 사용 | **EC2 IAM Role 자동 위임** (키 파일 미사용) | ❌ 절대 금지 |
| **AWS 리전** | `AWS_REGION` | 낮음 | `.env` (예: `us-east-1`) | EC2 `.env` | `.env.example` 가능 |
| **Bedrock 모델** | `BEDROCK_FAST_MODEL_ID` / `BEDROCK_SMART_MODEL_ID` / `BEDROCK_EMBED_MODEL_ID` | 낮음 | `.env` | EC2 `.env` | `.env.example` 가능 |
| **EC2 SSH 키** | `<keypair>.pem` | **최상** | 로컬 `~/.ssh/` 보관 (레포 외부) | AWS EC2 Key Pair | ❌ 절대 금지 |
| **GitHub 인증** | `gh` CLI 세션 토큰 | **최상** | OS Keyring (`gh auth login`) | 필요 시 Deploy Key (읽기 전용) | ❌ 절대 금지 |

---

## 3. 환경별 안전한 설정 방법

### 3.1 로컬 개발 환경 (`.env` 생성)

1. 템플릿을 복사해 로컬 전용 `.env` 파일을 생성합니다.
   ```powershell
   Copy-Item .env.example .env
   ```
2. `.env` 내부의 `CHANGE_ME_*` 플레이스홀더를 실제 로컬 값으로 교체합니다.
3. DB 비밀번호는 예측 불가능한 난수로 생성하는 것을 권장합니다.
   ```powershell
   # PowerShell에서 32바이트 안전한 랜덤 비밀번호 생성 예시
   -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
   ```
4. AWS Bedrock 호출 시 코드나 `.env`에 영구 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`를 직접 넣기보다, AWS CLI 프로파일(`~/.aws/credentials`)과 `AWS_PROFILE`을 사용하세요.
   ```powershell
   aws configure --profile career-agent-dev
   ```

### 3.2 EC2 운영 환경 (IAM Role 필수)

1. **AWS Access Key 파일 저장 금지:** EC2 인스턴스에 **Bedrock 최소 권한 IAM Role**을 연결합니다. `boto3` 기본 자격 증명 체인이 자동으로 IMDS를 통해 임시 자격 증명을 획득합니다.
   - 권장 최소 권한 예시: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` (필요 시 사용하는 모델 ARN으로 제한)
2. **EC2 `.env` 파일 보호:** 서버의 `.env`는 소유자만 읽을 수 있도록 권한을 제한합니다.
   ```bash
   chmod 600 .env
   ```
3. **네트워크 포트 최소화:**
   - DB(`5432`) 포트는 외부에 절대 노출하지 않고 Docker 내부 네트워크에서만 `backend`와 통신합니다.
   - EC2 보안 그룹은 HTTP(`80`)와 본인 IP 한정 SSH(`22`)만 허용합니다.

---

## 4. 커밋·푸시 전 보안 체크리스트

코드를 커밋/푸시하기 전 반드시 아래를 점검합니다.

- [ ] `git status` 출력에 `.env`, `*.pem`, `*.key`, `credentials*` 파일이 포함되지 않았는가?
- [ ] `git diff --cached`에서 실제 비밀번호, `AKIA...`(AWS Access Key ID), `ghp_`/`gho_` 토큰이 코드나 문서에 하드코딩되지 않았는가?
- [ ] `docker-compose.yml` 및 `backend/app/config.py`가 실제 비밀번호 대신 `${POSTGRES_PASSWORD}` 등 환경변수 참조만 사용하는가?
- [ ] GitHub 저장소 설정(`Settings → Code security`)에서 **Secret scanning** 및 **Push protection**이 활성화되어 있는가?

---

## 5. 실수로 비밀번호·키를 Push했을 때 긴급 대응 절차

Public 저장소에 민감 정보가 한 번이라도 Push되면 **즉시 유출된 것으로 간주**하고 아래 순서로 대응합니다.

1. **즉시 폐기 및 로테이션 (최우선):**
   - AWS 키: AWS IAM 콘솔에서 즉시 비활성화(Deactivate) 및 삭제(Delete) 후 새 키 발급 (또는 IAM Role 전환).
   - GitHub 토큰: GitHub `Settings → Developer settings → Personal access tokens`에서 즉시 Revoke.
   - DB 비밀번호: PostgreSQL 비밀번호 즉시 변경 후 컨테이너 재기동.
2. **Git 히스토리 제거:**
   - 단순히 파일만 삭제하는 커밋을 추가해도 이전 커밋 이력에 남습니다.
   - `git filter-repo` 또는 BFG Repo-Cleaner로 히스토리에서 해당 파일/문자열을 완전 제거한 뒤 force push 합니다.
3. **사후 점검:**
   - AWS CloudTrail 및 GitHub 보안 로그에서 비정상 접근 여부를 확인합니다.
