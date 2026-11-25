"""LangChain · LangGraph · RAG 4-Phase 고도화 단위 테스트."""

import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.bedrock import extract_llm_telemetry, llm_telemetry_scope
from app.core.chunker import build_source_label, split_into_chunks
from app.core.vector_store import (
    VectorSearchHit,
    compute_bm25_scores,
    format_hits_with_citations,
    mmr_rerank,
    reciprocal_rank_fusion,
    tokenize_korean_2gram,
)
from app.graphs.copilot_agent_graph import (
    MAX_TOOL_CALLS_PER_TURN,
    route_after_model,
    route_after_tools,
    safe_trim_agent_messages,
)
from app.graphs.cover_letter_graph import validate_cover_letter_post_checks
from app.prompts import build_chat_prompt, load_prompt
from app.tools.copilot_tools import COPILOT_TOOLS, _contains_blocked_pii
from eval.run_eval import build_byoi_jsonl_line, load_golden_dataset


class LangChainUpgradeUnitTests(unittest.TestCase):
    def test_external_prompts_and_chat_template(self):
        required_prompts = [
            "interview_extract",
            "interview_probe",
            "cover_letter_draft",
            "cover_letter_critic",
            "cover_letter_refiner",
            "cover_letter_humanizer",
            "query_rewrite",
            "hyde_generate",
            "copilot_agent_system",
        ]
        for name in required_prompts:
            text = load_prompt(name)
            self.assertIn("<role>", text, f"{name} missing <role>")
            self.assertIn("<rules>", text, f"{name} missing <rules>")
            self.assertIn("<output_format>", text, f"{name} missing <output_format>")

        msgs = build_chat_prompt(
            "interview_extract",
            "메모: {memo}",
            human_vars={"memo": "Redis 락 적용"},
        )
        self.assertEqual(len(msgs), 2)
        self.assertIn("STAR-L", msgs[0].content)
        self.assertIn("Redis 락 적용", msgs[1].content)

    def test_llm_telemetry_extraction_and_truncation_flag(self):
        fake_msg = AIMessage(
            content="partial response",
            usage_metadata={"input_tokens": 120, "output_tokens": 2048, "total_tokens": 2168},
            response_metadata={
                "stopReason": "max_tokens",
                "metrics": {"latencyMs": [845]},
            },
        )
        with llm_telemetry_scope("unit_test_scope") as tracker:
            rec = extract_llm_telemetry(
                fake_msg, model_id="amazon.nova-lite-v1:0", caller="test_node", elapsed_ms=900
            )
            self.assertTrue(rec.truncated)
            self.assertEqual(rec.input_tokens, 120)
            self.assertEqual(rec.output_tokens, 2048)
            self.assertEqual(rec.latency_ms, 845)
            summary = tracker.summary()
            self.assertEqual(summary["call_count"], 1)
            self.assertEqual(summary["total_tokens"], 2168)
            self.assertEqual(summary["truncated_callers"], ["test_node"])

    def test_cover_letter_post_checks(self):
        exp = ["P99 응답시간을 1420ms에서 185ms로 87% 단축했습니다."]
        sample = ["샘플에서는 트래픽 처리량을 350% 높이고 비용을 42% 절감했습니다."]

        bad_text = "결론적으로 한 단계 성장했습니다. 비용을 42% 절감했습니다."
        warnings = validate_cover_letter_post_checks(bad_text, exp, sample)
        self.assertTrue(any("AI 상투어" in w for w in warnings))
        self.assertTrue(any("42%" in w for w in warnings))

        clean_text = "Redis Lua 락과 Outbox 패턴으로 P99 지연시간을 185ms로 87% 줄였습니다."
        self.assertEqual(validate_cover_letter_post_checks(clean_text, exp, sample), [])

    def test_parent_child_chunker_short_and_long(self):
        short_chunks = split_into_chunks(
            "짧은 프로젝트 요약입니다.",
            doc_type="experience",
            ref_id="exp-1",
            metadata={"title": "짧은 경험"},
        )
        self.assertEqual(len(short_chunks), 1)
        self.assertEqual(short_chunks[0].ref_id, "exp-1")
        self.assertEqual(short_chunks[0].parent_ref_id, "exp-1")

        long_md = (
            "# 개요\n" + ("백엔드 정산 시스템 장애 분석 및 설계 내용입니다. " * 25) + "\n\n"
            "## 트러블슈팅\n" + ("Redis Lua 스크립트와 Outbox 패턴으로 중복 정산을 0%로 막았습니다. " * 25)
        )
        long_chunks = split_into_chunks(
            long_md,
            doc_type="experience",
            ref_id="proj-10-sec-3",
            metadata={"project_name": "PayGuard", "section_title": "아키텍처"},
        )
        self.assertGreater(len(long_chunks), 1)
        self.assertTrue(all(c.parent_ref_id == "proj-10-sec-3" for c in long_chunks))
        self.assertTrue(all("::c" in c.ref_id for c in long_chunks))
        self.assertIn("PayGuard", long_chunks[0].source_label)

    def test_korean_2gram_bm25_rrf_and_mmr(self):
        toks_a = set(tokenize_korean_2gram("수강신청 기간과 Redis 185ms"))
        toks_b = set(tokenize_korean_2gram("수강 신청 일정"))
        self.assertTrue({"수강", "신청"}.issubset(toks_a & toks_b))
        self.assertIn("redis", toks_a)
        self.assertIn("185ms", toks_a)

        bm25 = compute_bm25_scores(
            "Redis 분산 락 중복 정산",
            [
                ("d1", "Redis Lua 스크립트 분산 락으로 중복 정산을 해결했습니다."),
                ("d2", "프론트엔드 CSS 버튼 색상 디자인 가이드입니다."),
            ],
        )
        self.assertGreater(bm25["d1"], bm25["d2"])

        rrf = reciprocal_rank_fusion(["d2", "d1"], ["d1", "d3"], k=60)
        self.assertGreater(rrf["d1"], rrf["d2"])
        self.assertGreater(rrf["d1"], rrf["d3"])

        # MMR: d1과 d2가 거의 동일한 벡터일 때 d1 다음으로 다양한 d3을 선택해야 함
        h1 = VectorSearchHit(1, "experience", "p1::c0", "A", {}, 0.1, 0.9, source_label="P1")
        h2 = VectorSearchHit(2, "experience", "p1::c1", "A2", {}, 0.12, 0.88, source_label="P1")
        h3 = VectorSearchHit(3, "experience", "p2::c0", "B", {}, 0.2, 0.8, source_label="P2")
        picked = mmr_rerank(
            [1.0, 0.0, 0.0],
            [
                (h1, [0.99, 0.10, 0.0]),
                (h2, [0.98, 0.11, 0.0]),
                (h3, [0.75, 0.0, 0.66]),
            ],
            top_k=2,
            lambda_mult=0.5,
        )
        self.assertEqual([h.id for h in picked], [1, 3])
        self.assertIn("[출처: P1", format_hits_with_citations(picked))

    def test_golden_dataset_and_byoi_jsonl(self):
        ds = load_golden_dataset()
        self.assertEqual(len(ds["questions"]), 15)
        cats = {q["category"] for q in ds["questions"]}
        self.assertEqual(
            cats,
            {"fact_lookup", "metric_verify", "disambiguate", "condition_apply", "out_of_scope"},
        )
        line = build_byoi_jsonl_line(
            question="질문",
            reference_answer="정답",
            generated_answer="생성답",
            passages=[{"name": "출처1", "text": "조각1"}],
            model_identifier="amazon.nova-lite-v1:0",
            kb_identifier="rag-v2",
        )
        turn = line["conversationTurns"][0]
        self.assertEqual(turn["prompt"]["content"][0]["text"], "질문")
        self.assertEqual(turn["output"]["retrievedPassages"]["retrievalResults"][0]["name"], "출처1")

    def test_copilot_agent_tools_pii_trim_and_routers(self):
        self.assertEqual(len(COPILOT_TOOLS), 6)
        self.assertTrue(_contains_blocked_pii("내 비밀번호는 1234야"))
        self.assertTrue(_contains_blocked_pii("연락처 010-1234-5678"))
        self.assertFalse(_contains_blocked_pii("주말에 10시간 투자 가능하고 Python 백엔드 집중"))

        msgs = [
            HumanMessage(content="1번 질문"),
            AIMessage(content="1번 답"),
            HumanMessage(content="2번 질문"),
            AIMessage(content="", tool_calls=[{"name": "recall_career_memory", "args": {"query": "제약"}, "id": "c1"}]),
            ToolMessage(content="주 10시간", tool_call_id="c1", name="recall_career_memory"),
            AIMessage(content="2번 답"),
        ]
        trimmed = safe_trim_agent_messages(msgs, max_messages=4)
        self.assertIsInstance(trimmed[0], HumanMessage)
        self.assertEqual(trimmed[0].content, "2번 질문")

        ai_with_tool = AIMessage(
            content="",
            tool_calls=[{"name": "get_company_research", "args": {}, "id": "t1"}],
        )
        self.assertEqual(route_after_model({"messages": [ai_with_tool]}), "tools")
        self.assertEqual(route_after_model({"messages": [AIMessage(content="끝")]}), "__end__")
        self.assertEqual(route_after_tools({"tool_count": MAX_TOOL_CALLS_PER_TURN - 1}), "model")
        self.assertEqual(route_after_tools({"tool_count": MAX_TOOL_CALLS_PER_TURN}), "stop")


if __name__ == "__main__":
    unittest.main()
