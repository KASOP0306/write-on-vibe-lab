"""모듈형 포트폴리오 워크스페이스 & GitHub URL 파서 & 문서 파서 단위 테스트.

실행 예시 (backend 컨테이너 내부):
    python -m unittest discover -s tests -v
"""

import json
import unittest

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

    # --- 결정론적 포트폴리오 Markdown 렌더러 ---
    def test_render_portfolio_markdown(self) -> None:
        md = render_portfolio_markdown(
            {
                "name": "Career AI Agent",
                "period": "2026.11",
                "role": "Fullstack",
                "summary": "개인화 커리어 에이전트",
                "tech_stack": ["FastAPI", "LangGraph"],
                "repo_url": "https://github.com/KASOP0306/write-on-vibe-lab",
            },
            [
                {
                    "id": 1,
                    "section_type": "overview",
                    "title": STANDARD_SECTIONS[0]["title"],
                    "content": "- 배경 및 문제 정의",
                    "display_order": 1,
                },
                {
                    "id": 2,
                    "section_type": "architecture",
                    "title": STANDARD_SECTIONS[1]["title"],
                    "content": "",
                    "display_order": 2,
                },
            ],
        )
        self.assertIn("# Career AI Agent", md)
        self.assertIn("## 1. 개요 & 문제 정의", md)
        self.assertNotIn("## 2. 시스템 아키텍처", md)


if __name__ == "__main__":
    unittest.main()
