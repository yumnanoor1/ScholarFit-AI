import unittest

from app.models.scholarship_knowledge import ScholarshipSourceDocument
from app.services.scholarship_discovery import _normalize_url
from app.services.source_url_safety import (
    UnsafeSourceURL,
    safe_source_url,
    safe_source_urls_in_text,
    validate_source_url,
)


class SourceURLSafetyTests(unittest.TestCase):
    def test_https_url_preserves_safe_query_parameters(self):
        url = "https://official.example/document?language=en&page=2"
        self.assertEqual(validate_source_url(url), url)
        self.assertEqual(safe_source_url(url), url)

    def test_http_url_is_allowed(self):
        url = "http://official.example/document"
        self.assertEqual(validate_source_url(url), url)
        self.assertEqual(safe_source_url(url), url)

    def test_sensitive_query_parameters_are_removed(self):
        url = (
            "https://official.example/document?language=en&api_key=secret"
            "&X-Amz-Signature=signature&access_token=token"
        )
        self.assertEqual(
            safe_source_url(url),
            "https://official.example/document?language=en",
        )

    def test_fragment_is_removed(self):
        self.assertEqual(
            safe_source_url("https://official.example/document?language=en#section-2"),
            "https://official.example/document?language=en",
        )

    def test_free_text_urls_are_sanitized_without_redacting_prose_or_emails(self):
        text = (
            "See https://student:secret@official.example/path?token=hidden&lang=en#part, "
            "ftp://files.example/archive, //private.example/resource?api_key=hidden, "
            "and https://official.example/page?language=en. "
            "Contact awards@example.org; ordinary prose stays unchanged."
        )

        sanitized = safe_source_urls_in_text(text)

        self.assertIn("[redacted invalid source URL],", sanitized)
        self.assertIn("[redacted invalid source URL]", sanitized)
        self.assertIn("https://official.example/page?language=en.", sanitized)
        self.assertIn("awards@example.org", sanitized)
        self.assertIn("ordinary prose stays unchanged.", sanitized)
        for secret in ("student", "secret", "token=hidden", "api_key=hidden", "private.example"):
            self.assertNotIn(secret, sanitized)

    def test_opaque_unsupported_scheme_urls_are_redacted(self):
        sanitized = safe_source_urls_in_text(
            "Do not open javascript:alert(1) or data:text/plain,private."
        )

        self.assertNotIn("javascript:", sanitized)
        self.assertNotIn("alert(1)", sanitized)
        self.assertNotIn("data:text", sanitized)
        self.assertIn("[redacted invalid source URL]", sanitized)

    def test_bare_domains_are_redacted_with_paths_queries_and_fragments(self):
        examples = (
            "www.example.com",
            "example.com",
            "example.com/path",
            "example.com/path?token=example-token",
            "example.com?lang=en&api_key=example-key#private",
            "example.com#fragment",
            "example.xyz/path?token=example-token",
            "www.example.xyz",
            "example.com/path?token=(example-token)",
        )
        for url in examples:
            with self.subTest(url=url):
                self.assertEqual(safe_source_urls_in_text(f"See {url}."), "See [redacted URL].")

    def test_multiple_bare_domains_preserve_surrounding_punctuation(self):
        text = (
            "See (www.example.com), example.com/path?token=example-token; "
            "also [example.org#fragment]! Is example.net useful?"
        )
        self.assertEqual(
            safe_source_urls_in_text(text),
            "See ([redacted URL]), [redacted URL]; also [[redacted URL]]! Is [redacted URL] useful?",
        )

    def test_bare_domain_detection_preserves_emails_versions_and_filenames(self):
        text = (
            "Contact user@example.com or first.last+tag@sub.example.org. "
            "Use Python 3.11.9, v1.2.3, 10.1 and 192.168.1.1. "
            "Read report.pdf, archive.tar.gz, main.py and notes.txt. "
            "Ordinary words like alpha.beta remain."
        )
        self.assertEqual(safe_source_urls_in_text(text), text)

    def test_combined_url_sanitization_is_idempotent(self):
        text = (
            "See example.com/path?token=example-token, "
            "https://official.example/page?lang=en&token=example-token#fragment, "
            "ftp://files.example/archive and //private.example/path."
        )
        sanitized = safe_source_urls_in_text(text)
        self.assertEqual(
            sanitized,
            "See [redacted URL], https://official.example/page?lang=en, "
            "[redacted invalid source URL] and [redacted invalid source URL].",
        )
        self.assertEqual(safe_source_urls_in_text(sanitized), sanitized)

    def test_urls_with_username_or_password_are_rejected_without_echoing_them(self):
        for url in (
            "https://student:secret@official.example/document",
            "https://student@official.example/document",
        ):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeSourceURL) as error:
                    validate_source_url(url)
                self.assertNotIn("student", str(error.exception))
                self.assertNotIn("secret", str(error.exception))
                self.assertIsNone(safe_source_url(url))

    def test_malformed_and_non_http_urls_are_unavailable(self):
        for url in (
            "not a url",
            "ftp://official.example/document",
            "https://[invalid",
            "https://official.example:secret/document?token=hidden",
        ):
            with self.subTest(url=url):
                with self.assertRaises(UnsafeSourceURL) as error:
                    validate_source_url(url)
                self.assertIsNone(error.exception.__cause__)
                self.assertNotIn("secret", str(error.exception))
                self.assertNotIn("hidden", str(error.exception))
                self.assertIsNone(safe_source_url(url))

    def test_source_document_creation_rejects_credentialed_urls(self):
        with self.assertRaises(UnsafeSourceURL):
            ScholarshipSourceDocument(
                scholarship_id=1,
                source_url="https://student:secret@official.example/document",
                normalized_url="https://official.example/document",
                source_role="official_information",
            )

    def test_discovery_normalization_rejects_credentialed_urls_without_echoing_them(self):
        with self.assertRaises(UnsafeSourceURL) as error:
            _normalize_url("https://student:secret@official.example/document")
        self.assertNotIn("student", str(error.exception))
        self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
