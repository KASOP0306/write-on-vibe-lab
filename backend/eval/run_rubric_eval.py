"""STAR-L 21지표 하이브리드 점수축 5대 정량 캘리브레이션 평가 러너.

측정 지표 (5대 캘리브레이션 지표):
1. Spearman ρ (순위 상관계수): 전문가 기대 점수 vs 하이브리드 산출 점수 순위 일치도 (목표 >= 0.85)
2. MAE (평균 절대 오차): mean(|predicted - expected|) (목표 <= 12.0점)
3. Leniency Bias (관대화 편향): mean(predicted - expected) (+이면 후함, -이면 박함, 목표 -5 ~ +5)
4. Fluff Trap Pass Rate: 미사여구 함정 케이스들이 엄격하게 45점 미만으로 차단된 비율 (목표 100%)
5. Monotonicity Pass Rate: Before → After 보강 쌍에서 점수가 유의미하게 상승한 비율 (목표 100%)

실행 예:
  python -m eval.run_rubric_eval --rubric-version v2.0 --output eval/rubric_eval_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import time
from typing import Any

from app.core.star_rubric import (
    CURRENT_RUBRIC_VERSION,
    evaluate_star_experience_rubric,
)

DATASET_PATH = Path(__file__).resolve().parent / "rubric_calibration_dataset.json"


def _ranks(values: list[float]) -> list[float]:
    """동점(tie) 평균 순위를 계산한다."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def compute_spearman_rho(xs: list[float], ys: list[float]) -> float:
    """외부 의존성 없이 정확한 Spearman 순위 상관계수 ρ를 계산한다."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    rx = _ranks(xs)
    ry = _ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den_x = math.sqrt(sum((a - mx) ** 2 for a in rx))
    den_y = math.sqrt(sum((b - my) ** 2 for b in ry))
    if den_x == 0 or den_y == 0:
        return 0.0
    return round(num / (den_x * den_y), 4)


def compute_calibration_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """개별 평가 결과 목록에서 5대 캘리브레이션 지표를 집계한다."""
    expected = [float(r["expected_score"]) for r in records]
    predicted = [float(r["predicted_score"]) for r in records]
    n = len(records)

    rho = compute_spearman_rho(expected, predicted)
    mae = round(sum(abs(p - e) for p, e in zip(predicted, expected)) / max(1, n), 2)
    leniency_bias = round(sum(p - e for p, e in zip(predicted, expected)) / max(1, n), 2)

    fluff_cases = [r for r in records if r.get("category") == "fluff_trap"]
    fluff_passed = sum(
        1 for r in fluff_cases if r["predicted_score"] <= int(r.get("max_allowed_score", 44))
    )
    fluff_rate = round((fluff_passed / len(fluff_cases)) * 100, 1) if fluff_cases else 100.0

    # Monotonicity pairs
    before_map = {
        r["pair_id"]: r for r in records if r.get("category") == "monotonicity_before" and r.get("pair_id")
    }
    after_map = {
        r["pair_id"]: r for r in records if r.get("category") == "monotonicity_after" and r.get("pair_id")
    }
    mono_pairs: list[dict[str, Any]] = []
    for pid, b in before_map.items():
        a = after_map.get(pid)
        if a:
            gain = a["predicted_score"] - b["predicted_score"]
            mono_pairs.append(
                {
                    "pair_id": pid,
                    "before": b["predicted_score"],
                    "after": a["predicted_score"],
                    "gain": gain,
                    "passed": gain >= 25,
                }
            )
    mono_passed = sum(1 for p in mono_pairs if p["passed"])
    mono_rate = round((mono_passed / len(mono_pairs)) * 100, 1) if mono_pairs else 100.0

    total_caps = sum(len(r.get("cap_events") or []) for r in records)

    return {
        "sample_count": n,
        "spearman_rho": rho,
        "mae": mae,
        "leniency_bias": leniency_bias,
        "fluff_trap_pass_rate": fluff_rate,
        "fluff_trap_passed": fluff_passed,
        "fluff_trap_total": len(fluff_cases),
        "monotonicity_pass_rate": mono_rate,
        "monotonicity_pairs": mono_pairs,
        "total_hard_caps_triggered": total_caps,
    }


async def run_rubric_calibration_eval(
    *,
    dataset_path: Path = DATASET_PATH,
    rubric_version: str = CURRENT_RUBRIC_VERSION,
    limit: int | None = None,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = json.loads(dataset_path.read_text(encoding="utf-8"))
    if limit:
        cases = cases[:limit]

    records: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    for idx, case in enumerate(cases, start=1):
        case_t0 = time.perf_counter()
        res = await evaluate_star_experience_rubric(
            case["star"],
            project_types=case.get("project_types"),
            rubric_version=rubric_version,
        )
        elapsed_ms = int((time.perf_counter() - case_t0) * 1000)
        sc = int(res["completeness_score"])
        grade = res["star_scores"]["grade"]
        cap_events = res["star_scores"].get("cap_events") or []

        rec = {
            "id": case["id"],
            "tier": case["tier"],
            "category": case.get("category", "tier_anchor"),
            "pair_id": case.get("pair_id"),
            "max_allowed_score": case.get("max_allowed_score", 44),
            "expected_score": int(case["expected_score"]),
            "predicted_score": sc,
            "diff": sc - int(case["expected_score"]),
            "predicted_grade": grade,
            "passed_checkpoints": res["star_scores"].get("passed_checkpoints", 0),
            "cap_events": cap_events,
            "latency_ms": elapsed_ms,
        }
        records.append(rec)
        print(
            f"[{idx:02d}/{len(cases):02d}] {case['id']:16s} "
            f"exp={case['expected_score']:3d} ({case['tier']}) -> "
            f"pred={sc:3d} ({grade}) diff={rec['diff']:+3d} "
            f"caps={len(cap_events)} ({elapsed_ms}ms)",
            flush=True,
        )

    summary = compute_calibration_metrics(records)
    summary["rubric_version"] = rubric_version
    summary["total_elapsed_sec"] = round(time.perf_counter() - t0, 2)
    return {
        "summary": summary,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="STAR-L 21지표 하이브리드 점수축 캘리브레이션 평가")
    parser.add_argument("--rubric-version", default=CURRENT_RUBRIC_VERSION)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = asyncio.run(
        run_rubric_calibration_eval(
            rubric_version=args.rubric_version,
            limit=args.limit,
        )
    )
    print("\n=== STAR-L 21-Checkpoint Calibration Summary ===")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved report -> {out_path}")


if __name__ == "__main__":
    main()
