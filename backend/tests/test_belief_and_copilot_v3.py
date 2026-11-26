"""개인 신념 카드(인간·사회·인문학적 커리어 가치관) · 자소서 1급 신념 연동 · 코파일럿 STAR-L 마스터리 동기화 단위 테스트."""

import unittest

from app.api.beliefs import evaluate_belief_pillar_quality
from app.core.star_rubric import compute_cumulative_portfolio_xp
from app.graphs.cover_letter_graph import build_refiner_messages
from app.schemas.agents import CoverLetterGenerateRequest, CoverLetterSaveRequest
from app.tools.copilot_tools import format_star_mastery_summary


class TestBeliefAndCopilotV3(unittest.TestCase):
    def test_belief_pillar_quality_diagnostics(self) -> None:
        # 1) Proven humanistic/social belief: clear human/social direction + linked project/experience
        proven = evaluate_belief_pillar_quality(
            title="기술은 사람을 대체하는 도구가 아니라 개인의 주체성을 확장해야 한다",
            tradeoff_rule="정보 격차로 기회를 놓치는 사람들이 스스로 결정할 수 있는 서비스를 만들고 싶다",
            origin_story="독서와 사용자 인터뷰를 통해 기술 접근성이 삶의 기회를 바꾼다는 확신을 얻었다.",
            linked_project_ids=[1],
            linked_experience_ids=[10],
        )
        self.assertEqual(proven["proof_status"], "proven")
        self.assertGreaterEqual(proven["strength_score"], 85)
        self.assertEqual(proven["proof_count"], 2)

        # 2) Needs proof: strong social calling, no linked project/experience yet
        needs_proof = evaluate_belief_pillar_quality(
            title="AI 시대일수록 고립된 개인을 공동체와 따뜻하게 연결하는 일을 하고 싶다",
            tradeoff_rule="단기 체류시간보다 사람 간의 신뢰와 회복을 돕는 제품을 지향한다",
            linked_project_ids=[],
            linked_experience_ids=[],
            linked_note_ids=[3],
        )
        self.assertEqual(needs_proof["proof_status"], "needs_proof")
        self.assertEqual(needs_proof["proof_count"], 1)

        # 3) Cliche risk: generic slogan with no human/social direction
        cliche = evaluate_belief_pillar_quality(
            title="끊임없이 성장하며 최선을 다하는 인재",
            tradeoff_rule="",
            linked_project_ids=[],
            linked_experience_ids=[],
        )
        self.assertEqual(cliche["proof_status"], "cliche_risk")
        self.assertTrue(len(cliche["cliche_hits"]) >= 1)

    def test_cover_letter_schemas_and_refiner_preserves_belief_and_company(self) -> None:
        gen_req = CoverLetterGenerateRequest(
            company_name="토스",
            question="본인의 가치관이 실제 프로젝트에 반영된 경험을 작성해 주세요.",
            selected_project_ids=[1],
            selected_belief_ids=[2, 3],
            selected_belief_note_ids=[5],
        )
        self.assertEqual(gen_req.selected_belief_ids, [2, 3])
        self.assertEqual(gen_req.selected_belief_note_ids, [5])

        save_req = CoverLetterSaveRequest(
            company_name="토스",
            question="가치관 경험",
            final_text="테스트 본문입니다.",
            used_beliefs=[{"kind": "pillar", "id": 2, "title": "기술은 개인의 주체성을 확장해야 한다"}],
        )
        self.assertEqual(len(save_req.used_beliefs), 1)

        msgs = build_refiner_messages(
            {
                "question": "가치관 경험",
                "char_limit": 800,
                "draft": "초안 본문",
                "critic_score": 76,
                "critic_feedback": "신념 연결을 보강하세요",
                "identity_docs": ["[선택 핵심 신념 카드 #2] 기술은 개인의 주체성을 확장해야 한다"],
                "company_docs": ["[저장된 기업 리서치] 토스 — 금융의 기회 평등"],
                "experience_docs": ["[선택 핵심 프로젝트 #1] write-on-vibe-lab"],
            }
        )
        joined = "\n".join(str(m.content) for m in msgs)
        self.assertIn("기술은 개인의 주체성을 확장해야 한다", joined)
        self.assertIn("금융의 기회 평등", joined)
        self.assertIn("write-on-vibe-lab", joined)

    def test_copilot_star_mastery_summary_replaces_legacy_character(self) -> None:
        projects = [
            {"id": 1, "name": "write-on-vibe-lab", "period": "2026", "project_types": ["engineering"], "is_portfolio_selected": True}
        ]
        experiences = [
            {
                "id": 10,
                "project_id": 1,
                "title": "비전공자 커리어 접근성 개선",
                "completeness_score": 82,
                "star_scores": {},
            }
        ]
        pillars = [
            {
                "id": 1,
                "title": "정보 격차로 기회를 놓치는 사람을 돕고 싶다",
                "category": "social_impact",
                "tradeoff_rule": "누구나 스스로 판단할 수 있는 투명한 도구를 만든다",
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
        self.assertIn("미실천 신념", summary)
        self.assertIn("정보 격차로 기회를 놓치는 사람을 돕고 싶다", summary)
        self.assertNotIn("6축 포트폴리오 캐릭터", summary)


if __name__ == "__main__":
    unittest.main()
