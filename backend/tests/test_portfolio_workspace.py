"""모듈형 포트폴리오 워크스페이스 & GitHub URL 파서 & 문서 파서 단위 테스트.

실행 예시 (backend 컨테이너 내부):
    python -m unittest discover -s tests -v
"""

import json
import unittest

from app.core.bedrock import _repair_truncated_json
from app.core.project_templates import (
    compose_sections_for_types,
    get_templates_payload,
    infer_track_for_section_type,
    normalize_project_types,
)
from app.core.star_rubric import (
    compute_average_star_axes,
    compute_portfolio_overall_score,
    compute_weighted_star_score,
    get_calibration_tier,
    get_rubric_reference_payload,
    normalize_star_scores,
)
from app.tools.document_parser import DocumentParseError, parse_uploaded_file
from app.tools.github_analyzer import GitHubAnalyzerError, parse_github_url
from app.tools.portfolio_manager import STANDARD_SECTIONS, render_portfolio_markdown


class TestPortfolioWorkspace(unittest.TestCase):
    # --- GitHub URL 파싱 엣지 케이스 ---
    def test_parse_github_url_variants(self) -> None:
        cases = [
            ("https://github.com/KASOP0306/write-on-vibe-lab", ("KASOP0306", "write-on-vibe-lab")),
            ("https://github.com/KASOP0306/write-on-vibe-lab.git", ("KASOP0306", "write-on-vibe-lab")),
            ("https://github.com/KASOP0306/write-on-vibe-lab?tab=readme-ov-file#top", ("KASOP0306", "write-on-vibe-lab")),
            ("https://GitHub.com/KASOP0306/write-on-vibe-lab/tree/main/backend", ("KASOP0306", "write-on-vibe-lab")),
            ("git@github.com:KASOP0306/write-on-vibe-lab.git", ("KASOP0306", "write-on-vibe-lab")),
            ("KASOP0306/write-on-vibe-lab", ("KASOP0306", "write-on-vibe-lab")),
        ]
        for raw, expected in cases:
            self.assertEqual(parse_github_url(raw), expected, f"Failed on {raw}")

    def test_parse_github_url_rejects_invalid(self) -> None:
        for bad in ("", "https://gitlab.com/a/b", "https://github.com/onlyowner"):
            with self.assertRaises(GitHubAnalyzerError):
                parse_github_url(bad)

    # --- 문서 파서 테스트 ---
    def test_parse_markdown_and_ipynb(self) -> None:
        md = parse_uploaded_file("retro.md", "# 제목\n트러블슈팅 정리 내용입니다.".encode("utf-8"))
        self.assertEqual(md["file_format"], "md")
        self.assertIn("트러블슈팅", md["text"])

        nb_bytes = json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": ["# 실험 노트\n", "모델 비교"]},
                    {"cell_type": "code", "source": ["print('ok')"]},
                ]
            }
        ).encode("utf-8")
        nb = parse_uploaded_file("exp.ipynb", nb_bytes)
        self.assertEqual(nb["file_format"], "ipynb")
        self.assertIn("실험 노트", nb["text"])
        self.assertIn("print('ok')", nb["text"])

    def test_parse_rejects_unsupported_extension(self) -> None:
        with self.assertRaises(DocumentParseError):
            parse_uploaded_file("malware.exe", b"binary payload data")

    # --- 조합형 멀티트랙 템플릿 레지스트리 테스트 ---
    def test_normalize_project_types(self) -> None:
        self.assertEqual(normalize_project_types(None), ["engineering"])
        self.assertEqual(normalize_project_types([]), ["engineering"])
        self.assertEqual(normalize_project_types(["invalid_track"]), ["engineering"])
        self.assertEqual(
            normalize_project_types(["product_planning", "engineering", "product_planning", "unknown"]),
            ["product_planning", "engineering"],
        )

    def test_compose_sections_multi_track_no_duplication(self) -> None:
        composed = compose_sections_for_types(["product_planning", "engineering"])
        section_types = [s["section_type"] for s in composed]

        # 공통 코어(overview/outcomes)는 각 1회씩, 시작과 끝에 배치
        self.assertEqual(section_types[0], "overview")
        self.assertEqual(section_types[-1], "outcomes")
        self.assertEqual(section_types.count("overview"), 1)
        self.assertEqual(section_types.count("outcomes"), 1)

        # 기획 4개 + 개발 4개 + 공통 2개 = 총 10개, 중복 없음
        self.assertEqual(len(section_types), 10)
        self.assertEqual(len(set(section_types)), 10)
        self.assertIn("research_insights", section_types)
        self.assertIn("architecture", section_types)
        self.assertEqual(infer_track_for_section_type("research_insights"), "product_planning")
        self.assertEqual(infer_track_for_section_type("architecture"), "engineering")
        self.assertEqual(infer_track_for_section_type("custom_xyz"), "custom")

    def test_templates_payload_structure(self) -> None:
        payload = get_templates_payload()
        self.assertEqual(len(payload["core_sections"]), 2)
        self.assertEqual(len(payload["tracks"]), 5)
        track_ids = [t["id"] for t in payload["tracks"]]
        self.assertEqual(
            track_ids,
            ["engineering", "product_planning", "data_research", "operations_leadership", "general"],
        )

    # --- 결정론적 포트폴리오 Markdown 렌더러 ---
    def test_render_portfolio_markdown(self) -> None:
        md = render_portfolio_markdown(
            {
                "name": "Career AI Agent",
                "project_types": ["product_planning", "engineering"],
                "period": "2026.11",
                "role": "PM & Fullstack",
                "summary": "개인화 커리어 에이전트",
                "tech_stack": ["Figma", "FastAPI", "LangGraph"],
                "repo_url": "https://github.com/KASOP0306/write-on-vibe-lab",
                "artifact_links": [{"label": "Figma 와이어프레임", "url": "https://figma.com/file/demo"}],
            },
            [
                {
                    "id": 1,
                    "section_type": "overview",
                    "track": "core",
                    "title": STANDARD_SECTIONS[0]["title"],
                    "content": "- 배경 및 문제 정의",
                    "display_order": 10,
                },
                {
                    "id": 2,
                    "section_type": "architecture",
                    "track": "engineering",
                    "title": STANDARD_SECTIONS[1]["title"],
                    "content": "",
                    "display_order": 110,
                },
                {
                    "id": 3,
                    "section_type": "research_insights",
                    "track": "product_planning",
                    "title": "리서치 & 고객·시장 인사이트",
                    "content": "- 취준생 15명 심층 인터뷰",
                    "display_order": 210,
                },
            ],
        )
        self.assertIn("# Career AI Agent", md)
        self.assertIn("기획 · PM · 전략 · 개발 · 엔지니어링", md)
        self.assertIn("[Figma 와이어프레임](https://figma.com/file/demo)", md)
        self.assertIn("## 개요 & 문제 정의", md)
        self.assertIn("## [기획·PM] 리서치 & 고객·시장 인사이트", md)
        self.assertNotIn("시스템 아키텍처", md)

    def test_repair_truncated_json(self) -> None:
        truncated = '{"name": "demo", "items": [{"title": "a", "metrics": ""}'
        repaired = _repair_truncated_json(truncated)
        parsed = json.loads(repaired)
        self.assertEqual(parsed["name"], "demo")
        self.assertEqual(len(parsed["items"]), 1)

    # --- 5축 STAR-L BARS & 6축 포트폴리오 루브릭 단위 테스트 ---
    def test_star_rubric_weighted_math_and_normalization(self) -> None:
        axes = {
            "situation": {"level": 4, "score": 80},
            "task": {"level": 3, "score": 60},
            "action": {"level": 5, "score": 100},
            "result": {"level": 2, "score": 40},
            "learning": {"level": 4, "score": 80},
        }
        # 80*0.15 + 60*0.15 + 100*0.35 + 40*0.25 + 80*0.10 = 12 + 9 + 35 + 10 + 8 = 74
        self.assertEqual(compute_weighted_star_score(axes), 74)
        self.assertEqual(normalize_star_scores({}), {})
        norm = normalize_star_scores({"axes": axes})
        self.assertEqual(norm["weighted_score"], 74)

        avg = compute_average_star_axes([{"star_scores": norm}, {"star_scores": {}}])
        self.assertEqual(avg["evaluated_count"], 1)
        self.assertEqual(avg["total_count"], 2)
        self.assertEqual(avg["weighted_score"], 74)

    def test_portfolio_6_axis_score_and_reference(self) -> None:
        scores = compute_portfolio_overall_score(
            {
                "problem_depth": {"score": 90},
                "evidence_impact": {"score": 80},
                "narrative_coherence": {"score": 70},
                "time_execution": {"score": 60},
                "people_collaboration": {"score": 30},
                "adaptability_growth": {"score": 60},
            }
        )
        self.assertEqual(scores["internal_score"], 80)
        self.assertEqual(scores["external_score"], 50)
        self.assertEqual(scores["overall_score"], 65)

        ref = get_rubric_reference_payload()
        self.assertEqual(len(ref["star_rubric"]["axes"]), 5)
        self.assertEqual(len(ref["portfolio_rubric"]["axes"]), 6)
        self.assertEqual(len(ref["calibration_tiers"]), 5)
        self.assertEqual(len(ref["probing_techniques"]), 5)
        # 모든 STAR-L 축이 1~5 전 레벨 앵커 보유 확인
        for ax in ref["star_rubric"]["axes"]:
            self.assertEqual(set(ax["bars"].keys()), {"1", "2", "3", "4", "5"})
        self.assertEqual(get_calibration_tier(92)["grade"], "S")
        self.assertEqual(get_calibration_tier(82)["grade"], "A")
        self.assertEqual(get_calibration_tier(70)["grade"], "B")
        self.assertEqual(get_calibration_tier(50)["grade"], "C")
        self.assertEqual(get_calibration_tier(30)["grade"], "D")
        internal = [a for a in ref["portfolio_rubric"]["axes"] if a["domain"] == "internal"]
        external = [a for a in ref["portfolio_rubric"]["axes"] if a["domain"] == "external"]
        self.assertEqual(len(internal), 3)
        self.assertEqual(len(external), 3)


if __name__ == "__main__":
    unittest.main()
