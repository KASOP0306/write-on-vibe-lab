"""루프 A(질문 퀄리티 상승) & 루프 B(프로젝트 정리·요약 퀄리티 상승) 단위 테스트."""

import unittest

from app.core.question_critic import (
    MAX_QUESTION_REVISIONS,
    code_lint_questions,
)
from app.core.summary_verifier import (
    MAX_SUMMARY_REVISIONS,
    compute_cross_section_overlap,
    detect_unverified_metrics,
    format_evidence_map_block,
)
from app.prompts import load_prompt
from eval.run_quality_eval import (
    load_question_golden_dataset,
    load_summary_golden_dataset,
)


class QualityLoopsUnitTests(unittest.TestCase):
    def test_max_revisions_configured_to_two(self):
        self.assertEqual(MAX_QUESTION_REVISIONS, 2)
        self.assertEqual(MAX_SUMMARY_REVISIONS, 2)

    def test_quality_loop_prompts_load(self):
        for name in (
            "question_critic",
            "question_refiner",
            "evidence_extract",
            "summary_verifier",
            "summary_repair",
        ):
            text = load_prompt(name)
            self.assertIn("<role>", text)
            self.assertIn("<rules>", text)
            self.assertIn("<output_format>", text)

    def test_golden_datasets_structure(self):
        q_ds = load_question_golden_dataset()
        self.assertEqual(len(q_ds["cases"]), 10)
        s_ds = load_summary_golden_dataset()
        self.assertEqual(len(s_ds["cases"]), 6)

    def test_question_code_linter_catches_all_defects(self):
        # 1) 폐쇄형, 복합 질문, 이전 질문 중복, 약한 축 미적중 탐지
        bad_qs = [
            {
                "target_axis": "action",
                "question": "Redis 캐시를 도입해서 성능이 좋아졌나요?",
            },
            {
                "target_axis": "task",
                "question": "팀 역할은 무엇이었나요? 그리고 포기한 대안은 무엇이었나요?",
            },
        ]
        issues = code_lint_questions(
            bad_qs,
            prev_questions=["Redis 캐시를 도입해서 성능이 좋아졌나요?"],
            weakest_axes=["result", "learning"],
        )
        joined = " ".join(issues)
        self.assertIn("폐쇄형", joined)
        self.assertIn("복합 질문", joined)
        self.assertIn("이전 질문과 중복", joined)
        self.assertIn("result", joined)

        # 2) 좋은 개방형 질문은 0건 통과
        good_qs = [
            {
                "target_axis": "result",
                "question": "Redis 캐시 도입 전후로 검색 API P99 응답시간이 어떤 수치로 변했나요?",
            },
            {
                "target_axis": "learning",
                "question": "이 경험 이후 캐시 무효화 장애를 막기 위해 다음 프로젝트에 적용할 규칙은 무엇인가요?",
            },
        ]
        self.assertEqual(
            code_lint_questions(good_qs, prev_questions=[], weakest_axes=["result", "learning"]),
            [],
        )

    def test_summary_unverified_metrics_and_overlap(self):
        source = "P99 지연시간을 1,420ms에서 185ms로 87% 단축했고 오류율을 0.00%로 줄였습니다."
        clean_summary = "Redis Lua 락으로 P99를 1420ms에서 185ms(87%)로 줄이고 오류율 0.00%를 달성했습니다."
        self.assertEqual(detect_unverified_metrics(clean_summary, source), [])

        hallucinated = "P99를 185ms로 줄였고 서버 비용을 45% 절감했으며 동시접속 50,000명을 처리했습니다."
        unverified = detect_unverified_metrics(hallucinated, source)
        self.assertIn("45%", unverified)
        self.assertIn("50,000명", unverified)

        # 섹션 중복률 검사
        dup_sections = [
            {
                "section_type": "overview",
                "content": "소상공인 정산 플랫폼에서 새벽 배치 지연 문제를 해결하기 위해 Kafka와 Redis 기반 실시간 정산 엔진을 설계했습니다.",
            },
            {
                "section_type": "architecture",
                "content": "소상공인 정산 플랫폼에서 새벽 배치 지연 문제를 해결하기 위해 Kafka와 Redis 기반 실시간 정산 엔진을 설계했습니다.",
            },
        ]
        self.assertGreaterEqual(compute_cross_section_overlap(dup_sections), 0.9)

        distinct_sections = [
            {
                "section_type": "overview",
                "content": "소상공인 오전 정산 지연 CS 월 310건을 줄이기 위해 3명 팀에서 실시간 정산 전환을 리드했습니다.",
            },
            {
                "section_type": "troubleshooting",
                "content": "1,800 TPS 중복 정산 Race Condition을 idempotency_key DB 유니크 제약과 Outbox 패턴으로 0.00%까지 제거했습니다.",
            },
        ]
        self.assertLess(compute_cross_section_overlap(distinct_sections), 0.3)

        ev_block = format_evidence_map_block(
            [
                {
                    "category": "metric",
                    "importance": "high",
                    "fact": "P99 지연시간 단축",
                    "metric": "185ms",
                    "source_ref": "payguard.md",
                }
            ]
        )
        self.assertIn("★핵심", ev_block)
        self.assertIn("185ms", ev_block)


if __name__ == "__main__":
    unittest.main()
