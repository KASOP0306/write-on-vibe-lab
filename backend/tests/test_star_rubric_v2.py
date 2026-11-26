"""STAR-L 21지표 하이브리드 평가 엔진, 600 XP 누적 계산기, 캘리브레이션 지표 단위 테스트."""

import unittest

from app.core.question_critic import PASS_SCORE_THRESHOLD
from app.core.star_rubric import (
    CURRENT_RUBRIC_VERSION,
    STAR_AXIS_ORDER,
    STAR_CHECKPOINT_IDS,
    compute_cumulative_portfolio_xp,
    compute_experience_xp,
    load_rubric_bundle,
    rescore_experience_with_rubric,
    verify_and_score_checkpoints,
    verify_quote_grounding,
)
from app.schemas.agents import InterviewStartRequest
from eval.run_rubric_eval import compute_calibration_metrics, compute_spearman_rho


class TestStarRubricV2(unittest.TestCase):
    def test_rubric_bundle_integrity(self):
        bundle = load_rubric_bundle(CURRENT_RUBRIC_VERSION)
        self.assertEqual(bundle["version"], "v2.1")
        checkpoints = bundle["checkpoints"]
        self.assertEqual(len(checkpoints), 21)
        self.assertEqual([c["id"] for c in checkpoints], STAR_CHECKPOINT_IDS)

        # 모든 배점은 짝수 정수이며 합계는 정확히 100점, partial_weight는 엄격 보수화
        total_weight = 0
        axis_sums = {ax: 0 for ax in STAR_AXIS_ORDER}
        for cp in checkpoints:
            w = int(cp["weight"])
            pw = int(cp["partial_weight"])
            self.assertEqual(w % 2, 0, f"{cp['id']} weight must be even integer")
            self.assertGreaterEqual(pw, 1)
            self.assertLessEqual(pw, w // 2)
            total_weight += w
            axis_sums[cp["axis"]] += w

        self.assertEqual(total_weight, 100)
        self.assertEqual(axis_sums, {"situation": 12, "task": 14, "action": 36, "result": 26, "learning": 12})

    def test_quote_grounding_verification(self):
        source = "PostgreSQL 복합 인덱스를 적용해 검색 p95 응답 시간을 1800ms에서 175ms로 단축했습니다."
        ok, score = verify_quote_grounding("검색 p95 응답 시간을 1800ms에서 175ms로 단축", source)
        self.assertTrue(ok)
        self.assertEqual(score, 1.0)

        hallucinated_ok, h_score = verify_quote_grounding("Kafka 분산 스트리밍으로 초당 10만 건 처리", source)
        self.assertFalse(hallucinated_ok)
        self.assertLess(h_score, 0.3)

    def test_deterministic_hard_caps_and_fluff_rejection(self):
        # LLM이 관대하게 높은 점수를 줬다고 가정해도 Python 코드가 원문 대조·하드 캡으로 차단해야 함
        fluff_star = {
            "title": "검색 속도 개선",
            "situation": "우리 팀 프로젝트에서 검색이 느렸습니다.",
            "task": "팀이 함께 개선해야 했습니다.",
            "action": "우리 팀이 함께 캐시를 적용했습니다.",
            "result": "이전보다 훨씬 빨라졌습니다.",
            "learning": "많이 배웠습니다.",
            "quantified_metrics": "",
        }
        inflated_llm_output = {
            cid: {"status": 2, "quote": "존재하지 않는 환각 문장입니다", "tip": ""}
            for cid in STAR_CHECKPOINT_IDS
        }
        # 실제 존재하는 문장을 인용해도 하드 캡 대상(R1/R2/A3/L2)은 강등되어야 함
        inflated_llm_output["R1"] = {"status": 2, "quote": "이전보다 훨씬 빨라졌습니다", "tip": ""}
        inflated_llm_output["R2"] = {"status": 2, "quote": "이전보다 훨씬 빨라졌습니다", "tip": ""}
        inflated_llm_output["A3"] = {"status": 2, "quote": "우리 팀이 함께 캐시를 적용했습니다", "tip": ""}
        inflated_llm_output["L2"] = {"status": 2, "quote": "많이 배웠습니다", "tip": ""}

        scored = verify_and_score_checkpoints(inflated_llm_output, star=fluff_star)
        self.assertEqual(scored["checkpoints"]["R1"]["status"], 0)
        self.assertEqual(scored["checkpoints"]["A3"]["status"], 1)
        self.assertEqual(scored["checkpoints"]["L2"]["status"], 0)
        self.assertLess(scored["weighted_score"], 25)
        self.assertEqual(scored["grade"], "D")
        self.assertGreater(len(scored["cap_events"]), 3)

    def test_full_verified_experience_scores_high_and_rescores_deterministically(self):
        strong_star = {
            "title": "검색 API p95 1820ms→175ms 단축",
            "situation": "월 12만 사용자 커머스 검색 API에서 피크 420 RPS 시 p95 1820ms 지연과 2주 마감 제약이 있었습니다.",
            "task": "백엔드 오너로서 p95 250ms 이하 목표를 맡아 슬로우 쿼리 로그로 풀스캔 원인을 진단하고 검색 API를 최우선 선정했습니다.",
            "action": "제가 직접 복합 인덱스와 Redis 캐시를 설계했습니다. Elasticsearch 도입 vs Redis 캐시 대안을 비용·일정으로 비교했고, 캐시 스탬피드 장애를 분산 락으로 돌파하며 카나리 배포와 롤백 플래그로 리스크를 관리하고 프론트팀과 60초 TTL을 합의했습니다.",
            "result": "부하 테스트와 운영 모니터링에서 p95가 1820ms에서 175ms로 90% 감소했고, 단계별 벤치마크로 인과를 입증해 사내 표준 가이드로 채택되었습니다.",
            "learning": "초기 캐시 히트율이 낮았던 한계를 성찰하며 '기준선 측정→최소 변경→롤백 플래그' 원칙을 정립해 후속 결제 API 프로젝트에도 적용했습니다.",
            "quantified_metrics": "p95 1820ms → 175ms (-90%)",
        }
        perfect_llm = {
            "S1": {"status": 2, "quote": "월 12만 사용자 커머스 검색 API"},
            "S2": {"status": 2, "quote": "피크 420 RPS 시 p95 1820ms 지연"},
            "S3": {"status": 2, "quote": "2주 마감 제약"},
            "S4": {"status": 2, "quote": "월 12만 사용자"},
            "T1": {"status": 2, "quote": "p95 250ms 이하 목표"},
            "T2": {"status": 2, "quote": "백엔드 오너로서"},
            "T3": {"status": 2, "quote": "슬로우 쿼리 로그로 풀스캔 원인을 진단"},
            "T4": {"status": 2, "quote": "검색 API를 최우선 선정"},
            "A1": {"status": 2, "quote": "복합 인덱스와 Redis 캐시를 설계"},
            "A2": {"status": 2, "quote": "Elasticsearch 도입 vs Redis 캐시 대안을 비용·일정으로 비교"},
            "A3": {"status": 2, "quote": "제가 직접 복합 인덱스와 Redis 캐시를 설계"},
            "A4": {"status": 2, "quote": "캐시 스탬피드 장애를 분산 락으로 돌파"},
            "A5": {"status": 2, "quote": "카나리 배포와 롤백 플래그로 리스크를 관리"},
            "A6": {"status": 2, "quote": "프론트팀과 60초 TTL을 합의"},
            "R1": {"status": 2, "quote": "1820ms에서 175ms로 90% 감소"},
            "R2": {"status": 2, "quote": "1820ms에서 175ms로 90% 감소"},
            "R3": {"status": 2, "quote": "단계별 벤치마크로 인과를 입증"},
            "R4": {"status": 2, "quote": "사내 표준 가이드로 채택"},
            "L1": {"status": 2, "quote": "초기 캐시 히트율이 낮았던 한계를 성찰"},
            "L2": {"status": 2, "quote": "기준선 측정→최소 변경→롤백 플래그 원칙을 정립"},
            "L3": {"status": 2, "quote": "후속 결제 API 프로젝트에도 적용"},
        }
        scored = verify_and_score_checkpoints(perfect_llm, star=strong_star)
        self.assertEqual(scored["weighted_score"], 100)
        self.assertEqual(scored["grade"], "S")
        self.assertEqual(scored["xp"], 100)

        # Zero-LLM 재채점 일관성 확인
        rescored = rescore_experience_with_rubric(scored, strong_star, rubric_version="v2.1")
        self.assertEqual(rescored["weighted_score"], 100)

    def test_cumulative_portfolio_xp_project_cap_and_4_slot_selection(self):
        # 5개 프로젝트 보유: 1번 프로젝트에 S등급 경험 5개(각 90 XP)가 있어도 체감 가중치(1.0/0.8/0.5/0.2/0.0)로 90+72+45+18+0 = 225 XP!
        projects = [
            {"id": 1, "name": "P1", "is_portfolio_selected": True},
            {"id": 2, "name": "P2", "is_portfolio_selected": False},
            {"id": 3, "name": "P3", "is_portfolio_selected": False},
            {"id": 4, "name": "P4", "is_portfolio_selected": False},
            {"id": 5, "name": "P5", "is_portfolio_selected": False},
        ]
        experiences = [
            {"id": 10, "project_id": 1, "title": "E1", "completeness_score": 90, "star_scores": {}},  # 90 * 1.0 = 90
            {"id": 11, "project_id": 1, "title": "E2", "completeness_score": 90, "star_scores": {}},  # 90 * 0.8 = 72
            {"id": 12, "project_id": 1, "title": "E3", "completeness_score": 90, "star_scores": {}},  # 90 * 0.5 = 45
            {"id": 13, "project_id": 1, "title": "E4", "completeness_score": 90, "star_scores": {}},  # 90 * 0.2 = 18
            {"id": 14, "project_id": 1, "title": "E5", "completeness_score": 90, "star_scores": {}},  # 5th -> 0
            {"id": 20, "project_id": 2, "title": "E6", "completeness_score": 80, "star_scores": {}},  # A: round(80*0.85)=68
            {"id": 30, "project_id": 3, "title": "E7", "completeness_score": 60, "star_scores": {}},  # B: round(60*0.60)=36
            {"id": 40, "project_id": 4, "title": "E8", "completeness_score": 40, "star_scores": {}},  # C: round(40*0.30)=12
            {"id": 50, "project_id": 5, "title": "E9", "completeness_score": 20, "star_scores": {}},  # D: 2 (5위 제외)
        ]
        mastery = compute_cumulative_portfolio_xp(projects, experiences)
        self.assertEqual(mastery["max_total_xp"], 1000)
        self.assertEqual(mastery["project_cap"], 250)
        self.assertEqual(len(mastery["selected_projects"]), 4)
        self.assertEqual(mastery["selected_projects"][0]["project_id"], 1)
        self.assertEqual(mastery["selected_projects"][0]["capped_xp"], 225)
        self.assertEqual(mastery["total_xp"], 225 + 68 + 36 + 12)
        self.assertEqual(mastery["level"]["code"], "Lv.2")

        # 100점 S급 4개가 모여야 단일 프로젝트 250 XP 만점 (100+80+50+20=250)
        perfect_4 = [
            {"id": i, "project_id": 1, "title": f"S{i}", "completeness_score": 100, "star_scores": {}}
            for i in range(4)
        ]
        single_mastery = compute_cumulative_portfolio_xp([projects[0]], perfect_4)
        self.assertEqual(single_mastery["total_xp"], 250)
        self.assertTrue(single_mastery["selected_projects"][0]["cap_reached"])
        self.assertEqual(single_mastery["level"]["code"], "Lv.2")

    def test_conservative_critic_threshold_and_interview_start_schema(self):
        self.assertEqual(PASS_SCORE_THRESHOLD, 70)
        # project_id가 있으면 raw_notes 비어있어도 허용
        req = InterviewStartRequest(raw_notes="", project_id=1)
        self.assertEqual(req.project_id, 1)
        # project_id 없고 raw_notes 짧으면 실패
        with self.assertRaises(Exception):
            InterviewStartRequest(raw_notes="짧음", project_id=None)

    def test_calibration_metrics_math(self):
        rho = compute_spearman_rho([10, 30, 50, 70, 90], [12, 28, 55, 72, 91])
        self.assertEqual(rho, 1.0)
        summary = compute_calibration_metrics(
            [
                {"expected_score": 90, "predicted_score": 88, "category": "tier_anchor", "cap_events": []},
                {"expected_score": 20, "predicted_score": 22, "category": "fluff_trap", "max_allowed_score": 44, "cap_events": [{"reason": "R1"}]},
                {"expected_score": 18, "predicted_score": 20, "category": "monotonicity_before", "pair_id": "M1", "cap_events": []},
                {"expected_score": 78, "predicted_score": 76, "category": "monotonicity_after", "pair_id": "M1", "cap_events": []},
            ]
        )
        self.assertEqual(summary["fluff_trap_pass_rate"], 100.0)
        self.assertEqual(summary["monotonicity_pass_rate"], 100.0)
        self.assertEqual(summary["mae"], 2.0)


if __name__ == "__main__":
    unittest.main()
