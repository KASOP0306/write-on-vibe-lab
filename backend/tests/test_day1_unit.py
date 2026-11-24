"""Day 1 코어 모듈 단위 테스트 (외부 AWS/DB 의존성 없이 실행 가능).

실행 예시 (컨테이너 내부):
    python -m unittest discover -s tests -v
"""

import unittest

from app.core.vector_store import DocType, validate_doc_types
from app.seeds.seed_jasoseo import format_sample_content, load_jasoseo_samples


class TestDay1Core(unittest.TestCase):
    def test_validate_doc_types_accepts_valid_values(self) -> None:
        result = validate_doc_types(["experience", DocType.CAREER_IDENTITY])
        self.assertEqual(result, ["experience", "career_identity"])

    def test_validate_doc_types_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            validate_doc_types([])

    def test_validate_doc_types_rejects_unknown_type(self) -> None:
        with self.assertRaises(ValueError):
            validate_doc_types(["unknown_type"])

    def test_jasoseo_samples_loader_and_formatter(self) -> None:
        samples, source = load_jasoseo_samples()
        self.assertIn(source, {"local", "default_template"})
        self.assertGreaterEqual(len(samples), 1)
        for sample in samples:
            self.assertIn("role_category", sample)
            self.assertIn("question_type", sample)
            self.assertIn("sample_text", sample)
            formatted = format_sample_content(sample)
            self.assertIn("[참고 원문]", formatted)


if __name__ == "__main__":
    unittest.main()
