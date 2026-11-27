"""GitHub 토큰 인증 암호화, 슬러그 변환, 레포 URL 정규화 단위 테스트."""

import unittest

from app.api.github import _normalize_repo_key
from app.core.token_crypto import decrypt_secret, encrypt_secret, mask_token
from app.tools.github_analyzer import slugify_repo_name


class TestGitHubIntegration(unittest.TestCase):
    def test_token_encrypt_decrypt_roundtrip_and_tamper_detection(self) -> None:
        raw = "tok_test_11ABCDEFG_sampleSecretValue987654"
        enc = encrypt_secret(raw)
        self.assertTrue(enc.startswith("enc1:"))
        self.assertNotIn(raw, enc)
        self.assertEqual(decrypt_secret(enc), raw)

        # Tampered ciphertext must fail HMAC check and return empty string
        tampered = enc[:-2] + ("AA" if not enc.endswith("AA") else "BB")
        self.assertEqual(decrypt_secret(tampered), "")
        self.assertEqual(decrypt_secret(""), "")
        self.assertEqual(encrypt_secret(""), "")

    def test_mask_token(self) -> None:
        self.assertEqual(mask_token("tok_1234567890abcd"), "tok_****abcd")
        self.assertEqual(mask_token("short"), "*****")
        self.assertEqual(mask_token(""), "")

    def test_slugify_repo_name(self) -> None:
        self.assertEqual(slugify_repo_name("AI-Driven UX Optimizer!"), "ai-driven-ux-optimizer")
        self.assertEqual(slugify_repo_name("my_repo.v2"), "my_repo.v2")
        ko_slug = slugify_repo_name("인간 중심 커리어 플랫폼")
        self.assertTrue(ko_slug.startswith("career-project-"))
        self.assertGreaterEqual(len(ko_slug), 18)

    def test_normalize_repo_key(self) -> None:
        self.assertEqual(
            _normalize_repo_key("https://github.com/KASOP0306/write-on-vibe-lab.git"),
            "kasop0306/write-on-vibe-lab",
        )
        self.assertEqual(
            _normalize_repo_key("git@github.com:KASOP0306/write-on-vibe-lab.git"),
            "kasop0306/write-on-vibe-lab",
        )
        self.assertEqual(_normalize_repo_key(""), "")


if __name__ == "__main__":
    unittest.main()
