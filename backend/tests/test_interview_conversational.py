"""대화형 멀티턴 경험 채굴(Active Interviewer v3.0) 라우팅 · GitHub Diff 앵커링 단위 테스트."""

import asyncio
import unittest

from app.graphs.interview_graph import (
    _build_context_text,
    _format_preferences_guide,
    _is_github_diff_text,
    prepare_turn,
    route_after_prepare,
)
from app.prompts import load_prompt
from app.schemas.agents import InterviewReplyRequest, InterviewStartRequest


class TestConversationalInterviewV3(unittest.TestCase):
    def test_prompts_load(self):
        for name in ("interview_intent", "interview_probe", "interview_coach"):
            txt = load_prompt(name)
            self.assertIn("<role>", txt)
            self.assertIn("<rules>", txt)

    def test_github_diff_detection_and_focus_context_preservation(self):
        diff_text = "[GitHub 실제 PR·커밋 코드 변경 이력 기반 경험 채굴]\n### GitHub 변경 이력 분석\n```diff\n+PASS_SCORE_THRESHOLD = 70\n```"
        self.assertTrue(_is_github_diff_text(diff_text))
        ctx = _build_context_text(
            {
                "focus_context": diff_text,
                "project_context": "프로젝트명: write-on-vibe-lab",
                "raw_notes": diff_text,
                "qa_history": [],
            }
        )
        self.assertIn("[집중 채굴 컨텍스트", ctx)
        self.assertIn("PASS_SCORE_THRESHOLD = 70", ctx)

    def test_replace_question_action_routes_without_polluting_qa_history(self):
        state = {
            "star": {"title": "검색 성능 개선"},
            "questions": ["협업은 어떻게 했나요?", "정량 수치는 무엇인가요?"],
            "qa_history": [{"questions": ["초기 질문"], "answer": "Redis 캐시 도입"}],
            "chat_messages": [],
            "rejected_questions": [],
            "turn_action": "replace_question",
            "replace_question_index": 0,
            "latest_reply": "",
        }
        updated = asyncio.run(prepare_turn(state))
        self.assertEqual(updated["turn_intent"], "replace_question")
        self.assertEqual(route_after_prepare(updated), "generate_questions")
        # qa_history는 오염되지 않고 그대로 1건 유지되어야 함
        self.assertEqual(len(updated["qa_history"]), 1)
        # 거절된 질문이 rejected_questions에 누적되어야 함
        self.assertIn("협업은 어떻게 했나요?", updated["rejected_questions"])

    def test_ask_coach_routing_and_preferences_format(self):
        self.assertEqual(route_after_prepare({"turn_intent": "ask_coach"}), "coach_reply")
        self.assertEqual(route_after_prepare({"turn_intent": "save"}), "save_experience")
        self.assertEqual(route_after_prepare({"turn_intent": "answer"}), "extract_star")

        guide = _format_preferences_guide(
            {
                "focus_instruction": "PR #14 star_rubric.py 하드캡 위주",
                "excluded_checkpoints": ["A6"],
                "question_count": 1,
            }
        )
        self.assertIn("PR #14", guide)
        self.assertIn("A6", guide)
        self.assertIn("1개", guide)

    def test_start_and_reply_schemas(self):
        start_req = InterviewStartRequest(focus_context="PR #14 diff content here", raw_notes="")
        self.assertTrue(start_req.focus_context)
        reply_req = InterviewReplyRequest(
            thread_id="exp-1234",
            action="replace_question",
            replace_question_index=1,
        )
        self.assertEqual(reply_req.action, "replace_question")
        self.assertEqual(reply_req.replace_question_index, 1)


if __name__ == "__main__":
    unittest.main()
