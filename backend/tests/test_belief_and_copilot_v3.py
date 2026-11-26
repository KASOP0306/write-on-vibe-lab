"""개인 신념 카드(BeliefPillar) · 자소서 1급 신념 연동 · 코파일럿 STAR-L 마스터리 동기화 단위 테스트."""

import unittest

from app.api.beliefs import evaluate_belief_pillar_quality
from app.core.star_rubric import compute_cumulative_portfolio_xp
from app.graphs.cover_letter_graph import build_refiner_messages
from app.schemas.agents import CoverLetterGenerateRequest, CoverLetterSaveRequest
from app.tools.copilot_tools import format_star_mastery_summary


class TestBeliefAndCopilotV3(unittest.TestCase):
    def test_belief_pillar_quality_diagnostics(self) -> None:
        # 1) Proven belief: crisp trade-off + linked proof
        proven = evaluate_belief_pillar_quality(
            title="감에 의존하는 튜닝보다 측정 가능한 검증 루프를 먼저 만든다",
            tradeoff_rule="출시 속도와 채점 신뢰성이 충돌할 때 결정론적 검증 게이트를 우선한다",
            origin_story="LLM 평가 관대화 편향을 잡으며 골든셋 검증 체계를 도입했다.",
            linked_project_ids=[1],
            linked_experience_ids=[10],
        )
        self.assertEqual(proven["proof_status"], "proven")
        self.assertGreaterEqual(proven["strength_score"], 85)
        self.assertEqual(proven["proof_count"], 2)

        # 2) Needs proof: good trade-off, no linked project/experience
        needs_proof = evaluate_belief_pillar_quality(
            title="복잡한 추상화보다 팀이 바로 디버깅할 수 있는 단순한 구조를 우선한다",
            tradeoff_rule="코드 재사용성보다 장애 대응 속도를 우선한다",
            linked_project_ids=[],
            linked_experience_ids=[],
        )
        self.assertEqual(needs_proof["proof_status"], "needs_proof")
        self.assertEqual(needs_proof["proof_count"], 0)

        # 3) Cliche risk: generic slogan with no trade-off rule
        cliche = evaluate_belief_pillar_quality(
            title="끊임없이 성장하며 최선을 다하는 개발자",
            tradeoff_rule="",
            linked_project_ids=[],
            linked_experience_ids=[],
        )
        self.assertEqual(cliche["proof_status"], "cliche_risk")
        self.assertTrue(len(cliche["cliche_hits"]) >= 1)

    def test_cover_letter_schemas_and_refiner_preserves_belief_and_company(self) -> None:
        gen_req = CoverLetterGenerateRequest(
            company_name="토스",
            question="가장 도전적이었던 문제 해결 경험을 작성해 주세요.",
            selected_project_ids=[1],
            selected_belief_ids=[2, 3],
            selected_belief_note_ids=[5],
        )
        self.assertEqual(gen_req.selected_belief_ids, [2, 3])
        self.assertEqual(gen_req.selected_belief_note_ids, [5])

        save_req = CoverLetterSaveRequest(
            company_name="토스",
            question="문제 해결 경험",
            final_text="테스트 본문입니다.",
            used_beliefs=[{"kind": "pillar", "id": 2, "title": "측정 가능한 검증 우선"}],
        )
        self.assertEqual(len(save_req.used_beliefs), 1)

        # Verify refiner bug fix: both identity_docs and company_docs are passed to refiner prompt
        msgs = build_refiner_messages(
            {
                "question": "문제 해결 경험",
                "char_limit": 800,
                "draft": "초안 본문",
                "critic_score": 76,
                "critic_feedback": "신념 연결을 보강하세요",
                "identity_docs": ["[선택 핵심 신념 카드 #2] 측정 가능한 검증 루프 우선"],
                "company_docs": ["[저장된 기업 리서치] 토스 — 데이터 기반 의사결정"],
                "experience_docs": ["[선택 핵심 프로젝트 #1] write-on-vibe-lab"],
            }
        )
        joined = "\n".join(str(m.content) for m in msgs)
        self.assertIn("측정 가능한 검증 루프 우선", joined)
        self.assertIn("데이터 기반 의사결정", joined)
        self.assertIn("write-on-vibe-lab", joined)

    def test_copilot_star_mastery_summary_replaces_legacy_character(self) -> None:
        projects = [
            {"id": 1, "name": "write-on-vibe-lab", "period": "2026", "project_types": ["engineering"], "is_portfolio_selected": True}
        ]
        experiences = [
            {
                "id": 10,
                "project_id": 1,
                "title": "STAR-L 엄격 하이브리드 평가",
                "completeness_score": 82,
                "star_scores": {},
            }
        ]
        pillars = [
            {
                "id": 1,
                "title": "장애 복구 기준을 코드로 고정한다",
                "category": "work_principle",
                "tradeoff_rule": "속도보다 복구 가능성 우선",
                "linked_project_ids": [],
                "linked_experience_ids": [],
            }
        ]
        mastery = compute_cumulative_portfolio_xp(projects, experiences)
        summary = format_star_mastery_summary(mastery, pillars)

        self.assertIn("STAR-L 21지표 마스터리", summary)
        self.assertIn("/ 1000 XP", summary)
        self.assertIn("빈 대표 프로젝트 슬롯 3개", summary)
        self.assertIn("21지표 취약 체크포인트 TOP 5", summary)
        self.assertIn("[R1]", summary)
        self.assertIn("미증명 신념", summary)
        self.assertIn("장애 복구 기준을 코드로 고정한다", summary)
        self.assertNotIn("6축 포트폴리오 캐릭터", summary)


if __name__ == "__main__":
    unittest.main()
