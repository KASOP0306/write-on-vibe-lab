"""온디맨드 GitHub PR·커밋 Diff 포맷터 및 필터링 단위 테스트."""

import unittest

from app.tools.github_analyzer import (
    format_github_changes_for_mining,
    is_ignored_diff_file,
)


class TestGitHubActivityDiff(unittest.TestCase):
    def test_ignore_noisy_diff_files(self):
        self.assertTrue(is_ignored_diff_file("frontend/package-lock.json"))
        self.assertTrue(is_ignored_diff_file("dist/assets/index-abc.js"))
        self.assertTrue(is_ignored_diff_file("public/logo.png"))
        self.assertFalse(is_ignored_diff_file("backend/app/core/star_rubric.py"))
        self.assertFalse(is_ignored_diff_file("frontend/src/pages/ExperienceMinerPage.jsx"))

    def test_format_github_changes_for_mining_filters_and_summarizes(self):
        prs = [
            {
                "number": 14,
                "title": "STAR-L 21지표 하이브리드 평가 도입",
                "state": "closed",
                "merged_at": "2026-11-26T10:00:00Z",
                "body": "관대화 편향을 막기 위해 21개 체크포인트와 Python 하드 캡을 도입했습니다.",
                "html_url": "https://github.com/owner/repo/pull/14",
                "files": [
                    {
                        "filename": "frontend/package-lock.json",
                        "status": "modified",
                        "additions": 900,
                        "deletions": 800,
                        "patch": "@@ noisy lockfile @@",
                    },
                    {
                        "filename": "backend/app/core/star_rubric.py",
                        "status": "modified",
                        "additions": 120,
                        "deletions": 40,
                        "patch": "@@ -1,3 +1,5 @@\n+def verify_and_score_checkpoints(): pass",
                    },
                ],
                "review_comments": [
                    {
                        "path": "backend/app/core/star_rubric.py",
                        "body": "R1 하드 캡에서 단위 없는 숫자도 구분하면 좋겠어요.",
                    }
                ],
            }
        ]
        commits = [
            {
                "sha": "5cf6926abcdef1234567",
                "commit": {"message": "feat: conservative question critic threshold 70"},
                "html_url": "https://github.com/owner/repo/commit/5cf6926",
                "files": [
                    {
                        "filename": "backend/app/core/question_critic.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 2,
                        "patch": "@@ -18 +18 @@\n-PASS_SCORE_THRESHOLD = 80\n+PASS_SCORE_THRESHOLD = 70",
                    }
                ],
            }
        ]

        out = format_github_changes_for_mining("owner", "repo", prs, commits)
        self.assertEqual(out["stats"]["pr_count"], 1)
        self.assertEqual(out["stats"]["commit_count"], 1)
        # package-lock.json은 무시되어 files_changed는 2개만 집계
        self.assertEqual(out["stats"]["files_changed"], 2)
        self.assertNotIn("package-lock.json", out["summary_markdown"])
        self.assertIn("PR #14", out["mining_prompt_notes"])
        self.assertIn("star_rubric.py", out["mining_prompt_notes"])
        self.assertIn("PASS_SCORE_THRESHOLD = 70", out["mining_prompt_notes"])
        self.assertIn("R1 하드 캡", out["mining_prompt_notes"])


if __name__ == "__main__":
    unittest.main()
