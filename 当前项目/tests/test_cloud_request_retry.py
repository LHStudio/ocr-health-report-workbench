from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import local_service  # noqa: E402


class CloudRequestRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.source = Path(self.tempdir.name) / "page.pdf"
        self.source.write_bytes(b"fixture-pdf")
        self.state = {"processing_mode": "fast", "message": ""}

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_ssl_eof_is_retried_with_a_fresh_upload(self) -> None:
        success = Mock(status_code=200)
        uploaded_payloads: list[bytes] = []

        def post_side_effect(*_args, **kwargs):
            uploaded_payloads.append(kwargs["files"]["file"][1].read())
            if len(uploaded_payloads) == 1:
                raise local_service.requests.exceptions.SSLError("EOF")
            return success

        with patch(
            "local_service.requests.post",
            side_effect=post_side_effect,
        ) as post, patch("local_service.time.sleep") as sleep:
            response = local_service.request_cloud_ocr(
                self.state,
                "https://cloud.example:8443",
                self.source,
                document_kind="nutrition",
                page_index=2,
            )

        self.assertIs(response, success)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(sleep.call_args.args, (2,))
        self.assertIn("第 2/4 次", self.state["message"])
        self.assertEqual(uploaded_payloads, [b"fixture-pdf", b"fixture-pdf"])

    def test_transient_http_response_is_retried(self) -> None:
        unavailable = Mock(status_code=503)
        success = Mock(status_code=200)
        with patch("local_service.requests.post", side_effect=[unavailable, success]) as post, patch("local_service.time.sleep"):
            response = local_service.request_cloud_ocr(
                self.state,
                "https://cloud.example",
                self.source,
                document_kind="medical",
                page_index=1,
            )

        self.assertIs(response, success)
        self.assertEqual(post.call_count, 2)

    def test_reports_actionable_error_after_last_connection_failure(self) -> None:
        with patch(
            "local_service.requests.post",
            side_effect=local_service.requests.exceptions.ConnectionError("connection reset"),
        ), patch("local_service.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "连续 4 次未能连接云端 OCR"):
                local_service.request_cloud_ocr(
                    self.state,
                    "https://cloud.example",
                    self.source,
                    document_kind="nutrition",
                    page_index=1,
                )


if __name__ == "__main__":
    unittest.main()
