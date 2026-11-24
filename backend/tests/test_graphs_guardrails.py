"""Day 2~4 LangGraph 루프 가드레일 및 라우팅 단위 테스트.

실행 예시 (backend 컨테이너 내부):
    python -m unittest discover -s tests -v
"""

import unittest

from app.graphs.copilot_graph import route_after_relevance
from app.graphs.cover_letter_graph import ANTI_HALLUCINATION_RULE, route_after_critic
from app.graphs.interview_graph import route_after_grade, route_after_prepare


class TestGraphGuardrails(unittest.TestCase):
    # --- 워크플로우 ①: 경험 채굴 ---
    def test_interview_force_save_skips_questions(self) -> None:
        self.assertEqual(
            route_after_grade({"force_save": True, "completeness_score": 20, "is_sufficient": False}),
            "save_experience",
        )

    def test_interview_high_score_saves_automatically(self) -> None:
        self.assertEqual(
            route_after_grade({"force_save": False, "completeness_score": 85, "is_sufficient": True}),
            "save_experience",
        )

    def test_interview_low_score_generates_questions(self) -> None:
        self.assertEqual(
            route_after_grade({"force_save": False, "completeness_score": 60, "is_sufficient": False}),
            "generate_questions",
        )

    def test_interview_prepare_skip_shortcut(self) -> None:
        self.assertEqual(route_after_prepare({"skip_extraction": True}), "save_experience")
        self.assertEqual(route_after_prepare({"skip_extraction": False}), "extract_star")

    # --- 워크플로우 ③: 자소서 비평·퇴고·De-AI ---
    def test_cover_letter_stops_at_max_two_revisions(self) -> None:
        self.assertEqual(
            route_after_critic({"revision_count": 2, "critic_score": 60}),
            "de_ai_humanizer",
        )

    def test_cover_letter_stops_at_score_85(self) -> None:
        self.assertEqual(
            route_after_critic({"revision_count": 0, "critic_score": 85}),
            "de_ai_humanizer",
        )

    def test_cover_letter_refines_when_under_threshold(self) -> None:
        self.assertEqual(
            route_after_critic({"revision_count": 1, "critic_score": 78}),
            "refiner",
        )

    def test_anti_hallucination_rule_contains_mandatory_clause(self) -> None:
        self.assertIn("jasoseo_sample", ANTI_HALLUCINATION_RULE)
        self.assertIn("experience", ANTI_HALLUCINATION_RULE)

    # --- 워크플로우 ④: Corrective RAG 웹 검색 최대 1회 ---
    def test_copilot_allows_single_web_fallback(self) -> None:
        self.assertEqual(
            route_after_relevance({"is_sufficient": False, "web_search_count": 0}),
            "web_search_fallback",
        )

    def test_copilot_blocks_second_web_fallback(self) -> None:
        self.assertEqual(
            route_after_relevance({"is_sufficient": False, "web_search_count": 1}),
            "copilot_answer",
        )

    def test_copilot_skips_web_when_sufficient(self) -> None:
        self.assertEqual(
            route_after_relevance({"is_sufficient": True, "web_search_count": 0}),
            "copilot_answer",
        )


if __name__ == "__main__":
    unittest.main()
