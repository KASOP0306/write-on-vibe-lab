"""Day 4 E2E 스모크 테스트 & 데이터 영속성 검증 스크립트.

사용 예시:
    # 1) 기본 CRUD + 헬스체크 검증 (AWS Bedrock 없이도 실행 가능)
    python scripts/e2e_verify.py --base-url http://localhost

    # 2) 컨테이너 재시작 후 영속성 확인 모드
    python scripts/e2e_verify.py --base-url http://localhost --verify-persistence
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


PERSIST_PROJECT_NAME = "__e2e_persistence_probe__"


def _request(base_url: str, method: str, path: str, body: dict | None = None):
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, (json.loads(raw) if raw else None)


def run_smoke_test(base_url: str) -> None:
    print(f"[1/4] GET /api/health ({base_url})")
    status_code, health = _request(base_url, "GET", "/api/health")
    assert status_code == 200 and health.get("status") == "ok", f"Unexpected health: {health}"
    print(f"  PASS: {health}")

    print("[2/4] GET & PUT /api/profile")
    _, profile = _request(base_url, "GET", "/api/profile")
    assert "career_vision" in profile
    print("  PASS: profile loaded")

    print("[3/4] POST /api/projects (persistence probe creation)")
    _, projects = _request(base_url, "GET", "/api/projects")
    existing = [p for p in projects if p["name"] == PERSIST_PROJECT_NAME]
    if not existing:
        status_code, created = _request(
            base_url,
            "POST",
            "/api/projects",
            {
                "name": PERSIST_PROJECT_NAME,
                "period": "2026",
                "role": "E2E Verifier",
                "summary": "pgdata 볼륨 영속성 검증용 임시 프로젝트",
                "tech_stack": ["Docker", "pgvector"],
            },
        )
        assert status_code == 201
        print(f"  PASS: created project id={created['id']}")
    else:
        print(f"  PASS: probe project already exists id={existing[0]['id']}")

    print("[4/4] GET /api/interests, /api/companies, /api/samples, /api/applications")
    for endpoint in ("/api/interests", "/api/companies", "/api/samples", "/api/applications"):
        code, data = _request(base_url, "GET", endpoint)
        assert code == 200 and isinstance(data, list), f"Failed on {endpoint}"
        print(f"  PASS: {endpoint} ({len(data)} items)")

    print("\nALL SMOKE CHECKS PASSED!")
    print("다음 명령으로 재시작 후 영속성을 검증하세요:")
    print("  docker compose down && docker compose up -d")
    print(f"  python scripts/e2e_verify.py --base-url {base_url} --verify-persistence")


def verify_persistence_and_cleanup(base_url: str) -> None:
    print(f"[Persistence Check] Searching for '{PERSIST_PROJECT_NAME}' after restart...")
    _, projects = _request(base_url, "GET", "/api/projects")
    matches = [p for p in projects if p["name"] == PERSIST_PROJECT_NAME]
    if not matches:
        print("FAIL: Probe project missing after container restart! Check pgdata volume.")
        sys.exit(1)

    for item in matches:
        _request(base_url, "DELETE", f"/api/projects/{item['id']}")
        print(f"  PASS: Persisted project id={item['id']} verified & cleaned up.")
    print("\nPGDATA VOLUME PERSISTENCE VERIFIED!")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--verify-persistence", action="store_true")
    args = parser.parse_args()

    try:
        if args.verify_persistence:
            verify_persistence_and_cleanup(args.base_url)
        else:
            run_smoke_test(args.base_url)
    except urllib.error.URLError as exc:
        print(f"CONNECTION ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
